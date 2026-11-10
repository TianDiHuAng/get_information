"""存储层：跨天去重、已报抑制、评分留痕。"""

import json

from collector import store
from collector.identity import item_identity
from collector.model import Item


def mk(url: str, source: str = "hackernews", title: str = "标题", **kw) -> Item:
    return Item(source=source, title=title, url=url, **kw)


def test_migrate_is_idempotent(tmpdb):
    assert store.migrate() == len(store.MIGRATIONS)
    assert store.migrate() == len(store.MIGRATIONS)  # 第二次不应报错


def test_upsert_reports_new_then_seen(tmpdb):
    first = store.upsert_items([mk("https://a.com/1"), mk("https://a.com/2")])
    assert len(first["new"]) == 2 and not first["seen"]

    second = store.upsert_items([mk("https://a.com/1"), mk("https://a.com/3")])
    assert second["new"] == {item_identity("https://a.com/3")}
    assert second["seen"] == {item_identity("https://a.com/1")}


def test_upsert_keeps_first_seen_and_updates_last_seen(tmpdb):
    store.upsert_items([mk("https://a.com/1")], day="2026-11-01")
    store.upsert_items([mk("https://a.com/1")], day="2026-11-10")
    with store.db() as conn:
        row = conn.execute("SELECT first_seen, last_seen FROM items").fetchone()
    assert row["first_seen"] == "2026-11-01"
    assert row["last_seen"] == "2026-11-10"


def test_upsert_prefers_longer_title_and_summary(tmpdb):
    store.upsert_items([mk("https://a.com/1", title="短", summary="")])
    store.upsert_items([mk("https://a.com/1", title="更长的标题", summary="有摘要了")])
    with store.db() as conn:
        row = conn.execute("SELECT title, summary FROM items").fetchone()
    assert row["title"] == "更长的标题"
    assert row["summary"] == "有摘要了"


def test_fingerprint_change_bumps_revision(tmpdb):
    """同一入口的内容被更新（补了摘要）→ 修订号 +1，值得重新判定。"""
    store.upsert_items([mk("https://a.com/1", title="原标题", summary="")])
    first = store.upsert_items([mk("https://a.com/1", title="原标题", summary="")])
    assert first["revised"] == set(), "内容没变不该算修订"

    second = store.upsert_items([mk("https://a.com/1", title="原标题", summary="媒体补充了价格细节")])
    assert item_identity("https://a.com/1") in second["revised"]
    with store.db() as conn:
        assert conn.execute("SELECT revision FROM items").fetchone()["revision"] == 2


def test_backfill_attention_merges_scores_into_extra(tmpdb):
    """评分只写 scores 表时，从库里读的地方（周报）看不到分 —— 回填补上。"""
    store.upsert_items([mk("https://a/1")])
    ids = store.ids_for([item_identity("https://a/1")])
    item_id = ids[item_identity("https://a/1")]
    store.save_scores([
        {"item_id": item_id, "call_no": 1, "itype": "model_release", "axes": {}, "score": 80},
        {"item_id": item_id, "call_no": 2, "itype": "model_release", "axes": {}, "score": 70},
    ])
    assert store.backfill_attention() == 1
    with store.db() as conn:
        extra = json.loads(conn.execute("SELECT extra FROM items").fetchone()["extra"])
    assert extra["attention"]["score"] == 75      # 两次的平均
    assert extra["attention"]["calls"] == 2
    # 再跑一次不重复处理
    assert store.backfill_attention() == 0


def test_pair_dump_carries_body_for_evaluation(tmpdb):
    """归组评测要拿正文，否则评的是一个比线上更差的分布。"""
    import json as _json

    store.upsert_items([mk("https://a/1"), mk("https://a/2")])
    with store.db() as conn:
        for ident, body in (("url:https://a/1", "第一篇正文"), ("url:https://a/2", "第二篇正文")):
            conn.execute("UPDATE items SET extra = ? WHERE identity = ?",
                         (_json.dumps({"body": body}, ensure_ascii=False), ident))
    store.save_pairs([{"a": "url:https://a/1", "b": "url:https://a/2",
                       "relation": "SAME_OCCURRENCE", "confidence": 0.9}])
    rows = store.pair_dump(limit=5)
    assert len(rows) == 1
    assert rows[0]["a_body"] == "第一篇正文"
    assert rows[0]["b_body"] == "第二篇正文"


def test_reported_items_are_suppressed_then_expire(tmpdb):
    items = [mk("https://a.com/1"), mk("https://a.com/2")]
    store.upsert_items(items, day="2026-11-10")
    assert store.mark_reported(items, day="2026-11-10") == 2

    recent = store.recently_reported(days=7, day="2026-11-12")
    assert item_identity("https://a.com/1") in recent

    # 8 天后窗口滑出，重新可以出现
    old = store.recently_reported(days=7, day="2026-11-20")
    assert item_identity("https://a.com/1") not in old


def test_mark_reported_accepts_dicts(tmpdb):
    """日报选中的是 dict（payload["items"]），不是 Item。"""
    store.upsert_items([mk("https://a.com/1")])
    assert store.mark_reported([{"url": "https://a.com/1"}]) == 1


def test_scores_are_persisted_and_summarised(tmpdb):
    store.upsert_items([mk("https://a.com/1")])
    ids = store.ids_for([item_identity("https://a.com/1")])
    item_id = ids[item_identity("https://a.com/1")]
    store.save_scores([
        {"item_id": item_id, "call_no": 1, "itype": "model_release",
         "axes": {"sig": 9, "nov": 8, "cred": 7, "reson": 9, "act": 5}, "score": 80, "reason": "新模型"},
        {"item_id": item_id, "call_no": 2, "itype": "model_release",
         "axes": {"sig": 8, "nov": 8, "cred": 7, "reson": 8, "act": 5}, "score": 72, "reason": "新模型"},
    ])
    dist = store.score_distribution()
    assert dist["count"] == 2 and dist["min"] == 72 and dist["max"] == 80


def test_run_stages_record_progress(tmpdb):
    run_id = store.run_start("2026-11-10", "pipeline")
    assert "pipeline" not in store.stages_done("2026-11-10")
    store.run_finish(run_id, "ok")
    assert "pipeline" in store.stages_done("2026-11-10")


def test_source_health_upsert(tmpdb):
    store.save_source_health({"x": {"fails": 2, "last_ok": "2026-11-10 09:00:00", "last_count": 26}})
    store.save_source_health({"x": {"fails": 0, "last_count": 30}})
    rows = store.source_rows()
    assert rows[0]["fails"] == 0
    assert rows[0]["last_ok"] == "2026-11-10 09:00:00"  # 新的没带时间，保留旧的
    assert rows[0]["last_count"] == 30
