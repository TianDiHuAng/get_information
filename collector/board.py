"""本地看板：一眼看清"这台机器今天跑得怎么样"。

不做增删改界面（改配置就是改 YAML），只回答四个问题：
1. **跑通了吗** —— 阶段、告警、缺期、失败率；
2. **选得怎么样** —— 评分分布、门槛线在哪、分类构成；
3. **花了多少** —— 模型调用数、回执命中率、token、预算占用；
4. **舆论场偏了吗** —— 官方发布 vs 国内讨论，哪边只在说同一件事（差异本身就是信号）。

第 4 点是 AIHOT 没有的：它是公共站，只需要一个"热度"。单用户值得知道
"这条只有海外官方在讲"还是"国内外都在吵" —— 前者是情报，后者是热点。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from . import llm, store, theme

ROOT = Path(__file__).parent.parent
SITE = ROOT / "site"

# 官方发布：一手 + 海外
OFFICIAL_LAYERS = ("primary",)


def _subject_keys(it: dict[str, Any]) -> set[str]:
    """这条讲的是谁：优先用结构化抽出的主体/标签。

    没有结构化时（例如第一次跑还没到结构化的条目）退回"标题里出现的已知实体" ——
    否则舆论场那一段会整片空白，看起来像功能坏了。
    """
    st = (it.get("extra") or {}).get("structure") or {}
    keys = set()
    for s in st.get("subjects") or []:
        keys.add(str(s).strip().lower())
    for t in st.get("tags") or []:
        keys.add("tag:" + str(t).strip().lower())
    if keys:
        return keys

    title = (it.get("title") or "")
    if not title:
        return set()
    try:
        from . import grounding

        for ent in (grounding.taxonomy().get("entities") or {}).values():
            names = [str(ent.get("name") or "")] + [str(a) for a in (ent.get("aliases") or [])]
            for name in names:
                if name and name.lower() in title.lower():
                    keys.add(str(ent.get("name") or name).lower())
                    break
    except Exception:
        pass
    return keys


def discourse(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """官方发布 vs 国内讨论：两侧各有多少、哪些主体只在一边。

    刻意用"主体/标签"而不是文章数：同一件事被十家中文号转一遍，
    主体还是那一个，不该因为转发多就算"国内更热"。
    """
    official, domestic = [], []
    for it in items:
        region = (it.get("region") or "overseas")
        layer = (it.get("layer") or "broad")
        if region == "overseas" and layer in OFFICIAL_LAYERS:
            official.append(it)
        elif region == "domestic" and layer == "social":
            domestic.append(it)

    off_keys = set().union(*[_subject_keys(i) for i in official]) if official else set()
    dom_keys = set().union(*[_subject_keys(i) for i in domestic]) if domestic else set()

    return {
        "official_items": len(official),
        "domestic_items": len(domestic),
        "official_only": sorted(off_keys - dom_keys)[:12],
        "domestic_only": sorted(dom_keys - off_keys)[:12],
        "both": sorted(off_keys & dom_keys)[:12],
        "official_titles": [i.get("title") for i in official[:5]],
        "domestic_titles": [i.get("title") for i in domestic[:5]],
    }


def histogram(scores: Iterable[float | None], width: int = 20) -> list[dict[str, Any]]:
    """评分分布。看"堆在门槛附近的有多少"比看平均值有用得多。"""
    buckets = [{"lo": i, "hi": min(100, i + width), "n": 0} for i in range(0, 100, width)]
    total = 0
    for s in scores:
        if s is None:
            continue
        try:
            value = float(s)
        except (TypeError, ValueError):
            continue
        value = max(0.0, min(99.999, value))
        buckets[int(value // width)]["n"] += 1
        total += 1
    for b in buckets:
        b["pct"] = round(b["n"] / total, 3) if total else 0.0
    return buckets


def compute(payload: dict[str, Any], *, day: str | None = None) -> dict[str, Any]:
    """把当天状态压成一个可直接渲染的 dict。纯计算，不写盘。"""
    day = day or store.today_str()
    items = list(payload.get("items") or [])
    stats = payload.get("stats") or {}

    attention = [(i.get("extra") or {}).get("attention") or {} for i in items]
    scores = [a.get("score") for a in attention if a.get("available")]
    legacy = [(i.get("extra") or {}).get("score") for i in items]

    by_cat: dict[str, int] = {}
    for it in items:
        st = (it.get("extra") or {}).get("structure") or {}
        key = st.get("category") or "未结构化"
        by_cat[key] = by_cat.get(key, 0) + 1

    sources: list[dict[str, Any]] = []
    try:
        sources = store.source_rows()
    except Exception:
        pass
    alerts: list[dict[str, Any]] = []
    try:
        alerts = store.alerts_on(day)
    except Exception:
        pass
    llm_stats: dict[str, Any] = {}
    try:
        llm_stats = llm.stats(day)
    except Exception:
        pass

    return {
        "day": day,
        "generated_at": stats.get("generated_at") or datetime.now().isoformat(timespec="seconds"),
        "items": len(items),
        "new_today": stats.get("new_today", 0),
        "repeats": stats.get("repeats", 0),
        "events": (stats.get("events") or {}).get("events", 0),
        "daily": (stats.get("export") or {}).get("daily", 0),
        "sources_ok": stats.get("sources_ok", 0),
        "attention": {
            "scored": (stats.get("attention") or {}).get("scored", len(scores)),
            "selected": (stats.get("attention") or {}).get("selected", 0),
            "blocked": (stats.get("attention") or {}).get("blocked", 0),
            "failed": (stats.get("attention") or {}).get("failed", 0),
        },
        "histogram_attention": histogram(scores),
        "histogram_legacy": histogram([s for s in legacy if isinstance(s, (int, float))]),
        "categories": dict(sorted(by_cat.items(), key=lambda kv: -kv[1])),
        "discourse": discourse(items),
        "sources": sources,
        "alerts": alerts,
        "llm": llm_stats,
        "extract": stats.get("extract") or {},
    }


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #

def _card(label: str, value: Any, hint: str = "") -> str:
    return (f'<div class="card"><div class="k">{label}</div>'
            f'<div class="v">{value}</div>'
            f'<div class="h">{hint}</div></div>')


def _bars(rows: list[dict[str, Any]], label_key: str, value_key: str = "n") -> str:
    top = max([r.get(value_key) or 0 for r in rows] or [1]) or 1
    out = []
    for r in rows:
        n = r.get(value_key) or 0
        width = round(n / top * 100)
        out.append(
            f'<div class="bar"><span class="bl">{r.get(label_key)}</span>'
            f'<span class="bt"><i style="width:{width}%"></i></span>'
            f'<span class="bn">{n}</span></div>')
    return "".join(out)


def _override():
    from .theme import override_css
    return override_css()


def render(data: dict[str, Any]) -> str:
    from .share import og_tags

    a = data["attention"]
    hist = data["histogram_attention"]
    d = data["discourse"]
    llm_stats = data["llm"] or {}

    cards = '<div class="kpi">' + "".join([
        _card("今日条目", data["items"], f"新增 {data['new_today']} · 重复 {data['repeats']}"),
        _card("进日报", data["daily"], f"事件 {data['events']} 个"),
        _card("评分", f"{a['selected']}/{a['scored']}", f"过门槛 · 拦截 {a['blocked']} · 失败 {a['failed']}"),
        _card("模型调用", llm_stats.get("total", 0),
              f"命中回执 {llm_stats.get('hit', 0)} · token {llm_stats.get('tokens', 0)}"),
    ]) + '</div>' 

    hist_rows = [{"label": f"{b['lo']}–{b['hi']}", "n": b["n"], "pct": b["pct"]} for b in hist]

    # 分数分布环形图（纯 CSS conic-gradient，不引图表库）
    SEG = ("#b3402a", "#c9743a", "#b8873a", "#4c8c72", "#176b75")
    acc, stops = 0.0, []
    for i, b in enumerate(hist):
        start = acc
        acc = min(1.0, acc + float(b["pct"]))
        stops.append(f"{SEG[i % len(SEG)]} {start * 100:.2f}% {acc * 100:.2f}%")
    total_n = sum(int(b["n"]) for b in hist) or 1
    donut = (f'<div class="donut-wrap"><div class="donut" style="--seg:{", ".join(stops)}">'
             f'<div class="donut-c"><b>{total_n}</b><span>条 · 今日已评分</span></div></div>'
             '<div class="donut-legend">'
             + "".join(f'<span><i style="background:{SEG[i % len(SEG)]}"></i>'
                       f'{b["label"]} · {b["n"]} 条</span>'
                       for i, b in enumerate(hist_rows))
             + "</div></div>") if hist else ""
    hist_html = "".join(
        f'<div class="bar"><span class="bl">{b["label"]}</span>'
        f'<span class="bt"><i style="width:{round(b["pct"] * 100)}%"></i></span>'
        f'<span class="bn">{b["n"]}</span></div>' for b in hist_rows)

    cats = [{"label": k, "n": v} for k, v in data["categories"].items()]
    src_rows = [{"label": f'{s["source"]}',
                 "n": s.get("last_count") or 0,
                 "fails": s.get("fails") or 0,
                 "ok": s.get("last_ok") or ""} for s in data["sources"]]
    src_rows.sort(key=lambda r: (r["fails"], -r["n"]))

    def chips(keys: list[str]) -> str:
        return "".join(f'<span class="chip">{k}</span>' for k in keys) or '<span class="muted">—</span>'

    alerts_html = "".join(
        f'<li class="{"err" if x.get("severity") == "error" else ""}">{x.get("kind")} — {x.get("message")}</li>'
        for x in data["alerts"]) or '<li class="muted">今天没有告警</li>'

    page_css = """
