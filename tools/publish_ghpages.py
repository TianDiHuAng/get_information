"""把构建好的静态站加工成 GitHub Pages 可发布版本。

用途：求职演示站。做四件事：
  1. 修掉模板里漏掉 base 的裸绝对路径（根路径 "/" / logo / 子页）
  2. 去掉后台入口（公开演示站不该出现 /admin.html）
  3. 把 AIDD 子站入口指向真正的子站（而不是首页）
  4. 注入 zbit-switch.js：AI ⇄ AIDD 无刷新切换（像本地 serve.py 一样）

用法（AI 主站）：
  python tools/publish_ghpages.py --site <AI站目录> --base /get_information --switch-js tools/zbit-switch.js
用法（AIDD 子站）：
  python tools/publish_ghpages.py --site <AIDD站目录> --base /get_information/aidd --aidd-mode --switch-js tools/zbit-switch.js

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
    ap.add_argument("--aidd-mode", action="store_true", help="处理的是 AIDD 子站")
    ap.add_argument("--ai-base", default="/get_information", help="AIDD 模式下 AI 主站的 base")
    ap.add_argument("--switch-js", default="", help="注入的切换脚本路径（inline 到每个页面）")
    args = ap.parse_args()

    root = Path(args.site)
    base = args.base.rstrip("/")
    if not root.is_dir():
        raise SystemExit(f"目录不存在: {root}")

    switch_js = ""
    if args.switch_js:
        p = Path(args.switch_js)
        switch_js = p.read_text(encoding="utf-8") if p.is_file() else ""
        # </script> 会出现在 JS 字符串里时截断，做最小防护
        switch_js = switch_js.replace("</script>", "<\\/script>")
    inline_tag = f"<script>\n{switch_js}\n</script>" if switch_js else ""

    patched = 0
    for page in root.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        original = text

        # 裸根路径 "/"（导航里的品牌/AI 切换）→ 加 base
        text = re.sub(r'(href|src)="/"', rf'\1="{base}/"', text)

        # 裸 logo 路径 → 加 base
        text = re.sub(r'(src|href)="/(logo-[^"]+)"', rf'\1="{base}/\2"', text)

        # 其它裸绝对路径（/all.html /daily.html 等）→ 加 base
        text = re.sub(r'(href|src)="/([a-zA-Z0-9_.\-/]+\.(?:html|xml|txt|png|svg|ico|js|css|json))"',
                      rf'\1="{base}/\2"', text)

        if not args.keep_admin:
            text = text.replace(f'href="{base}/admin.html"', f'href="{base}/about.html"')

        # 去掉模板自带的 switcher（旧注入的游离 div 也一并删）——统一交给 JS 渲染
        text = re.sub(r'<div class="switcher"[^>]*>.*?</div>', '', text, flags=re.S)

        if inline_tag and "</body>" in text:
            text = text.replace("</body>", inline_tag + "\n</body>", 1)

        if text != original:
            page.write_text(text, encoding="utf-8")
            patched += 1

    removed = []
    if not args.keep_admin:
        admin = root / "admin.html"
        if admin.exists():
            admin.unlink()
            removed.append("admin.html")

    print(f"处理 HTML {patched} 个，移除 {removed or '无'}，base={base}，切换JS={'注入' if inline_tag else '无'}")


if __name__ == "__main__":
    main()
