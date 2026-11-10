"""全站视觉：一套「纸感编辑风」，所有页面共用。

为什么单独一个模块：之前每个页面各自内联一份 CSS，配色和字号各写一遍 ——
加一个页面就要抄一次，抄错就花。这里只留一套 token 和几个组件类：

- 顶部导航（桌面）+ 底部导航（手机）
- 卡片、标签、分数条、五轴条、反馈按钮
- 纸底 + 衬线标题（日报/周刊的阅读感），无外部字体与图片

旧页面（首页 / 看板 / 时间线 / 主题 / 离线）是深色的，用 `override_css()`
在它们自己的样式后面追加一段覆盖，换到同一套配色 —— 不改它们的结构。
"""

from __future__ import annotations

import html
from typing import Any

# 站点导航：顺序就是阅读顺序
NAV = (
    ("/", "精选"),
    ("/all.html", "全部"),
    ("/hot.html", "热门"),
    ("/topics.html", "主题"),
    ("/daily.html", "日报"),
    ("/weekly.html", "周报"),
    ("/monthly.html", "月报"),
    ("/timeline.html", "时间线"),
    ("/search.html", "搜索"),
)
# 次级入口，放页脚与"更多"页
MORE = (
    ("/agent.html", "给 Agent 用"),
    ("/admin.html", "后台"),
    ("/board.html", "运行看板"),
    ("/archive/", "历史归档"),
    ("/offline.html", "离线版"),
    ("/starred.html", "我的收藏"),
    ("/feedback.html", "反馈"),
    ("/about.html", "关于"),
    ("/terms.html", "使用条款"),
    ("/privacy.html", "隐私"),
    ("/changelog.html", "更新日志"),
)

