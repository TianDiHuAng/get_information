"""兑换码提取：只抽真正可用的凭据，不把普通英文单词当码。

用例取自 freebie-radar 的 enrich/codes.ts 语义，移植后按 Python 风格验收。
"""

from collector import codes


def test_explicit_code_with_label():
    assert codes.extract_codes("邀请码: ABC12345")[0] == "ABC12345"
    assert codes.extract_codes("兑换码：GIFT-2026-FREE")[0] == "GIFT-2026-FREE"
    assert codes.extract_codes("code=SAVE50NOW")[0] == "SAVE50NOW"


def test_dashed_and_long_upper():
    assert "ABCD-EFGH-IJKL" in codes.extract_codes("CDKEY ABCD-EFGH-IJKL 限量发放")
    assert "ALLUPPERCASECODE123" in codes.extract_codes("口令 ALLUPPERCASECODE123")


def test_plausible_filters():
    # 纯数字、停用词、URL 片段、太短 —— 都不算码
    assert codes.extract_codes("兑换码 12345678") == []
    assert codes.extract_codes("兑换码 FREE") == []
    assert codes.extract_codes("兑换码 https123") == []
    assert codes.extract_codes("兑换码 AB") == []


def test_dedup_and_limit():
    got = codes.extract_codes("邀请码 ABCD1234 兑换码 ABCD1234 口令 WXYZ9876")
    assert got.count("ABCD1234") == 1
    assert len(codes.extract_codes(" ".join(f"兑换码 CODE{i:04d}X" for i in range(10)), limit=3)) == 3


def test_empty():
    assert codes.extract_codes() == []
    assert codes.extract_codes("没有任何码的标题", None) == []
