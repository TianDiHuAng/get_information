"""关于页：把"这个站怎么工作"画出来。

对应 AIHOT 的 `/about`：它那里不是一张图，是一块 `<canvas>` 实时动画 ——
每条线是一个真实信源，线汇成束（同一件事的多篇报道），经过精选的闸门，
通过的几条变青绿、流进一张报纸。下面四栏是采集 / 收录 / 精选 / 成刊，
数字来自真实统计。

这里照同样的思路做，但用我们自己库里的数：
- 线的数量 = 实际信源数
- 束的数量 = 实际事件数
- 通过的束 = 实际过门槛的条数
- 报纸上的数字 = 实际出刊期数

canvas 只是示意；同样的信息在下面四栏里也有文字，读屏和关掉动画都能看懂。
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from . import industry, store, theme

ROOT = Path(__file__).parent.parent
SITE = ROOT / "site"


def _counts() -> dict[str, Any]:
    """真实统计。任何一项取不到就给 0，页面不能因此挂掉。"""
    out = {"sources": 0, "items": 0, "selected": 0, "events": 0, "editions": 0}
    try:
        with store.db() as conn:
            out["sources"] = int(conn.execute(
                "SELECT count(*) FROM sources WHERE coalesce(enabled,1)=1").fetchone()[0] or 0)
            out["items"] = int(conn.execute("SELECT count(*) FROM items").fetchone()[0] or 0)
            out["editions"] = int(conn.execute(
                "SELECT count(*) FROM editions WHERE kind='daily'").fetchone()[0] or 0)
            out["events"] = int(conn.execute(
                "SELECT count(DISTINCT event_id) FROM event_items").fetchone()[0] or 0)
            row = conn.execute(
                "SELECT count(*) FROM scores WHERE score >= 58").fetchone()
            out["selected"] = int(row[0] or 0) if row else 0
    except Exception:
        pass
    if not out["sources"]:
        try:
            from .sources import REGISTRY

            out["sources"] = len([s for s in REGISTRY if s.get("enabled")])
        except Exception:
            pass
    return out


_RIVER_JS = r"""
<script>
(function(){
  var cv = document.getElementById('river');
  if (!cv) return;
  var ctx = cv.getContext('2d');
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var D = window.__RIVER__ || {sources: 20, bundles: 6};

  function palette(){
    var dark = document.documentElement.getAttribute('data-theme') === 'dark'
      || (!document.documentElement.getAttribute('data-theme')
          && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    return dark
      ? {line:'rgba(255,255,255,.13)', pass:'#12ccd8', text:'#a5b0b3', paper:'#1a2226', ink:'#e7eceb'}
      : {line:'rgba(32,42,48,.14)', pass:'#176b75', text:'#657176', paper:'#ffffff', ink:'#202a30'};
  }

  var W = 0, H = 0, dpr = 1;
  function resize(){
    var box = cv.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = Math.max(320, box.width); H = Math.max(160, box.height);
    cv.width = W * dpr; cv.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  // 每条线一个信源；随机归入某个"束"（同一件事）
  var N = Math.max(6, Math.min(48, D.sources || 20));
  var lines = [];
  for (var i = 0; i < N; i++) {
    lines.push({
      y0: (i + 0.5) / N,
      bundle: i % Math.max(2, Math.min(6, D.bundles || 4)),
      phase: Math.random(),
      speed: 0.006 + Math.random() * 0.006
    });
  }
  var GATE = 0.62, PAPER = 0.82;
  var t = 0;

  function bundleY(b, total){
    return 0.16 + (b + 0.5) / total * 0.68;
  }

  function draw(){
    var p = palette();
    ctx.clearRect(0, 0, W, H);
    var total = Math.max(2, Math.min(6, D.bundles || 4));

    // 线：从左边散开，到 GATE 前收成一束
    for (var i = 0; i < lines.length; i++) {
      var L = lines[i];
      var by = bundleY(L.bundle, total);
      ctx.beginPath();
      ctx.moveTo(0, L.y0 * H);
      ctx.bezierCurveTo(W * 0.28, L.y0 * H, W * 0.42, by * H, W * GATE, by * H);
      ctx.strokeStyle = p.line; ctx.lineWidth = 1; ctx.stroke();
    }

    // 闸门之后：只有一部分束通过（用 bundles 里排名靠前的）
    var passCount = Math.max(1, Math.round(total * 0.45));
    for (var b = 0; b < total; b++) {
      var by2 = bundleY(b, total);
      var open = b < passCount;
      ctx.beginPath();
      ctx.moveTo(W * GATE, by2 * H);
      ctx.lineTo(W * PAPER, (0.3 + b / total * 0.4) * H);
      ctx.strokeStyle = open ? p.pass : p.line;
      ctx.lineWidth = open ? 2 : 1;
      ctx.globalAlpha = open ? 0.85 : 1;
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    // 闸门
    var gx = W * GATE;
    ctx.beginPath(); ctx.moveTo(gx, H * 0.08); ctx.lineTo(gx, H * 0.92);
    ctx.strokeStyle = p.text; ctx.globalAlpha = 0.35; ctx.setLineDash([3, 4]);
    ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1;
    ctx.fillStyle = p.text; ctx.font = '11px system-ui,sans-serif';
    ctx.fillText('精选', gx + 6, H * 0.08 + 12);

    // 报纸
    var px = W * PAPER, pw = Math.min(84, W * 0.16), ph = H * 0.46, py = H * 0.27;
    ctx.fillStyle = p.paper;
    ctx.strokeStyle = p.text; ctx.globalAlpha = 0.35;
    roundRect(px, py, pw, ph, 5); ctx.fill(); ctx.stroke(); ctx.globalAlpha = 1;
    ctx.fillStyle = p.text; ctx.font = '600 10px system-ui,sans-serif';
    ctx.fillText('日报', px + 8, py + 15);
    ctx.globalAlpha = 0.35;
    for (var k = 0; k < 4; k++) {
      ctx.fillRect(px + 8, py + 22 + k * 7, pw - 16, 2);
    }
    ctx.globalAlpha = 1;

    // 往来的脉冲：大部分停在闸门前
    if (!reduce) {
      for (var j = 0; j < lines.length; j++) {
        var P = lines[j];
        P.phase += P.speed;
        if (P.phase > 1) P.phase -= 1;
        var reach = (P.bundle < passCount) ? PAPER : GATE - 0.02;
        var u = P.phase * reach;
        var x, y;
        if (u <= GATE) {
          var s = u / GATE;
          x = u * W;
          y = (P.y0 + (bundleY(P.bundle, total) - P.y0) * (s * s)) * H;
        } else {
          var s2 = (u - GATE) / (PAPER - GATE);
          x = u * W;
          y = (bundleY(P.bundle, total) + ((0.3 + P.bundle / total * 0.4) - bundleY(P.bundle, total)) * s2) * H;
        }
        ctx.beginPath();
        ctx.arc(x, y, 2, 0, Math.PI * 2);
        ctx.fillStyle = (P.bundle < passCount) ? p.pass : p.text;
        ctx.globalAlpha = 0.7;
        ctx.fill(); ctx.globalAlpha = 1;
      }
    }
    if (!reduce) requestAnimationFrame(draw);
  }

  function roundRect(x, y, w, h, r){
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  resize();
  window.addEventListener('resize', function(){ resize(); if (reduce) draw(); });
  draw();
})();
</script>"""

_RIVER_CSS = """
.riverbox{position:relative;background:var(--surface);border:1px solid var(--line);
          border-radius:var(--r-panel);box-shadow:var(--shadow-card);padding:8px;margin:10px 0 6px}
.riverbox canvas{display:block;width:100%;height:220px}
.caption{font-size:12.5px;color:var(--ink-4);margin:6px 0 26px}
@media(max-width:640px){.riverbox canvas{height:160px}}
.steps{display:grid;gap:18px;margin:26px 0 0}
@media(min-width:700px){.steps{grid-template-columns:repeat(4,1fr);gap:20px}}
.step{border-top:1px solid var(--line);padding-top:12px}
.step .no{font:600 11px var(--font-mono);color:var(--accent);letter-spacing:.08em}
.step h3{font-size:16px;font-weight:600;margin:6px 0 2px}
.step .big{font:600 22px var(--font-mono);color:var(--ink);margin:2px 0 8px;
           font-variant-numeric:tabular-nums}
.step p{font-size:13px;line-height:1.7;color:var(--ink-3);margin:0}
.hero{font-size:30px;line-height:1.35;font-weight:600;margin:18px 0 10px;letter-spacing:-.01em}
@media(max-width:640px){.hero{font-size:23px}}
.hero em{font-style:normal;color:var(--accent)}
"""


def build(site_root: Path | None = None, day: str | None = None) -> dict[str, Any]:
    root = site_root or SITE
    conf = industry.settings()
    c = _counts()
    brand = theme.esc(conf.get("name") or theme.BRAND)

    hero = (f'<p class="hero">每天都有新动静，<em>值得看的只有几条。</em></p>'
            f'<p class="lead">{brand} 替你盯着 {c["sources"]} 个信源：抓取、归并、打分、精选，'
            f'每天 {theme.esc((conf.get("edition") or {}).get("daily") or "09:00")} 出一份日报。</p>')

    river = (f'<h2 class="sec">它怎么工作</h2>'
             f'<div class="riverbox"><canvas id="river" aria-label="示意图"></canvas></div>'
             f'<p class="caption">每条线是一个信源；线汇成一束束，代表同一件事的多篇报道；'
             f'经过精选的闸门，只有少数几束通过，汇入每天的日报。</p>')

    steps = f"""
<div class="steps">
  <div class="step"><div class="no">01</div><h3>采集</h3>
    <div class="big">{c['sources']} 个源</div>
    <p>官方博客、媒体、榜单、社区与搜索都在看。每个源有自己的分级与参与方式。</p></div>
  <div class="step"><div class="no">02</div><h3>收录</h3>
    <div class="big">{c['items']:,} 条</div>
    <p>收下的每条都留着，跨天去重；讲同一件事的多篇报道归成一个事件，热点就从这里算。</p></div>
  <div class="step"><div class="no">03</div><h3>精选</h3>
    <div class="big">{c['selected']:,} 条</div>
    <p>先筛掉营销稿与重复转发，再按五个维度独立打两次分；够分的才进日报。</p></div>
  <div class="step"><div class="no">04</div><h3>成刊</h3>
    <div class="big">{c['editions']} 期</div>
    <p>每天出日报，周一出周报，每月 1 日出月报；也可以用 RSS、API、llms.txt 订阅。</p></div>
</div>"""

    body = hero + river + steps + f"""
<h2 class="sec">这个站怎么来的</h2>
<p>它的引擎吸收了 AIHOT 的工程做法：五维加权评分、事件聚簇与热度、
LLM 回执与预算、断点续跑、多出口。判断标准（提示词与门槛）全部是本地文件，
可以换成任何一个行业 —— 见 <a href="/agent.html">Agent 接入</a> 与
<a href="/changelog.html">更新日志</a>。</p>
<p class="muted small">内容是聚合摘要与阅读索引，原文版权归各来源所有。
如果你希望更正或下架，请通过<a href="/feedback.html">反馈页</a>联系。</p>"""

    doc = theme.page(f"关于 · {brand}", body, active="/about.html", own_heading=True,
                     subtitle=f"关于 {brand}")
    doc = doc.replace("</head>", f"<style>{_RIVER_CSS}</style></head>", 1)
    doc = doc.replace("</body>", f"<script>window.__RIVER__={{sources:{c['sources']},"
                                 f"bundles:{max(2, min(6, c['events'] or 4))}}};</script>"
                                 f"{_RIVER_JS}</body>", 1)
    (root.mkdir(parents=True, exist_ok=True), (root / "about.html").write_text(doc, encoding="utf-8"))
    return {"file": str(root / "about.html"), "counts": c}
