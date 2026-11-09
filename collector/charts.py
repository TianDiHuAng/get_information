"""纯 SVG 图表：渲染期在 Python 里生成，零外部依赖。

页面要在无外网、无代理的环境也能打开，所以不引任何图表库 / CDN。
配色与 render.py 的深色主题保持一致（LAYER_* 为唯一定义处）。
"""

from __future__ import annotations

import math

LAYER_LABEL = {"primary": "一手", "rank": "榜单", "broad": "广谱", "search": "搜索", "social": "社媒"}
LAYER_COLOR = {"primary": "#f472b6", "rank": "#f59e0b", "broad": "#38bdf8", "search": "#a78bfa", "social": "#34d399"}

INK = "#e6edf3"    # 主文字
MUTED = "#8b98a5"  # 次要文字
FAINT = "#6b7785"  # 弱文字 / 占位
TRACK = "#131c27"  # 条形图底槽
GRID = "#1a2331"   # 轴线
ACCENT = "#38bdf8"
GOOD = "#34d399"
PINK = "#f472b6"

# 所有图表统一 viewBox 高度，保证面板网格里视觉齐平
CHART_W, CHART_H = 320, 220


def _svg(body: str) -> str:
    return (
        f'<svg viewBox="0 0 {CHART_W} {CHART_H}" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" preserveAspectRatio="xMidYMid meet">{body}</svg>'
    )


def _placeholder(lines: list[str]) -> str:
    parts = []
    for i, msg in enumerate(lines):
        dy = 0 if len(lines) == 1 else (i - (len(lines) - 1) / 2) * 20
        parts.append(
            f'<text x="{CHART_W / 2}" y="{CHART_H / 2 + dy}" text-anchor="middle" '
            f'fill="{FAINT}" font-size="{11 if i else 12}">{msg}</text>'
        )
    return _svg("".join(parts))


def donut(by_layer: dict, topic_n: int, total: int) -> str:
    """层级分布环形图，中心显示总数与 AI 相关条数。"""
    cx, cy, r = 82, CHART_H / 2, 68
    circ = 2 * math.pi * r
    order = ("primary", "rank", "broad", "search", "social")
    segs = [(k, int(by_layer.get(k, 0))) for k in order]
    segs = [(k, n) for k, n in segs if n > 0]
    if not segs or total <= 0:
        return _placeholder(["暂无数据"])

    rings, offset = [], 0.0
    for k, n in segs:
        dash = n / sum(v for _, v in segs) * circ
        rings.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{LAYER_COLOR[k]}" stroke-width="16"'
            f' stroke-dasharray="{dash:.2f} {circ - dash:.2f}" stroke-dashoffset="{-offset:.2f}"'
            f' transform="rotate(-90 {cx} {cy})" />'
        )
        offset += dash
    center = (
        f'<text x="{cx}" y="{cy + 1}" text-anchor="middle" fill="{INK}" font-size="24" font-weight="650">{total}</text>'
        f'<text x="{cx}" y="{cy + 21}" text-anchor="middle" fill="{PINK}" font-size="10">AI 相关 {topic_n}</text>'
    )
    lx, ly, step = 172, cy - (len(segs) - 1) * 13, 26
    legend = []
    for k, n in segs:
        legend.append(
            f'<rect x="{lx}" y="{ly - 8}" width="10" height="10" rx="3" fill="{LAYER_COLOR[k]}" />'
            f'<text x="{lx + 16}" y="{ly}" fill="{MUTED}" font-size="11">{LAYER_LABEL[k]} {n}</text>'
        )
        ly += step
    return _svg("".join(rings) + center + "".join(legend))


def hbar(per_source: dict, layer_of: dict, labels: dict | None = None) -> str:
    """各源条目数横向条形图，条形颜色随该源所在层级。"""
    rows = sorted(per_source.items(), key=lambda kv: kv[1], reverse=True)[:11]
    if not rows:
        return _placeholder(["暂无数据"])
    label_w, value_w, row_h, bar_h = 92, 36, 19, 11
    plot_w = CHART_W - label_w - value_w
    top = max(v for _, v in rows) or 1
    out, y = [], 12
    for sid, n in rows:
        name = (labels or {}).get(sid, sid)
        color = LAYER_COLOR.get(layer_of.get(sid, ""), ACCENT)
        bw = max(2.0, n / top * plot_w)
        out.append(
            f'<text x="{label_w - 10}" y="{y + bar_h - 2}" text-anchor="end" fill="{MUTED}" font-size="11">{name}</text>'
            f'<rect x="{label_w}" y="{y}" width="{plot_w}" height="{bar_h}" rx="3" fill="{TRACK}" />'
            f'<rect x="{label_w}" y="{y}" width="{bw:.1f}" height="{bar_h}" rx="3" fill="{color}" />'
            f'<text x="{CHART_W - 4}" y="{y + bar_h - 2}" text-anchor="end" fill="{FAINT}" font-size="10">{n}</text>'
        )
        y += row_h
    return _svg("".join(out))


