"""正文与日期提取：把 RSS 摘要之外的东西补回来。

两个具体问题（都是在真实数据上量出来的）：
1. **评分只看摘要**：RSS 的 description 常常只有一两句，五轴里的 `nov`（信息增量）
   和 `cred`（证据强度）根本没法判 —— 质量天花板卡在这里。
2. **215 条里 43 条没有发布时间**：`_age_hours` 只好一律按 48 小时算，
   于是这些条目永远拿不到"新鲜"加成，也不会随时间衰减。

做法：对"够格进日报"的条目抓一次原文页，同时尝试读出发布日期。
抓不到就什么都不改 —— **绝不用推测的日期填空**，那会让评分凭空变准，其实是假的。
"""

from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml
from bs4 import BeautifulSoup

from . import net

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config" / "extract.yaml"

# 页面里这些块不是正文
DROP_TAGS = ("script", "style", "nav", "header", "footer", "aside", "form",
             "iframe", "noscript", "svg", "figure", "figcaption", "button", "select")
# 正文容器常见命名
BODY_HINTS = re.compile(
    r"(article|post|entry|content|markdown|story|prose|body|main|text)", re.I
)
META_DATE = (
    ("meta", {"property": "article:published_time"}),
    ("meta", {"property": "og:published_time"}),
    ("meta", {"itemprop": "datePublished"}),
    ("meta", {"name": "pubdate"}),
    ("meta", {"name": "publishdate"}),
    ("meta", {"name": "publish_date"}),
    ("meta", {"name": "date"}),
    ("meta", {"name": "sailthru.date"}),
    ("meta", {"name": "parsely-pub-date"}),
)
LOCAL_TZ = timezone(timedelta(hours=8))

_lock = threading.Lock()
_cache: dict[str, Any] = {"mtime": 0.0, "value": {}}


def config() -> dict[str, Any]:
    try:
        mtime = CONFIG_PATH.stat().st_mtime
    except OSError:
        return {}
    with _lock:
        if _cache["mtime"] == mtime:
            return _cache["value"]
        try:
            value = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            value = {}
        _cache.update(mtime=mtime, value=value)
        return value


# --------------------------------------------------------------------------- #
# 日期
# --------------------------------------------------------------------------- #

_DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M%z",
    "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日",
)


def parse_date(raw: str | None) -> str | None:
    """把各种写法的发布时间归一成 ISO8601；**解析不出来就返回 None，不猜**。"""
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None

    # 纯数字：秒级 / 毫秒级时间戳
    if re.fullmatch(r"\d{10}|\d{13}", text):
        ts = int(text)
        if len(text) == 13:
            ts //= 1000
        try:
            return datetime.fromtimestamp(ts, tz=LOCAL_TZ).isoformat()
        except Exception:
            return None

    cleaned = text.replace("Z", "+0000")
    # +08:00 → +0800，%z 才认
    cleaned = re.sub(r"([+-]\d{2}):(\d{2})$", r"\1\2", cleaned)
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
        if dt.tzinfo is None:
            # 没有时区的中文站点时间按北京时间理解（AIHOT 同样默认 +08:00），
            # 这一点在文档里写明，不假装是 UTC。
            dt = dt.replace(tzinfo=LOCAL_TZ)
        return dt.isoformat()
    return None


RELATIVE_MINUTES = re.compile(r"(\d+)\s*分钟前")
RELATIVE_HOURS = re.compile(r"(\d+)\s*小时前")
TODAY_AT = re.compile(r"今天\s*(\d{1,2}):(\d{2})")
YESTERDAY_AT = re.compile(r"昨天\s*(\d{1,2}):(\d{2})")
MONTH_DAY = re.compile(r"^(\d{1,2})-(\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?$")
MONTH_DAY_CN = re.compile(r"^(\d{1,2})月(\d{1,2})日(?:\s*(\d{1,2}):(\d{2}))?$")


