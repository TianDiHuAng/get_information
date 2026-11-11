"""站点前缀：两个行业站合并成一个网站时的链接规则。

这条规则最容易错的是**切换器自己被加前缀** —— 点 AI 却还停在 AIDD，
用户会以为"坏了"。所以专门测。
"""

import pytest

from collector import theme


@pytest.fixture(autouse=True)
def reset_base():
    theme.set_base("")
    yield
    theme.set_base("")


def test_root_site_has_no_prefix():
    doc = theme.page("精选", "<p>x</p>", active="/")
    assert 'href="/all.html"' in doc
    assert "@@ROOT@@" not in doc


def test_subsite_prefixes_internal_links():
    theme.set_base("/aidd")
    doc = theme.page("精选", '<a href="/all.html">全部</a>', active="/all.html")
    assert 'href="/aidd/all.html"' in doc
    assert "@@ROOT@@" not in doc


def test_switcher_links_stay_absolute():
    """切换器必须始终指向 / 与 /aidd/，不能被前缀二次改写。"""
    theme.set_base("/aidd")
    doc = theme.page("精选", "", active="/")
    assert 'href="/">AI' in doc
    assert 'href="/aidd/">AIDD' in doc
    assert 'href="/aidd/aidd/"' not in doc


def test_brand_points_to_current_site():
    theme.set_base("/aidd")
    doc = theme.page("精选", "", active="/")
    assert 'class="brand" href="/aidd/"' in doc

    theme.set_base("")
    doc = theme.page("精选", "", active="/")
    assert 'class="brand" href="/"' in doc


def test_subsite_admin_points_to_root():
    theme.set_base("/aidd")
    doc = theme.page("精选", "", active="/")
    assert 'href="/admin.html"' in doc          # 后台只有根站一份
    assert 'href="/aidd/admin.html"' not in doc


def test_external_links_untouched():
    theme.set_base("/aidd")
    doc = theme.page("精选", '<a href="https://example.com/x">外链</a>', active="/")
    assert 'href="https://example.com/x"' in doc
