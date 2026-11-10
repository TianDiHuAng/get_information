"""正文与日期提取。

两类真问题：
1. 日期解析**不能猜** —— 解析不出来就返回 None，宁可让条目按"无日期"处理；
2. 正文**不能抓到导航** —— 抓到导航会让模型把菜单当内容，评分全歪。
"""

from collector import extract

HTML = """
<html><head>
  <meta property="article:published_time" content="2026-11-09T08:30:00+08:00">
</head><body>
  <nav><p>首页 产品 关于我们 联系方式 加入我们</p></nav>
  <script>var x = 1;</script>
  <article class="post-content">
    <h1>Anthropic 发布 Claude Fable 5.2</h1>
    <p>官方宣布新模型在长上下文与工具调用上有明显提升，上下文窗口扩展到 100 万 token。</p>
    <p>API 价格同步下降 40%，即日起对付费用户开放，免费额度在本周内跟进。</p>
    <p>官方博客还给出了在 SWE-bench 与长文档问答上的对比数据，并说明这次升级对既有 API 保持兼容。</p>
  </article>
  <footer><p>版权所有 2026 某公司</p></footer>
</body></html>
"""

HTML_JSONLD = """
<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@type":"NewsArticle","datePublished":"2026-11-08T21:00:00Z"}
</script></head><body><article><p>正文段落一，内容足够长以便被识别成正文内容而不是噪声。</p></article></body></html>
"""

HTML_TIME = """
<html><body><article>
<time datetime="2026-11-07">11 月 7 日</time>
<p>这是正文段落，长度超过二十个字符，用于通过段落过滤阈值。</p>
</article></body></html>
"""


def test_parse_date_keeps_offset():
    assert extract.parse_date("2026-11-09T08:30:00+08:00") == "2026-11-09T08:30:00+08:00"


def test_parse_date_naive_assumes_beijing():
    got = extract.parse_date("2026-11-09 08:30:00")
    assert got is not None and got.endswith("+08:00")


def test_parse_date_zulu():
    got = extract.parse_date("2026-11-08T21:00:00Z")
    assert got is not None and got.startswith("2026-11-08T21:00:00")


def test_parse_date_epoch_seconds_and_millis():
    assert extract.parse_date("1762648200") is not None
    assert extract.parse_date("1762648200000") == extract.parse_date("1762648200")


def test_parse_date_rejects_garbage_instead_of_guessing():
    for raw in ("", "昨天", "2026-13-45", "马上发布", None):
        assert extract.parse_date(raw) is None


def test_extract_date_from_meta():
    from bs4 import BeautifulSoup
    assert extract.extract_date(BeautifulSoup(HTML, "html.parser")) == "2026-11-09T08:30:00+08:00"


def test_extract_date_from_jsonld():
    from bs4 import BeautifulSoup
    got = extract.extract_date(BeautifulSoup(HTML_JSONLD, "html.parser"))
    assert got is not None and got.startswith("2026-11-08T21:00:00")


def test_extract_date_from_time_tag():
    from bs4 import BeautifulSoup
    got = extract.extract_date(BeautifulSoup(HTML_TIME, "html.parser"))
    assert got is not None and got.startswith("2026-11-07")


def test_body_excludes_nav_and_script():
    body = extract.extract_body(HTML)
    assert "100 万 token" in body
    assert "首页 产品" not in body
    assert "var x" not in body


def test_body_keeps_paragraph_breaks():
    body = extract.extract_body(HTML)
    assert "\n" in body, "段落之间要保留换行，模型才分得清句子边界"


def test_body_respects_max_chars():
    body = extract.extract_body(HTML, max_chars=40)
    assert len(body) <= 40


def test_parse_relative_date_from_weibo_style_text():
    from datetime import datetime, timezone, timedelta

    now = datetime(2026, 11, 10, 15, 30, tzinfo=timezone(timedelta(hours=8)))
    assert extract.parse_relative_date("刚刚", now).startswith("2026-11-10T15:30")
    assert extract.parse_relative_date("12分钟前", now).startswith("2026-11-10T15:18")
    assert extract.parse_relative_date("3小时前", now).startswith("2026-11-10T12:30")
    assert extract.parse_relative_date("今天 09:12", now).startswith("2026-11-10T09:12")
    assert extract.parse_relative_date("昨天 22:05", now).startswith("2026-11-09T22:05")
    assert extract.parse_relative_date("11-08", now).startswith("2026-11-08T00:00")
    assert extract.parse_relative_date("2026-11-05", now).startswith("2026-11-05")


