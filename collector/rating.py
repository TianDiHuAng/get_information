"""注意力评分：预筛 → 五轴 × 双次 → 门槛 → 降级。

吸收自 AIHOT 的 `editorial/analyze.ts` + `industry/prompts/selection-score.md`，
并做两处针对本项目的改动：

1. **模型只输出五轴，不算总分**。AIHOT 让模型自己按权重表算 `attentionScore`，
   好处是"模型知道权重"，坏处是算术错误会直接毁掉一条结果（11 分算成 12），
   而且调权重必须重写提示词、历史回执全部失效。这里把权重留在 `config/scoring.yaml`，
   代码合成 → 权重可扫、可评测、改口味不用碰提示词。
2. **多要一个 `reason`**。这是单用户场景和公共站的区别：你不只需要"这条高不高"，
   还需要知道"为什么高"，否则无法判断是模型读懂了还是被标题骗了。

降级策略（很重要）：LLM 不可用、预算耗尽、结果不明 —— 一律保留
`pipeline.score()` 的老分，只把 `attention` 标记为不可用。**任何情况下都不阻断出刊。**
"""

from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable

import yaml

from . import llm, store
from .identity import item_identity

AXES = ("sig", "nov", "cred", "reson", "act")
ROOT = Path(__file__).parent.parent
SCORING_PATH = ROOT / "config" / "scoring.yaml"
PROMPT_DIR = ROOT / "config" / "prompts"
SITE_NAME = "Z-Bit"

_config_lock = threading.Lock()
_config_cache: dict[str, Any] = {"mtime": 0.0, "value": {}}
_prompt_cache: dict[str, tuple[str, str]] = {}


# --------------------------------------------------------------------------- #
# 配置与提示词
# --------------------------------------------------------------------------- #

