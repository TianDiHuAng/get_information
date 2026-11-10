"""小红书深度稿：两段式生成。

第一段：让模型从论文正文里抽出结构化事实（问题/方法/两个发现/局限/意义）。
第二段：由本程序按固定骨架拼装正文，保证五段齐全、字数可控。

这样做的好处是结构不靠模型自觉：模型只负责"说清楚"，排版和完整性由代码保证。
"""

from __future__ import annotations

import json
import re

FACT_PROMPT = """你在读一篇论文的正文片段，请提取可写成科普笔记的事实。

论文：{title}
{sec_text}

严格按字数写（超了会被截断，宁可少写细节也要写完整句子）：
- problem ≤ 88 字
- method ≤ 155 字
- findings 恰好 2 条，每条 ≤ 62 字
- limits ≤ 76 字
- meaning ≤ 80 字

只输出 JSON（不要解释）：
{{
  "problem": "要解决的具体问题 + 为什么难（完整句子，≤88 字）",
  "method": "关键设计：模型/数据/训练规模（完整句子，≤155 字）",
  "findings": ["带数字或对比的发现（≤62 字）", "第二个发现（≤62 字）"],
  "limits": "局限，具体到哪种设置下不成立（≤76 字）",
  "meaning": "对做药/蛋白设计的人意味着什么，可执行（≤80 字）"
}}

要求：
- 只能用原文出现的信息，不要补充背景知识，不要编数字。
- 英文术语没把握就保留原文。
- findings 必须至少 2 条，每条都要有具体的结果，不要"效果很好"这类空话。"""


