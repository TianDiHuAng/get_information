"""把采集到的条目改写成小红书笔记（标题 / 正文 / 标签 / 封面文案）。

用法：
    python -m collector.xhs                # 用 data/papers_pending.json 的 arXiv 论文
    python -m collector.xhs --source daily  # 用今日 items.json 的 AI 相关条目

产出：data/xhs/YYYY-MM-DD-<source>.md（可直接复制去发布）
LLM 不可用时退回模板拼装，保证永远有稿子。
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
CONF = ROOT / "config" / "xhs.yaml"
LLM_CONF = ROOT / "config" / "llm.yaml"
OUT_DIR = ROOT / "data" / "xhs"

DEFAULTS = {
    "persona": "你是 AI × 生物医药方向的科研人。",
    "audience": "做 AI 制药的研究生和工程师",
    "title_rules": {"max_chars": 20, "banned": []},
    "tags": {"fixed": [], "pool": []},
    "cover": {"lines": 3, "max_chars_per_line": 9},
    "limit_per_post": 6,
}


def conf() -> dict:
    data = dict(DEFAULTS)
    if CONF.exists():
        try:
            data.update(yaml.safe_load(CONF.read_text(encoding="utf-8")) or {})
        except Exception:
            pass
    return data


def _llm_conf() -> dict:
    c: dict = {}
    if LLM_CONF.exists():
        try:
            c = yaml.safe_load(LLM_CONF.read_text(encoding="utf-8")) or {}
        except Exception:
            c = {}
    return {
        "api_key": os.environ.get("OPENAI_API_KEY") or str(c.get("api_key") or ""),
        "base_url": (os.environ.get("OPENAI_BASE_URL") or str(c.get("base_url") or "")).rstrip("/")
        or "https://api.openai.com/v1",
        "model": os.environ.get("OPENAI_MODEL") or str(c.get("model") or ""),
    }


# ---------------------------------------------------------------- 取素材


def load_papers(limit: int) -> list[dict]:
    """arXiv 论文：优先用待发队列（已翻译、已按主题筛选）。"""
    p = ROOT / "data" / "papers_pending.json"
    rows = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    rows = sorted(rows, key=lambda x: x.get("published", ""), reverse=True)[:limit]
    return rows


def load_daily(limit: int) -> list[dict]:
    p = ROOT / "data" / "items.json"
    if not p.exists():
        return []
    items = json.loads(p.read_text(encoding="utf-8")).get("items", [])
    pool = [i for i in items if i.get("extra", {}).get("topic")]
    pool.sort(key=lambda x: x.get("extra", {}).get("score", 0), reverse=True)
    return pool[:limit]


def _brief(items: list[dict], kind: str) -> str:
    lines = []
    for i, it in enumerate(items, 1):
        title = it.get("title") or it.get("title_original") or ""
        summary = (it.get("extra", {}).get("summary_original") or it.get("summary") or "")[:220]
        meta = it.get("published") or it.get("extra", {}).get("age_h", "")
        lines.append(f"{i}. {title}\n   摘要：{summary}\n   来源：{it.get('source', kind)} {meta}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 生成


def _brief_deep(lead: dict, others: list[dict], sec: dict) -> str:
    """主打论文给正文四段，陪跑论文只给摘要。"""
    parts = [f"【主打】{lead.get('title', '')}"]
    if sec.get("abstract"):
        parts.append(f"摘要：{sec['abstract']}")
    if sec.get("intro"):
        parts.append(f"问题背景：{sec['intro']}")
    if sec.get("method"):
        parts.append(f"方法与做法：{sec['method']}")
    if sec.get("results"):
        parts.append(f"实验结果：{sec['results']}")
    if sec.get("conclusion"):
        parts.append(f"结论与局限：{sec['conclusion']}")
    if len(others) == 0:
        return "\n".join(parts)
    parts.append("\n【陪跑，各 1~2 句带过】")
    for i, it in enumerate(others, 1):
        parts.append(f"{i}. {it.get('title', '')}\n   摘要：{(it.get('summary') or '')[:300]}")
    return "\n".join(parts)


PROMPT_DEEP = """{persona}

