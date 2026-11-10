"""Z-Bit 站点骨架与视觉：直接移植 aihot.news 的设计系统。

颜色、圆角、间距、字号全部取自它的 `apps/web/app/app.css` 与组件：

- 底色 `#faf9f6`（暖白）、卡片 `#ffffff`、侧栏 `#fdfdfb`、正文墨色 `#202a30`
- 唯一强调色是青绿 `#176b75`（暗色下 `#12ccd8`），**不用渐变**
- 圆角档位：5 / 8 / 10 / 12 / 14 / 16
- 侧栏 180px（窄屏 64px 图标轨，手机隐藏走底栏）
- 页面容器：手机 640px，桌面 `max(1200px, 270dvh - 236px)`

品牌换成 Z-Bit，其余保持原样 —— 先像，再谈改。
"""

from __future__ import annotations

import html
from typing import Any

def _brand() -> tuple[str, str]:
    """站名与 slogan 从行业配置读 —— 换行业不该改代码。"""
    try:
        from . import industry

        conf = industry.settings()
        return str(conf.get("name") or "Z-Bit"), str(conf.get("tagline") or "")
    except Exception:
        return "Z-Bit", ""


BRAND, TAGLINE = _brand()

# 侧栏分组（对齐它的 SECTIONS：内容 / 模型 / 更多）
SECTIONS = (
    ("内容", (
        ("/", "精选", "bolt"),
        ("/all.html", "全部动态", "list"),
        ("/hot.html", "热点榜", "flame"),
        ("/daily.html", "日报", "doc"),
        ("/topics.html", "主题", "grid"),
        ("/starred.html", "收藏", "bookmark"),
    )),
    ("模型", (
        ("/leaderboard.html", "模型榜", "chart"),
        ("/free-tokens.html", "Token 羊毛", "tag"),
        ("/monthly.html", "月报", "doc"),
        ("/timeline.html", "时间线", "clock"),
    )),
    ("更多", (
        ("/agent.html", "Agent 接入", "plug"),
        ("/about.html", "关于", "heart"),
        ("/changelog.html", "更新日志", "history"),
        ("/feedback.html", "反馈", "message"),
        ("/board.html", "运行看板", "grid"),
        ("/admin.html", "后台", "lock"),
    )),
)
# 扁平表，兼容旧代码（页脚 / 更多页）
MORE = tuple((href, label) for _t, items in SECTIONS for href, label, _i in items
             if href not in ("/", "/all.html", "/hot.html", "/daily.html", "/topics.html", "/starred.html"))
# 手机底栏
TABS = (("/", "精选", "bolt"), ("/hot.html", "热点", "flame"),
        ("/daily.html", "日报", "doc"), ("/more.html", "我的", "user"))

_ICONS = {
    "bolt": '<path d="M13 2 4.5 13.5H11l-1 8.5 8.5-11.5H12l1-8.5Z"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    "flame": '<path d="M12 2c1 4-2 5-2 8a2 2 0 0 0 4 0c0-1-.5-2-.5-2S17 11 17 15a5 5 0 0 1-10 0c0-5 5-6 5-13Z"/>',
    "doc": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M9 13h6M9 17h4"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    "bookmark": '<path d="M19 21 12 16 5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2Z"/>',
    "chart": '<path d="M3 3v18h18"/><path d="M7 15l4-5 3 3 5-7"/>',
    "tag": '<path d="M20 12.5 12.5 20a2 2 0 0 1-2.8 0L3 13.3V3h10.3l6.7 6.7a2 2 0 0 1 0 2.8Z"/><circle cx="7.5" cy="7.5" r="1.2"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "plug": '<path d="M12 22v-5"/><path d="M9 8V2M15 8V2"/><path d="M6 8h12v3a6 6 0 0 1-12 0Z"/>',
    "heart": '<path d="M20.8 5.6a5 5 0 0 0-7.1 0L12 7.3l-1.7-1.7a5 5 0 1 0-7.1 7.1L12 21.5l8.8-8.8a5 5 0 0 0 0-7.1Z"/>',
    "history": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 8v5l4 2"/>',
    "message": '<path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z"/>',
    "lock": '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21v-1a7 7 0 0 1 14 0v1"/>',
}


def icon(name: str, size: int = 17) -> str:
    body = _ICONS.get(name, _ICONS["grid"])
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true">{body}</svg>')


