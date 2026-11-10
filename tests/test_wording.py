"""改用词：命中才改，改坏就退回原文。

这一步最怕的不是改不了，而是**改多了**：润色顺手改了事实、动了数字、
或者模型返回空字符串把标题搞没了。所以测试的重点全在"退回"上。
"""

import pytest

from collector import wording


@pytest.fixture(autouse=True)
def rules_file(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setattr(wording.industry, "CONFIG", config)
    monkeypatch.setattr(wording.industry, "PACKS", tmp_path / "industry")
    monkeypatch.setattr(wording.industry, "SETTINGS_PATH", config / "industry.yaml")
    wording.industry._cache.clear()
    path = config / "wording.yaml"
    path.write_text(
        "rules:\n"
        "  - {pattern: 赋能, replace: 帮助}\n"
        "  - {pattern: 闭环, replace: 完整流程}\n"
        "  - {pattern: '([unclosed', replace: x}\n",
        encoding="utf-8")
    yield path
    wording.industry._cache.clear()


def test_rules_skips_broken_regex(rules_file):
    rules = wording.rules()
    assert len(rules) == 2                     # 坏正则被丢掉，不影响其它规则
    assert {r["pattern"] for r in rules} == {"赋能", "闭环"}


def test_matches_finds_hits(rules_file):
    hits = wording.matches("这个方案能赋能业务，形成闭环")
    assert len(hits) == 2
    assert {h["found"] for h in hits} == {"赋能", "闭环"}


def test_matches_empty_on_plain_text(rules_file):
    assert wording.matches("这是一段普通的话") == []


def test_mend_no_rule_hit_does_not_call_model(rules_file, monkeypatch):
    called = []
    monkeypatch.setattr("collector.llm.call_text", lambda *a, **k: called.append(1))
    out = wording.mend("这是一段普通的话")
    assert out["changed"] is False and out["reason"] == "no-rule-hit"
    assert called == []                        # 没命中就一次都不调


def test_mend_applies_replacement(rules_file, monkeypatch):
    monkeypatch.setattr("collector.llm.call_text",
                        lambda *a, **k: "这个方案能帮助业务，形成完整流程")
    out = wording.mend("这个方案能赋能业务，形成闭环")
    assert out["changed"] is True
    assert out["text"] == "这个方案能帮助业务，形成完整流程"


def test_mend_keeps_original_when_numbers_change(rules_file, monkeypatch):
    """模型顺手改了数字 —— 这一步不该动数字，必须退回。"""
    monkeypatch.setattr("collector.llm.call_text",
                        lambda *a, **k: "这个方案能帮助业务，效率提升 30%")
    out = wording.mend("这个方案能赋能业务，效率提升 40%")
    assert out["changed"] is False
    assert out["reason"] == "numbers-changed"
    assert out["text"] == "这个方案能赋能业务，效率提升 40%"


def test_mend_keeps_original_when_result_blank(rules_file, monkeypatch):
    monkeypatch.setattr("collector.llm.call_text", lambda *a, **k: "   ")
    out = wording.mend("赋能")
    assert out["changed"] is False and out["reason"] == "empty-result"


def test_mend_keeps_original_on_model_error(rules_file, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("模型挂了")

    monkeypatch.setattr("collector.llm.call_text", boom)
    out = wording.mend("赋能")
    assert out["changed"] is False
    assert out["text"] == "赋能"


def test_mend_empty_input(rules_file):
    assert wording.mend("")["changed"] is False


def test_apply_to_items_no_rules_means_zero_calls(tmp_path, monkeypatch):
    config = tmp_path / "c2"
    config.mkdir()
    monkeypatch.setattr(wording.industry, "CONFIG", config)
    monkeypatch.setattr(wording.industry, "SETTINGS_PATH", config / "nope.yaml")
    wording.industry._cache.clear()
    (config / "wording.yaml").write_text("rules: []\n", encoding="utf-8")
    called = []
    monkeypatch.setattr("collector.llm.call_text", lambda *a, **k: called.append(1))
    out = wording.apply_to_items([{"title": "赋能", "summary": "闭环"}])
    assert out == {"checked": 0, "changed": 0, "skipped": 0}
    assert called == []


def test_apply_to_items_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(wording, "rules", lambda: [{"pattern": "赋能", "replace": "帮助"}])
    monkeypatch.setattr("collector.llm.call_text",
                        lambda *a, **k: "帮助业务")
    items = [{"title": "赋能业务", "summary": "无关"}]
    out = wording.apply_to_items(items)
    assert out["checked"] == 1 and out["changed"] == 1
    assert items[0]["title"] == "帮助业务"
