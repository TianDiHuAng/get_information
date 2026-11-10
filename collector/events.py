"""事件聚簇：把「同一件事的多篇报道」收成一个事件，再按事件算热度。

为什么必须做（实测动机）：
`digest-2026-11-10.md` 里 LG 的 K-EXAONE 2.5 出现了两次 —— 汽车之家与 Unite.AI 两条，
标题 bigram 相似度只有 **0.50**，低于合并线 0.72。**光比标题永远解决不了这个问题。**

吸收自 AIHOT 的 `events/{recall,relate,group,hot}.ts`，但按单机成本做了三处改动：

1. **粗排挡在模型前面**：用 IDF 加权的 token 重合先算分，只有够像的对才送进模型
   （AIHOT 是每条都召回候选再批量判），一轮模型调用从数百次降到几十次。
2. **判定结果落库**：`event_pairs` 让同一对永不重复付费，也让"人工改过的判断"有地方存。
3. **复核用独立提示词**：回执是按「提示词 + 输入」做键的，同一条重跑会直接命中回执、
   等于没复核。所以复核是另一份提示词（`group-review.md`），只给两句话的概括，
   让第二次判断真的独立。

降级：没有 LLM 时退回纯相似度合并（≥ `fallback_similarity`），行为不差于改造前。
"""

from __future__ import annotations

import math
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from . import llm, store
from .identity import bigrams, item_identity, title_similar

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config" / "events.yaml"
PROMPT_DIR = ROOT / "config" / "prompts"

RELATIONS = ("SAME_OCCURRENCE", "SAME_STORY", "UNRELATED", "ROUNDUP")
# 代表稿优先级：官方一手 > 榜单/广谱 > 搜索/社媒
LAYER_RANK = {"primary": 3, "rank": 2, "broad": 2, "search": 1, "social": 1}

_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{1,}")
_VERSION = re.compile(r"\d+(?:\.\d+)+")
_STOP = {
    "the", "and", "for", "with", "from", "this", "that", "new", "api", "via", "are",
    "was", "has", "its", "you", "not", "but", "all", "can", "our", "now", "out",
    "get", "use", "how", "why", "what", "when", "who", "will", "more", "than",
}

_config_lock = threading.Lock()
_config_cache: dict[str, Any] = {"mtime": 0.0, "value": {}}
_prompt_cache: dict[str, tuple[str, str]] = {}


# --------------------------------------------------------------------------- #
# 配置与提示词
# --------------------------------------------------------------------------- #

def config() -> dict[str, Any]:
    try:
        mtime = CONFIG_PATH.stat().st_mtime
    except OSError:
        return {}
    with _config_lock:
        if _config_cache["mtime"] == mtime:
            return _config_cache["value"]
        try:
            value = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            value = {}
        _config_cache.update(mtime=mtime, value=value)
        return value


def prompt(name: str) -> tuple[str, str]:
    """返回 `(正文, 版本号)`；版本号是内容哈希，改了提示词旧回执自动失效。"""
    if name in _prompt_cache:
        return _prompt_cache[name]
    try:
        text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    except OSError:
        text = ""
    import hashlib
    version = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    _prompt_cache[name] = (text, version)
    return text, version


# --------------------------------------------------------------------------- #
# 粗排：IDF 加权的 token 重合（不花模型钱）
# --------------------------------------------------------------------------- #

def tokens(title: str, summary: str = "") -> set[str]:
    """实体型 token：拉丁词、型号版本号、中文二元组。

    型号要能跨写法对齐：`K-EXAONE2.5` 与 `K-EXAONE 2.5` 都产出
    `{"k-exaone", "2.5"}` —— 前者靠"去掉尾部数字再收一份"，后者靠版本号正则。
    否则同一款模型的两种写法永远算不出相似度。
    """
    text = f"{title or ''} {summary or ''}"
    out: set[str] = set()
    for m in _LATIN.finditer(text):
        raw = m.group(0).lower()
        if len(raw) >= 2 and raw not in _STOP:
            out.add(raw)
        stripped = re.sub(r"\d+$", "", raw)
        if len(stripped) >= 2 and stripped not in _STOP:
            out.add(stripped)
    out.update(_VERSION.findall(text))
    out |= {g for g in bigrams(title or "")}
    out.discard("")
    return out


def build_idf(sets: Iterable[set[str]]) -> dict[str, float]:
    docs = [s for s in sets if s]
    total = len(docs) or 1
    df: dict[str, int] = {}
    for s in docs:
        for t in s:
            df[t] = df.get(t, 0) + 1
    return {t: math.log(1 + total / (1 + n)) for t, n in df.items()}


