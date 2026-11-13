"""各信息源适配器 + 源清单。

设计要点：每个源都归一化成 Item；源清单里显式标注“层 / 通道 / 状态”，
这样“覆盖全不全”是可检查的，而不是靠感觉。
"""

from __future__ import annotations

import html
import json
import urllib.parse
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote, urlparse

import yaml
from bs4 import BeautifulSoup

from . import xfeed
from . import apify_x
from . import agentcases
from . import extract as extract_mod
from .model import Item
from .net import get_json, get_text

X_ENABLED = xfeed.is_enabled()

COOKIE_PATH = Path(__file__).parent.parent / "config" / "cookies.yaml"
DOMESTIC_CONF_PATH = Path(__file__).parent.parent / "config" / "domestic.yaml"


def _domestic_conf(name: str) -> dict:
    try:
        data = yaml.safe_load(DOMESTIC_CONF_PATH.read_text(encoding="utf-8")) or {}
        return data.get(name) or {}
    except Exception:
        return {}


def _cookie_conf() -> dict:
    try:
        return yaml.safe_load(COOKIE_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


_COOKIES = _cookie_conf()
WEIBO_COOKIE = str((_COOKIES.get("weibo") or {}).get("cookie") or "").strip()
ZHIHU_COOKIE = str((_COOKIES.get("zhihu") or {}).get("cookie") or "").strip()

# ---------------------------------------------------------------- helpers


def _clean(text) -> str:
    if isinstance(text, (list, tuple)):
        text = " ".join(str(t) for t in text if t)
    if not isinstance(text, str):
        text = str(text) if text is not None else ""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _from_struct(tm) -> str:
    try:
        return _iso(datetime(*tm[:6], tzinfo=timezone.utc))
    except Exception:
        return ""


def parse_feed(xml_text: str) -> list[dict]:
    """同时兼容 RSS 2.0 与 Atom。"""
    root = ET.fromstring(xml_text)
    out: list[dict] = []

    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        d: dict = {"title": "", "link": "", "summary": "", "published": ""}
        for child in it:
            ctag = child.tag.split("}")[-1]
            if ctag == "title":
                d["title"] = _clean(child.text or "")
            elif ctag == "link":
                d["link"] = child.get("href") or (child.text or "").strip()
            elif ctag in ("description", "summary", "content"):
                if not d["summary"]:
                    d["summary"] = _clean(child.text or "")
            elif ctag in ("pubDate", "updated", "published"):
                raw = (child.text or "").strip()
                if not raw:
                    continue
                try:
                    d["published"] = _iso(parsedate_to_datetime(raw))
                except Exception:
                    try:
                        d["published"] = _iso(datetime.fromisoformat(raw.replace("Z", "+00:00")))
                    except Exception:
                        pass
        if d["title"] and d["link"]:
            out.append(d)
    return out


# ---------------------------------------------------------------- 榜单层


def hackernews(limit: int = 12) -> list[Item]:
    ids = get_json("https://hacker-news.firebaseio.com/v0/topstories.json")[:limit]
    items: list[Item] = []
    for i in ids:
        d = get_json(f"https://hacker-news.firebaseio.com/v0/item/{i}.json", timeout=10)
        if not d or not d.get("title"):
            continue
        items.append(
            Item(
                source="hackernews",
                layer="rank",
                title=d["title"],
                url=d.get("url") or f"https://news.ycombinator.com/item?id={i}",
                published=_iso(datetime.fromtimestamp(d.get("time", 0), tz=timezone.utc)),
                summary=f"{d.get('descendants', 0)} comments",
                heat=float(d.get("score", 0)),
                lang="en",
                extra={"hn_id": i},
            )
        )
    return items


def github_trending(limit: int = 10) -> list[Item]:
    week_ago = datetime.now(timezone.utc).date().fromordinal(
        datetime.now(timezone.utc).date().toordinal() - 7
    )
    q = quote(f"created:>{week_ago} stars:>50")
    data = get_json(
        f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page={limit}",
        use_proxy=False,
    )
    items = []
    for r in data.get("items", []):
        items.append(
            Item(
                source="github",
                layer="rank",
                title=f"{r['full_name']} — {r.get('description') or ''}"[:160],
                url=r["html_url"],
                published=_iso(datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))),
                summary=f"{r.get('language') or 'n/a'} · ★{r['stargazers_count']}",
                heat=float(r["stargazers_count"]),
                lang="en",
                author=r["owner"]["login"],
            )
        )
    return items


