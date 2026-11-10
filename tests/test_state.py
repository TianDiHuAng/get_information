"""断点续跑：状态文件能存能读，且不会把过期数据当成新的。

三条性质：
1. 存下去的条目读回来必须**完全一样**（含 extra 里的正文、评分、结构化）；
2. 坏了 / 不是同一天的 / 没有的，一律当作"没有状态"，让调用方重新抓；
3. 太旧的状态（默认 12 小时）不用 —— 半天的行情已经变了。
"""

from datetime import datetime, timedelta

import pytest

from collector import state
from collector.model import Item


def mk(url="https://a/1") -> Item:
    it = Item(source="thebatch", title="标题", url=url, layer="primary",
              summary="摘要", published="2026-11-10T09:00:00+08:00")
    it.extra["score"] = 70.5
    it.extra["body"] = "正文" * 50
    it.extra["attention"] = {"available": True, "score": 82}
    return it


def test_round_trip_preserves_everything(tmp_path):
    items = [mk(), mk("https://a/2")]
    state.save({"items": items, "stats": {"sources_ok": 5}}, "2026-11-10", tmp_path)
    back = state.load("2026-11-10", tmp_path)
    assert back is not None
    assert back["stats"]["sources_ok"] == 5
    assert len(back["items"]) == 2
    assert back["items"][0] == items[0]
    assert back["items"][0].extra["attention"]["score"] == 82


def test_missing_state_returns_none(tmp_path):
    assert state.load("2026-11-11", tmp_path) is None


def test_corrupt_state_returns_none(tmp_path):
    target = state.path("2026-11-10", tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{ 不是 json", encoding="utf-8")
    assert state.load("2026-11-10", tmp_path) is None


def test_state_from_another_day_is_ignored(tmp_path):
    state.save({"items": [mk()], "stats": {}}, "2026-11-09", tmp_path)
    # 文件被改名为今天，但内容里的 day 还是昨天
    state.path("2026-11-09", tmp_path).rename(state.path("2026-11-10", tmp_path))
    assert state.load("2026-11-10", tmp_path) is None


def test_empty_items_means_no_state(tmp_path):
    state.save({"items": [], "stats": {}}, "2026-11-10", tmp_path)
    assert state.load("2026-11-10", tmp_path) is None


def test_stale_state_is_flagged(tmp_path):
    import json

    state.save({"items": [mk()], "stats": {}}, "2026-11-10", tmp_path)
    target = state.path("2026-11-10", tmp_path)
    data = json.loads(target.read_text(encoding="utf-8"))
    data["saved_at"] = (datetime.now() - timedelta(hours=20)).isoformat(timespec="seconds")
    target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert state.is_stale("2026-11-10", tmp_path, hours=12) is True


def test_fresh_state_is_not_stale(tmp_path):
    state.save({"items": [mk()], "stats": {}}, "2026-11-10", tmp_path)
    assert state.is_stale("2026-11-10", tmp_path, hours=12) is False


def test_prune_keeps_most_recent(tmp_path):
    for day in ("2026-11-07", "2026-11-08", "2026-11-09", "2026-11-10"):
        state.save({"items": [mk()], "stats": {}}, day, tmp_path)
    removed = state.prune(tmp_path, keep=2)
    assert removed == 2
    left = sorted(p.name for p in (tmp_path / "data").glob("state-*.json"))
    assert left == ["state-2026-11-09.json", "state-2026-11-10.json"]


def test_ensure_stats_fills_missing_fields():
    """续跑读回的是上一次的 stats，字段可能比现在的代码少。"""
    got = state.ensure_stats({"sources_ok": 7}, items=12)
    assert got["sources_ok"] == 7          # 有就用原值
    assert got["generated_at"]
    assert got["registry"] == [] and got["errors"] == []
    assert got["by_layer"] == {} and got["by_region"] == {}
    assert got["raw"] == 12


def test_ensure_stats_handles_none():
    got = state.ensure_stats(None)
    assert got["sources_ok"] == 0 and isinstance(got["generated_at"], str)


def test_discard_removes_only_that_day(tmp_path):
    state.save({"items": [mk()], "stats": {}}, "2026-11-09", tmp_path)
    state.save({"items": [mk()], "stats": {}}, "2026-11-10", tmp_path)
    assert state.discard("2026-11-10", tmp_path) is True
    assert state.path("2026-11-10", tmp_path).exists() is False
    assert state.path("2026-11-09", tmp_path).exists() is True
