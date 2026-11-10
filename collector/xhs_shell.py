"""包装层：为小红书深度稿生成开场/标题/封面/结尾（模型只写这几块）。"""

from __future__ import annotations

import json
import re

PACK_PROMPT = """{persona}

你要把一篇论文的要点写成小红书笔记的「外壳」。读者是{audience}。

论文：{title}
核心问题：{problem}
做法：{method}
关键结果：{findings}
局限：{limits}
意义：{meaning}

请输出 JSON：
{{
  "titles": ["3 个标题，每个 ≤{max_title} 字，要具体，带方法名或结论性判断，禁用空词"],
  "hook": "开头 2 行，第一人称口语，说清今天为什么想聊这篇（不要复述摘要）",
  "problem_head": "一个小标题，≤10 字，点出问题（不要用冒号）",
  "cover": ["封面 3 行，每行 ≤{cover_len} 字，第一行具体、第三行是判断"],
  "tags": ["6~10 个标签，从这些里挑：{pool}"],
  "ending": "最后两行：一句判断 + 一个具体的互动提问"
}}

事实纪律：只能使用上面给出的信息，不要新增数字或结论。"""


def _json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e < s:
        raise ValueError("no json")
    return json.loads(text[s : e + 1], strict=False)


def build_shell(chat, llm: dict, cfg: dict, title: str, facts: dict) -> dict | None:
    findings = "；".join(facts.get("findings") or []) or "（未提取到）"
    prompt = PACK_PROMPT.format(
        persona=cfg["persona"].strip(),
        audience=cfg["audience"],
        title=title,
        problem=facts.get("problem", ""),
        method=facts.get("method", ""),
        findings=findings,
        limits=facts.get("limits", ""),
        meaning=facts.get("meaning", ""),
        max_title=cfg["title_rules"]["max_chars"],
        cover_len=cfg["cover"]["max_chars_per_line"],
        pool="、".join(cfg["tags"].get("pool") or []),
    )
    try:
        return _json(chat(prompt, llm))
    except Exception as e:
        print(f"  [xhs] 外壳生成失败: {type(e).__name__}: {e}")
        return None
