"""防幻觉校验：模型写出来的东西，必须能在原文里找到依据。

吸收自 AIHOT 的 `grounded()` 思路（周报月报里逐词比对语料，不达标整段丢弃），
但这里做得更明确：**不是靠提示词"请不要编"，而是写出可执行的检查**。

检查两类最容易被编造的东西：
1. **专名**：拉丁字母的公司/产品名（`Gemini`、`Claude`、`Qwen`）——标题里冒出原文没有的公司，
   是最常见的张冠李戴；
2. **数字**：3 位以上、或带小数/百分号的数字——"提升 40%" 里的 40% 原文没有，就是编的。

豁免：通用技术词（`AI`、`GPU`、`LLM`…，见 `config/taxonomy.yaml` 的 `plain_terms`）、
四位年份（`2026` 常出现在语料之外），以及词表里实体的**别名**。
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).parent.parent
TAXONOMY_PATH = ROOT / "config" / "taxonomy.yaml"

_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9.+\-]{2,}")
_NUMBER = re.compile(r"\d+(?:\.\d+)?\s*%?")
_YEAR = re.compile(r"^(19|20)\d{2}$")

_lock = threading.Lock()
_cache: dict[str, Any] = {"mtime": 0.0, "value": {}}


def taxonomy() -> dict[str, Any]:
    try:
        mtime = TAXONOMY_PATH.stat().st_mtime
    except OSError:
        return {}
    with _lock:
        if _cache["mtime"] == mtime:
            return _cache["value"]
        try:
            value = yaml.safe_load(TAXONOMY_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            value = {}
        _cache.update(mtime=mtime, value=value)
        return value


def plain_terms() -> set[str]:
    """豁免词（小写）：只含通用技术词。

    注意**不能**把实体名放进豁免 —— 那正是要检查的对象：
    `OpenAI` 若不在原文里，就是模型补出来的公司，必须被抓到。
    """
    tax = taxonomy()
    return {str(t).lower() for t in (tax.get("plain_terms") or [])}


def entity_terms() -> set[str]:
    """词表里的实体名与别名（供别处做"是否本行业相关公司"的判断，不用于豁免）。"""
    tax = taxonomy()
    out: set[str] = set()
    for ent in (tax.get("entities") or {}).values():
        name = str(ent.get("name") or "")
        if name:
            out.add(name.lower())
        out.update(str(a).lower() for a in (ent.get("aliases") or []))
    return out


def publisher_owner(url: str) -> str:
    """这个网址属于哪家机构（publisher_domains 里配的）。没有就返回空。"""
    tax = taxonomy()
    domains = tax.get("publisher_domains") or {}
    host = ""
    try:
        from urllib.parse import urlparse

        host = (urlparse(url or "").hostname or "").lower()
    except Exception:
        host = ""
    if not host:
        return ""
    for domain, entity in domains.items():
        d = str(domain).lower().lstrip(".")
        if host == d or host.endswith("." + d):
            return str(entity)
    return ""


def _entity_names(entity_id: str) -> set[str]:
    """一个实体的所有叫法（名字、label、别名），小写。"""
    ent = (taxonomy().get("entities") or {}).get(entity_id) or {}
    names = {str(ent.get("name") or ""), str(ent.get("label") or ""), str(entity_id)}
    names.update(str(a) for a in (ent.get("aliases") or []))
    return {n.lower() for n in names if n}


def _norm(text: str) -> str:
    """把语料压成可比对的形式：小写、去掉空白与常见分隔变形。"""
    return re.sub(r"\s+", "", (text or "").lower())


def unsupported(text: str, corpus: str, *, skip: Iterable[str] = (),
                url: str = "") -> list[str]:
    """返回 `text` 里找不到依据的专名与数字（去重、保序）。空列表表示通过。"""
    if not text:
        return []
    # skip 里的多词短语要拆成单词才能和 token 对上（"Hacker News" → hacker / news）
    skip_words = {w.lower() for s in skip for w in str(s).replace("-", " ").split()}
    plain = plain_terms() | skip_words
    corpus_n = _norm(corpus)
    corpus_raw = corpus or ""
    tax = taxonomy()
    # 三张表：自家域名发的稿、易混别名、上下文别名
    owner = publisher_owner(url)
    owner_names = _entity_names(owner) if owner else set()
    lexicon = {str(k).lower(): str(v) for k, v in (tax.get("identity_lexicon") or {}).items()}
    context_aliases = {str(k).lower(): str(v)
                       for k, v in (tax.get("identity_context_aliases") or {}).items()}
    bad: list[str] = []

    def add(token: str) -> None:
        if token not in bad:
            bad.append(token)

    for m in _LATIN.finditer(text):
        word = m.group(0)
        low = word.lower()
        if len(low) < 3 or low in plain:
            continue
        # 只查专名：模型写英文产品名会大写；小写的普通英文词（release / model）不当作编造
        if not word[0].isupper():
            continue
        # 1) 自家域名：信源就是这家机构，标题点自己的名不需要正文再核
        if low in owner_names:
            continue
        # 2) 易混别名：只要对应的机构名在正文里出现过，就算有依据
        target = lexicon.get(low)
        if target and any(_norm(n) in corpus_n for n in _entity_names(target)):
            continue
        # 3) 上下文别名：单独出现不算机构名，必须上文提过
        target = context_aliases.get(low)
        if target and any(_norm(n) in corpus_n for n in _entity_names(target)):
            continue
        if _norm(word) and _norm(word) in corpus_n:
            continue
        if low in corpus_n:
            continue
        add(word)

    # 中文实体名：只查词表里的公司与别名，不做泛化识别（避免把普通词当人名）
    cjk = re.compile(r"[\u4e00-\u9fff]{2,}")
    for entity_id, ent in (tax.get("entities") or {}).items():
        names = [str(ent.get("name") or ""), str(ent.get("label") or "")]
        names += [str(a) for a in (ent.get("aliases") or [])]
        for name in names:
            if not name or not cjk.search(name):
                continue
            if name not in text:
                continue
            if name in corpus_raw or _norm(name) in corpus_n:
                continue
            # 上下文别名：只有上文提过这家机构才算数
            if name in (tax.get("identity_context_aliases") or {}):
                if any(_norm(n) in corpus_n for n in _entity_names(entity_id)):
                    continue
            add(name)

    for m in _NUMBER.finditer(text):
        raw = m.group(0).strip()
        digits = raw.rstrip("% ").replace(".", "").replace(" ", "")
        if _YEAR.match(digits):
            continue
        has_pct = "%" in raw
        # 3 位数太多是行文里的序号（"3 个要点"），只认真数据：带 % / 小数点 / 4 位以上
        if len(digits) < 4 and not has_pct and "." not in raw:
            continue
        if raw in corpus_raw or raw.replace(" ", "") in _norm(corpus_raw):
            continue
        add(raw)

    return bad


def check(text: str, corpus: str, *, skip: Iterable[str] = (),
          url: str = "") -> dict[str, Any]:
    """给调用方一个结构化结果，方便日志与降级判断。"""
    bad = unsupported(text, corpus, skip=skip, url=url)
    return {"ok": not bad, "unsupported": bad}
