"""周报月报：从日报汇编，规则决定一切。

三条要守住的性质：
1. **同一件事跨天只算一件**（按事件合并），否则周报就是日报的堆叠；
2. 排序看"报道面 + 持续天数 + 分数"，不是"某天分最高" ——
   一次性刷屏不该压过持续一周的话题；
3. 空窗口也要能出文（第一次跑的时候就是空的）。
"""

import pytest

from collector import report, store


def item(title="标题", url="https://a/1", event_id=1, sources=1, days=1, score=60,
         category="model_release", layer="rank", source="hackernews",
         published="2026-11-09T08:00:00+08:00", identity=None) -> dict:
    return {"id": hash(url) & 0xFFFF, "identity": identity or f"url:{url}",
            "title": title, "url": url, "category": category, "layer": layer,
            "source": source, "summary": "摘要内容", "published": published,
            "first_day": published[:10], "days_seen": days, "event_id": event_id,
            "event_sources": sources, "event_size": sources, "score": score,
            "attention": {"score": score, "available": True}, "tags": [], "subjects": []}


def test_same_event_across_days_merges():
    rows = [item(url="https://a/1", title="第一天报道"),
            item(url="https://a/2", title="第二天报道", sources=3, days=2, score=80)]
    got = report.group(rows)
    assert len(got) == 1
    # 代表稿是分高的那条
    assert got[0]["title"] == "第二天报道"
    assert got[0]["days_seen"] == 2 and got[0]["event_sources"] == 3


def test_persistence_beats_single_high_score():
    one_off = item(url="https://b/1", title="一次性刷屏", score=95, sources=1, days=1, event_id=1)
    steady = item(url="https://b/2", title="连续一周", score=70, sources=4, days=5, event_id=2)
    ranked = report.group([one_off, steady])
    assert ranked[0]["title"] == "连续一周"


def test_more_sources_rank_higher():
    few = item(url="https://c/1", event_id=1, score=70, sources=1)
    many = item(url="https://c/2", event_id=2, score=70, sources=5)
    ranked = report.group([few, many])
    assert ranked[0]["event_size"] == 5


def test_short_title_is_demoted_not_dropped(monkeypatch):
    """「太疯狂了」这类空标题不该占据周报前排，但也不该消失（和日报同一套规则）。"""
    rows = [item(url="https://j/1", event_id=1, title="太疯狂了", score=90),
            item(url="https://j/2", event_id=2, score=70,
                 title="Anthropic 发布 Claude Fable 5.2 与 Mythos 5.2")]
    monkeypatch.setattr(report.store, "reported_items", lambda days, day: rows)
    data = report.compose("weekly", "2026-11-10")
    assert data["top"][0]["title"].startswith("Anthropic")
    assert any(t["title"] == "太疯狂了" for t in data["top"])


def test_official_layer_gets_a_bonus():
    official = item(url="https://d/1", event_id=1, layer="primary", score=70)
    media = item(url="https://d/2", event_id=2, layer="rank", score=70)
    assert report._score(official) > report._score(media)


def test_compose_buckets_by_category(monkeypatch):
    rows = [item(url="https://e/1", event_id=1, category="model_release"),
            item(url="https://e/2", event_id=2, category="research_paper"),
            item(url="https://e/3", event_id=3, category="model_release")]
    monkeypatch.setattr(report.store, "reported_items", lambda days, day: rows)
    data = report.compose("weekly", "2026-11-10")
    assert data["events"] == 3
    assert set(data["sections"]) == {"model_release", "research_paper"}
    assert len(data["sections"]["model_release"]) == 2


def test_compose_limits(monkeypatch):
    rows = [item(url=f"https://f/{i}", event_id=i) for i in range(40)]
    monkeypatch.setattr(report.store, "reported_items", lambda days, day: rows)
    assert len(report.compose("weekly", "2026-11-10")["top"]) == report.LIMITS["weekly"]
    assert len(report.compose("monthly", "2026-11-10")["top"]) == report.LIMITS["monthly"]


def test_render_md_has_range_and_items(monkeypatch):
    rows = [item(url="https://g/1", title="某条新闻")]
    monkeypatch.setattr(report.store, "reported_items", lambda days, day: rows)
    md = report.render_md(report.compose("weekly", "2026-11-10"))
    assert "周报" in md and "2026-11-04 ~ 2026-11-10" in md
    assert "某条新闻" in md
    assert "## 本期要闻" in md


def test_empty_window_renders(monkeypatch):
    monkeypatch.setattr(report.store, "reported_items", lambda days, day: [])
    data = report.compose("weekly", "2026-11-10")
    md = report.render_md(data)
    assert "本期没有进过日报的内容" in md


def test_build_writes_file_and_records_edition(tmpdb, tmp_path, monkeypatch):
    rows = [item(url="https://h/1")]
    monkeypatch.setattr(report.store, "reported_items", lambda days, day: rows)
    out = report.build("weekly", "2026-11-10", out_dir=tmp_path)
    from pathlib import Path

    assert Path(out["file"]).exists()
    assert store.edition_row("weekly", "2026-11-10") is not None


def test_reported_items_returns_only_window(tmpdb):
    from collector.model import Item

    store.upsert_items([Item(source="hackernews", title="最近一条", url="https://i/1")])
    store.mark_reported([{"url": "https://i/1"}], day=store.today_str()[:10])
    rows = store.reported_items(days=7)
    assert [r["title"] for r in rows] == ["最近一条"]
    # 窗口之外（把"今天"设到很远的将来）应当什么都取不到
    assert store.reported_items(days=7, day="2099-01-01") == []
