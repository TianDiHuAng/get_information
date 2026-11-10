"""防幻觉校验：模型写的专名与数字，必须能在原文里找到。

这是 AIHOT `grounded()` 的可执行版本：不靠提示词"请不要编"，而是写出检查，
不通过就整段丢弃（宁可没有导读，也不要一段编造的导读）。
"""

from collector import grounding


CORPUS = (
    "Anthropic 发布 Claude Fable 5.2，上下文 100 万 token，API 价格下降 40%。"
    "官方称在 SWE-bench 上提升到 78.3%。"
)


def test_passes_when_everything_is_grounded():
    text = "Anthropic 上线 Claude Fable 5.2，API 价格下降 40%。"
    assert grounding.check(text, CORPUS)["ok"] is True


def test_flags_invented_company():
    text = "OpenAI 同日也宣布降价，行业竞争加剧。"
    verdict = grounding.check(text, CORPUS)
    assert verdict["ok"] is False
    assert "OpenAI" in verdict["unsupported"]


def test_flags_invented_percent():
    text = "Anthropic 这次降价 65%，力度罕见。"
    verdict = grounding.check(text, CORPUS)
    assert verdict["ok"] is False
    assert any("65" in u for u in verdict["unsupported"])


def test_ignores_plain_terms_and_years():
    text = "2026 年，GPU 与 LLM 的成本继续下降，AI 应用落地。"
    assert grounding.check(text, CORPUS)["ok"] is True


def test_ignores_lowercase_english():
    """小写普通英文词（release / model）不是专名，不该判成编造。"""
    text = "这次 release 的重点是 model 能力。"
    assert grounding.check(text, CORPUS)["ok"] is True


def test_ignores_small_numbers():
    """行文里的序号（3 个要点）不该被当成数据。"""
    text = "今天有 3 个要点，其中 1 个值得注意。"
    assert grounding.check(text, CORPUS)["ok"] is True


def test_number_with_decimals_must_appear():
    text = "在 SWE-bench 上达到 91.7%。"
    verdict = grounding.check(text, CORPUS)
    assert verdict["ok"] is False


def test_empty_text_passes():
    assert grounding.check("", CORPUS)["ok"] is True


def test_skip_list_is_honoured():
    text = "据 Hacker News 讨论。"  # 语料里没有，但调用方可以豁免
    assert grounding.check(text, CORPUS)["ok"] is False
    assert grounding.check(text, CORPUS, skip=["Hacker News"])["ok"] is True
