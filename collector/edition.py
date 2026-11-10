"""成刊：把当天的候选按规则编成一期日报，**不调模型**。

吸收自 AIHOT 的 `reports/edition.ts`：
- 重要性 = 排序分 + 参与方加成 + 官方一手加成 − 跟进扣分；
- 一件事一条（事件已有代表稿时不再重复）；
- 正文 12 条、快讯 10 条一行一个，同一信源最多 2 条；
- 第一条是头条，导语就是它自己的摘要；第 2–4 条是今日看点；
- 最近 7 天报过的事再有进展：只有多家在说才进快讯，否则不出现。

为什么"不调模型"很重要：日报是每天都要出的东西，任何一次模型抽风都不该让今天的报纸变样。
模型只负责写导读（且要过 grounding 校验），编排完全可复现。

这个模块只做**选择**，不做排版：渲染交给 digest（Markdown 与邮件共用同一份编排）。
"""

from __future__ import annotations

import math
from typing import Any

from .identity import title_key

LEAD_N = 1
HIGHLIGHTS_N = 3
BODY_N = 8
BRIEF_N = 8
PER_SOURCE = 2
# 老事件要进快讯，至少这么多家还在说
FOLLOWUP_MIN_SOURCES = 2
# 标题短于这个字数视为"没有信息量"（「太疯狂了」「赢！」这类），扣分而不是丢弃
SHORT_TITLE = 6
THIN_TITLE = 12


def title_penalty(it: dict[str, Any]) -> float:
    """标题太短就轻微降权（不删条目，真正的限制在 `headline_eligible`）。"""
    n = len(title_key(it.get("title") or ""))
    if n < SHORT_TITLE:
        return -6.0
    if n < THIN_TITLE:
        return -2.0
    return 0.0


def headline_eligible(it: dict[str, Any]) -> bool:
    """能不能当头条/看点。

    社媒源常把正文当标题、或者只有「太疯狂了」这类情绪 —— 它们可以是好线索、
    可以进正文和快讯，但**不该占据一期里最贵的两个位置**。
    """
    return len(title_key(it.get("title") or "")) >= SHORT_TITLE


def importance(it: dict[str, Any]) -> float:
    """一天的排序分：分数为主，参与方与一手性加成，跟进减分，空标题扣分。"""
    extra = it.get("extra") or {}
    score = float(extra.get("score") or 0.0)
    sources = int(extra.get("event_sources") or 0) or int(extra.get("event_size") or 1)
    crowd = 5 * math.log2(1 + max(0, sources - 1))
    official = 5.0 if it.get("layer") == "primary" else 0.0
    follow = -6.0 if extra.get("repeat") else 0.0
    return round(score + crowd + official + follow + title_penalty(it), 2)


def _eligible(it: dict[str, Any]) -> bool:
    extra = it.get("extra") or {}
    if not (it.get("title") or "").strip() or not it.get("url"):
        return False
    if (extra.get("attention") or {}).get("label") == "BLOCK":
        return False  # 预筛判定与行业无关
    if extra.get("event_representative") is False:
        return False  # 同一事件只出代表稿
    if extra.get("deal"):
        return False  # 羊毛单独成区
    return True


def candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """候选排序：分数优先，**同分按 URL 定序**。

    必须给定序：Python 的排序是稳定的，不指定 tie-break 时同分条目会沿用输入顺序，
    而输入顺序取决于抓取完成先后 —— 同一批内容换个抓取顺序就会排出两期不同的报纸。
    """
    items = [i for i in payload.get("items") or [] if _eligible(i)]
    return sorted(items, key=lambda it: (-importance(it), it.get("url") or ""))


def arrange(payload: dict[str, Any], *, body_n: int = BODY_N, brief_n: int = BRIEF_N,
            highlights_n: int = HIGHLIGHTS_N) -> dict[str, Any]:
    """返回 `{lead, highlights, body, briefs, used, ranked}`。`used` 里的 URL 已被本期用掉。"""
    ranked = candidates(payload)
    limit = LEAD_N + highlights_n + body_n
    main: list[dict[str, Any]] = []
    briefs: list[dict[str, Any]] = []
    used: set[str] = set()
    per_source: dict[str, int] = {}

    for it in ranked:
        extra = it.get("extra") or {}
        url = it.get("url") or ""

        if extra.get("repeat"):
            # 老事件：多数情况下不再出现；多家仍在说才降级成快讯
            sources = int(extra.get("event_sources") or 0) or 1
            if sources >= FOLLOWUP_MIN_SOURCES and len(briefs) < brief_n:
                briefs.append(it)
                used.add(url)
            continue

        if per_source.get(it.get("source") or "", 0) >= PER_SOURCE:
            continue
        if len(main) >= limit:
            continue
        main.append(it)
        used.add(url)
        per_source[it.get("source") or ""] = per_source.get(it.get("source") or "", 0) + 1

    # 头条优先给"有信息量的标题"；整期都没有合格标题时，退回最高分那条 ——
    # 宁可头条标题差一点，也不要出一份空的报纸。
    lead = next((it for it in main if headline_eligible(it)), main[0] if main else None)
    rest = [it for it in main if it is not lead]
    highlights = [it for it in rest if headline_eligible(it)][:highlights_n]
    body = [it for it in rest if it not in highlights]
    return {
        "lead": lead,
        "highlights": highlights,
        "body": body,
        "briefs": briefs,
        "used": used,
        "ranked": ranked,
        "total": len(main) + len(briefs),
    }


def summary_line(plan: dict[str, Any]) -> str:
    """给日志/邮件页脚的一行统计。"""
    return (f"头条 1 · 看点 {len(plan['highlights'])} · 正文 {len(plan['body'])} · "
            f"快讯 {len(plan['briefs'])}")


def render_md(plan: dict[str, Any], line) -> list[str]:
    """把编排结果渲染成 Markdown 行。`line` 是 digest 里那套单条格式（返回 `- **[标题](url)** …`）。"""
    out: list[str] = ["## 今日要闻", ""]
    lead = plan.get("lead")
    if not lead:
        return out + ["- 今天没有值得入选的内容。", ""]

    out.append(line(lead))
    out.append("")

    if plan["highlights"]:
        out.append("### 今日看点")
        out.append("")
        for i, it in enumerate(plan["highlights"], start=1):
            text = line(it)
            out.append(f"{i}. {text[2:] if text.startswith('- ') else text}")
        out.append("")

    if plan["body"]:
        out.append("### 其他值得知道")
        out.append("")
        out.extend(line(it) for it in plan["body"])
        out.append("")

    if plan["briefs"]:
        out.append("### 快讯")
        out.append("")
        out.append(" · ".join(f"[{it['title']}]({it['url']})" for it in plan["briefs"]))
        out.append("")
    return out
