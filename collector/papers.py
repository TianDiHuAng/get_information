"""arXiv 周报：按主题抓取，只推「没推过」的新论文。

两个主题（见 config/papers.yaml）：
  1. 大模型 / Agent   —— cs.AI / cs.CL + 收紧后的关键词
  2. AI 制药          —— 小分子 / 大分子 / 蛋白 / 环肽生成模型

抓取：按主题查询 + 分页翻到回看窗口边界（不再只取最新 100 条，
      停机几天也能补回来）。
去重：data/papers_seen.json 记 ID（去掉版本号），推过的永不重复。
节奏：data/papers_state.json 记 ISO 周，一周只发一封；错过下次补发。
"""

from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import yaml

from .net import get_text

CONF_PATH = Path(__file__).parent.parent / "config" / "papers.yaml"
SEEN_PATH = Path(__file__).parent.parent / "data" / "papers_seen.json"
PENDING_PATH = Path(__file__).parent.parent / "data" / "papers_pending.json"
STATE_PATH = Path(__file__).parent.parent / "data" / "papers_state.json"

NS = {"a": "http://www.w3.org/2005/Atom"}
API = "https://export.arxiv.org/api/query"

DEFAULTS = {
    "enabled": True,
    "max_items": 40,
    "lookback_days": 8,
    "page_size": 200,
    "max_pages": 6,
    "send_weekday": 0,
    "send_hour": 7,
    "topics": [
        {"name": "大模型 / Agent", "categories": ["cs.AI", "cs.CL"],
         "keywords": ["agent", "large language model", "LLM"]}
    ],
}


def conf() -> dict:
    data = dict(DEFAULTS)
    if CONF_PATH.exists():
        try:
            loaded = yaml.safe_load(CONF_PATH.read_text(encoding="utf-8")) or {}
            data.update(loaded)
        except Exception:
            pass
    if not data.get("topics"):
        data["topics"] = DEFAULTS["topics"]
    return data


