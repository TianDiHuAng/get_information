"""统一 LLM 调用层：回执 + 预算 + 重试 + 换模型 + 结构化输出。

为什么不直接 `requests.post`（原来 translate.py / digest.py 各写一份）：
- **同一输入重复调用是纯浪费**：翻译和评分每轮都会重跑，回执让同输入零成本复用；
- **超时之后说不清扣没扣钱**：必须有一个 `unknown` 状态，且不自动重发；
- **评分一轮几百次调用**：需要并发上限、每日预算和熔断；
- **模型会挂**：要能换一家，而不是整轮失败；
- **要算准召**：每次调用的模型、提示词版本、token 都要留痕。

吸收自 AIHOT 的 `providers/receipts.ts`，按单机场景简化：
- 逻辑键 = `task|model|prompt_version|sha256(system+user+温度+上限)`；
- 调用前先落 `pending` 行（预算按尝试次数计）；
- 拿到响应先存库再返回，崩溃后能复用；
- `unknown` 状态 30 分钟后才允许再发一次，其余交给人看。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
import yaml

from . import store

CONFIG_PATH = Path(__file__).parent.parent / "config" / "llm.yaml"

# 结果不明时，等这么久才允许再发一次（避免「其实已经计费」的重复扣费）
RELEASE_AFTER = timedelta(minutes=30)
# 一次逻辑请求最多尝试几次（含首次）
MAX_ATTEMPTS = 3
# 明确了「没被受理」的错误才立刻重试
RETRY_DELAY = (1.0, 3.0)

_local = threading.local()


def _session() -> requests.Session:
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        _local.session = s
    return s


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #

def settings() -> dict[str, Any]:
    """环境变量优先，其次 config/llm.yaml。缺失时返回空 key（调用方应当降级）。"""
    conf: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        try:
            conf = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            conf = {}
    budget = conf.get("budget") or {}
    return {
        "api_key": os.environ.get("OPENAI_API_KEY") or str(conf.get("api_key") or ""),
        "base_url": (os.environ.get("OPENAI_BASE_URL") or str(conf.get("base_url") or "")).rstrip("/")
        or "https://api.openai.com/v1",
        "model": os.environ.get("OPENAI_MODEL") or str(conf.get("model") or ""),
        # 备用模型：主模型整体不可用时切换一次（可以指向另一家）
        "backup_model": str(conf.get("backup_model") or ""),
        "backup_base_url": str(conf.get("backup_base_url") or "").rstrip("/"),
        "backup_api_key": str(conf.get("backup_api_key") or ""),
        "timeout": int(conf.get("timeout") or 90),
        "max_workers": int(conf.get("max_workers") or 4),
        "temperature": float(conf.get("temperature") or 0.1),
        # 预算：每轮/每天最多多少次调用（0 表示不限）
        "budget_per_day": int(budget.get("per_day") or 0),
        "budget_per_hour": int(budget.get("per_hour") or 0),
    }


def available() -> bool:
    s = settings()
    return bool(s["api_key"] and s["model"])


# --------------------------------------------------------------------------- #
# 预算
# --------------------------------------------------------------------------- #

def _win_hour() -> str:
    return "H:" + datetime.now().strftime("%Y-%m-%d %H")


def _win_day() -> str:
    return "D:" + store.today_str()


def _budget_take(service: str = "llm") -> bool:
    """尝试占用一次预算。返回 False 表示额度已用完，调用方必须降级。"""
    conf = settings()
    limits = {_win_hour(): conf["budget_per_hour"], _win_day(): conf["budget_per_day"]}
    with store.db() as conn:
        for window, limit in limits.items():
            if limit <= 0:
                continue
            row = conn.execute(
                "SELECT calls FROM llm_budget WHERE window = ? AND service = ?", (window, service)
            ).fetchone()
            used = row["calls"] if row else 0
            if used >= limit:
                return False
        for window in limits:
            conn.execute(
                "INSERT INTO llm_budget (window, service, calls) VALUES (?,?,1) "
                "ON CONFLICT(window, service) DO UPDATE SET calls = calls + 1",
                (window, service),
            )
    return True


def budget_usage() -> dict[str, Any]:
    with store.db() as conn:
        rows = conn.execute(
            "SELECT window, service, calls FROM llm_budget WHERE window IN (?,?)", (_win_hour(), _win_day())
        ).fetchall()
    return {f"{r['window']}/{r['service']}": r["calls"] for r in rows}


# --------------------------------------------------------------------------- #
# 回执
# --------------------------------------------------------------------------- #

def _receipt_key(task: str, model: str, prompt_version: str, payload: str) -> str:
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:24]
    return f"{task}|{model}|{prompt_version}|{digest}"


def _await_receipt(key: str, timeout: float = 20.0) -> dict[str, Any] | None:
    """同一个请求已经在飞（并发场景）：等它落地，而不是直接判失败。

    之前这里直接返回 None，结果双次评分里第二次看到 pending 就放弃了 ——
    180 条里有 147 条被判"失败"，其实只是被自己挡住了。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.5)
        rec = _receipt_get(key)
        if rec and rec["state"] in ("ok", "failed", "unknown"):
            return rec
    return _receipt_get(key)


