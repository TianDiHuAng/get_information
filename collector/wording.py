"""改用词：读者看不懂的行话、要压住的夸张说法。

对齐 AIHOT 的 `industry/wording.ts` + `mend-wording.md`：规则是一串正则和改法，
标题/摘要/推荐理由写完后逐个查，命中才让模型**只改这些词**一次。

四条安全边界（照它的规定）：
1. 改完数字有变 → 保留原文
2. 改完变空 → 保留原文
3. 模型拒绝/失败 → 保留原文
4. 词表空着 → **一次都不调用**（不花钱，也不在告警里出现）

为什么是"只改这几个词"而不是"重写"：重写会顺手改掉事实与语气，
而这一步的目的只是把读者不用的词换掉。
"""

from __future__ import annotations

import re
from typing import Any

from . import industry

_NUM = re.compile(r"\d+(?:\.\d+)?")

_SYSTEM = """你只做一件事：把给定文字里的指定词语换成指定的说法。
规则：
- 只替换列出的词，其它字一个都别改（不要润色、不要改语序、不要补内容）
- 数字、专有名词、引号里的原话必须原样保留
- 只输出替换后的文字，不要解释，不要加引号"""


def rules() -> list[dict[str, str]]:
    """读行业包里的 wording.yaml（没有就是空表）。"""
    data = industry.load("wording.yaml")
    out = []
    for row in (data.get("rules") or []):
        if not isinstance(row, dict):
            continue
        pattern = str(row.get("pattern") or "").strip()
        replace = str(row.get("replace") or "").strip()
        if not pattern or not replace:
            continue
        try:
            re.compile(pattern)
        except re.error:
            continue
        out.append({"pattern": pattern, "replace": replace,
                    "note": str(row.get("note") or "")})
    return out


def matches(text: str) -> list[dict[str, str]]:
    """这段文字命中了哪些规则（不调模型，纯正则）。"""
    hits = []
    for rule in rules():
        try:
            found = re.search(rule["pattern"], text or "")
        except re.error:
            continue
        if found:
            hits.append({**rule, "found": found.group(0)})
    return hits


def _numbers(text: str) -> list[str]:
    return sorted(_NUM.findall(text or ""))


def mend(text: str, *, model: str | None = None) -> dict[str, Any]:
    """改写一段文字。返回 `{text, changed, reason}`。

    `changed=False` 时 `text` 就是原文 —— 调用方不需要判断。
    """
    original = text or ""
    if not original.strip():
        return {"text": original, "changed": False, "reason": "empty"}
    hits = matches(original)
    if not hits:
        return {"text": original, "changed": False, "reason": "no-rule-hit"}

    pairs = "\n".join(f"- 「{h['found']}」→「{h['replace']}」" for h in hits)
    try:
        from . import llm

        result = llm.call_text(
            "wording", "1", _SYSTEM,
            f"要替换的词：\n{pairs}\n\n原文：\n{original}",
            max_tokens=max(120, len(original) * 2), model=model)
    except Exception as e:
        return {"text": original, "changed": False, "reason": f"error: {type(e).__name__}"}

    if not result or not str(result).strip():
        return {"text": original, "changed": False, "reason": "empty-result"}
    cleaned = str(result).strip().strip('"').strip()
    if _numbers(cleaned) != _numbers(original):
        # 数字变了：这一步不该动数字，说明模型改多了
        return {"text": original, "changed": False, "reason": "numbers-changed"}
    if not cleaned:
        return {"text": original, "changed": False, "reason": "blank"}
    return {"text": cleaned, "changed": cleaned != original, "reason": "ok"}


def apply_to_items(items: list[dict[str, Any]], *, limit: int = 30,
                   model: str | None = None) -> dict[str, int]:
    """给一批条目改用词（只动 title / summary）。命中才调用，最多 `limit` 条。"""
    if not rules():
        return {"checked": 0, "changed": 0, "skipped": 0}
    checked = changed = skipped = 0
    for item in items:
        if changed >= limit:
            break
        for field in ("title", "summary"):
            value = str(item.get(field) or "")
            if not value or not matches(value):
                continue          # 没命中就不算"检查过"，也不调用
            checked += 1
            result = mend(value, model=model)
            if result["changed"]:
                item[field] = result["text"]
                changed += 1
            elif result["reason"] not in ("no-rule-hit", "empty"):
                skipped += 1
    return {"checked": checked, "changed": changed, "skipped": skipped}