你在为「{audience}」写一篇小红书笔记。读者是同行，一眼能看出你懂不懂，
所以不要复述摘要，要讲清"这篇到底做了什么、结果说明什么、哪里还不能信"。

材料（主打论文我给了正文的四个部分，其余只给摘要）：
{brief}

硬性要求：
1. **标题**给 3 个备选，每个 ≤{max_title} 字。要具体：带上方法名、任务名或一个结论性判断，
   禁止「盘点」「干货」「必看」这类空词，禁止 {banned}。
2. **正文** 700~880 字（小红书上限 1000，务必不要超过 900），纯文本，不要 Markdown（不要 ** ## - ），用换行和 emoji 分段。
3. 正文结构：
   - 开头 2~3 行：说清这篇解决的是什么具体问题，以及为什么它难（第一人称，口语）
   - 「怎么做」：用 3~5 句话讲方法的关键设计，要提到具体的技术选择（比如用了什么模型、什么数据集、怎么训练）
   - 「结果」：至少 2 个具体发现，带上原始数字或对比关系；不要写"效果很好"这种空话
   - 「哪里还不能信」：明确说出局限、适用范围、或者作者自己承认的问题
   - 「对做药的人意味着什么」：1~2 句，落到可执行的动作
   - 结尾：一句你的判断 + 一个具体的互动提问
   - 最后另起一段，用「📌 顺带」开头，把陪跑论文各用一句话带过
4. **事实纪律**：只能用材料里出现的数字、方法名、数据集名、结论。
   材料没说的一律不写，不要补充你自己的背景知识，不要编造对比结果。
   英文术语没有把握就保留英文原词。
5. 标签 6~10 个，从这些里挑：{pool}
6. 封面文案 3 行，每行 ≤{cover_len} 字。第一行要具体（点出论文解决的核心问题），第三行制造"值不值得看"的判断。

只输出 JSON：
{{"titles": ["...", "...", "..."], "body": "...", "tags": ["..."], "cover": ["...", "...", "..."]}}"""


PROMPT = """{persona}

你在为一个「{audience}」写小红书笔记。小红书用户划得很快，前三行决定生死。

素材（{n} 条）：
{brief}

硬性要求：
1. **标题**给 3 个备选，每个 ≤{max_title} 字（中文字符计）。用数字/反差/身份代入制造点击欲，
   禁止出现 {banned} 这类学术词，禁止用"盘点""干货分享"这类空词。
2. **正文** 400~650 字，纯文本，**不要用 Markdown 语法**（不要 ** ## - ），只用换行和 emoji。
   相邻两条要点之间空一行，方便手机上阅读。
3. 结构：
   - 开头 2 行：一个具体场景或一句反常识判断（第一人称，口语，比如"我连着扫了三天 arXiv，越看越觉得……"）
   - 中间 3~5 条，每条格式：`emoji 一句小标题` 换行 `一到两行解释`，解释要落到"这对做药的人意味着什么"
   - 结尾：一句自己的判断 + 一个具体的互动提问（不要"你怎么看"这种空话）
4. **事实纪律（最重要）**：只能使用素材摘要里出现过的概念、数字、方法名。
   摘要里没有的术语一律不写；不确定中文译法就直接用英文原词。
   不许编造机构、对比结论、性能提升幅度，也不要把两条素材的结论混成一条。
5. 标签 6~10 个，从这些里挑：{pool}
6. 封面文案 3 行，每行 ≤{cover_len} 字，第一行是钩子，第三行是"值不值得看"。

只输出 JSON：
{{"titles": ["...", "...", "..."], "body": "...", "tags": ["..."], "cover": ["...", "...", "..."]}}"""


FIX_PROMPT = """上一版没通过自检，问题如下：
{issues}

上一版：
标题：{titles}
正文：
{body}