# 设计 token：直接照搬 app.css 的 :root 与 [data-theme=dark]
CSS = """
:root{
  color-scheme:light;
  --bg:#faf9f6; --bg-sunk:#f3f3ef; --bg-muted:#e9ede9; --well:#f3f3ef;
  --surface:#fff; --surface-2:#fdfdfb; --raised:#fff; --sidebar:#fdfdfb; --daybar:#f0f2ee;
  --ink:#202a30; --ink-2:#303c42; --ink-3:#59656b; --ink-4:#657176;
  --line:#dfe4e1; --line-strong:#d1d9d5; --line-soft:#e9ede9;
  --accent:#176b75; --accent-ink:#145f68; --accent-soft:rgba(23,107,117,.08);
  --accent-softer:rgba(23,107,117,.05); --accent-contrast:#fff;
  --note:#526f72; --hot:#b3402a; --hot-soft:rgba(179,64,42,.08);
  --amber:#b8873a; --ok:#2f7d5c;
  --rank-1:#b3402a; --rank-2:#a3642f; --rank-3:#96702e; --rank-rest:#6b7684;
  --shadow-card:0 1px 2px rgba(32,42,48,.025);
  --shadow-card-hover:0 3px 12px rgba(32,42,48,.055);
  --shadow-thumb:0 1px 2px rgba(28,39,51,.1),0 1px 1px rgba(28,39,51,.04);
  --shadow-soft:0 4px 12px rgba(28,39,51,.06);
  --r-mark:5px; --r-control:8px; --r-tile:10px; --r-card:12px; --r-panel:14px; --r-sheet:16px;
  --font-sans:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","HarmonyOS Sans SC","Microsoft YaHei",sans-serif;
  --font-mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Monaco,Consolas,monospace;
  --side-w:180px; --page-max-wide:max(1200px,calc(270dvh - 236px));
}
[data-theme="dark"]{
  color-scheme:dark;
  --bg:#13191c; --bg-sunk:#182024; --bg-muted:#202a2f;
  --well:color-mix(in oklab,var(--bg-muted) 60%,transparent);
  --surface:#1a2226; --surface-2:#1d272b; --raised:#202a2f; --sidebar:#161e21; --daybar:#182024;
  --ink:#e7eceb; --ink-2:#d2dada; --ink-3:#a5b0b3; --ink-4:#89979d;
  --line:rgba(255,255,255,.08); --line-strong:rgba(255,255,255,.12); --line-soft:rgba(255,255,255,.06);
  --accent:#12ccd8; --accent-ink:#2ce2e8; --accent-soft:rgba(18,204,216,.12);
  --accent-softer:rgba(18,204,216,.06); --accent-contrast:#000;
  --note:#8fb8a8; --hot:#d86a52; --hot-soft:rgba(216,106,82,.12);
  --amber:#d3b26a; --ok:#5fc79a;
  --rank-1:#d86a52; --rank-2:#d18a5e; --rank-3:#d3b26a; --rank-rest:#7b869a;
  --shadow-card:none; --shadow-card-hover:none; --shadow-thumb:0 1px 2px rgba(0,0,0,.45);
  --shadow-soft:0 6px 18px rgba(0,0,0,.35);
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font-sans);
     font-size:16px;line-height:1.6;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
a:hover{color:var(--accent)}
button{font-family:inherit}
.mono{font-family:var(--font-mono);font-variant-numeric:tabular-nums}
.num{font-variant-numeric:tabular-nums}

/* —— 外壳：侧栏 + 主列 —— */
.shell{display:flex;min-height:100dvh}
.main{min-width:0;flex:1;padding:0 0 72px}
@media(min-width:700px){.main{padding:24px 20px 72px}}
@media(min-width:941px){.main{padding:24px 28px 72px}}
.page{margin:0 auto;width:100%;max-width:640px;padding:0 16px}
@media(min-width:700px){.page{max-width:var(--page-max-wide);padding:0}}

/* —— 侧栏 —— */
.side{display:none}
@media(min-width:700px){
  .side{display:flex;position:sticky;top:0;height:100dvh;width:64px;flex:none;
        flex-direction:column;align-items:center;gap:4px;border-right:1px solid var(--line);
        background:var(--sidebar);padding:20px 6px 14px;overflow:auto;scrollbar-width:none}
  .side::-webkit-scrollbar{display:none}
  .side .brand{display:flex;align-items:center;justify-content:center;width:44px;height:44px;
               margin-bottom:12px;color:var(--accent)}
  .side .mark{font:800 18px/1 var(--font-sans);letter-spacing:-.02em;color:var(--accent)}
  .side .mark .full{display:none}
  .side .mark .short{display:inline}
  .side .sec-title{display:none}
  .side .grp{display:flex;flex-direction:column;gap:4px;width:100%}
  .side a.item{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;
               height:56px;border-radius:var(--r-control);font-size:11px;font-weight:500;
               color:var(--ink-3);transition:background .15s,color .15s}
  .side a.item span.lbl{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .side a.item.on{background:var(--accent-soft);color:var(--ink);font-weight:600}
  .side a.item.on svg{color:var(--accent)}
  .side .foot{display:none}
}
@media(min-width:941px){
  .side{width:var(--side-w);align-items:stretch;padding:24px 12px 14px}
  .side .brand{justify-content:flex-start;height:50px;padding:0 4px;margin-bottom:16px;color:var(--ink)}
  .side .mark{font-size:22px;color:var(--ink);letter-spacing:-.01em}
  .side .mark .full{display:inline}
  .side .mark .short{display:none}
  .side .sec-title{display:block;padding:14px 10px 4px;font-size:11px;color:var(--ink-4)}
  .side .grp{gap:4px}
  .side a.item{flex-direction:row;align-items:center;justify-content:flex-start;gap:10px;
               height:40px;padding:0 10px;font-size:14px;font-weight:500}
  .side a.item span.ico{display:flex;width:22px;flex:none;justify-content:center}
  .side a.item.on svg{color:var(--accent)}
  .side .foot{display:block;margin-top:auto;padding-top:8px}
  .side .gh{display:flex;align-items:center;justify-content:center;gap:6px;height:34px;
            border:1px solid var(--line);border-radius:999px;font-size:12.5px;color:var(--ink-3)}
  .side .gh:hover{background:var(--bg-sunk);color:var(--ink)}
  .side .themebtn{display:flex;align-items:center;justify-content:center;gap:6px;width:100%;
                  height:32px;margin-top:10px;border:1px solid var(--line);border-radius:999px;
                  background:transparent;font-size:12px;color:var(--ink-3);cursor:pointer}
  .side .themebtn:hover{background:var(--bg-sunk);color:var(--ink)}
}

/* —— 页头 —— */
h1.title{font-size:24px;font-weight:600;line-height:1.3;margin:20px 0 14px}
@media(min-width:700px){h1.title{margin:4px 0 16px}}
h1.title small{font-size:13px;font-weight:400;color:var(--ink-4);margin-left:10px}
.lead{color:var(--ink-3);font-size:14px;margin:-6px 0 18px}

/* —— 药丸筛选 + 搜索 —— */
.pillbar{display:inline-flex;gap:2px;max-width:100%;overflow-x:auto;scrollbar-width:none;
         border-radius:999px;background:var(--well);padding:3px;
         box-shadow:inset 0 0 0 1px var(--line-soft)}
.pillbar::-webkit-scrollbar{display:none}
.pillbar a{display:inline-flex;align-items:center;height:30px;padding:0 12px;border-radius:999px;
           font-size:13px;color:var(--ink-3);white-space:nowrap}
.pillbar a.on{background:var(--surface);color:var(--ink);font-weight:600;
              box-shadow:var(--shadow-thumb);box-shadow:var(--shadow-thumb),0 0 0 1px var(--line)}
.searchrow{display:flex;gap:10px;align-items:center;margin:14px 0 18px}
.searchrow .box{position:relative;flex:1;min-width:0}
.searchrow input{width:100%;height:42px;border:0;border-radius:999px;background:var(--well);
                 padding:0 40px 0 38px;font-size:15px;color:var(--ink);outline:none;
                 box-shadow:inset 0 0 0 1px var(--line-soft)}
.searchrow input:focus{box-shadow:inset 0 0 0 1px var(--accent)}
.searchrow .ic{position:absolute;left:13px;top:50%;transform:translateY(-50%);color:var(--ink-4)}
.searchrow kbd{position:absolute;right:14px;top:50%;transform:translateY(-50%);
               border:1px solid var(--line-strong);border-radius:var(--r-mark);background:var(--surface);
               padding:0 6px;font:11px/16px var(--font-mono);color:var(--ink-4)}

/* —— 当前热点卡片 —— */
.hotcard{position:relative;overflow:hidden;background:var(--surface);border:1px solid var(--line);
         border-radius:var(--r-card);box-shadow:var(--shadow-card);padding:10px 14px 4px;margin-bottom:16px}
.hotcard::before{content:"";position:absolute;inset:0;pointer-events:none;
  background:radial-gradient(120% 90% at 100% 0%,var(--hot-soft),transparent 55%)}
.hotcard .hd{position:relative;display:flex;align-items:center;justify-content:space-between;margin-bottom:4px}
.hotcard h2{display:flex;align-items:center;gap:8px;margin:0;font-size:14px;font-weight:600}
.dotlive{position:relative;display:flex;width:8px;height:8px}
.dotlive i{position:absolute;inset:0;border-radius:50%;background:var(--hot);opacity:.4;
           animation:ping 1.8s cubic-bezier(0,0,.2,1) infinite}
.dotlive b{position:relative;width:8px;height:8px;border-radius:50%;background:var(--hot)}
@keyframes ping{75%,100%{transform:scale(2.2);opacity:0}}
.hotcard .more{font-size:12.5px;color:var(--ink-3)}
.hotcard ol{position:relative;list-style:none;margin:0;padding:0}
.hotcard li a{display:grid;grid-template-columns:20px minmax(0,1fr) auto;gap:12px;align-items:center;
              margin:0 -8px;padding:7px 8px;border-radius:var(--r-tile);min-height:40px}
@media(min-width:641px){
  .hotcard li a{grid-template-columns:20px minmax(0,1fr) 96px 56px 18px;gap:16px;padding:8px}
  .hotcard li:nth-child(n+4){display:block}
}
.hotcard li a:hover{background:var(--bg-sunk)}
.hotcard .rk{font-size:15px;font-weight:900;text-align:center;line-height:1;color:var(--rank-rest)}
.hotcard li:nth-child(1) .rk{color:var(--rank-1)}
.hotcard li:nth-child(2) .rk{color:var(--rank-2)}
.hotcard li:nth-child(3) .rk{color:var(--rank-3)}
.hotcard .tt{font-size:14.5px;font-weight:600;line-height:1.5;overflow:hidden;
             display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical}
.hotcard .faces{display:none;justify-content:flex-end}
@media(min-width:641px){.hotcard .faces{display:flex}}
.hotcard .faces i{width:20px;height:20px;border-radius:50%;background:var(--bg-muted);
                  border:1.5px solid var(--surface);margin-left:-6px}
.hotcard .heat{font-size:12.5px;color:var(--ink-4);white-space:nowrap;text-align:right}
.hotcard .heat b{font-size:13.5px;font-weight:600;color:var(--ink-2)}
@media(max-width:640px){.hotcard li:nth-child(n+4){display:none}.hotcard .faces{display:none}}

/* —— 日期分组 + 时间轴 —— */
.daybar{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:12px;height:44px;
        background:var(--bg);margin:0}
.daybar .d{font-size:18px;font-weight:600;line-height:24px;white-space:nowrap}
.daybar .w{font-size:13px;color:var(--ink-4)}
.daybar .aside{margin-left:auto;font-size:12px;color:var(--ink-4)}
.feed{list-style:none;margin:0;padding:4px 0 0}
.slot{display:grid;grid-template-columns:minmax(0,1fr);padding:14px 0;
      border-bottom:1px solid var(--line-soft)}
.slot:last-child{border-bottom:0}
@media(min-width:700px){
  .slot{grid-template-columns:64px 22px minmax(0,1fr);border-bottom:0;padding:0 0 12px}
  .slot:last-child{padding-bottom:0}
  .slot>time{font-family:var(--font-mono);font-size:12.5px;font-weight:600;line-height:24px;
             color:var(--ink-3);padding-top:15px}
  .slot .rail{position:relative}
  .slot .rail::before{content:"";position:absolute;left:10.5px;top:29px;bottom:-41px;width:1px;
                      background:var(--line-strong)}
  .slot:last-child .rail::before{display:none}
  .slot .rail::after{content:"";position:absolute;left:7.5px;top:25.5px;width:7px;height:7px;
                     border-radius:50%;background:var(--accent);
                     box-shadow:0 0 0 4px var(--bg);transition:transform .3s}
  .slot:hover .rail::after{transform:scale(1.15)}
}
@media(max-width:699px){.slot>time{display:none}.slot .rail{display:none}}

/* —— 卡片（条目） —— */
.cardrow{min-width:0}
@media(min-width:700px){
  .cardrow{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-card);
           box-shadow:var(--shadow-card);padding:15px 18px 14px;
           transition:box-shadow .2s,border-color .2s,transform .2s}
  .cardrow:hover{box-shadow:var(--shadow-card-hover);border-color:var(--line-strong);
                 transform:translateY(-1px)}
}
.cardrow .hd{display:flex;align-items:center;gap:6px;min-height:22px;font-size:12.5px;
             line-height:18px;color:var(--ink-4)}
@media(min-width:700px){.cardrow .hd{min-height:18px;gap:8px}}
.cardrow .hd .src{display:inline-flex;align-items:center;gap:6px;min-width:0;overflow:hidden;
                  text-overflow:ellipsis;white-space:nowrap}
.cardrow .hd .rt{margin-left:auto;display:flex;align-items:center;gap:6px;flex:none;padding-left:8px}
.badge-pick{display:none;align-items:center;height:18px;padding:0 6px;border-radius:var(--r-mark);
            background:var(--accent-soft);color:var(--accent);font-size:11px;font-weight:600}
@media(min-width:700px){.badge-pick{display:inline-flex}}
.scorelabel{display:inline-flex;align-items:baseline;gap:2px;font-family:var(--font-mono);
            font-size:11.5px;color:var(--ink-4)}
.scorelabel b{font-size:12.5px;font-weight:600;color:var(--ink-3)}
.cardrow h3{margin:6px 0 0;font-size:17px;font-weight:650;line-height:1.5;color:var(--ink)}
@media(min-width:700px){.cardrow h3{margin-top:8px;line-height:1.55}}
.cardrow h3 a:hover{color:var(--accent)}
.cardrow .sum{margin:4px 0 0;font-size:14.5px;line-height:1.7;color:var(--ink-3);
              display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
@media(min-width:700px){
  .cardrow .sum{margin-top:8px;font-size:15px;line-height:1.75;-webkit-line-clamp:3}
}
.cardrow .reason{margin:4px 0 0;font-size:13px;line-height:1.65;color:var(--note);
                 display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden}
@media(min-width:700px){
  .cardrow .reason{margin-top:12px;border-top:1px solid var(--line-soft);padding-top:12px;
                   line-height:1.75;-webkit-line-clamp:unset;display:block}
}
.cardrow .tags{display:none;gap:10px;margin-top:8px;font-size:12px;color:var(--ink-4)}
@media(min-width:700px){.cardrow .tags{display:flex;flex-wrap:wrap}}
.tag{display:inline-block;border:1px solid var(--line);border-radius:var(--r-mark);
     padding:0 6px;font-size:11px;color:var(--ink-4)}

/* —— 通用块 —— */
.well{background:var(--well);border-radius:var(--r-panel);box-shadow:inset 0 0 0 1px var(--line-soft);
      padding:14px 16px}
.muted{color:var(--ink-4)}
.small{font-size:13px}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:12px;color:var(--ink-4)}
.dot{width:3px;height:3px;border-radius:50%;background:var(--line-strong);display:inline-block}
.badge,.pill{display:inline-flex;align-items:center;height:18px;border-radius:var(--r-mark);
             padding:0 6px;font-size:11px;color:var(--ink-4);background:var(--well);
             box-shadow:inset 0 0 0 1px var(--line-soft)}
.pill{border-radius:999px;padding:1px 9px}
.pill.ok{color:var(--ok);background:rgba(47,125,92,.1);box-shadow:none}
.pill.err{color:var(--hot);background:var(--hot-soft);box-shadow:none}
.axes{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin:10px 0 2px}
.axis{font-size:11px;color:var(--ink-4);text-align:center}
.axis .bar{height:4px;border-radius:3px;background:var(--line-soft);margin-bottom:4px;overflow:hidden}
.axis .bar i{display:block;height:100%;background:var(--accent)}
.score{font-family:var(--font-mono);font-size:22px;font-weight:600}
.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line-soft)}
th{color:var(--ink-4);font-weight:500;font-size:12px}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.fb{cursor:pointer;border:1px solid var(--line);border-radius:var(--r-control);padding:2px 9px;
    font-size:12px;background:var(--surface);color:var(--ink-3)}
.fb:hover,.fb.on{border-color:var(--accent);color:var(--accent);background:var(--accent-softer)}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 16px}
.tabs a{border:1px solid var(--line);border-radius:999px;padding:3px 12px;font-size:13px;color:var(--ink-3)}
.tabs a.on{background:var(--accent-soft);border-color:transparent;color:var(--accent);font-weight:600}
ol.list,ul.list{padding-left:20px;margin:0}
ol.list li,ul.list li{margin:8px 0}
hr{border:0;border-top:1px solid var(--line);margin:24px 0}
h2.sec{font-size:14px;font-weight:600;margin:26px 0 12px;display:flex;
       justify-content:space-between;align-items:baseline}
h2.sec a{font-size:12.5px;font-weight:400;color:var(--ink-3)}

/* —— 页脚（内容区） —— */
footer{margin-top:40px;padding-top:16px;border-top:1px solid var(--line);
       font-size:12px;color:var(--ink-4)}
footer .links{display:flex;flex-wrap:wrap;gap:6px 16px;margin-top:8px}
footer .links a{color:var(--ink-4)}

/* —— 手机底栏 —— */
.bnav{display:flex;position:fixed;left:0;right:0;bottom:0;z-index:40;
      background:var(--surface);border-top:1px solid var(--line);
      padding:6px 0 max(6px,env(safe-area-inset-bottom))}
.bnav a{flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;
        font-size:11px;color:var(--ink-4)}
.bnav a.on{color:var(--accent);font-weight:600}
@media(min-width:700px){.bnav{display:none}.main{padding-bottom:72px}}
"""


