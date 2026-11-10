"""Z-Bit 站点视觉与骨架：布局对齐 aihot.news，皮肤换成自己的。

布局事实（照抄 aihot.news 首页）：
- 单列窄栏，约 42rem，居中；手机上左右各留一点
- 两级顶栏：第一行只有 精选 / 全部 / 热点 / 日报 / 模型榜 / 我的 + 主题切换；
  第二行是可展开的分组菜单（内容 / 模型 / 更多）
- 首页：H1「精选」→ 筛选条（全部/一手/模型/产品/行业/论文/教程/观点）→ 搜索框
  → 「当前热点」5 条（序号 + 标题 + 来源头像堆叠 + 热度）→ 「只看未读」
  → 按日期分组的消息流：左侧时间，右侧来源行 · 精选徽标 · AI 评分 / 标题 / 摘要 / 推荐理由
- 条目页、日报页都是同一条窄栏

艺术化只做三件事，不破布局：更大的字级对比、衬线展示字、极轻的纸感与渐层。
"""

from __future__ import annotations

import html
from typing import Any

BRAND = "Z-Bit"

NAV = (
    ("/", "精选"),
    ("/all.html", "全部"),
    ("/hot.html", "热点"),
    ("/daily.html", "日报"),
    ("/monthly.html", "模型榜"),
    ("/topics.html", "主题"),
)
MENU = {
    "内容": (("/", "精选"), ("/all.html", "全部动态"), ("/hot.html", "热点榜"),
             ("/daily.html", "日报"), ("/weekly.html", "周报"), ("/topics.html", "主题"),
             ("/starred.html", "收藏")),
    "模型": (("/monthly.html", "月报"), ("/timeline.html", "时间线"),
             ("/board.html", "运行看板")),
    "更多": (("/agent.html", "Agent 接入"), ("/about.html", "关于"),
             ("/feedback.html", "反馈"), ("/changelog.html", "更新日志"),
             ("/offline.mp4" if False else "/offline.html", "离线版"),
             ("/admin.html", "后台")),
}

# 扁平入口表：页脚、"更多"页与后台都用这个（保持和旧接口一致）
MORE = (
    ("/agent.html", "Agent 接入"), ("/admin.html", "后台"),
    ("/board.html", "运行看板"), ("/archive/", "历史归档"),
    ("/offline.html", "离线版"), ("/starred.html", "我的收藏"),
    ("/feedback.html", "反馈"), ("/about.html", "关于"),
    ("/terms.html", "使用条款"), ("/privacy.html", "隐私"),
    ("/changelog.html", "更新日志"),
)

