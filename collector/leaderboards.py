"""榜单快照：无公开 API 的榜单走官方数据镜像。

LMArena：官方每天把总榜同步到 HF 数据集 lmarena-ai/leaderboard-dataset
（text/latest-*.parquet，需代理）。每次采集拉一次，按发布日期去重，
和上一份快照对比给出排名升降，存 data/lmarena.json。

Artificial Analysis：官方免费 API（1000 次/天，x-api-key 鉴权，直连），
拉智能指数 Top 10 + 价格，存 data/aa.json，同样对比排名与价格变动。
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .net import session

PATH = Path(__file__).parent.parent / "data" / "lmarena.json"
DATASET_URL = (
    "https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset"
    "/resolve/main/text/latest-00000-of-00001.parquet"
)
TOP_N = 10

AA_PATH = Path(__file__).parent.parent / "data" / "aa.json"
AA_KEY_PATH = Path(__file__).parent.parent / "config" / "aa.yaml"
AA_URL = "https://artificialanalysis.ai/api/v2/language/models/free"


def _load() -> dict | None:
    if not PATH.exists():
        return None
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def fetch() -> dict | None:
    """拉取 LMArena 总榜前 10：{"date", "models": [...]}；失败返回 None。"""
    try:
        import pandas as pd

        r = session(use_proxy=True).get(DATASET_URL, timeout=90)
        r.raise_for_status()
        df = pd.read_parquet(io.BytesIO(r.content))
        df = df[df["category"] == "overall"].nsmallest(TOP_N, "rank")
        models = [
            {
                "rank": int(row["rank"]),
                "model": str(row["model_name"]),
                "org": str(row["organization"]),
                "rating": round(float(row["rating"]), 1),
                "votes": int(row["vote_count"] or 0),
            }
            for _, row in df.iterrows()
        ]
        date = str(df["leaderboard_publish_date"].iloc[0])[:10]
        return {"date": date, "models": models}
    except Exception as e:
        print(f"  [lmarena] 拉取失败: {type(e).__name__}: {e}")
        return None


def update(latest: dict | None) -> dict | None:
    """与上一份快照对比排名，写入 PATH。同一天重复拉取直接复用。"""
    prev = _load()
    if not latest:
        return prev
    if prev and prev.get("date") == latest.get("date"):
        return prev  # 官方榜单日期没变，快照仍是新的
    prev_rank = {m["model"]: m["rank"] for m in (prev or {}).get("models", [])}
    for m in latest["models"]:
        m["prev_rank"] = prev_rank.get(m["model"])
    latest["prev_date"] = (prev or {}).get("date")
    PATH.parent.mkdir(exist_ok=True)
    PATH.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
    return latest


def change_of(model: dict) -> tuple[str, str]:
    """返回 (符号, css色)：升▲ / 降▼ / 新 / 持平。"""
    p = model.get("prev_rank")
    if p is None:
        return "新", "#38bdf8"
    d = p - model["rank"]
    if d > 0:
        return f"▲{d}", "#34d399"
    if d < 0:
        return f"▼{-d}", "#f87171"
    return "—", "#6b7785"


# ---------------------------------------------------------------- Artificial Analysis


def _aa_key() -> str:
    try:
        conf = yaml.safe_load(AA_KEY_PATH.read_text(encoding="utf-8")) or {}
        return str(conf.get("api_key") or "")
    except Exception:
        return ""


def fetch_aa() -> dict | None:
    """AA 智能指数 Top 10（免费端点）：{"date", "models"}；失败返回 None。"""
    key = _aa_key()
    if not key:
        return None
    try:
        r = session().get(AA_URL, headers={"x-api-key": key}, timeout=60)
        r.raise_for_status()
        rows = r.json().get("data", [])
        rated = [
            {
                "model": str(x.get("name") or ""),
                "org": str((x.get("model_creator") or {}).get("name") or ""),
                "intelligence": x["evaluations"]["artificial_analysis_intelligence_index"],
                "price_out": (x.get("pricing") or {}).get("price_1m_output_tokens"),
            }
            for x in rows
            if x.get("evaluations", {}).get("artificial_analysis_intelligence_index")
        ]
        rated.sort(key=lambda m: m["intelligence"], reverse=True)
        models = [
            {
                "rank": i,
                "model": m["model"],
                "org": m["org"],
                "intelligence": round(float(m["intelligence"]), 1),
                "price_out": (round(float(m["price_out"]), 2) if m["price_out"] else None),
            }
            for i, m in enumerate(rated[:TOP_N], 1)
        ]
        return {"date": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d"),
                "models": models}
    except Exception as e:
        print(f"  [aa] 拉取失败: {type(e).__name__}: {e}")
        return None


def _load_aa() -> dict | None:
    if not AA_PATH.exists():
        return None
    try:
        return json.loads(AA_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def update_aa(latest: dict | None) -> dict | None:
    """与上一份快照对比排名与输出价格，写入 AA_PATH。同日重复拉取复用。"""
    if not latest:
        return _load_aa()  # 拉取失败时用缓存
    prev = _load_aa()
    if prev and prev.get("date") == latest.get("date"):
        return prev
    prev_by = {m["model"]: m for m in (prev or {}).get("models", [])}
    for m in latest["models"]:
        old = prev_by.get(m["model"])
        m["prev_rank"] = old["rank"] if old else None
        m["prev_price"] = old["price_out"] if old else None
    AA_PATH.parent.mkdir(exist_ok=True)
    AA_PATH.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
    return latest


def price_change_of(model: dict) -> str:
    """输出价格变化描述：降价 ↓ / 涨价 ↑ / 无变化空串。"""
    p, prev = model.get("price_out"), model.get("prev_price")
    if p is None or prev is None or prev == 0:
        return ""
    d = p - prev
    if d <= -0.01:
        return f"↓${abs(d):.2f}"
    if d >= 0.01:
        return f"↑${d:.2f}"
    return ""
