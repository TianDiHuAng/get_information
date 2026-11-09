"""X 关键词搜索（Apify，按条计费）。

用 apidojo/tweet-scraper：$0.0001/条（$0.1/千条），比 scweet 便宜 3 倍。
token 放在 config/secrets.yaml（tools/set_secret.py 写入），或环境变量 APIFY_TOKEN。

只在 token 存在且启用时工作；没有 token 时不报错，交给 fxtwitter 免费搜索兜底。
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .model import Item
from .net import session

ROOT = Path(__file__).parent.parent
SECRETS = ROOT / "config" / "secrets.yaml"
XCONF = ROOT / "config" / "x.yaml"
SEEN = ROOT / "data" / "x_seen.json"
ACTOR = "apidojo~tweet-scraper"


def _tokens() -> list[str]:
    """支持多个免费账号轮换（每个号每月 $5 额度）。"""
    toks: list[str] = []
    env = (os.environ.get("APIFY_TOKEN") or "").strip()
    if env:
        toks.append(env)
    try:
        data = yaml.safe_load(SECRETS.read_text(encoding="utf-8")) or {}
    except Exception:
        data = {}
    for key in ("apify_token", "apify_token_2", "apify_token_3"):
        v = str(data.get(key) or "").strip()
        if v and v not in toks:
            toks.append(v)
    return toks


def _token() -> str:
    toks = _tokens()
    return toks[0] if toks else ""


def _conf() -> dict:
    try:
        data = yaml.safe_load(XCONF.read_text(encoding="utf-8")) or {}
    except Exception:
        data = {}
    ap = data.get("apify") or {}
    return {
        "enabled": bool(ap.get("enabled", True)),
        "actor": str(ap.get("actor") or ACTOR),
        "queries": ap.get("queries") or data.get("searches") or [],
        "queries_per_run": int(ap.get("queries_per_run") or 0),
        "per_query": int(ap.get("max_items_per_query") or 15),
        "max_total": int(ap.get("max_items_total") or 40),
        "window_hours": int(ap.get("window_hours") or 48),
        "min_likes": int(ap.get("min_likes") or 0),
        "min_chars": int(ap.get("min_chars") or 20),
        "sort": str(ap.get("sort") or "Latest"),
    }


def enabled() -> bool:
    return bool(_token()) and _conf()["enabled"]


def _load_seen() -> dict:
    try:
        return json.loads(SEEN.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_seen(seen: dict) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=45)).strftime("%Y-%m-%d")
    SEEN.parent.mkdir(exist_ok=True)
    SEEN.write_text(json.dumps({k: v for k, v in seen.items() if v >= cutoff}, ensure_ascii=False), encoding="utf-8")


def _parse_time(raw: str | None) -> datetime | None:
    if not raw:
        return None
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(raw, fmt)
        except Exception:
            continue
    return None


def _headline(text: str) -> str:
    for ln in (text or "").splitlines():
        ln = re.sub(r"https?://\S+", "", ln).strip()
        if len(ln) >= 8:
            return ln[:90]
    return re.sub(r"https?://\S+", "", text or "").strip()[:90] or "（无正文）"


def search(queries: list[str] | None = None, per_query: int | None = None) -> list[Item]:
    tokens = _tokens()
    c = _conf()
    if not tokens or not c["enabled"]:
        return []
    qs = queries or c["queries"]
    if not qs:
        return []
    # 轮换：矩阵有 8 条，每轮只跑 4 条，避免一次打太多
    per_run = int(c.get("queries_per_run") or 0)
    if per_run and len(qs) > per_run:
        state_file = SEEN.parent / "x_apify_state.json"
        try:
            offset = int(json.loads(state_file.read_text(encoding="utf-8")).get("offset", 0))
        except Exception:
            offset = 0
        qs = [qs[(offset + i) % len(qs)] for i in range(per_run)]
        try:
            state_file.write_text(json.dumps({"offset": offset + per_run}), encoding="utf-8")
        except Exception:
            pass

    per = int(per_query or c["per_query"])
    cutoff = datetime.now(timezone.utc) - timedelta(hours=c["window_hours"])
    seen = _load_seen()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    items: list[Item] = []
    local: set[str] = set()

    for q in qs:
        body = {"searchTerms": [str(q)], "maxItems": per, "sort": c["sort"]}
        rows: list[dict] = []
        # 多个账号轮换：某个号被限（整批 noResults）就换下一个
        for n, tok in enumerate(tokens, 1):
            try:
                with session() as s:
                    r = s.post(
                        f"https://api.apify.com/v2/acts/{c['actor']}/run-sync-get-dataset-items",
                        params={"token": tok, "timeout": 240},
                        json=body,
                        timeout=300,
                    )
                    r.raise_for_status()
                    raw = r.json() or []
                real = [x for x in raw if not x.get("noResults")]
                if real:
                    rows = real
                    break
            except Exception as e:
                print(f"  [x/apify] 账号{n}「{q}」失败: {type(e).__name__}: {str(e)[:100]}")
            time.sleep(1)

        kept = 0
        for t in rows:
            tid = str(t.get("id") or "")
            if not tid or tid in seen or tid in local:
                continue
            if t.get("isReply"):
                continue
            text = str(t.get("fullText") or t.get("text") or "")
            if text.startswith("RT @"):
                continue
            clean = re.sub(r"https?://\S+", "", text).strip()
            if len(clean) < c["min_chars"]:
                continue
            if int(t.get("likeCount") or 0) < c["min_likes"]:
                continue
            created = _parse_time(t.get("createdAt"))
            if created and created.astimezone(timezone.utc) < cutoff:
                continue
            author = str((t.get("author") or {}).get("userName") or "")
            items.append(
                Item(
                    source="x",
                    layer="social",
                    region="overseas",
                    title="🔎 " + _headline(text),
                    url=str(t.get("url") or f"https://x.com/{author}/status/{tid}"),
                    published=created.astimezone(timezone.utc).isoformat(timespec="seconds") if created else "",
                    summary=text[:280],
                    heat=float(t.get("likeCount") or 0),
                    lang=str(t.get("lang") or "en"),
                    author=author,
                    extra={"tweet_id": tid, "keyword": q, "via": "apify"},
                )
            )
            local.add(tid)
            kept += 1
        print(f"  [x/apify] 「{q}」: {kept} 条")
        time.sleep(1)

    items.sort(key=lambda x: x.heat or 0, reverse=True)
    top = items[: c["max_total"]]
    for it in top:
        seen[str(it.extra.get("tweet_id"))] = today
    _save_seen(seen)
    return top


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("enabled:", enabled())
    for it in search():
        print(f"{it.published[:16]} ♥{int(it.heat or 0):<5} @{it.author:<16} {it.title[:60]}")
