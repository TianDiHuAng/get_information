"""补跑翻译：把 items.json 里的非中文条目翻译成中文并写回。

用途：run.py 一轮里如果预算在评分阶段就打满，翻译会整体降级成英文。
这个脚本单独跑翻译阶段，只读 items.json、不重采集、不重评分。

用法：
  python tools/finish_translate.py              # 翻译 data/items.json
  python tools/finish_translate.py --data data-aidd/items.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data" / "items.json"))
    args = ap.parse_args()

    path = Path(args.data)
    if not path.is_file():
        raise SystemExit(f"文件不存在: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("items") or []
    print(f"读入 {len(items)} 条")

    from collector.translate import translate_items

    stats = translate_items(items)
    print(f"翻译结果: {stats}")

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写回 {path}")


if __name__ == "__main__":
    main()
