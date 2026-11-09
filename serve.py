"""本地可视化服务：把 site/ 挂到 http://<本机IP>:8123，局域网内手机也能看。

只依赖标准库。端口被占用（已有实例在跑）时静默退出，
所以 watchdog / 开机脚本重复拉起没有副作用。
"""

import os
import socket
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8123
SITE = Path(__file__).parent / "site"

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
