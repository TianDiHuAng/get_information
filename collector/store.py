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

from .identity import content_fingerprint, item_identity

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
    # v2 —— 事件聚簇：事件、成员、两两判定缓存、热度快照
    """
    CREATE TABLE IF NOT EXISTS events (
        id         INTEGER PRIMARY KEY,
        key        TEXT NOT NULL UNIQUE,   -- 代表条目身份，用于幂等
        title      TEXT,
        first_at   TEXT,
        last_at    TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS event_items (
        event_id   INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        item_id    INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
        relation   TEXT,
        confidence REAL,
        decided_at TEXT,
        PRIMARY KEY (event_id, item_id)
    );
    CREATE INDEX IF NOT EXISTS idx_event_items_item ON event_items(item_id);

    CREATE TABLE IF NOT EXISTS event_pairs (
        a              TEXT NOT NULL,
        b              TEXT NOT NULL,
        relation       TEXT NOT NULL,
        confidence     REAL,
        prompt_version TEXT,
        created_at     TEXT NOT NULL,
        PRIMARY KEY (a, b)
    );

    CREATE TABLE IF NOT EXISTS event_heat (
        event_id     INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        computed_at  TEXT NOT NULL,
        heat         REAL NOT NULL,
        participants INTEGER NOT NULL,
        PRIMARY KEY (event_id, computed_at)
    );
    """,
    # v3 —— 内容指纹与修订号、结构化抽取结果
    """
    ALTER TABLE items ADD COLUMN fingerprint TEXT;
    ALTER TABLE items ADD COLUMN revision INTEGER NOT NULL DEFAULT 1;

    CREATE TABLE IF NOT EXISTS structures (
        id             INTEGER PRIMARY KEY,
        item_id        INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
        day            TEXT NOT NULL,
        category       TEXT,
        tags           TEXT,
        subjects       TEXT,
        scope          TEXT,
        fact           TEXT,
        model          TEXT,
        prompt_version TEXT,
        created_at     TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_structures_item     ON structures(item_id, day);
    CREATE INDEX IF NOT EXISTS idx_structures_category ON structures(category);
    """,
    # v4 —— 出刊记录（判缺期）与告警
    """
    CREATE TABLE IF NOT EXISTS editions (
        kind         TEXT NOT NULL,
        day          TEXT NOT NULL,
        entries      INTEGER NOT NULL DEFAULT 0,
        model        TEXT,
        generated_at TEXT NOT NULL,
        PRIMARY KEY (kind, day)
    );

    CREATE TABLE IF NOT EXISTS alerts (
        id         INTEGER PRIMARY KEY,
        kind       TEXT NOT NULL,
        day        TEXT NOT NULL,
        severity   TEXT NOT NULL DEFAULT 'warn',
        message    TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (kind, day, message)
    );
    """,
    # v5 —— 阅读反馈：点开 / 有用 / 没用。同一个身份同一天只记最后一次态度，
    # 否则"点错了再改回来"会被当成两条相反的证据，把兴趣向量搅乱。
    """
    CREATE TABLE IF NOT EXISTS feedback (
        id         INTEGER PRIMARY KEY,
        identity   TEXT NOT NULL,
        day        TEXT NOT NULL,
        kind       TEXT NOT NULL,
        terms      TEXT,
        created_at TEXT NOT NULL,
        UNIQUE (identity, day)
    );
    CREATE INDEX IF NOT EXISTS idx_feedback_day ON feedback(day);
    """,
    # v6 —— 已推送记录：同一条内容作为「突发」只推一次，永久去重
    """
    CREATE TABLE IF NOT EXISTS pushes (
        identity   TEXT NOT NULL,
        kind       TEXT NOT NULL,
        day        TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (identity, kind)
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
    title = (it.title or "").strip()
    summary = (getattr(it, "summary", "") or "").strip()
    return (
        item_identity(it.url),
        it.source,
        getattr(it, "layer", None),
        getattr(it, "region", None),
        getattr(it, "lang", None),
        title,
        it.url,
        summary,
        getattr(it, "author", "") or "",
        getattr(it, "published", "") or "",
        getattr(it, "heat", None),
        content_fingerprint(title, summary),
        day,
        day,
        json.dumps(extra, ensure_ascii=False),
    )


def upsert_items(items: Iterable[Any], day: str | None = None) -> dict[str, Any]:
    """写入本轮条目，返回 `{new, seen, revised, ids}`。

    - `new`：今天第一次见到的身份；
    - `seen`：库里已存在的（跨天重复的来源）；
    - `revised`：同一身份但**内容指纹变了**（媒体补了内容/改了标题）→ 修订号 +1，值得重新判定。
    """
    day = day or today_str()
    items = list(items)
    rows = [_item_row(it, day) for it in items]
    if not rows:
        return {"new": set(), "seen": set(), "revised": set(), "ids": {}}

    identities = [r[0] for r in rows]
    fingerprints = {r[0]: r[11] for r in rows}
    existing_fp: dict[str, str | None] = {}
    with db() as conn:
        for start in range(0, len(identities), 400):
            chunk = identities[start : start + 400]
            marks = ",".join("?" * len(chunk))
            for r in conn.execute(
                f"SELECT identity, fingerprint FROM items WHERE identity IN ({marks})", chunk
            ):
                existing_fp[r["identity"]] = r["fingerprint"]

        conn.executemany(
            """
            INSERT INTO items (identity, source, layer, region, lang, title, url, summary,
                               author, published, heat, fingerprint, first_seen, last_seen, extra)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(identity) DO UPDATE SET
                last_seen = excluded.last_seen,
                title     = CASE WHEN length(excluded.title) > length(items.title)
                                 THEN excluded.title ELSE items.title END,
                summary   = CASE WHEN length(excluded.summary) > length(items.summary)
                                 THEN excluded.summary ELSE items.summary END,
                published = CASE WHEN items.published = '' THEN excluded.published
                                 ELSE items.published END,
                heat      = coalesce(max(items.heat, excluded.heat), excluded.heat),
                revision  = CASE WHEN items.fingerprint IS NOT NULL
                                  AND excluded.fingerprint IS NOT NULL
                                  AND items.fingerprint <> excluded.fingerprint
                                 THEN items.revision + 1 ELSE items.revision END,
                fingerprint = excluded.fingerprint,
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

    existing = set(existing_fp)
    revised = {
        ident for ident, fp in fingerprints.items()
        if ident in existing_fp and existing_fp[ident] and fp and existing_fp[ident] != fp
    }
    return {"new": set(identities) - existing, "seen": set(identities) & existing,
            "revised": revised, "ids": id_map}


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
# 事件聚簇
# --------------------------------------------------------------------------- #

