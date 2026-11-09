from __future__ import annotations

import json
import math
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import yaml

from .model import Item
from .sources import REGISTRY, build_fetchers, region_of

DROP_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "spm", "from", "share_token", "ref", "ref_src", "fbclid", "gclid",
}
TOPICS_PATH = Path(__file__).parent.parent / "config" / "topics.yaml"


def _load_patterns() -> list[re.Pattern]:
    try:
        data = yaml.safe_load(TOPICS_PATH.read_text(encoding="utf-8")) or {}
        kws = [str(k).strip().lower() for k in data.get("keywords", []) if str(k).strip()]
    except Exception:
        kws = []
    pats = []
    for kw in kws:
        if re.fullmatch(r"[a-z0-9+#.\-]+", kw):
            pats.append(re.compile(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", re.I))
        else:
            pats.append(re.compile(re.escape(kw), re.I))
    return pats


PATTERNS = _load_patterns()


def _domestic_patterns() -> list[re.Pattern]:
    try:
        data = yaml.safe_load(TOPICS_PATH.read_text(encoding="utf-8")) or {}
        kws = [str(k).strip().lower() for k in (data.get("domestic_keywords") or []) if str(k).strip()]
    except Exception:
        kws = []
    pats = []
    for kw in kws:
        if re.fullmatch(r"[a-z0-9+#.-]+", kw):
            pats.append(re.compile(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", re.I))
        else:
            pats.append(re.compile(re.escape(kw), re.I))
    return pats


DOMESTIC_PATTERNS = _domestic_patterns()


def _deal_patterns() -> list[re.Pattern]:
    try:
        data = yaml.safe_load(TOPICS_PATH.read_text(encoding="utf-8")) or {}
        kws = [str(k).strip().lower() for k in (data.get("deal_keywords") or []) if str(k).strip()]
    except Exception:
        kws = []
    pats = []
    for kw in kws:
        if re.fullmatch(r"[a-z0-9+#.-]+", kw):
            pats.append(re.compile(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", re.I))
        else:
            pats.append(re.compile(re.escape(kw), re.I))
    return pats


DEAL_PATTERNS = _deal_patterns()

WEIGHT = {"primary": 1.1, "rank": 1.0, "search": 0.9, "social": 0.9, "broad": 0.85}
# 不同层的“保鲜期”：周报/长文不该按小时衰减
HALFLIFE = {"primary": 96.0, "rank": 18.0, "broad": 48.0, "search": 18.0, "social": 12.0}


def canonical_url(url: str) -> str:
    try:
        p = urlparse(url.strip())
        if p.netloc.endswith("toutiao.com"):
            return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))
        q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=False) if k not in DROP_PARAMS]
        return urlunparse((p.scheme, p.netloc.lower(), p.path.rstrip("/"), "", urlencode(q), ""))
    except Exception:
        return url.strip()


def title_key(title: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", title.lower())


def bigrams(text: str) -> set[str]:
    t = title_key(text)
    return {t[i : i + 2] for i in range(len(t) - 1)} if len(t) > 1 else {t}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _age_hours(item: Item) -> float:
    if not item.published:
        return 48.0
    try:
        dt = datetime.fromisoformat(item.published)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600)
    except Exception:
        return 48.0


# 单源等待上限：X 要跑多条 Apify 查询，必须放宽
SOURCE_TIMEOUT = {"x": 900, "deals": 180, "weibo": 180, "zhihu": 180, "smolai": 120}


def fetch_all(max_workers: int = 8) -> tuple[list[Item], list[dict], dict, set[str]]:
    fetchers = build_fetchers()
    items: list[Item] = []
    errors: list[dict] = []
    counts: dict[str, int] = {}
    ok_sources: set[str] = set()
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fn): sid for sid, fn in fetchers}
        for fut in as_completed(futures):
            sid = futures[fut]
            try:
                got = fut.result(timeout=SOURCE_TIMEOUT.get(sid, 90)) or []
                items.extend(got)
                counts[sid] = len(got)
                ok_sources.add(sid)  # 抓取成功但 0 条（如 X 本轮没有新推文）也算健康
                print(f"  ✓ {sid:<12} {len(got):>3} 条")
            except Exception as e:
                counts[sid] = 0
                errors.append({"source": sid, "error": f"{type(e).__name__}: {e}"})
                print(f"  ✗ {sid:<12} {type(e).__name__}: {e}")
    return items, errors, counts, ok_sources


