"""移动端截图：用 CDP 的 device emulation，绕开 Chrome 无头窗口最小宽度。

为什么需要单独一个脚本：headless Chrome 的 `--window-size` 在 Windows 上会被
钳到约 500px（实测 390 请求 → 489 实际视口）。于是截出来的"手机图"是把
489px 的渲染裁成 390px，右边被切掉，看起来像布局溢出 —— 其实是测试假象。

CDP 的 Emulation.setDeviceMetricsOverride 才能真正把 CSS 视口设成 390。

用法：
    python tools/shoot_mobile.py                # 默认 390x844，拍一组页面
    python tools/shoot_mobile.py --width 360 --pages / /hot.html
    python tools/shoot_mobile.py --probe        # 只量宽度，不出图
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / ".shots"
CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
)
PAGES = ("/", "/all.html", "/hot.html", "/daily.html", "/topics.html")


def browser() -> str | None:
    for p in CANDIDATES:
        if Path(p).is_file():
            return p
    for name in ("chrome", "google-chrome", "chromium"):
        f = shutil.which(name)
        if f:
            return f
    return None


class CDP:
    def __init__(self, ws_url: str):
        import websocket

        self.ws = websocket.create_connection(ws_url, timeout=30)
        self.n = 0

    def send(self, method: str, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})

    def eval(self, expr: str):
        r = self.send("Runtime.evaluate", expression=expr, returnByValue=True)
        return (r.get("result") or {}).get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


MEASURE = """(() => {
  const w = el => el ? Math.round(el.getBoundingClientRect().width) : -1;
  return {
    vw: document.documentElement.clientWidth,
    scrollW: document.documentElement.scrollWidth,
    body: w(document.body),
    shell: w(document.querySelector('.shell')),
    page: w(document.querySelector('.page')),
    card: w(document.querySelector('.cardrow')),
    overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth
  };
})()"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8124")
    ap.add_argument("--pages", nargs="*", default=list(PAGES))
    ap.add_argument("--width", type=int, default=390)
    ap.add_argument("--height", type=int, default=844)
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--probe", action="store_true")
    args = ap.parse_args()

    exe = browser()
    if not exe:
        print("没找到浏览器")
        return 1

    proc = subprocess.Popen(
        [exe, "--headless=new", "--disable-gpu", "--remote-debugging-port=9333",
         "--user-data-dir=" + str(ROOT / ".shots" / "_chrome_profile"), "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        for _ in range(40):
            try:
                with urllib.request.urlopen("http://127.0.0.1:9333/json", timeout=2) as r:
                    tabs = json.load(r)
                page = next((t for t in tabs if t.get("type") == "page"), None)
                if page:
                    ws_url = page["webSocketDebuggerUrl"]
                    break
            except Exception:
                time.sleep(0.25)
        if not ws_url:
            print("连不上调试端口")
            return 1

        cdp = CDP(ws_url)
        cdp.send("Page.enable")
        cdp.send("Runtime.enable")
        cdp.send("Emulation.setDeviceMetricsOverride", width=args.width, height=args.height,
                 deviceScaleFactor=args.scale, mobile=True)
        SHOTS.mkdir(parents=True, exist_ok=True)

        ok = 0
        for p in args.pages:
            name = p.strip("/").replace("/", "-").replace(".html", "") or "home"
            url = args.base.rstrip("/") + p
            cdp.send("Page.navigate", url=url)
            time.sleep(1.8)
            m = cdp.eval(MEASURE) or {}
            flag = "⚠ 溢出" if (m.get("overflow") or 0) > 1 else "✓"
            print(f"{p:<16} vw={m.get('vw')} scrollW={m.get('scrollW')} {flag}")
            if not args.probe:
                shot = cdp.send("Page.captureScreenshot", format="png")
                out = SHOTS / f"m-{name}.png"
                out.write_bytes(base64.b64decode(shot["data"]))
                ok += 1
        cdp.close()
        print(f"\n{ok} 张 → {SHOTS.name}/")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