def _json_block(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e < s:
        raise ValueError("no json")
    return json.loads(text[s : e + 1], strict=False)


def sec_text(sec: dict, per_field: int = 520) -> str:
    out = []
    for key, label in (
        ("abstract", "摘要"),
        ("intro", "问题背景"),
        ("method", "方法与做法"),
        ("results", "实验结果"),
        ("conclusion", "结论与局限"),
    ):
        v = (sec.get(key) or "").strip()
        if v:
            out.append(f"## {label}\n{v[:per_field]}")
    return "\n\n".join(out)


FILL_PROMPT = """论文正文片段如下，请只补提取缺失的项。

{sec_text}

需要补：{missing}

只输出 JSON，key 只用下面这些：
{{"findings": ["带具体数字或对比关系的发现", "第二个发现"], "limits": "局限（1~2 句，具体）", "meaning": "对做药物发现/蛋白设计的人意味着什么（1~2 句，可执行）"}}

只输出你被要求补的 key；只能用原文信息，不要编数字。"""


def _complete(d: dict) -> list[str]:
    missing = []
    if len([f for f in (d.get("findings") or []) if str(f).strip()]) < 2:
        missing.append("findings")
    if not str(d.get("limits") or "").strip():
        missing.append("limits")
    if not str(d.get("meaning") or "").strip():
        missing.append("meaning")
    return missing


def extract_facts(chat, llm: dict, title: str, sec: dict) -> dict | None:
    try:
        raw = chat(FACT_PROMPT.format(title=title, sec_text=sec_text(sec)), llm)
        d = _json_block(raw)
    except Exception as e:
        print(f"  [xhs] 事实提取失败: {type(e).__name__}: {e}")
        return None
    if not (d.get("problem") and d.get("method")):
        return None
    d["findings"] = [str(x).strip() for x in (d.get("findings") or []) if str(x).strip()][:3]

    missing = _complete(d)
    if missing:
        print(f"  [xhs] 缺 {missing}，补提取")
        try:
            more = _json_block(
                chat(FILL_PROMPT.format(sec_text=sec_text(sec, 700), missing="、".join(missing)), llm)
            )
            if "findings" in missing:
                extra = [str(x).strip() for x in (more.get("findings") or []) if str(x).strip()]
                seen = set(d["findings"])
                d["findings"] += [x for x in extra if x not in seen][: max(0, 3 - len(d["findings"]))]
            for k in ("limits", "meaning"):
                if k in missing and str(more.get(k) or "").strip():
                    d[k] = str(more[k]).strip()
        except Exception as e:
            print(f"  [xhs] 补提取失败: {type(e).__name__}")
    return d


def ensure_sections(post: dict, facts: dict, endpoint: dict, others: list[dict]) -> dict:
    """最后一道保险：哪个板块丢了，就用事实原样补回来。"""
    body = post.get("body") or ""
    has = {m: m in body for m in ("🧪", "🔧", "📊", "⚠️", "💡")}
    order = ["🧪", "🔧", "📊", "⚠️", "💡"]
    blocks = [b for b in re.split(r"\n\s*\n", body) if b.strip()]

    def insert_after(marker: str, block: str) -> None:
        nxt = order[order.index(marker) + 1 :]
        for m in nxt:
            for i, b in enumerate(blocks):
                if b.startswith(m):
                    blocks.insert(i, block)
                    return
        blocks.append(block)

    if not has["🔧"] and facts.get("method"):
        insert_after("🧪", f"🔧 怎么做\n{_fit(facts['method'], B['method'])}")
    if not has["📊"] and facts.get("findings"):
        lines = "\n".join(f"· {_fit(f, B['finding_each'])}" for f in facts["findings"][:3])
        insert_after("🔧", f"📊 结果\n{lines}")
    if not has["⚠️"] and facts.get("limits"):
        insert_after("📊", f"⚠️ 哪里还不能信\n{_fit(facts['limits'], B['limits'])}")
    if not has["💡"] and facts.get("meaning"):
        insert_after("⚠️", f"💡 对做药的人意味着什么\n{_fit(facts['meaning'], B['meaning'])}")

    lost = [m for m, ok in has.items() if not ok]
    if lost:
        print(f"  [xhs] 补回缺失板块: {lost}")
    return {**post, "body": "\n\n".join(blocks)}


BUDGET = {
    "hook": 72,
    "problem": 115,
    "method": 225,
    "finding_each": 90,
    "limits": 105,
    "meaning": 108,
    "other_title": 34,
    "other_sum": 55,
    "ending": 115,
}


def _scaled(scale: float) -> dict:
    return {k: max(20, int(v * scale)) for k, v in BUDGET.items()}


SENT_SPLIT = re.compile(r"(?<=[。！？；])")


def _fit(text: str, limit: int, allow_ellipsis: bool = False) -> str:
    """截到 limit 以内：优先保留完整句子，绝不切在句子中间。

    1) 整句累加，直到再加一句就超限 → 返回已收的整句
    2) 一句都放不下时：英文按词边界收尾，中文按分句（，）收尾
    3) 只有 allow_ellipsis=True 才允许加省略号
    """
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= limit:
        return t

    # 整句累加
    sents = [s for s in SENT_SPLIT.split(t) if s.strip()]
    acc = ""
    for s in sents:
        if len(acc) + len(s) > limit:
            break
        acc += s
    if acc:
        return acc.strip()

    # 第一句就超限：按分句/词边界退让
    cut = t[:limit]
    for sep in ("，", "、", ", ", " "):
        i = cut.rfind(sep)
        if i > limit * 0.5:
            body = cut[:i].rstrip("，,、 ")
            return body + ("…" if allow_ellipsis else "")
    body = cut[: limit - 1].rstrip("，,、 ")
    return body + ("…" if allow_ellipsis else "")


CONDENSE_PROMPT = """把下面这段中文压缩到 {limit} 字以内，输出压缩后的结果（不要解释、不要引号）。

必须保留：具体数字、方法名、数据集名、模型名、结论方向。
可以删：修饰语、重复表述、铺垫、举例。
不要加省略号，必须是完整通顺的句子结尾。

原文：
{text}"""


def condense(facts: dict, chat, llm: dict, budget: dict | None = None) -> dict:
    """字段超过预算时，先让模型按字数重写一次；失败再靠 _fit 整句裁剪。"""
    B = budget or BUDGET
    out = dict(facts)

    def fix_field(key: str, limit: int) -> str:
        val = str(out.get(key) or "").strip()
        if not val or len(val) <= limit:
            return val
        try:
            new = chat(CONDENSE_PROMPT.format(limit=limit, text=val), llm).strip()
            new = re.sub(r"^```.*?```$", "", new, flags=re.S).strip().strip('"“”')
            if 20 <= len(new) <= limit:
                print(f"  [xhs] {key} 压缩 {len(val)}→{len(new)}")
                return new
        except Exception as e:
            print(f"  [xhs] {key} 压缩失败: {type(e).__name__}")
        return val

    for key in ("problem", "method", "limits", "meaning"):
        out[key] = fix_field(key, B[key])
    if out.get("findings"):
        out["findings"] = [fix_field_one(f, B["finding_each"], chat, llm) for f in out["findings"]]
    return out


def fix_field_one(text: str, limit: int, chat, llm: dict) -> str:
    val = str(text or "").strip()
    if len(val) <= limit:
        return val
    try:
        new = chat(CONDENSE_PROMPT.format(limit=limit, text=val), llm).strip()
        new = re.sub(r"^```.*?```$", "", new, flags=re.S).strip().strip('"“”')
        if 12 <= len(new) <= limit:
            return new
    except Exception:
        pass
    return val


def _paper_ref(it: dict) -> str:
    """给出一行可搜索的原文引用：arxiv.org/abs/xxxx 或 arXiv:xxxx。"""
    url = str(it.get("url") or "").strip()
    pid = str(it.get("id") or "").strip()
    if url.startswith("http"):
        return url.split("://", 1)[1]
    if pid:
        return f"arXiv:{pid}"
    return ""


def assemble(facts: dict, endpoint: dict, others: list[dict], cover: list[str], tags: list[str],
             titles: list[str], scale: float = 1.0) -> dict:
    """按固定骨架拼正文；每段有字数预算，保证结构完整且不超长。"""
    B = _scaled(scale) if scale != 1.0 else BUDGET
    body = []
    head = _fit(endpoint.get("hook") or "", B["hook"])
    if head:
        body.append(head)
    body.append(f"🧪 {endpoint.get('problem_head') or '问题在哪'}\n{_fit(facts.get('problem', ''), B['problem'])}")
    body.append(f"🔧 怎么做\n{_fit(facts.get('method', ''), B['method'])}")

    findings = [f for f in (facts.get("findings") or []) if str(f).strip()][:3]
    if findings:
        lines = "\n".join(f"· {_fit(f, B['finding_each'])}" for f in findings)
        body.append(f"📊 结果\n{lines}")
    if facts.get("limits"):
        body.append(f"⚠️ 哪里还不能信\n{_fit(facts['limits'], B['limits'])}")
    if facts.get("meaning"):
        body.append(f"💡 对做药的人意味着什么\n{_fit(facts['meaning'], B['meaning'])}")

    lead_ref = _paper_ref(endpoint.get("_lead") or {})
    if lead_ref:
        body.append(f"📎 原文：{lead_ref}")

    if others:
        rows = ["📌 顺带记两篇"]
        for it in others:
            t = _fit(re.sub(r"\s*[:：]\s*", "：", it.get("title") or ""), B["other_title"], allow_ellipsis=True)
            raw = (it.get("summary") or "").strip()
            zh = re.search(r"[\u4e00-\u9fff]", raw) is not None
            s = (raw.split("。")[0] if zh else raw.split(". ")[0]).strip()
            s = _fit(s, B["other_sum"], allow_ellipsis=True)
            ref = _paper_ref(it)
            head = f"· {t}｜{ref}" if ref else f"· {t}"
            rows.append(f"{head}\n  {s}" if s else head)
        body.append("\n".join(rows))

    tail = _fit(endpoint.get("ending") or "", B["ending"])
    if tail:
        body.append(tail)

    text = "\n\n".join(b for b in body if b)
    if len(text) > 990 and scale == 1.0:
        return assemble(facts, endpoint, others, cover, tags, titles, scale=0.8)
    return {"titles": titles, "body": text, "tags": tags, "cover": cover}
