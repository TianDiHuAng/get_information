"""结构化抽取：分类、标签、主体公司、是不是一条具体新闻。

为什么值得花这一轮模型调用（而不是靠关键词分类）：
- **主题页/标签页**要有稳定的聚合键，关键词匹配会把"提到芯片"和"芯片发布"混在一起；
- **事件综述与叙事对比**需要知道"这件事的主体是谁"，否则只能比标题；
- **防张冠李戴**需要一份"原文提了哪些公司"的清单，这正是 `subjects`。

吸收自 AIHOT 的 `structure.md` + `editorial/vocabulary.ts`，两处改动：
1. 分类与标签词表放在 `config/taxonomy.yaml`，**模型越界就丢掉**（不静默接受脏值）；
2. 抽出 `scope`（single / composite / unknown）—— 综合稿不能当单事件处理，
   这是日报"一件事一条"的前提。

降级：模型不可用/输出不合规 → 不写结构，条目不进主题页，其余流程照旧。
"""

from __future__ import annotations

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable

import yaml

from . import llm, store
from .identity import item_identity

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config" / "structure.yaml"
TAXONOMY_PATH = ROOT / "config" / "taxonomy.yaml"
PROMPT_DIR = ROOT / "config" / "prompts"
SITE_NAME = "Z-Bit"

SCOPES = ("single", "composite", "unknown")

_lock = threading.Lock()
_config_cache: dict[str, Any] = {"mtime": 0.0, "value": {}}
_tax_cache: dict[str, Any] = {"mtime": 0.0, "value": {}}
_prompt_cache: dict[str, tuple[str, str]] = {}


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #

def config() -> dict[str, Any]:
    try:
        mtime = CONFIG_PATH.stat().st_mtime
    except OSError:
        return {}
    with _lock:
        if _config_cache["mtime"] == mtime:
            return _config_cache["value"]
        try:
            value = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            value = {}
        _config_cache.update(mtime=mtime, value=value)
        return value


