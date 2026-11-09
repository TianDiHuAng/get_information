"""把微博/知乎的 Cookie 安全写进 config/cookies.yaml。

用法（在项目根目录）：
    D:\\Anaconda\\python.exe tools\\set_cookie.py weibo
    D:\\Anaconda\\python.exe tools\\set_cookie.py zhihu

为什么要用脚本：Cookie 等于登录态，直接贴在聊天里会留在记录中。
脚本用隐藏输入，只写本地文件，不回显、不上传。
"""

from __future__ import annotations

import getpass
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONF = ROOT / "config" / "cookies.yaml"

HEADER = """# 微博 / 知乎 登录 Cookie
# 由 tools/set_cookie.py 写入；程序只在请求时带上，不会外传。
# 失效后重新运行一次脚本即可。

weibo:
  cookie: "{weibo}"

zhihu:
  cookie: "{zhihu}"
"""


def _load() -> dict:
    text = CONF.read_text(encoding="utf-8") if CONF.exists() else ""
    out = {"weibo": "", "zhihu": ""}
    for name in ("weibo", "zhihu"):
        m = re.search(rf'{name}:\s*\n\s*cookie:\s*"([^"]*)"', text)
        if m:
            out[name] = m.group(1)
    return out


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("weibo", "zhihu"):
        print("用法: python tools/set_cookie.py [weibo|zhihu]")
        print("  可选第二个参数 --clear 清空")
        raise SystemExit(2)

    name = sys.argv[1]
    data = _load()

    if "--clear" in sys.argv[2:]:
        data[name] = ""
        CONF.write_text(HEADER.format(**data), encoding="utf-8")
        print(f"已清空 {name} 的 Cookie")
        return

    if sys.stdin.isatty():
        value = getpass.getpass(f"粘贴 {name} 的 Cookie（输入不回显，粘贴后回车）: ").strip()
    else:
        value = sys.stdin.readline().strip()

    if not value:
        print("没有输入，未修改")
        raise SystemExit(1)

    data[name] = value.replace('"', "")
    CONF.write_text(HEADER.format(**data), encoding="utf-8")
    print(f"已保存 {name} Cookie（{len(data[name])} 字符）。下一轮采集生效。")
    print("验证：python -c \"from collector.sources import WEIBO_COOKIE, ZHIHU_COOKIE; print(bool(WEIBO_COOKIE), bool(ZHIHU_COOKIE))\"")


if __name__ == "__main__":
    main()
