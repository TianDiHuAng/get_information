"""换行业时那几个"细节"：对外合并分类、接口版本、隐藏导航、三张词典、
报头字、字体回退、按步骤切模型。

这些都不是核心流程，但少了任何一个，换行业后就会有一块静默地不对 ——
所以每一个都要有测试。
"""

import pytest

from collector import export, grounding, llm, share, theme, topics


# —— 对外合并分类 —— #

def test_public_category_merges_via_config(monkeypatch):
    from collector import industry

    monkeypatch.setattr(industry, "settings", lambda reload=False: {
        "public_categories": {"deal": "model_release"}})
    assert export.public_category("deal") == "model_release"
    assert export.public_category("research_paper") == "research_paper"
    assert export.public_category("") == "other"


def test_public_category_no_mapping_is_identity(monkeypatch):
    from collector import industry

    monkeypatch.setattr(industry, "settings", lambda reload=False: {"public_categories": {}})
    assert export.public_category("deal") == "deal"


# —— 接口版本 —— #

def test_api_carries_version(monkeypatch):
    from collector import industry

    monkeypatch.setattr(industry, "settings", lambda reload=False: {"api_version": "2"})
    payload = export.render_api([], generated_at="2026-11-10T09:00:00")
    assert payload["version"] == "2"


# —— 隐藏导航 —— #

def test_nav_hides_configured_entries(monkeypatch):
    from collector import industry

    monkeypatch.setattr(industry, "settings", lambda reload=False: {"nav_hidden": ["/hot.html"]})
    doc = theme.nav_html("/")
    assert "/hot.html" not in doc
    assert "/all.html" in doc              # 其它入口不受影响


def test_nav_shows_everything_by_default(monkeypatch):
    from collector import industry

    monkeypatch.setattr(industry, "settings", lambda reload=False: {"nav_hidden": []})
    assert "/hot.html" in theme.nav_html("/")


# —— 三张词典 —— #

def test_publisher_domain_exempts_own_name():
    """自家域名发的稿，标题点自己的名不需要正文再核。"""
    assert grounding.unsupported("Anthropic 发布新模型", "今天发布",
                                 url="https://www.anthropic.com/news/x") == []


def test_unknown_publisher_name_still_flagged():
    assert grounding.unsupported("OpenAI 发布新模型", "今天发布") == ["OpenAI"]


def test_identity_lexicon_alias_needs_canonical_in_corpus():
    """Claude 指 Anthropic：正文提到 Anthropic 才算有依据。"""
    assert grounding.unsupported("Claude 表现不错", "Anthropic 公布了成绩") == []
    assert grounding.unsupported("Claude 表现不错", "今天公布了成绩") == ["Claude"]


def test_context_alias_requires_context():
    assert grounding.unsupported("豆包更新了", "字节跳动发布了新版本") == []
    assert grounding.unsupported("豆包更新了", "今天发布了新版本") == ["豆包"]


# —— 主题三分组 —— #

def test_grouped_topics_has_three_groups():
    groups = topics.grouped_topics([])
    assert [g["key"] for g in groups] == ["company", "field", "genre"]
    assert all(g["topics"] == [] for g in groups)


def test_grouped_topics_matches_company_by_display_name():
    """subjects 存的是显示名（Anthropic），不是实体 id（anthropic）。"""
    rows = [{"title": "Anthropic 发布", "url": "https://a/1", "source": "x",
             "published": "2026-11-10", "subjects": ["Anthropic"], "tags": []}]
    groups = topics.grouped_topics(rows)
    company = next(g for g in groups if g["key"] == "company")
    anthropic = next((t for t in company["topics"] if t["slug"] == "anthropic"), None)
    assert anthropic and anthropic["count"] == 1


def test_grouped_topics_matches_field_by_tag():
    rows = [{"title": "某开源项目", "url": "https://a/2", "source": "x",
             "published": "2026-11-10", "subjects": [], "tags": ["开源"]}]
    groups = topics.grouped_topics(rows)
    field = next(g for g in groups if g["key"] == "field")
    assert any(t["slug"] == "open-source" and t["count"] == 1 for t in field["topics"])


# —— 按步骤切模型 —— #

def test_model_for_uses_step_override(tmp_path, monkeypatch):
    conf = tmp_path / "llm.yaml"
    conf.write_text("model: default-model\nsteps:\n  translate: cheap-model\n", encoding="utf-8")
    monkeypatch.setattr(llm, "CONFIG_PATH", conf)
    assert llm.model_for("translate") == "cheap-model"
    assert llm.model_for("attention-score") == "default-model"


def test_model_for_falls_back_when_no_config(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "CONFIG_PATH", tmp_path / "nope.yaml")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert llm.model_for("anything") is None


# —— 字体回退链 —— #

def test_font_chain_returns_usable_fonts():
    fonts = share._font_chain(24, bold=False)
    # 这台机器上至少有一种中文字体；没有就说明环境问题，跳过
    if not fonts:
        pytest.skip("没有可用字体")
    assert share._has_glyph(fonts[0], "报")
    assert share.text_width("测试", fonts) > 0


def test_custom_font_dir_is_preferred(tmp_path, monkeypatch):
    monkeypatch.setattr(share, "FONTS_DIR", tmp_path)
    assert share._custom_fonts(bold=False) == []      # 空目录不影响


def test_draw_text_does_not_raise_without_fonts():
    class FakeDraw:
        def text(self, *a, **k):
            raise AssertionError("没有字体时不该尝试绘制")

    share.draw_text(FakeDraw(), (0, 0), "abc", [], (0, 0, 0))   # 静默返回
