"""SQLite 存储层：把「一轮抓取」变成可追溯、可跨天去重、可评测的记录。

为什么要有这一层（原来只有 JSON 文件）：
- **跨天去重**：`data/daily/*.json` 是快照，没有身份记忆，实测两天有 41–43% 重复；
- **可评测**：每次评分都要留痕（模型、提示词版本、五轴、理由），否则算不出准召；
- **省钱**：`llm_calls` 让同一输入永不重复计费，且能表达「结果不明」；
- **可恢复**：`runs` 记录阶段进度，中断后能接着跑而不是整轮作废。

设计取舍（对照 AIHOT 的 PostgreSQL + pg-boss）：
- 单文件 `data/radar.db`，WAL 模式，够每天一轮用；
- 用 `PRAGMA user_version` 做迁移，一个版本一段 SQL，不引入迁移框架；
- 每次操作用短连接（批量任务里最省心），并发靠 WAL 的读写分离。

约定：所有时间戳用本地时间字符串 `YYYY-MM-DD HH:MM:SS`，
「天」用本地日期 `YYYY-MM-DD`（项目按北京时间出刊）。
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Iterator

from .identity import item_identity

DB_PATH = Path(__file__).parent.parent / "data" / "radar.db"

# 迁移：索引 = 版本号，执行完把 user_version 设成该版本。只增不改。
MIGRATIONS: list[str] = [
    # v1 —— 条目身份、出现记录、已报记录、评分留痕、LLM 回执、预算、运行阶段、信源健康
    """
    CREATE TABLE IF NOT EXISTS items (
        id          INTEGER PRIMARY KEY,
        identity    TEXT NOT NULL UNIQUE,
        source      TEXT NOT NULL,
        layer       TEXT,
        region      TEXT,
        lang        TEXT,
        title       TEXT,
        url         TEXT,
        summary     TEXT,
        author      TEXT,
        published   TEXT,
        heat        REAL,
        first_seen  TEXT NOT NULL,
        last_seen   TEXT NOT NULL,
        extra       TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_items_source   ON items(source);
    CREATE INDEX IF NOT EXISTS idx_items_lastseen ON items(last_seen);

    CREATE TABLE IF NOT EXISTS item_days (
        item_id  INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
        day      TEXT NOT NULL,
        score    REAL,
        PRIMARY KEY (item_id, day)
    );

    CREATE TABLE IF NOT EXISTS reported (
        item_id  INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
        day      TEXT NOT NULL,
        slot     TEXT,
        PRIMARY KEY (item_id, day)
    );
    CREATE INDEX IF NOT EXISTS idx_reported_day ON reported(day);

    CREATE TABLE IF NOT EXISTS scores (
        id             INTEGER PRIMARY KEY,
        item_id        INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
        day            TEXT NOT NULL,
        model          TEXT,
        prompt_version TEXT,
        call_no        INTEGER NOT NULL,
        scope          TEXT,
        itype          TEXT,
        axes           TEXT,
        score          INTEGER,
        reason         TEXT,
        created_at     TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_scores_item ON scores(item_id, day);

    CREATE TABLE IF NOT EXISTS llm_calls (
        id             INTEGER PRIMARY KEY,
        key            TEXT NOT NULL UNIQUE,
        task           TEXT NOT NULL,
        model          TEXT,
        prompt_version TEXT,
        state          TEXT NOT NULL,
        response       TEXT,
        error          TEXT,
        tokens         INTEGER NOT NULL DEFAULT 0,
        attempts       INTEGER NOT NULL DEFAULT 0,
        created_at     TEXT NOT NULL,
        updated_at     TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_llm_calls_task ON llm_calls(task, created_at);

    CREATE TABLE IF NOT EXISTS llm_budget (
        window  TEXT NOT NULL,
        service TEXT NOT NULL,
        calls   INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (window, service)
    );

    CREATE TABLE IF NOT EXISTS runs (
        id          INTEGER PRIMARY KEY,
        day         TEXT NOT NULL,
        stage       TEXT NOT NULL,
        status      TEXT NOT NULL,
        detail      TEXT,
        started_at  TEXT NOT NULL,
        finished_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_runs_day ON runs(day);

    CREATE TABLE IF NOT EXISTS sources (
        source     TEXT PRIMARY KEY,
        fails      INTEGER NOT NULL DEFAULT 0,
        last_ok    TEXT,
        last_error TEXT,
        last_count INTEGER,
        updated_at TEXT
    );
    """,
]


# --------------------------------------------------------------------------- #
# 连接与迁移
# --------------------------------------------------------------------------- #

def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _configure(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=15000")


@contextmanager
def db(path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    """短连接 + 事务。异常回滚，正常提交。"""
    target = Path(path) if path else DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=15)
    try:
        _configure(conn)
        with conn:  # 自动 commit / rollback
            yield conn
    finally:
        conn.close()


def migrate(path: Path | str | None = None) -> int:
    """把库升到最新版本，返回当前版本号。幂等。"""
    target = Path(path) if path else DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=15)
    try:
        _configure(conn)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
            with conn:
                conn.executescript(script)
                conn.execute(f"PRAGMA user_version={i}")
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# 条目
# --------------------------------------------------------------------------- #

def _item_row(it: Any, day: str) -> tuple:
    extra = dict(getattr(it, "extra", None) or {})
    extra.pop("_raw", None)
    return (
        item_identity(it.url),
        it.source,
        getattr(it, "layer", None),
        getattr(it, "region", None),
        getattr(it, "lang", None),
        (it.title or "").strip(),
        it.url,
        (getattr(it, "summary", "") or "").strip(),
        getattr(it, "author", "") or "",
        getattr(it, "published", "") or "",
        getattr(it, "heat", None),
        day,
        day,
        json.dumps(extra, ensure_ascii=False),
    )


def upsert_items(items: Iterable[Any], day: str | None = None) -> dict[str, Any]:
    """写入本轮条目，返回 `{new: set, seen: set, ids: dict}`。

    `new` 是今天第一次见到的身份；`seen` 是库里已存在的（跨天重复的来源）。
    """
    day = day or today_str()
    items = list(items)
    rows = [_item_row(it, day) for it in items]
    if not rows:
        return {"new": set(), "seen": set(), "ids": {}}

    identities = [r[0] for r in rows]
    with db() as conn:
        existing = set()
        for start in range(0, len(identities), 400):
            chunk = identities[start : start + 400]
            marks = ",".join("?" * len(chunk))
            existing.update(r["identity"] for r in conn.execute(
                f"SELECT identity FROM items WHERE identity IN ({marks})", chunk))

        conn.executemany(
            """
            INSERT INTO items (identity, source, layer, region, lang, title, url, summary,
                               author, published, heat, first_seen, last_seen, extra)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(identity) DO UPDATE SET
                last_seen = excluded.last_seen,
                title     = CASE WHEN length(excluded.title) > length(items.title)
                                 THEN excluded.title ELSE items.title END,
                summary   = CASE WHEN length(excluded.summary) > length(items.summary)
                                 THEN excluded.summary ELSE items.summary END,
                published = CASE WHEN items.published = '' THEN excluded.published
                                 ELSE items.published END,
                heat      = coalesce(max(items.heat, excluded.heat), excluded.heat),
                extra     = excluded.extra
            """,
            rows,
        )

        id_map: dict[str, int] = {}
        for start in range(0, len(identities), 400):
            chunk = identities[start : start + 400]
            marks = ",".join("?" * len(chunk))
            for r in conn.execute(f"SELECT id, identity FROM items WHERE identity IN ({marks})", chunk):
                id_map[r["identity"]] = r["id"]

        day_rows = []
        for it, ident in zip(items, identities):
            item_id = id_map.get(ident)
            if item_id is None:
                continue
            score = (getattr(it, "extra", None) or {}).get("score")
            day_rows.append((item_id, day, score))
        conn.executemany(
            "INSERT INTO item_days (item_id, day, score) VALUES (?,?,?) "
            "ON CONFLICT(item_id, day) DO UPDATE SET score = coalesce(excluded.score, item_days.score)",
            day_rows,
        )

    return {"new": set(identities) - existing, "seen": set(identities) & existing, "ids": id_map}


def recently_reported(days: int = 7, day: str | None = None) -> set[str]:
    """最近 N 天已经进过日报的条目身份。用于「报过的不再出现」。"""
    day = day or today_str()
    since = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
    with db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT i.identity FROM reported r JOIN items i ON i.id = r.item_id WHERE r.day >= ?",
            (since,),
        ).fetchall()
    return {r["identity"] for r in rows}


def ids_for(identities: Iterable[str]) -> dict[str, int]:
    """身份 → 主键。用于把评分写回 items。"""
    idents = [i for i in dict.fromkeys(identities) if i]
    out: dict[str, int] = {}
    if not idents:
        return out
    with db() as conn:
        for start in range(0, len(idents), 400):
            chunk = idents[start : start + 400]
            marks = ",".join("?" * len(chunk))
            for r in conn.execute(f"SELECT id, identity FROM items WHERE identity IN ({marks})", chunk):
                out[r["identity"]] = r["id"]
    return out


def mark_reported(items: Iterable[Any], day: str | None = None, slot: str | None = None) -> int:
    """标记这批条目已经进过当天的日报/邮件。"""
    day = day or today_str()
    idents = [item_identity(getattr(it, "url", "") or (it.get("url") if isinstance(it, dict) else "")) for it in items]
    if not idents:
        return 0
    with db() as conn:
        marks = ",".join("?" * len(idents)) if len(idents) <= 400 else None
        if marks:
            pairs = conn.execute(f"SELECT id, identity FROM items WHERE identity IN ({marks})", idents).fetchall()
        else:
            pairs = []
            for start in range(0, len(idents), 400):
                chunk = idents[start : start + 400]
                pairs += conn.execute(
                    "SELECT id, identity FROM items WHERE identity IN (%s)" % ",".join("?" * len(chunk)), chunk
                ).fetchall()
        conn.executemany(
            "INSERT INTO reported (item_id, day, slot) VALUES (?,?,?) ON CONFLICT(item_id, day) DO NOTHING",
            [(r["id"], day, slot) for r in pairs],
        )
    return len(pairs)


# --------------------------------------------------------------------------- #
# 评分留痕
# --------------------------------------------------------------------------- #

def save_scores(rows: list[dict[str, Any]], day: str | None = None) -> None:
    """写评分记录。rows 里每项：item_id/model/prompt_version/call_no/scope/itype/axes/score/reason。"""
    if not rows:
        return
    day = day or today_str()
    ts = now_str()
    with db() as conn:
        conn.executemany(
            """INSERT INTO scores (item_id, day, model, prompt_version, call_no, scope, itype, axes, score, reason, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    r["item_id"], day, r.get("model"), r.get("prompt_version"), int(r.get("call_no", 1)),
                    r.get("scope"), r.get("itype"),
                    json.dumps(r.get("axes") or {}, ensure_ascii=False),
                    r.get("score"), r.get("reason"), ts,
                )
                for r in rows
            ],
        )


def score_distribution(day: str | None = None) -> dict[str, Any]:
    """当天评分的分布，喂给看板：够看「门槛附近堆了多少」。"""
    day = day or today_str()
    with db() as conn:
        rows = conn.execute("SELECT score FROM scores WHERE day = ? AND score IS NOT NULL", (day,)).fetchall()
    vals = sorted(r["score"] for r in rows)
    if not vals:
        return {"count": 0}
    def pct(p: float) -> float:
        return vals[min(len(vals) - 1, int(len(vals) * p))]
    return {
        "count": len(vals),
        "min": vals[0], "p25": pct(0.25), "median": pct(0.5), "p75": pct(0.75), "max": vals[-1],
    }


# --------------------------------------------------------------------------- #
# 运行阶段（断点恢复）
# --------------------------------------------------------------------------- #

def run_start(day: str, stage: str) -> int:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO runs (day, stage, status, started_at) VALUES (?,?,?,?)",
            (day, stage, "running", now_str()),
        )
        return int(cur.lastrowid)


def run_finish(run_id: int, status: str, detail: str | None = None) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE runs SET status = ?, detail = ?, finished_at = ? WHERE id = ?",
            (status, detail, now_str(), run_id),
        )


