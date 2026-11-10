"""长期时间线与叙事对比。

两块都只读库、不调模型，所以测的重点是**口径**：
1. 月份必须来自事件首次出现时间，而不是抓取时间（否则重抓会把旧事当成新的）；
2. 叙事只保留"至少两个渠道都在说"的事件 —— 只有一个来源谈不上差异；
3. 空库不能崩（第一次跑的时候就是空的）。
"""

import pytest

from collector import timeline


def row(event_id=1, subject="Anthropic", layer="primary", region="overseas",
        title="事件标题", item_title="报道标题", first_at="2026-11-09T08:00:00+08:00",
        published=None, source="thebatch") -> dict:
    return {"event_id": event_id, "event_title": title, "event_key": f"k{event_id}",
            "first_at": first_at, "last_at": first_at, "item_id": event_id * 10,
            "source": source, "layer": layer, "region": region,
            "item_title": item_title, "url": f"https://a/{event_id}",
            "published": published or first_at,
            "category": "model_release", "tags": ["开源"], "subjects": [subject]}


def test_month_comes_from_event_first_seen():
    rows = [row(first_at="2026-09-03T10:00:00+08:00")]
    got = timeline.monthly(rows)
    assert got["months"] == ["2026-09"]
    assert got["subjects"][0]["months"] == {"2026-09": 1}


def test_monthly_counts_events_not_articles():
    """同一事件的三篇报道只算一个事件。"""
    rows = [row(event_id=1), row(event_id=1, layer="rank"), row(event_id=1, layer="social")]
    got = timeline.monthly(rows)
    assert got["events"] == 1
    assert got["subjects"][0]["total"] == 1


def test_monthly_ranks_by_total_events():
    rows = [row(event_id=1, subject="Anthropic"), row(event_id=2, subject="Anthropic"),
            row(event_id=3, subject="Google"), row(event_id=3, subject="Google")]
    got = timeline.monthly(rows)
    assert got["subjects"][0]["subject"] == "Anthropic"
    assert got["subjects"][0]["total"] == 2


def test_narratives_split_by_layer():
    rows = [row(event_id=1, layer="primary", item_title="官方公告"),
            row(event_id=1, layer="rank", item_title="媒体报道"),
            row(event_id=1, layer="social", item_title="社区讨论")]
    got = timeline.narratives(rows)
    assert len(got) == 1
    b = got[0]
    assert [e["title"] for e in b["official"]] == ["官方公告"]
    assert [e["title"] for e in b["media"]] == ["媒体报道"]
    assert [e["title"] for e in b["social"]] == ["社区讨论"]
    assert b["sources"] == 3


def test_narratives_skip_single_channel_events():
    """只有一个渠道在说，谈不上"叙事差异"。"""
    rows = [row(event_id=1, layer="primary"), row(event_id=1, layer="primary")]
    assert timeline.narratives(rows) == []


def test_narratives_limit():
    rows = []
    for i in range(30):
        rows += [row(event_id=i, layer="primary"), row(event_id=i, layer="rank")]
    assert len(timeline.narratives(rows, limit=20)) == 20


def test_unknown_month_is_not_a_column():
    rows = [row(first_at="", published="")]
    got = timeline.monthly(rows)
    assert "未知" not in got["months"]


def test_render_handles_empty_data():
    html = timeline.render(timeline.compute([]))
    assert html.startswith("<!doctype html>")
    assert "还没有足够的事件" in html
    assert "今天没有跨渠道的事件" in html


def test_build_writes_file_with_empty_store(tmpdb, tmp_path):
    out = timeline.build(tmp_path)
    from pathlib import Path

    path = Path(out["file"])
    assert path.exists() and path.name == "timeline.html"
    assert out["events"] == 0