def _month_day(month: int, day: int, hour: int, minute: int, now: datetime) -> str | None:
    """月日没有年份：取今年，落到未来就退回去年；不存在的日期返回 None。"""
    for year in (now.year, now.year - 1):
        try:
            dt = now.replace(year=year, month=month, day=day, hour=hour,
                             minute=minute, second=0, microsecond=0)
        except ValueError:
            return None  # 2 月 30 日这类
        if dt <= now:
            return dt.isoformat()
    return None


def parse_relative_date(text: str | None, now: datetime | None = None) -> str | None:
    """解析中文站点的相对时间（微博搜索页那套写法）。解析不出来返回 None。

    这些写法没有绝对年份，所以只能按"当前时间"反推；因此**只在能确定时才用**，
    推到未来的（今年不可能发生的月日）按去年算。
    """
    if not text:
        return None
    now = now or datetime.now(tz=LOCAL_TZ)
    raw = str(text).strip()
    if not raw:
        return None

    if raw in ("刚刚", "刚才", "just now"):
        return now.replace(microsecond=0).isoformat()

    m = RELATIVE_MINUTES.search(raw)
    if m:
        return (now - timedelta(minutes=int(m.group(1)))).replace(microsecond=0).isoformat()
    m = RELATIVE_HOURS.search(raw)
    if m:
        return (now - timedelta(hours=int(m.group(1)))).replace(microsecond=0).isoformat()

    m = TODAY_AT.search(raw)
    if m:
        return now.replace(hour=int(m.group(1)), minute=int(m.group(2)),
                           second=0, microsecond=0).isoformat()
    m = YESTERDAY_AT.search(raw)
    if m:
        base = now - timedelta(days=1)
        return base.replace(hour=int(m.group(1)), minute=int(m.group(2)),
                            second=0, microsecond=0).isoformat()

    m = MONTH_DAY.match(raw)
    if m:
        return _month_day(int(m.group(1)), int(m.group(2)),
                          int(m.group(3) or 0), int(m.group(4) or 0), now)

    m = MONTH_DAY_CN.match(raw)
    if m:
        return _month_day(int(m.group(1)), int(m.group(2)),
                          int(m.group(3) or 0), int(m.group(4) or 0), now)
    return parse_date(raw)


def _date_from_jsonld(soup: BeautifulSoup) -> str | None:
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        if "datePublished" not in raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            # 有的站会塞注释或多余逗号，退回正则抠
            m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', raw)
            return parse_date(m.group(1)) if m else None
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                if node.get("datePublished"):
                    got = parse_date(str(node["datePublished"]))
                    if got:
                        return got
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    return None


def extract_date(soup: BeautifulSoup) -> str | None:
    """按 meta → time[datetime] → JSON-LD 的顺序找发布日期。"""
    for tag_name, attrs in META_DATE:
        tag = soup.find(tag_name, attrs=attrs)
        if tag and tag.get("content"):
            got = parse_date(tag["content"])
            if got:
                return got
    time_tag = soup.find("time", attrs={"datetime": True})
    if time_tag:
        got = parse_date(time_tag.get("datetime"))
        if got:
            return got
    return _date_from_jsonld(soup)


# --------------------------------------------------------------------------- #
# 正文
# --------------------------------------------------------------------------- #

def _text_of(node: Any) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def extract_body(html: str, max_chars: int = 6000) -> str:
    """从页面里抠正文：先按语义标签，再按"段落最多的容器"。"""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(DROP_TAGS):
        tag.decompose()

    def density(node: Any) -> int:
        return sum(len(_text_of(p)) for p in node.find_all("p"))

    best = None
    best_score = 0
    for candidate in soup.find_all(["article", "main", "section", "div"]):
        hints = " ".join([
            " ".join(candidate.get("class") or []),
            candidate.get("id") or "",
        ])
        if not (candidate.name in ("article", "main") or BODY_HINTS.search(hints)):
            continue
        score = density(candidate)
        if score > best_score:
            best, best_score = candidate, score
    if best is None:
        best = soup.body or soup

    paragraphs = [_text_of(p) for p in best.find_all("p")]
    paragraphs = [p for p in paragraphs if len(p) >= 20]
    if not paragraphs:  # 没有 <p> 的站点（纯 <div> 排版）退回整块文本
        text = _text_of(best)
        return text[:max_chars]
    body = "\n".join(paragraphs)
    return body[:max_chars]


