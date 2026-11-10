"""本地可视化服务：把 site/ 挂到 http://<本机IP>:8123，局域网内手机也能看。

只依赖标准库 + 项目自己的 collector 包。端口被占用（已有实例在跑）时静默退出，
所以 watchdog / 开机脚本重复拉起没有副作用。

除了静态文件，还提供两个小接口：
- `POST /api/feedback`  `{"url": "...", "kind": "up|down"}` —— 卡片上的反馈按钮
- `GET  /api/prefs`     当前学到的兴趣权重（调试用，能看出它到底学到了什么）
"""

import json
import os
import socket
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8123
SITE = Path(__file__).parent / "site"
# 反馈请求体上限：这是个本机小接口，不需要接受大包
MAX_BODY = 4096

if sys.stdout is None:  # pythonw 静默运行时没有 stdout
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
else:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # 不真正发包，只为拿到选中的出口网卡
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kw):
        super().__init__(*args, directory=str(SITE), **kw)

    def log_message(self, *args):  # 常驻运行，别刷控制台
        pass

    # ---- 小接口 ---------------------------------------------------------- #
    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.split("?")[0].rstrip("/") == "/api/prefs":
            try:
                from collector import prefs

                weights = prefs.weights()
                top = sorted(weights.items(), key=lambda kv: abs(kv[1]), reverse=True)[:20]
                return self._json({"ok": True, "terms": len(weights), "top": dict(top)})
            except Exception as e:
                return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
        return super().do_GET()

    def do_POST(self):  # noqa: N802
        if self.path.split("?")[0].rstrip("/") != "/api/feedback":
            return self._json({"ok": False, "error": "not found"}, 404)
        try:
            length = int(self.headers.get("content-length") or 0)
            if length <= 0 or length > MAX_BODY:
                raise ValueError("bad body size")
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            from collector import prefs

            result = prefs.record(str(payload.get("url") or ""), str(payload.get("kind") or ""))
        except Exception as e:
            result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        self._json(result, 200 if result.get("ok") else 400)


def already_running() -> bool:
    """探测本机端口是否已有实例在服务。

    不用"绑定失败"来判断：Windows 的 SO_REUSEADDR 允许重复绑定同一端口，
    靠 bind 报错发现不了已有实例。
    """
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", PORT))
        return True
    except OSError:
        return False
    finally:
        s.close()


def main() -> None:
    if already_running():
        print(f"端口 {PORT} 已有实例在服务，本进程退出")
        return
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    except OSError:
        print(f"端口 {PORT} 绑定失败，可视化服务应已在运行")
        return
    print("信息雷达已上线：")
    print(f"  本机    http://localhost:{PORT}")
    print(f"  局域网  http://{lan_ip()}:{PORT}   （手机需连同一 Wi-Fi）")
    srv.serve_forever()


if __name__ == "__main__":
    main()