def bilibili(limit: int = 30) -> list[Item]:
    data = get_json(
        "https://api.bilibili.com/x/web-interface/ranking/v2?rid=36&type=all",
        headers={"Referer": "https://www.bilibili.com/"},
    )
    items = []
    for v in (data.get("data", {}).get("list") or [])[:limit]:
        items.append(
            Item(
                source="bilibili",
                layer="rank",
                title=v["title"],
                url=f"https://www.bilibili.com/video/{v['bvid']}",
                published=_iso(datetime.fromtimestamp(v.get("pubdate", 0), tz=timezone.utc)),
                summary=_clean(v.get("desc", ""))[:120],
                heat=float(v.get("stat", {}).get("view", 0)),
                author=v.get("owner", {}).get("name", ""),
            )
        )
    return items


def toutiao(limit: int = 50) -> list[Item]:
    data = get_json("https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc")
    items = []
    for v in (data.get("data") or [])[:limit]:
        items.append(
            Item(
                source="toutiao",
                layer="rank",
                title=v.get("Title", ""),
                url=v.get("Url", ""),
                summary=_clean(v.get("LabelDesc") or v.get("InterestCategory") or ""),
                heat=float(v.get("HotValue") or 0),
            )
        )
    return items


# ---------------------------------------------------------------- 广谱层


def rss_source(url: str, source: str, layer: str = "broad", limit: int = 12, lang="zh",
               use_proxy: bool = False):
    def _fetch() -> list[Item]:
        feed = parse_feed(get_text(url, use_proxy=use_proxy))
        return [
            Item(
                source=source,
                layer=layer,
                title=d["title"],
                url=d["link"],
                published=d["published"],
                summary=d["summary"][:180],
                lang=lang,
            )
            for d in feed[:limit]
        ]

    return _fetch


# ---------------------------------------------------------------- 一手源头


def smolai(limit: int = 4) -> list[Item]:
    """smol.ai 的 AINews：每天一篇长文汇总。RSS 已停更，改解析首页卡片。"""
    soup = BeautifulSoup(get_text("https://news.smol.ai/", timeout=40), "html.parser")
    items: list[Item] = []
    for card in soup.select("article.post-card")[:limit]:
        a = card.select_one("h3 a") or card.select_one('a[href^="/p/"]')
        if not (a and a.get("href") and a.get_text(strip=True)):
            continue
        href = a["href"]
        # news.smol.ai 是镜像，/p/ 详情页 404；正文在 latent.space，slug 相同
        url = href.replace("https://news.smol.ai", "https://www.latent.space")
        if url.startswith("/"):
            url = "https://www.latent.space" + url
        published = ""
        t = card.select_one("time[datetime]")
        if t:
            try:
                published = _iso(datetime.fromisoformat(t["datetime"].replace("Z", "+00:00")))
            except Exception:
                pass
        items.append(
            Item(
                source="smolai",
                layer="primary",
                title=a.get_text(strip=True),
                url=url,
                published=published,
                lang="en",
            )
        )

    # 卡片没有摘要，抓详情页 og:description 补上（失败不影响）
    for it in items:
        try:
            page = get_text(it.url, timeout=25)
            m = re.search(
                r'<meta[^>]+(?:name|property)="(?:description|og:description)"[^>]+content="([^"]{20,400})"',
                page,
            )
            if m:
                it.summary = _clean(m.group(1))[:200]
        except Exception:
            pass
    return items


def the_batch(limit: int = 4) -> list[Item]:
    """吴恩达团队的 The Batch：无 RSS，解析列表页后按日期倒序。"""
    soup = BeautifulSoup(get_text("https://www.deeplearning.ai/the-batch/", timeout=30), "html.parser")
    parsed: list[tuple[datetime, Item]] = []
    for art in soup.select("article"):
        a = art.select_one('a[href^="/the-batch/issue"]')
        h3 = art.select_one("h3")
        if not (a and h3):
            continue
        published, dt = "", None
        date_el = art.select_one('a[href^="/the-batch/tag/"]')
        if date_el:
            try:
                dt = datetime.strptime(date_el.get_text(strip=True), "%b %d, %Y").replace(tzinfo=timezone.utc)
                published = _iso(dt)
            except Exception:
                dt = None
        desc = art.select_one("p")
        item = Item(
            source="thebatch",
            layer="primary",
            title=h3.get_text(strip=True),
            url="https://www.deeplearning.ai" + a["href"],
            published=published,
            summary=(desc.get_text(" ", strip=True) if desc else "")[:200],
            lang="en",
        )
        parsed.append((dt or datetime(1970, 1, 1, tzinfo=timezone.utc), item))
    parsed.sort(key=lambda x: x[0], reverse=True)
    return [it for _, it in parsed[:limit]]


