"""提交前自检：扫描会被 git 跟踪的文件里是否有 token / 密码 / cookie。

用法：
    python tools/scan_secrets.py
有命中则退出码 1。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

PATTERNS = [
    (re.compile(r"apify_api_[A-Za-z0-9]{20,}"), "Apify token"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}"), "OpenAI 风格 key"),
    (re.compile(r'auth_code\s*:\s*"[^"\s]{8,}"'), "邮箱授权码"),
    (re.compile(r'cookie\s*:\s*"[^"\s]{20,}"'), "Cookie"),
    (re.compile(r"(api_key|password|secret)\s*:\s*\"[^\"\s]{12,}\""), "疑似密钥字段"),
]

ALLOW = {"tools/scan_secrets.py", "tools/set_secret.py", "tools/set_cookie.py"}


def tracked_files() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout
        return [f for f in out.splitlines() if f.strip()]
    except Exception:
        # 非 git 仓库：扫工作区，跳过被忽略的目录
        skip = (".git", "data", "logs", "site", "__pycache__", ".venv", "node_modules", "research")
        files = []
        for p in ROOT.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(ROOT).as_posix()
            if any(rel.startswith(s + "/") or rel == s for s in skip):
                continue
            files.append(rel)
        return files


def main() -> None:
    hits = []
    for rel in tracked_files():
        if rel in ALLOW:
            continue
        p = ROOT / rel
        if p.suffix.lower() not in (".py", ".yaml", ".yml", ".json", ".md", ".bat", ".txt", ".ps1", ""):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for rx, label in PATTERNS:
            m = rx.search(text)
            if m:
                hits.append((rel, label, m.group(0)[:12] + "…"))

    if not hits:
        print("✅ 未发现明文密钥")
        return
    print("❌ 发现疑似密钥，请改用 example + 本地文件：")
    for rel, label, sample in hits:
        print(f"  - {rel}  [{label}]  {sample}")
    sys.exit(1)


if __name__ == "__main__":
    main()
