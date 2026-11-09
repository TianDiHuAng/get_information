"""每日归档：A) 条目快照  B) 静态页归档。

为什么要有这一层：
items.json / index.html 每轮都覆盖，三个月后就查不到"那天到底抓到过什么"。
这里在每轮结束时额外存两份按日期命名的副本：

  data/daily/items-YYYY-MM-DD.json   当天全量条目（可回溯、可重渲染）
  site/archive/YYYY-MM-DD.html       当天页面快照（手机可直接翻）

同日多轮只保留最后一版（与 digest-YYYY-MM-DD.md 的行为一致）。
另生成 site/archive/index.html 作为归档目录页。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path


def _count_items(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return f"{len(data.get('items', []))} 条"
    except Exception:
        return "—"


def _rebuild_index(arch_dir: Path, daily_dir: Path) -> None:
    files = sorted((p for p in arch_dir.glob("*.html") if p.stem != "index"), reverse=True)
    rows = []
    for p in files:
        day = p.stem
        size_kb = max(1, round(p.stat().st_size / 1024))
        rows.append(
            f'<li><a href="{day}.html"><b>{day}</b>'
            f'<span>{_count_items(daily_dir / f"items-{day}.json")} · {size_kb} KB</span></a></li>'
        )
    body = "\n".join(rows) or '<li class="empty">还没有归档</li>'
    doc = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>情报雷达 · 历史归档</title>
<style>
  :root{{color-scheme:dark}} *{{box-sizing:border-box}}
  body{{margin:0;background:#0b0f14;color:#e6edf3;font:15px/1.6 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}}
  .wrap{{max-width:760px;margin:0 auto;padding:48px 20px 80px}}
  h1{{font-size:26px;margin:0 0 6px}}
  .sub{{color:#8b98a5;font-size:13px;margin-bottom:26px}}
  a.back{{color:#7dd3fc;text-decoration:none;font-size:13px}}
  ul{{list-style:none;padding:0;margin:22px 0 0;border-top:1px solid #1a2331}}
  li{{border-bottom:1px solid #1a2331}}
  li a{{display:flex;justify-content:space-between;gap:12px;padding:14px 4px;color:#e6edf3;text-decoration:none}}
  li a:hover{{background:#0f151d;color:#7dd3fc}}
  li b{{font-weight:600;font-variant-numeric:tabular-nums}}
  li span{{color:#6b7785;font-size:12px}}
  li.empty{{color:#6b7785;padding:14px 4px}}
</style></head>
<body><div class="wrap">
  <h1>历史归档</h1>
  <div class="sub">每天一份页面快照 + 全量条目。点日期回看当天。</div>
  <a class="back" href="/">← 返回今日</a>
  <ul>{body}</ul>
</div></body></html>"""
    (arch_dir / "index.html").write_text(doc, encoding="utf-8")


def save(payload: dict, site_index: Path, root: Path, day: str) -> dict:
    """存当天条目快照与页面副本，并刷新归档目录。失败不抛异常。"""
    out = {"page": "", "snapshot": ""}
    try:
        arch_dir = root / "site" / "archive"
        arch_dir.mkdir(parents=True, exist_ok=True)
        page = arch_dir / f"{day}.html"
        shutil.copyfile(site_index, page)
        out["page"] = str(page)

        daily_dir = root / "data" / "daily"
        daily_dir.mkdir(parents=True, exist_ok=True)
        snap = daily_dir / f"items-{day}.json"
        snap.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        out["snapshot"] = str(snap)

        _rebuild_index(arch_dir, daily_dir)
    except Exception as e:
        print(f"  [archive] 归档失败: {type(e).__name__}: {e}")
    return out