def config() -> dict[str, Any]:
    """读 config/scoring.yaml，按 mtime 缓存（改完立刻生效，不用重启）。"""
    try:
        mtime = SCORING_PATH.stat().st_mtime
    except OSError:
        return {}
    with _config_lock:
        if _config_cache["mtime"] == mtime:
            return _config_cache["value"]
        try:
            value = yaml.safe_load(SCORING_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            value = {}
        _config_cache.update(mtime=mtime, value=value)
        return value


def prompt(name: str) -> tuple[str, str]:
    """返回 `(正文, 版本号)`。版本号是内容哈希：改了提示词，旧回执自动失效。"""
    if name in _prompt_cache:
        return _prompt_cache[name]
    # 行业包优先：industry/<pack>/prompts/<name>.md 存在就用它。
    # 之前只读 config/prompts/，导致 industry/aidd/prompts/ 里那三份
    # （prefilter / attention-score / structure）从来没生效过 ——
    # AIDD 一直在用 AI 行业的评分口径。
    import os

    path = None
    pack = (os.environ.get("RADAR_PACK") or "").strip()
    if pack:
        cand = (Path(__file__).parent.parent / "industry" / pack / "prompts"
                / f"{name}.md")
        if cand.is_file():
            path = cand
    if path is None:
        path = PROMPT_DIR / f"{name}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    text = text.replace("{{site_name}}", SITE_NAME)
    version = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    _prompt_cache[name] = (text, version)
    return text, version


def _render(template: str, **fields: Any) -> str:
    for key, value in fields.items():
        template = template.replace("{{" + key + "}}", str(value))
    return template


# --------------------------------------------------------------------------- #
# 打分公式
# --------------------------------------------------------------------------- #

def weighted_score(axes: dict[str, int], itype: str, weights: dict[str, dict[str, int]]) -> int:
    """五轴 × 类型权重 → 0–100。权重行和若不为 10 会归一，避免配置写错就爆分。"""
    table = weights.get(itype) or weights.get("product_launch") or {}
    if not table:
        return 0
    total = sum(table.get(axis, 0) * int(axes.get(axis, 0)) for axis in AXES)
    spread = sum(table.get(axis, 0) for axis in AXES) or 1
    return int(round(total * 10 / spread))


def threshold_for(item: Any, conf: dict[str, Any]) -> int:
    """信源 → 门槛。单个信源的覆盖优先，其次按分层。"""
    thresholds = conf.get("thresholds") or {}
    per_source = conf.get("sources") or {}
    source = getattr(item, "source", "") or ""
    if source in per_source:
        return int(per_source[source])
    return int(thresholds.get(getattr(item, "layer", "broad") or "broad", thresholds.get("broad", 70)))


# --------------------------------------------------------------------------- #
# 材料
# --------------------------------------------------------------------------- #

def material(item: Any, conf: dict[str, Any]) -> tuple[str, bool]:
    """拼出喂给模型的材料，返回 `(文本, 是否只有标题)`。"""
    limit = int(conf.get("max_chars") or 3000)
    title = (getattr(item, "title", "") or "").strip()
    summary = (getattr(item, "summary", "") or "").strip()
    body = (getattr(item, "extra", {}) or {}).get("body") or ""
    parts = [f"标题：{title}"]
    if summary:
        parts.append(f"摘要：{summary}")
    if body:
        parts.append(f"正文片段：{body}")
    if getattr(item, "published", ""):
        parts.append(f"发布时间：{item.published}")
    text = "\n".join(parts)
    title_only = not summary and not body
    return text[:limit], title_only


# --------------------------------------------------------------------------- #
# 单条判定
# --------------------------------------------------------------------------- #

def prefilter(item: Any, model: str | None = None) -> str:
    """PASS / BLOCK / UNKNOWN。任何失败都返回 UNKNOWN（保留，不误杀）。

    `model` 只给评测用：同一批样本换不同模型跑，才能比较"哪个模型判得准"。
    """
    conf = config()
    if not conf.get("prefilter", True):
        return "PASS"
    system, version = prompt("prefilter")
    if not system:
        return "PASS"
    text, _ = material(item, conf)
    obj = llm.call_json("prefilter", version, system, text, max_tokens=200, model=model)
    if not obj:
        return "UNKNOWN"
    label = str(obj.get("label") or "").upper()
    return label if label in ("PASS", "BLOCK", "UNKNOWN") else "UNKNOWN"


def score_once(item: Any, call_no: int, model: str | None = None) -> dict[str, Any] | None:
    """一次独立打分。返回 `{axes, itype, reason, score}` 或 None。"""
    conf = config()
    weights = conf.get("weights") or {}
    system, version = prompt("attention-score")
    if not system:
        return None
    text, title_only = material(item, conf)
    system = _render(
        system,
        title_only_cred_cap=int(conf.get("title_only_cred_cap") or 4),
        call_no=call_no,
    )
    user = text
    if title_only:
        user += "\n\n（这条材料只有标题，没有摘要和正文。）"
    obj = llm.call_json("attention-score", version, system, user, max_tokens=300,
                        model=model, variant=f"call{call_no}")
    if not obj:
        return None
    itype = str(obj.get("itype") or "").strip()
    if itype not in weights:
        itype = "product_launch"
    axes: dict[str, int] = {}
    for axis in AXES:
        try:
            value = int(obj.get(axis))
        except (TypeError, ValueError):
            return None
        axes[axis] = max(0, min(10, value))
    if title_only:
        axes["cred"] = min(axes["cred"], int(conf.get("title_only_cred_cap") or 4))
    return {
        "axes": axes,
        "itype": itype,
        "reason": str(obj.get("reason") or "").strip()[:60],
        "score": weighted_score(axes, itype, weights),
        "prompt_version": version,
    }


# --------------------------------------------------------------------------- #
# 批量
# --------------------------------------------------------------------------- #

def rate_items(items: Iterable[Any], *, ids: dict[str, int] | None = None,
               day: str | None = None) -> dict[str, Any]:
    """给每条 item 打上 `extra["attention"]` 与新的 `extra["score"]`。

    返回统计，供日志和看板使用。LLM 不可用时立刻返回 `{"skipped": ...}`，
    调用方的老分不受影响。
    """
    conf = config()
    if not conf.get("enabled", True):
        return {"skipped": "disabled"}
    if not llm.available():
        return {"skipped": "no-llm"}

    items = list(items)
    if not items:
        return {"skipped": "empty"}
    if isinstance(items[0], dict):
        # 曾经踩过的坑：pipeline 早就把 items 转成 dict 了，这里 getattr 拿不到 extra，
        # 于是整轮"评分了 0 条"却不报错。宁可炸，也不要静默空转。
        raise TypeError("rating 需要 Item 对象；收到 dict（是不是提前 to_dict 了？）")
    day = day or store.today_str()
    calls = int(conf.get("score_calls") or 2)
    workers = max(1, int(conf.get("max_workers") or 4))
    max_items = int(conf.get("max_items") or 0)
    if max_items:
        items.sort(key=lambda i: (getattr(i, "extra", {}) or {}).get("score") or 0, reverse=True)
        items = items[:max_items]

    if ids is None:
        ids = store.ids_for([item_identity(getattr(i, "url", "")) for i in items])

    # 第一段：预筛（并发）
    labels: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(prefilter, it): idx for idx, it in enumerate(items)}
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                labels[idx] = fut.result()
            except Exception:
                labels[idx] = "UNKNOWN"

    # 第二段：双次评分（并发，只跑通过预筛的）
    scored: dict[int, list[dict[str, Any]]] = {}
    targets = [idx for idx in range(len(items)) if labels.get(idx) != "BLOCK"]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for idx in targets:
            for call_no in range(1, calls + 1):
                futures[pool.submit(score_once, items[idx], call_no)] = (idx, call_no)
        for fut in as_completed(futures):
            idx, call_no = futures[fut]
            try:
                result = fut.result()
            except Exception:
                result = None
            if result:
                result["call_no"] = call_no
                scored.setdefault(idx, []).append(result)

    # 第三段：合成、门槛、留痕
    score_rows: list[dict[str, Any]] = []
    stats = {"scored": 0, "selected": 0, "blocked": 0, "unknown": 0, "failed": 0}
    blend = conf.get("blend") or {"attention": 0.8, "legacy": 0.2}
    w_att = float(blend.get("attention", 0.8))
    w_leg = float(blend.get("legacy", 0.2))
    understand_floor = int(conf.get("understand_floor") or 50)

    for idx, it in enumerate(items):
        label = labels.get(idx, "UNKNOWN")
        extra = getattr(it, "extra", None)
        if extra is None:
            continue
        legacy = extra.get("score") or 0.0
        extra["legacy_score"] = legacy
        runs = scored.get(idx) or []

        if label == "BLOCK":
            stats["blocked"] += 1
            extra["attention"] = {"label": "BLOCK", "available": False, "score": None}
            extra["score"] = round(float(legacy) * 0.5, 1)  # 降权但保留，避免预筛误杀
            continue

        if len(runs) < calls:
            stats["failed"] += 1
            extra["attention"] = {"label": label, "available": False, "score": None,
                                  "got": len(runs), "want": calls}
            extra["score"] = round(float(legacy), 1)
            continue

        avg = int(sum(r["score"] for r in runs) // len(runs))
        axis_mean = {axis: round(sum(r["axes"][axis] for r in runs) / len(runs), 1) for axis in AXES}
        itype = runs[0]["itype"]
        threshold = threshold_for(it, conf)
        selected = avg >= threshold
        extra["attention"] = {
            "label": label,
            "available": True,
            "score": avg,
            "sum": sum(r["score"] for r in runs),
            "axes": axis_mean,
            "itype": itype,
            "reason": runs[0]["reason"],
            "threshold": threshold,
            "selected": selected,
            "calls": len(runs),
            "understand": avg >= understand_floor,
            "prompt_version": runs[0].get("prompt_version"),
        }
        # 排序分：判断为主，老分（时效/热度/层权重）做轻微修正
        extra["score"] = round(w_att * avg + w_leg * float(legacy), 1)
        stats["scored"] += 1
        if selected:
            stats["selected"] += 1

        item_id = ids.get(item_identity(getattr(it, "url", "")))
        if item_id:
            for r in runs:
                score_rows.append({
                    "item_id": item_id, "model": None, "prompt_version": r.get("prompt_version"),
                    "call_no": r["call_no"], "scope": label, "itype": r["itype"],
                    "axes": r["axes"], "score": r["score"], "reason": r["reason"],
                })

    if score_rows:
        store.save_scores(score_rows, day)

    stats.update({
        "calls": stats["scored"] * calls,
        "llm": llm.stats(day),
        "config_version": int(SCORING_PATH.stat().st_mtime) if SCORING_PATH.exists() else 0,
    })
    return stats


def describe(item: Any) -> str:
    """把一条的评分写成一行，给日志/看板看。"""
    att = (getattr(item, "extra", {}) or {}).get("attention") or {}
    if not att.get("available"):
        return f"[{att.get('label', '?')}] 未评分"
    axes = att.get("axes") or {}
    axis_text = " ".join(f"{a}{axes.get(a, 0)}" for a in AXES)
    return (f"[{att.get('score')}/{att.get('threshold')} {att.get('itype')}] "
            f"{axis_text} — {att.get('reason') or ''}")


if __name__ == "__main__":  # 便于手工验证：python -m collector.rating
    import sys
    from .model import Item
    sample = Item(source="thebatch", title="OpenAI 发布 GPT-6，支持 100 万 token 上下文",
                  url="https://example.com/x", layer="primary",
                  summary="官方宣布新模型在长上下文与工具调用上有明显提升，API 价格下降 40%。")
    result = rate_items([sample], ids={})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(describe(sample))
