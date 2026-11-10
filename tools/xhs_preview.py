import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
src = root / "data" / "xhs" / "2026-11-10-arxiv.md"
text = src.read_text(encoding="utf-8")


def block(start: str, end: str) -> str:
    if start not in text:
        return ""
    seg = text.split(start, 1)[1]
    if end and end in seg:
        seg = seg.split(end, 1)[0]
    return seg.strip()


cover = re.findall(r"^\*\*(.+?)\*\*$", block("## 封面文案", "## 标题"), re.M)
titles = re.findall(r"^\d+\.\s*(.+?)（\d+ 字）", block("## 标题", "## 正文"), re.M)
body = block("## 正文", "## 标签")
tags = block("## 标签", "\n---").splitlines()[0].strip()

paras = [p.strip() for p in body.split("\n") if p.strip()]
html_p = []
for p in paras:
    if re.match(r"^[\U0001F300-\U0001FAFF\u2600-\u27BF]", p) and len(p) < 24:
        html_p.append(f'<p class="h">{p}</p>')
    elif p.startswith("·"):
        html_p.append(f'<p class="li">{p}</p>')
    else:
        html_p.append(f"<p>{p}</p>")

big = cover[0] if cover else ""
for kw in ("ADMET", "GLP", "SAE", "ESM-2", "ESM2"):
    if kw in big:
        big = big.replace(kw, f"<em>{kw}</em>")
        break

html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#f4f5f7;padding:30px;display:flex;gap:26px;justify-content:center;
     align-items:flex-start;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}}
.cover{{width:300px;height:400px;border-radius:16px;flex:0 0 auto;padding:30px 24px;color:#fff;
  background:linear-gradient(160deg,#12233f 0%,#274875 55%,#3a6ea5 100%);
  display:flex;flex-direction:column;justify-content:space-between;position:relative;overflow:hidden;
  box-shadow:0 10px 30px rgba(18,35,63,.28)}}
.cover::after{{content:"";position:absolute;right:-70px;top:-70px;width:210px;height:210px;
  border-radius:50%;background:rgba(120,190,255,.16)}}
.cover .kicker{{font-size:11px;letter-spacing:.16em;color:#9fc6f5}}
.cover .big{{font-size:32px;font-weight:800;line-height:1.35;margin-top:16px;text-shadow:0 2px 12px rgba(0,0,0,.28)}}
.cover .big em{{font-style:normal;color:#ffd66b}}
.cover .sub{{font-size:14px;line-height:1.75;color:#d6e6f8}}
.cover .foot{{font-size:11px;color:#8fb3dc;margin-top:12px}}
.card{{width:430px;background:#fff;border-radius:14px;padding:22px 24px 26px;box-shadow:0 2px 16px rgba(0,0,0,.07)}}
.card h3{{margin:0 0 4px;font-size:17px;line-height:1.45;color:#161616}}
.meta{{font-size:12px;color:#9aa0a6;margin-bottom:14px}}
.card p{{margin:0 0 11px;font-size:14.5px;line-height:1.85;color:#333}}
.card p.h{{font-weight:700;color:#111;margin-top:17px;margin-bottom:5px;font-size:15px}}
.card p.li{{padding-left:12px;color:#444}}
.tags{{margin-top:16px;font-size:13px;color:#13386e;line-height:1.9}}
.alt{{width:250px;background:#fff;border-radius:14px;padding:18px 20px;box-shadow:0 2px 16px rgba(0,0,0,.07)}}
.alt h4{{margin:0 0 10px;font-size:13px;color:#9aa0a6}}
.alt li{{font-size:13px;line-height:1.65;color:#444;margin-bottom:9px;list-style:none}}
</style></head><body>
<div class="cover">
  <div>
    <div class="kicker">AI × DRUG DISCOVERY</div>
    <div class="big">{big}</div>
  </div>
  <div>
    <div class="sub">{'<br>'.join(cover[1:])}</div>
    <div class="foot">信息雷达 · arXiv 深度精读</div>
  </div>
</div>
<div class="card">
  <h3>{titles[0] if titles else ''}</h3>
  <div class="meta">arXiv 深度稿 · 主打 1 篇 + 顺带 2 篇</div>
  {''.join(html_p)}
  <div class="tags">{tags}</div>
</div>
<div class="alt">
  <h4>备选标题</h4>
  <ul>{''.join(f'<li>{t}</li>' for t in titles[1:])}</ul>
  <h4 style="margin-top:16px">字数</h4>
  <div style="font-size:13px;color:#444">{len(body)} 字（小红书上限 1000）</div>
</div>
</body></html>"""

out = root / "data" / "xhs" / "_preview.html"
out.write_text(html, encoding="utf-8")
print("preview:", out, "|", len(body), "字")