def pair_score(a: set[str], b: set[str], idf: dict[str, float]) -> float:
    """IDF 加权 Jaccard：稀有的共有词（K-EXAONE、2.5）权重高，套话权重低。"""
    common = a & b
    if not common:
        return 0.0
    default = 1.0
    num = sum(idf.get(t, default) for t in common)
    den = sum(idf.get(t, default) for t in (a | b))
    return num / den if den else 0.0


# --------------------------------------------------------------------------- #
# 一条资料的可判定视图
# --------------------------------------------------------------------------- #

def _view_item(it: Any) -> dict[str, Any]:
    return {
        "identity": item_identity(getattr(it, "url", "") or ""),
        "title": getattr(it, "title", "") or "",
        "summary": getattr(it, "summary", "") or "",
        "source": getattr(it, "source", "") or "",
        "layer": getattr(it, "layer", "broad") or "broad",
        "published": getattr(it, "published", "") or "",
    }


def _material(a: dict[str, Any], b: dict[str, Any]) -> str:
    def block(tag: str, v: dict[str, Any]) -> str:
        parts = [f"【{tag}】", f"标题：{v['title']}"]
        if v["summary"]:
            parts.append(f"摘要：{v['summary'][:400]}")
        if v["published"]:
            parts.append(f"发布时间：{v['published']}")
        return "\n".join(parts)

    return f"{block('A', a)}\n\n{block('B', b)}"


# --------------------------------------------------------------------------- #
# 判定
# --------------------------------------------------------------------------- #

def _review(a: dict[str, Any], b: dict[str, Any], first: dict[str, Any]) -> dict[str, Any]:
    """独立复核。用另一份提示词，只给两句话的概括，避免被原文措辞带跑。"""
    system, version = prompt("group-review")
    if not system:
        return first
    user = (
        f"A：{first.get('a_gist') or a['title']}\n"
        f"B：{first.get('b_gist') or b['title']}\n"
        f"第一位编辑的判断：{first.get('relation')}（置信度 {first.get('confidence')}）\n"
        f"他的说明：{first.get('difference') or '无'}"
    )
    obj = llm.call_json("group-review", version, system, user, max_tokens=200)
    if not obj:
        return first
    relation = str(obj.get("relation") or "").upper()
    if relation not in RELATIONS:
        relation = first.get("relation") or "UNRELATED"
    try:
        confidence = float(obj.get("confidence"))
    except (TypeError, ValueError):
        confidence = first.get("confidence") or 0.0
    agree = bool(obj.get("agree"))
    if not agree and relation == (first.get("relation") or ""):
        # 复核者不同意，却也没给出不同的判断：按"不确定"处理，宁可不合
        relation = "UNRELATED"
    return {
        "relation": relation,
        "confidence": max(0.0, min(1.0, confidence)),
        "difference": obj.get("why") or first.get("difference") or "",
        "reviewed": True,
    }


def judge(a: dict[str, Any], b: dict[str, Any], conf: dict[str, Any]) -> dict[str, Any] | None:
    """判一对。返回 `{relation, confidence, difference, prompt_version}` 或 None。"""
    system, version = prompt("group-pair")
    if not system:
        return None
    obj = llm.call_json("group-pair", version, system, _material(a, b), max_tokens=400)
    if not obj:
        return None
    relation = str(obj.get("relation") or "").upper()
    if relation not in RELATIONS:
        relation = "UNRELATED"
    try:
        confidence = max(0.0, min(1.0, float(obj.get("confidence"))))
    except (TypeError, ValueError):
        confidence = 0.0
    result = {
        "relation": relation,
        "confidence": confidence,
        "difference": str(obj.get("difference") or "")[:200],
        # 注意：这两个字段名不能叫 a / b —— 会和"身份键"撞名，写进缓存表就再也查不到了
        "a_gist": str(obj.get("a") or "")[:200],
        "b_gist": str(obj.get("b") or "")[:200],
        "prompt_version": version,
    }
    merge = set(conf.get("merge_relations") or ["SAME_OCCURRENCE", "SAME_STORY"])
    if relation in merge and confidence < float(conf.get("review_confidence") or 0.85):
        reviewed = _review(a, b, result)
        result.update(reviewed)
    return result


# --------------------------------------------------------------------------- #
# 并查集
# --------------------------------------------------------------------------- #

class _DSU:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


# --------------------------------------------------------------------------- #
# 时间与热度
# --------------------------------------------------------------------------- #

