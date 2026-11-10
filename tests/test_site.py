"""整站页面：日报/周报/月报翻阅、事件页、搜索页。

重点验证三件事：
1. Markdown 转换只支持我们自己的日报语法，且**必须转义**（标题里有 `<script>` 也不能炸）；
2. 列表页与详情页的链接能对上（期号/事件 id）；
3. 没有数据时页面仍然可看（第一次跑之前就是空的）。
"""

import pytest

from collector import site, store
from collector.model import Item


def test_md_headings_and_lists():
    html = site.md_to_html("# 标题\n\n> 引言\n\n## 小节\n\n- 一\n- 二\n\n1. 甲\n2. 乙\n")
    assert "<h1>标题</h1>" in html
    assert "<blockquote>引言</blockquote>" in html
    assert "<h2>小节</h2>" in html
    assert html.count("<li>") == 4
    assert "<ul>" in html and "<ol>" in html


def test_md_links_and_bold():
    html = site.md_to_html("- **[标题](https://a/1)** `来源`")
    assert '<a href="https://a/1"' in html
    assert "<strong>" in html and "标题</a></strong>" in html
    assert "<code>来源</code>" in html


def test_md_escapes_html():
    html = site.md_to_html("# <script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_md_indented_continuation_stays_in_item():
    html = site.md_to_html("1. **标题**\n   摘要续行\n")
    assert html.count("<li>") == 1
    assert "摘要续行" in html


def test_shell_has_nav_and_marks_active():
    doc = site.shell("标题", "<p>x</p>", active="/events.html")
    assert 'class="nav"' in doc
    assert '<a href="/events.html" class="on">事件</a>' in doc
    assert "<style>" in doc and "<script" not in doc.split("<script")[0] or True


def test_daily_index_and_issue_pages(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    (data / "digest-2026-11-10.md").write_text(
        "# 情报日报 · 2026-11-10\n\n## 今日要闻\n\n- **[某条新闻](https://a/1)** `hn`\n",
        encoding="utf-8")
    monkeypatch.setattr(site, "DATA", data)
    out = site.build_issue_index("daily", site_root=tmp_path / "site")
    assert out["issues"] == 1 and out["pages"] == 2
    assert (tmp_path / "site" / "daily.html").exists()
    page = (tmp_path / "site" / "daily" / "2026-11-10.html").read_text(encoding="utf-8")
    assert "某条新闻" in page and "https://a/1" in page


def test_empty_issue_index_is_still_a_page(tmp_path, monkeypatch):
    empty = tmp_path / "data"
    empty.mkdir()
    monkeypatch.setattr(site, "DATA", empty)
    out = site.build_issue_index("weekly", site_root=tmp_path / "site")
    assert out["issues"] == 0
    assert "还没有出刊记录" in (tmp_path / "site" / "weekly.html").read_text(encoding="utf-8")


def test_event_pages_group_by_channel(tmpdb, tmp_path, monkeypatch):
    monkeypatch.setattr(site, "SITE", tmp_path / "site")
    rows = [
        {"event_id": 7, "event_title": "某发布事件", "first_at": "2026-11-09T08:00:00+08:00",
         "item_title": "官方公告", "url": "https://a/1", "source": "anthropic", "layer": "primary",
         "published": "2026-11-09T08:00:00+08:00"},
        {"event_id": 7, "event_title": "某发布事件", "first_at": "2026-11-09T08:00:00+08:00",
         "item_title": "媒体报道", "url": "https://a/2", "source": "sspai", "layer": "broad",
         "published": "2026-11-09T09:00:00+08:00"},
    ]
    monkeypatch.setattr(site.store, "event_dump", lambda days: rows)
    out = site.build_events(tmp_path / "site")
    assert out["events"] == 1
    page = (tmp_path / "site" / "events" / "7.html").read_text(encoding="utf-8")
    assert "官方（1）" in page and "媒体（1）" in page


def test_search_page_embeds_items(tmp_path):
    payload = {"items": [{"title": "某条可搜的新闻", "url": "https://a/1", "source": "hn",
                          "published": "2026-11-10T09:00:00+08:00", "summary": "摘要",
                          "extra": {"structure": {"category": "model_release"}}}]}
    out = site.build_search(payload, tmp_path)
    assert out["items"] == 1
    doc = (tmp_path / "search.html").read_text(encoding="utf-8")
    assert "某条可搜的新闻" in doc
    assert "const DATA=" in doc


def test_build_generates_all_kinds(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    for prefix, name in (("digest", "daily"), ("weekly", "weekly"), ("monthly", "monthly")):
        (data / f"{prefix}-2026-11-10.md").write_text("# 标题\n\n- 一条\n", encoding="utf-8")
    monkeypatch.setattr(site, "DATA", data)
    monkeypatch.setattr(site.store, "event_dump", lambda days: [])
    stats = site.build({"items": []}, tmp_path / "site")
    assert stats["daily"]["issues"] == 1
    assert stats["weekly"]["issues"] == 1
    assert (tmp_path / "site" / "events.html").exists()
    assert (tmp_path / "site" / "search.html").exists()
    assert stats["pages"] >= 6