CSS = """
:root{
  --bg:#0a0a0b; --bg2:#101013; --ink:#f2efe9; --ink2:#a8a29a; --ink3:#6d6862;
  --line:#1e1e22; --line2:#2a2a30;
  --accent:#e8b04b; --accent2:#c9743a; --ok:#7fb069; --bad:#d1694a;
  --serif:"Playfair Display","Iowan Old Style",Georgia,"Songti SC","Noto Serif CJK SC",serif;
  --sans:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",Inter,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --w:42rem;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0;background:var(--bg);color:var(--ink);
  font:16px/1.75 var(--sans);
  -webkit-font-smoothing:antialiased;
}
/* 极轻的顶部渐层，替代表情化的装饰 */
body::before{
  content:"";position:fixed;inset:0 0 auto;height:340px;pointer-events:none;z-index:0;
  background:radial-gradient(120% 100% at 50% -30%,rgba(232,176,75,.10),transparent 62%);
}
a{color:inherit;text-decoration:none}
a:hover{color:var(--accent)}
.wrap{position:relative;z-index:1;max-width:var(--w);margin:0 auto;padding:0 18px 90px}

/* —— 顶栏（两级） —— */
.top{position:sticky;top:0;z-index:30;background:rgba(10,10,11,.86);
     backdrop-filter:blur(14px) saturate(140%);border-bottom:1px solid var(--line)}
.top .in{max-width:var(--w);margin:0 auto;padding:10px 18px;display:flex;align-items:center;gap:14px}
.brand{font-family:var(--serif);font-size:20px;font-weight:700;letter-spacing:.04em;
       background:linear-gradient(92deg,#fff,var(--accent) 78%);-webkit-background-clip:text;
       background-clip:text;color:transparent;white-space:nowrap}
.navlinks{display:flex;gap:16px;margin-left:auto;align-items:center;overflow:auto;scrollbar-width:none}
.navlinks::-webkit-scrollbar{display:none}
.navlinks a{font-size:14px;color:var(--ink2);white-space:nowrap}
.navlinks a.on{color:var(--ink);position:relative}
.navlinks a.on::after{content:"";position:absolute;left:0;right:0;bottom:-6px;height:2px;
                      background:var(--accent);border-radius:2px}
.subnav{max-width:var(--w);margin:0 auto;padding:0 18px 9px;display:flex;gap:18px;
        font-size:12px;color:var(--ink3);overflow:auto;scrollbar-width:none}
.subnav::-webkit-scrollbar{display:none}
.subnav b{color:var(--ink3);font-weight:500;margin-right:6px}
.subnav a{white-space:nowrap}
.subnav span{display:flex;align-items:center}

/* —— 页头 —— */
h1.title{font-family:var(--serif);font-size:40px;line-height:1.15;margin:34px 0 18px;
         letter-spacing:-.01em;font-weight:600}
h1.title small{font-family:var(--sans);font-size:13px;color:var(--ink3);letter-spacing:0;
               font-weight:400;margin-left:10px}
.lead{color:var(--ink2);font-size:14px;margin:-8px 0 20px}

/* —— 筛选条 + 搜索 —— */
.chips{display:flex;gap:8px;overflow:auto;scrollbar-width:none;padding-bottom:4px;margin:0 0 14px}
.chips::-webkit-scrollbar{display:none}
.chip{font-size:13px;color:var(--ink2);padding:5px 12px;border-radius:999px;
      border:1px solid var(--line2);white-space:nowrap}
.chip.on{color:#12100c;background:var(--accent);border-color:var(--accent);font-weight:600}
.searchrow{display:flex;gap:10px;align-items:center;margin:0 0 26px}
.searchrow input{flex:1;background:var(--bg2);border:1px solid var(--line2);color:var(--ink);
                 border-radius:10px;padding:10px 13px;font-size:14px;outline:none}
.searchrow input:focus{border-color:var(--accent)}
.searchrow kbd{font:12px var(--mono);color:var(--ink3);border:1px solid var(--line2);
               border-radius:5px;padding:2px 6px}

/* —— 当前热点 —— */
h2.sec{font-size:13px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink3);
       margin:30px 0 12px;display:flex;justify-content:space-between;align-items:baseline;
       font-weight:600}
h2.sec a{font-size:12px;letter-spacing:0;text-transform:none;color:var(--accent)}
.hot{display:flex;flex-direction:column;gap:2px;margin-bottom:12px}
.hot a{display:flex;gap:10px;align-items:baseline;padding:9px 10px;border-radius:10px;
       border:1px solid transparent}
.hot a:hover{background:var(--bg2);border-color:var(--line)}
.hot .n{font:12px var(--mono);color:var(--ink3);width:16px;flex:none}
.hot .t{font-size:14.5px;line-height:1.5}
.hot .av{display:flex;margin-left:auto;flex:none}
.hot .av i{width:16px;height:16px;border-radius:50%;background:var(--line2);
           border:1px solid var(--bg);margin-left:-5px}
.hot .h{font:12px var(--mono);color:var(--accent);flex:none;margin-left:8px}

/* —— 日期分组 + 消息流 —— */
.daybar{position:sticky;top:64px;z-index:5;display:flex;justify-content:space-between;
        align-items:center;font-size:13px;color:var(--ink3);padding:8px 0;
        background:linear-gradient(var(--bg) 72%,transparent);border-bottom:1px solid var(--line)}
.feed{list-style:none;margin:0;padding:0}
.item{display:grid;grid-template-columns:52px 1fr;gap:12px;padding:16px 0;
      border-bottom:1px solid var(--line)}
.item .time{font:12px var(--mono);color:var(--ink3);padding-top:3px}
.item .src{font-size:12.5px;color:var(--ink3);display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.item .src .pick{color:var(--accent)}
.item .src .score{font:12px var(--mono);color:var(--ink3);border:1px solid var(--line2);
                  border-radius:5px;padding:0 5px}
.item h3{font-family:var(--sans);font-size:16.5px;line-height:1.6;font-weight:600;
         margin:6px 0 0;letter-spacing:.005em}
.item h3 a{display:inline}
.item .sum{color:var(--ink2);font-size:14px;margin:6px 0 0;line-height:1.75}
.item .reason{color:var(--ink3);font-size:13px;margin:8px 0 0;padding-left:10px;
              border-left:2px solid var(--line2)}
.item .thumb{width:74px;height:74px;border-radius:10px;background:var(--bg2);
             border:1px solid var(--line);float:right;margin:2px 0 6px 12px}
.item .ops{display:flex;gap:10px;margin-top:10px;font-size:12px;color:var(--ink3)}

/* —— 通用块（后台/主题/日报沿用） —— */
.card{background:var(--bg2);border:1px solid var(--line);border-radius:12px;padding:16px 18px;
      margin:0 0 12px}
.card h3{font-size:16px;margin:0 0 6px;font-weight:600}
.muted{color:var(--ink3)}
.small{font-size:13px}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:12px;color:var(--ink3)}
.dot{width:3px;height:3px;border-radius:50%;background:var(--line2);display:inline-block}
.badge,.tag{display:inline-block;border:1px solid var(--line2);border-radius:6px;padding:1px 7px;
            font-size:11px;color:var(--ink3)}
.tag{border-radius:999px;padding:1px 10px;margin:2px 4px 2px 0}
.pill{display:inline-block;border-radius:999px;padding:1px 9px;font-size:11px;
      border:1px solid var(--line2);color:var(--ink3)}
.pill.ok{color:var(--ok);border-color:#2c3a28}.pill.err{color:var(--bad);border-color:#3a2620}
.axes{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin:10px 0 2px}
.axis{font-size:11px;color:var(--ink3);text-align:center}
.axis .bar{height:4px;border-radius:3px;background:var(--line2);margin-bottom:4px;overflow:hidden}
.axis .bar i{display:block;height:100%;background:var(--accent)}
.score{font-family:var(--serif);font-size:26px}
.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
th{color:var(--ink3);font-weight:500;font-size:12px}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.fb{cursor:pointer;border:1px solid var(--line2);border-radius:7px;padding:2px 9px;font-size:12px;
    background:transparent;color:var(--ink3);font-family:inherit}
.fb:hover,.fb.on{border-color:var(--accent);color:var(--accent)}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 16px}
.tabs a{border:1px solid var(--line2);border-radius:999px;padding:3px 12px;font-size:13px;
        color:var(--ink3)}
.tabs a.on{background:rgba(232,176,75,.14);border-color:var(--accent);color:var(--accent)}
ol.list,ul.list{padding-left:20px;margin:0}
ol.list li,ul.list li{margin:9px 0}
hr{border:0;border-top:1px solid var(--line);margin:26px 0}

/* —— 页脚 —— */
footer{margin-top:52px;padding-top:20px;border-top:1px solid var(--line);
       color:var(--ink3);font-size:12px}
footer .links{display:flex;flex-wrap:wrap;gap:6px 16px;margin-top:10px}
footer .links a{color:var(--ink3)}

/* —— 手机底栏 —— */
.bnav{display:none}
@media(max-width:640px){
  h1.title{font-size:30px;margin-top:24px}
  .item{grid-template-columns:44px 1fr;gap:10px}
  .bnav{display:flex;position:fixed;left:0;right:0;bottom:0;z-index:40;
        background:rgba(10,10,11,.94);backdrop-filter:blur(12px);
        border-top:1px solid var(--line);padding:7px 0 max(7px,env(safe-area-inset-bottom))}
  .bnav a{flex:1;text-align:center;font-size:11px;color:var(--ink3)}
  .bnav a.on{color:var(--accent)}
  .wrap{padding-bottom:80px}
}
@media(prefers-color-scheme:light){
  :root{--bg:#faf8f4;--bg2:#fffdf9;--ink:#16150f;--ink2:#57534b;--ink3:#8b857b;
        --line:#e7e2d8;--line2:#d8d2c6;--accent:#a8620f;--accent2:#8a4d09}
  body::before{background:radial-gradient(120% 100% at 50% -30%,rgba(168,98,15,.07),transparent 62%)}
  .top{background:rgba(250,248,244,.88)}
  .chip.on{color:#fff}
  .brand{background:linear-gradient(92deg,#16150f,var(--accent) 82%);
         -webkit-background-clip:text;background-clip:text}
  .bnav{background:rgba(250,248,244,.94)}
}
"""