请在保留事实和主要观点不变的前提下修正，重新输出同样的 JSON 格式
（titles 3 个、body、tags、cover）。
注意：标题每个必须 ≤{max_title} 字（含英文和标点），正文严格控制在 350~500 字，
不要用任何 Markdown 符号。"""


TERM_FIX = {
    r"\bpLMI\b": "pLM",
    r"\bPLM\b": "pLM",
    r"\bpLm\b": "pLM",
    r"\bplm\b": "pLM",
    r"\bADME\b(?!T)": "ADMET",
    r"\bGNNs\b": "GNN",
}


def _normalize_terms(text: str) -> str:
    for pat, rep in TERM_FIX.items():
        text = re.sub(pat, rep, text)
    return text


def _as_list(v, maxlen: int = 0) -> list[str]:
    """把模型可能返回的字符串/数组统一成干净的字符串列表。"""
    if v is None:
        return []
    if isinstance(v, str):
        parts = [p.strip() for p in re.split(r"[\n|｜/]+", v) if p.strip()]
    elif isinstance(v, (list, tuple)):
        parts = [str(x).strip() for x in v if str(x).strip()]
    else:
        parts = [str(v).strip()]
    out = []
    for p in parts:
        p = re.sub(r"^\*+|\*+$", "", p).strip()
        p = re.sub(r"^\d+[.、)]\s*", "", p)
        if 1 < len(p) <= (maxlen or 200):
            out.append(p)
    return out


def _repair(post: dict, cfg: dict) -> dict:
    """确定性修补：截标题、压正文、去 Markdown 符号。不依赖模型。"""
    lim = int(cfg["title_rules"]["max_chars"])

    def trim_title(t: str) -> str:
        t = re.sub(r"\s+", " ", (t or "").strip())
        if len(t) <= lim:
            return t
        # 优先在标点处断开，保留前半句
        cut = re.split(r"[，。！？；、,.!?;]", t)[0]
        if 6 <= len(cut) <= lim:
            return cut
        return t[: lim - 1].rstrip("，。！？,.!?") + "…" if lim > 3 else t[:lim]

    titles, seen = [], set()
    for t in _as_list(post.get("titles") or post.get("title"), maxlen=60):
        t2 = trim_title(_normalize_terms(t))
        if t2 and t2 not in seen:
            seen.add(t2)
            titles.append(t2)

    body = (post.get("body") or "").replace("\r", "")
    # 模型常把换行写成字面 \n（JSON 双重转义），这里还原成真换行
    if "\n" not in body and "\\n" in body:
        body = body.replace("\\n", "\n")
    body = _normalize_terms(body)
    # 兜底：每个 emoji 小标题前断行，避免挤成一大段
    body = re.sub(r"\s*(?=[\U0001F300-\U0001FAFF\u2600-\u27BF])", "\n\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    body = re.sub(r"\*\*(.+?)\*\*", r"\1", body)
    body = re.sub(r"^#{1,6}\s*", "", body, flags=re.M)
    body = re.sub(r"^\s*[-*]\s+", "", body, flags=re.M)

    if len(body) > 980:  # 小红书正文上限 1000 字；只在失控时按「整节」丢弃
        blocks = [b.strip() for b in re.split(r"\n\s*\n", body) if b.strip()]
        acc, total = [], 0
        for b in blocks:
            if total + len(b) > 900 and acc:
                break
            acc.append(b)
            total += len(b)
        body = "\n\n".join(acc)

    return {**post,
            "titles": titles,
            "body": body,
            "cover": _as_list(post.get("cover"), maxlen=20)[: cfg["cover"]["lines"] or 3],
            "tags": _as_list(post.get("tags"), maxlen=20)}


def _check(post: dict, cfg: dict, count: int = 0) -> list[str]:
    """发布前自检：只提示问题，不阻断。"""
    issues = []
    lim = int(cfg["title_rules"]["max_chars"])
    for t in post.get("titles") or [post.get("title", "")]:
        if len(t) > lim:
            issues.append(f"标题超 {lim} 字：{t}（{len(t)} 字）")
        for bad in cfg["title_rules"].get("banned") or []:
            if bad in t:
                issues.append(f"标题含违禁词「{bad}」：{t}")
    body = post.get("body") or ""
    if any(m in body for m in ("**", "##", "- ")):
        issues.append("正文含 Markdown 符号，小红书不渲染")
    bmin = int(cfg.get('body_min') or 300)
    bmax = int(cfg.get('body_max') or 950)
    if len(body) < bmin:
        issues.append(f"正文偏短（{len(body)} 字），目标 {bmin}~{bmax}")
    if len(body) > 1000:
        issues.append(f"正文超小红书上限（{len(body)} 字）")
    tail = body.strip().split("\n")[-1] if body.strip() else ""
    if not any(q in tail for q in ("？", "?", "评论区", "留言", "说说")):
        issues.append("结尾缺少互动提问")
    if len(post.get("tags") or []) < 6:
        issues.append("标签少于 6 个")
    if count:
        blob = " ".join(post.get("titles") or []) + " " + (post.get("body") or "")
        for n in set(re.findall(r"(\d+)\s*篇", blob)):
            if int(n) != count:
                issues.append(f"篇数不一致：文中说 {n} 篇，实际 {count} 篇")
    return issues


def _chat(prompt: str, c: dict) -> str:
    import requests

    headers = {"Content-Type": "application/json"}
    if c["api_key"]:
        headers["Authorization"] = f"Bearer {c['api_key']}"
    r = requests.post(
        f"{c['base_url']}/chat/completions",
        headers=headers,
        json={"model": c["model"], "messages": [{"role": "user", "content": prompt}], "temperature": 0.7},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _parse(text: str) -> dict:
    """容错解析：模型常在 JSON 里放裸换行/尾逗号，逐级修复。"""
    raw = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    s, e = raw.find("{"), raw.rfind("}")
    if s < 0 or e < s:
        raise ValueError("no JSON object")
    body = raw[s : e + 1]

    attempts = [
        body,
        body.replace("\r", ""),
        re.sub(r",\s*([}\]])", r"\1", body.replace("\r", "")),  # 去尾逗号
    ]
    for a in attempts:
        for strict in (True, False):
            try:
                return json.loads(a, strict=strict)
            except Exception:
                continue
    raise ValueError("JSON 解析失败")


def fallback(items: list[dict], cfg: dict, kind: str) -> dict:
    """LLM 不可用时的模板稿：结构仍然像小红书。"""
    n = len(items)
    label = "AI 制药" if kind == "arxiv" else "AI 前沿"
    title = f"{label}这周最值得读的 {n} 篇 🔬"[: cfg["title_rules"]["max_chars"]]
    body = [f"又在 arXiv 上泡了一天，挑了 {n} 篇真的有用的 👇", ""]
    for i, it in enumerate(items, 1):
        t = it.get("title") or it.get("title_original") or ""
        t = re.sub(r"\s*[:：]\s*", "：", t)[:40]
        body.append(f"{i}️⃣ {t}")
        s = (it.get("summary") or "").strip()
        if s:
            body.append(f"　{s[:80]}")
        body.append("")
    body.append("有条件的话建议直接看原文，摘要只能看个大概 👀")
    body.append("你最想我拆哪一篇？评论区点单～")
    return {
        "titles": [title, f"{label}本周 {n} 篇", f"这 {n} 篇论文别错过"],
        "body": "\n".join(body),
        "tags": list(cfg["tags"]["fixed"]),
        "cover": [f"{label}", f"本周 {n} 篇", "挑重点讲"],
    }


ENDING_PROMPT = """下面是一篇小红书笔记的正文，缺结尾。