# --------------------------------------------------------------------------- #
# 抓取
# --------------------------------------------------------------------------- #

def _host(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    return (m.group(1) if m else "").lower()


def _skipped(url: str, conf: dict[str, Any]) -> bool:
    host = _host(url)
    if not host:
        return True
    if url.lower().endswith(".pdf"):
        return True
    return any(host == h or host.endswith("." + h) for h in (conf.get("skip_hosts") or []))


def fetch_html(url: str, *, use_proxy: bool, timeout: int) -> str | None:
    with net.session(use_proxy) as s:
        r = s.get(url, timeout=timeout, allow_redirects=True)
        if r.status_code != 200:
            return None
        if "html" not in (r.headers.get("content-type") or "").lower():
            return None
        # 中文站常不声明 charset，requests 会退回 ISO-8859-1，中文会变乱码
        if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
            r.encoding = r.apparent_encoding or "utf-8"
        return r.text


def enrich_item(item: Any, conf: dict[str, Any]) -> dict[str, Any]:
    """给一条补正文/日期。返回 `{body, published, error}`，不改 item 本身。"""
    url = getattr(item, "url", "") or ""
    if _skipped(url, conf):
        return {"error": "skipped"}
    use_proxy = (getattr(item, "region", "overseas") or "overseas") == "overseas"
    try:
        html = fetch_html(url, use_proxy=use_proxy, timeout=int(conf.get("timeout") or 20))
    except Exception as e:
        return {"error": f"{type(e).__name__}"}
    if not html:
        return {"error": "no-html"}

    out: dict[str, Any] = {}
    try:
        soup = BeautifulSoup(html, "html.parser")
        published = extract_date(soup)
        if published and not (getattr(item, "published", "") or "").strip():
            out["published"] = published
        body = extract_body(html, int(conf.get("max_chars") or 6000))
        # 太短的多半是拦截页/登录页/纯图页：宁可没有正文，也不要喂一段导航给模型
        if len(body) >= int(conf.get("min_body_chars") or 120):
            out["body"] = body
    except Exception as e:
        return {"error": f"parse:{type(e).__name__}"}
    return out or {"error": "empty"}


def enrich_items(items: list[Any]) -> dict[str, Any]:
    """按分数挑条目抓原文。返回统计，供日志。"""
    conf = config()
    if not conf.get("enabled", True):
        return {"skipped": "disabled"}

    min_score = float(conf.get("min_score") or 0)
    only_missing = bool(conf.get("only_when_missing", True))
    pool = []
    for it in items:
        extra = getattr(it, "extra", {}) or {}
        score = float(extra.get("score") or 0)
        if score < min_score:
            continue
        if only_missing and (getattr(it, "summary", "") or "").strip() and getattr(it, "published", ""):
            continue
        pool.append(it)

    pool.sort(key=lambda i: float((getattr(i, "extra", {}) or {}).get("score") or 0), reverse=True)
    max_items = int(conf.get("max_items") or 0)
    if max_items:
        pool = pool[:max_items]
    if not pool:
        return {"fetch": 0, "body": 0, "date": 0, "failed": 0}

    workers = max(1, int(conf.get("max_workers") or 4))
    stats = {"fetch": len(pool), "body": 0, "date": 0, "failed": 0, "skipped": 0}
    with ThreadPoolExecutor(max_workers=workers) as pool_ex:
        futures = {pool_ex.submit(enrich_item, it, conf): it for it in pool}
        for fut in as_completed(futures):
            it = futures[fut]
            try:
                got = fut.result()
            except Exception:
                got = {"error": "exception"}
            if got.get("error"):
                if got["error"] == "skipped":
                    stats["skipped"] += 1
                else:
                    stats["failed"] += 1
                continue
            if got.get("body"):
                it.extra["body"] = got["body"]
                stats["body"] += 1
            if got.get("published"):
                it.published = got["published"]
                stats["date"] += 1
    return stats