def esc(text: Any) -> str:
    return html.escape(str(text or ""))


def nav_html(active: str = "/") -> str:
    """两级顶栏：第一行主导航，第二行分组菜单。"""
    links = []
    for href, label in NAV:
        cls = ' class="on"' if href == active else ""
        links.append(f'<a href="{href}"{cls}>{label}</a>')
    links.append('<a href="/starred.html">我的</a>')
    top = (f'<div class="top"><div class="in">'
           f'<a class="brand" href="/">{BRAND}</a>'
           f'<nav class="navlinks">{"".join(links)}</nav></div>')
    groups = []
    for name, items in MENU.items():
        inner = " ".join(f'<a href="{href}">{label}</a>' for href, label in items)
        groups.append(f'<span><b>{name}</b>{inner}</span>')
    top += f'<div class="subnav">{"".join(groups)}</div></div>'
    return top


def bottom_nav(active: str = "/") -> str:
    picks = ("/", "/all.html", "/hot.html", "/daily.html", "/starred.html")
    labels = {href: label for href, label in NAV}
    labels["/starred.html"] = "我的"
    out = []
    for href in picks:
        cls = ' class="on"' if href == active else ""
        out.append(f'<a href="{href}"{cls}>{labels.get(href, href)}</a>')
    return f'<div class="bnav">{"".join(out)}</div>'