def hf_papers(limit: int = 8) -> list[Item]:
    """Hugging Face Daily Papers：社区投票选出的当日热门论文。"""
    data = get_json("https://huggingface.co/api/daily_papers?limit=40", use_proxy=True, timeout=30)
    rows = []
    for d in data:
        paper = d.get("paper", {})
        if not paper.get("id"):
            continue
        summary = paper.get("ai_summary") or d.get("summary") or paper.get("summary") or ""
        if isinstance(summary, dict):
            summary = summary.get("text", "")
        rows.append(
            Item(
                source="hf_papers",
                layer="primary",
                title=paper.get("title", ""),
                url=f"https://huggingface.co/papers/{paper['id']}",
                published=paper.get("publishedAt", ""),
                summary=str(summary)[:220],
                heat=float(paper.get("upvotes") or 0),
                lang="en",
                author=", ".join(a.get("name", "") for a in paper.get("authors", [])[:2]),
            )
        )
    rows.sort(key=lambda x: (x.heat or 0, x.published), reverse=True)
    return rows[:limit]


# ---------------------------------------------------------------- 搜索层


def google_news(queries: list[str], per_query: int = 6) -> list[Item]:
    items: list[Item] = []
    for q in queries:
        url = (
            "https://news.google.com/rss/search?q="
            + quote(q)
            + "&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
        )
        try:
            for d in parse_feed(get_text(url, use_proxy=True))[:per_query]:
                items.append(
                    Item(
                        source="google_news",
                        layer="search",
                        title=d["title"],
                        url=d["link"],
                        published=d["published"],
                        summary=d["summary"][:160],
                        lang="zh",
                        extra={"query": q},
                    )
                )
        except Exception as e:  # 单个 query 失败不影响整体
            print(f"  [google_news] {q} 失败: {e}")
        time.sleep(0.5)
    return items


# ---------------------------------------------------------------- 国内热榜（需 Cookie）


def weibo_hot(limit: int = 50) -> list[Item]:
    if not WEIBO_COOKIE:
        return []
    data = get_json(
        "https://weibo.com/ajax/side/hotSearch",
        headers={
            "Cookie": WEIBO_COOKIE,
            "Referer": "https://weibo.com/",
            "Accept": "application/json, text/plain, */*",
        },
        timeout=25,
    )
    rows = ((data.get("data") or {}).get("realtime") or [])[:limit]
    out: list[Item] = []
    for r in rows:
        word = (r.get("word") or "").strip()
        if not word:
            continue
        out.append(
            Item(
                source="weibo",
                layer="rank",
                region="domestic",
                title=word,
                url="https://s.weibo.com/weibo?q=%23" + quote(word) + "%23",
                summary=(r.get("label_name") or "").strip(),
                heat=float(r.get("num") or 0),
                lang="zh",
            )
        )
    return out


def zhihu_hot(limit: int = 50) -> list[Item]:
    if not ZHIHU_COOKIE:
        return []
    page = get_text(
        "https://www.zhihu.com/hot",
        headers={"Cookie": ZHIHU_COOKIE, "Referer": "https://www.zhihu.com/"},
        timeout=30,
    )
    m = re.search(r'<script id="js-initialData" type="text/json">(.*?)</script>', page, re.S)
    if not m:
        return []
    data = json.loads(m.group(1))
    rows = (((data.get("initialState") or {}).get("topstory") or {}).get("hotList") or [])[:limit]
    out: list[Item] = []
    for it in rows:
        target = it.get("target") or {}
        title = ((target.get("titleArea") or {}).get("text") or "").strip()
        if not title:
            continue
        out.append(
            Item(
                source="zhihu",
                layer="rank",
                region="domestic",
                title=title,
                url=(target.get("link") or {}).get("url") or "https://www.zhihu.com/hot",
                summary=((target.get("metricsArea") or {}).get("text") or "").strip(),
                heat=float(((target.get("metricsArea") or {}).get("followers") or 0)),
                lang="zh",
            )
        )
    return out


# ---------------------------------------------------------------- 国内搜索（关键词模式）