CSS = """
:root {
  --paper:#f6f1e7; --card:#fffdf7; --ink:#1c1a16; --muted:#6f6759; --rule:#e2d8c6;
  --accent:#b4530a; --accent-soft:#f3e0cd; --teal:#0f6b5c; --warn:#9a3412;
  --shadow:0 1px 2px rgba(28,26,22,.05), 0 8px 24px -18px rgba(28,26,22,.35);
  --serif:"Iowan Old Style","Palatino Linotype",Georgia,"Songti SC","Noto Serif CJK SC",serif;
  --sans:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.75 var(--sans)}
a{color:var(--accent);text-decoration:none;text-underline-offset:2px}
a:hover{text-decoration:underline}
.shell{max-width:900px;margin:0 auto;padding:0 20px 96px}
/* —— 顶部导航 —— */
.nav{position:sticky;top:0;z-index:20;background:rgba(246,241,231,.94);
     backdrop-filter:blur(8px);border-bottom:1px solid var(--rule)}
.nav .in{max-width:900px;margin:0 auto;display:flex;gap:16px;align-items:center;
         padding:12px 20px;overflow-x:auto;scrollbar-width:none}
.nav .in::-webkit-scrollbar{display:none}
.nav .brand{font-family:var(--serif);font-size:18px;font-weight:700;letter-spacing:.02em;
            color:var(--ink);margin-right:6px;white-space:nowrap}
.nav a{font-size:14px;color:var(--muted);white-space:nowrap}
.nav a.on{color:var(--ink);font-weight:600;box-shadow:inset 0 -2px 0 var(--accent)}
/* —— 页头 —— */
.head{padding:34px 0 6px}
.head h1{font-family:var(--serif);font-size:30px;line-height:1.3;margin:0 0 6px;letter-spacing:.01em}
.head .lead{color:var(--muted);font-size:14px}
.head .lead b{color:var(--ink)}
/* —— 正文块 —— */
h2{font-family:var(--serif);font-size:19px;margin:34px 0 12px;padding-bottom:8px;
   border-bottom:1px solid var(--rule);display:flex;justify-content:space-between;align-items:baseline}
h2 small{font-family:var(--sans);font-size:12px;color:var(--muted);font-weight:400}
h3{font-family:var(--serif);font-size:18px;margin:0 0 6px;line-height:1.45}
p{margin:0 0 12px}
.muted{color:var(--muted)}
.small{font-size:13px}
.card{background:var(--card);border:1px solid var(--rule);border-radius:12px;
      padding:16px 18px;margin:0 0 12px;box-shadow:var(--shadow)}
.card.flat{box-shadow:none}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:12px;color:var(--muted)}
.dot{width:3px;height:3px;border-radius:50%;background:var(--rule);display:inline-block}
.badge{display:inline-block;border:1px solid var(--rule);border-radius:6px;padding:1px 7px;
       font-size:11px;color:var(--muted);background:#fff}
.badge.hot{color:var(--warn);border-color:#f0c9b4;background:#fdf1ea}
.tag{display:inline-block;border:1px solid var(--rule);border-radius:999px;
     padding:1px 10px;font-size:12px;color:var(--muted);background:#fff;margin:2px 4px 2px 0}
.sum{color:#4a4438;font-size:14px;margin:6px 0 0}
/* —— 评分可视化 —— */
.axes{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin:10px 0 2px}
.axis{font-size:11px;color:var(--muted);text-align:center}
.axis .bar{height:5px;border-radius:3px;background:var(--rule);margin-bottom:4px;overflow:hidden}
.axis .bar i{display:block;height:100%;background:var(--accent)}
.score{font-family:var(--serif);font-size:26px;line-height:1}
.score small{font-size:12px;color:var(--muted);font-family:var(--sans)}
.reason{background:var(--accent-soft);border-radius:8px;padding:10px 12px;font-size:13px;
        color:#5b3a17;margin:10px 0 0}
/* —— 反馈 / 列表 —— */
.fb{cursor:pointer;border:1px solid var(--rule);border-radius:8px;padding:2px 9px;
    font-size:13px;background:#fff;color:var(--muted)}
.fb:hover{border-color:var(--accent);color:var(--accent)}
.fb.on{background:var(--accent-soft);border-color:var(--accent);color:var(--accent)}
ol.list,ul.list{padding-left:22px;margin:0}
ol.list li,ul.list li{margin:10px 0}
.grid{display:grid;gap:12px}
@media(min-width:640px){.grid.two{grid-template-columns:1fr 1fr}}
/* —— 页脚 + 移动端底栏 —— */
footer{margin-top:48px;padding-top:18px;border-top:1px solid var(--rule);
       color:var(--muted);font-size:12px}
footer a{color:var(--muted)}
footer .links{display:flex;flex-wrap:wrap;gap:6px 14px;margin-top:8px}
.bnav{display:none}
@media(max-width:719px){
  .bnav{display:flex;position:fixed;left:0;right:0;bottom:0;z-index:30;
        background:rgba(255,253,247,.96);backdrop-filter:blur(8px);
        border-top:1px solid var(--rule);padding:6px 0 max(6px,env(safe-area-inset-bottom))}
  .bnav a{flex:1;text-align:center;font-size:11px;color:var(--muted);
          display:flex;flex-direction:column;gap:2px;align-items:center}
  .bnav a.on{color:var(--accent)}
  .bnav .i{font-size:17px;line-height:1}
  .shell{padding-bottom:76px}
  .head h1{font-size:24px}
  h2{font-size:17px}
  .axes{grid-template-columns:repeat(5,1fr)}
}
@media(prefers-color-scheme:dark){
  :root{--paper:#15130f;--card:#1c1914;--ink:#efe9df;--muted:#9c9384;--rule:#2e2921;
        --accent:#e08a4b;--accent-soft:#2a211a;--teal:#4ecdc4;--warn:#f0a07a}
  .badge,.tag,.fb{background:#221e18}
  .sum{color:#cfc7ba}
  .reason{color:#e6cbb0}
}
"""

_ICONS = {"精选": "◆", "全部": "☰", "热门": "▲", "主题": "❖", "日报": "☀",
          "周报": "◷", "月报": "◫", "时间线": "↕", "搜索": "⌕"}


def esc(text: Any) -> str:
    return html.escape(str(text or ""))


