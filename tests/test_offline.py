"""单文件离线归档。

重点是"一个文件自洽"：不引用外部样式/脚本，四块内容各自失败不影响其他块。
"""

import pytest

from collector import offline, store
from collector.model import Item


def payload(items=None) -> dict:
    items = items or []
    return {"items": items,
            "stats": {"generated_at": "2026-11-10T09:00:00+08:00", "sources_ok": 5}}


def test_build_writes_self_contained_html(tmpdb, tmp_path):
    out = offline.build(payload(), tmp_path)
    from pathlib import Path

    path = Path(out["file"])
    assert path.exists() and path.name == "offline.html"
    doc = path.read_text(encoding="utf-8")
    assert doc.startswith("<!doctype html>")
    assert "<style>" in doc
    # 不允许引用外部资源（只允许正文里的 http 链接）
    assert "<link" not in doc
    assert "<script" not in doc
    assert "src=" not in doc


def test_sections_render_without_data(tmpdb, tmp_path):
    out = offline.build(payload(), tmp_path)
    doc = open(out["file"], encoding="utf-8").read()
    assert "今日要闻" in doc and "本周要闻" in doc
    assert "今天没有选出要闻" in doc
    assert "还没有足够的事件" in doc or "还没有结构化结果" in doc


def test_today_section_lists_lead(tmpdb, tmp_path):
    items = [{"source": "thebatch", "title": "Anthropic 发布 Claude Fable 5.2 与 Mythos 5.2",
              "url": "https://a/1", "layer": "primary", "region": "overseas",
              "summary": "官方宣布两个模型正式开放，价格下调四成。", "published": "2026-11-10T08:00:00+08:00",
              "extra": {"score": 92, "deal": False, "topic": True}}]
    out = offline.build(payload(items), tmp_path)
    doc = open(out["file"], encoding="utf-8").read()
    assert "Anthropic 发布 Claude Fable 5.2" in doc
    assert "https://a/1" in doc


def test_escapes_html_in_titles(tmpdb, tmp_path):
    items = [{"source": "x", "title": "<script>alert(1)</script>", "url": "https://a/2",
              "layer": "rank", "region": "overseas", "summary": "",
              "published": "2026-11-10T08:00:00+08:00", "extra": {"score": 80}}]
    out = offline.build(payload(items), tmp_path)
    doc = open(out["file"], encoding="utf-8").read()
    assert "<script>alert(1)</script>" not in doc
    assert "&lt;script&gt;" in doc


def test_week_section_uses_reported_items(tmpdb, tmp_path):
    store.upsert_items([Item(source="hackernews", title="本周进过日报的一条新闻标题",
                             url="https://w/1", layer="rank")])
    store.mark_reported([{"url": "https://w/1"}], day=store.today_str())
    out = offline.build(payload(), tmp_path, day=store.today_str())
    doc = open(out["file"], encoding="utf-8").read()
    assert "本周进过日报的一条新闻标题" in doc