def weibo_search(keywords: list[str] | None = None, per_keyword: int | None = None) -> list[Item]:
    """微博网页搜索：s.weibo.com 的 HTML 结果，按关键词取，科技含量比热搜高。"""
    if not WEIBO_COOKIE:
        return []
    conf = _domestic_conf("weibo")
    kws = keywords or conf.get("keywords") or ["AI"]
    limit = int(per_keyword or conf.get("per_keyword") or 8)
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    out: list[Item] = []
    seen: set[str] = set()
    for kw in kws:
        try:
            page = get_text(
                "https://s.weibo.com/weibo?q=" + quote(str(kw)),
                headers={"Cookie": WEIBO_COOKIE, "Referer": "https://weibo.com/", "User-Agent": ua},
                timeout=30,
            )
        except Exception as e:
            print(f"  [weibo] 搜索「{kw}」失败: {type(e).__name__}: {e}")
            continue

        got = 0
        texts = re.findall(r'<p[^>]*node-type="feed_list_content"[^>]*>(.*?)</p>', page, re.S)
        links = re.findall(r'href="(//weibo\.com/\d+/[A-Za-z0-9]+)"', page)
        mids = re.findall(r'\bmid="(\d{10,})"', page)
        # 搜索结果卡片里有「今天 09:12」「11-09」这类时间；条数与正文对齐时才用，
        # 对不上就留空 —— 宁可没有日期，也不要给一条错的时间。
        stamps = [re.sub(r"<[^>]+>", " ", s).strip()
                  for s in re.findall(r'<div class="from[^"]*"[^>]*>(.*?)</div>', page, re.S)]
        aligned = len(stamps) == len(texts)
        for idx, raw in enumerate(texts):
            if got >= limit:
                break
            text = _clean(raw)
            if len(text) < 12:
                continue
            if idx < len(links):
                url = "https:" + links[idx]
            elif idx < len(mids):
                url = "https://m.weibo.cn/detail/" + mids[idx]
            else:
                url = f"https://s.weibo.com/weibo?q={quote(str(kw))}&p={idx + 1}"
            if url in seen:
                continue
            seen.add(url)
            out.append(
                Item(
                    source="weibo",
                    layer="social",
                    region="domestic",
                    title=text[:70],
                    url=url,
                    summary=text[:200],
                    published=extract_mod.parse_relative_date(stamps[idx]) or "" if aligned else "",
                    lang="zh",
                    extra={"keyword": kw},
                )
            )
            got += 1
        time.sleep(1.5)

    print(f"  [weibo] 搜索 {len(kws)} 个词，得 {len(out)} 条")
    return out


def zhihu_search(keywords: list[str] | None = None, per_keyword: int | None = None) -> list[Item]:
    """知乎搜索 API（v4/search_v3）：返回回答/文章，带赞同数。"""
    if not ZHIHU_COOKIE:
        return []
    conf = _domestic_conf("zhihu")
    kws = keywords or conf.get("keywords") or ["AI"]
    limit = int(per_keyword or conf.get("per_keyword") or 8)
    out: list[Item] = []
    seen: set[str] = set()
    for kw in kws:
        try:
            data = get_json(
                "https://www.zhihu.com/api/v4/search_v3?t=general&q="
                + quote(str(kw))
                + "&correction=1&offset=0&limit=20",
                headers={
                    "Cookie": ZHIHU_COOKIE,
                    "Referer": "https://www.zhihu.com/search",
                    "x-requested-with": "fetch",
                },
                timeout=30,
            )
        except Exception as e:
            print(f"  [zhihu] 搜索「{kw}」失败: {type(e).__name__}: {e}")
            continue

        got = 0
        for row in data.get("data") or []:
            if row.get("type") != "search_result":
                continue
            obj = row.get("object") or {}
            if obj.get("type") not in ("answer", "article", "zvideo"):
                continue
            title = _clean(str(obj.get("title") or (obj.get("question") or {}).get("name") or ""))
            if not title:
                continue
            href = str(obj.get("url") or "")
            href = (
                href.replace("https://api.zhihu.com/answers/", "https://www.zhihu.com/answer/")
                .replace("https://api.zhihu.com/articles/", "https://zhuanlan.zhihu.com/p/")
                .replace("https://api.zhihu.com/zvideos/", "https://www.zhihu.com/zvideo/")
            )
            if href in seen:
                continue
            seen.add(href)
            # search_v3 的 created_time 是秒级时间戳；之前被丢掉了，
            # 导致知乎条目全部"无发布时间"，在评分里被当成 48 小时前的老料。
            created = obj.get("created_time") or obj.get("updated_time")
            published = ""
            if created:
                try:
                    published = _iso(datetime.fromtimestamp(int(created), tz=timezone.utc))
                except Exception:
                    published = ""
            out.append(
                Item(
                    source="zhihu",
                    layer="social",
                    region="domestic",
                    title=title[:90],
                    url=href or "https://www.zhihu.com/hot",
                    summary=_clean(str(obj.get("excerpt") or ""))[:200],
                    heat=float(obj.get("voteup_count") or 0),
                    published=published,
                    lang="zh",
                    extra={"keyword": kw},
                )
            )
            got += 1
            if got >= limit:
                break
        time.sleep(1.2)

    print(f"  [zhihu] 搜索 {len(kws)} 个词，得 {len(out)} 条")
    return out


