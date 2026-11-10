"""后台：只读的诊断与运营视图。

**故意只读。**改配置仍然改 YAML —— 给一个只读服务加写入口，安全边界要重新划，
而收益并不大（这些操作一天最多几次，编辑文件更快也更可审）。

它比 `/board.html` 多看五样东西，都是排障时真正会问的：

1. **运行**：每个阶段什么时候跑的、多久、成败（`runs` 表）；
2. **信源**：连续失败、最近错误、最近一次成功（`sources` 表）；
3. **内容诊断**：今天每条的分、理由、预筛标签 —— 可以只看"被判成无关"和"评分失败"的；
4. **评测**：`data/eval/*.json` 最近一份报告的准确率、覆盖率与门槛扫描；
5. **配置快照**：门槛、预算、每一步用哪个模型（只展示，不修改）。

访问需要口令（`data/admin_token.txt`，首次由 serve.py 生成）。
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import llm, rating, store, theme

ROOT = Path(__file__).parent.parent
SITE = ROOT / "site"
DATA = ROOT / "data"
TOKEN_PATH = ROOT / "data" / "admin_token.txt"   # data/ 已在 .gitignore 里


# --------------------------------------------------------------------------- #
# 口令
# --------------------------------------------------------------------------- #

def token() -> str:
    """读后台口令；没有就生成一个（首次运行 serve.py 时也会调到这里）。"""
    try:
        existing = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass
    import secrets

    value = secrets.token_urlsafe(12)
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(value + "\n", encoding="utf-8")
    return value


def check(value: str | None) -> bool:
    """常量时间比较，避免用响应时间猜口令。"""
    if not value:
        return False
    expected = token()
    return len(value) == len(expected) and _same(expected, value)


def _same(a: str, b: str) -> bool:
    diff = 0
    for x, y in zip(a.encode(), b.encode()):
        diff |= x ^ y
    return diff == 0


# --------------------------------------------------------------------------- #
# 数据
# --------------------------------------------------------------------------- #

def _rows(sql: str, args: tuple = ()) -> list[dict[str, Any]]:
    with store.db() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def runs(day: str | None = None, limit: int = 40) -> list[dict[str, Any]]:
    day = day or store.today_str()
    try:
        rows = _rows(
            "SELECT id, stage, status, started_at, finished_at, detail FROM runs "
            "WHERE day = ? ORDER BY id DESC LIMIT ?", (day, limit))
    except Exception:
        return []
    for r in rows:
        try:
            start = datetime.strptime(r["started_at"], "%Y-%m-%d %H:%M:%S")
            end = datetime.strptime(r["finished_at"], "%Y-%m-%d %H:%M:%S") if r["finished_at"] else None
            r["seconds"] = int((end - start).total_seconds()) if end else None
        except Exception:
            r["seconds"] = None
    return rows


def sources() -> list[dict[str, Any]]:
    try:
        return store.source_rows()
    except Exception:
        return []


def alerts(limit: int = 50) -> list[dict[str, Any]]:
    try:
        return _rows("SELECT kind, day, severity, message, created_at FROM alerts "
                     "ORDER BY id DESC LIMIT ?", (limit,))
    except Exception:
        return []


def content(day: str | None = None, only: str = "all", limit: int = 200) -> list[dict[str, Any]]:
    """今天的内容诊断表。`only` 支持 all / blocked / failed / selected。"""
    day = day or store.today_str()
    rows = store.all_items(day, limit=limit)
    out = []
    for it in rows:
        att = it.get("attention") or {}
        label = att.get("label") if att else None
        available = bool(att.get("available"))
        if only == "blocked" and label != "BLOCK":
            continue
        if only == "failed" and (available or label == "BLOCK"):
            # "评分失败"是"没拿到分"且不是预筛判定的 —— 预筛拦截单独一档
            continue
        if only == "selected" and not att.get("selected"):
            continue
        out.append({
            "id": it["id"], "title": it["title"], "source": it["source"],
            "published": (it.get("published") or "")[:10],
            "score": att.get("score"), "threshold": att.get("threshold"),
            "itype": att.get("itype"), "reason": att.get("reason"),
            "available": available, "label": label,
            "selected": bool(att.get("selected")),
            "category": (it.get("structure") or {}).get("category"),
        })
    return out


def evaluations(limit: int = 5) -> list[dict[str, Any]]:
    """`data/eval/*.json` 里最近的评测报告摘要。"""
    folder = DATA / "eval"
    if not folder.exists():
        return []
    out = []
    for path in sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        report = data.get("report") or {}
        out.append({
            "file": path.name,
            "kind": "relations" if path.name.startswith("relations") else "selection",
            "model": data.get("model"),
            "seconds": data.get("seconds"),
            "total": report.get("total"),
            "valid": report.get("valid"),
            "coverage": report.get("coverage"),
            "accuracy": report.get("accuracy"),
            "complete_accuracy": report.get("complete_accuracy"),
            "f1": report.get("f1") or report.get("macro_f1"),
            "sweep": len(data.get("sweep") or []),
        })
    return out


def config_snapshot() -> dict[str, Any]:
    """配置快照：只展示，不修改。"""
    conf = rating.config()
    llm_conf = {}
    try:
        llm_conf = llm.settings()
    except Exception:
        pass
    models = {}
    try:
        from .editorial_models import per_step  # 不存在时静默（本项目没有这一层）
        models = per_step()
    except Exception:
        models = {}
    return {
        "thresholds": conf.get("thresholds") or {},
        "weights": conf.get("weights") or {},
        "score_calls": conf.get("score_calls"),
        "understand_floor": conf.get("understand_floor"),
        "browse_floor": conf.get("browse_floor"),
        "max_workers": conf.get("max_workers"),
        "model": llm_conf.get("model"),
        "backup_model": llm_conf.get("backup_model"),
        "budget_per_day": llm_conf.get("budget_per_day"),
        "budget_per_hour": llm_conf.get("budget_per_hour"),
        "models": models,
    }


def llm_table(day: str | None = None) -> list[dict[str, Any]]:
    """按任务分组的调用与失败情况。"""
    day = day or store.today_str()
    try:
        return _rows(
            """SELECT task, state, count(*) AS n, sum(tokens) AS tokens,
                      sum(attempts) AS attempts
               FROM llm_calls WHERE date(created_at) = ?
               GROUP BY task, state ORDER BY task, state""", (day,))
    except Exception:
        return []


# --------------------------------------------------------------------------- #
# 信源操作（供 serve.py 的两个受保护接口调用）
# --------------------------------------------------------------------------- #

def toggle_source(source: str, enabled: bool) -> dict[str, Any]:
    """停用/启用。只写 SQLite 的开关列，不动代码里的源定义。"""
    if not source:
        return {"ok": False, "error": "missing source"}
    try:
        store.set_source_enabled(str(source), bool(enabled))
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return {"ok": True, "source": source, "enabled": bool(enabled)}


def preview_source(source: str, *, timeout: float = 25.0, limit: int = 8) -> dict[str, Any]:
    """试抓一个源：真的跑一次它的抓取器，但**不入库**。

    慢的源（X 的 Apify 要跑多条查询）会超时 —— 那就如实返回超时，别让页面一直等。
    """
    import time
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

    from . import sources as src

    if not source:
        return {"ok": False, "error": "missing source"}
    fetchers = dict(src.build_fetchers())
    fn = fetchers.get(str(source))
    if fn is None:
        return {"ok": False, "error": f"没有这个源，或者它已被停用: {source}"}

    started = time.time()
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(fn)
        items = future.result(timeout=timeout)
    except FutureTimeout:
        pool.shutdown(wait=False, cancel_futures=True)
        return {"ok": False, "error": f"超时（>{int(timeout)}s），这个源比较慢，稍后再试"}
    except Exception as e:
        pool.shutdown(wait=False, cancel_futures=True)
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    pool.shutdown(wait=False)

    rows = [{"title": (getattr(it, "title", "") or "")[:80],
             "url": getattr(it, "url", "") or "",
             "published": getattr(it, "published", "") or "",
             "source": getattr(it, "source", "") or ""} for it in (items or [])]
    return {"ok": True, "source": source, "count": len(rows),
            "seconds": round(time.time() - started, 1), "items": rows[:limit]}


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #

_EXTRA_CSS = """
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--rule);vertical-align:top}
th{color:var(--muted);font-weight:500;font-size:12px}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.pill{display:inline-block;border-radius:999px;padding:1px 9px;font-size:11px;
      border:1px solid var(--rule);color:var(--muted)}
