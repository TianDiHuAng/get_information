"""整站页面：模块齐不齐、链接对不对、转义有没有漏。

重点覆盖 AIHOT 有而之前缺的四块：全部动态（分页）、热门（按事件热度）、
文章页（含评分理由与同事件其他报道）、以及静态页与"更多"。
"""

import pytest

from collector import site, store, theme
from collector.model import Item


def test_md_headings_lists_quote():
    html = site.md_to_html("# 标题\n\n> 引言\n\n## 小节\n\n- 一\n- 二\n\n1. 甲\n2. 乙\n")
    assert "<h1>标题</h1>" in html and "<h2>小节</h2>" in html
    assert html.count("<li>") == 4 and "<ul" in html and "<ol" in html


def test_md_links_bold_code():
    html = site.md_to_html("- **[标题](https://a/1)** `来源`")
    assert '<a href="https://a/1"' in html and "<strong>" in html and "<code>来源</code>" in html


def test_md_escapes_html():
    html = site.md_to_html("# <script>alert(1)</script>")
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_theme_page_has_nav_and_bottom_nav():
    doc = theme.page("标题", "<p>x</p>", active="/all.html", lead="引子")
    assert 'class="side"' in doc and 'class="bnav"' in doc
    assert "Z-Bit" in doc and 'class="brand"' in doc
    assert "<style>" in doc


def test_theme_css_is_scoped_to_one_block():
    assert theme.CSS.count("<") == 0          # 样式里不该混进标签
    assert "@media(max-width" in theme.CSS


def seed(day=None):
    items = [
        Item(source="anthropic", title="Anthropic 发布 Claude Fable 5.2 与 Mythos 5.2",
             url="https://a/1", layer="primary", summary="官方宣布两个模型正式开放。"),
        Item(source="hackernews", title="Fable 5.2 在 Artificial Analysis 得 65 分",
             url="https://a/2", layer="rank", summary="190 条评论"),
    ]
    for it in items:
        it.extra["score"] = 80 if it.layer == "primary" else 70
        it.extra["attention"] = {"available": True, "score": 82, "threshold": 58,
                                 "itype": "model_release", "axes": {"sig": 9, "nov": 8,
                                                                    "cred": 7, "reson": 8, "act": 6},
                                 "reason": "正式发布且价格变化清楚"}
        it.extra["structure"] = {"category": "model_release", "tags": ["开源"],
                                 "subjects": ["Anthropic"], "scope": "single"}
    store.upsert_items(items, day)


def test_all_list_paginates(tmpdb, tmp_path, monkeypatch):
    monkeypatch.setattr(site, "PAGE_SIZE", 1)
    seed()
    out = site.build_all(site_root=tmp_path)
    assert out["items"] == 2 and out["pages"] == 2
    assert (tmp_path / "all.html").exists()
    assert (tmp_path / "all" / "2.html").exists()
    doc = (tmp_path / "all.html").read_text(encoding="utf-8")
    assert "/items/" in doc


def test_item_page_shows_reason_axes_and_siblings(tmpdb, tmp_path):
    seed()
    site.build_items(site_root=tmp_path)
    pages = list((tmp_path / "items").glob("*.html"))
    assert len(pages) == 2
    doc = pages[0].read_text(encoding="utf-8")
    assert "正式发布且价格变化清楚" in doc          # 评分理由
    assert "份量" in doc and "可用" in doc          # 五轴标签
    assert "阅读原文" in doc


def test_item_page_lists_other_reports_of_same_event(tmpdb, tmp_path):
    seed()
    # 手工把两条并到同一事件
    store.upsert_event("url:https://a/1", "同一件事", "2026-11-10", "2026-11-10",
                       [(1, "SAME_OCCURRENCE", 1.0), (2, "SAME_OCCURRENCE", 1.0)])
    ids = store.ids_for(["url:https://a/1"])
    detail = store.item_detail(int(ids["url:https://a/1"]))
    assert detail and len(detail["siblings"]) == 2


def test_hot_ranks_by_event_heat(tmpdb, tmp_path, monkeypatch):
    rows = [
        {"event_id": 1, "event_title": "冷门事件", "first_at": "2026-11-09", "source": "a"},
        {"event_id": 2, "event_title": "大热事件", "first_at": "2026-11-09", "source": "b"},
        {"event_id": 2, "event_title": "大热事件", "first_at": "2026-11-09", "source": "c"},
    ]
    monkeypatch.setattr(site.store, "event_dump", lambda days, day=None: rows)
    monkeypatch.setattr(site.store, "latest_heat", lambda: {1: 1.0, 2: 9.0})
    out = site.build_hot(site_root=tmp_path)
    assert out["events"] == 2
    doc = (tmp_path / "hot.html").read_text(encoding="utf-8")
    assert doc.index("大热事件") < doc.index("冷门事件")


def test_events_page_groups_by_channel(tmpdb, tmp_path, monkeypatch):
    rows = [
        {"event_id": 7, "event_title": "某发布事件", "first_at": "2026-11-09T08:00:00+08:00",
         "item_title": "官方公告", "url": "https://a/1", "source": "anthropic", "layer": "primary",
         "published": "2026-11-09T08:00:00+08:00"},
        {"event_id": 7, "event_title": "某发布事件", "first_at": "2026-11-09T08:00:00+08:00",
         "item_title": "媒体报道", "url": "https://a/2", "source": "sspai", "layer": "broad",
         "published": "2026-11-09T09:00:00+08:00"},
    ]
    monkeypatch.setattr(site.store, "event_dump", lambda days: rows)
    out = site.build_events(tmp_path)
    assert out["events"] == 1
    page = (tmp_path / "events" / "7.html").read_text(encoding="utf-8")
    assert "官方" in page and "媒体" in page


def test_search_embeds_items(tmpdb, tmp_path):
    seed()
    out = site.build_search(site_root=tmp_path)
    assert out["items"] == 2
    doc = (tmp_path / "search.html").read_text(encoding="utf-8")
    assert "const DATA=" in doc and "Claude Fable 5.2" in doc


def test_static_pages_exist(tmp_path):
    out = site.build_static(tmp_path)
    for slug in ("about", "terms", "privacy", "agent", "starred", "feedback", "more"):
        assert (tmp_path / f"{slug}.html").exists(), slug
    assert out["pages"] == 7


def test_issue_pages_from_markdown(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    (data / "digest-2026-11-10.md").write_text(
        "# 情报日报 · 2026-11-10\n\n- **[某条新闻](https://a/1)** `hn`\n", encoding="utf-8")
    monkeypatch.setattr(site, "DATA", data)
    out = site.build_issue_index("daily", site_root=tmp_path / "site")
    assert out["issues"] == 1 and out["pages"] == 2
    page = (tmp_path / "site" / "daily" / "2026-11-10.html").read_text(encoding="utf-8")
    assert "某条新闻" in page


def test_build_runs_every_module_even_when_empty(tmpdb, tmp_path, monkeypatch):
    monkeypatch.setattr(site, "DATA", tmp_path / "data")
    (tmp_path / "data").mkdir(exist_ok=True)
    stats = site.build({}, tmp_path / "site")
    for name in ("all", "hot", "items", "events", "search", "static", "daily", "weekly", "monthly"):
        assert name in stats and not stats[name].get("error"), f"{name}: {stats[name]}"
    assert stats["pages"] >= 10