def esc(text: Any) -> str:
    return html.escape(str(text or ""))


def nav_html(active: str = "/") -> str:
    """左侧栏：图标轨（700–940px）→ 完整栏（≥941px）。

    `nav_hidden` 里的入口不显示，但页面照常生成、直接打开也能访问。
    """
    try:
        from . import industry

        hidden = set(industry.settings().get("nav_hidden") or [])
    except Exception:
        hidden = set()
    blocks = []
    for title, items in SECTIONS:
        links = []
        for href, label, name in items:
            if href in hidden:
                continue
            on = ' class="item on"' if href == active else ' class="item"'
            links.append(f'<a{on} href="{href}"><span class="ico">{icon(name)}</span>'
                         f'<span class="lbl">{label}</span></a>')
        blocks.append(f'<div class="grp"><div class="sec-title">{title}</div>{"".join(links)}</div>')
    foot = ('<div class="foot">'
            '<a class="gh" href="https://github.com/KKKKhazix/AIHOT" target="_blank" rel="noopener">'
            f'{icon("grid", 14)} GitHub 开源</a>'
            '<button class="themebtn" type="button" id="themebtn">◐ 跟随系统</button>'
            '</div>')
    return (f'<aside class="side"><a class="brand" href="/" aria-label="{BRAND} 首页">'
            f'<span class="mark"><span class="short">Z</span>'
            f'<span class="full">{BRAND}</span></span></a>{"".join(blocks)}{foot}</aside>')


