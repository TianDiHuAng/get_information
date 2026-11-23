"""把构建好的静态站加工成 GitHub Pages 可发布版本。

用途：求职演示站。做三件事：
  1. 修掉模板里漏掉 base 的裸绝对路径（logo / aidd / admin）
  2. 去掉后台入口（公开演示站不该出现 /admin.html）
  3. 去掉 AIDD 子站入口（发布版只构建 AI 站，没构建 /aidd/）
  4. 移除 admin.html 本身（里面有后台逻辑，不需要公开）

输入：python tools/publish_ghpages.py --site <构建目录> --base /get_information
不会改仓库里的 site/，只在传入的目录上原地处理。
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True, help="构建好的静态站目录")
    ap.add_argument("--base", required=True, help="GitHub Pages 子路径，如 /get_information")
    ap.add_argument("--keep-admin", action="store_true", help="保留后台入口与 admin.html（默认去掉）")
    ap.add_argument("--keep-aidd", action="store_true", help="保留 AIDD 子站入口（默认去掉）")
    args = ap.parse_args()

    root = Path(args.site)
    base = args.base.rstrip("/")
    if not root.is_dir():
        raise SystemExit(f"目录不存在: {root}")

    patched = 0
    for page in root.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        original = text

        # 裸 logo 路径 → 加 base（这些是导航模板里的，build_sites 没套上）
        text = re.sub(r'(src|href)="/(logo-[^"]+)"', rf'\1="{base}/\2"', text)

        if not args.keep_admin:
            text = text.replace('href="/admin.html"', f'href="{base}/about.html"')
        if not args.keep_aidd:
            text = text.replace('href="/aidd/"', f'href="{base}/"')

        if text != original:
            page.write_text(text, encoding="utf-8")
            patched += 1

    removed = []
    if not args.keep_admin:
        admin = root / "admin.html"
        if admin.exists():
            admin.unlink()
            removed.append("admin.html")

    print(f"处理 HTML {patched} 个，移除 {removed or '无'}，base={base}")


if __name__ == "__main__":
    main()