.pill.ok{color:#166534;border-color:#bbf7d0;background:#f0fdf4}
.pill.err{color:#9a3412;border-color:#fed7aa;background:#fff7ed}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 18px}
.tabs a{border:1px solid var(--rule);border-radius:999px;padding:3px 12px;font-size:13px;color:var(--muted)}
.tabs a.on{background:var(--accent-soft);border-color:var(--accent);color:var(--accent)}
.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px}
.scroll{overflow-x:auto}
"""


def _pill(text: str, kind: str = "") -> str:
    cls = f"pill {kind}".strip()
    return f'<span class="{cls}">{theme.esc(text)}</span>'


def _run_section(day: str) -> str:
    rows = runs(day)
    if not rows:
        return '<p class="muted">今天还没有运行记录。</p>'
    body = "".join(
        f'<tr><td class="mono">{theme.esc(r["started_at"][11:])}</td>'
        f'<td>{theme.esc(r["stage"])}</td>'
        f'<td>{_pill(r["status"], "ok" if r["status"] == "ok" else "err")}</td>'
        f'<td class="num">{r["seconds"] if r["seconds"] is not None else "—"}s</td>'
        f'<td class="muted small">{theme.esc(r.get("detail") or "")}</td></tr>'
        for r in rows)
    return (f'<div class="scroll"><table><thead><tr><th>开始</th><th>阶段</th><th>状态</th>'
            f'<th>耗时</th><th>说明</th></tr></thead><tbody>{body}</tbody></table></div>')


def _source_section() -> str:
    rows = sources()
    if not rows:
        return ('<p class="muted">还没有信源健康记录。跑一次 <code>python run.py</code> 就有了。</p>'
                '<p class="muted small">新增信源仍然改 <code>config/feeds.yaml</code> 或 '
                '<code>collector/sources.py</code> 的 REGISTRY。</p>')
    body_rows = []
    for r in rows:
        name = theme.esc(r["source"])
        enabled = int(r.get("enabled", 1)) != 0
        fails = int(r.get("fails") or 0)
        badge = _pill("已停用", "err") if not enabled else ""
        toggle = (f'<button class="fb" data-toggle="{name}" data-enable="{0 if enabled else 1}">'
                  f'{"停用" if enabled else "启用"}</button>')
        preview = f'<button class="fb" data-preview="{name}">试抓</button>'
        body_rows.append(
            f'<tr><td>{name} {badge}</td>'
            f'<td class="num">{r.get("last_count") or 0}</td>'
            f'<td class="num">{_pill(str(fails), "err" if fails >= 3 else "")}</td>'
            f'<td class="muted small">{theme.esc((r.get("last_ok") or "—")[:19])}</td>'
            f'<td class="muted small">{theme.esc((r.get("last_error") or "")[:40])}</td>'
            f'<td>{toggle} {preview}</td></tr>')
    table = (f'<div class="scroll"><table><thead><tr><th>信源</th><th>本轮条数</th>'
             f'<th>连续失败</th><th>最近成功</th><th>最近错误</th><th>操作</th>'
             f'</tr></thead><tbody>{"".join(body_rows)}</tbody></table></div>')
    return (table +
            '<h2>试抓结果</h2><div id="preview"><p class="muted">点某一行的「试抓」看这个源现在能抓到什么'
            '（不会入库；慢的源可能超时）。</p></div>'
            '<p class="muted small">停用的源会在下一轮抓取时跳过。新增信源仍然改 '
            '<code>config/feeds.yaml</code>。</p>' + _SOURCE_JS)


_SOURCE_JS = """
<script>
function el(tag, cls, text){var e=document.createElement(tag); if(cls)e.className=cls;
  if(text!==undefined)e.textContent=text; return e;}
async function post(path, body){
  var r = await fetch(path, {method:'POST', headers:{'content-type':'application/json'},
                             body: JSON.stringify(body)});
  return r.json();
}
document.addEventListener('click', async function(e){
  var t = e.target.closest('[data-toggle]');
  if (t){
    t.disabled = true;
    var want = t.dataset.enable === '1';
    var j = await post('/api/source/toggle', {source:t.dataset.toggle, enabled:want});
    t.disabled = false;
    if (j.ok) { location.reload(); } else { alert(j.error || '失败'); }
    return;
  }
  var p = e.target.closest('[data-preview]');
  if (p){
    var box = document.getElementById('preview');
    box.innerHTML = '<p class="muted">正在抓取 ' + p.dataset.preview + ' …</p>';
    var j = await post('/api/source/preview', {source:p.dataset.preview});
    if (!j.ok){ box.innerHTML = '<p class="muted">失败：' + (j.error||'') + '</p>'; return; }
    var rows = (j.items||[]).map(function(it){
      var li = el('li'); var a = el('a', null, it.title || '(无标题)');
      a.href = it.url || '#'; a.target = '_blank'; a.rel = 'noopener';
      li.appendChild(a);
      if (it.published) li.appendChild(el('span','muted small',' · ' + it.published.slice(0,10)));
      return li.outerHTML;
    }).join('');
    box.innerHTML = '<p class="muted small">' + (j.count||0) + ' 条，用时 ' + (j.seconds||0) +
      's（前 ' + (j.items||[]).length + ' 条）</p><ul class="list">' + rows + '</ul>';
  }
});
</script>"""


def _tabs(base: str, items: tuple, current: str) -> str:
    """生成一排标签链接。`base` 形如 `/admin.html?tab=content&only=`。"""
    out = []
    for key, label in items:
        cls = ' class="on"' if key == current else ""
        out.append(f'<a href="{base}{key}"{cls}>{label}</a>')
    return f'<div class="tabs">{"".join(out)}</div>'


def _content_section(day: str, only: str) -> str:
    rows = content(day, only=only)
    tabs = _tabs("/admin.html?tab=content&only=",
                 (("all", "全部"), ("selected", "过门槛"),
                  ("blocked", "预筛拦截"), ("failed", "评分失败")), only)
    if not rows:
        return tabs + '<p class="muted">这个筛选下没有条目。</p>'
    body_rows = []
    for r in rows:
        thr = f" / {r['threshold']}" if r.get("threshold") else ""
        score = r["score"] if r["score"] is not None else "—"
        note = (r.get("reason") or r.get("label") or "")[:46]
        body_rows.append(
            f'<tr><td><a href="/items/{r["id"]}.html">{theme.esc(r["title"][:52])}</a></td>'
            f'<td class="muted small">{theme.esc(r["source"])}</td>'
            f'<td>{theme.esc(r.get("category") or "—")}</td>'
            f'<td class="num">{score}{thr}</td>'
            f'<td class="muted small">{theme.esc(note)}</td></tr>')
    body = "".join(body_rows)
    return (tabs + '<div class="scroll"><table><thead><tr>'
            '<th>标题</th><th>源</th><th>分类</th><th>分/门槛</th><th>理由</th>'
            f'</tr></thead><tbody>{body}</tbody></table></div>')


def _better_section(day: str, split: str = "development") -> str:
    """标注台：给今天的条目打「选 / 不选 / 两可」，只写 data/gold.jsonl。

    顶部可以切"标进开发集还是留出集"：调提示词只看开发集，最后用留出集验收。
    """
    from . import selectbench

    split = split if split in ("development", "holdout") else "development"
    rows = selectbench.candidates(day)
    st = selectbench.stats()
    done = sum(st[d] for d in selectbench.DECISIONS)
    bar = (f'<p class="muted small">已标 <b>{done}</b> 条'
           f'（选 {st["select"]} · 不选 {st["reject"]} · 两可 {st["either"]}）'
           f'｜开发集 {st["split_development"]} · 留出集 {st["split_holdout"]}'
           f'｜<code>data/gold.jsonl</code></p>'
           + _tabs("/admin.html?tab=better&split=",
                   (("development", "标进开发集"), ("holdout", "标进留出集")), split))

    body_rows = []
    for r in rows:
        decision = r["decision"]
        cells = []
        for key, label in (("select", "选"), ("reject", "不选"), ("either", "两可")):
            cls = "fb on" if decision == key else "fb"
            cells.append(f'<button class="{cls}" data-label="{r["id"]}" '
                         f'data-decision="{key}" data-split="{split}">{label}</button>')
        if decision:
            cells.append(f'<button class="fb" data-clear="{r["id"]}" title="撤销">×</button>')
        score = r["score"] if r["score"] is not None else "—"
        mark = "" if decision else ' <span class="pill">未标</span>'
        body_rows.append(
            f'<tr><td><a href="/items/{r["id"]}.html">{theme.esc(r["title"][:56])}</a>{mark}</td>'
            f'<td class="muted small">{theme.esc(r["source"])}</td>'
            f'<td class="muted small">{theme.esc(r["category"] or "—")}</td>'
            f'<td class="num">{score}</td>'
            f'<td class="muted small">{theme.esc((r["reason"] or "")[:38])}</td>'
            f'<td>{"".join(cells)}</td></tr>')

    table = (f'<div class="scroll"><table><thead><tr><th>标题</th><th>源</th><th>分类</th>'
             f'<th>分</th><th>理由</th><th>你的判断</th></tr></thead>'
             f'<tbody>{"".join(body_rows) or "<tr><td colspan=6 class=muted>今天没有条目</td></tr>"}'
             f'</tbody></table></div>')
    return (bar + table +
            '<h2>标完做什么</h2>'
            '<pre class="card flat small" style="overflow:auto;">'
            'python tools/eval_selection.py --enrich --split development   # 调提示词\npython tools/eval_selection.py --enrich --split holdout       # 最后验收</pre>'
            '<p class="muted small">评测会读 <code>data/gold.jsonl</code>，'
            '出准确率 / 覆盖率 / 门槛扫描。标注只存在这个文件里，'
            '不碰提示词与门槛 —— 你可以随时手改或删掉。</p>' + _BETTER_JS)


_BETTER_JS = """
<script>
async function postGold(body){
  var r = await fetch('/api/gold', {method:'POST', headers:{'content-type':'application/json'},
                                    body: JSON.stringify(body)});
  return r.json();
}
document.addEventListener('click', async function(e){
  var b = e.target.closest('[data-label]');
  if (b){
    b.disabled = true;
    var j = await postGold({item_id: Number(b.dataset.label), decision: b.dataset.decision, split: b.dataset.split});
    b.disabled = false;
    if (!j.ok){ alert(j.error || '失败'); return; }
    var row = b.closest('tr');
    row.querySelectorAll('[data-label]').forEach(function(x){x.classList.remove('on')});
    b.classList.add('on');
    location.reload();
    return;
  }
  var c = e.target.closest('[data-clear]');
  if (c){
    c.disabled = true;
    var j = await postGold({item_id: Number(c.dataset.clear), decision: 'clear'});
    c.disabled = false;
    if (j.ok) location.reload(); else alert(j.error || '失败');
  }
});
</script>"""


def _eval_section() -> str:
    rows = evaluations()
    if not rows:
        return ('<p class="muted">还没有评测报告。跑 <code>python tools/make_gold.py</code> '
                '标注后用 <code>tools/eval_selection.py</code> 生成。</p>')
    body = "".join(
        f'<tr><td class="mono">{theme.esc(r["file"])}</td>'
        f'<td>{_pill(r["kind"])}</td><td class="muted small">{theme.esc(r.get("model") or "")}</td>'
        f'<td class="num">{r.get("total")}</td>'
        f'<td class="num">{(r.get("accuracy") or 0):.1%}</td>'
        f'<td class="num">{(r.get("coverage") or 0):.1%}</td>'
        f'<td class="num">{(r.get("complete_accuracy") or 0):.1%}</td>'
        f'<td class="num">{(r.get("f1") or 0):.3f}</td></tr>'
        for r in rows)
    return (f'<div class="scroll"><table><thead><tr><th>报告</th><th>类型</th><th>模型</th>'
            f'<th>样本</th><th>准确率</th><th>覆盖率</th><th>完整准确率</th><th>F1</th>'
            f'</tr></thead><tbody>{body}</tbody></table></div>')


def _llm_section(day: str) -> str:
    rows = llm_table(day)
    if not rows:
        return '<p class="muted">今天还没有模型调用记录。</p>'
    body = "".join(
        f'<tr><td class="mono">{theme.esc(r["task"])}</td>'
        f'<td>{_pill(r["state"], "ok" if r["state"] == "ok" else "err")}</td>'
        f'<td class="num">{r["n"]}</td><td class="num">{r.get("tokens") or 0}</td>'
        f'<td class="num">{r.get("attempts") or 0}</td></tr>' for r in rows)
    return (f'<div class="scroll"><table><thead><tr><th>任务</th><th>状态</th><th>次数</th>'
            f'<th>token</th><th>尝试</th></tr></thead><tbody>{body}</tbody></table></div>')


def _config_section() -> str:
    snap = config_snapshot()
    thr = "".join(f'<span class="tag">{theme.esc(k)} {theme.esc(v)}</span>'
                  for k, v in (snap["thresholds"] or {}).items())
    weights = "".join(
        f'<tr><td class="mono">{theme.esc(k)}</td>'
        f'<td class="mono">{" ".join(f"{a}{w}" for a, w in (v or {}).items())}</td></tr>'
        for k, v in (snap["weights"] or {}).items())
    return f"""
<h2>入选门槛 <small>config/scoring.yaml</small></h2>
<div>{thr or '<span class="muted">未配置</span>'}</div>
<p class="muted small">双次打分求和 ≥ 2×门槛；页面上显示平均分。
改门槛前先用金标跑评测（见上面的"评测"）。</p>
<h2>内容类型权重 <small>五轴：sig nov cred reson act</small></h2>
<div class="scroll"><table><tbody>{weights}</tbody></table></div>
<h2>运行参数</h2>
<ul class="list small">
  <li>评分次数/条：<b>{theme.esc(snap["score_calls"])}</b> ｜ 并发：<b>{theme.esc(snap["max_workers"])}</b></li>
  <li>understand_floor：<b>{theme.esc(snap["understand_floor"])}</b> ｜ browse_floor：<b>{theme.esc(snap["browse_floor"])}</b></li>
  <li>模型：<b>{theme.esc(snap["model"])}</b>
      {'（备用 ' + theme.esc(snap["backup_model"]) + '）' if snap.get("backup_model") else ""}</li>
  <li>预算：每天 <b>{theme.esc(snap["budget_per_day"]) or "不限"}</b> ｜ 每小时 <b>{theme.esc(snap["budget_per_hour"]) or "不限"}</b></li>
</ul>
<p class="muted small">这一页只读。要改就改 <code>config/*.yaml</code>，下一轮自动生效。</p>
"""


def _alert_section() -> str:
    rows = alerts()
    if not rows:
        return '<p class="muted">没有告警。</p>'
    lis = "".join(
        f'<li>{_pill(r["severity"], "err" if r["severity"] == "error" else "")} '
        f'<span class="mono small">{theme.esc(r["day"])}</span> {theme.esc(r["message"])}</li>'
        for r in rows)
    return f'<ul class="list">{lis}</ul>'


def render(day: str | None = None, tab: str = "runs", only: str = "all",
           split: str = "development") -> str:
    day = day or store.today_str()
    tabs = _tabs("/admin.html?tab=",
                 (("runs", "运行"), ("sources", "信源"), ("content", "内容诊断"),
                  ("better", "标注"), ("evals", "评测"), ("llm", "模型调用"),
                  ("config", "配置"), ("alerts", "告警")), tab)
    sections = {
        "runs": lambda: _run_section(day),
        "sources": _source_section,
        "content": lambda: _content_section(day, only),
        "better": lambda: _better_section(day, split),
        "evals": _eval_section,
        "llm": lambda: _llm_section(day),
        "config": _config_section,
        "alerts": _alert_section,
    }
    body = (f'<div class="tabs">{tabs}</div>' + sections.get(tab, sections["runs"])())
    doc = theme.page("后台", body, active="", lead=f"{theme.esc(day)} · 只读诊断视图")
    return doc.replace("</head>", f"<style>{_EXTRA_CSS}</style></head>", 1)


def build(site_root: Path | None = None, day: str | None = None) -> dict[str, Any]:
    """把后台写成一个静态页 —— 它自己不带写操作，所以不需要额外护栏；
    真正的护栏在 serve.py（`/admin.html` 需要口令）。"""
    root = site_root or SITE
    target = root / "admin.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(day), encoding="utf-8")
    return {"file": str(target), "bytes": target.stat().st_size}
