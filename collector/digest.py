"""把抓取结果压成一份可读的日报。

有 LLM key（OPENAI_API_KEY / OPENAI_BASE_URL）时让模型写导读；
没有时退化成结构化简报——同样是“总结”，只是不编造。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import yaml

SOURCE_LABEL = {
    "smolai": "smol.ai AINews",
    "thebatch": "The Batch",
    "hf_papers": "HF Daily Papers",
    "arxiv": "arXiv",
    "hackernews": "Hacker News",
    "github": "GitHub",
    "bilibili": "B站",
    "toutiao": "头条",
    "kr36": "36氪",
    "sspai": "少数派",
    "google_news": "Google News",
}

LLM_CONFIG_PATH = Path(__file__).parent.parent / "config" / "llm.yaml"


def _llm_conf() -> dict:
    """环境变量优先，其次 config/llm.yaml（免设环境变量的场景）。"""
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
        "model": os.environ.get("OPENAI_MODEL") or str(conf.get("model") or "gpt-4o-mini"),
    }


def _pick(items: list[dict], n: int, per_source: int = 2) -> list[dict]:
    """按分数取前 n 条，但同一来源最多 per_source 条，避免刷屏。"""
    out, count = [], {}
    for it in items:
        if count.get(it["source"], 0) >= per_source:
            continue
        out.append(it)
        count[it["source"]] = count.get(it["source"], 0) + 1
        if len(out) >= n:
            break
    return out


def _line(it: dict) -> str:
    src = SOURCE_LABEL.get(it["source"], it["source"])
    summary = (it.get("summary") or "").strip()
    tail = f" — {summary}" if summary else ""
    return f"- **[{it['title']}]({it['url']})** `{src}`{tail}"


def _sections(payload: dict) -> dict:
    """分区选条：国外（重点）在前，国内热榜在后。MD 与 HTML 邮件共用。"""
    items = payload["items"]
    ov = [i for i in items if (i.get("region") or "overseas") == "overseas"]
    dom = [i for i in items if (i.get("region") or "overseas") == "domestic"]
    head = _pick(ov, 6) or _pick(items, 6)
    primary = _pick([i for i in ov if i["layer"] == "primary"], 5, per_source=2)
    dom.sort(key=lambda x: (bool(x["extra"].get("topic")), x["extra"]["score"]), reverse=True)
    cn = _pick(dom, 6, per_source=2)
    papers = _pick([i for i in ov if i["source"] in ("hf_papers", "arxiv")], 4, per_source=2)
    x = _pick([i for i in ov if i["source"] == "x"], 5, per_source=5)
    deal = _pick([i for i in items if i["extra"].get("deal")], 6, per_source=2)
    return {"head": head, "primary": primary, "cn": cn, "papers": papers, "x": x, "deal": deal}


def structured_digest(payload: dict, lmarena: dict | None = None,
                      aa: dict | None = None) -> str:
    items = payload["items"]
    stats = payload["stats"]
    day = datetime.now().strftime("%Y-%m-%d")
    sec = _sections(payload)

    parts = [
        f"# 情报日报 · {day}",
        "",
        f"> {len(items)} 条 / {stats['sources_ok']} 个源"
        f"（国外 {(stats.get('by_region') or {}).get('overseas', 0)} · 国内 {(stats.get('by_region') or {}).get('domestic', 0)}）"
        f" / 覆盖 {len(stats['by_layer'])} 层",
        "",
        "## 国外 · 今日必看",
        *[_line(i) for i in sec["head"]],
        "",
        "## 国外 · 一手源头",
        *[_line(i) for i in sec["primary"]],
        "",
        "## 国外 · X 在聊什么",
        *[_line(i) for i in sec["x"]],
        "",
        "## 国外 · 论文速览",
        *[_line(i) for i in sec["papers"]],
        "",
        "## 国内 · 热榜与媒体",
        *[_line(i) for i in sec["cn"]],
        "",
        "## 羊毛福利",
        *([_line(i) for i in sec["deal"]] or ["- 今天没有值得报的羊毛"]),
    ]
    if lmarena and lmarena.get("models"):
        from .leaderboards import change_of

        parts += [
            "",
            f"## LMArena 总榜 Top 5（数据 {lmarena['date']}）",
            *[
                f"- **{m['model']}** {m['rating']}（{change_of(m)[0]}）`{m['org']}`"
                for m in lmarena["models"][:5]
            ],
        ]
    if aa and aa.get("models"):
        from .leaderboards import change_of, price_change_of

        parts += [
            "",
            f"## AA 智能指数 Top 5（快照 {aa['date']}）",
            *[
                f"- **{m['model']}** {m['intelligence']}（{change_of(m)[0]}）"
                f" 输出价 {'$' + format(m['price_out'], '.2f') if m.get('price_out') is not None else '—'}"
                f"{price_change_of(m)} `{m['org']}`"
                for m in aa["models"][:5]
            ],
        ]
    parts += ["", "---", "由 `python run.py` 自动生成；数据在 `data/items.json`。"]
    return "\n".join(parts)


def email_html(payload: dict, ai_text: str | None, lmarena: dict | None = None,
               aa: dict | None = None) -> str:
    """浅色卡片式 HTML 邮件（内联样式，QQ 邮箱等客户端直接渲染）。"""
    import html as _h
    import re

    stats = payload["stats"]
    sec = _sections(payload)
    day = datetime.now().strftime("%Y-%m-%d")
    bl = stats.get("by_layer", {})

    def item_html(it: dict, num: int | None = None) -> str:
        src = _h.escape(SOURCE_LABEL.get(it["source"], it["source"]))
        title = _h.escape(it["title"] or "")
        url = _h.escape(it["url"] or "", quote=True)
        summary = _h.escape((it.get("summary") or "").strip()[:140])
        num_html = (
            f'<span style="color:#c1c9d3;font-size:14px;font-weight:700;'
            f'margin-right:8px;">{num:02d}</span>' if num else ""
        )
        sum_html = (
            f'<div style="color:#6b7280;font-size:13px;line-height:1.65;'
            f'margin-top:3px;">{summary}</div>' if summary else ""
        )
        return (
            f'<div style="margin:0 0 16px;">'
            f'{num_html}<a href="{url}" style="font-size:15px;font-weight:600;'
            f'color:#1a56db;text-decoration:none;line-height:1.5;">{title}</a>'
            f'<span style="color:#9ca3af;font-size:12px;margin-left:6px;">{src}</span>'
            f'{sum_html}</div>'
        )

    def section(title: str, items: list[dict], numbered: bool = False) -> str:
        rows = "".join(item_html(it, i + 1 if numbered else None) for i, it in enumerate(items))
        if not rows:
            return ""
        return (
            f'<h2 style="font-size:15px;color:#111827;margin:26px 0 12px;'
            f'padding-bottom:8px;border-bottom:1px solid #e5e7eb;">{title}</h2>{rows}'
        )

    ai_html = ""
    if ai_text:
        t = _h.escape(ai_text)
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        t = t.replace("\n\n", '<br><br>').replace("\n", "<br>")
        ai_html = (
            '<div style="background:#eff6ff;border-left:4px solid #3b82f6;'
            'border-radius:8px;padding:14px 18px;margin:0 0 8px;'
            'font-size:14px;line-height:1.8;">'
            '<div style="font-weight:700;color:#1e40af;margin-bottom:6px;">AI 导读</div>'
            f'<div>{t}</div></div>'
        )

    lm_html = ""
    if lmarena and lmarena.get("models"):
        from .leaderboards import change_of

        th = ('color:#6b7280;font-weight:500;font-size:12px;padding:4px 8px;'
              'border-bottom:1px solid #e5e7eb;')
        td = 'padding:6px 8px;border-bottom:1px solid #f3f4f6;'
        rows = ""
        for m in lmarena["models"]:
            ch, _ = change_of(m)
            color = ("#059669" if ch.startswith("▲") else
                     "#dc2626" if ch.startswith("▼") else
                     "#2563eb" if ch == "新" else "#9ca3af")
            rows += (
                f'<tr><td style="{td}color:#374151;">{m["rank"]}</td>'
                f'<td style="{td}color:{color};">{ch}</td>'
                f'<td style="{td}font-weight:600;">{_h.escape(m["model"])}</td>'
                f'<td style="{td}color:#6b7280;">{_h.escape(m["org"])}</td>'
                f'<td align="right" style="{td}">{m["rating"]}</td></tr>'
            )
        lm_html = (
            '<h2 style="font-size:15px;color:#111827;margin:26px 0 12px;padding-bottom:8px;'
            f'border-bottom:1px solid #e5e7eb;">LMArena 总榜 Top {len(lmarena["models"])}'
            f'（数据 {lmarena["date"]}）</h2>'
            '<table style="width:100%;border-collapse:collapse;font-size:13px;">'
            f'<tr><th align="left" style="{th}">排名</th><th align="left" style="{th}">变化</th>'
            f'<th align="left" style="{th}">模型</th><th align="left" style="{th}">组织</th>'
            f'<th align="right" style="{th}">评分</th></tr>{rows}</table>'
        )

    aa_html = ""
    if aa and aa.get("models"):
        from .leaderboards import change_of, price_change_of

        th = ('color:#6b7280;font-weight:500;font-size:12px;padding:4px 8px;'
              'border-bottom:1px solid #e5e7eb;')
        td = 'padding:6px 8px;border-bottom:1px solid #f3f4f6;'
        rows = ""
        for m in aa["models"]:
            ch, _ = change_of(m)
            color = ("#059669" if ch.startswith("▲") else
                     "#dc2626" if ch.startswith("▼") else
                     "#2563eb" if ch == "新" else "#9ca3af")
            pc = price_change_of(m)
            pc_html = f'<span style="color:#059669;">{pc}</span>' if pc else ""
            price = "—" if m.get("price_out") is None else f'${m["price_out"]:.2f}'
            rows += (
                f'<tr><td style="{td}color:#374151;">{m["rank"]}</td>'
                f'<td style="{td}color:{color};">{ch}</td>'
                f'<td style="{td}font-weight:600;">{_h.escape(m["model"])}</td>'
                f'<td style="{td}color:#6b7280;">{_h.escape(m["org"])}</td>'
                f'<td align="right" style="{td}">{m["intelligence"]}</td>'
                f'<td align="right" style="{td}">{price} {pc_html}</td></tr>'
            )
        aa_html = (
            '<h2 style="font-size:15px;color:#111827;margin:26px 0 12px;padding-bottom:8px;'
            f'border-bottom:1px solid #e5e7eb;">AA 智能指数 Top {len(aa["models"])}'
            f'（快照 {aa["date"]}）</h2>'
            '<table style="width:100%;border-collapse:collapse;font-size:13px;">'
            f'<tr><th align="left" style="{th}">排名</th><th align="left" style="{th}">变化</th>'
            f'<th align="left" style="{th}">模型</th><th align="left" style="{th}">组织</th>'
            f'<th align="right" style="{th}">智能指数</th>'
            f'<th align="right" style="{th}">输出价 $/1M</th></tr>{rows}</table>'
        )

    return f"""<div style="background:#f5f7fa;padding:24px 8px;font-family:-apple-system,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;">
