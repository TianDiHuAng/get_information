"""统一屏蔽词（来自 freebie-radar 的 enrich/blocklist.ts）。"""

from pathlib import Path

from collector import blocklist


def test_preset_keyword():
    rules = blocklist.load_block_rules(Path("/nonexistent/blocklist.yaml"))
    assert blocklist.is_blocked("避坑指南", rules)
    assert blocklist.is_blocked("某品牌致歉声明", rules)
    assert not blocklist.is_blocked("Epic 免费游戏", rules)


def test_custom_regex_and_scope(tmp_path):
    cfg = tmp_path / "blocklist.yaml"
    cfg.write_text(
        "preset: false\n"
        "rules:\n"
        "  - pattern: '^广告|推广合作'\n"
        "    mode: regex\n"
        "    scope: linuxdo\n"
        "  - pattern: 博彩\n"
        "    mode: keyword\n",
        encoding="utf-8",
    )
    rules = blocklist.load_block_rules(cfg)
    assert blocklist.is_blocked("广告位招租", rules, "linuxdo")
    assert not blocklist.is_blocked("广告位招租", rules, "v2ex")  # scope 不匹配
    assert blocklist.is_blocked("博彩网站", rules, "any")  # scope 默认 all


def test_invalid_regex_degrades_gracefully(tmp_path):
    cfg = tmp_path / "blocklist.yaml"
    cfg.write_text("preset: false\nrules:\n  - pattern: '['\n    mode: regex\n", encoding="utf-8")
    rules = blocklist.load_block_rules(cfg)
    assert rules and rules[0].mode == "keyword"
    assert blocklist.is_blocked("文本含 [ 字符", rules)
