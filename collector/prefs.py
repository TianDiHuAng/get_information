"""阅读反馈 → 兴趣权重 → 排序微调。

这是 AIHOT 结构上做不到的一件事：它是对所有人的公共站，读者匿名，没有个人画像。
这里是单用户，**你自己点过的就是最强的信号**——不需要推荐系统，只需要一点加成。

设计上的三个克制：
1. **只调排序，不调精选门槛**。门槛是"值不值得看"的公共标准，掺进个人偏好会让
   日报慢慢只剩你本来就爱看的东西（回音室）。这里只让"你更关心的"在同分时靠前。
2. **幅度很小**（默认 ±8%）。它是微调，不是重写；
3. **可解释**：每条都记下"因为哪些词被调了多少"，页面上能看到。

信号来源：`config/prefs.yaml` 里给每种动作定权重——点开一次比"点赞"弱，
"没用"比"没点开"强。默认值是拍出来的，但改起来不用碰代码。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Iterable

import yaml

from . import store
from .identity import item_identity

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config" / "prefs.yaml"

DEFAULT_KINDS = {"up": 1.0, "down": -1.2, "open": 0.25}

_lock = threading.Lock()
_cache: dict[str, Any] = {"mtime": 0.0, "value": {}}


def config() -> dict[str, Any]:
    try:
        mtime = CONFIG_PATH.stat().st_mtime
    except OSError:
        return {"enabled": True, "kinds": DEFAULT_KINDS, "scale": 0.08, "days": 60,
                "max_terms": 300, "min_evidence": 3}
    with _lock:
        if _cache["mtime"] == mtime:
            return _cache["value"]
        try:
            value = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            value = {}
        _cache.update(mtime=mtime, value=value)
        return value


# --------------------------------------------------------------------------- #
# 条目 → 词
# --------------------------------------------------------------------------- #

def terms_of(item: Any) -> list[str]:
    """把条目归纳成几个可加权的词：分类、标签、主体、信源。

    只用结构化抽取出来的东西，不从标题里切词——标题切词出来的权重没法解释，
    也没法让人看懂"我为什么被这条吸引了"。

    同时接受 `Item` 对象和库里查出来的 dict：反馈是在 HTTP 请求里记的，
    那里只有 dict，早期版本只认对象，导致线上永远学不到东西。
    """
    if isinstance(item, dict):
        extra = item.get("extra") or {}
        source = item.get("source") or ""
    else:
        extra = getattr(item, "extra", None) or {}
        source = getattr(item, "source", "") or ""

    st = extra.get("structure") or {}
    out: list[str] = []
    if st.get("category"):
        out.append(f"cat:{st['category']}")
    for tag in st.get("tags") or []:
        out.append(f"tag:{tag}")
    for subject in st.get("subjects") or []:
        out.append(f"sub:{subject}")
    if not out:  # 没有结构化时退回信源，至少能学到"你更爱看哪家"
        if source:
            out.append(f"src:{source}")
    return list(dict.fromkeys(out))


def terms_for_identity(identity: str) -> list[str]:
    """反馈写入时用：从库里查这条的身份、信源与结构化结果。"""
    item = store.item_by_identity(identity)
    if not item:
        return []
    st = store.latest_structure(int(item["id"]))
    return terms_of({"source": item.get("source"), "extra": {"structure": st or {}}})


# --------------------------------------------------------------------------- #
# 记录
# --------------------------------------------------------------------------- #

def record(url: str, kind: str) -> dict[str, Any]:
    """记一次反馈。`kind` 只能是配置里列出的动作之一。"""
    conf = config()
    kinds = conf.get("kinds") or DEFAULT_KINDS
    if kind not in kinds:
        return {"ok": False, "error": f"unknown kind: {kind}"}
    identity = item_identity(url or "")
    if not identity or identity == "url:":
        return {"ok": False, "error": "bad url"}
    item = store.item_by_identity(identity)
    if not item:
        return {"ok": False, "error": "unknown item"}
    terms = terms_for_identity(identity)
    store.save_feedback(identity, kind, terms)
    return {"ok": True, "identity": identity, "terms": terms}


# --------------------------------------------------------------------------- #
# 权重
# --------------------------------------------------------------------------- #

def weights(days: int | None = None) -> dict[str, float]:
    """把反馈压成 `{词: 权重}`，权重已归一化到 [-1, 1]。证据太少的词不参与。"""
    conf = config()
    if not conf.get("enabled", True):
        return {}
    kinds = conf.get("kinds") or DEFAULT_KINDS
    days = int(days or conf.get("days") or 60)
    min_evidence = int(conf.get("min_evidence") or 3)
    max_terms = int(conf.get("max_terms") or 300)

    raw: dict[str, float] = {}
    counts: dict[str, int] = {}
    for row in store.feedback_rows(days=days):
        w = float(kinds.get(row["kind"], 0.0))
        if not w:
            continue
        for term in row.get("terms") or []:
            raw[term] = raw.get(term, 0.0) + w
            counts[term] = counts.get(term, 0) + 1

    out: dict[str, float] = {}
    for term, total in raw.items():
        if counts[term] < min_evidence:
            continue
        # 用平均而不是总和：常出现的词不该因为出现次数多就压倒一切
        avg = total / counts[term]
        out[term] = max(-1.0, min(1.0, avg))
    if len(out) > max_terms:
        keep = sorted(out.items(), key=lambda kv: abs(kv[1]), reverse=True)[:max_terms]
        out = dict(keep)
    return out


def boost(item: Any, pref_weights: dict[str, float] | None = None) -> tuple[float, list[str]]:
    """返回 `(倍率, 命中的词)`。没有证据时倍率是 1.0。"""
    conf = config()
    if not conf.get("enabled", True):
        return 1.0, []
    weights_map = pref_weights if pref_weights is not None else weights()
    if not weights_map:
        return 1.0, []
    terms = terms_of(item)
    hits = [t for t in terms if t in weights_map]
    if not hits:
        return 1.0, []
    score = sum(weights_map[t] for t in hits) / max(1, len(hits))
    scale = float(conf.get("scale") or 0.08)
    return round(1.0 + scale * score, 4), hits


def apply(items: Iterable[Any], pref_weights: dict[str, float] | None = None) -> dict[str, Any]:
    """把偏好乘进排序分，并把依据写进 `extra["pref"]`（页面可解释用）。"""
    items = list(items)
    weights_map = weights() if pref_weights is None else pref_weights
    stats = {"terms": len(weights_map), "boosted": 0}
    for it in items:
        extra = getattr(it, "extra", None)
        if extra is None:
            continue
        factor, hits = boost(it, weights_map)
        if factor == 1.0:
            extra.pop("pref", None)
            continue
        base = float(extra.get("score") or 0.0)
        extra["score"] = round(base * factor, 1)
        extra["pref"] = {"factor": factor, "terms": hits}
        stats["boosted"] += 1
    return stats