def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def heat_of(members: list[dict[str, Any]], conf: dict[str, Any]) -> tuple[float, int]:
    """按独立参与方算热度：Σ 0.5^(Δt/半衰期)，每个参与方只取最新一次。"""
    hcfg = conf.get("heat") or {}
    window = float(hcfg.get("window_hours") or 48)
    half = float(hcfg.get("half_life_hours") or 24)
    groups = hcfg.get("participant_groups") or {}
    now = datetime.now(timezone.utc)

    def participant(source: str) -> str:
        for name, sources in groups.items():
            if source in (sources or []):
                return f"group:{name}"
        return f"src:{source}"

    latest: dict[str, datetime] = {}
    for m in members:
        dt = _parse_time(m.get("published") or "") or now
        if (now - dt).total_seconds() / 3600 > window:
            continue
        key = participant(m.get("source") or "")
        if key not in latest or dt > latest[key]:
            latest[key] = dt

    total = 0.0
    for dt in latest.values():
        age_h = max(0.0, (now - dt).total_seconds() / 3600)
        total += 0.5 ** (age_h / half)
    return round(total, 3), len(latest)


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

def _representative(members: list[dict[str, Any]], today_ids: dict[str, int]) -> dict[str, Any]:
    """代表稿：官方一手 > 有摘要 > 分数高 > 发得早；同分时优先今天这条。"""
    def rank(m: dict[str, Any]) -> tuple:
        published = _parse_time(m.get("published") or "")
        ts = published.timestamp() if published else 0.0
        return (
            1 if m["identity"] in today_ids else 0,
            LAYER_RANK.get(m.get("layer") or "", 0),
            1 if (m.get("summary") or "").strip() else 0,
            float(m.get("score") or 0),
            -ts,
        )

    return max(members, key=rank)


