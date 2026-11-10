"""多出口：RSS / JSON / llms.txt。

重点验证：XML 合法（能被阅读器解析）、字段不丢、转义正确、
分类 feed 只含该分类、以及**所有出口的数据都来自同一份 payload**（不重新判断）。
"""

import json
import xml.etree.ElementTree as ET

import pytest

from collector import export


def mk(url, title, source="hackernews", layer="rank", score=50.0, category=None, **extra):
    base = {"topic": True, "deal": False, "score": score}
    base.update(extra)
    item = {"source": source, "title": title, "url": url, "layer": layer,
            "region": "overseas", "summary": f"{title} 的摘要 & 说明", "published": "2026-11-10T09:00:00+08:00",
            "extra": base}
    if category:
        base["structure"] = {"category": category, "tags": [], "subjects": [], "scope": "single"}
    return item


def payload(items):
    return {"items": items,
            "stats": {"generated_at": "2026-11-10T09:00:00+08:00", "sources_ok": 5,
                      "by_region": {}, "by_layer": {}}}


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    monkeypatch.setattr(export, "config", lambda: {
        "base_url": "http://localhost:8123", "feed_items": 50,
        "api_items": 200, "category_feeds": True,
    })


def test_rss_is_valid_xml_and_escapes():
    items = [mk("https://a/1", "OpenAI 发布 A&B 模型", score=80)]
    xml = export.render_rss(items, title="测试", link="http://x/", description="说明")
    root = ET.fromstring(xml)          # 不合法会直接抛异常
    assert root.tag == "rss"
    title = root.findtext("./channel/item/title")
    assert "A&B" in title, "& 必须被转义成 &amp; 后仍能读回"


def test_rss_items_carry_link_guid_date():
    items = [mk("https://a/1", "标题一", score=80)]
    root = ET.fromstring(export.render_rss(items, title="t", link="http://x/", description="d"))
    item = root.find("./channel/item")
    assert item.findtext("link") == "https://a/1"
    assert item.findtext("guid") == "https://a/1"
    assert item.findtext("pubDate")            # RFC822，能解析出来即可
    assert item.findtext("category") == "other"


def test_rss_self_link_points_at_the_feed():
    items = [mk("https://a/1", "标题一", score=80)]
    xml = export.render_rss(items, title="t", link="http://x/", description="d",
                            self_url="http://x/feed.xml")
    assert 'href="http://x/feed.xml" rel="self"' in xml


def test_rss_marks_multi_report_events():
    items = [mk("https://a/1", "某事件", event_size=7, event_sources=4, score=80)]
    xml = export.render_rss(items, title="t", link="http://x/", description="d")
    assert "7 篇报道" in xml


def test_api_shape_and_fields():
    items = [mk("https://a/1", "标题一", score=80, category="model_release",
                event_id=3, event_size=2, event_sources=2, event_representative=True)]
    items[0]["extra"]["attention"] = {"available": True, "score": 72, "threshold": 60,
                                     "selected": True, "itype": "model_release",
                                     "axes": {"sig": 9}, "reason": "正式发布"}
    data = export.render_api(items, generated_at="2026-11-10T09:00:00+08:00")
    assert data["count"] == 1
    row = data["items"][0]
    assert row["url"] == "https://a/1"
    assert row["attention"]["score"] == 72
    assert row["attention"]["reason"] == "正式发布"
    assert row["structure"]["category"] == "model_release"
    assert row["event"]["size"] == 2 and row["event"]["representative"] is True


def test_api_omits_empty_blocks():
    items = [mk("https://a/1", "没有评分没有事件")]
    row = export.render_api(items, generated_at="now")["items"][0]
    assert row["attention"] is None and row["event"] is None and row["structure"] is None


def test_llms_txt_lists_endpoints():
    text = export.render_llms("http://localhost:8123/", {"items": 10, "daily": 8, "events": 3, "sources": 5})
    assert text.startswith("# 信息雷达")
    assert "http://localhost:8123/feed.xml" in text
    assert "http://localhost:8123/api/v1/latest.json" in text
    assert "今日条目：10" in text


def test_build_writes_all_files(tmp_path):
    items = [mk("https://a/1", "模型发布新闻标题要足够长", score=80, category="model_release"),
             mk("https://a/2", "另一条新闻标题也够长", score=70, source="sspai", category="deal")]
    stats = export.build(payload(items), tmp_path)
    names = set(stats["files"])
    assert {"feed.xml", "feed-all.xml", "api/v1/latest.json", "llms.txt"} <= names
    assert (tmp_path / "feed.xml").read_text(encoding="utf-8").startswith("<?xml")
    data = json.loads((tmp_path / "api/v1/latest.json").read_text(encoding="utf-8"))
    assert data["count"] == len(data["items"]) > 0


def test_category_feeds_split_by_structure(tmp_path):
    items = [mk("https://a/1", "模型发布新闻标题足够长", score=80, category="model_release"),
             mk("https://a/2", "羊毛福利新闻标题足够长", score=70, category="deal")]
    stats = export.build(payload(items), tmp_path)
    assert (tmp_path / "feed/category/model_release.xml").exists()
    root = ET.parse(tmp_path / "feed/category/model_release.xml").getroot()
    titles = [i.findtext("title") for i in root.findall("./channel/item")]
    assert all("模型" in t for t in titles if t)


def test_exports_read_from_the_same_payload(tmp_path):
    """出口不重新判断：feed.xml 里的条目必须都来自当日 payload。"""
    items = [mk(f"https://a/{i}", f"第 {i} 条新闻标题足够长", score=80 - i, source=f"s{i}")
             for i in range(5)]
    export.build(payload(items), tmp_path)
    root = ET.parse(tmp_path / "feed.xml").getroot()
    links = {i.findtext("link") for i in root.findall("./channel/item")}
    assert links <= {i["url"] for i in items}


def test_build_survives_empty_day(tmp_path):
    stats = export.build(payload([]), tmp_path)
    assert (tmp_path / "feed.xml").exists()
    assert stats["daily"] == 0