def bottom_nav(active: str = "/") -> str:
    try:
        from . import industry

        hidden = set(industry.settings().get("nav_hidden") or [])
    except Exception:
        hidden = set()
    out = []
    for href, label, name in TABS:
        if href in hidden:
            continue
        on = ' class="on"' if href == active else ""
        out.append(f'<a href="{href}"{on}>{icon(name, 20)}{label}</a>')
    return f'<div class="bnav">{"".join(out)}</div>'


def footer_html() -> str:
    links = "".join(f'<a href="{href}">{label}</a>' for href, label in
                    (("/about.html", "关于"), ("/agent.html", "Agent 接入"),
                     ("/changelog.html", "更新日志"), ("/feedback.html", "反馈"),
                     ("/terms.html", "条款"), ("/privacy.html", "隐私")))
    return f'<footer><div>{BRAND} · 每天 09:00 更新 · 内容与评分均在本机生成</div><div class="links">{links}</div></footer>'


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


_THEME_JS = """<script>
(function(){var r=document.documentElement;
 var saved=null;try{saved=localStorage.getItem('zbit.theme')}catch(e){}
 if(saved)r.setAttribute('data-theme',saved);
 var b=document.getElementById('themebtn');
 if(b){b.addEventListener('click',function(){
   var now=r.getAttribute('data-theme')==='dark'?'light':'dark';
   r.setAttribute('data-theme',now);
   try{localStorage.setItem('zbit.theme',now)}catch(e){}
 });}
})();</script>"""


