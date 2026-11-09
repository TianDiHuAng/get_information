"""X / Twitter 时间线：走 fxtwitter 公开镜像，免费、无需 token。

用法：config/x.yaml 里填账号。每条推文只在第一次抓到时保留，
之后记录在 data/x_seen.json，所以"重复的不会再推"。
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .model import Item
from .net import get_json

CONF_PATH = Path(__file__).parent.parent / "config" / "x.yaml"
SEEN_PATH = Path(__file__).parent.parent / "data" / "x_seen.json"

DEFAULTS = {
    "enabled": False,
    "use_proxy": True,
    "users": [],
    "per_user": 8,
    "window_hours": 26,
    "min_likes": 0,
    "exclude_replies": True,
    "min_chars": 40,
    "include_reposts": False,
    "searches": [],
    "search_per_query": 20,
    "search_min_likes": 8,
    "search_window_hours": 72,
}


def conf() -> dict:
    data = dict(DEFAULTS)
    if CONF_PATH.exists():
        try:
            data.update(yaml.safe_load(CONF_PATH.read_text(encoding="utf-8")) or {})
        except Exception:
            pass
    data["users"] = [str(u).lstrip("@") for u in (data.get("users") or []) if str(u).strip()]
    return data


def is_enabled() -> bool:
    c = conf()
    return bool(c["enabled"] and c["users"])


def _load_seen() -> dict:
    if not SEEN_PATH.exists():
        return {}
    try:
        return json.loads(SEEN_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_seen(seen: dict) -> None:
    # 只保留 45 天，防止无限增长
    cutoff = (datetime.now(timezone.utc) - timedelta(days=45)).strftime("%Y-%m-%d")
    trimmed = {k: v for k, v in seen.items() if v >= cutoff}
    SEEN_PATH.parent.mkdir(exist_ok=True)
    SEEN_PATH.write_text(json.dumps(trimmed, ensure_ascii=False), encoding="utf-8")


def _parse_time(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y")
    except Exception:
        return None


def _headline(text: str) -> str:
    line = ""
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("http"):
            line = ln
            break
    line = line or (text or "").strip()
    line = re.sub(r"https?://\S+", "", line).strip()
    return line[:90] or "（无正文）"


def fetch() -> list[Item]:
    c = conf()
    if not c["enabled"] or not c["users"]:
        return []

    seen = _load_seen()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=int(c["window_hours"]))
    items: list[Item] = []

    for user in c["users"]:
        try:
            data = get_json(
                f"https://api.fxtwitter.com/2/profile/{user}/statuses",
                use_proxy=bool(c["use_proxy"]),
                timeout=45,
            )
        except Exception as e:
            print(f"  [x] @{user} 抓取失败: {type(e).__name__}: {e}")
            continue

        kept = 0
        for t in (data.get("results") or [])[: int(c["per_user"]) * 2]:
            if t.get("type") != "status":
                continue
            tid = str(t.get("id") or "")
            if not tid or tid in seen:
                continue
            created = _parse_time(t.get("created_at"))
            if created and created < cutoff:
                continue
            if int(t.get("likes") or 0) < int(c["min_likes"]):
                continue
            if c.get("exclude_replies") and t.get("replying_to"):
                continue

            raw = t.get("text") or t.get("raw_text") or ""
            if isinstance(raw, dict):
                raw = raw.get("text") or ""
            text = str(raw)
            if not text.strip():
                continue
            # 太短的（"never"、"好耶"）没有信息量，直接丢
            if len(re.sub(r"https?://\S+", "", text).strip()) < int(c.get("min_chars", 0)):
                continue

            # 转推识别：reposted_by 存在且与原作者不同 → 真转推
            author_info = t.get("author") or {}
            orig_author = str(author_info.get("screen_name") or user)
            reposted_by = (t.get("reposted_by") or {}).get("screen_name")
            is_repost = bool(reposted_by and str(reposted_by).lower() != orig_author.lower())
            if is_repost and not c.get("include_reposts", False):
                continue

            headline = _headline(text)
            if is_repost:
                headline = f"🔁 @{orig_author}：{headline}"
            items.append(
                Item(
                    source="x",
                    layer="social",
                    title=headline,
                    url=t.get("url") or f"https://x.com/{user}/status/{tid}",
                    published=created.astimezone(timezone.utc).isoformat(timespec="seconds") if created else "",
                    summary=text[:280],
                    heat=float(t.get("likes") or 0),
                    lang=str(t.get("lang") or "en"),
                    author=orig_author,
                    extra={
                        "tweet_id": tid,
                        "replies": t.get("replies"),
                        "reposts": t.get("reposts"),
                        "views": t.get("views"),
                        "reposted_by": reposted_by,
                        "is_repost": is_repost,
                    },
                )
            )
            seen[tid] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            kept += 1
            if kept >= int(c["per_user"]):
                break

        print(f"  [x] @{user}: 新 {kept} 条")

    _save_seen(seen)
    return items


def search(queries: list[str] | None = None, per_query: int | None = None) -> list[Item]:
    """X 关键词搜索（fxtwitter /2/search，免费）：补名单以外的羊毛/技巧。"""
    c = conf()
    if not c.get("enabled"):
        return []
    qs = queries or c.get("searches") or []
    if not qs:
        return []
    # 轮换：每轮只跑 2 个词，避免触发接口限流（一天 4 轮正好覆盖 8 个词）
    per_run = int(c.get("search_queries_per_run") or len(qs))
    state_file = SEEN_PATH.parent / "x_search_state.json"
    try:
        offset = int(json.loads(state_file.read_text(encoding="utf-8")).get("offset", 0))
    except Exception:
        offset = 0
    qs = [qs[(offset + i) % len(qs)] for i in range(min(per_run, len(qs)))]
    try:
        state_file.write_text(json.dumps({"offset": offset + len(qs)}), encoding="utf-8")
    except Exception:
        pass
    per = int(per_query or c.get("search_per_query") or 20)
    min_likes = int(c.get("search_min_likes", c.get("min_likes", 0)))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=int(c.get("search_window_hours", 72)))
    seen = _load_seen()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    items: list[Item] = []
    local: set[str] = set()

    for q in qs:
        data: dict = {}
        for attempt in range(2):
            try:
                data = get_json(
                    "https://api.fxtwitter.com/2/search",
                    use_proxy=bool(c.get("use_proxy", True)),
                    timeout=45,
                    params={"q": str(q), "feed": "latest", "count": per},
                )
                break
            except Exception as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status == 404:  # 接口在没有结果/被限流时也回 404，视为空
                    data = {}
                    break
                if attempt == 0:
                    time.sleep(4)
                    continue
                print(f"  [x] 搜索「{q}」失败: {type(e).__name__}: {e}")
                data = {}

        kept = 0
        for t in data.get("results") or []:
            if t.get("type") != "status":
                continue
            tid = str(t.get("id") or "")
            if not tid or tid in seen or tid in local:
                continue
            created = _parse_time(t.get("created_at"))
            if created and created < cutoff:
                continue
            if int(t.get("likes") or 0) < min_likes:
                continue
            if c.get("exclude_replies") and t.get("replying_to"):
                continue
            text = t.get("text") or ""
            if isinstance(text, dict):
                text = text.get("text") or ""
            text = str(text)
            if len(re.sub(r"https?://\S+", "", text).strip()) < int(c.get("min_chars", 0)):
                continue
            author = str((t.get("author") or {}).get("screen_name") or "")
            reposted_by = (t.get("reposted_by") or {}).get("screen_name")
            if reposted_by and str(reposted_by).lower() != author.lower() and not c.get("include_reposts"):
                continue

            items.append(
                Item(
                    source="x",
                    layer="social",
                    region="overseas",
                    title="🔎 " + _headline(text),
                    url=t.get("url") or f"https://x.com/{author}/status/{tid}",
                    published=created.astimezone(timezone.utc).isoformat(timespec="seconds") if created else "",
                    summary=text[:280],
                    heat=float(t.get("likes") or 0),
                    lang=str(t.get("lang") or "en"),
                    author=author,
                    extra={"tweet_id": tid, "keyword": q, "via": "search"},
                )
            )
            local.add(tid)
            kept += 1

        print(f"  [x] 搜索「{q}」: {kept} 条")
        time.sleep(2.5)

    # 搜索结果按点赞排序，只留前 N 条，避免淹没时间线
    items.sort(key=lambda x: x.heat or 0, reverse=True)
    limit = int(c.get("search_max_items") or 25)
    top = items[:limit]
    for it in top:
        seen[str(it.extra.get("tweet_id"))] = today
    _save_seen(seen)
    return top


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for it in fetch() + search():
        print(f"{it.published[:16]} ♥{int(it.heat or 0):<6} @{it.author}  {it.title[:70]}")