def cluster_items(items: Iterable[Any], *, day: str | None = None,
                  ids: dict[str, int] | None = None) -> dict[str, Any]:
    """给每条 item 打上事件信息，并写入 events / event_items / event_heat。"""
    conf = config()
    if not conf.get("enabled", True):
        return {"skipped": "disabled"}

    items = list(items)
    if not items:
        return {"skipped": "empty"}
    if isinstance(items[0], dict):
        raise TypeError("events 需要 Item 对象；收到 dict（是不是提前 to_dict 了？）")
    day = day or store.today_str()
    views = [_view_item(it) for it in items]
    by_identity: dict[str, Any] = {v["identity"]: it for v, it in zip(views, items)}
    today_ids = ids if ids is not None else store.ids_for([v["identity"] for v in views])
    item_ids = {v["identity"]: today_ids.get(v["identity"]) for v in views}

    pool = store.recent_items(int(conf.get("lookback_days") or 14))
    pool_views = [{
        "identity": p["identity"], "title": p.get("title") or "", "summary": p.get("summary") or "",
        "source": p.get("source") or "", "layer": p.get("layer") or "broad",
        "published": p.get("published") or "", "score": None, "item_id": p.get("id"),
    } for p in pool]

    tok_cache: dict[str, set[str]] = {}
    for v in views + pool_views:
        if v["identity"] not in tok_cache:
            tok_cache[v["identity"]] = tokens(v["title"], v["summary"])
    idf = build_idf(tok_cache.values())

    # 1) 召回：每条今天的新资料，在池子里找最像的若干条
    floor = float(conf.get("candidate_floor") or 0.2)
    per_item = int(conf.get("max_candidates_per_item") or 6)
    proposals: dict[tuple[str, str], float] = {}
    for v in views:
        own = tok_cache[v["identity"]]
        scored = []
        for pv in pool_views:
            if pv["identity"] == v["identity"]:
                continue
            s = pair_score(own, tok_cache[pv["identity"]], idf)
            if s >= floor:
                scored.append((s, pv["identity"]))
        scored.sort(reverse=True)
        for s, other in scored[:per_item]:
            key = tuple(sorted((v["identity"], other)))
            proposals[key] = max(proposals.get(key, 0.0), s)

    # 2) 控成本：只判最像的若干对
    max_pairs = int(conf.get("max_pairs") or 150)
    ordered = sorted(proposals.items(), key=lambda kv: kv[1], reverse=True)[:max_pairs]
    wanted = [k for k, _ in ordered]

    view_by_id = {v["identity"]: v for v in views + pool_views}
    cached = store.load_pairs(wanted)
    missing = [k for k in wanted if k not in cached]
    judged: dict[tuple[str, str], dict[str, Any]] = dict(cached)

    if missing and llm.available():
        workers = max(1, int(conf.get("max_workers") or 4))
        fresh: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=workers) as pool_ex:
            futures = {
                pool_ex.submit(judge, view_by_id[a], view_by_id[b], conf): (a, b)
                for a, b in missing
            }
            for fut in as_completed(futures):
                a, b = futures[fut]
                try:
                    result = fut.result()
                except Exception:
                    result = None
                if not result:
                    continue
                judged[(a, b)] = result
                fresh.append({
                    "a": a, "b": b,
                    "relation": result["relation"],
                    "confidence": result.get("confidence"),
                    "prompt_version": result.get("prompt_version"),
                })
        store.save_pairs(fresh)

    # 3) 合并：只有 merge_relations 才连边；没有 LLM 时退回纯相似度
    merge = set(conf.get("merge_relations") or ["SAME_OCCURRENCE", "SAME_STORY"])
    fallback = float(conf.get("fallback_similarity") or 0.72)
    dsu = _DSU()
    for ident in list(view_by_id):
        dsu.find(ident)

    merged_pairs = 0
    for (a, b), score in ordered:
        decision = judged.get((a, b))
        if decision:
            if decision["relation"] in merge:
                dsu.union(a, b)
                merged_pairs += 1
        elif title_similar(view_by_id[a]["title"], view_by_id[b]["title"]) >= fallback:
            dsu.union(a, b)  # 无模型时的保守兜底
            merged_pairs += 1

    clusters: dict[str, list[str]] = {}
    for ident in view_by_id:
        clusters.setdefault(dsu.find(ident), []).append(ident)

    # 4) 先算出所有事件，再一次性落库（逐个开事务会把一轮拖到几十秒）
    stats = {"events": 0, "merged": 0, "pairs_judged": len(judged), "pairs_new": len(missing),
             "clusters": 0, "ranked": 0, "llm": llm.available()}
    min_participants = int((conf.get("heat") or {}).get("min_participants") or 2)

    event_rows: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for _root, members in clusters.items():
        member_views = [view_by_id[i] for i in members]
        todays = [v for v in member_views if v["identity"] in by_identity]
        if not todays:
            continue

        if len(member_views) == 1:
            # 单篇不是"事件"：只标注，不留事件壳（215 条里 199 条属于这种）
            for v in todays:
                by_identity[v["identity"]].extra.update({
                    "event_id": None, "event_key": v["identity"], "event_size": 1,
                    "event_sources": 1, "event_heat": 0.0, "event_trend": None,
                    "event_representative": True,
                })
            continue

        ordered_members = sorted(
            (v for v in member_views if v.get("published")), key=lambda v: v.get("published") or ""
        ) or sorted(member_views, key=lambda v: v.get("published") or "")
        rep = _representative(member_views, today_ids)
        heat, participants = heat_of(ordered_members, conf)
        rows = []
        for v in member_views:
            iid = v.get("item_id") or today_ids.get(v["identity"])
            if iid:
                rows.append((iid, "SAME_OCCURRENCE", 1.0))
        if not rows:
            continue
        event_rows.append({
            "key": rep["identity"],
            "title": rep["title"],
            "first_at": ordered_members[0].get("published") or "",
            "last_at": ordered_members[-1].get("published") or "",
            "members": rows,
        })
        pending.append({
            "rep": rep, "members": member_views, "todays": todays,
            "heat": heat, "participants": participants,
        })
        stats["clusters"] += 1
        stats["merged"] += len(member_views) - 1
        if participants >= min_participants:
            stats["ranked"] += 1

    ids_by_key = store.upsert_events_bulk(event_rows)
    heat_rows: list[tuple[int, float, int]] = []
    for item in pending:
        event_id = ids_by_key.get(item["rep"]["identity"])
        if event_id is None:
            continue
        stats["events"] += 1
        heat_rows.append((event_id, item["heat"], item["participants"]))
        prev = store.previous_heat(event_id, hours=6)
        trend = round(item["heat"] / prev - 1, 3) if prev and prev > 0 else None
        for v in item["todays"]:
            by_identity[v["identity"]].extra.update({
                "event_id": event_id,
                "event_key": item["rep"]["identity"],
                "event_size": len(item["members"]),
                "event_sources": item["participants"],
                "event_heat": item["heat"],
                "event_trend": trend,
                "event_representative": v["identity"] == item["rep"]["identity"],
                "event_rep_title": item["rep"]["title"],
            })
    store.save_heat_many(heat_rows)
    return stats


def representative_first(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """日报用：同一事件只留代表稿，其余保留在原列表里给网站。"""
    out: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for it in items:
        extra = it.get("extra") or {}
        event_id = extra.get("event_id")
        if event_id is None:
            out.append(it)
            continue
        if extra.get("event_representative") is False:
            continue
        if event_id in seen:
            continue
        seen.add(event_id)
        out.append(it)
    return out