def _receipt_get(key: str) -> dict[str, Any] | None:
    with store.db() as conn:
        row = conn.execute("SELECT * FROM llm_calls WHERE key = ?", (key,)).fetchone()
    return dict(row) if row else None


def _receipt_upsert(key: str, task: str, model: str, prompt_version: str, state: str,
                    response: str | None = None, error: str | None = None,
                    tokens: int = 0, bump_attempt: bool = False) -> None:
    """`bump_attempt` 只在真正发出请求前（写 pending）加 1，后续状态更新不再加。"""
    ts = store.now_str()
    with store.db() as conn:
        conn.execute(
            """
            INSERT INTO llm_calls (key, task, model, prompt_version, state, response, error, tokens, attempts, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(key) DO UPDATE SET
                state      = excluded.state,
                response   = coalesce(excluded.response, llm_calls.response),
                error      = excluded.error,
                tokens     = llm_calls.tokens + excluded.tokens,
                attempts   = llm_calls.attempts + excluded.attempts,
                updated_at = excluded.updated_at
            """,
            (key, task, model, prompt_version, state, response, error, tokens, 1 if bump_attempt else 0, ts, ts),
        )


def _is_stale(rec: dict[str, Any]) -> bool:
    """pending/unknown 超过了放行时间，才允许再发。"""
    try:
        updated = datetime.strptime(rec["updated_at"], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return True
    return datetime.now() - updated > RELEASE_AFTER


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #

_FENCE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.S)


def parse_json(text: str) -> dict[str, Any] | None:
    """从模型输出里抠出 JSON：容忍 ```json 围栏、前后废话、尾随逗号。"""
    if not text:
        return None
    candidates: list[str] = []
    m = _FENCE.search(text)
    if m:
        candidates.append(m.group(1))
    candidates.append(text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])
    for raw in candidates:
        for attempt in (raw, re.sub(r",\s*([}\]])", r"\1", raw)):
            try:
                obj = json.loads(attempt)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                continue
    return None


# --------------------------------------------------------------------------- #
# 调用
# --------------------------------------------------------------------------- #

class Refused(Exception):
    """模型/网关明确拒绝了这次请求（没被受理，可以换模型）。"""