def page(title: str, body: str, *, active: str = "/", lead: str = "",
         subtitle: str = "", own_heading: bool = False) -> str:
    head = "" if own_heading else f'<h1 class="title">{esc(title)}</h1>'
    lead_html = f'<div class="lead">{lead}</div>' if lead else ""
    return (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(subtitle or title)}</title>'
            f'{og_tags(title, lead)}<style>{CSS}</style></head><body>'
            f'<div class="shell">{nav_html(active)}<main class="main"><div class="page">'
            f'{head}{lead_html}{body}{footer_html()}</div></main></div>'
            f'{bottom_nav(active)}{_THEME_JS}</body></html>')


def toptabs(active: str = "/") -> str:
    """内容区顶部的药丸筛选（首页/全部用真筛选，其它页只做轻量入口）。"""
    return ""


def override_css() -> str:
    """老页面（看板/时间线/主题/离线）并入同一套 token。

    这些页面自带一份旧 CSS，变量名不一样；这里把 Z-Bit 的 token 也一起发过去，
    再把它们用到的颜色类映射过去 —— 否则 `var(--bg)` 是空的，颜色会塌。
    """
    return """
:root{color-scheme:light;
 --bg:#faf9f6;--bg-sunk:#f3f3ef;--bg-muted:#e9ede9;--well:#f3f3ef;
 --surface:#fff;--surface-2:#fdfdfb;--raised:#fff;--sidebar:#fdfdfb;--daybar:#f0f2ee;
 --ink:#202a30;--ink-2:#303c42;--ink-3:#59656b;--ink-4:#657176;
 --line:#dfe4e1;--line-strong:#d1d9d5;--line-soft:#e9ede9;
 --accent:#176b75;--accent-ink:#145f68;--accent-soft:rgba(23,107,117,.08);
 --accent-softer:rgba(23,107,117,.05);--note:#526f72;--hot:#b3402a;--hot-soft:rgba(179,64,42,.08);
 --ok:#2f7d5c;--rank-1:#b3402a;--rank-2:#a3642f;--rank-3:#96702e;--rank-rest:#6b7684;
 --r-mark:5px;--r-control:8px;--r-tile:10px;--r-card:12px;--r-panel:14px;
 --font-sans:system-ui,-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
 --font-mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
[data-theme="dark"]{color-scheme:dark;
 --bg:#13191c;--bg-sunk:#182024;--bg-muted:#202a2f;--well:rgba(32,42,47,.6);
 --surface:#1a2226;--surface-2:#1d272b;--raised:#202a2f;--sidebar:#161e21;--daybar:#182024;
 --ink:#e7eceb;--ink-2:#d2dada;--ink-3:#a5b0b3;--ink-4:#89979d;
 --line:rgba(255,255,255,.08);--line-strong:rgba(255,255,255,.12);--line-soft:rgba(255,255,255,.06);
 --accent:#12ccd8;--accent-ink:#2ce2e8;--accent-soft:rgba(18,204,216,.12);
 --accent-softer:rgba(18,204,216,.06);--note:#8fb8a8;--hot:#d86a52;--hot-soft:rgba(216,106,82,.12);
 --ok:#5fc79a;--rank-1:#d86a52;--rank-2:#d18a5e;--rank-3:#d3b26a;--rank-rest:#7b869a}
body{background:var(--bg) !important;color:var(--ink) !important;
     font-family:var(--font-sans) !important;
     /* 老页面没有 .shell 外壳：让 body 自己充当 flex 容器，侧栏和内容并排 */
     display:flex !important;min-height:100dvh}
.wrap{flex:1;min-width:0;max-width:max(1200px,calc(270dvh - 236px)) !important;
      margin:0 auto !important;padding:0 0 72px !important}
@media(min-width:700px){.wrap{padding:24px 20px 72px !important}}
@media(min-width:941px){.wrap{padding:24px 28px 72px !important}}
h1,h2,h3{color:var(--ink) !important;font-family:var(--font-sans) !important}
a{color:var(--accent) !important}
.card,.tile{background:var(--surface) !important;border-color:var(--line) !important;
            color:var(--ink) !important}
.muted,.sub,.k,.h,.bn,.bl{color:var(--ink-3) !important}
footer{color:var(--ink-4) !important}
table th{color:var(--ink-4) !important;border-color:var(--line) !important}
table td{border-color:var(--line-soft) !important}
"""
