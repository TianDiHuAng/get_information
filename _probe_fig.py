import sys

import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
pid = "2611.09818"
r = requests.get(f"https://arxiv.org/html/{pid}v1", headers={"User-Agent": "Mozilla/5.0"}, timeout=40)
print("html", r.status_code, len(r.text))
soup = BeautifulSoup(r.text, "html.parser")

figs = soup.find_all("figure")
print("figures:", len(figs))
for i, f in enumerate(figs[:8]):
    img = f.find("img")
    cap = f.find("figcaption")
    print(f"\n[{i}] img src: {(img.get('src') if img else None)}")
    print(f"    alt: {(img.get('alt') if img else '')[:70]}")
    print(f"    caption: {cap.get_text(' ', strip=True)[:110] if cap else '-'}")

# 也看看有没有 table 图/公式图
print("\nall img count:", len(soup.find_all("img")))