def footer_html() -> str:
    links = "".join(f'<a href="{href}">{label}</a>' for href, label in
                    (("/about.html", "关于"), ("/agent.html", "Agent 接入"),
                     ("/changelog.html", "更新日志"), ("/feedback.html", "反馈"),
                     ("/terms.html", "条款"), ("/privacy.html", "隐私")))
    return (f'<footer><div>{BRAND} · 每天 09:00 更新 · 内容与评分均在本机生成</div>'
            f'<div class="links">{links}</div></footer>')


def og_tags(title: str, description: str = "") -> str:
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


def page(title: str, body: str, *, active: str = "/", lead: str = "",
         subtitle: str = "", own_heading: bool = False) -> str:
    head = "" if own_heading else f'<h1 class="title">{esc(title)}</h1>'
    lead_html = f'<div class="lead">{lead}</div>' if lead else ""
    return (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(subtitle or title)}</title>'
            f'{og_tags(title, lead)}<style>{CSS}</style></head><body>'
            f'{nav_html(active)}<div class="wrap">{head}{lead_html}{body}{footer_html()}</div>'
            f'{bottom_nav(active)}</body></html>')


def override_css() -> str:
    """给老页面（看板/时间线/主题/离线）追加的一段，让它们并入新皮肤。"""
    return """
body{background:#0a0a0b !important;color:#f2efe9 !important;
     font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif !important}
h1,h2,h3{font-family:"Playfair Display",Georgia,"Songti SC",serif !important;color:#f2efe9 !important}
a{color:#e8b04b !important}
.card,.tile{border-color:#1e1e22 !important;background:#101013 !important}
.muted,.sub,.k,.h,.bn,.bl{color:#6d6862 !important}
footer{color:#6d6862 !important}
@media(prefers-color-scheme:light){
  body{background:#faf8f4 !important;color:#16150f !important}
  h1,h2,h3{color:#16150f !important}
  a{color:#a8620f !important}
  .card,.tile{border-color:#e7e2d8 !important;background:#fffdf9 !important}
  .muted,.sub,.k,.h,.bn,.bl{color:#8b857b !important}
}
"""
