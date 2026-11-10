"""抓 arXiv 论文正文，抽出可读的「问题 / 方法 / 结果 / 局限」四段素材。

只给摘要写不出深度稿，所以需要正文。arXiv 近年论文有 HTML 版
（https://arxiv.org/html/<id>v1），比 PDF 好解析、无需 OCR。
拿不到 HTML 时退回摘要，绝不报错。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

from .net import get_text

CACHE = Path(__file__).parent.parent / "data" / "paper_full_cache.json"

# 章节名 → 归类（英文标题小写匹配）
WANT = [
    ("intro", ("introduction", "motivation", "problem")),
    ("method", ("method", "approach", "framework", "architecture", "benchmark",
                "experimental setup", "problem formulation", "model")),
    ("results", ("result", "experiment", "evaluation", "finding")),
    ("conclusion", ("conclusion", "discussion", "limitation", "future work")),
]


def _cache() -> dict:
    if not CACHE.exists():
        return {}
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(c: dict) -> None:
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")


def _clean(t: str) -> str:
    t = re.sub(r"\[[0-9,\s]+\]", "", t or "")  # 去引用编号
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    # 尽量在句号处收尾
    for sep in (". ", "。", "! ", "? "):
        i = cut.rfind(sep)
        if i > limit * 0.6:
            return cut[: i + len(sep)].strip()
    return cut.strip()


def fetch_sections(paper_id: str, per_section: int = 520) -> dict:
    """返回 {abstract, intro, method, results, conclusion, ok}。失败时 ok=False。"""
    cache = _cache()
    if paper_id in cache:
        return cache[paper_id]

    out: dict = {"id": paper_id, "ok": False}
    html = ""
    for url in (f"https://arxiv.org/html/{paper_id}v1", f"https://arxiv.org/html/{paper_id}"):
        try:
            html = get_text(url, timeout=45)
            if len(html) > 5000:
                break
        except Exception:
            html = ""
    if not html:
        return out

    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.select("nav, script, style, figure, table, .ltx_bibliography"):
            tag.decompose()

        abs_el = (
            soup.select_one(".ltx_abstract")
            or soup.select_one("blockquote.abstract")
            or soup.select_one("div.abstract")
        )
        abstract = _clean(abs_el.get_text(" ", strip=True)) if abs_el else ""
        abstract = re.sub(r"^Abstract\s*", "", abstract)

        buckets: dict[str, list[str]] = {k: [] for k, _ in WANT}
        current = None
        for el in soup.find_all(["h2", "h3", "p"]):
            if el.name in ("h2", "h3"):
                title = _clean(el.get_text(" ", strip=True)).lower()
                if el.name == "h3":
                    # 子章节：只有明确换了主题才切桶，否则沿用上级章节
                    for key, words in WANT:
                        if any(w in title for w in words):
                            current = key
                            break
                else:
                    current = None
                    for key, words in WANT:
                        if any(w in title for w in words):
                            current = key
                            break
            elif el.name == "p" and current:
                t = _clean(el.get_text(" ", strip=True))
                if len(t) > 80:
                    buckets[current].append(t)

        out.update(
            {
                "ok": True,
                "abstract": _trim(abstract, 1400),
                "intro": _trim(" ".join(buckets["intro"][:3]), per_section),
                "method": _trim(" ".join(buckets["method"][:3]), per_section),
                "results": _trim(" ".join(buckets["results"][:3]), per_section),
                "conclusion": _trim(" ".join(buckets["conclusion"][:2]), per_section),
            }
        )
    except Exception:
        out["ok"] = False
        return out

    cache[paper_id] = out
    _save(cache)
    return out


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for pid in sys.argv[1:] or ["2611.09818"]:
        d = fetch_sections(pid)
        print(f"\n=== {pid} ok={d.get('ok')}")
        for k in ("abstract", "intro", "method", "results", "conclusion"):
            v = d.get(k) or ""
            print(f"-- {k} ({len(v)}): {v[:160]}")