/* 看板：所有区块给足纵向间距，标签允许换行，表格可横向滚动 —— 之前挤在一起是因为
   间距是按 14px/紧排版写的，换成 15px/1.65 和 20px 圆角后就贴到一起了。 */
.kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;
     margin:8px 0 10px}
.kpi .card{padding:16px 18px;margin:0;min-width:0}
.kpi .k{font-size:12px;color:var(--ink-4);letter-spacing:.02em}
.kpi .v{font:700 32px/1.15 var(--font-mono);color:var(--ink);letter-spacing:-.02em;
        margin:8px 0 4px;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.kpi .h{font-size:12px;color:var(--ink-4);line-height:1.5}

/* 环形分布：单独一张卡，图和图例分两列，互不压迫 */
.donut-wrap{display:grid;grid-template-columns:164px minmax(0,1fr);gap:40px;align-items:center;
            margin:10px 0 20px;padding:18px 20px;background:var(--surface);
            border:1px solid var(--line);border-radius:var(--r-card);box-shadow:var(--shadow-card)}
@media(max-width:720px){.donut-wrap{grid-template-columns:1fr;justify-items:center;gap:18px}}
.donut{width:164px;height:164px;border-radius:50%;position:relative;flex:none;
       justify-self:center;
       background:conic-gradient(var(--seg))}
.donut::after{content:"";position:absolute;inset:40px;border-radius:50%;
              background:var(--surface)}      /* 内圈跟卡片同色，不留白块 */
.donut-c{position:absolute;inset:0;display:grid;place-items:center;z-index:1;
         text-align:center;line-height:1.2;padding:0 14px;pointer-events:none}
.donut-c b{font:700 22px var(--font-mono);color:var(--ink);line-height:1.05}
.donut-c span{display:block;font-size:10.5px;color:var(--ink-4);margin-top:3px;
              letter-spacing:.02em}
.donut-legend{display:grid;gap:9px;font-size:13px;color:var(--ink-3);min-width:0;
              padding-left:4px}
.donut-legend span{display:flex;align-items:center;gap:9px}
.donut-legend i{flex:none;width:10px;height:10px;border-radius:3px}

/* 条形：标签定宽省略号，数值右对齐，条不自适应撑破 */
.bar{display:flex;align-items:center;gap:12px;margin:0 0 11px;font-size:13px}
.bar .bl{flex:0 0 104px;color:var(--ink-4);overflow:hidden;text-overflow:ellipsis;
         white-space:nowrap}
.bar .bt{flex:1;min-width:40px;height:8px;border-radius:999px;background:var(--bg-sunk);
         overflow:hidden}
.bar .bt i{display:block;height:100%;border-radius:999px;
           background:linear-gradient(90deg,#9a9af2,var(--accent))}
.bar .bn{flex:0 0 52px;text-align:right;font-family:var(--font-mono);color:var(--ink-3)}

/* 标签云：换行不重叠 */
.chip{display:inline-flex;align-items:center;margin:0 6px 7px 0;padding:3px 11px;
      border-radius:999px;background:var(--bg-sunk);color:var(--ink-3);font-size:12px;
      line-height:1.7;max-width:100%;overflow-wrap:anywhere}
.two{display:grid;grid-template-columns:1fr 1fr;gap:22px}
@media(max-width:720px){.two{grid-template-columns:1fr}}
.two > div{min-width:0}

/* 表格：小屏可横向滚，纵向给足行高 */
.page table{width:100%;border-collapse:collapse;font-size:13px;margin:4px 0 8px}
.page table th,.page table td{padding:9px 10px;border-bottom:1px solid var(--line-soft);
                              text-align:left;vertical-align:top}
.page table th{color:var(--ink-4);font-weight:600;font-size:12px}
.scroll{overflow-x:auto}
.axes{margin:6px 0 4px}
"""

    body = f"""<div class="cards">{cards}</div>

<h2>评分分布（五轴加权分，每 20 分一档）</h2>
{donut}{hist_html}
<div class="muted" style="font-size:11px;margin-top:6px;">
门槛在 config/scoring.yaml：primary 58 / rank 66 / broad 68 / search 74 / social 76。
堆在门槛附近的那一档，就是"最该拿去看错例"的样本。
</div>

<h2>内容分类</h2>
{_bars(cats, "label") if cats else '<span class="muted">今天没有结构化结果</span>'}

<h2>中文舆论场：官方发布 vs 国内讨论</h2>
<div class="two">
  <div>
    <div class="muted" style="font-size:12px;">海外官方一手（{d['official_items']} 条）</div>
    {chips(d['official_only'])}
  </div>
  <div>
    <div class="muted" style="font-size:12px;">国内社媒（{d['domestic_items']} 条）</div>
    {chips(d['domestic_only'])}
  </div>
</div>
<div style="margin-top:10px;">
  <div class="muted" style="font-size:12px;">两边都在说（{len(d['both'])} 个主体/标签）</div>
  {chips(d['both'])}
</div>
<div class="muted" style="font-size:11px;margin-top:8px;">
只在左边出现的，是"还没传进中文圈"的情报；只在右边出现的，是"中文圈在聊但官方没动静"。
</div>

<h2>模型调用</h2>
<div class="muted" style="font-size:12px;">
共 {llm_stats.get('total', 0)} 次 · 命中回执 {llm_stats.get('hit', 0)}
（{float(llm_stats.get('hit_rate') or 0):.0%}） · token {llm_stats.get('tokens', 0)}
<br>回执命中 = 同一输入复用，不花钱也不等待。按状态：
{llm_stats.get('by_state') or '—'}
</div>

<h2>信源健康</h2>
<table><tr><th>信源</th><th>本轮条数</th><th>连续失败</th><th>最近成功</th></tr>
{''.join(f'<tr><td>{r["label"]}</td><td>{r["n"]}</td><td style="color:{"#f87171" if r["fails"] else "#6b7785"}">{r["fails"]}</td><td class="muted">{r["ok"]}</td></tr>' for r in src_rows)}
</table>

<h2>告警</h2>
<ul>{alerts_html}</ul>

<div class="muted" style="font-size:11px;margin-top:30px;">
本页由 collector/board.py 生成，不读写业务数据；反馈与设置请改 config/*.yaml。
</div>"""

    return theme.page(f"看板 · {data['day']}", body, active="/board.html",
                      lead="源健康、评分分布、模型成本、官方与国内舆论场",
                      extra_css=page_css)



def _nav():
    from .theme import bottom_nav, nav_html
    return nav_html("/board.html") + bottom_nav("/board.html")


def build(payload: dict[str, Any], site_root: Path | None = None) -> dict[str, Any]:
    """写 `site/board.html`。失败不影响主流程。"""
    data = compute(payload)
    target = (site_root or SITE) / "board.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(data), encoding="utf-8")
    return {"file": str(target), "items": data["items"], "alerts": len(data["alerts"]),
            "discourse": {"official": data["discourse"]["official_items"],
                          "domestic": data["discourse"]["domestic_items"]}}
