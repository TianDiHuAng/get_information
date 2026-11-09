"""把非中文条目翻成简体中文（走本机 LLM 网关），带磁盘缓存。

为什么要做这一层：
日报/网站里一手源（smol.ai、The Batch、HF Papers、arXiv、HN）全是英文，
中文读者读起来很累。这里在采集之后、渲染之前统一翻一遍，
原文保留在 extra["title_original"] / ["summary_original"]，随时可回溯。

设计原则：
- 只翻 lang != "zh" 的条目；
- 按 hash 缓存，同一篇永不重复翻（省钱、省钱、还是省钱）；
- 模型名/公司名/产品名保留英文原文；
- 任何失败都不抛异常，条目保持英文，绝不拖垮采集。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import yaml

CACHE_PATH = Path(__file__).parent.parent / "data" / "trans_cache.json"
LLM_CONFIG_PATH = Path(__file__).parent.parent / "config" / "llm.yaml"

BATCH = 6
MAX_SUMMARY_IN = 300


def _conf() -> dict:
    conf: dict = {}
    if LLM_CONFIG_PATH.exists():
        try:
            conf = yaml.safe_load(LLM_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            conf = {}
    return {
        "api_key": os.environ.get("OPENAI_API_KEY") or str(conf.get("api_key") or ""),
        "base_url": (
            os.environ.get("OPENAI_BASE_URL") or str(conf.get("base_url") or "")
        ).rstrip("/")
        or "https://api.openai.com/v1",
        "model": os.environ.get("OPENAI_MODEL") or str(conf.get("model") or ""),
    }


def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def _key(item: dict) -> str:
    raw = f"{item.get('title', '')}||{item.get('summary', '')}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")


def _apply(item: dict, tr: dict) -> None:
    item.setdefault("extra", {})
    if not item["extra"].get("title_original"):
        item["extra"]["title_original"] = item.get("title", "")
    if not item["extra"].get("summary_original"):
        item["extra"]["summary_original"] = item.get("summary", "")
    if tr.get("title"):
        item["title"] = tr["title"]
    if tr.get("summary"):
        item["summary"] = tr["summary"]
    item["lang"] = "zh"


def _parse_array(text: str) -> list[dict]:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < start:
        raise ValueError("no JSON array in response")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("not a list")
    return data


PROMPT = """你是翻译。把下面的英文资讯条目翻成简体中文。

规则：
1. 只输出 JSON 数组，不要代码块、不要解释。
2. 每项格式：{{"i": 序号, "title": "中文标题", "summary": "中文摘要"}}
3. 模型名、公司名、产品名保留英文原文，如 Gemini 4 Carbon、Claude Opus 5.5、GPT-6、OpenAI。
4. 论文标题可译，但方法名（如 DPDM、VFlash）保留。
5. title 不超过 40 个汉字，summary 不超过 80 个汉字，只讲事实不评价。
6. 条数和 i 必须与输入一一对应，不得省略。

输入：
{payload}"""


def _chat(prompt: str, conf: dict) -> str:
    import requests

    headers = {"Content-Type": "application/json"}
    if conf["api_key"]:
        headers["Authorization"] = f"Bearer {conf['api_key']}"
    r = requests.post(
        f"{conf['base_url']}/chat/completions",
        headers=headers,
        json={
            "model": conf["model"],
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        },
        timeout=90,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def translate_items(items: list[dict], verbose: bool = True) -> dict:
    conf = _conf()
    stats = {"candidates": 0, "cached": 0, "translated": 0, "failed": 0, "skipped": ""}
    if not conf["model"]:
        stats["skipped"] = "no model configured"
        return stats

    cache = _load_cache()
    todo: list[dict] = []
    for it in items:
        if it.get("lang") == "zh":
            continue
        title, summary = it.get("title", ""), it.get("summary", "") or ""
        if _has_cjk(title) and (not summary or _has_cjk(summary)):
            continue
        stats["candidates"] += 1
        k = _key(it)
        it.setdefault("extra", {})["_tkey"] = k
        if k in cache:
            _apply(it, cache[k])
            stats["cached"] += 1
        else:
            todo.append(it)

    if verbose:
        print(f"  [translate] 待翻 {len(todo)} 条，命中缓存 {stats['cached']} 条")

    for i in range(0, len(todo), BATCH):
        chunk = todo[i : i + BATCH]
        payload = json.dumps(
            [
                {"i": n + 1, "title": c.get("title", ""), "summary": (c.get("summary") or "")[:MAX_SUMMARY_IN]}
                for n, c in enumerate(chunk)
            ],
            ensure_ascii=False,
        )
        try:
            out = _chat(PROMPT.format(payload=payload), conf)
            rows = _parse_array(out)
            by_i = {int(r.get("i", 0)): r for r in rows if isinstance(r, dict)}
            for n, c in enumerate(chunk, 1):
                row = by_i.get(n)
                if not row or not str(row.get("title") or "").strip():
                    stats["failed"] += 1
                    continue
                tr = {
                    "title": str(row.get("title")).strip()[:80],
                    "summary": str(row.get("summary") or "").strip()[:160],
                }
                cache[c["extra"]["_tkey"]] = tr
                _apply(c, tr)
                stats["translated"] += 1
        except Exception as e:
            stats["failed"] += len(chunk)
            if verbose:
                print(f"  [translate] 批次 {i // BATCH + 1} 失败: {type(e).__name__}: {e}")

    for it in items:
        (it.get("extra") or {}).pop("_tkey", None)

    _save_cache(cache)
    if verbose:
        print(
            f"  [translate] 完成：翻译 {stats['translated']} 条 / 缓存 {stats['cached']} 条"
            f" / 失败 {stats['failed']} 条"
        )
    return stats


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = json.loads((Path(__file__).parent.parent / "data" / "items.json").read_text(encoding="utf-8"))
    s = translate_items(p["items"][:8])
    print(s)
    for it in p["items"][:8]:
        print(f'- {it["title"]} | {(it.get("summary") or "")[:60]}')