def _load(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(path: Path, data) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def topic_query(topic: dict) -> str:
    if topic.get("query"):
        return " ".join(str(topic["query"]).split())
    cats = " OR ".join(f"cat:{c}" for c in topic["categories"])
    kws = " OR ".join(
        f'abs:"{k}"' if " " in str(k) else f"abs:{k}" for k in topic["keywords"]
    )
    return f"({cats}) AND ({kws})"


def _fetch_page(query: str, start: int, size: int) -> list[dict]:
    url = (
        f"{API}?search_query={quote(query)}&sortBy=submittedDate&sortOrder=descending"
        f"&start={start}&max_results={size}"
    )
    xml = get_text(url, timeout=120)
    root = ET.fromstring(xml)
    rows: list[dict] = []
    for e in root.findall("a:entry", NS):
        raw_id = (e.findtext("a:id", default="", namespaces=NS) or "").rsplit("/", 1)[-1]
        base = re.sub(r"v\d+$", "", raw_id).strip()
        if not base:
            continue
        title = " ".join((e.findtext("a:title", default="", namespaces=NS) or "").split())
        summary = " ".join((e.findtext("a:summary", default="", namespaces=NS) or "").split())
        authors = [
            (a.findtext("a:name", default="", namespaces=NS) or "").strip()
            for a in e.findall("a:author", NS)
        ]
        rows.append(
            {
                "id": base,
                "source": "arxiv",
                "lang": "en",
                "title": title[:220],
                "summary": summary[:500],
                "published": (e.findtext("a:published", default="", namespaces=NS) or "")[:10],
                "url": f"https://arxiv.org/abs/{base}",
                "authors": ", ".join([a for a in authors if a][:3]),
            }
        )
    return rows


def fetch_topic(topic: dict, c: dict, seen: dict) -> list[dict]:
    """一个主题翻页抓，直到越过回看窗口边界。"""
    query = topic_query(topic)
    cutoff = (datetime.now() - timedelta(days=int(c["lookback_days"]))).strftime("%Y-%m-%d")
    size = int(c["page_size"])
    out: list[dict] = []
    got = 0

    for page in range(int(c["max_pages"])):
        try:
            rows = _fetch_page(query, page * size, size)
        except Exception as e:
            print(f"  [papers] {topic['name']} 第 {page+1} 页失败: {type(e).__name__}: {e}")
            break
        if not rows:
            break

        reached_end = False
        for r in rows:
            if r["published"] and r["published"] < cutoff:
                reached_end = True
                continue
            if r["id"] in seen:
                continue
            r["topics"] = [topic["name"]]
            r["topic"] = topic["name"]
            out.append(r)
            got += 1

        if reached_end or len(rows) < size:
            break
        time.sleep(3)  # arXiv 对连续请求敏感

    print(f"  [papers] {topic['name']}: 新增候选 {got} 篇")
    return out


def fetch_recent(c: dict | None = None) -> list[dict]:
    c = c or conf()
    seen = _load(SEEN_PATH, {})
    merged: dict[str, dict] = {}
    for topic in c["topics"]:
        for r in fetch_topic(topic, c, seen):
            if r["id"] in merged:
                merged[r["id"]]["topics"].append(topic["name"])
                merged[r["id"]]["topic"] = " / ".join(merged[r["id"]]["topics"])
            else:
                merged[r["id"]] = r
    return list(merged.values())


def _week_key(dt: datetime) -> str:
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _due(now: datetime, c: dict, state: dict) -> bool:
    if state.get("last_sent_week") == _week_key(now):
        return False
    target = now - timedelta(days=(now.weekday() - int(c["send_weekday"])) % 7)
    target = target.replace(hour=int(c["send_hour"]), minute=0, second=0, microsecond=0)
    return now >= target


def select_items(pending: list[dict], c: dict) -> list[dict]:
    """按主题限额挑选，且按日期轮转，避免一期全被最后一天的论文占满。"""
    limits = {t["name"]: int(t.get("limit") or 0) for t in c["topics"]}
    out: list[dict] = []
    for name, rows in _grouped(pending):
        lim = limits.get(name) or int(c.get("max_items") or 40)
        buckets: dict[str, list[dict]] = {}
        for r in rows:
            buckets.setdefault(str(r.get("published") or ""), []).append(r)
        dates = sorted(buckets, reverse=True)
        picked: list[dict] = []
        while len(picked) < lim and any(buckets[d] for d in dates):
            for d in dates:
                if buckets[d] and len(picked) < lim:
                    picked.append(buckets[d].pop(0))
        out.extend(picked)
    out.sort(key=lambda x: str(x.get("published") or ""), reverse=True)
    return out


def _grouped(items: list[dict]) -> list[tuple[str, list[dict]]]:
    order: list[str] = []
    bucket: dict[str, list[dict]] = {}
    for it in items:
        key = it.get("topic") or "其他"
        if key not in bucket:
            bucket[key] = []
            order.append(key)
        bucket[key].append(it)
    return [(k, bucket[k]) for k in order]


def _md(items: list[dict], now: datetime) -> str:
    parts = [f"# arXiv 周报 · {now.strftime('%Y-%m-%d')} · {len(items)} 篇新论文\n"]
    for name, rows in _grouped(items):
        parts.append(f"\n## {name}（{len(rows)} 篇）\n")
        for i, it in enumerate(rows, 1):
            parts.append(
                f"\n### {i}. {it['title']}\n\n"
                f"- 日期：{it.get('published', '—')} · [原文]({it['url']})\n"
                f"- 作者：{it.get('authors', '—')}\n\n"
                f"{it.get('summary', '')}\n"
            )
    parts.append("\n---\n由 Get_Information 自动生成 · 只推没推送过的新论文\n")
    return "".join(parts)


def _html(items: list[dict], now: datetime) -> str:
    import html as _h

    blocks = []
    for name, rows in _grouped(items):
        cards = []
        for i, it in enumerate(rows, 1):
            cards.append(
                '<div style="margin:0 0 18px;padding-bottom:16px;border-bottom:1px solid #f1f3f5;">'
                '<div style="font-size:15px;font-weight:600;color:#111827;line-height:1.5;">'
                f'<span style="color:#c1c9d3;margin-right:6px;">{i:02d}</span>'
                f'<a href="{_h.escape(it["url"], quote=True)}" style="color:#1a56db;text-decoration:none;">'
                f'{_h.escape(it["title"])}</a></div>'
                f'<div style="color:#9ca3af;font-size:12px;margin:4px 0;">'
                f'{_h.escape(it.get("published") or "")} · {_h.escape(it.get("authors") or "")}</div>'
                f'<div style="color:#4b5563;font-size:13px;line-height:1.7;">'
                f'{_h.escape((it.get("summary") or "")[:220])}</div></div>'
            )
        blocks.append(
            '<h2 style="font-size:15px;color:#111827;margin:26px 0 12px;padding-bottom:8px;'
            f'border-bottom:1px solid #e5e7eb;">{_h.escape(name)}（{len(rows)} 篇）</h2>'
            + "".join(cards)
        )

    return (
        '<div style="background:#f5f7fa;padding:24px 8px;font-family:-apple-system,\'Segoe UI\','
        '\'PingFang SC\',\'Microsoft YaHei\',sans-serif;">'
        '<div style="max-width:680px;margin:0 auto;background:#fff;border:1px solid #e5e7eb;'
        'border-radius:12px;padding:26px 30px;">'
        f'<h1 style="font-size:20px;color:#111827;margin:0 0 6px;">arXiv 周报 · {now.strftime("%Y-%m-%d")}</h1>'
        f'<p style="color:#6b7280;font-size:12px;margin:0 0 18px;">本周新增 {len(items)} 篇 · '
        f'主题：{" / ".join(t["name"] for t in conf()["topics"])}</p>'
        + "".join(blocks)
        + '<p style="color:#9ca3af;font-size:11px;margin:26px 0 0;padding-top:14px;'
        'border-top:1px solid #f3f4f6;">由 Get_Information 自动生成 · 只推没推送过的新论文</p>'
        "</div></div>"
    )


def run(dry: bool = False) -> str:
    c = conf()
    if not c.get("enabled"):
        return "未启用"

    new = fetch_recent(c)
    pending = _load(PENDING_PATH, [])
    have = {p["id"]: p for p in pending}

    for r in new:
        if r["id"] in have:
            old = have[r["id"]]
            merged_topics = sorted(set((old.get("topics") or []) + (r.get("topics") or [])))
            old["topics"] = merged_topics
            old["topic"] = " / ".join(merged_topics)
        else:
            pending.append(r)

    cutoff_day = (datetime.now() - timedelta(days=int(c["lookback_days"]))).strftime("%Y-%m-%d")
    pending = [p for p in pending if str(p.get("published", "")) >= cutoff_day]
    pending.sort(key=lambda x: x.get("published", ""), reverse=True)
    _save(PENDING_PATH, pending)

    now = datetime.now()
    state = _load(STATE_PATH, {})
    if not _due(now, c, state):
        return f"累计中：待推 {len(pending)} 篇（本轮新增 {len(new)}）"

    items = select_items(pending, c)
    if not items:
        return "本周到期，但没有新论文"

    from .translate import translate_items

    translate_items(items)

    n_topics = len({i.get("topic") for i in items})
    subject = f"arXiv 周报 {now.strftime('%Y-%m-%d')} · {len(items)} 篇 / {n_topics} 个主题"
    if dry:
        return f"[dry-run] 将推送 {len(items)} 篇：{subject}"

    from .pushmail import send_custom

    result = send_custom(subject, _md(items, now), _html(items, now))

    seen = _load(SEEN_PATH, {})
    day = now.strftime("%Y-%m-%d")
    for it in items:
        seen[it["id"]] = day
    _save(SEEN_PATH, seen)

    ids = {it["id"] for it in items}
    _save(PENDING_PATH, [p for p in pending if p["id"] not in ids])
    state["last_sent_week"] = _week_key(now)
    state["last_sent_at"] = now.isoformat(timespec="seconds")
    _save(STATE_PATH, state)

    return f"{result}（{len(items)} 篇）"


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = conf()
    rows = fetch_recent(c)
    print(f"抓到候选 {len(rows)} 篇")
    from collections import Counter

    print(Counter(r["topic"] for r in rows))
    print("最新:", max((r["published"] for r in rows), default="—"))