# ---------------------------------------------------------------- 羊毛福利（搜索型）


def deals_news(queries: list[str] | None = None, per_query: int = 4) -> list[Item]:
    """用 Google News 搜"免费额度 / 免费 API / free credits"这类羊毛线索。"""
    qs = queries or ["AI 免费额度", "免费 API", "免费 GPU 算力", "free AI credits"]
    items: list[Item] = []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
    for q in qs:
        url = (
            "https://news.google.com/rss/search?q="
            + quote(f"{q} when:7d")
            + "&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
        )
        try:
            for d in parse_feed(get_text(url, use_proxy=True))[:per_query]:
                if d["published"][:10] and d["published"][:10] < cutoff:
                    continue
                if any(j in d["title"] for j in ("下载", "在线观看", "破解", "最新版", "网址", "apk")):
                    continue
                items.append(
                    Item(
                        source="deals",
                        layer="search",
                        region="domestic",
                        title=d["title"],
                        url=d["link"],
                        published=d["published"],
                        summary=d["summary"][:160],
                        lang="zh",
                        extra={"deal": True, "keyword": q},
                    )
                )
        except Exception as e:
            print(f"  [deals] 「{q}」失败: {type(e).__name__}: {e}")
        time.sleep(0.6)
    return items


# ---------------------------------------------------------------- Telegram（公开频道）


