"""公开读取层：旧文归档、无日期不公开。

这条规则解决一个真实问题：第一轮实跑 175 条里，71 条早于 3 天、21 条没有发布时间 ——
40% 的"今天"其实是旧文。所以测试重点是**边界**：48 小时这条线前后的判定。
"""

from datetime import date, timedelta

import pytest

from collector import scope


@pytest.fixture(autouse=True)
def conf(tmp_path, monkeypatch):
    path = tmp_path / "scope.yaml"
    path.write_text("max_age_hours: 48\nrequire_date: true\n", encoding="utf-8")
    monkeypatch.setattr(scope, "CONFIG_PATH", path)
    yield path


def today() -> str:
    return date.today().isoformat()


def days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def test_today_item_is_public():
    status, _ = scope.classify(f"{today()}T08:00:00+08:00", today())
    assert status == "today"


def test_one_day_old_is_still_public():
    status, _ = scope.classify(f"{days_ago(1)}T08:00:00", today())
    assert status == "today"


def test_three_days_old_is_archived():
    status, reason = scope.classify(f"{days_ago(3)}T08:00:00", today())
    assert status == "archive"
    assert "3 天" in reason


def test_missing_date_is_undated():
    status, reason = scope.classify("", today())
    assert status == "undated" and reason


def test_garbage_date_is_undated():
    assert scope.classify("昨天下午", today())[0] == "undated"


def test_require_date_false_allows_undated(tmp_path, monkeypatch):
    path = tmp_path / "scope2.yaml"
    path.write_text("max_age_hours: 48\nrequire_date: false\n", encoding="utf-8")
    monkeypatch.setattr(scope, "CONFIG_PATH", path)
    assert scope.classify("", today())[0] == "today"


def test_public_filters_archive_and_undated():
    rows = [
        {"published": f"{today()}T08:00:00"},
        {"published": f"{days_ago(5)}T08:00:00"},
        {"published": ""},
    ]
    assert len(scope.public(rows, today())) == 1


def test_public_include_archived_keeps_old_but_not_undated():
    rows = [{"published": f"{days_ago(5)}T08:00:00"}, {"published": ""}]
    kept = scope.public(rows, today(), include_archived=True)
    assert len(kept) == 1 and kept[0]["published"]


def test_summary_counts_three_states():
    rows = [{"published": f"{today()}T08:00:00"},
            {"published": f"{days_ago(6)}T08:00:00"},
            {"published": ""}]
    assert scope.summary(rows, today()) == {"today": 1, "archive": 1, "undated": 1}


def test_store_all_items_hides_stale_by_default(tmpdb):
    from collector.model import Item
    from collector import store

    fresh = Item(source="a", title="今天的新闻", url="https://s/1",
                 published=f"{today()}T08:00:00")
    stale = Item(source="b", title="五天前的旧闻", url="https://s/2",
                 published=f"{days_ago(5)}T08:00:00")
    undated = Item(source="c", title="没有日期的新闻", url="https://s/3")
    store.upsert_items([fresh, stale, undated])

    assert [r["title"] for r in store.all_items()] == ["今天的新闻"]
    assert len(store.all_items(include_archived=True)) == 2
    assert len(store.all_items(include_archived=True, include_undated=True)) == 3
