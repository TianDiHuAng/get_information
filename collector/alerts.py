"""告警：源连续失败、日报缺期、预算耗尽、模型失败率过高。

吸收自 AIHOT 的 `operations/alerts.ts` + `operations/watch.ts` 的最小版本。
原则和那边一样：**告警要能说清"哪件事、什么时候、多严重"**，并且同一天同一条只发一次，
否则每轮都发一封同样的信，等于没有告警。

这里只负责"判断 + 记录 + 汇总成一封信"；发信走 `pushmail.send_text`（同一套 SMTP 配置），
以后接 Telegram/飞书时换发送端即可。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from . import llm, store

# 源连续失败多少次算异常
SOURCE_FAIL_LIMIT = 3
# 多久没有成功抓取算"哑了"
SOURCE_SILENT_HOURS = 24
# 日报过了这个点还没出，算缺期
EDITION_DEADLINE = (9, 30)
# 模型失败率超过这个比例就告警（样本太少不报，避免噪声）
LLM_FAIL_RATIO = 0.3
LLM_MIN_CALLS = 20


def _now() -> datetime:
    return datetime.now()


def check(payload: dict[str, Any] | None = None, day: str | None = None) -> list[dict[str, str]]:
    """返回告警列表：`[{kind, severity, message}]`。不写库、不发信。"""
    day = day or store.today_str()
    found: list[dict[str, str]] = []

    # 1) 信源健康：连续失败 / 长期没成功
    try:
        rows = store.source_rows()
    except Exception:
        rows = []
    for row in rows:
        fails = int(row.get("fails") or 0)
        last_ok = row.get("last_ok")
        name = row.get("source")
        if fails >= SOURCE_FAIL_LIMIT:
            found.append({"kind": "source_fails", "severity": "warn",
                          "message": f"{name} 连续失败 {fails} 次（{row.get('last_error') or '无错误信息'}）"})
        elif last_ok:
            try:
                age = _now() - datetime.strptime(last_ok, "%Y-%m-%d %H:%M:%S")
            except Exception:
                age = timedelta(0)
            if age > timedelta(hours=SOURCE_SILENT_HOURS):
                found.append({"kind": "source_silent", "severity": "warn",
                              "message": f"{name} 已经 {age.days} 天没有成功抓取"})

    # 2) 日报缺期
    deadline = _now().replace(hour=EDITION_DEADLINE[0], minute=EDITION_DEADLINE[1], second=0, microsecond=0)
    if _now() >= deadline and store.edition_row("daily", day) is None:
        found.append({"kind": "edition_missing", "severity": "error",
                      "message": f"今天（{day}）的日报到 {EDITION_DEADLINE[0]:02d}:{EDITION_DEADLINE[1]:02d} 还没出刊"})
    try:
        gaps = store.missing_editions("daily", days=3, day=day)
    except Exception:
        gaps = []
    if gaps:
        found.append({"kind": "edition_gap", "severity": "warn",
                      "message": f"最近 3 天里缺了 {len(gaps)} 期日报：{'、'.join(gaps)}"})

    # 3) 模型调用：预算与失败率
    try:
        stats = llm.stats(day)
    except Exception:
        stats = {}
    total = int(stats.get("total") or 0)
    by_state = stats.get("by_state") or {}
    bad = int(by_state.get("failed") or 0) + int(by_state.get("unknown") or 0)
    if total >= LLM_MIN_CALLS and bad / total > LLM_FAIL_RATIO:
        found.append({"kind": "llm_failures", "severity": "warn",
                      "message": f"模型调用失败 {bad}/{total}（{bad / total:.0%}），检查网关或预算"})

    conf = llm.settings()
    budget = (stats.get("budget") or {})
    day_key = f"D:{day}/llm"
    used = int(budget.get(day_key) or 0)
    limit = int(conf.get("budget_per_day") or 0)
    if limit and used >= limit:
        found.append({"kind": "budget_exhausted", "severity": "error",
                      "message": f"今天的模型预算已用完（{used}/{limit}），后续条目退回规则打分"})

    # 4) 评分失败率（有 payload 时才看）
    if payload:
        att = (payload.get("stats") or {}).get("attention") or {}
        scored = int(att.get("scored") or 0)
        failed = int(att.get("failed") or 0)
        if scored and failed / max(1, scored + failed) > 0.3:
            found.append({"kind": "rating_failures", "severity": "warn",
                          "message": f"评分失败率偏高：{failed}/{scored + failed}"})

    return found


def record(found: list[dict[str, str]], day: str | None = None) -> list[dict[str, str]]:
    """写库并只返回新出现的那些（用来决定发不发信）。"""
    day = day or store.today_str()
    fresh: list[dict[str, str]] = []
    for item in found:
        try:
            if store.save_alert(item["kind"], day, item["message"], item.get("severity", "warn")):
                fresh.append(item)
        except Exception:
            pass
    return fresh


def render(found: list[dict[str, str]]) -> tuple[str, str]:
    """把告警渲染成 (主题, 正文)。"""
    day = store.today_str()
    errors = [a for a in found if a.get("severity") == "error"]
    subject = f"[Z-Bit] {day} 告警 {len(found)} 条" + ("（含错误）" if errors else "")
    lines = [f"# Z-Bit · {day} 运行告警", ""]
    for a in found:
        mark = "❌" if a.get("severity") == "error" else "⚠️"
        lines.append(f"- {mark} **{a['kind']}** — {a['message']}")
    lines += ["", "---", "由 `collector/alerts.py` 自动生成。"]
    return subject, "\n".join(lines)


def send(found: list[dict[str, str]]) -> str:
    """发一封汇总信。没有配置或没有新告警时静默跳过。"""
    if not found:
        return "no-alert"
    subject, body = render(found)
    try:
        from . import pushmail

        return pushmail.send_text(subject, body)
    except Exception as e:
        return f"send-failed: {type(e).__name__}: {e}"


def run(payload: dict[str, Any] | None = None, *, notify: bool = True) -> dict[str, Any]:
    """一轮自检：检查 → 写库 → 有新告警才发信。绝不抛异常。"""
    try:
        found = check(payload)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    fresh = record(found)
    result = {"found": len(found), "fresh": len(fresh), "sent": "skipped"}
    if notify and fresh:
        result["sent"] = send(fresh)
    return result