def stages_done(day: str) -> set[str]:
    """当天已经成功的阶段，重跑时跳过。"""
    with db() as conn:
        rows = conn.execute("SELECT stage FROM runs WHERE day = ? AND status = 'ok'", (day,)).fetchall()
    return {r["stage"] for r in rows}


# --------------------------------------------------------------------------- #
# 信源健康
# --------------------------------------------------------------------------- #

def save_source_health(health: dict[str, dict[str, Any]]) -> None:
    """health: {source: {fails, last_ok, last_error, last_count}}"""
    if not health:
        return
    ts = now_str()
    with db() as conn:
        conn.executemany(
            """INSERT INTO sources (source, fails, last_ok, last_error, last_count, updated_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(source) DO UPDATE SET
                 fails=excluded.fails, last_ok=coalesce(excluded.last_ok, sources.last_ok),
                 last_error=excluded.last_error, last_count=excluded.last_count, updated_at=excluded.updated_at""",
            [
                (
                    src,
                    int(info.get("fails") or 0),
                    info.get("last_ok"),
                    info.get("last_error"),
                    info.get("last_count"),
                    ts,
                )
                for src, info in health.items()
            ],
        )


def source_rows() -> list[dict[str, Any]]:
    with db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM sources ORDER BY source").fetchall()]


# --------------------------------------------------------------------------- #
# 概览
# --------------------------------------------------------------------------- #

def summary() -> dict[str, Any]:
    with db() as conn:
        def one(sql: str, *args: Any) -> Any:
            row = conn.execute(sql, args).fetchone()
            return row[0] if row else 0
        return {
            "version": conn.execute("PRAGMA user_version").fetchone()[0],
            "items": one("SELECT count(*) FROM items"),
            "items_today": one("SELECT count(*) FROM item_days WHERE day = ?", today_str()),
            "reported_total": one("SELECT count(*) FROM reported"),
            "llm_calls": one("SELECT count(*) FROM llm_calls"),
            "llm_hit": one("SELECT count(*) FROM llm_calls WHERE state = 'ok' AND attempts = 0"),
            "runs_today": one("SELECT count(*) FROM runs WHERE day = ?", today_str()),
        }


if __name__ == "__main__":
    print("schema version:", migrate())
    print(json.dumps(summary(), ensure_ascii=False, indent=2))