def _tg_conf() -> dict:
    try:
        return yaml.safe_load((Path(__file__).parent.parent / "config" / "telegram.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


TG_CHANNELS = []
for _c in (_tg_conf().get("channels") or []):
    if isinstance(_c, dict):
        TG_CHANNELS.append(
            (str(_c.get("name") or _c.get("channel") or "").lstrip("@"), str(_c.get("region") or "domestic"))
        )
    elif str(_c).strip():
        TG_CHANNELS.append((str(_c).lstrip("@"), "domestic"))


TG_SEEN_PATH = Path(__file__).parent.parent / "data" / "tg_seen.json"


def _tg_seen() -> dict:
    try:
        return json.loads(TG_SEEN_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _tg_save_seen(seen: dict) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    TG_SEEN_PATH.parent.mkdir(exist_ok=True)
    TG_SEEN_PATH.write_text(
        json.dumps({k: v for k, v in seen.items() if v >= cutoff}, ensure_ascii=False), encoding="utf-8"
    )


def telegram_channels(limit: int | None = None) -> list[Item]:
    conf = _tg_conf()
    channels = TG_CHANNELS
    if not channels:
        return []
    limit = int(limit or conf.get("limit") or 20)
    use_proxy = bool(conf.get("use_proxy", True))
    seen = _tg_seen()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    items: list[Item] = []
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    for ch, ch_region in channels:
        try:
            page = get_text(
                f"https://t.me/s/{ch}",
                headers={"User-Agent": ua},
                use_proxy=use_proxy,
                timeout=40,
            )
        except Exception as e:
            print(f"  [telegram] @{ch} 失败: {type(e).__name__}: {e}")
            continue
        blocks = re.split(r'<div class="tgme_widget_message_wrap', page)[1:]
        got = 0
        for block in reversed(blocks):  # 页面是旧→新，反转成新→旧
            m_text = re.search(
                r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, re.S
            )
            if not m_text:
                continue
            text = _clean(m_text.group(1))
            if len(text) < 15:
                continue
            # 频道里混杂的博彩/广告，先挡掉
            if any(j in text for j in ("博彩", "体育", "信誉", "押", "钱包", "加微信", "开户",
                                       "彩票", "棋牌", "刷单", "返利", "官网", "代理")):
                continue
            m_post = re.search(r'data-post="([^"]+)"', block)
            m_time = re.search(r'<time[^>]*datetime="([^"]+)"', block)
            msg_id = m_post.group(1) if m_post else ""
            if msg_id and msg_id in seen:
                continue
            url = f"https://t.me/{msg_id}" if msg_id else f"https://t.me/s/{ch}"
            published = ""
            if m_time:
                try:
                    published = _iso(datetime.fromisoformat(m_time.group(1).replace("Z", "+00:00")))
                except Exception:
                    published = ""
            items.append(
                Item(
                    source="telegram",
                    layer="social",
                    region=ch_region,
                    title=text[:70],
                    url=url,
                    published=published,
                    summary=text[:220],
                    lang="zh" if ch_region == "domestic" else "en",
                    extra={"channel": ch, "region": ch_region},
                )
            )
            got += 1
            if msg_id:
                seen[msg_id] = today
            if got >= limit:
                break
        print(f"  [telegram] @{ch}: {got} 条")
    _tg_save_seen(seen)
    return items


# ---------------------------------------------------------------- 源清单

REGISTRY: list[dict] = [
    # id, 名称, 层, 通道, 状态, 是否启用
    {"id": "smolai", "name": "smol.ai AINews", "layer": "primary", "access": "直连", "status": "ok", "enabled": True},
    {"id": "thebatch", "name": "The Batch", "layer": "primary", "access": "直连", "status": "ok", "enabled": True},
    {"id": "hf_papers", "name": "HF Daily Papers", "layer": "primary", "access": "代理", "status": "ok", "enabled": True},
    {"id": "hackernews", "name": "Hacker News", "layer": "rank", "access": "直连", "status": "ok", "enabled": True},
    {"id": "github", "name": "GitHub 新项目", "layer": "rank", "access": "直连", "status": "ok", "enabled": True},
    {"id": "bilibili", "name": "B站科技区", "layer": "rank", "access": "直连", "status": "ok", "enabled": True},
    {"id": "toutiao", "name": "头条热榜", "layer": "rank", "access": "直连", "status": "ok", "enabled": True},
    {"id": "arxiv", "name": "arXiv cs.AI/CL", "layer": "broad", "access": "直连", "status": "ok", "enabled": True},
    {"id": "kr36", "name": "36氪", "layer": "broad", "access": "直连", "status": "ok", "enabled": True},
    {"id": "sspai", "name": "少数派", "layer": "broad", "access": "直连", "status": "ok", "enabled": True},
    {"id": "google_news", "name": "Google News 搜索", "layer": "search", "access": "代理", "status": "ok", "enabled": True},
    {"id": "deals", "name": "羊毛情报", "layer": "search", "access": "代理", "status": "ok", "enabled": True},
    {"id": "agentcases", "name": "AI Agent 用例", "layer": "broad", "access": "代理", "status": "ok", "enabled": True},
    {"id": "alphaxiv", "name": "alphaXiv", "layer": "primary", "access": "参考页", "status": "无公开 API", "enabled": False},
    {"id": "lmarena", "name": "LMArena", "layer": "primary", "access": "参考页", "status": "403 受限", "enabled": False},
    {"id": "artificial_analysis", "name": "Artificial Analysis", "layer": "primary", "access": "参考页", "status": "无公开 API", "enabled": False},
    {"id": "weibo", "name": "微博热搜", "layer": "rank", "access": "Cookie", "status": "ok" if WEIBO_COOKIE else "需 Cookie", "enabled": bool(WEIBO_COOKIE)},
    {"id": "zhihu", "name": "知乎热榜", "layer": "rank", "access": "Cookie", "status": "ok" if ZHIHU_COOKIE else "需 Cookie", "enabled": bool(ZHIHU_COOKIE)},
    {"id": "x", "name": "X / Twitter", "layer": "social", "access": "fxtwitter", "status": "ok" if X_ENABLED else "未启用", "enabled": X_ENABLED},
    {"id": "telegram", "name": "Telegram 频道", "layer": "social", "access": "代理", "status": "ok" if TG_CHANNELS else "未配置", "enabled": bool(TG_CHANNELS)},
    {"id": "reddit", "name": "Reddit", "layer": "social", "access": "代理", "status": "403 受限", "enabled": False},
    {"id": "gdelt", "name": "GDELT 全球新闻", "layer": "search", "access": "代理", "status": "429 限流", "enabled": False},
    {"id": "v2ex", "name": "V2EX", "layer": "rank", "access": "直连", "status": "不可达", "enabled": False},
]


# ---- 额外 RSS 源（config/feeds.yaml）：加源只改配置 ----
FEEDS_PATH = Path(__file__).parent.parent / "config" / "feeds.yaml"


def _load_feeds() -> list[dict]:
    """读 feeds.yaml：行业包里有就用包里的，没有用 config/ 的。"""
    try:
        from . import industry

        data = industry.load("feeds.yaml")
        if data:
            return list(data.get("feeds") or [])
    except Exception:
        pass
    try:
        data = yaml.safe_load(FEEDS_PATH.read_text(encoding="utf-8")) or {}
        return list(data.get("feeds") or [])
    except Exception:
        return []


def _load_feeds() -> list[dict]:
    """读 feeds.yaml：行业包里有就用包里的，没有用 config/ 的。

    这是「一个站一个行业」的关键 —— AIDD 站的源不该出现在 AI 站的清单里。
    """
    try:
        from . import industry

        data = industry.load("feeds.yaml")
        if data and data.get("feeds"):
            return [f for f in data["feeds"] if f.get("id") and f.get("url")]
    except Exception:
        pass
    try:
        data = yaml.safe_load(FEEDS_PATH.read_text(encoding="utf-8")) or {}
        return [f for f in (data.get("feeds") or []) if f.get("id") and f.get("url")]
    except Exception:
        return []


FEEDS = _load_feeds()
FEED_REGION = {f["id"]: f.get("region", "overseas") for f in FEEDS}
for _f in FEEDS:
    REGISTRY.append(
        {
            "id": _f["id"],
            "name": _f.get("name") or _f["id"],
            "layer": _f.get("layer", "broad"),
            "access": "代理" if _f.get("proxy") else "直连",
            "status": "ok",
            "enabled": True,
            "region": _f.get("region", "overseas"),
        }
    )


# 国外 / 国内：网站与日报按这个分区。改这里就能调整某个源的归属。
REGION = {
    "smolai": "overseas",
    "thebatch": "overseas",
    "hf_papers": "overseas",
    "hackernews": "overseas",
    "github": "overseas",
    "arxiv": "overseas",
    "x": "overseas",
    "telegram": "overseas",
    "reddit": "overseas",
    "gdelt": "overseas",
    "alphaxiv": "overseas",
    "lmarena": "overseas",
    "artificial_analysis": "overseas",
    "bilibili": "domestic",
    "toutiao": "domestic",
    "kr36": "domestic",
    "sspai": "domestic",
    "google_news": "domestic",
    "deals": "domestic",
    "agentcases": "overseas",
    "weibo": "domestic",
    "zhihu": "domestic",
    "v2ex": "domestic",
}


def region_of(source_id: str) -> str:
    return REGION.get(source_id) or FEED_REGION.get(source_id) or "overseas"


def _x_fetch_all() -> list[Item]:
    """X：免费时间线 + 关键词搜索（Apify 有结果用 Apify，否则退回免费镜像）。"""
    items = xfeed.fetch()
    if apify_x.enabled():
        got = apify_x.search()
        items += got if got else xfeed.search()
    else:
        items += xfeed.search()
    return items


def _feed_field(sid: str, field: str = "url") -> str:
    """从 feeds.yaml 里取某个源的原始字段。

    REGISTRY 里是**装饰后**的源（只留 id/name/layer/tier/enabled 等），
    url 这种抓取参数会被丢掉，所以这里回原始配置里查。
    """
    try:
        from . import industry

        data = industry.load("feeds.yaml") or {}
        rows = data.get("feeds") if isinstance(data, dict) else data
        for row in rows or []:
            if str(row.get("id")) == sid:
                return str(row.get(field) or "")
    except Exception:
        return ""
    return ""


def build_fetchers() -> list[tuple[str, callable]]:
    """返回 [(source_id, callable)]，只包含 enabled 的源。"""
    fetchers: list[tuple[str, callable]] = []
    for s in REGISTRY:
        if not s["enabled"]:
            continue
        # isolated：抓了但不进任何公开页面（内部观察用）
        if str(s.get("participation_mode") or "") == "isolated":
            continue
        sid = s["id"]
        if sid == "x":
            fetchers.append((sid, _x_fetch_all))
        elif sid == "weibo":
            fetchers.append(
                (sid, weibo_search if _domestic_conf("weibo").get("mode") == "search" else weibo_hot)
            )
        elif sid == "zhihu":
            fetchers.append(
                (sid, zhihu_search if _domestic_conf("zhihu").get("mode") == "search" else zhihu_hot)
            )
        elif sid == "smolai":
            fetchers.append((sid, smolai))
        elif sid == "thebatch":
            fetchers.append((sid, the_batch))
        elif sid.startswith("pubmed"):
            from . import pubmed as _pm

            _q = urllib.parse.unquote(_feed_field(sid))
            fetchers.append((sid, (lambda u=_q, i=sid: _pm.pubmed(
                u, limit=12, source_id=i))))
        elif sid == "hf_papers":
            fetchers.append((sid, hf_papers))
        elif sid == "hackernews":
            fetchers.append((sid, hackernews))
        elif sid == "github":
            fetchers.append((sid, github_trending))
        elif sid == "bilibili":
            fetchers.append((sid, bilibili))
        elif sid == "toutiao":
            fetchers.append((sid, toutiao))
        elif sid == "arxiv":
            fetchers.append(
                (
                    sid,
                    rss_source(
                        "https://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.CL&sortBy=submittedDate&sortOrder=descending&max_results=12",
                        "arxiv",
                        lang="en",
                    ),
                )
            )
        elif sid == "kr36":
            fetchers.append((sid, rss_source("https://www.36kr.com/feed", "kr36")))
        elif sid == "sspai":
            fetchers.append((sid, rss_source("https://sspai.com/feed", "sspai")))
        elif sid == "google_news":
            fetchers.append((sid, lambda: google_news(["大模型", "AI 创业"], per_query=6)))
        elif sid == "deals":
            fetchers.append((sid, deals_news))
        elif sid == "telegram":
            fetchers.append((sid, telegram_channels))
        elif sid == "agentcases":
            fetchers.append((sid, agentcases.fetch))
    for f in FEEDS:
        fetchers.append(
            (
                f["id"],
                rss_source(
                    f["url"],
                    f["id"],
                    layer=f.get("layer", "broad"),
                    limit=int(f.get("limit", 10)),
                    lang="zh" if f.get("region") == "domestic" else "en",
                    use_proxy=bool(f.get("proxy")),
                ),
            )
        )
    seen: set[str] = set()
    uniq: list[tuple[str, object]] = []
    for sid, fn in fetchers:
        if sid in seen:
            continue
        seen.add(sid)
        uniq.append((sid, fn))
    return uniq

# ---------------------------------------------------------------- 分级与参与方式
#
# 对齐 AIHOT 的信源字段（docs/customize.md 第 3 节）：
#   tier                 T1 官方一手 / T1_5 官方账号 / T2 媒体与个人 / EXCLUDE_MP 不参与精选
#   participation_mode   editorial 进精选与全部；hot_signal 只作热度证据；isolated 不进任何公开页
#   site_fulltext        站内能不能展示正文（**默认关**，只给摘要与原文链接）
#   syndicate_fulltext   全文 RSS 能不能带正文（只在 site_fulltext 也开时生效）
#   owner_entity_id      属于哪家公司；同一家的多个源在热度里只算一个参与方
#
# 默认值按 layer 推导，单个源可在 config/sources.yaml 里覆盖。

_LAYER_TIER = {"primary": "T1", "rank": "T1_5", "broad": "T2", "search": "T2", "social": "T2"}
_LAYER_MODE = {"primary": "editorial", "broad": "editorial",
               "rank": "hot_signal", "search": "hot_signal", "social": "hot_signal"}


def _source_overrides() -> dict[str, dict]:
    """config/sources.yaml 里的逐源覆盖（可选）。格式：sources: [{id: x, tier: T1, ...}]"""
    try:
        import yaml

        from . import industry

        data = industry.load("sources.yaml")
        if data:
            return data
        if not path.exists():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return {str(r["id"]): r for r in (data.get("sources") or [])
                if isinstance(r, dict) and r.get("id")}
    except Exception:
        return {}


def _decorate_sources() -> None:
    overrides = _source_overrides()
    # 行业包可以整批停源（AIDD 站不需要 AI 通用资讯）
    disabled_in_pack = set()
    try:
        from . import industry

        conf = industry.load("sources.yaml") or {}
        disabled_in_pack = {str(x) for x in (conf.get("disable") or [])}
    except Exception:
        disabled_in_pack = set()
    for src in REGISTRY:
        if str(src.get("id")) in disabled_in_pack:
            src["enabled"] = False
        src.setdefault("tier", _LAYER_TIER.get(src.get("layer"), "T2"))
        src.setdefault("participation_mode", _LAYER_MODE.get(src.get("layer"), "editorial"))
        src.setdefault("site_fulltext", False)
        src.setdefault("syndicate_fulltext", False)
        src.setdefault("owner_entity_id", None)
        patch = overrides.get(str(src.get("id"))) or {}
        for key, value in patch.items():
            if key != "id":
                src[key] = value


_decorate_sources()


def source_meta(source_id: str) -> dict:
    """取一个源的分级信息（页脚、条目页、热度都用这个）。"""
    for src in REGISTRY:
        if src.get("id") == source_id:
            return src
    return {}
