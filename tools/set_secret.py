"""把 API Token 安全写进 config/secrets.yaml（隐藏输入，不回显、不进聊天记录）。

用法：
    D:\\Anaconda\\python.exe tools\\set_secret.py apify
"""

from __future__ import annotations

import getpass
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONF = ROOT / "config" / "secrets.yaml"

KEYS = {"apify": "apify_token", "apify2": "apify_token_2", "apify3": "apify_token_3", "mail": "mail_password"}
HEADER = """# 各类 API Token（不要手抄进聊天）
# 写入方式：D:\\Anaconda\\python.exe tools\\set_secret.py apify

"""


def _load() -> dict:
    text = CONF.read_text(encoding="utf-8") if CONF.exists() else ""
    out = {v: "" for v in KEYS.values()}
    for k, field in KEYS.items():
        m = re.search(rf'{field}:\s*"([^"]*)"', text)
        if m:
            out[field] = m.group(1)
    return out


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in KEYS:
        print("用法: python tools/set_secret.py [apify]")
        print("  可选第二个参数 --clear 清空")
        raise SystemExit(2)

    field = KEYS[sys.argv[1]]
    data = _load()

    if "--clear" in sys.argv[2:]:
        data[field] = ""
    else:
        if sys.stdin.isatty():
            value = getpass.getpass(f"粘贴 {sys.argv[1]} token（输入不回显）: ").strip()
        else:
            value = sys.stdin.readline().strip()
        if not value:
            print("没有输入，未修改")
            raise SystemExit(1)
        data[field] = value.replace('"', "")

    lines = [HEADER.rstrip(), ""]
    for f in KEYS.values():
        lines.append(f'{f}: "{data[f]}"')
    CONF.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已保存 {sys.argv[1]} token（{len(data[field])} 字符）。")


if __name__ == "__main__":
    main()