def nav_html(active: str = "/") -> str:
    links = []
    for href, label in NAV:
        cls = ' class="on"' if href == active else ""
        links.append(f'<a href="{href}"{cls}>{label}</a>')
    joined = "".join(links)
    return f'<div class="nav"><div class="in"><a class="brand" href="/">信息雷达</a>{joined}</div></div>'


def bottom_nav(active: str = "/") -> str:
    """手机底栏：只放最常用的五个。"""
    picks = ("/", "/all.html", "/hot.html", "/topics.html", "/search.html")
    items = []
    for href, label in NAV:
        if href not in picks:
            continue
        cls = ' class="on"' if href == active else ""
        items.append(f'<a href="{href}"{cls}><span class="i">{_ICONS.get(label, "·")}</span>{label}</a>')
    return f'<div class="bnav">{"".join(items)}</div>'


def footer_html() -> str:
    links = "".join(f'<a href="{href}">{label}</a>' for href, label in MORE)
    return (f'<footer><div>每天 09:00 更新 · 数据与评分均由本机生成，页面只读。</div>'
            f'<div class="links">{links}</div></footer>')


def page(title: str, body: str, *, active: str = "/", lead: str = "",
         subtitle: str = "") -> str:
    """整页骨架。`lead` 是标题下面那一行（可以带 HTML），`subtitle` 进 <title>。"""
    head = f'<div class="head"><h1>{esc(title)}</h1>'
    if lead:
        head += f'<div class="lead">{lead}</div>'
    head += "</div>"
    return (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(subtitle or title)}</title>'
            f'{og_tags(title, lead)}<style>{CSS}</style></head><body>'
            f'{nav_html(active)}<div class="shell">{head}{body}{footer_html()}</div>'
            f'{bottom_nav(active)}</body></html>')


def og_tags(title: str, description: str = "") -> str:
    """Open Graph / Twitter 卡片。图片全站共用 `/og.png`（share.py 每次重画）。"""
    try:
        from .export import config as export_config

        base = str(export_config().get("base_url") or "").rstrip("/")
    except Exception:
        base = ""
    image = f"{base}/og.png" if base else "/og.png"
    desc = " ".join(str(description or "").split())[:180]
    return "\n".join([
        '<meta property="og:type" content="website">',
        f'<meta property="og:title" content="{esc(title)}">',
        f'<meta property="og:description" content="{esc(desc)}">',
        f'<meta property="og:image" content="{esc(image)}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:image" content="{esc(image)}">',
    ])


def override_css() -> str:
    """给旧的深色页面追加的一段覆盖样式，让它们并入同一套配色。

    只覆盖颜色与字体，不动尺寸和布局 —— 那些页面已经调好了，重排风险大。
    """
    return """
:root{--paper:#f6f1e7;--ink:#1c1a16;--muted:#6f6759;--rule:#e2d8c6;--accent:#b4530a}
body{background:#f6f1e7 !important;color:#1c1a16 !important;
     font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif !important}
h1,h2,h3{font-family:"Iowan Old Style",Georgia,"Songti SC","Noto Serif CJK SC",serif !important;
         color:#1c1a16 !important}
a{color:#b4530a !important}
.card,.tile{border-color:#e2d8c6 !important;background:#fffdf7 !important}
.muted,.sub,.k,.h,.bn,.bl{color:#6f6759 !important}
footer{color:#6f6759 !important}
/* 手机底栏：旧页面也要有，否则手机上翻不到别的页面 */
.bnav{display:none}
@media(max-width:719px){
  .bnav{display:flex;position:fixed;left:0;right:0;bottom:0;z-index:30;
        background:rgba(255,253,247,.96);border-top:1px solid #e2d8c6;padding:6px 0}
  .bnav a{flex:1;text-align:center;font-size:11px;color:#6f6759;
          display:flex;flex-direction:column;gap:2px;align-items:center;text-decoration:none}
  .bnav a.on{color:#b4530a}
  .bnav .i{font-size:17px;line-height:1}
}
"""
