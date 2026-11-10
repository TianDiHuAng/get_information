"""主题页：分类与标签能翻、能点，且不把用户的标签改名。

三个口径：
1. 分类用 `taxonomy.yaml` 的中文标签，没配到的 key 原样显示（不猜）；
2. 同一条可以同时出现在分类页和多个标签页里（这本来就是标签的用法）；
3. 标签里有中文和空格，文件名必须转成安全 slug，但不能撞车。
"""

import pytest

from collector import store, topics
from collector.identity import item_identity
from collector.model import Item


def row(category="model_release", tags=("开源",), title="标题", published="2026-11-09T08:00:00+08:00",
        source="thebatch") -> dict:
    return {"category": category, "tags": list(tags), "subjects": [], "scope": "single",
            "day": "2026-11-10", "title": title, "url": f"https://a/{hash(title) & 0xFFFF}",
            "source": source, "layer": "primary", "region": "overseas", "published": published}


def test_category_uses_chinese_label():
    data = topics.compute([row(category="model_release")])
    assert data["categories"][0]["label"] == "模型发布"


def test_unknown_category_keeps_its_key():
    data = topics.compute([row(category="weird_new_thing")])
    assert data["categories"][0]["label"] == "weird_new_thing"


def test_same_item_appears_in_every_tag():
    data = topics.compute([row(tags=("开源", "推理"))])
    keys = {g["key"] for g in data["tags"]}
    assert keys == {"开源", "推理"}


def test_counts_and_order():
    rows = [row(tags=("开源",)), row(tags=("开源",)), row(tags=("推理",))]
    data = topics.compute(rows)
    assert data["tags"][0]["key"] == "开源"
    assert data["tags"][0]["count"] == 2


def test_slug_is_safe_for_chinese_and_spaces():
    assert topics._slug("开源") == "开源"
    assert topics._slug("企业 应用") == "企业-应用"
    assert topics._slug("///") == "topic"


def test_empty_input_renders_without_error():
    data = topics.compute([])
    html = topics.render_index(data)
    assert "还没有结构化结果" in html
    assert html.startswith("<!doctype html>")


def test_render_escapes_html():
    data = topics.compute([row(title="<script>alert(1)</script>")])
    html = topics.render_index(data)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_topic_lists_items():
    data = topics.compute([row(title="某条新闻标题")])
    html = topics.render_topic(data["categories"][0], data)
    assert "某条新闻标题" in html
    assert "全部主题" in html


def test_build_creates_index_and_topic_pages(tmpdb, tmp_path):
    it = Item(source="thebatch", title="模型发布新闻标题足够长", url="https://a/1", layer="primary")
    store.upsert_items([it])
    ids = store.ids_for([item_identity(it.url)])
    store.save_structures([{"item_id": ids[item_identity(it.url)],
                            "category": "model_release", "tags": ["开源"],
                            "subjects": ["Anthropic"], "scope": "single", "fact": None}])

    stats = topics.build(tmp_path, days=7)
    assert (tmp_path / "topics.html").exists()
    assert (tmp_path / "topics" / "model_release.html").exists()
    assert stats["categories"] >= 1 and stats["pages"] >= 2


def test_build_with_no_data_still_writes_index(tmpdb, tmp_path):
    stats = topics.build(tmp_path, days=7)
    assert (tmp_path / "topics.html").exists()
    assert stats["pages"] == 1
    assert stats["rows"] == 0