def dedupe(items: list[Item]) -> list[Item]:
    """URL 完全去重 + 标题近重复（同事件跨源合并）。"""
    by_url: dict[str, Item] = {}
    for it in items:
        key = canonical_url(it.url)
        it.url = key
        if key not in by_url:
            by_url[key] = it
        else:
            by_url[key].extra.setdefault("also", []).append(it.source)

    kept: list[Item] = []
    for it in by_url.values():
        grams = bigrams(it.title)
        merged = False
        for k in kept:
            if jaccard(grams, bigrams(k.title)) > 0.72:
                k.extra.setdefault("also", []).append(it.source)
                if (it.heat or 0) > (k.heat or 0):
                    k.heat = it.heat
                merged = True
                break
        if not merged:
            kept.append(it)
    return kept


def score(items: list[Item]) -> list[Item]:
    max_heat: dict[str, float] = {}
    for it in items:
        if it.heat:
            max_heat[it.source] = max(max_heat.get(it.source, 0), it.heat)

    for it in items:
        recency = math.exp(-math.log(2) * _age_hours(it) / HALFLIFE.get(it.layer, 24.0))
        if it.heat and max_heat.get(it.source):
            heat = math.log1p(it.heat) / math.log1p(max_heat[it.source])
        else:
            heat = 0.35
        base = 100 * (0.4 * recency + 0.4 * heat + 0.2 * WEIGHT.get(it.layer, 0.8))
        text = f"{it.title} {it.summary}"
        topic = any(p.search(text) for p in PATTERNS)
        it.extra["topic"] = topic
        if it.source == "deals":
            # 羊毛源按标题二次校验，剔掉"收费/涨价"这类反向新闻
            it.extra["deal"] = bool(DEAL_PATTERNS and any(p.search(it.title) for p in DEAL_PATTERNS))
        else:
            it.extra["deal"] = bool(
                it.extra.get("deal")
                or (topic and DEAL_PATTERNS and any(p.search(it.title) for p in DEAL_PATTERNS))
            )
        if topic:
            base = min(100.0, base * 1.12)
        it.extra["score"] = round(base, 1)
        it.extra["age_h"] = round(_age_hours(it), 1)

    return sorted(items, key=lambda x: x.extra["score"], reverse=True)


def _proxy_ok(host: str = "127.0.0.1", port: int = 10808, timeout: float = 1.0) -> bool:
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def run() -> dict:
    print("[1/4] 抓取...")
    proxy_ok = _proxy_ok()
    print(f"      代理 127.0.0.1:10808 {'可用' if proxy_ok else '不可用（墙外源将全部失败）'}")
    items, errors, counts, ok_sources = fetch_all()
    print(f"[2/4] 原始 {len(items)} 条，去重中...")
    for it in items:
        it.region = it.extra.get("region") or region_of(it.source)
    if DOMESTIC_PATTERNS:
        before = len(items)
        items = [
            it
            for it in items
            if it.region != "domestic"
            or it.source == "deals"
            or any(p.search(f"{it.title} {it.summary}") for p in DOMESTIC_PATTERNS)
        ]
        print(f"      国内源按科技/AI 词表过滤: {before} → {len(items)} 条")
    items = dedupe(items)
    items = score(items)
    print(f"[3/4] 去重后 {len(items)} 条")

    stats = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "raw": len(items),
        "sources_ok": len({i.source for i in items}),
        "errors": errors,
        "registry": REGISTRY,
        "per_source": counts,
        "ok_sources": sorted(ok_sources),
        "proxy_ok": proxy_ok,
        "by_layer": {},
        "by_region": {},
    }
    for it in items:
        stats["by_layer"][it.layer] = stats["by_layer"].get(it.layer, 0) + 1
        stats["by_region"][it.region] = stats["by_region"].get(it.region, 0) + 1
    return {"items": [i.to_dict() for i in items], "stats": stats}


if __name__ == "__main__":
    print(json.dumps(run()["stats"], ensure_ascii=False, indent=2))
