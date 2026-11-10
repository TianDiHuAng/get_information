"""换行业：建包、切换、体检。

    python tools/customize.py check                  # 体检当前行业，列出所有"改了一半"的地方
    python tools/customize.py new legal --name "法律热点"   # 建一个行业包骨架
    python tools/customize.py use legal               # 切过去
    python tools/customize.py use ""                  # 切回 config/ 原值
    python tools/customize.py list                    # 看有哪些包

换行业不是改值，是换一整套判断标准。包的做法是 `industry/<slug>/` 覆盖 `config/` 同名文件，
`config/industry.yaml` 里一行 `pack:` 切换 —— 原来的始终在，随时切得回来。

完整步骤见 docs/customize.md。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector import industry  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="行业包：建 / 切 / 体检")
    sub = ap.add_subparsers(dest="cmd")

    p_check = sub.add_parser("check", help="体检当前行业包")
    p_check.add_argument("--strict", action="store_true", help="有提醒也返回非零")

    p_new = sub.add_parser("new", help="建一个行业包骨架")
    p_new.add_argument("slug")
    p_new.add_argument("--name", required=True, help="行业名，例如「法律热点」")
    p_new.add_argument("--force", action="store_true")

    p_use = sub.add_parser("use", help="切换行业包（空串 = 用 config/）")
    p_use.add_argument("slug", nargs="?", default="")

    sub.add_parser("list", help="列出已有行业包")

    args = ap.parse_args()
    cmd = args.cmd or "check"

    if cmd == "check":
        conf = industry.settings(reload=True)
        target = industry.pack()
        print(f"当前行业：{conf.get('name')}  （包：{target.name if target else 'config/ 原值'}）")
        issues = industry.validate()
        print(industry.summary(issues))
        if not issues:
            return 0
        has_error = any(i["level"] == "error" for i in issues)
        if has_error or args.strict:
            return 1
        return 0

    if cmd == "new":
        result = industry.scaffold(args.slug, args.name, force=args.force)
        if not result.get("ok"):
            print(f"失败：{result.get('error')}")
            return 1
        print(f"已建 {result['pack']}")
        print("  文件：" + "、".join(result["files"]))
        print("\n接下来（按这个顺序，前两步最关键）：")
        print("  1. 改 prompts/attention-score.md —— 什么该选、什么该压住，写成你行业的话")
        print(f"  2. 改 taxonomy.yaml —— 分类与标签（key 会进网址，定下别改）")
        print("  3. 改 wording.yaml —— 读者看不懂的行话、要压住的夸张说法")
        print("  4. 在 config/sources.yaml 里加你行业的源（id 要对应代码里的抓取器）")
        print(f"  5. python tools/customize.py use {args.slug}")
        print("  6. 标 100–200 条金标，重新校准门槛")
        return 0

    if cmd == "use":
        result = industry.use(args.slug)
        if not result.get("ok"):
            print(f"失败：{result.get('error')}")
            return 1
        print(f"已切到：{result['pack']}")
        print("下一步：python tools/customize.py check")
        return 0

    if cmd == "list":
        packs = industry.available()
        if not packs:
            print("还没有行业包。建一个：python tools/customize.py new <slug> --name <名称>")
            return 0
        current = (industry.pack() or Path()).name
        for name in packs:
            mark = " ← 当前" if name == current else ""
            print(f"  {name}{mark}")
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
