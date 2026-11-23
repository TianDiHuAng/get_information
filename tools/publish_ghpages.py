"""把构建好的静态站加工成 GitHub Pages 可发布版本。

用途：求职演示站。做四件事：
  1. 修掉模板里漏掉 base 的裸绝对路径（根路径 "/" / logo / aidd）
  2. 去掉后台入口（公开演示站不该出现 /admin.html）
  3. 把 AIDD 子站入口指向真正的子站（而不是首页）
  4. 移除 admin.html 本身

用法（AI 主站）：
  python tools/publish_ghpages.py --site <AI站目录> --base /get_information
用法（AIDD 子站，输出到 AI 站的 aidd/ 子目录前先单独加工）：
  python tools/publish_ghpages.py --site <AIDD站目录> --base /get_information/aidd --aidd-mode

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
    ap.add_argument("--aidd-mode", action="store_true", help="处理的是 AIDD 子站：注入返回 AI 主站的切换器")
    ap.add_argument("--ai-base", default="/get_information", help="AIDD 模式下 AI 主站的 base")
    args = ap.parse_args()

    root = Path(args.site)
    base = args.base.rstrip("/")
    if not root.is_dir():
        raise SystemExit(f"目录不存在: {root}")

    patched = 0
    for page in root.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        original = text

        # 裸根路径 "/"（导航里的「AI」切换、brand logo）→ 加 base
        text = re.sub(r'(href|src)="/"', rf'\1="{base}/"', text)

        # 裸 logo 路径 → 加 base
        text = re.sub(r'(src|href)="/(logo-[^"]+)"', rf'\1="{base}/\2"', text)

        # 其它裸绝对路径（/all.html /daily.html 等）→ 加 base
        text = re.sub(r'(href|src)="/([a-zA-Z0-9_.\-/]+\.(?:html|xml|txt|png|svg|ico|js|css|json))"',
                      rf'\1="{base}/\2"', text)

        if not args.keep_admin:
            text = text.replace('href="/admin.html"', f'href="{base}/about.html"')
            # 加 base 后形态变成 base/admin.html，也要处理
            text = text.replace(f'href="{base}/admin.html"', f'href="{base}/about.html"')

        if args.aidd_mode:
            # AIDD 子站：brand/首页链接已指向自己的 base，注入返回 AI 的切换器
            # 旧模板没有 .switcher，插到 body 开头一个简洁的返回条
            if 'class="switcher"' not in text and '<body' in text:
                bar = (f'<div class="switcher" style="padding:8px 16px;font-size:13px">'
                       f'<a href="{args.ai_base.rstrip("/")}/">AI</a> · '
                       f'<a href="{base}/" class="on">AIDD</a></div>')
                text = text.replace('<body', bar + '<body', 1)
        else:
            # AI 主站：AIDD 链接指向真子站。
            # 两种形态都处理：① 原始 href="/aidd/"；② 上一轮误加工成 href="{base}/" 的
            # （只改 switcher 里文字恰为 AIDD 的锚点，避免动到别的首页链接）
            text = text.replace('href="/aidd/"', f'href="{base}/aidd/"')
            if args.keep_aidd:
                text = re.sub(
                    r'(<a[^>]*href=")' + re.escape(base) + r'/"([^>]*>)AIDD(</a>)',
                    rf'\1{base}/aidd/"\2AIDD\3',
                    text,
                )
            else:
                text = text.replace(f'href="{base}/aidd/"', f'href="{base}/"')

        if text != original:
            page.write_text(text, encoding="utf-8")
            patched += 1

    removed = []
    if not args.keep_admin:
        admin = root / "admin.html"
        if admin.exists():
            admin.unlink()
            removed.append("admin.html")

    print(f"处理 HTML {patched} 个，移除 {removed or '无'}，base={base}，aidd_mode={args.aidd_mode}")


if __name__ == "__main__":
    main()
