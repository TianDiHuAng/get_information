"""行业包：建、切、体检。

这个模块的价值全在"体检"上 —— 换行业时最容易出错的是**改了一半**：
分类改了但提示词没改，主题引用了不存在的标签，门槛写了两处对不上。
这些错误不会让程序崩溃，只会让页面悄悄变成空的。

所以测试重点：
1. 每种"改了一半"都能被抓出来，且 hint 说得清怎么修；
2. 建包 / 切包不破坏原有配置；
3. 切回 config/ 能完全恢复。
"""

import textwrap

import pytest
import yaml

from collector import industry


@pytest.fixture(autouse=True)
def temp_industry(tmp_path, monkeypatch):
    """把 CONFIG / PACKS / SETTINGS_PATH 全部指到临时目录。"""
    config = tmp_path / "config"
    packs = tmp_path / "industry"
    config.mkdir()
    packs.mkdir()
    monkeypatch.setattr(industry, "CONFIG", config)
    monkeypatch.setattr(industry, "PACKS", packs)
    monkeypatch.setattr(industry, "SETTINGS_PATH", config / "industry.yaml")
    industry._cache.clear()
    yield config, packs
    industry._cache.clear()


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")


def base_config(config):
    write(config / "industry.yaml", """
        name: Z-Bit
        tagline: 今日 AI 热点
        pack: ""
        edition: {daily: "09:00"}
        tiers: {T1: 58, T1_5: 66, T2: 68}
    """)
    write(config / "taxonomy.yaml", """
        categories:
          model_release: {label: 模型发布}
          research_paper: {label: 论文}
        tags: [开源, 智能体]
        entities: [{id: anthropic, label: Anthropic}]
    """)
    write(config / "topics.yaml", """
        topics:
          - slug: open-source
            tags: [开源]
    """)
    write(config / "scoring.yaml", """
        thresholds: {primary: 58, rank: 66, broad: 68, search: 74, social: 76}
    """)
    for name in industry.REQUIRED_PROMPTS:
        write(config / "prompts" / name, "model_release research_paper 开源 智能体")


def test_settings_defaults_when_no_file(temp_industry):
    conf = industry.settings(reload=True)
    assert conf["name"] == "Z-Bit"
    assert conf["tiers"]["T1"] == 58


def test_settings_reads_file_and_merges_sections(temp_industry):
    config, _ = temp_industry
    write(config / "industry.yaml", """
        name: 法律热点
        tiers: {T1: 60}
    """)
    conf = industry.settings(reload=True)
    assert conf["name"] == "法律热点"
    assert conf["tiers"]["T1"] == 60
    assert conf["tiers"]["T2"] == 68          # 没写的沿用默认


def test_validate_clean_pack_has_no_issues(temp_industry):
    config, _ = temp_industry
    base_config(config)
    issues = industry.validate()
    assert issues == [], industry.summary(issues)


def test_validate_flags_missing_required_prompt(temp_industry):
    config, _ = temp_industry
    base_config(config)
    (config / "prompts" / "structure.md").unlink()
    codes = {i["code"] for i in industry.validate()}
    assert "prompt.missing" in codes


def test_validate_flags_empty_name(temp_industry):
    config, _ = temp_industry
    base_config(config)
    write(config / "industry.yaml", 'name: ""\ntagline: 一句话\n')
    codes = {i["code"] for i in industry.validate()}
    assert "meta.empty" in codes


def test_validate_flags_bad_edition_time(temp_industry):
    config, _ = temp_industry
    base_config(config)
    write(config / "industry.yaml", 'name: X\ntagline: Y\nedition: {daily: "9点"}\n')
    codes = {i["code"] for i in industry.validate()}
    assert "meta.edition" in codes


def test_validate_flags_category_missing_from_prompt(temp_industry):
    config, _ = temp_industry
    base_config(config)
    write(config / "taxonomy.yaml", """
        categories:
          model_release: {label: 模型发布}
          brand_new_type: {label: 新类型}
    """)
    issues = [i for i in industry.validate() if i["code"] == "prompt.category"]
    assert any("brand_new_type" in i["message"] for i in issues)
    assert issues[0]["hint"]


def test_validate_flags_duplicate_category_key(temp_industry):
    config, _ = temp_industry
    base_config(config)
    write(config / "taxonomy.yaml", """
        categories:
          - {key: a, label: A}
          - {key: a, label: B}
    """)
    codes = {i["code"] for i in industry.validate()}
    assert "taxonomy.dup" in codes