def recent_items(days: int = 14, limit: int = 1500) -> list[dict[str, Any]]:
    """近 N 天见过的条目，作为聚簇召回池。"""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    with db() as conn:
        rows = conn.execute(
            """SELECT id, identity, source, layer, title, url, summary, published, first_seen
               FROM items WHERE last_seen >= ? ORDER BY last_seen DESC LIMIT ?""",
            (since, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def load_pairs(keys: Iterable[tuple[str, str]]) -> dict[tuple[str, str], dict[str, Any]]:
    """已经判过的关系对，避免重复花模型钱。"""
    pairs = list(dict.fromkeys(tuple(sorted(k)) for k in keys))
    out: dict[tuple[str, str], dict[str, Any]] = {}
    if not pairs:
        return out
    wanted = set(pairs)
    idents = list({x for pair in pairs for x in pair})
    with db() as conn:
        for start in range(0, len(idents), 400):
            chunk = idents[start : start + 400]
            marks = ",".join("?" * len(chunk))
            # SQLite 不支持行值 IN，按一侧过滤后在内存里配对
            for row in conn.execute(
                f"SELECT a, b, relation, confidence FROM event_pairs WHERE a IN ({marks})", chunk
            ):
                key = (row["a"], row["b"])
                if key in wanted:
                    out[key] = {"relation": row["relation"], "confidence": row["confidence"]}
    return out


def save_pairs(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    ts = now_str()
    with db() as conn:
        conn.executemany(
            """INSERT INTO event_pairs (a, b, relation, confidence, prompt_version, created_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(a, b) DO UPDATE SET relation=excluded.relation,
                 confidence=excluded.confidence, prompt_version=excluded.prompt_version""",
            [(r["a"], r["b"], r["relation"], r.get("confidence"), r.get("prompt_version"), ts) for r in rows],
        )


def upsert_events_bulk(rows: list[dict[str, Any]]) -> dict[str, int]:
    """一次事务写完所有事件，返回 `{key: event_id}`。

    单机上一轮可能有几百个事件，逐个开事务会把整轮拖到几十秒（实测 215 条要 44s）。
    """
    if not rows:
        return {}
    ts = now_str()
    out: dict[str, int] = {}
    with db() as conn:
        for row in rows:
            conn.execute(
                """INSERT INTO events (key, title, first_at, last_at, created_at, updated_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(key) DO UPDATE SET title=excluded.title, last_at=excluded.last_at,
                     updated_at=excluded.updated_at""",
                (row["key"], row["title"], row.get("first_at"), row.get("last_at"), ts, ts),
            )
        for row in rows:
            eid = conn.execute("SELECT id FROM events WHERE key = ?", (row["key"],)).fetchone()["id"]
            out[row["key"]] = int(eid)
            members = row.get("members") or []
            if members:
                conn.executemany(
                    """INSERT INTO event_items (event_id, item_id, relation, confidence, decided_at)
                       VALUES (?,?,?,?,?)
                       ON CONFLICT(event_id, item_id) DO UPDATE SET
                         relation=excluded.relation, confidence=excluded.confidence,
                         decided_at=excluded.decided_at""",
                    [(eid, iid, rel, conf, ts) for iid, rel, conf in members],
                )
    return out


def save_heat_many(rows: list[tuple[int, float, int]]) -> None:
    """批量写热度快照：`[(event_id, heat, participants)]`。"""
    if not rows:
        return
    ts = now_str()
    with db() as conn:
        conn.executemany(
            "INSERT INTO event_heat (event_id, computed_at, heat, participants) VALUES (?,?,?,?) "
            "ON CONFLICT(event_id, computed_at) DO UPDATE SET heat=excluded.heat, "
            "participants=excluded.participants",
            [(eid, ts, heat, parts) for eid, heat, parts in rows],
        )


def upsert_event(key: str, title: str, first_at: str | None, last_at: str | None,
                 members: list[tuple[int, str, float]]) -> int:
    """事件按代表条目的身份幂等写入，成员关系一并更新。"""
    ts = now_str()
    with db() as conn:
        conn.execute(
            """INSERT INTO events (key, title, first_at, last_at, created_at, updated_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(key) DO UPDATE SET title=excluded.title, last_at=excluded.last_at,
                 updated_at=excluded.updated_at""",
            (key, title, first_at, last_at, ts, ts),
        )
        eid = conn.execute("SELECT id FROM events WHERE key = ?", (key,)).fetchone()["id"]
        conn.executemany(
            """INSERT INTO event_items (event_id, item_id, relation, confidence, decided_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(event_id, item_id) DO UPDATE SET
                 relation=excluded.relation, confidence=excluded.confidence, decided_at=excluded.decided_at""",
            [(eid, iid, rel, conf, ts) for iid, rel, conf in members],
        )
    return int(eid)


def event_members(event_id: int) -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            """SELECT i.id, i.source, i.layer, i.title, i.url, i.published, ei.relation, ei.confidence
               FROM event_items ei JOIN items i ON i.id = ei.item_id
               WHERE ei.event_id = ? ORDER BY i.published""",
            (event_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def save_heat(event_id: int, heat: float, participants: int) -> None:
    """同一秒内重算不报错：秒级快照按最后一次为准。"""
    with db() as conn:
        conn.execute(
            "INSERT INTO event_heat (event_id, computed_at, heat, participants) VALUES (?,?,?,?) "
            "ON CONFLICT(event_id, computed_at) DO UPDATE SET heat=excluded.heat, "
            "participants=excluded.participants",
            (event_id, now_str(), heat, participants),
        )


def previous_heat(event_id: int, hours: int = 6) -> float | None:
    """上一次（至少 hours 小时前）的热度快照，用来算趋势。"""
    since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    with db() as conn:
        row = conn.execute(
            "SELECT heat FROM event_heat WHERE event_id = ? AND computed_at <= ? "
            "ORDER BY computed_at DESC LIMIT 1",
            (event_id, since),
        ).fetchone()
    return row["heat"] if row else None


# --------------------------------------------------------------------------- #
# 结构化抽取
# --------------------------------------------------------------------------- #

def save_structures(rows: list[dict[str, Any]], day: str | None = None) -> None:
    """写结构化结果。rows: item_id/category/tags/subjects/scope/fact/model/prompt_version。"""
    if not rows:
        return
    day = day or today_str()
    ts = now_str()
    with db() as conn:
        conn.executemany(
            """INSERT INTO structures (item_id, day, category, tags, subjects, scope, fact,
                                       model, prompt_version, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    r["item_id"], day, r.get("category"),
                    json.dumps(r.get("tags") or [], ensure_ascii=False),
                    json.dumps(r.get("subjects") or [], ensure_ascii=False),
                    r.get("scope"),
                    json.dumps(r.get("fact") or {}, ensure_ascii=False),
                    r.get("model"), r.get("prompt_version"), ts,
                )
                for r in rows
            ],
        )


def structure_rows(day: str | None = None, category: str | None = None) -> list[dict[str, Any]]:
    day = day or today_str()
    sql = ("SELECT s.*, i.title, i.url, i.source FROM structures s "
           "JOIN items i ON i.id = s.item_id WHERE s.day = ?")
    args: list[Any] = [day]
    if category:
        sql += " AND s.category = ?"
        args.append(category)
    with db() as conn:
        return [dict(r) for r in conn.execute(sql + " ORDER BY s.id DESC", args).fetchall()]


# --------------------------------------------------------------------------- #
# 出刊与告警
# --------------------------------------------------------------------------- #

def save_edition(kind: str, day: str, entries: int, model: str | None = None) -> None:
    with db() as conn:
        conn.execute(
            """INSERT INTO editions (kind, day, entries, model, generated_at) VALUES (?,?,?,?,?)
               ON CONFLICT(kind, day) DO UPDATE SET entries=excluded.entries,
                 model=excluded.model, generated_at=excluded.generated_at""",
            (kind, day, int(entries), model, now_str()),
        )


def edition_row(kind: str, day: str) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM editions WHERE kind = ? AND day = ?", (kind, day)
        ).fetchone()
    return dict(row) if row else None


def missing_editions(kind: str = "daily", days: int = 7, day: str | None = None) -> list[str]:
    """最近 N 天里没有出刊的日期。

    两个边界：
    - 今天不算缺（还没到点，交给 `edition_missing` 按时限判断）；
    - **比库里最早一期还早的日子不算缺** —— 否则新建的库会一上来就报"缺 7 期"，
      这种误报会让告警失去可信度（实测踩过：空库实跑发了一封"缺 3 期"的邮件）。
    """
    day = day or today_str()
    today = datetime.strptime(day, "%Y-%m-%d")
    start = (today - timedelta(days=days)).strftime("%Y-%m-%d")
    with db() as conn:
        rows = conn.execute(
            "SELECT day FROM editions WHERE kind = ? AND day >= ?", (kind, start)
        ).fetchall()
        earliest_row = conn.execute(
            "SELECT min(day) AS d FROM editions WHERE kind = ?", (kind,)
        ).fetchone()
    if not earliest_row or not earliest_row["d"]:
        return []  # 从来没出过刊：这不是"缺期"，是还没起来
    have = {r["day"] for r in rows}
    earliest = str(earliest_row["d"])
    out: list[str] = []
    for offset in range(1, days + 1):
        d = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
        if d < earliest or d in have:
            continue
        out.append(d)
    return out


def save_alert(kind: str, day: str, message: str, severity: str = "warn") -> bool:
    """同一天同一条告警只记一次，返回是否新写入（避免每轮重复发信）。"""
    with db() as conn:
        cur = conn.execute(
            """INSERT INTO alerts (kind, day, severity, message, created_at) VALUES (?,?,?,?,?)
               ON CONFLICT(kind, day, message) DO NOTHING""",
            (kind, day, severity, message, now_str()),
        )
        return cur.rowcount > 0


def alerts_on(day: str | None = None) -> list[dict[str, Any]]:
    day = day or today_str()
    with db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM alerts WHERE day = ? ORDER BY id", (day,)
        ).fetchall()]


# --------------------------------------------------------------------------- #
# 阅读反馈
# --------------------------------------------------------------------------- #

def latest_structure(item_id: int) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute(
            "SELECT category, tags, subjects, scope FROM structures WHERE item_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (item_id,),
        ).fetchone()
    if not row:
        return None
    out = dict(row)
    for key in ("tags", "subjects"):
        try:
            out[key] = json.loads(out[key] or "[]")
        except Exception:
            out[key] = []
    return out


def item_by_identity(identity: str) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute(
            "SELECT id, identity, source, title, url, layer, region FROM items WHERE identity = ?",
            (identity,),
        ).fetchone()
    return dict(row) if row else None


def save_feedback(identity: str, kind: str, terms: Iterable[str], day: str | None = None) -> bool:
    """同一个身份同一天只保留最后一次态度（改主意就覆盖）。"""
    day = day or today_str()
    with db() as conn:
        conn.execute(
            """INSERT INTO feedback (identity, day, kind, terms, created_at) VALUES (?,?,?,?,?)
               ON CONFLICT(identity, day) DO UPDATE SET
                 kind = excluded.kind, terms = excluded.terms, created_at = excluded.created_at""",
            (identity, day, kind, json.dumps(list(dict.fromkeys(terms)), ensure_ascii=False), now_str()),
        )
    return True


def feedback_rows(days: int = 60, day: str | None = None) -> list[dict[str, Any]]:
    day = day or today_str()
    since = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
    with db() as conn:
        rows = conn.execute(
            "SELECT identity, day, kind, terms FROM feedback WHERE day >= ? ORDER BY day DESC",
            (since,),
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        try:
            item["terms"] = json.loads(item["terms"] or "[]")
        except Exception:
            item["terms"] = []
        out.append(item)
    return out


# --------------------------------------------------------------------------- #
# 推送记录
# --------------------------------------------------------------------------- #

def pushed_identities(kind: str = "breaking") -> set[str]:
    with db() as conn:
        rows = conn.execute("SELECT identity FROM pushes WHERE kind = ?", (kind,)).fetchall()
    return {r["identity"] for r in rows}


def mark_pushed(identities: Iterable[str], kind: str = "breaking", day: str | None = None) -> int:
    idents = [i for i in dict.fromkeys(identities) if i]
    if not idents:
        return 0
    ts = now_str()
    day = day or today_str()
    with db() as conn:
        conn.executemany(
            "INSERT INTO pushes (identity, kind, day, created_at) VALUES (?,?,?,?) "
            "ON CONFLICT(identity, kind) DO NOTHING",
            [(i, kind, day, ts) for i in idents],
        )
    return len(idents)


def event_dump(days: int = 120, day: str | None = None) -> list[dict[str, Any]]:
    """把近 N 天的事件连同成员、结构化结果一起取出来。

    一行 = 一个事件的成员报道。时间线的"公司/产品演进"和"叙事对比"都从它算。
    """
    day = day or today_str()
    since = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
    with db() as conn:
        rows = conn.execute(
            """
            SELECT e.id AS event_id, e.title AS event_title, e.key AS event_key,
                   e.first_at, e.last_at,
                   i.id AS item_id, i.source, i.layer, i.region, i.title AS item_title,
                   i.url, i.published,
                   s.category, s.tags, s.subjects
            FROM events e
            JOIN event_items ei ON ei.event_id = e.id
            JOIN items i       ON i.id = ei.item_id
            LEFT JOIN structures s ON s.item_id = i.id
            WHERE coalesce(e.last_at, '') >= ? OR coalesce(e.updated_at, '') >= ?
            ORDER BY coalesce(e.first_at, ''), e.id
            """,
            (since, since),
        ).fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key in ("tags", "subjects"):
            try:
                item[key] = json.loads(item[key] or "[]")
            except Exception:
                item[key] = []
        out.append(item)
    return out


def structure_history(days: int = 30, day: str | None = None,
                      limit: int = 3000) -> list[dict[str, Any]]:
    """近 N 天的结构化结果（分类 / 标签 / 主体）+ 条目本身。

    主题页要的是"这段时间这个方向都发生了什么"，所以按天往前查，而不是只看今天。
    """
    day = day or today_str()
    since = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
    with db() as conn:
        rows = conn.execute(
            """
            SELECT s.category, s.tags, s.subjects, s.scope, s.day,
                   i.title, i.url, i.source, i.layer, i.region, i.published
            FROM structures s
            JOIN items i ON i.id = s.item_id
            WHERE s.day >= ?
            ORDER BY coalesce(nullif(i.published, ''), s.day) DESC
            LIMIT ?
            """,
            (since, limit),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key in ("tags", "subjects"):
            try:
                item[key] = json.loads(item[key] or "[]")
            except Exception:
                item[key] = []
        out.append(item)
    return out


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
