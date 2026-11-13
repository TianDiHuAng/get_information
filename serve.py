"""本地可视化服务：把 site/ 挂到 http://<本机IP>:8123，局域网内手机也能看。

只依赖标准库 + 项目自己的 collector 包。端口被占用（已有实例在跑）时静默退出，
所以 watchdog / 开机脚本重复拉起没有副作用。

除了静态文件，还提供两个小接口：
- `POST /api/feedback`  `{"url": "...", "kind": "up|down"}` —— 卡片上的反馈按钮
- `GET  /api/prefs`     当前学到的兴趣权重（调试用，能看出它到底学到了什么）

后台 `/admin.html` 是唯一的受保护路径：需要口令（`data/admin_token.txt`，
首次启动自动生成并在控制台打印）。后台本身是只读的，改配置请改 `config/*.yaml`。
"""

import json
import os
import socket
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("RADAR_PORT") or 8123)   # 换端口：RADAR_PORT=8124 python serve.py
SITE = Path(__file__).parent / "site"
# 反馈请求体上限：这是个本机小接口，不需要接受大包
MAX_BODY = 4096
COOKIE = "radar_admin"

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
    # 静态文件一律按 UTF-8 发，并对 html/css/js 显式声明 charset，
    # 否则浏览器按 latin-1 猜，中文全变乱码。
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".xml": "application/xml; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
    }

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

    # ---- 静态文件：能压缩就压缩 ----------------------------------------- #
    _COMPRESSIBLE = (".html", ".css", ".js", ".json", ".xml", ".txt", ".webmanifest",
                     ".svg")

    def _serve_gzip(self, path: str) -> bool:
        """文本类静态文件按 gzip 发。首页 107KB → 约 16KB。

        这里是本机站，没有 CDN 帮忙压缩；不压缩的话手机在局域网也要多等几倍。
        已压缩过的内容不缓存到磁盘（每次都小，CPU 开销可忽略）。
        """
        if "gzip" not in (self.headers.get("accept-encoding") or "").lower():
            return False
        # 只有动态接口需要跳过；/api/v1/*.json 是静态产物，照常压缩
        if path.startswith("/admin") or path in ("/api/feedback", "/api/prefs"):
            return False
        rel = path.lstrip("/") or "index.html"
        target = (SITE / rel).resolve()
        try:
            target.relative_to(SITE.resolve())
        except ValueError:
            return False                       # 越界，交给默认处理
        if target.is_dir():                    # 目录：用它的 index.html
            target = target / "index.html"
            rel = str(target.relative_to(SITE.resolve()))
        if not target.is_file() or target.suffix.lower() not in self._COMPRESSIBLE:
            return False
        try:
            raw = target.read_bytes()
        except OSError:
            return False
        if len(raw) < 1024:                    # 太小，压了反而更大
            return False
        import gzip as _gzip

        body = _gzip.compress(raw, 6)
        if len(body) >= len(raw):
            return False
        self.send_response(200)
        self.send_header("content-type", self.extensions_map.get(
            target.suffix.lower(), "application/octet-stream"))
        self.send_header("content-encoding", "gzip")
        self.send_header("content-length", str(len(body)))
        self.send_header("vary", "accept-encoding")
        self.send_header("cache-control", "no-cache")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        return True

    def send_error(self, code, message=None, explain=None):  # noqa: D401
        """404 用站点自己的页面，而不是 Python 自带的裸错误页。

        `/aidd/...` 下找不到时用子站自己的 404，牌子要对得上。
        """
        if code == 404:
            path = urlparse(self.path).path
            candidates = []
            if path.startswith("/aidd/"):
                candidates.append(SITE / "aidd" / "404.html")
            candidates.append(SITE / "404.html")
            for page in candidates:
                if not page.is_file():
                    continue
                try:
                    body = page.read_bytes()
                    self.send_response(404)
                    self.send_header("content-type", "text/html; charset=utf-8")
                    self.send_header("content-length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                except Exception:
                    continue
        return super().send_error(code, message, explain)

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if self._serve_gzip(path):
            return

        if path in ("/admin", "/admin.html"):
            return self._admin(parsed)
        if path == "/admin/login":
            return self._admin_login_page()
        if path == "/admin/logout":
            return self._redirect("/admin.html", clear_cookie=True)
        if path == "/api/prefs":
            try:
                from collector import prefs

                weights = prefs.weights()
                top = sorted(weights.items(), key=lambda kv: abs(kv[1]), reverse=True)[:20]
                return self._json({"ok": True, "terms": len(weights), "top": dict(top)})
            except Exception as e:
                return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
        return super().do_GET()

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/admin/login":
            return self._admin_login()
        if path in ("/api/source/toggle", "/api/source/preview"):
            return self._source_action(path)
        if path == "/api/gold":
            return self._gold_action()
        if path != "/api/feedback":
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

    # ---- 后台：口令 + 按需渲染 ------------------------------------------- #
    def _authed(self) -> bool:
        from collector import admin

        cookie = self.headers.get("cookie") or ""
        for part in cookie.split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE:
                return admin.check(value)
        return False

    def _html(self, doc: str, status: int = 200, extra: dict[str, str] | None = None) -> None:
        body = doc.encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, to: str, *, clear_cookie: bool = False) -> None:
        self.send_response(303)
        self.send_header("location", to)
        if clear_cookie:
            self.send_header("set-cookie", f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
        self.end_headers()

    def _admin_login_page(self, error: str = "") -> None:
        from collector import theme

        msg = f'<p class="reason">{theme.esc(error)}</p>' if error else ""
        body = (msg + '<form method="post" action="/admin/login" style="max-width:360px;">'
                '<p><input name="token" type="password" placeholder="后台口令" autofocus '
                'style="width:100%;padding:11px 13px;border:1px solid var(--rule);'
                'border-radius:10px;background:var(--card);color:var(--ink)"></p>'
                '<p><button type="submit" style="padding:9px 18px;border-radius:10px;border:0;'
                'background:var(--accent);color:#fff;font-size:14px;cursor:pointer">进入</button></p>'
                "</form>"
                '<p class="muted small">口令在 <code>data/admin_token.txt</code>；'
                "首次启动 <code>serve.py</code> 时自动生成并打印在控制台。</p>")
        self._html(theme.page("后台 · 登录", body, active="", lead="需要口令"))

    def _admin_login(self) -> None:
        from collector import admin

        try:
            length = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(min(length, MAX_BODY)).decode("utf-8") if length > 0 else ""
            token = (parse_qs(raw).get("token") or [""])[0]
        except Exception:
            token = ""
        if not admin.check(token):
            return self._admin_login_page("口令不对")
        self.send_response(303)
        self.send_header("location", "/admin.html")
        # 会话 cookie：只在本机局域网用，不设 domain，HttpOnly 防脚本读取
        self.send_header("set-cookie",
                         f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800")
        self.end_headers()

    def _source_action(self, path: str) -> None:
        """停用/启用、试抓 —— 两个都要求后台登录，且只动本机状态。"""
        if not self._authed():
            return self._json({"ok": False, "error": "unauthorized"}, 401)
        from collector import admin

        try:
            length = int(self.headers.get("content-length") or 0)
            if length <= 0 or length > MAX_BODY:
                raise ValueError("bad body size")
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception as e:
            return self._json({"ok": False, "error": f"bad request: {e}"}, 400)

        source = str(body.get("source") or "")
        if path.endswith("/toggle"):
            result = admin.toggle_source(source, bool(body.get("enabled")))
        else:
            result = admin.preview_source(source)
        self._json(result, 200 if result.get("ok") else 400)

    def _gold_action(self) -> None:
        """标注：只写 data/gold.jsonl，和人手改那个文件完全等价。"""
        if not self._authed():
            return self._json({"ok": False, "error": "unauthorized"}, 401)
        from collector import selectbench

        try:
            length = int(self.headers.get("content-length") or 0)
            if length <= 0 or length > MAX_BODY:
                raise ValueError("bad body size")
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            item_id = int(body.get("item_id") or 0)
            decision = str(body.get("decision") or "")
            split = str(body.get("split") or "development")
        except Exception as e:
            return self._json({"ok": False, "error": f"bad request: {e}"}, 400)

        result = (selectbench.clear(item_id) if decision == "clear"
                  else selectbench.label(item_id, decision, split=split))
        self._json(result, 200 if result.get("ok") else 400)

    def _admin(self, parsed) -> None:
        if not self._authed():
            return self._admin_login_page("请先输入口令")
        from collector import admin

        query = parse_qs(parsed.query or "")
        tab = (query.get("tab") or ["runs"])[0]
        only = (query.get("only") or ["all"])[0]
        split = (query.get("split") or ["development"])[0]
        report = (query.get("report") or [None])[0]
        model = (query.get("model") or [None])[0]
        outcome = (query.get("outcome") or ["all"])[0]
        stratum = (query.get("stratum") or ["all"])[0]
        disagree = bool(query.get("disagree"))
        try:
            doc = admin.render(tab=tab, only=only, split=split, report=report,
                               model=model, outcome=outcome, stratum=stratum,
                               disagree=disagree)
        except Exception as e:
            doc = f"<pre>后台渲染失败：{e}</pre>"
        self._html(doc)


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


# ---- 每日自动采集 ------------------------------------------------------ #
# 计划任务需要管理员权限，这台机器上注册被拒；改成 serve.py 常驻时自带调度：
# 每天 09:00 之后第一次检查就触发一次，靠 data/last_daily.txt 防止重复跑。
DAILY_AT = 9
DAILY_STAMP = Path(__file__).parent / "data" / "last_daily.txt"


def _daily_scheduler() -> None:
    import subprocess
    import time
    from datetime import datetime

    while True:
        try:
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            done = DAILY_STAMP.read_text(encoding="utf-8").strip() if DAILY_STAMP.is_file() else ""
            if now.hour >= DAILY_AT and done != today:
                DAILY_STAMP.parent.mkdir(parents=True, exist_ok=True)
                DAILY_STAMP.write_text(today, encoding="utf-8")
                log = Path(__file__).parent / "logs" / f"run-{now.strftime('%Y%m%d')}.log"
                log.parent.mkdir(parents=True, exist_ok=True)
                with open(log, "a", encoding="utf-8") as fh:
                    fh.write(f"[{now:%Y-%m-%d %H:%M}] 定时触发\n")
                    subprocess.run([sys.executable, "run.py", "--no-mail", "--dry-push"],
                                   cwd=str(Path(__file__).parent), stdout=fh,
                                   stderr=subprocess.STDOUT, timeout=7200)
                    subprocess.run([sys.executable, "tools/build_sites.py", "--site", "site",
                                    "--data", "data", "--db", "data/radar.db"],
                                   cwd=str(Path(__file__).parent), stdout=fh,
                                   stderr=subprocess.STDOUT, timeout=1800)

                    # AIDD 站：独立的数据/库/站点目录，跑完单独建站
                    env_aidd = dict(os.environ)
                    env_aidd.update({
                        "RADAR_PACK": "aidd",
                        "RADAR_DB": "data/aidd.db",
                        "RADAR_DATA": "data-aidd",
                        "RADAR_SITE": "site/aidd",
                    })
                    fh.write(f"[{datetime.now():%Y-%m-%d %H:%M}] AIDD 开始\n")
                    subprocess.run([sys.executable, "run.py", "--no-mail", "--dry-push"],
                                   cwd=str(Path(__file__).parent), env=env_aidd, stdout=fh,
                                   stderr=subprocess.STDOUT, timeout=7200)
                    subprocess.run([sys.executable, "tools/build_sites.py", "--site", "site/aidd",
                                    "--data", "data-aidd", "--db", "data/aidd.db",
                                    "--base", "/aidd"],
                                   cwd=str(Path(__file__).parent), env=env_aidd, stdout=fh,
                                   stderr=subprocess.STDOUT, timeout=1800)
                    fh.write(f"[{datetime.now():%Y-%m-%d %H:%M}] AIDD 完成\n")
                    fh.write(f"[{datetime.now():%Y-%m-%d %H:%M}] 定时完成\n")
        except Exception:
            pass
        time.sleep(300)          # 每 5 分钟看一次，跨过 09:00 就触发


def main() -> None:
    if already_running():
        print(f"端口 {PORT} 已有实例在服务，本进程退出")
        return
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    except OSError:
        print(f"端口 {PORT} 绑定失败，可视化服务应已在运行")
        return
    # 只有在真正成为服务进程时才启动每日调度，避免多进程重复跑
    threading.Thread(target=_daily_scheduler, daemon=True).start()
    print("Z-Bit已上线：")
    print(f"  本机    http://localhost:{PORT}")
    print(f"  局域网  http://{lan_ip()}:{PORT}   （手机需连同一 Wi-Fi）")
    srv.serve_forever()


if __name__ == "__main__":
    main()