{body}

请只输出两行（不要编号、不要解释）：
第一行：一句你的判断，说清这篇工作的意义或局限，要具体，不要空话
第二行：一个具体的互动提问，要能让同行有话说（比如问他们用什么方法、踩过什么坑）"""


def _ensure_ending(post: dict, llm: dict) -> dict:
    """结尾缺互动提问时，单独补两行。比整篇重写更可靠。"""
    body = (post.get("body") or "").rstrip()
    if any(q in body.split("\n")[-1] for q in ("？", "?", "评论区")):
        return post
    try:
        add = _chat(ENDING_PROMPT.format(body=body[-1200:]), llm).strip()
        add = re.sub(r"^```.*?```$", "", add, flags=re.S).strip()
        add = "\n".join(ln for ln in add.splitlines() if ln.strip())[:400]
        if add:
            post = {**post, "body": body + "\n\n" + add}
            print("  [xhs] 已补写结尾")
    except Exception as e:
        print(f"  [xhs] 结尾补写失败: {type(e).__name__}")
    return post


def _ensure_extras(post: dict, others: list[dict]) -> dict:
    """陪跑论文没写进正文时，用摘要补一个「顺带」段，保证不漏。"""
    body = post.get("body") or ""
    if not others or "📌" in body:
        return post

    def short(t: str, n: int = 34) -> str:
        t = re.sub(r"\s+", " ", (t or "").strip())
        if len(t) <= n:
            return t
        cut = t[:n]
        i = cut.rfind(" ")
        return (cut[:i] if i > n * 0.5 else cut) + "…"

    lines = ["📌 顺带记两篇"]
    for it in others:
        title = short(re.sub(r"\s*[:：]\s*", "：", it.get("title", "")), 38)
        raw = (it.get("summary") or "").strip()
        # 中文摘要取首句；英文摘要只取到第一个句点，避免半句
        zh = re.search(r"[\u4e00-\u9fff]", raw) is not None
        s = raw.split("。")[0] if zh else raw.split(". ")[0]
        s = short(s, 52)
        lines.append(f"· {title}\n  {s}" if s else f"· {title}")
    post = {**post, "body": body.rstrip() + "\n\n" + "\n".join(lines)}
    print("  [xhs] 已补「顺带」段")
    return post


SHRINK_PROMPT = """下面这篇小红书正文有 {n} 字，超过平台 1000 字上限。

