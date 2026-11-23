"""从站点的公开 API 快照（api/v1/latest.json）恢复被清空的 data/。

用途：data/ 在 .gitignore 里，反复切分支时可能被清空。站点 API 是
从 items.json 构建的公开读取层，保留了标题/URL/来源/评分/五轴/结构/事件，
足以重建一份可用的 items.json 和数据库条目，让 run.py / build_sites.py 能继续跑。

用法：
  python tools/restore_data.py                      # 从 site/api/v1/latest.json 恢复
  python tools/restore_data.py --dry-run            # 只看不写
  python tools/restore_data.py --source <json路径>  # 指定快照

注意：恢复的是「展示层」数据，不含 LLM 回执/预算等运行态——那些无法从公开数据逆推，
需要重新跑一轮 run.py 生成。恢复后站点可正常构建，采集流程也能从干净状态继续。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # 让 tools/ 下运行时能 import collector
DEFAULT_SNAPSHOT = ROOT / "site" / "api" / "v1" / "latest.json"
ITEMS_JSON = ROOT / "data" / "items.json"
DB_PATH = ROOT / "data" / "radar.db"


def load_snapshot(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise SystemExit(f"不是有效的 latest.json 快照: {path}")
    return data


def to_item(entry: dict) -> dict:
    """把 latest.json 的条目还原成 items.json 里的条目形状。"""
    attention = entry.get("attention") or {}
    structure = entry.get("structure") or {}
    event = entry.get("event") or {}
    extra: dict = {}
    if attention:
        extra["attention"] = attention
    if structure:
        extra["structure"] = structure
    if event:
        extra["event"] = event
    return {
        "title": entry.get("title") or "",
        "url": entry.get("url") or "",
        "source": entry.get("source") or "",
        "layer": entry.get("layer"),
        "region": entry.get("region"),
        "published": entry.get("published") or "",
        "summary": entry.get("summary") or "",
        "score": entry.get("score"),
        "heat": event.get("heat") if event else None,
        "extra": extra,
    }


def restore_items_json(data: dict, dry_run: bool) -> int:
    items = [to_item(e) for e in data["items"]]
    payload = {
        "items": items,
        "stats": {
            "generated_at": data.get("generated_at") or datetime.now().astimezone().isoformat(),
            "restored_from": "site/api/v1/latest.json",
            "restored_at": datetime.now().astimezone().isoformat(),
            "count": len(items),
        },
    }
    if not dry_run:
        ITEMS_JSON.parent.mkdir(parents=True, exist_ok=True)
        ITEMS_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(items)


def restore_db(data: dict, dry_run: bool) -> tuple[int, int]:
    """把条目写回 items / scores / structures 表（幂等，按 identity 去重）。"""
    if not DB_PATH.exists() and not dry_run:
        raise SystemExit(f"数据库不存在，请先运行一次 python run.py 初始化: {DB_PATH}")

    day = (data.get("generated_at") or "")[:10] or datetime.now().astimezone().date().isoformat()
    new_items = 0
    new_scores = 0
    if dry_run:
        return len(data["items"]), len(data["items"])

    conn = sqlite3.connect(DB_PATH)
    try:
        from collector.identity import item_identity
        for entry in data["items"]:
            item = to_item(entry)
            ident = item_identity(item["url"])
            cur = conn.execute("SELECT id FROM items WHERE identity=?", (ident,))
            row = cur.fetchone()
            if row:
                item_id = row[0]
            else:
                cur = conn.execute(
                    "INSERT INTO items (identity,source,layer,region,title,url,summary,"
                    "published,heat,first_seen,last_seen,extra) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        ident, item["source"], item["layer"], item["region"],
                        item["title"], item["url"], item["summary"], item["published"],
                        item["heat"], day, day,
                        json.dumps(item["extra"], ensure_ascii=False),
                    ),
                )
                item_id = cur.lastrowid
                new_items += 1

            # 五轴评分写回 scores（call_no=0 表示恢复的快照值，不占真实模型调用）
            attention = item["extra"].get("attention") or {}
            if attention.get("score") is not None:
                exists = conn.execute(
                    "SELECT 1 FROM scores WHERE item_id=? AND day=? AND call_no=0",
                    (item_id, day),
                ).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO scores (item_id,day,model,prompt_version,call_no,scope,"
                        "itype,axes,score,reason,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            item_id, day, "restored", "snapshot", 0,
                            "attention", attention.get("itype"),
                            json.dumps(attention.get("axes") or {}, ensure_ascii=False),
                            attention.get("score"), attention.get("reason") or "",
                            datetime.now().isoformat(),
                        ),
                    )
                    new_scores += 1

            # 结构化结果写回 structures
            structure = item["extra"].get("structure") or {}
            if structure:
                exists = conn.execute(
                    "SELECT 1 FROM structures WHERE item_id=? AND day=?",
                    (item_id, day),
                ).fetchone()
                if not exists:
                    cols = [c[1] for c in conn.execute("PRAGMA table_info(structures)")]
                    payload = {
                        "item_id": item_id, "day": day,
                        "category": structure.get("category"),
                        "tags": json.dumps(structure.get("tags") or [], ensure_ascii=False),
                        "subjects": json.dumps(structure.get("subjects") or [], ensure_ascii=False),
                        "scope": structure.get("scope"),
                        "created_at": datetime.now().isoformat(),
                        "updated_at": datetime.now().isoformat(),
                    }
                    keys = [k for k in payload if k in cols]
                    conn.execute(
                        f"INSERT INTO structures ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
                        [payload[k] for k in keys],
                    )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return new_items, new_scores


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=str(DEFAULT_SNAPSHOT))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    data = load_snapshot(Path(args.source))
    n_items = restore_items_json(data, args.dry_run)
    n_db_items, n_scores = restore_db(data, args.dry_run)

    tag = "[dry-run] " if args.dry_run else ""
    print(f"{tag}快照条目: {len(data['items'])}（{data.get('generated_at', '?')}）")
    print(f"{tag}items.json: {n_items} 条")
    print(f"{tag}数据库: 新增 {n_db_items} items / {n_scores} scores")
    if not args.dry_run:
        print(f"恢复完成。运行 python tools/build_sites.py 可重建站点。")


if __name__ == "__main__":
    main()
