from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

from .charts import LAYER_COLOR, LAYER_LABEL, panel_grid

SOURCE_CN = {
    "smolai": "smol.ai", "thebatch": "The Batch", "hf_papers": "HF Papers", "arxiv": "arXiv",
    "hackernews": "Hacker News", "github": "GitHub", "bilibili": "B站", "toutiao": "头条",
    "kr36": "36氪", "sspai": "少数派", "google_news": "Google News",
}


def _ago(iso: str) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso)
        now = datetime.now(dt.tzinfo)
        mins = int((now - dt).total_seconds() // 60)
    except Exception:
        return ""
    if mins < 1:
        return "刚刚"
    if mins < 60:
        return f"{mins} 分钟前"
    if mins < 1440:
        return f"{mins // 60} 小时前"
    return f"{mins // 1440} 天前"


def _fmt_heat(v) -> str:
    if not v:
        return ""
    return f"{int(v):,}"


def render(payload: dict, out_path: Path, history: list[dict] | None = None,
           lmarena: dict | None = None, aa: dict | None = None) -> Path:
    items = payload["items"]
    # 续跑或旧状态文件里可能缺字段：补齐再画，缺了就少画一块，不要整页崩掉
    from .state import ensure_stats

    stats = ensure_stats(payload.get("stats"), items=len(items))
    registry = stats.get("registry") or []

    from .health import status_of

    health = stats.get("health") or {}
    chips = []
    for s in registry:
        if s["enabled"]:
            label, cls = status_of(s["id"], health)
        else:
            label, cls = s["status"], "off"
        chips.append(
            f'<span class="chip {cls}" title="{html.escape(s["access"])} · {html.escape(label)}">'
            f'{html.escape(s["name"])}<b>{html.escape(label)}</b></span>'
        )

    layers_present = [k for k in ("primary", "rank", "search", "broad", "social") if stats["by_layer"].get(k)]
    topic_n = sum(1 for i in items if i["extra"].get("topic"))
    filters = ['<button class="f active" data-f="all">全部 %d</button>' % len(items)]
    if topic_n:
        filters.append(f'<button class="f" data-f="topic" style="--c:#f472b6">AI 相关 {topic_n}</button>')
    deal_n = sum(1 for i in items if i["extra"].get("deal"))
    if deal_n:
        filters.append(f'<button class="f" data-f="deal" style="--c:#f59e0b">羊毛福利 {deal_n}</button>')
    by_region = stats.get("by_region") or {}
    filters.append(f'<button class="f" data-f="overseas">国外 {by_region.get("overseas", 0)}</button>')
    filters.append(f'<button class="f" data-f="domestic">国内 {by_region.get("domestic", 0)}</button>')
    for k in layers_present:
        filters.append(
            f'<button class="f" data-f="{k}" style="--c:{LAYER_COLOR[k]}">'
            f"{LAYER_LABEL[k]} {stats['by_layer'][k]}</button>"
        )

    cards_by_region: dict[str, list[str]] = {"overseas": [], "domestic": []}
    for it in items:
        layer = it["layer"]
        color = LAYER_COLOR.get(layer, "#94a3b8")
        tags = [it["source"]]
        for extra in it.get("extra", {}).get("also", []):
            tags.append(f"+{extra}")
        tag_html = "".join(f'<span class="tag">{html.escape(t)}</span>' for t in tags)
        heat = _fmt_heat(it.get("heat"))
        heat_html = f'<span class="heat">🔥 {heat}</span>' if heat else ""
        summary = html.escape(it.get("summary") or "")
        _orig = it["extra"].get("title_original")
        tip_html = f' title="{html.escape(_orig, quote=True)}"' if _orig else ""
        cards_by_region.setdefault(it.get("region", "overseas"), []).append(
            f"""
      <a class="card" data-region="{it.get('region', 'overseas')}" data-deal="{1 if it['extra'].get('deal') else 0}" data-layer="{layer}" data-topic="{1 if it['extra'].get('topic') else 0}" data-source="{html.escape(it['source'])}" href="{html.escape(it['url'])}" target="_blank" rel="noopener"{tip_html}>
        <div class="bar" style="background:{color}"></div>
        <div class="body">
          <div class="meta">
            <span class="badge" style="color:{color};border-color:{color}33;background:{color}14">{LAYER_LABEL.get(layer, layer)}</span>
            {tag_html}
            {'<span class="badge" style="color:#f472b6;border-color:#f472b633;background:#f472b614">AI</span>' if it['extra'].get('topic') else ''}
            {'<span class="badge" style="color:#f59e0b;border-color:#f59e0b33;background:#f59e0b14">羊毛</span>' if it['extra'].get('deal') else ''}
            <span class="time">{_ago(it.get('published'))}</span>
          </div>
          <h3>{html.escape(it['title'])}</h3>
          <p>{summary}</p>
          <div class="foot">{heat_html}<span class="score">权重 {it['extra'].get('score', 0)}</span><span class="fb" data-kind="up" data-url="{html.escape(it['url'], quote=True)}" title="有用：以后多推这类">👍</span><span class="fb" data-kind="down" data-url="{html.escape(it['url'], quote=True)}" title="没用：以后少推这类">👎</span></div>
        </div>
      </a>"""
        )

    zones = []
    for key, title, sub in (
        ("overseas", "国外 · 一手与社区", "Horizon 式渠道：论文 / HN / GitHub / X / 长文分析"),
        ("domestic", "国内 · 热榜与媒体", "TrendRadar 式渠道：热榜与科技媒体"),
    ):
        group = cards_by_region.get(key) or []
        if not group:
            continue
        zones.append(
            f'\n  <section class="zone" data-zone="{key}">'
            f'<h2>{title}<span>{len(group)} 条</span></h2>'
            f'<p class="zone-sub">{sub}</p><div class="grid">{"".join(group)}</div></section>'
        )
    zones_html = "".join(zones)

    charts_html = panel_grid(items, stats, history, source_labels=SOURCE_CN)

    lmarena_html = ""
    if lmarena and lmarena.get("models"):
        from .leaderboards import change_of

        rows = "".join(
            f'<tr><td class="r">{m["rank"]}</td><td class="c" style="color:{color}">{ch}</td>'
            f'<td class="m">{html.escape(m["model"])}</td><td class="o">{html.escape(m["org"])}</td>'
            f'<td class="s">{m["rating"]}</td></tr>'
            for m in lmarena["models"]
            for ch, color in [change_of(m)]
        )
        lmarena_html = (
            f'<section class="panel lmx"><h2>LMArena 总榜 Top {len(lmarena["models"])} · 数据 {lmarena["date"]}</h2>'
            f'<table><thead><tr><th>排名</th><th>变化</th><th>模型</th><th>组织</th><th class="s">评分</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></section>'
        )

    aa_html = ""
    if aa and aa.get("models"):
        from .leaderboards import change_of, price_change_of

        rows = []
        for m in aa["models"]:
            ch, color = change_of(m)
            pc = price_change_of(m)
            price = "—" if m.get("price_out") is None else f'${m["price_out"]:.2f}'
            if pc:
                price += f' <span style="color:#34d399">{pc}</span>'
            rows.append(
                f'<tr><td class="r">{m["rank"]}</td><td class="c" style="color:{color}">{ch}</td>'
                f'<td class="m">{html.escape(m["model"])}</td><td class="o">{html.escape(m["org"])}</td>'
                f'<td class="s">{m["intelligence"]}</td><td class="s">{price}</td></tr>'
            )
        aa_html = (
            f'<section class="panel lmx"><h2>AA 智能指数 Top {len(aa["models"])} · 快照 {aa["date"]}</h2>'
            f'<table><thead><tr><th>排名</th><th>变化</th><th>模型</th><th>组织</th>'
            f'<th class="s">智能指数</th><th class="s">输出价 $/1M</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></section>'
        )

    _hero_pool = [x for x in items if x.get("region") == "overseas"] or items
    hero_pool = sorted(
        _hero_pool, key=lambda x: (bool(x["extra"].get("topic")), x["extra"].get("score", 0)), reverse=True
    )[:5]
    hero = []
    for i, it in enumerate(hero_pool, 1):
        hero.append(
            f'<a class="hero-item" href="{html.escape(it["url"])}" target="_blank" rel="noopener">'
            f'<span class="num">{i:02d}</span>'
            f'<span class="ht">{html.escape(it["title"])}</span>'
            f'<span class="hs">{html.escape(SOURCE_CN.get(it["source"], it["source"]))}</span></a>'
        )

    doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>信息雷达 · {stats['generated_at'][:16]}</title>
<link rel="alternate" type="application/rss+xml" title="信息雷达 · 今日要闻" href="/feed.xml">
<link rel="alternate" type="application/rss+xml" title="信息雷达 · 全部动态" href="/feed-all.xml">
<link rel="alternate" type="application/json" title="结构化数据" href="/api/v1/latest.json">
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:#0b0f14; color:#e6edf3;
         font:15px/1.6 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }}
  .wrap {{ max-width:1180px; margin:0 auto; padding:40px 20px 80px; }}
  header h1 {{ font-size:30px; margin:0 0 6px; letter-spacing:-.5px; }}
  header .sub {{ color:#8b98a5; font-size:13px; }}
  .stats {{ display:flex; gap:26px; margin:24px 0 8px; flex-wrap:wrap; }}
  .stat b {{ display:block; font-size:24px; font-weight:650; }}
  .stat span {{ color:#8b98a5; font-size:12px; }}
  .coverage {{ display:flex; gap:8px; flex-wrap:wrap; margin:18px 0 26px; }}
  .charts {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(255px,1fr)); gap:14px;
             margin:26px 0 22px; }}
  .panel {{ background:#0f151d; border:1px solid #1a2331; border-radius:12px; padding:14px 16px 10px; }}
  .panel h2 {{ font-size:13px; color:#7d8b99; font-weight:600; letter-spacing:.08em; margin:0 0 6px; }}
  .panel svg {{ display:block; width:100%; height:auto; }}
  .panel svg text {{ font-family:inherit; }}
  .lmx {{ margin:0 0 22px; }}
  .lmx table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  .lmx th {{ text-align:left; color:#5f6b78; font-weight:500; font-size:11px;
             padding:4px 10px; border-bottom:1px solid #1a2331; }}
  .lmx th.s {{ text-align:right; }}
  .lmx td {{ padding:7px 10px; border-bottom:1px solid #141d29; }}
  .lmx td.r {{ color:#8b98a5; width:60px; font-variant-numeric:tabular-nums; }}
  .lmx td.c {{ width:70px; font-variant-numeric:tabular-nums; }}
  .lmx td.m {{ font-weight:600; }}
  .lmx td.o {{ color:#8b98a5; }}
  .lmx td.s {{ color:#e6edf3; font-variant-numeric:tabular-nums; text-align:right; width:90px; }}
  .chip {{ font-size:12px; padding:5px 10px; border-radius:999px; border:1px solid #1f2937;
           background:#111823; color:#9aa7b4; display:inline-flex; gap:6px; align-items:center; }}
  .chip b {{ font-weight:500; color:#5f6b78; font-size:11px; }}
  .chip.on {{ border-color:#1d4d3a; background:#0d1f19; color:#a7f3d0; }}
  .chip.on b {{ color:#34d399; }}
  .chip.off {{ opacity:.55; }}
  .filters {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:18px; }}
  .f {{ cursor:pointer; border:1px solid #1f2937; background:#0f151d; color:#9aa7b4;
        padding:6px 14px; border-radius:8px; font-size:13px; }}
  .f:hover {{ border-color:#374151; color:#e6edf3; }}
  .f.active {{ background:#e6edf3; color:#0b0f14; border-color:#e6edf3; font-weight:600; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(340px,1fr)); gap:14px; }}
  .zone {{ margin-bottom:8px; }}
  .zone h2 {{ font-size:17px; margin:30px 0 2px; display:flex; align-items:baseline; gap:10px; }}
  .zone h2 span {{ font-size:12px; color:#6b7785; font-weight:400; }}
  .zone-sub {{ margin:0 0 14px; color:#5f6b78; font-size:12px; }}
  .card {{ position:relative; display:flex; background:#0f151d; border:1px solid #1a2331;
           border-radius:12px; overflow:hidden; text-decoration:none; color:inherit;
           transition:border-color .15s, transform .15s; }}
  .card:hover {{ border-color:#2f3d50; transform:translateY(-2px); }}
  .bar {{ width:3px; flex:0 0 3px; }}
  .body {{ padding:14px 16px; display:flex; flex-direction:column; gap:8px; min-width:0; }}
  .meta {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; font-size:11px; }}
  .badge {{ border:1px solid; padding:1px 7px; border-radius:6px; }}  .tag {{ color:#6b7785; }}
  .time {{ margin-left:auto; color:#6b7785; }}
  h3 {{ margin:0; font-size:15px; line-height:1.45; font-weight:600; }}
  p {{ margin:0; color:#8b98a5; font-size:12.5px; display:-webkit-box; -webkit-line-clamp:2;
       -webkit-box-orient:vertical; overflow:hidden; }}
  .foot {{ display:flex; gap:12px; align-items:center; font-size:11px; color:#6b7785; margin-top:auto; }}
  .score {{ margin-left:auto; }}
  /* 反馈按钮：点一下就记，不用登录也不用刷新 */
  .fb {{ cursor:pointer; opacity:.35; font-size:13px; line-height:1; padding:2px 4px; border-radius:5px;
         user-select:none; transition:opacity .15s, background .15s; }}
  .fb:hover {{ opacity:.9; background:#ffffff14; }}
  .fb.on {{ opacity:1; background:#22c55e26; }}
  .hero {{ background:linear-gradient(135deg,#101a26,#0d141d); border:1px solid #1d2a3a;
           border-radius:14px; padding:6px 18px; margin-bottom:22px; }}
  .hero h2 {{ font-size:13px; color:#7d8b99; font-weight:600; letter-spacing:.08em; margin:14px 0 6px; }}
  .hero-item {{ display:flex; gap:12px; align-items:baseline; padding:9px 0; text-decoration:none;
                color:inherit; border-bottom:1px solid #16202c; }}
  .hero-item:last-child {{ border-bottom:0; }}
  .hero-item:hover .ht {{ color:#7dd3fc; }}
  .num {{ color:#3b4b5e; font-variant-numeric:tabular-nums; font-size:12px; }}
  .ht {{ font-size:14.5px; font-weight:600; flex:1; }}
  .hs {{ color:#5f6b78; font-size:11px; white-space:nowrap; }}
  .chip.bad {{ border-color:#5c1f1f; background:#1d0f0f; color:#fca5a5; }}
  .chip.bad b {{ color:#ef4444; }}
  .chip.warn {{ border-color:#5c441f; background:#1d160f; color:#fcd34d; }}
  .chip.warn b {{ color:#f59e0b; }}
  footer {{ margin-top:40px; color:#4b5563; font-size:12px; }}
  @media (max-width:520px) {{ .grid {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>信息雷达</h1>
    <div class="sub">生成于 {stats['generated_at'][:19].replace('T', ' ')} · 每 {len(registry)} 个源中已启用 {sum(1 for s in registry if s['enabled'])} 个 · 代理 {('可用' if stats.get('proxy_ok') else '不可用')}</div>
    <div class="stats">
      <div class="stat"><b>{len(items)}</b><span>去重后条目</span></div>
      <div class="stat"><b>{(stats.get('by_region') or {}).get('overseas', 0)}</b><span>国外</span></div>
      <div class="stat"><b>{(stats.get('by_region') or {}).get('domestic', 0)}</b><span>国内</span></div>
      <div class="stat"><b>{stats['sources_ok']}</b><span>本次可用源</span></div>
      <div class="stat"><b>{len(stats['errors'])}</b><span>失败源</span></div>
    </div>
    <div class="coverage">{''.join(chips)}</div>
  </header>
  {charts_html}
  {lmarena_html}
  {aa_html}
  <section class="hero">
    <h2>今日必看</h2>
    {''.join(hero)}
  </section>
  <div class="filters">{''.join(filters)}</div>
  {zones_html}
  <footer>覆盖层级：榜单 = 热度信号 · 广谱 = 稳定订阅 · 搜索 = 长尾兜底 · 社媒 = 人。悬停源标签可看通道与状态 · <a href="/board.html" style="color:#7dd3fc;text-decoration:none;">运行看板 →</a> · <a href="/timeline.html" style="color:#7dd3fc;text-decoration:none;">时间线 →</a> · <a href="/archive/" style="color:#7dd3fc;text-decoration:none;">历史归档 →</a></footer>
</div>
<script>
const cards = [...document.querySelectorAll('.card')];
const zones = [...document.querySelectorAll('.zone')];
function apply(f) {{
  cards.forEach(c => {{
    let ok;
    if (f === 'all') ok = true;
    else if (f === 'topic') ok = c.dataset.topic === '1';
    else if (f === 'deal') ok = c.dataset.deal === '1';
    else if (f === 'overseas' || f === 'domestic') ok = c.dataset.region === f;
    else ok = c.dataset.layer === f;
    c.style.display = ok ? '' : 'none';
  }});
  zones.forEach(z => {{
    const any = [...z.querySelectorAll('.card')].some(c => c.style.display !== 'none');
    z.style.display = any ? '' : 'none';
  }});
}}
document.querySelectorAll('.f').forEach(btn => btn.addEventListener('click', () => {{
  document.querySelectorAll('.f').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  apply(btn.dataset.f);
}}));
// 反馈：卡片是 <a>，必须拦住跳转，否则点一下按钮就打开了原文
document.addEventListener('click', (e) => {{
  const el = e.target.closest('.fb');
  if (!el) return;
  e.preventDefault();
  e.stopPropagation();
  const url = el.dataset.url, kind = el.dataset.kind;
  fetch('/api/feedback', {{
    method: 'POST',
    headers: {{ 'content-type': 'application/json' }},
    body: JSON.stringify({{ url: url, kind: kind }})
  }}).then(r => r.json()).then(j => {{
    if (!j.ok) return;
    const card = el.closest('.card');
    card.querySelectorAll('.fb').forEach(b => b.classList.remove('on'));
    el.classList.add('on');
  }}).catch(() => {{}});
}});
</script>
</body>
</html>"""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    return out_path
