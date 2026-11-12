"""一次重建两站，避免只重建主站、子站留旧版。

之前反复出现「改了 board/主题，只跑了 --site site，AIDD 还是旧版」的情况。
这个脚本就是两条命令的合体：

    python tools/build_both.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], env: dict[str, str] | None = None) -> int:
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run([sys.executable, *args], cwd=str(ROOT), env=e).returncode


def main() -> int:
    code = run(["tools/build_sites.py", "--site", "site", "--data", "data",
                "--db", "data/radar.db"])
    if code != 0:
        return code
    return run(["tools/build_sites.py", "--site", "site/aidd", "--data", "data-aidd",
                "--db", "data/aidd.db", "--base", "/aidd"], {"RADAR_PACK": "aidd"})


if __name__ == "__main__":
    raise SystemExit(main())
