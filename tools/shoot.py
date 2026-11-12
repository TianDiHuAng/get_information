"""截图：用本机 Chrome 无头模式给页面拍照，肉眼验排版。

为什么需要：只对着 CSS 数值改样式，很容易"数值都对、看起来还是不对"。
这个脚本把页面渲染成 PNG，改完直接看。

用法：
    python tools/shoot.py                    # 拍一组核心页面
    python tools/shoot.py --pages /hot.html /topics.html
    python tools/shoot.py --url https://example.com --name ref
    python tools/shoot.py --width 420         # 手机宽度
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / ".shots"
CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
)
DEFAULT_PAGES = ("/", "/all.html", "/hot.html", "/daily.html", "/topics.html",
                 "/timeline.html", "/board.html", "/events.html")


def browser() -> str | None:
    for path in CANDIDATES:
        if Path(path).is_file():
            return path
    for name in ("chrome", "google-chrome", "chromium", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    return None


def shoot(exe: str, url: str, out: Path, width: int, height: int, wait_ms: int) -> bool:
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [exe, "--headless=new", "--disable-gpu", "--hide-scrollbars",
           f"--window-size={width},{height}", f"--screenshot={out}",
           f"--virtual-time-budget={wait_ms}", url]
    try:
        subprocess.run(cmd, capture_output=True, timeout=wait_ms / 1000 + 30)
    except Exception:
        return False
    return out.is_file() and out.stat().st_size > 5000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8124")
    ap.add_argument("--pages", nargs="*", default=list(DEFAULT_PAGES))
    ap.add_argument("--url", default="", help="拍单个完整地址（外站也行）")
    ap.add_argument("--name", default="", help="--url 时的文件名")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=1000)
    ap.add_argument("--wait", type=int, default=3500, help="虚拟时间预算（毫秒）")
    args = ap.parse_args()

    exe = browser()
    if not exe:
        print("没找到 Chrome / Edge，无法截图")
        return 1

    todo = [(args.name or "shot", args.url)] if args.url else [
        ((p.strip("/").replace("/", "-").replace(".html", "") or "home"), args.base.rstrip("/") + p)
        for p in args.pages]

    ok = 0
    for name, url in todo:
        out = SHOTS / f"{name}.png"
        if shoot(exe, url, out, args.width, args.height, args.wait):
            print(f"✓ {out.relative_to(ROOT)}  {out.stat().st_size // 1024} KB  ← {url}")
            ok += 1
        else:
            print(f"× {url}")
    print(f"\n{ok}/{len(todo)} 张，输出目录 {SHOTS.relative_to(ROOT)}/")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
