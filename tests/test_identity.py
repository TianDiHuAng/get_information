"""身份与相似度：跨入口合并、中文标题指纹。"""

from collector.identity import canonical_url, item_identity, title_key, title_similar


def test_canonical_url_drops_tracking():
    assert canonical_url("https://Example.com/post/?utm_source=x&id=7") == "https://example.com/post?id=7"
    assert canonical_url("https://example.com/post/") == "https://example.com/post"


def test_same_article_across_entries_merges():
    """同一篇 arXiv 论文的 abs / pdf 入口必须是同一个身份。"""
    a = item_identity("https://arxiv.org/abs/2611.09891v1")
    b = item_identity("https://arxiv.org/pdf/2611.09891v1.pdf")
    c = item_identity("https://huggingface.co/papers/2611.09891")
    assert a == b == c == "arxiv:2611.09891"


def test_x_status_with_query_merges():
    assert item_identity("https://x.com/foo/status/1234567890?utm_source=tw") == "x:1234567890"


def test_zhihu_and_bilibili_ids():
    assert item_identity("https://zhuanlan.zhihu.com/p/209559") == "zhihu:p:209559"
    assert item_identity("https://www.zhihu.com/answer/209417") == "zhihu:a:209417"
    assert item_identity("https://www.bilibili.com/video/BV1xx411c7mD") == "bili:BV1xx411c7mD"


def test_title_key_keeps_chinese_and_digits():
    assert title_key("OpenAI 发布 GPT-6，支持百万上下文") == "openai发布gpt6支持百万上下文"


def test_title_similarity_is_discriminating():
    # 同一件事、两种说法：只能到 0.5 左右 —— 这正是"光比标题解决不了"的证据
    same_event = title_similar(
        "LG 免费开放 K-EXAONE 2.5 模型 API",
        "LG AI Research 开放 K-EXAONE 2.5 模型免费 API",
    )
    different = title_similar("OpenAI 发布 GPT-6", "英伟达免费开放 API")
    assert different == 0.0
    assert 0.3 < same_event < 0.72


def test_empty_title_does_not_match_everything():
    """空标题不能因为「都为空」就判成相似（历史上这类 bug 会让整站塌成一条）。"""
    assert title_similar("", "完全无关的标题") < 1.0
