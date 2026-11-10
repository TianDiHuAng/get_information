"""一键出稿：arXiv 论文 → 小红书笔记（事实提取 + 确定性拼装）。

不经过 build() 的清洗链，结构由代码保证。
用法：python tools/xhs_make.py [--limit 3] [--date 2026-11-10]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from collector import xhs_deep, xhs_shell  # noqa: E402
from collector.paper_deep import fetch_sections  # noqa: E402
from collector.xhs import _chat, _llm_conf, conf  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    a = ap.parse_args()

    papers = json.loads((ROOT / "data" / "papers_pending.json").read_text(encoding="utf-8"))
    papers.sort(key=lambda x: x.get("published", ""), reverse=True)
    lead, others = papers[0], papers[1 : a.limit]

    cfg, llm = conf(), _llm_conf()
    sec = fetch_sections(str(lead["id"]))
    if not sec.get("ok"):
        raise SystemExit("正文抓取失败")
    print(f"主打：{lead['title'][:60]}")

    facts = xhs_deep.extract_facts(_chat, llm, lead["title"], sec)
    if not facts:
        raise SystemExit("事实提取失败")
    missing = xhs_deep._complete(facts)
    print(f"事实齐备：{not missing}  {missing or ''}")

    shell = xhs_shell.build_shell(_chat, llm, cfg, lead["title"], facts) or {}
    titles = shell.get("titles") or [lead["title"][:18]]
    cover = shell.get("cover") or ["GLP 读 ESM-2", "扩散当先验", "能读但没新料"]
    tags = shell.get("tags") or list(cfg["tags"]["fixed"])

    post = xhs_deep.assemble(facts, shell, others, cover=cover, tags=tags, titles=titles)
    body = post["body"]

    marks = {m: m in body for m in ("🧪", "🔧", "📊", "⚠️", "💡", "📌")}
    print(f"正文字数：{len(body)}  板块：{marks}")

    out = ROOT / "data" / "xhs" / f"{a.date}-arxiv.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# 小红书笔记 · {a.date} · arXiv 深度稿",
        "",
        "## 封面文案",
        "",
        *[f"**{c}**" for c in cover],
        "",
        "## 标题（三选一）",
        "",
        *[f"{i}. {t}（{len(t)} 字）" for i, t in enumerate(titles, 1)],
        "",
        "## 正文",
        "",
        body,
        "",
        "## 标签",
        "",
        " ".join("#" + t.lstrip("#") for t in tags),
        "",
        "---",
        f"主打：{lead.get('title')} — {lead.get('url')}",
        *[f"陪跑：{o.get('title')} — {o.get('url')}" for o in others],
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"→ {out}")


if __name__ == "__main__":
    main()