{body}

请把它压缩到 850 字以内并输出正文（不要 JSON，不要解释）：
- 必须保留所有具体数字、方法名、数据集名和结论
- 优先删掉修饰语、重复表述、铺垫句
- 保留开头钩子、每段的小标题、结尾的判断和提问
- 不要丢「📌 顺带」那一段"""


def _shrink(post: dict, llm: dict, limit: int = 980) -> dict:
    body = (post.get("body") or "").strip()
    if len(body) <= limit:
        return post
    try:
        out = _chat(SHRINK_PROMPT.format(n=len(body), body=body), llm).strip()
        out = re.sub(r"^```.*?```$", "", out, flags=re.S).strip()
        if 300 < len(out) <= limit:
            print(f"  [xhs] 压缩 {len(body)} → {len(out)} 字")
            return {**post, "body": out}
    except Exception as e:
        print(f"  [xhs] 压缩失败: {type(e).__name__}")
    # 兜底：丢中间最长的段
    paras = [p for p in body.split("\n\n") if p.strip()]
    while len("\n\n".join(paras)) > limit and len(paras) > 3:
        mid = max(range(1, len(paras) - 1), key=lambda i: len(paras[i]))
        paras.pop(mid)
    return {**post, "body": "\n\n".join(paras)}


def build(kind: str = "arxiv", limit: int | None = None, deep: bool = True) -> Path:
    cfg = conf()
    n = int(limit or cfg.get("limit_per_post") or 6)
    items = load_papers(n) if kind == "arxiv" else load_daily(n)
    if not items:
        raise SystemExit(f"没有素材：{kind}")

    used: list[dict] = items
    lead, others, sec = items[0], [], {}
    if deep and kind == "arxiv":
        from .paper_deep import fetch_sections

        lead = items[0]
        others = items[1:3]
        sec = fetch_sections(str(lead.get("id") or ""))
        if not sec.get("ok"):
            print("  [xhs] 正文抓取失败，退回摘要模式")
            deep = False
        else:
            used = [lead] + others

    post: dict | None = None
    llm = _llm_conf()
    if deep and llm['model']:
        from . import xhs_deep, xhs_shell

        facts = xhs_deep.extract_facts(_chat, llm, lead.get('title', ''), sec)
        if facts:
            print('  [xhs] 事实提取完成')
            shell = xhs_shell.build_shell(_chat, llm, cfg, lead.get('title', ''), facts) or {}
            post = xhs_deep.assemble(
                facts, shell, others,
                cover=shell.get('cover') or [],
                tags=shell.get('tags') or list(cfg['tags']['fixed']),
                titles=shell.get('titles') or [],
            )
            # 深度稿的正文由 assemble 确定性拼装，不再走 LLM 正文清洗，避免结构被削掉
            post['cover'] = _as_list(post.get('cover'), maxlen=20)[:3]
            post['tags'] = _as_list(post.get('tags'), maxlen=20)
            post['titles'] = [_normalize_terms(t) for t in _as_list(post.get('titles'), maxlen=60)]
            post = xhs_deep.ensure_sections(post, facts, shell, others)
            print(f'  [xhs] 拼装完成，{len(post["body"])} 字')
        else:
            deep = False
    if post is None and llm["model"]:
        tpl = PROMPT_DEEP if deep else PROMPT
        prompt = tpl.format(
            persona=cfg["persona"].strip(),
            audience=cfg["audience"],
            n=len(items),
            brief=_brief_deep(lead, others, sec) if deep else _brief(items, kind),
            max_title=cfg["title_rules"]["max_chars"],
            banned="、".join(cfg["title_rules"].get("banned") or []) or "无",
            pool="、".join(cfg["tags"].get("pool") or []),
            cover_len=cfg["cover"]["max_chars_per_line"],
        )
        try:
            post = _parse(_chat(prompt, llm))
            print("  [xhs] LLM 生成成功")
            post = _repair(post, cfg)
            titles = post.get("titles") or []
            issues = _check({**post, "titles": titles}, cfg, count=len(used))
            if issues:
                # 本地修补后仍有问题，尝试一次带反馈的重写
                print(f"  [xhs] 自检未过，尝试重写: {'；'.join(issues)[:80]}")
                try:
                    fix = FIX_PROMPT.format(
                        issues="\n".join(f"- {x}" for x in issues),
                        titles=" / ".join(titles),
                        body=post.get("body", ""),
                        max_title=cfg["title_rules"]["max_chars"],
                    )
                    fixed = _repair(_parse(_chat(fix, llm)), cfg)
                    # 重写稿更差就保留原稿
                    if len(_check({**fixed, "titles": fixed.get("titles") or []}, cfg, count=len(used))) <= len(issues) \
                            and fixed.get("titles") and fixed.get("cover"):
                        post = fixed
                    else:
                        print("  [xhs] 重写稿不达标，保留修补稿")
                except Exception as e2:
                    print(f"  [xhs] 重写失败，保留修补稿: {type(e2).__name__}: {e2}")
        except Exception as e:
            print(f"  [xhs] LLM 失败，用模板稿: {type(e).__name__}: {e}")
    if not post:
        post = fallback(items, cfg, kind)
    elif deep and llm['model']:
        post = _ensure_extras(post, others)
        post = _ensure_ending(post, llm)
        if not deep or len(post['body']) > 1000:
            post = _shrink(post, llm)

    day = datetime.now().strftime("%Y-%m-%d")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{day}-{kind}.md"

    cover = post.get("cover") or []
    tags = post.get("tags") or []
    if not any(t.startswith("#") for t in tags):
        tags = ["#" + t.lstrip("#") for t in tags]
    titles = post.get("titles") or ([post["title"]] if post.get("title") else [])
    issues = _check({**post, "titles": titles}, cfg, count=len(used))

    doc = [
        f"# 小红书笔记 · {day} · {kind}",
        "",
        "## 封面文案（做成图片三行大字，第一行最大）",
        "",
        *[f"**{c}**" for c in cover],
        "",
        "## 标题（三选一）",
        "",
        *[f"{i}. {t}   （{len(t)} 字）" for i, t in enumerate(titles, 1)],
        "",
        "## 正文（直接复制，不要带 Markdown）",
        "",
        post.get("body", ""),
        "",
        "## 标签",
        "",
        " ".join(tags),
        "",
    ]
    if issues:
        doc += ["## ⚠️ 自检提示", "", *[f"- {x}" for x in issues], ""]
    doc += [
        "---",
        f"素材来源：{len(used)} 条 {'arXiv（AI 制药）' if kind == 'arxiv' else '今日 AI 相关'}",
        "",
        "### 素材清单（发布时不用带）",
        "",
        *[f"- {i.get('title', '')} — {i.get('url', '')}" for i in used],
    ]
    out.write_text("\n".join(doc), encoding="utf-8")
    return out


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="arxiv", choices=["arxiv", "daily"])
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    print(build(a.source, a.limit))
