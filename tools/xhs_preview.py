import json
import re
from pathlib import Path

root = Path(".")


def load(path: str, sec_end: str) -> tuple[str, list[str], str, list[str]]:
    t = (root / path).read_text(encoding="utf-8")
    cover = re.findall(r"^\*\*(.+?)\*\*$", t.split("## 封面文案")[1].split("## 标题")[0], re.M)
    titles = re.findall(r"^\d+\. (.+?)\s+（", t.split("## 标题")[1].split("## 正文")[0], re.M)
    body = t.split("## 正文（直接复制，不要带 Markdown）")[1].split(sec_end)[0].strip()
    tags = t.split("## 标签")[1].split("\n")[1].strip()
    return cover, titles, body, tags


cover, titles, body, tags = load("data/xhs/2026-11-10-arxiv.md", "## 标签")

paras = [p.strip() for p in body.split("\n") if p.strip()]
body_html = []
for p in paras:
    if len(p) < 30 and not p.endswith(("。", "？", "！")):
        body_html.append(f'<p class="h">{p}</p>')
    else:
        body_html.append(f'<p>{p}</p>')

html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#f2f3f5;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
      display:flex;gap:28px;justify-content:center;padding:28px;align-items:flex-start}}
.cover{{width:300px;height:400px;border-radius:16px;flex:0 0 auto;
  background:linear-gradient(160deg,#1b2a4a 0%,#2d4a7c 55%,#3f6ba8 100%);
  color:#fff;padding:30px 24px;display:flex;flex-direction:column;justify-content:space-between;
  box-shadow:0 8px 28px rgba(20,35,60,.28);position:relative;overflow:hidden}}
.cover::after{{content:"";position:absolute;right:-60px;top:-60px;width:200px;height:200px;
  border-radius:50%;background:rgba(120,190,255,.18)}}
.cover .tag{{font-size:11px;letter-spacing:.14em;color:#9fc6f5;text-transform:uppercase}}
.cover .big{{font-size:33px;font-weight:800;line-height:1.34;letter-spacing:-.5px;
  text-shadow:0 2px 14px rgba(0,0,0,.25)}}
.cover .big em{{font-style:normal;color:#ffd66b}}
.cover .sub{{font-size:14px;color:#cfe2f8;line-height:1.7}}
.cover .foot{{font-size:11px;color:#8fb3dc;letter-spacing:.06em}}
.card{{width:420px;background:#fff;border-radius:14px;padding:22px 24px 26px;
  box-shadow:0 2px 14px rgba(0,0,0,.06)}}
.card h3{{margin:0 0 4px;font-size:17px;line-height:1.45;color:#1a1a1a}}
.meta{{font-size:12px;color:#9aa0a6;margin-bottom:16px}}
.card p{{margin:0 0 12px;font-size:14.5px;line-height:1.85;color:#333}}
.card p.h{{font-weight:700;color:#111;margin-top:18px;margin-bottom:6px}}
.tags{{margin-top:18px;font-size:13px;color:#13386e;line-height:2}}
.alt{{width:250px;background:#fff;border-radius:14px;padding:18px 20px;box-shadow:0 2px 14px rgba(0,0,0,.06)}}
.alt h4{{margin:0 0 10px;font-size:13px;color:#9aa0a6;font-weight:600}}
.alt li{{font-size:13px;line-height:1.7;color:#444;margin-bottom:8px;list-style:none}}
</style></head><body>
<div class="cover">
  <div>
    <div class="tag">AI × Drug Discovery</div>
    <div class="big" style="margin-top:18px">{cover[0].replace('ADMET','<em>ADMET</em>')}</div>
  </div>
  <div>
    <div class="sub">{cover[1] if len(cover)>1 else ''}<br>{cover[2] if len(cover)>2 else ''}</div>
    <div class="foot" style="margin-top:14px">信息雷达 · 每日 arXiv 精选</div>
  </div>
</div>
<div class="card">
  <h3>{titles[0]}</h3>
  <div class="meta">AI 制药 · 6 篇新论文 · 2026-11-10</div>
  {''.join(body_html)}
  <div class="tags">{tags}</div>
</div>
<div class="alt">
  <h4>备选标题</h4>
  <ul>{''.join(f'<li>{t}</li>' for t in titles[1:])}</ul>
</div>
</body></html>"""

out = root / "data" / "xhs" / "_preview.html"
out.write_text(html, encoding="utf-8")
print("preview:", out)