def _post(model: str, system: str, user: str, temperature: float, max_tokens: int | None,
          base_url: str, api_key: str, timeout: int) -> tuple[str, int, dict[str, Any]]:
    url = f"{base_url}/chat/completions"
    body: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    if max_tokens:
        body["max_tokens"] = max_tokens
    resp = _session().post(
        url, json=body, timeout=timeout,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    if resp.status_code in (401, 403, 404):
        raise Refused(f"HTTP {resp.status_code}: {resp.text[:200]}")
    if resp.status_code == 429 or resp.status_code >= 500:
        raise ConnectionError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    resp.raise_for_status()
    data = resp.json()
    text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    tokens = int((data.get("usage") or {}).get("total_tokens") or 0)
    return text, tokens, data


def call_json(task: str, prompt_version: str, system: str, user: str, *,
              model: str | None = None, temperature: float | None = None,
              max_tokens: int | None = None, service: str = "llm",
              variant: str | None = None) -> dict[str, Any] | None:
    """带回执的结构化调用。返回解析后的 dict，或 None（不可用/预算尽/结果不明）。

    `variant` 参与回执键但不进提示词：需要"同一输入独立问两次"时（双次评分），
    两次必须用不同的 variant，否则第二次会命中第一次的回执，等于只问了一次。
    """
    conf = settings()
    if not conf["api_key"] or not conf["model"]:
        return None
    model = model or conf["model"]
    temperature = conf["temperature"] if temperature is None else temperature
    key = _receipt_key(task, model, prompt_version,
                       f"{system}\x00{user}\x00{temperature}\x00{max_tokens}\x00{variant or ''}")

    rec = _receipt_get(key)
    if rec:
        if rec["state"] == "ok" and rec["response"]:
            # 命中回执：不花钱、不等待
            return parse_json(rec["response"])
        if rec["state"] == "pending" and not _is_stale(rec):
            rec = _await_receipt(key) or rec
            if rec["state"] == "ok" and rec["response"]:
                return parse_json(rec["response"])
            if rec["state"] == "pending" and not _is_stale(rec):
                return None
        if rec["state"] == "unknown" and not _is_stale(rec):
            # 结果不明且还没到放行时间：不重发，交给下一轮或人工
            return None
        if rec["state"] == "failed" and rec["attempts"] >= MAX_ATTEMPTS:
            return None

    if not _budget_take(service):
        return None

    _receipt_upsert(key, task, model, prompt_version, "pending", bump_attempt=True)

    routes = [(model, conf["base_url"], conf["api_key"])]
    if conf["backup_model"]:
        routes.append((conf["backup_model"], conf["backup_base_url"] or conf["base_url"],
                       conf["backup_api_key"] or conf["api_key"]))

    last_error = ""
    for attempt in range(MAX_ATTEMPTS):
        for route_model, base_url, api_key in routes:
            try:
                text, tokens, _raw = _post(route_model, system, user, temperature, max_tokens,
                                           base_url, api_key, conf["timeout"])
            except Refused as e:
                last_error = f"refused: {e}"
                continue  # 换下一个路由
            except requests.exceptions.Timeout as e:
                last_error = f"timeout: {e}"
                _receipt_upsert(key, task, route_model, prompt_version, "unknown", error=last_error)
                return None  # 可能已计费：不重发
            except (requests.exceptions.ConnectionError, ConnectionError) as e:
                last_error = f"conn: {e}"
                break  # 同一家重试
            except Exception as e:  # 解析响应体等
                last_error = f"{type(e).__name__}: {e}"
                _receipt_upsert(key, task, route_model, prompt_version, "failed", error=last_error)
                break

            obj = parse_json(text)
            if obj is None:
                # 拿到了响应但不能用：存下来（不重复付钱），允许后续再试
                _receipt_upsert(key, task, route_model, prompt_version, "failed",
                                response=text[:20000], error="unparseable", tokens=tokens,
                                bump_attempt=False)
                return None
            _receipt_upsert(key, task, route_model, prompt_version, "ok",
                            response=text, tokens=tokens, bump_attempt=False)
            return obj

        if attempt < MAX_ATTEMPTS - 1:
            time.sleep(RETRY_DELAY[min(attempt, len(RETRY_DELAY) - 1)])

    _receipt_upsert(key, task, model, prompt_version, "failed", error=last_error or "unreachable")
    return None


def call_text(task: str, prompt_version: str, system: str, user: str, *,
              model: str | None = None, temperature: float | None = None,
              max_tokens: int | None = None, service: str = "llm") -> str | None:
    """纯文本调用（翻译/改写）。同样走回执与预算。"""
    conf = settings()
    if not conf["api_key"] or not conf["model"]:
        return None
    model = model or conf["model"]
    temperature = conf["temperature"] if temperature is None else temperature
    key = _receipt_key(task, model, prompt_version, f"{system}\x00{user}\x00{temperature}\x00{max_tokens}")

    rec = _receipt_get(key)
    if rec:
        if rec["state"] == "ok" and rec["response"]:
            return rec["response"]
        if rec["state"] in ("pending", "unknown") and not _is_stale(rec):
            return None
        if rec["state"] == "failed" and rec["attempts"] >= MAX_ATTEMPTS:
            return None
    if not _budget_take(service):
        return None

    _receipt_upsert(key, task, model, prompt_version, "pending", bump_attempt=True)
    try:
        text, tokens, _ = _post(model, system, user, temperature, max_tokens,
                                conf["base_url"], conf["api_key"], conf["timeout"])
    except requests.exceptions.Timeout as e:
        _receipt_upsert(key, task, model, prompt_version, "unknown", error=f"timeout: {e}")
        return None
    except Exception as e:
        _receipt_upsert(key, task, model, prompt_version, "failed", error=f"{type(e).__name__}: {e}")
        return None
    if not text.strip():
        _receipt_upsert(key, task, model, prompt_version, "failed", error="empty",
                        tokens=tokens, bump_attempt=False)
        return None
    _receipt_upsert(key, task, model, prompt_version, "ok", response=text,
                    tokens=tokens, bump_attempt=False)
    return text


def stats(day: str | None = None) -> dict[str, Any]:
    """给看板和日报用：命中率、失败率、token。"""
    day = day or store.today_str()
    with store.db() as conn:
        rows = conn.execute(
            "SELECT state, count(*) n, sum(tokens) t FROM llm_calls WHERE date(created_at) = ? GROUP BY state",
            (day,),
        ).fetchall()
        hits = conn.execute(
            "SELECT count(*) c FROM llm_calls WHERE date(created_at) = ? AND attempts = 0 AND state = 'ok'",
            (day,),
        ).fetchone()
    by_state = {r["state"]: r["n"] for r in rows}
    tokens = sum((r["t"] or 0) for r in rows)
    total = sum(by_state.values())
    return {
        "total": total,
        "by_state": by_state,
        "tokens": tokens,
        "hit": hits["c"] if hits else 0,
        "hit_rate": round((hits["c"] / total) if total and hits else 0.0, 3),
        "budget": budget_usage(),
    }