def taxonomy() -> dict[str, Any]:
    try:
        mtime = TAXONOMY_PATH.stat().st_mtime
    except OSError:
        return {}
    with _lock:
        if _tax_cache["mtime"] == mtime:
            return _tax_cache["value"]
        try:
            value = yaml.safe_load(TAXONOMY_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            value = {}
        _tax_cache.update(mtime=mtime, value=value)
        return value


def prompt() -> tuple[str, str]:
    """渲染 `structure.md`，返回 `(正文, 版本号)`。版本号含词表，改词表同样失效。"""
    tax = taxonomy()
    tags = [str(t) for t in (tax.get("tags") or [])]
    vocab = "、".join(tags)
    try:
        raw = (PROMPT_DIR / "structure.md").read_text(encoding="utf-8")
    except OSError:
        raw = ""
    text = raw.replace("{{site_name}}", SITE_NAME).replace("{{tag_vocab}}", vocab)
    version = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return text, version


# --------------------------------------------------------------------------- #
# 抽取
# --------------------------------------------------------------------------- #

def _material(item: Any, limit: int = 2500) -> tuple[str, bool]:
    title = (getattr(item, "title", "") or "").strip()
    summary = (getattr(item, "summary", "") or "").strip()
    body = (getattr(item, "extra", {}) or {}).get("body") or ""
    parts = [f"标题：{title}"]
    if summary:
        parts.append(f"摘要：{summary}")
    if body:
        parts.append(f"正文片段：{body}")
    if getattr(item, "published", ""):
        parts.append(f"发布时间：{item.published}")
    return "\n".join(parts)[:limit], not summary and not body


def _clean(obj: dict[str, Any], tax: dict[str, Any]) -> dict[str, Any] | None:
    """把模型输出收敛到词表范围内；越界的值丢掉而不是照收。"""
    categories = tax.get("categories") or {}
    tags_vocab = {str(t) for t in (tax.get("tags") or [])}
    category = str(obj.get("category") or "").strip()
    if category not in categories:
        return None

    tags: list[str] = []
    for t in obj.get("tags") or []:
        t = str(t).strip()
        if t in tags_vocab and t not in tags:
            tags.append(t)
    scope = str(obj.get("scope") or "").strip()
    if scope not in SCOPES:
        scope = "unknown"

    subjects: list[str] = []
    for s in obj.get("subjects") or []:
        s = str(s).strip()
        if s and s not in subjects and len(s) <= 40:
            subjects.append(s)

    fact = obj.get("fact")
    if scope != "single" or not isinstance(fact, dict):
        fact = None
    else:
        fact = {
            "subject": str(fact.get("subject") or "")[:60],
            "action": str(fact.get("action") or "")[:20],
            "object": str(fact.get("object") or "")[:80],
            "when": str(fact.get("when") or "")[:20],
        }
        if not (fact["subject"] or fact["object"]):
            fact = None

    return {"category": category, "tags": tags[:3], "subjects": subjects[:3],
            "scope": scope, "fact": fact}


def extract(item: Any) -> dict[str, Any] | None:
    system, version = prompt()
    if not system:
        return None
    user, title_only = _material(item)
    if title_only:
        user += "\n\n（这条材料只有标题，没有摘要和正文。）"
    obj = llm.call_json("structure", version, system, user, max_tokens=300)
    if not obj:
        return None
    cleaned = _clean(obj, taxonomy())
    if cleaned is None:
        return None
    cleaned["prompt_version"] = version
    return cleaned


# --------------------------------------------------------------------------- #
# 批量
# --------------------------------------------------------------------------- #

def structure_items(items: Iterable[Any], *, day: str | None = None,
                    ids: dict[str, int] | None = None) -> dict[str, Any]:
    conf = config()
    if not conf.get("enabled", True):
        return {"skipped": "disabled"}
    if not llm.available():
        return {"skipped": "no-llm"}

    items = list(items)
    if not items:
        return {"skipped": "empty"}
    if isinstance(items[0], dict):
        raise TypeError("structure 需要 Item 对象；收到 dict（是不是提前 to_dict 了？）")
    day = day or store.today_str()

    min_score = float(conf.get("min_score") or 0)
    pool = [i for i in items if float((getattr(i, "extra", {}) or {}).get("score") or 0) >= min_score]
    pool.sort(key=lambda i: float((getattr(i, "extra", {}) or {}).get("score") or 0), reverse=True)
    max_items = int(conf.get("max_items") or 0)
    if max_items:
        pool = pool[:max_items]
    if not pool:
        return {"skipped": "empty"}

    if ids is None:
        ids = store.ids_for([item_identity(getattr(i, "url", "")) for i in pool])

    workers = max(1, int(conf.get("max_workers") or 4))
    results: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool_ex:
        futures = {pool_ex.submit(extract, it): idx for idx, it in enumerate(pool)}
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                got = fut.result()
            except Exception:
                got = None
            if got:
                results[idx] = got

    rows: list[dict[str, Any]] = []
    stats = {"structured": 0, "failed": len(pool) - len(results), "categories": {}, "scopes": {}}
    for idx, data in results.items():
        it = pool[idx]
        it.extra["structure"] = data
        stats["structured"] += 1
        stats["categories"][data["category"]] = stats["categories"].get(data["category"], 0) + 1
        stats["scopes"][data["scope"]] = stats["scopes"].get(data["scope"], 0) + 1
        item_id = ids.get(item_identity(getattr(it, "url", "")))
        if item_id:
            rows.append({"item_id": item_id, **data})
    if rows:
        store.save_structures(rows, day)
    stats["llm"] = llm.stats(day)
    return stats


def by_category(items: Iterable[Any]) -> dict[str, list[Any]]:
    """给主题页/分区用：按分类分组（没有结构的归到 other）。"""
    out: dict[str, list[Any]] = {}
    for it in items:
        cat = ((getattr(it, "extra", {}) or {}).get("structure") or {}).get("category") or "other"
        out.setdefault(cat, []).append(it)
    return out