def timeline(items: list[dict]) -> str:
    """近 72h 发布节奏，6h 一桶，旧在左新在右。"""
    bucket_h, hours = 6, 72
    nb = hours // bucket_h
    buckets = [0] * nb
    for it in items:
        age = (it.get("extra") or {}).get("age_h")
        if age is None:
            continue
        b = int(age // bucket_h)
        if 0 <= b < nb:
            buckets[b] += 1
    buckets.reverse()  # bucket 0 原本是最新，翻转让时间从左往右流动

    pad_t, pad_b = 16, 20
    pad_l = pad_r = 8
    plot_w, plot_h = CHART_W - pad_l - pad_r, CHART_H - pad_t - pad_b
    top = max(buckets) or 1
    gap = 6
    bw = plot_w / nb - gap
    base_y = pad_t + plot_h
    out = [f'<line x1="{pad_l}" y1="{base_y}" x2="{CHART_W - pad_r}" y2="{base_y}" stroke="{GRID}" />']
    for i, v in enumerate(buckets):
        bh = v / top * (plot_h - 14)
        x = pad_l + i * (plot_w / nb)
        if v:
            out.append(
                f'<rect x="{x:.1f}" y="{base_y - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="3" '
                f'fill="{ACCENT}" opacity="0.85" />'
                f'<text x="{x + bw / 2:.1f}" y="{base_y - bh - 4:.1f}" text-anchor="middle" '
                f'fill="{MUTED}" font-size="9">{v}</text>'
            )
    for i, cap in ((0, "-72h"), (nb // 3, "-48h"), (2 * nb // 3, "-24h"), (nb - 1, "现在")):
        x = pad_l + i * (plot_w / nb) + bw / 2
        out.append(
            f'<text x="{x:.1f}" y="{CHART_H - 4}" text-anchor="middle" fill="{FAINT}" font-size="10">{cap}</text>'
        )
    return _svg("".join(out))


def trend(rows: list[dict]) -> str:
    """近 7 天趋势：条目数 + 可用源数两条折线。不足 2 天先占位。"""
    rows = [r for r in rows if r.get("date")]
    if len(rows) < 2:
        msg = f"已积累 {len(rows)} 天数据" if rows else "还没有历史数据"
        return _placeholder([msg, "趋势图从第 2 天开始绘制"])

    pad_t, pad_b, pad_l, pad_r = 24, 20, 8, 8
    plot_w, plot_h = CHART_W - pad_l - pad_r, CHART_H - pad_t - pad_b
    base_y = pad_t + plot_h
    n = len(rows)

    def series(key: str) -> list[tuple[float, float, int]]:
        vals = [int(r.get(key) or 0) for r in rows]
        top = max(vals) or 1
        pts = []
        for i, v in enumerate(vals):
            x = pad_l + plot_w * (i / (n - 1))
            y = base_y - (v / top) * (plot_h - 10) - 2
            pts.append((x, y, v))
        return pts

    out = [f'<line x1="{pad_l}" y1="{base_y}" x2="{CHART_W - pad_r}" y2="{base_y}" stroke="{GRID}" />']
    for pts, color in ((series("raw"), ACCENT), (series("sources_ok"), GOOD)):
        pl = " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in pts)
        out.append(f'<polyline points="{pl}" fill="none" stroke="{color}" stroke-width="2" />')
        for x, y, v in pts:
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}" />')
        # 数值只标最后一个点，避免两条线的标签互相打架
        x, y, v = pts[-1]
        out.append(
            f'<text x="{min(x, CHART_W - 16):.1f}" y="{y - 8:.1f}" text-anchor="middle" '
            f'fill="{color}" font-size="10" font-weight="600">{v}</text>'
        )
    for i, r in enumerate(rows):
        x = pad_l + plot_w * (i / (n - 1))
        out.append(
            f'<text x="{x:.1f}" y="{CHART_H - 4}" text-anchor="middle" fill="{FAINT}" font-size="9">'
            f'{r["date"][5:]}</text>'
        )
    legend = (
        f'<circle cx="14" cy="10" r="3.5" fill="{ACCENT}" /><text x="22" y="14" fill="{MUTED}" font-size="10">条目</text>'
        f'<circle cx="64" cy="10" r="3.5" fill="{GOOD}" /><text x="72" y="14" fill="{MUTED}" font-size="10">可用源</text>'
    )
    return _svg("".join(out) + legend)


def panel_grid(items: list[dict], stats: dict, history: list[dict] | None = None,
               source_labels: dict | None = None) -> str:
    """把四张图拼成仪表盘区块，由 render.py 插到统计与“今日必看”之间。"""
    topic_n = sum(1 for it in items if (it.get("extra") or {}).get("topic"))
    layer_of = {s.get("id"): s.get("layer", "broad") for s in stats.get("registry", [])}
    panels = [
        ("条目层级分布", donut(stats.get("by_layer", {}), topic_n, len(items))),
        ("各源条目数", hbar(stats.get("per_source", {}), layer_of, labels=source_labels)),
        ("近 72h 发布节奏", timeline(items)),
        ("近 7 天趋势", trend(history or [])),
    ]
    cells = "".join(f'<div class="panel"><h2>{title}</h2>{svg}</div>' for title, svg in panels)
    return f'<section class="charts">{cells}</section>'