def test_validate_flags_topic_unknown_tag(temp_industry):
    config, _ = temp_industry
    base_config(config)
    write(config / "topics.yaml", """
        topics:
          - slug: ghost
            tags: [不存在的标签]
    """)
    issues = [i for i in industry.validate() if i["code"] == "topic.tag"]
    assert issues and "ghost" in issues[0]["message"]


def test_validate_flags_topic_unknown_entity(temp_industry):
    config, _ = temp_industry
    base_config(config)
    write(config / "topics.yaml", """
        topics:
          - slug: acme
            entity: not-a-real-entity
    """)
    codes = {i["code"] for i in industry.validate()}
    assert "topic.entity" in codes


def test_validate_warns_when_new_pack_has_no_own_thresholds(temp_industry):
    """换了行业却沿用 AI 行业的门槛 —— 最容易忘、后果最大的一步。"""
    config, packs = temp_industry
    base_config(config)
    industry.scaffold("legal", "法律热点")
    industry.use("legal")
    write(config / "industry.yaml", 'name: 法律热点\ntagline: Y\npack: legal\n')
    industry._cache.clear()
    codes = {i["code"] for i in industry.validate()}
    assert "threshold.uncalibrated" in codes


def test_validate_flags_threshold_drift(temp_industry):
    config, _ = temp_industry
    base_config(config)
    write(config / "industry.yaml",
          'name: X\ntagline: Y\ntiers: {T1: 50, T1_5: 66, T2: 68}\n')
    issues = [i for i in industry.validate() if i["code"] == "threshold.drift"]
    assert issues and "58" in issues[0]["message"]


def test_validate_flags_broken_wording_regex(temp_industry):
    config, _ = temp_industry
    base_config(config)
    write(config / "wording.yaml", """
        rules:
          - pattern: "([unclosed"
            replace: x
    """)
    codes = {i["code"] for i in industry.validate()}
    assert "wording.regex" in codes


def test_scaffold_creates_files(temp_industry):
    config, packs = temp_industry
    base_config(config)
    out = industry.scaffold("legal", "法律热点")
    assert out["ok"]
    folder = packs / "legal"
    assert (folder / "taxonomy.yaml").exists()
    assert (folder / "prompts" / "attention-score.md").exists()
    # 其它提示词拷贝了一份，改起来比从零写快
    assert (folder / "prompts" / "structure.md").exists()


def test_scaffold_refuses_existing_pack(temp_industry):
    config, packs = temp_industry
    base_config(config)
    industry.scaffold("legal", "法律热点")
    again = industry.scaffold("legal", "法律热点")
    assert again["ok"] is False and "已存在" in again["error"]


def test_scaffold_rejects_bad_slug(temp_industry):
    config, _ = temp_industry
    base_config(config)
    assert industry.scaffold("Bad Slug!", "X")["ok"] is False


def test_pack_overrides_config_then_restores(temp_industry):
    config, packs = temp_industry
    base_config(config)
    industry.scaffold("legal", "法律热点")
    write(packs / "legal" / "taxonomy.yaml", """
        categories:
          policy: {label: 政策}
    """)
    industry.use("legal")
    assert industry.pack_path("taxonomy.yaml").parent.name == "legal"
    assert "policy" in industry.load("taxonomy.yaml")["categories"]

    industry.use("")
    assert industry.pack_path("taxonomy.yaml") == config / "taxonomy.yaml"
    assert "model_release" in industry.load("taxonomy.yaml")["categories"]


def test_use_rejects_unknown_pack(temp_industry):
    config, _ = temp_industry
    base_config(config)
    assert industry.use("nope")["ok"] is False


def test_use_keeps_other_settings(temp_industry):
    config, packs = temp_industry
    base_config(config)
    write(config / "industry.yaml", """
        name: 法律热点
        tagline: 法律人的每日必读
        pack: ""
        tiers: {T1: 60, T1_5: 66, T2: 68}
    """)
    industry.scaffold("legal", "法律热点")
    industry.use("legal")
    raw = yaml.safe_load((config / "industry.yaml").read_text(encoding="utf-8"))
    assert raw["pack"] == "legal"
    assert raw["name"] == "法律热点"
    assert raw["tiers"]["T1"] == 60
