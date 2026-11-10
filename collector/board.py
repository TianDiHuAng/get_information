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

from . import llm, store

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


def render(data: dict[str, Any]) -> str:
    a = data["attention"]
    hist = data["histogram_attention"]
    d = data["discourse"]
    llm_stats = data["llm"] or {}

    cards = "".join([
        _card("今日条目", data["items"], f"新增 {data['new_today']} · 重复 {data['repeats']}"),
        _card("进日报", data["daily"], f"事件 {data['events']} 个"),
        _card("评分", f"{a['selected']}/{a['scored']}", f"过门槛 · 拦截 {a['blocked']} · 失败 {a['failed']}"),
        _card("模型调用", llm_stats.get("total", 0),
              f"命中回执 {llm_stats.get('hit', 0)} · token {llm_stats.get('tokens', 0)}"),
    ])

    hist_rows = [{"label": f"{b['lo']}–{b['hi']}", "n": b["n"], "pct": b["pct"]} for b in hist]
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

    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>信息雷达 · 看板 {data['day']}</title>
<style>
:root {{ color-scheme: dark; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:#0b0f14; color:#e6edf3; font:14px/1.6 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }}
.wrap {{ max-width:1080px; margin:0 auto; padding:28px 18px 60px; }}
h1 {{ font-size:19px; margin:0 0 4px; }}
.sub {{ color:#6b7785; font-size:12px; margin-bottom:22px; }}
a {{ color:#7dd3fc; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:12px; margin-bottom:26px; }}
.card {{ background:#111820; border:1px solid #1f2a37; border-radius:10px; padding:14px 16px; }}
.k {{ color:#8b98a8; font-size:12px; }}
.v {{ font-size:24px; font-weight:700; letter-spacing:.3px; margin:2px 0 2px; }}
.h {{ color:#6b7785; font-size:11px; }}
h2 {{ font-size:14px; color:#b7c3d0; margin:26px 0 10px; padding-bottom:6px; border-bottom:1px solid #1f2a37; }}
.bar {{ display:flex; align-items:center; gap:10px; margin:5px 0; font-size:12px; }}
.bl {{ width:64px; color:#8b98a8; flex:none; }}
.bt {{ flex:1; background:#151d26; border-radius:4px; height:14px; overflow:hidden; }}
.bt i {{ display:block; height:100%; background:linear-gradient(90deg,#2563eb,#22c55e); }}
.bn {{ width:44px; text-align:right; color:#8b98a8; flex:none; }}
.chip {{ display:inline-block; background:#16202b; border:1px solid #22303d; color:#9fb0c0;
        border-radius:999px; padding:1px 9px; font-size:11px; margin:2px 4px 2px 0; }}
.two {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
@media (max-width:760px) {{ .two {{ grid-template-columns:1fr; }} }}
ul {{ margin:6px 0; padding-left:18px; }}
li.err {{ color:#f87171; }}
.muted {{ color:#6b7785; }}
table {{ width:100%; border-collapse:collapse; font-size:12px; }}
th,td {{ text-align:left; padding:5px 8px; border-bottom:1px solid #18212b; }}
th {{ color:#6b7785; font-weight:500; }}
</style></head><body><div class="wrap">
<h1>信息雷达 · 看板</h1>
<div class="sub">{data['day']} · 生成于 {data['generated_at']} · <a href="/">回到今日要闻</a></div>

<div class="cards">{cards}</div>

<h2>评分分布（五轴加权分，每 20 分一档）</h2>
{hist_html}
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
</div>
</div></body></html>"""


def build(payload: dict[str, Any], site_root: Path | None = None) -> dict[str, Any]:
    """写 `site/board.html`。失败不影响主流程。"""
    data = compute(payload)
    target = (site_root or SITE) / "board.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(data), encoding="utf-8")
    return {"file": str(target), "items": data["items"], "alerts": len(data["alerts"]),
            "discourse": {"official": data["discourse"]["official_items"],
                          "domestic": data["discourse"]["domestic_items"]}}
