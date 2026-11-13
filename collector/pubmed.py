"""PubMed 检索抓取（NCBI E-utilities）。

为什么单独写：PubMed 没有可按检索式取用的 RSS，要走 esearch + efetch 两段。
免费、无鉴权（有 API key 只是提高限流），字段（标题/摘要/日期/DOI）与 Item 一一对应。

限流：无 key 时 3 次/秒，这里两次调用间隔 0.4 秒，够用。
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET

from .model import Item
from .net import get_text

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_UA_HEADERS = {"User-Agent": "ZBit-Radar/1.0 (literature monitor)"}
_last_call = [0.0]


def _throttle(interval: float = 0.4) -> None:
    gap = time.time() - _last_call[0]
    if gap < interval:
        time.sleep(interval - gap)
    _last_call[0] = time.time()


def _esearch(term: str, retmax: int) -> list[str]:
    _throttle()
    url = (f"{EUTILS}/esearch.fcgi?db=pubmed&retmode=json&sort=date"
           f"&retmax={retmax}&term={term}")
    text = get_text(url, headers=_UA_HEADERS, timeout=30)
    if not text:
        return []
    import json

    try:
        data = json.loads(text)
    except Exception:
        return []
    return list((data.get("esearchresult") or {}).get("idlist") or [])


def _efetch(pmids: list[str], source_id: str = "pubmed") -> list[Item]:
    if not pmids:
        return []
    _throttle()
    url = (f"{EUTILS}/efetch.fcgi?db=pubmed&retmode=xml&rettype=abstract"
           f"&id={','.join(pmids)}")
    text = get_text(url, headers=_UA_HEADERS, timeout=45)
    if not text:
        return []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []

    rows: list[Item] = []
    for art in root.findall(".//PubmedArticle"):
        pmid = (art.findtext(".//PMID") or "").strip()
        title = "".join(art.find(".//ArticleTitle").itertext()).strip() if art.find(".//ArticleTitle") is not None else ""
        if not pmid or not title:
            continue

        parts = []
        for node in art.findall(".//AbstractText"):
            label = node.get("Label")
            body = "".join(node.itertext()).strip()
            if body:
                parts.append(f"{label}: {body}" if label else body)
        summary = " ".join(parts)

        year = (art.findtext(".//PubDate/Year")
                or art.findtext(".//ArticleDate/Year") or "").strip()
        month = (art.findtext(".//PubDate/Month")
                 or art.findtext(".//ArticleDate/Month") or "01").strip()
        day = (art.findtext(".//PubDate/Day")
               or art.findtext(".//ArticleDate/Day") or "01").strip()
        months = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
                  "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"}
        month = months.get(month, month.zfill(2))
        published = f"{year}-{month}-{day.zfill(2)}" if year else ""

        journal = art.findtext(".//Journal/Title") or ""
        rows.append(Item(
            source=source_id,
            layer="primary",
            title=title,
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            published=published,
            summary=(f"{journal}. " if journal else "") + summary[:400],
            lang="en",
            region="overseas",
            extra={"pmid": pmid, "journal": journal},
        ))
    return rows


def pubmed(term: str = "", limit: int = 10, source_id: str = "pubmed",
           **_: object) -> list[Item]:
    """按检索式取 PubMed 最新文献。`term` 由 feeds.yaml 的 url 字段传入。"""
    if not term:
        return []
    pmids = _esearch(term, int(limit))
    return _efetch(pmids, source_id)[: int(limit)]
