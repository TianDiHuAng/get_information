"""规则兜底结构化：没有 LLM 时，用词表给条目打分类/标签/主体。

背景：`structure_items()` 在无 LLM 时直接跳过，导致 structures 表为空，
主题页/标签页/主体页全空。求职演示站需要在不花钱、不配 key 的前提下把这些板块填满。

做法：用行业包 taxonomy.yaml 的词表（categories/tags/entities）对
标题 + 摘要 + 正文做关键词匹配。这是确定性的、可解释的——命中什么词就打什么标，
不编造、不调模型。质量不如 LLM，但足以让主题导航可用。

用法：
  python -m collector.rule_structure --db data/aidd.db --data data-aidd --day 2026-11-23
  （通常不需要手动跑：tools/fill_structure.py 会调用它）

写入 structures 表，字段 model='rule-keyword'，便于和 LLM 结果区分、日后覆盖。
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _taxonomy() -> dict:
    """优先读行业包 taxonomy，退回 config。"""
    try:
        from . import industry
        p = industry.pack_path("taxonomy.yaml")
        if p and Path(p).is_file():
            import yaml
            return yaml.safe_load(Path(p).read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    import yaml
    p = ROOT / "config" / "taxonomy.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _match(text: str, keywords: list[str]) -> bool:
    """中文子串 / 英文全词匹配。"""
    t = text.lower()
    for kw in keywords:
        kw = str(kw).strip().lower()
        if not kw:
            continue
        if re.search(r"[a-z0-9]", kw):
            # 英文/数字用边界匹配
            if re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", t):
                return True
        elif kw in t:
            return True
    return False


# 英文关键词兜底：taxonomy 的 label/desc/tags 是中文，匹配不了 arXiv 等英文源标题。
# 这里给每个分类配一组英文信号词，只做「归类」，不编造内容。
_EN_CATEGORY = {
    "research_paper": ["paper", "arxiv", "biorxiv", "preprint", "dataset", "benchmark",
                       "study", "analysis", "network", "graph", "model", "learning"],
    "clinical_data": ["clinical", "trial", "patient", "efficacy", "safety", "phase ii",
                      "phase iii", "endpoint", "cohort"],
    "pipeline_progress": ["candidate", "preclinical", "pipeline", "milestone", "ind ",
                          "filing", "approval", "program"],
    "platform_release": ["launch", "release", "platform", "engine", "version", "api"],
}
_EN_TAG = {
    "大语言模型": ["llm", "large language model", "gpt", "foundation model"],
    "分子对接": ["docking", "molecular docking"],
    "虚拟筛选": ["virtual screening", "screening"],
    "强化学习": ["reinforcement learning", "rl "],
    "图神经网络": ["graph neural", "gnn"],
    "生成模型": ["generative", "diffusion", "generative model"],
    "知识图谱": ["knowledge graph"],
    "ADMET": ["admet"],
}

def build_rules(tax: dict) -> tuple[list[tuple[str, list[str]]], list[tuple[str, list[str]]], dict[str, list[str]]]:
    """从 taxonomy 抽出 (category, 词), (tag, 词), entity→别名 三套规则（含英文兜底）。"""
    cats: list[tuple[str, list[str]]] = []
    for cid, meta in (tax.get("categories") or {}).items():
        words = [str(cid)]
        if isinstance(meta, dict):
            words += [str(meta.get("label", "")), str(meta.get("desc", ""))]
            words += [str(x) for x in (meta.get("keywords") or meta.get("aliases") or [])]
        words += _EN_CATEGORY.get(str(cid), [])
        cats.append((str(cid), [w for w in words if w]))

    tags: list[tuple[str, list[str]]] = []
    for tag in tax.get("tags") or []:
        if isinstance(tag, str):
            name = tag
            words = [tag]
        elif isinstance(tag, dict):
            name = str(tag.get("label") or tag.get("name") or "")
            words = [name] + [str(x) for x in (tag.get("aliases") or tag.get("keywords") or [])]
        else:
            continue
        if name:
            words += _EN_TAG.get(name, [])
            tags.append((name, [w for w in words if w]))
    # plain_terms（AI/CADD/LLM/SMILES 等）作为额外标签
    for term in tax.get("plain_terms") or []:
        tags.append((str(term), [str(term)]))

    entities: dict[str, list[str]] = {}
    for eid, meta in (tax.get("entities") or {}).items():
        words = [eid]
        if isinstance(meta, dict):
            words += [str(meta.get("label", "")), str(meta.get("name", ""))]
            words += [str(x) for x in (meta.get("aliases") or [])]
        entities[str(meta.get("label") or meta.get("name") or eid)] = [w for w in words if w]
    return cats, tags, entities


def fill(db_path: Path, day: str | None = None, limit: int = 0) -> dict:
    tax = _taxonomy()
    cats, tags, entities = build_rules(tax)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT i.id, i.title, i.summary, i.extra, i.source, i.layer "
            "FROM items i ORDER BY i.last_seen DESC"
        ).fetchall()
        if limit:
            rows = rows[:limit]
        day = day or (datetime.now().astimezone().date().isoformat())
        added = 0
        now = datetime.now().isoformat()
        for r in rows:
            # 已有结构就跳过（不覆盖 LLM 结果）
            if conn.execute("SELECT 1 FROM structures WHERE item_id=?", (r["id"],)).fetchone():
                continue
            text = " ".join(str(r[k] or "") for k in ("title", "summary"))
            try:
                extra = json.loads(r["extra"] or "{}")
            except Exception:
                extra = {}
            text += " " + str(extra.get("body") or "")[:1500]

            category = ""
            for cid, words in cats:
                # 只拿词表前几项匹配，desc 太长容易误命中，用 label/关键词优先
                if _match(text, words):
                    category = cid
                    break
            hit_tags = [name for name, words in tags if _match(text, words)][:6]
            subjects = []
            for label, words in entities.items():
                if _match(text, words):
                    subjects.append(label)
            subjects = subjects[:6]

            if not (category or hit_tags or subjects):
                continue
            conn.execute(
                "INSERT OR IGNORE INTO structures "
                "(item_id,day,category,tags,subjects,scope,model,prompt_version,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    r["id"], day, category or None,
                    json.dumps(hit_tags, ensure_ascii=False),
                    json.dumps(subjects, ensure_ascii=False),
                    "single", "rule-keyword", "v1", now,
                ),
            )
            added += 1
        conn.commit()
        return {"items": len(rows), "filled": added, "categories": len(cats),
                "tags": len(tags), "entities": len(entities)}
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "radar.db"))
    ap.add_argument("--day", default="")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    result = fill(Path(args.db), args.day or None, args.limit)
    print(f"规则结构化：扫描 {result['items']} 条，填充 {result['filled']} 条 "
          f"（词表 {result['categories']} 分类 / {result['tags']} 标签 / {result['entities']} 实体）")


if __name__ == "__main__":
    main()
