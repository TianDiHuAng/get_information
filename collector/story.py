"""事件综述：一个事件只读一处，就知道"这件事到底怎么回事"。

现在的事件页是把官方/媒体/社区的标题并列 —— 读者要自己拼。这一步补上
一段综述：谁做了什么、进展到哪、分歧在哪，并且**每个事实都要能落到某篇报道上**。

对齐 AIHOT 的 `story-digest.md` 与 `events/` 的综述：
- 只在事件有 ≥2 篇报道时才写（单篇没有"综述"可言）；
- 写完过一遍 grounding：综述里出现的专名/数字必须在源报道里找得到，否则丢弃重写一次；
- 结果落库（`story_digests`），同一天同一事件不重复花钱（走 LLM 回执）；
- 页面只读库，不调模型。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from . import grounding, llm, store

ROOT = Path(__file__).parent.parent
PROMPT_PATH = ROOT / "config" / "prompts" / "story-digest.md"

MIN_REPORTS = 2          # 少于两篇不写综述
MAX_CHARS = 1200


def prompt() -> tuple[str, str]:
    """返回 (system, 版本号)。版本号 = 文件内容哈希，改提示词自动失效旧回执。"""
    try:
        text = PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        return "", ""
    import hashlib

    return text, hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def _material(rows: list[dict[str, Any]]) -> str:
    """把事件的所有报道压成给模型看的材料。"""
    lines = []
    for i, row in enumerate(rows, 1):
        lines.append(
            f"[{i}] {row.get('source')}（{(row.get('published') or '')[:10]}）："
            f"{row.get('item_title')}\n"
            f"    {(row.get('item_summary') or '')[:300]}")
    return "\n".join(lines)


def _corpus(rows: list[dict[str, Any]]) -> str:
    """核对用的语料：报道内容 + **来源名**。

    来源名必须算进语料 —— 综述里写"Hacker News 上出现讨论帖"是事实，
    但标题摘要里不会出现"Hacker News"这几个字。
    """
    parts = []
    for row in rows:
        parts.append(f"{row.get('item_title') or ''} {row.get('item_summary') or ''} "
                     f"{row.get('source') or ''} {row.get('event_title') or ''}")
    return "\n".join(parts)


def _clean(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    return text.strip()[:MAX_CHARS]


def generate(event_id: int, rows: list[dict[str, Any]], *,
             model: str | None = None, retry: bool = True) -> dict[str, Any]:
    """写一条综述。返回 `{ok, text, reason}`。"""
    if len(rows) < MIN_REPORTS:
        return {"ok": False, "text": "", "reason": "reports<2"}
    system, version = prompt()
    if not system:
        return {"ok": False, "text": "", "reason": "no-prompt"}

    title = rows[0].get("event_title") or ""
    user = f"事件：{title}\n\n以下是这件事的各家报道：\n{_material(rows)}"
    text = _clean(llm.call_text("story-digest", version, system, user,
                                max_tokens=900, model=model) or "")
    if not text:
        return {"ok": False, "text": "", "reason": "empty"}

    bad = grounding.unsupported(text, _corpus(rows))
    if bad and retry:
        # 一次重写：把没依据的词指出来，让它只用原文说过的东西
        text2 = _clean(llm.call_text(
            "story-digest", version + "r", system,
            user + f"\n\n上一版里这些词在原文中找不到依据，请只用原文有的事实重写：{'、'.join(bad)}",
            max_tokens=900, model=model) or "")
        if text2:
            text = text2
            bad = grounding.unsupported(text2, _corpus(rows))

    return {"ok": not bad, "text": text, "reason": "ok" if not bad else f"ungrounded:{bad[:3]}"}


def save(event_id: int, day: str, text: str, *, model: str = "",
         sources: int = 0) -> None:
    _, version = prompt()
    with store.db() as conn:
        conn.execute(
            """INSERT INTO story_digests (event_id, day, model, prompt_version, text, sources, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(event_id) DO UPDATE SET
                 day = excluded.day, model = excluded.model,
                 prompt_version = excluded.prompt_version, text = excluded.text,
                 sources = excluded.sources, created_at = excluded.created_at""",
            (event_id, day, model, version, text, sources,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )


def get(event_id: int) -> dict[str, Any] | None:
    try:
        with store.db() as conn:
            row = conn.execute(
                "SELECT event_id, day, text, sources, created_at FROM story_digests "
                "WHERE event_id = ?", (event_id,)).fetchone()
    except Exception:
        return None
    return dict(row) if row else None


def _events_needing(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        eid = row.get("event_id")
        if eid is None:
            continue
        grouped.setdefault(int(eid), []).append(row)
    return {k: v for k, v in grouped.items() if len(v) >= MIN_REPORTS}


def run(day: str | None = None, *, limit: int = 10, model: str | None = None) -> dict[str, Any]:
    """给今天的事件写综述。已有且提示词版本没变的不重写。"""
    day = day or store.today_str()
    try:
        rows = store.event_dump(days=3, day=day)
    except Exception as e:
        return {"events": 0, "written": 0, "error": f"{type(e).__name__}: {e}"}
    todo = _events_needing(rows)
    written = skipped = failed = 0
    _, version = prompt()
    for eid, group in list(todo.items())[:limit]:
        existing = get(eid)
        if existing and existing.get("day") == day:
            skipped += 1
            continue
        result = generate(eid, group, model=model)
        if not result["ok"]:
            failed += 1
            continue
        save(eid, day, result["text"], model=model or "", sources=len(group))
        written += 1
    return {"events": len(todo), "written": written, "skipped": skipped,
            "failed": failed, "prompt_version": version}


def count() -> int:
    try:
        with store.db() as conn:
            return int(conn.execute("SELECT count(*) FROM story_digests").fetchone()[0] or 0)
    except Exception:
        return 0