<div style="max-width:660px;margin:0 auto;background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;padding:26px 30px;">
<h1 style="font-size:21px;color:#111827;margin:0 0 6px;">情报日报 · {day}</h1>
<p style="color:#6b7280;font-size:12px;margin:0 0 18px;">{stats.get('raw', 0)} 条 / {stats.get('sources_ok', 0)} 个源（国外 {(stats.get('by_region') or {}).get('overseas', 0)} · 国内 {(stats.get('by_region') or {}).get('domestic', 0)}）</p>
{ai_html}
{section('国外 · 今日必看', sec['head'], numbered=True)}
{section('国外 · 一手源头', sec['primary'])}
{section('国外 · X 在聊什么', sec.get('x') or [])}
{section('国外 · 论文速览', sec['papers'])}
{section('国内 · 热榜与媒体', sec['cn'])}
{section('羊毛福利', sec.get('deal') or [])}
{lm_html}
{aa_html}
<p style="color:#9ca3af;font-size:11px;margin:26px 0 0;padding-top:14px;border-top:1px solid #f3f4f6;">由 Get_Information 自动采集生成，每天一封 · 可视化面板在局域网内访问 http://localhost:8123</p>
</div>
</div>"""


def llm_digest(payload: dict) -> str | None:
    conf = _llm_conf()
    key = conf["api_key"]
    if not key:
        return None
    import requests

    base = conf["base_url"]
    model = conf["model"]
    top = _pick(payload["items"], 20)
    bullets = "\n".join(
        f"- [{i['source']}] {i['title']} :: {(i.get('summary') or '')[:150]}" for i in top
    )
    prompt = (
        f"今天是 {datetime.now().strftime('%Y 年 %m 月 %d 日')}。"
        "你是科技情报编辑。下面是从多个一手/榜单源抓到的条目。"
        "请用中文写一份 400 字以内的简报：开头 2 句总结今天最值得注意的趋势，"
        "然后分 3~5 个要点，每个要点说清发生了什么、为什么重要。"
        "不要编造事实，只基于给定条目。直接输出正文，不要加大标题、结尾语，不要写日期。\n\n"
        f"{bullets}"
    )
    try:
        r = requests.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3},
            timeout=90,
        )
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()
        return text  # 原文；标题由调用方决定（MD 加 "## AI 导读"，邮件加蓝框）
    except Exception as e:
        print(f"  [digest] LLM 失败，退回结构化简报: {e}")
        return None


def build(payload: dict, lmarena: dict | None = None, aa: dict | None = None) -> Path:
    ai = llm_digest(payload)
    body = structured_digest(payload, lmarena, aa)
    if ai:
        body = body.replace("## 今日必看", f"## AI 导读\n\n{ai}\n\n## 今日必看", 1)
    day = datetime.now().strftime("%Y-%m-%d")
    out = Path(__file__).parent.parent / "data" / f"digest-{day}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(body, encoding="utf-8")
    return out


if __name__ == "__main__":
    p = json.loads((Path(__file__).parent.parent / "data" / "items.json").read_text(encoding="utf-8"))
    print(build(p))
