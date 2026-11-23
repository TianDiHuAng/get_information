"""把构建好的静态站加工成 GitHub Pages 可发布版本。

用途：求职演示站。做四件事：
  1. 归一化 base：折叠重复前缀（build_sites 已加过一次，这里不再叠）
  2. 修掉模板里漏掉 base 的裸绝对路径（根路径 "/" / logo / 子页）
  3. 去掉后台入口（公开演示站不该出现 /admin.html）
  4. 注入 zbit-switch.js：AI ⇄ AIDD 无刷新切换（像本地 serve.py 一样）

幂等：同一目录跑多次结果一致，不会把 /get_information/ 叠成三层。

用法（AI 主站）：
  python tools/publish_ghpages.py --site <AI站目录> --base /get_information --switch-js tools/zbit-switch.js
用法（AIDD 子站）：
  python tools/publish_ghpages.py --site <AIDD站目录> --base /get_information/aidd --aidd-mode --switch-js tools/zbit-switch.js
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
    ap.add_argument("--keep-aidd", action="store_true", help="保留 AIDD 子站入口")
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
        switch_js = switch_js.replace("</script>", "<\\/script>")
    inline_tag = f"<script>\n{switch_js}\n</script>" if switch_js else ""

    # 归一化：把重复 base 折叠成一个（/(base/)+ → /base/）
    # 例：/get_information/get_information/favicon.ico → /get_information/favicon.ico
    collapse = re.compile(r"(/get_information/)(?:get_information/)+")
    # AIDD 子站：/get_information/aidd/aidd/... → /get_information/aidd/...
    collapse_aidd = re.compile(r"(/get_information/aidd/)(?:aidd/)+")

    patched = 0
    for page in root.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        original = text

        # ① 先折叠重复前缀（最关键的幂等保护）
        text = collapse.sub(r"\1", text)
        text = collapse_aidd.sub(r"\1", text)

        # ② 裸根路径 "/" → 加 base（注意：不碰已带 base 的）
        text = re.sub(r'(href|src)="/"', rf'\1="{base}/"', text)

        # ③ 裸 logo / 其它裸绝对路径 → 加 base（负向断言排除已带 base 的）
        text = re.sub(r'(?<!' + re.escape(base) + r')/(logo-[^"]+)"',
                      rf'{base}/\1"', text)
        text = re.sub(r'(href|src)="/(?!get_information/)([a-zA-Z0-9_.\-/]+\.(?:html|xml|txt|png|svg|ico|js|css|json))"',
                      rf'\1="{base}/\2"', text)

        if not args.keep_admin:
            text = text.replace(f'href="{base}/admin.html"', f'href="{base}/about.html"')

        # 去掉模板自带的 switcher（旧注入的游离 div 也一并删）——统一交给 JS 渲染
        text = re.sub(r'<div class="switcher"[^>]*>.*?</div>', '', text, flags=re.S)

        # 去掉旧的注入脚本，避免多轮叠加
        text = re.sub(r'<script>\s*// 双站无刷新切换.*?</script>', '', text, flags=re.S)

        if inline_tag and "</body>" in text:
            text = text.replace("</body>", inline_tag + "\n</body>", 1)

        if text != original:
            page.write_text(text, encoding="utf-8")
            patched += 1

    # manifest.webmanifest：修 PWA 图标/start_url 的裸路径（build_sites 漏加 base）
    # 用 json 模块改，避免正则破坏同行的 "src"/"sizes" 结构
    import json
    for manifest in root.rglob("manifest*.webmanifest"):
        try:
            m = json.loads(manifest.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        changed = False
        for key in ("start_url", "scope"):
            v = m.get(key)
            if isinstance(v, str) and not v.startswith(base):
                m[key] = base + ("" if v == "/" else (v if v.startswith("/") else "/" + v))
                changed = True
        for icon in m.get("icons") or []:
            v = icon.get("src")
            if isinstance(v, str) and v.startswith("/") and not v.startswith(base + "/"):
                icon["src"] = base + v
                changed = True
        if changed:
            manifest.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    removed = []
    if not args.keep_admin:
        admin = root / "admin.html"
        if admin.exists():
            admin.unlink()
            removed.append("admin.html")

    print(f"处理 HTML {patched} 个，移除 {removed or '无'}，base={base}，aidd_mode={args.aidd_mode}")


if __name__ == "__main__":
    main()
