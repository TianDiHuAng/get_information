"""多出口：RSS、公共 JSON 接口、`llms.txt`。

为什么这三样值得做（吸收自 AIHOT 的"同一个公开读取层，多个出口"）：
- **RSS**：读者可以不打开网站就订阅；也是"今天出了什么"最省事的通知方式；
- **JSON**：给脚本和 Agent 用，比解析 HTML 稳得多；
- **`llms.txt`**：让大模型在读页面之前就知道这个站有什么、去哪拿，不用猜。

设计上刻意和 AIHOT 保持一致的一条规则：**出口只读同一份数据**。
这里所有出口都从 `payload`（当天落库的那批条目）+ `edition` 的编排结果生成，
不重新判断、不重新排序，所以网站、日报、RSS 说的永远是同一件事。

文件落在 `site/` 下，`serve.py` 直接就能访问（`/feed.xml`、`/api/v1/latest.json`）。
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import yaml

from . import edition

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config" / "export.yaml"

_lock = threading.Lock()
_cache: dict[str, Any] = {"mtime": 0.0, "value": {}}


def config() -> dict[str, Any]:
    try:
        mtime = CONFIG_PATH.stat().st_mtime
    except OSError:
        return {"base_url": "http://localhost:8123", "feed_items": 50, "api_items": 200}
    with _lock:
        if _cache["mtime"] == mtime:
            return _cache["value"]
        try:
            value = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            value = {}
        _cache.update(mtime=mtime, value=value)
        return value


def _one_line(text: str, limit: int = 300) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()[:limit]


def _pub_date(raw: str, fallback: datetime) -> str:
    """ISO 时间 → RFC 822（RSS 要求）。解析不出来用现在，不编一个过去的时间。"""
    try:
        dt = datetime.fromisoformat((raw or "").replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return format_datetime(dt)
    except Exception:
        return format_datetime(fallback)


def _category(it: dict[str, Any]) -> str:
    return ((it.get("extra") or {}).get("structure") or {}).get("category") or "other"


# --------------------------------------------------------------------------- #
# RSS
# --------------------------------------------------------------------------- #

def render_rss(items: list[dict[str, Any]], *, title: str, link: str, description: str,
               self_url: str | None = None) -> str:
    now = datetime.now(timezone.utc)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "<channel>",
        f"<title>{escape(title)}</title>",
        f"<link>{escape(link)}</link>",
        f"<description>{escape(description)}</description>",
        "<language>zh-CN</language>",
        f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>",
        # rel="self" 要指向 feed 文件本身，不是站点首页；阅读器靠它识别同一份订阅
        f'<atom:link href="{escape(self_url or link)}" rel="self" type="application/rss+xml"/>',
    ]
    for it in items:
        extra = it.get("extra") or {}
        desc = _one_line(it.get("summary") or "")
        crowd = ""
        size = int(extra.get("event_size") or 1)
        if size > 1:
            crowd = f"（{size} 篇报道）"
        parts += [
            "<item>",
            f"<title>{escape((it.get('title') or '') + crowd)}</title>",
            f"<link>{escape(it.get('url') or '')}</link>",
            f'<guid isPermaLink="true">{escape(it.get("url") or "")}</guid>',
            f"<pubDate>{_pub_date(it.get('published') or '', now)}</pubDate>",
            f"<description>{escape(desc)}</description>",
            f"<category>{escape(_category(it))}</category>",
            f"<source>{escape(it.get('source') or '')}</source>",
            "</item>",
        ]
    parts += ["</channel>", "</rss>", ""]
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# JSON
# --------------------------------------------------------------------------- #

def render_api(items: list[dict[str, Any]], *, generated_at: str) -> dict[str, Any]:
    out = []
    for it in items:
        extra = it.get("extra") or {}
        att = extra.get("attention") or {}
        st = extra.get("structure") or {}
        out.append({
            "title": it.get("title"),
            "url": it.get("url"),
            "source": it.get("source"),
            "layer": it.get("layer"),
            "region": it.get("region"),
            "published": it.get("published") or None,
            "summary": _one_line(it.get("summary") or "", 500) or None,
            "score": extra.get("score"),
            "attention": {
                "score": att.get("score"),
                "threshold": att.get("threshold"),
                "selected": att.get("selected"),
                "itype": att.get("itype"),
                "axes": att.get("axes"),
                "reason": att.get("reason"),
            } if att.get("available") else None,
            "structure": {
                "category": st.get("category"),
                "tags": st.get("tags"),
                "subjects": st.get("subjects"),
                "scope": st.get("scope"),
            } if st else None,
            "event": {
                "id": extra.get("event_id"),
                "size": extra.get("event_size"),
                "sources": extra.get("event_sources"),
                "heat": extra.get("event_heat"),
                "representative": extra.get("event_representative"),
            } if extra.get("event_size") else None,
        })
    return {
        "generated_at": generated_at,
        "count": len(out),
        "items": out,
    }


def render_llms(base_url: str, counts: dict[str, Any]) -> str:
    base = base_url.rstrip("/")
    return "\n".join([
        "# Z-Bit",
        "",
        "> 每天采集 AI 前沿信息（一手博客 / 论文 / X / Telegram / 国内科技媒体），",
        "> 用五轴模型打分、按事件聚簇、按规则编成一份日报。",
        "",
        "## 怎么读这个站",
        "",
        f"- 今日要闻：{base}/",
        f"- 今日要闻 RSS：{base}/feed.xml",
        f"- 全部动态 RSS：{base}/feed-all.xml",
        f"- 结构化数据（JSON）：{base}/api/v1/latest.json",
        "",
        "## 数据说明",
        "",
        "- `score` 是排序分（0–100）：判断价值为主，时效与热度只做轻微修正。",
        "- `attention` 是判断本身：五个维度（sig 实质份量 / nov 信息增量 / cred 证据强度 /",
        "  reson 共振面 / act 可用性）各 0–10，按内容类型加权；同一份材料独立打两次分。",
        "- `event`：同一件事被多家报道时合并成一个事件，`representative` 为 true 的那条是代表稿。",
        "- 标题与摘要已翻成简体中文；原文链接始终保留，不转载全文。",
        "",
        "## 当前规模",
        "",
        f"- 今日条目：{counts.get('items', 0)}",
        f"- 进日报：{counts.get('daily', 0)}",
        f"- 事件数：{counts.get('events', 0)}",
        f"- 信源数：{counts.get('sources', 0)}",
        "",
    ])


# --------------------------------------------------------------------------- #
# 写盘
# --------------------------------------------------------------------------- #

def build(payload: dict[str, Any], site_root: Path) -> dict[str, Any]:
    """生成全部出口文件。返回统计（给日志）。任何单个出口失败都不影响其他。"""
    conf = config()
    base_url = str(conf.get("base_url") or "http://localhost:8123").rstrip("/")
    feed_n = int(conf.get("feed_items") or 50)
    api_n = int(conf.get("api_items") or 200)
    items = list(payload.get("items") or [])
    generated_at = (payload.get("stats") or {}).get("generated_at") or datetime.now().isoformat()

    plan = edition.arrange(payload)
    daily = [i for i in ([plan.get("lead")] + plan["highlights"] + plan["body"] + plan["briefs"]) if i]
    stats = {"feeds": 0, "daily": len(daily), "items": len(items),
             "events": len({(i.get("extra") or {}).get("event_id") for i in items} - {None}),
             "sources": len({i.get("source") for i in items if i.get("source")})}

    site_root.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    def write(rel: str, text: str) -> None:
        path = site_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(rel)

    try:
        write("feed.xml", render_rss(daily or items[:20], title="Z-Bit · 今日要闻",
                                     link=f"{base_url}/", self_url=f"{base_url}/feed.xml",
                                     description="每天一份 AI 情报日报：五轴评分、事件聚簇、规则编排。"))
        write("feed-all.xml", render_rss(items[:feed_n], title="Z-Bit · 全部动态",
                                         link=f"{base_url}/", self_url=f"{base_url}/feed-all.xml",
                                         description="当天采集到的全部条目，按排序分从高到低。"))
        stats["feeds"] = 2
    except Exception as e:
        stats["feed_error"] = f"{type(e).__name__}: {e}"

    try:
        write("api/v1/latest.json", json.dumps(
            render_api(items[:api_n], generated_at=generated_at),
            ensure_ascii=False, indent=1))
    except Exception as e:
        stats["api_error"] = f"{type(e).__name__}: {e}"

    if conf.get("category_feeds", True):
        try:
            groups: dict[str, list[dict[str, Any]]] = {}
            for it in daily or items:
                groups.setdefault(_category(it), []).append(it)
            for key, group in groups.items():
                if key == "other" and len(groups) > 1:
                    continue  # 没有分类的单独出不值得
                write(f"feed/category/{key}.xml", render_rss(
                    group[:feed_n], title=f"Z-Bit · {key}",
                    link=f"{base_url}/",
                    self_url=f"{base_url}/feed/category/{key}.xml",
                    description=f"按结构化分类过滤：{key}"))
                stats["feeds"] += 1
        except Exception as e:
            stats["category_error"] = f"{type(e).__name__}: {e}"

    try:
        write("llms.txt", render_llms(base_url, stats))
    except Exception as e:
        stats["llms_error"] = f"{type(e).__name__}: {e}"

    stats["files"] = written
    return stats