def test_parse_relative_date_rolls_back_to_last_year():
    from datetime import datetime, timezone, timedelta

    now = datetime(2026, 1, 5, 12, 0, tzinfo=timezone(timedelta(hours=8)))
    # 一月份看到 "12-20"，只可能是去年
    assert extract.parse_relative_date("12-20", now).startswith("2025-12-20")


def test_parse_relative_date_chinese_month_day():
    """微博卡片写 `11月08日 15:47`，不是 `11-08`。"""
    from datetime import datetime, timezone, timedelta

    now = datetime(2026, 11, 10, 15, 30, tzinfo=timezone(timedelta(hours=8)))
    assert extract.parse_relative_date("11月08日 15:47", now).startswith("2026-11-08T15:47")
    assert extract.parse_relative_date("11月09日 18:43", now).startswith("2026-11-09T18:43")


def test_parse_relative_date_rejects_nonsense():
    from datetime import datetime, timezone, timedelta

    now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone(timedelta(hours=8)))
    for raw in ("", "热门", "2-30", None, "查看全文"):
        assert extract.parse_relative_date(raw, now) is None


def test_enrich_items_fills_body_and_date(tmpdb, monkeypatch):
    from collector.model import Item

    monkeypatch.setattr(extract, "config", lambda: {
        "enabled": True, "min_score": 0, "max_items": 10, "max_workers": 2,
        "timeout": 5, "max_chars": 6000, "only_when_missing": False, "skip_hosts": [],
    })
    monkeypatch.setattr(extract, "fetch_html", lambda url, **kw: HTML)

    it = Item(source="thebatch", title="Anthropic 发布 Claude Fable 5.2",
              url="https://example.com/post", summary="", published="", layer="primary")
    it.extra["score"] = 80
    stats = extract.enrich_items([it])

    assert stats["body"] == 1 and stats["date"] == 1
    assert "100 万 token" in it.extra["body"]
    assert it.published.startswith("2026-11-09T08:30:00")


def test_enrich_skips_low_score(tmpdb, monkeypatch):
    from collector.model import Item

    monkeypatch.setattr(extract, "config", lambda: {
        "enabled": True, "min_score": 90, "max_items": 10, "max_workers": 1,
        "timeout": 5, "max_chars": 6000, "only_when_missing": False, "skip_hosts": [],
    })
    monkeypatch.setattr(extract, "fetch_html", lambda url, **kw: HTML)
    it = Item(source="x", title="低分条目标题", url="https://example.com/a", summary="", published="")
    it.extra["score"] = 40
    assert extract.enrich_items([it])["fetch"] == 0


def test_enrich_skips_social_hosts(tmpdb, monkeypatch):
    from collector.model import Item

    monkeypatch.setattr(extract, "config", lambda: {
        "enabled": True, "min_score": 0, "max_items": 10, "max_workers": 1,
        "timeout": 5, "max_chars": 6000, "only_when_missing": False,
        "skip_hosts": ["x.com"],
    })
    called = {"n": 0}

    def spy(url, **kw):
        called["n"] += 1
        return HTML

    monkeypatch.setattr(extract, "fetch_html", spy)
    it = Item(source="x", title="某条推文标题足够长", url="https://x.com/a/status/1",
              summary="", published="")
    it.extra["score"] = 80
    stats = extract.enrich_items([it])
    assert called["n"] == 0 and stats["skipped"] == 1


def test_enrich_does_not_overwrite_existing_date(tmpdb, monkeypatch):
    from collector.model import Item

    monkeypatch.setattr(extract, "config", lambda: {
        "enabled": True, "min_score": 0, "max_items": 10, "max_workers": 1,
        "timeout": 5, "max_chars": 6000, "only_when_missing": False, "skip_hosts": [],
    })
    monkeypatch.setattr(extract, "fetch_html", lambda url, **kw: HTML)
    it = Item(source="thebatch", title="已有日期的条目标题", url="https://example.com/b",
              summary="摘要", published="2026-11-01T00:00:00+00:00")
    it.extra["score"] = 80
    extract.enrich_items([it])
    assert it.published == "2026-11-01T00:00:00+00:00", "已有日期不能被页面覆盖"


def test_fetch_failure_changes_nothing(tmpdb, monkeypatch):
    from collector.model import Item

    monkeypatch.setattr(extract, "config", lambda: {
        "enabled": True, "min_score": 0, "max_items": 10, "max_workers": 1,
        "timeout": 5, "max_chars": 6000, "only_when_missing": False, "skip_hosts": [],
    })
    monkeypatch.setattr(extract, "fetch_html", lambda url, **kw: None)
    it = Item(source="thebatch", title="抓不到页面的条目", url="https://example.com/c",
              summary="", published="")
    it.extra["score"] = 80
    stats = extract.enrich_items([it])
    assert stats["failed"] == 1
    assert "body" not in it.extra and it.published == ""
