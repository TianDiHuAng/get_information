"""条目的「身份」：URL 规范化、平台原生 ID、标题指纹、相似度。

为什么单独一个模块：
- store.py（跨天去重）和 rating.py（事件聚簇）都要用，它们不该反过来依赖 pipeline；
- 同一篇文章在不同入口下的 URL 往往不同（`m.weibo.cn/detail/123` vs
  `weibo.com/123/abc`、`arxiv.org/abs/x` vs `arxiv.org/pdf/x`），
  只有认平台原生 ID 才能合并，光比 URL 或标题都不够。

实测依据：原来只做 URL 规范化 + 标题 Jaccard，两天日报有 41–43% 重复，
其中既有「跨天没记忆」（store 解决），也有「同文章不同入口」（本模块解决）。
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# 追踪参数：删掉不影响文章身份
DROP_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "spm", "from", "share_token", "ref", "ref_src", "fbclid", "gclid",
    "oc",  # Google News 的 ?oc=5：同一条新闻不同版面会带不同值
}

# 平台原生 ID：命中就用它做身份，跨域名/跨入口都能合并。
# 顺序有意义：先宽后窄，先具体后通用。
NATIVE_ID_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"x\.com/[^/]+/status/(\d+)"), "x:"),
    (re.compile(r"twitter\.com/[^/]+/status/(\d+)"), "x:"),
    (re.compile(r"weibo\.(?:com|cn)/(?:detail|status)/(\d+)"), "weibo:"),
    (re.compile(r"zhihu\.com/answer/(\d+)"), "zhihu:a:"),
    (re.compile(r"zhihu\.com/question/(\d+)"), "zhihu:q:"),
    (re.compile(r"zhuanlan\.zhihu\.com/p/(\d+)"), "zhihu:p:"),
    (re.compile(r"bilibili\.com/video/(BV[0-9A-Za-z]+)"), "bili:"),
    (re.compile(r"bilibili\.com/video/av(\d+)", re.I), "bili:av:"),
    (re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})"), "arxiv:"),
    (re.compile(r"huggingface\.co/papers/(\d{4}\.\d{4,5})"), "arxiv:"),
    (re.compile(r"github\.com/([^/]+/[^/?#]+)/releases"), "gh:rel:"),
    (re.compile(r"t\.me/([^/]+)/(\d+)"), "tg:"),
]

# 这些站点的查询串常常是文章身份的一部分，不能一概丢掉
KEEP_QUERY_HOSTS = {"news.google.com", "www.bing.com"}


def canonical_url(url: str) -> str:
    """规范化 URL：去追踪参数、统一大小写与尾斜杠。"""
    try:
        p = urlparse(url.strip())
        if not p.scheme or not p.netloc:
            return url.strip()
        if p.netloc.endswith("toutiao.com"):
            return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))
        if p.netloc in KEEP_QUERY_HOSTS:
            q = parse_qsl(p.query, keep_blank_values=False)
            return urlunparse((p.scheme, p.netloc.lower(), p.path.rstrip("/"), "", urlencode(q), ""))
        q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=False) if k not in DROP_PARAMS]
        return urlunparse((p.scheme, p.netloc.lower(), p.path.rstrip("/"), "", urlencode(q), ""))
    except Exception:
        return url.strip()


def item_identity(url: str) -> str:
    """一条内容的稳定身份。同一篇文章换了入口，身份不变。"""
    canon = canonical_url(url)
    for pattern, prefix in NATIVE_ID_PATTERNS:
        m = pattern.search(canon)
        if m:
            tail = m.group(2) if m.lastindex and m.lastindex >= 2 else ""
            return f"{prefix}{m.group(1)}{(':' + tail) if tail else ''}"
    return "url:" + canon


def title_key(title: str) -> str:
    """标题指纹：只留中英文与数字。"""
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", (title or "").lower())


def bigrams(text: str) -> set[str]:
    """字符二元组，用于中文短标题的粗相似度。"""
    t = title_key(text)
    return {t[i : i + 2] for i in range(len(t) - 1)} if len(t) > 1 else {t}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def title_similar(a: str, b: str) -> float:
    return jaccard(bigrams(a), bigrams(b))
