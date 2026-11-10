from __future__ import annotations

import json
import math
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import yaml

from . import extract, store
from .identity import bigrams, canonical_url, item_identity, jaccard, title_key  # noqa: F401  (对外保持原名字)
from .model import Item
from .sources import REGISTRY, build_fetchers, region_of

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
# 「报过的不再出现」的回看天数（日报层面），吸收自 AIHOT 的「最近 7 期报过的不再出现」
REPEAT_WINDOW_DAYS = 7


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
    """身份去重 + 标题近重复（同事件跨源合并）。

    身份用 `item_identity`：同一篇内容的 abs/pdf 入口、微博的 m 站与主站、
    带追踪参数的分享链接，都会落到同一个身份上。标题相似度只作为兜底，
    它解决不了"同一件事换个说法"（实测 LG 那两条只有 0.50），那要靠事件聚簇。
    """
    by_id: dict[str, Item] = {}
    for it in items:
        it.url = canonical_url(it.url)
        key = item_identity(it.url)
        if key not in by_id:
            by_id[key] = it
        else:
            by_id[key].extra.setdefault("also", []).append(it.source)

    kept: list[Item] = []
    for it in by_id.values():
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

    # 补正文与发布日期：评分与结构化都靠它。
    # 先打分是为了挑出"够格"的条目再抓，抓完用新日期重算一次（纯 CPU，很便宜）。
    extract_stats: dict = {}
    try:
        extract_stats = extract.enrich_items(items)
        if extract_stats.get("body") or extract_stats.get("date"):
            items = score(items)
        print(f"      正文: 抓 {extract_stats.get('fetch', 0)} 篇"
              f"（正文 {extract_stats.get('body', 0)} / 日期 {extract_stats.get('date', 0)}"
              f" / 失败 {extract_stats.get('failed', 0)}）")
    except Exception as e:
        print(f"      正文提取跳过: {type(e).__name__}: {e}")

    # 落库 + 跨天已报抑制。
    # 这一段以前不存在，代价是站点列表里 41–43% 是昨天的同位条目；
    # 现在每条都记 first_seen / last_seen，并把「最近 N 天已进过日报」标出来。
    store_note = ""
    try:
        store.migrate()
        counted = store.upsert_items(items, store.today_str())
        recent = store.recently_reported(REPEAT_WINDOW_DAYS)
        repeats = 0
        revised = 0
        for it in items:
            ident = item_identity(it.url)
            it.extra["new_today"] = ident in counted["new"]
            it.extra["repeat"] = ident in recent
            it.extra["revised"] = ident in counted.get("revised", set())
            repeats += 1 if it.extra["repeat"] else 0
            revised += 1 if it.extra["revised"] else 0
        store_note = f"，新增 {len(counted['new'])} 条，已报过 {repeats} 条"
        if revised:
            store_note += f"，内容更新 {revised} 条"
    except Exception as e:  # 存储层不可用不能拖垮采集
        print(f"      存储层跳过: {type(e).__name__}: {e}")
    print(f"      落库{store_note}")

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
        "extract": extract_stats,
        "new_today": sum(1 for i in items if i.extra.get("new_today")),
        "repeats": sum(1 for i in items if i.extra.get("repeat")),
    }
    for it in items:
        stats["by_layer"][it.layer] = stats["by_layer"].get(it.layer, 0) + 1
        stats["by_region"][it.region] = stats["by_region"].get(it.region, 0) + 1
    return {"items": [i.to_dict() for i in items], "stats": stats}


if __name__ == "__main__":
    print(json.dumps(run()["stats"], ensure_ascii=False, indent=2))
