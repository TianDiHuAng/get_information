"""抽取 arXiv 论文里的插图，供小红书卡片使用。

论文自带的架构图、结果图比任何网图都有说服力，
所以图卡直接用原文 Figure，并保留 caption。
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

from .net import get_text, session

CACHE_DIR = Path(__file__).parent.parent / "data" / "xhs" / "figs"
INDEX = Path(__file__).parent.parent / "data" / "xhs" / "figs" / "index.json"

SKIP_WORDS = ("table", "算法", "algorithm")


def _index() -> dict:
    if not INDEX.exists():
        return {}
    try:
        return json.loads(INDEX.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_index(d: dict) -> None:
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def _clean_caption(text: str) -> str:
    t = re.sub(r"^Figure\s*\d+\s*[:：]\s*", "", text or "", flags=re.I)
    t = re.sub(r"\\(alpha|beta|rho|times|cdot|sim|approx|leq|geq)", "", t)
    t = re.sub(r"[{}]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def fetch_figures(paper_id: str, limit: int = 3, min_kb: int = 12) -> list[dict]:
    """返回 [{path, caption, w, h}]，本地已下载。失败返回空列表。"""
    cache = _index()
    if paper_id in cache:
        items = cache[paper_id]
        if all(Path(i["path"]).exists() for i in items):
            return items

    try:
        html = get_text(f"https://arxiv.org/html/{paper_id}v1", timeout=45)
    except Exception:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out_dir = CACHE_DIR / paper_id
    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"https://arxiv.org/html/{paper_id}v1/"
    items: list[dict] = []

    for fig in soup.find_all("figure"):
        if len(items) >= limit:
            break
        img = fig.find("img")
        src = (img.get("src") if img else "") or ""
        if not src or src.endswith(".svg"):
            continue
        cap = _clean_caption(
            (fig.find("figcaption").get_text(" ", strip=True) if fig.find("figcaption") else "")
        )
        if any(w in cap.lower() for w in SKIP_WORDS):
            continue
        fname = src.split("/")[-1]
        dst = out_dir / fname
        if not dst.exists():
            try:
                with session() as s:
                    r = s.get(base + src.split("/", 1)[-1], timeout=60)
                    r.raise_for_status()
                if len(r.content) < min_kb * 1024:
                    continue
                dst.write_bytes(r.content)
            except Exception:
                continue
        try:
            from PIL import Image

            with Image.open(dst) as im:
                w, h = im.size
        except Exception:
            w = h = 0
        if not w or h < 120:
            continue
        items.append({"path": str(dst), "caption": cap[:120], "w": w, "h": h})

    cache[paper_id] = items
    _save_index(cache)
    return items


def data_uri(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    b64 = base64.b64encode(p.read_bytes()).decode()
    ext = p.suffix.lower().lstrip(".").replace("jpg", "jpeg")
    return f"data:image/{ext};base64,{b64}"


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    pid = sys.argv[1] if len(sys.argv) > 1 else "2611.09818"
    for f in fetch_figures(pid):
        print(f"{f['w']}x{f['h']}  {Path(f['path']).name}  | {f['caption'][:70]}")
