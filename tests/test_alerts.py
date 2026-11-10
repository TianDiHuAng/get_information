"""告警：能发现真问题，且同一天同一条不重复发。

告警最容易出的两种错：**没发现**（等于没有）和**每次都发**（等于噪声）。
这里两边都测。
"""

from datetime import datetime, timedelta

import pytest

from collector import alerts, store


@pytest.fixture(autouse=True)
def after_deadline(monkeypatch):
    """默认把"现在"设在出刊点之后，这样缺期检测才有意义。"""
    monkeypatch.setattr(alerts, "_now", lambda: datetime.now().replace(hour=11, minute=0))


def test_source_with_repeated_failures_is_flagged(tmpdb):
    store.save_source_health({"x": {"fails": 5, "last_error": "timeout", "last_count": 0}})
    found = alerts.check()
    kinds = {a["kind"] for a in found}
    assert "source_fails" in kinds


def test_silent_source_is_flagged(tmpdb):
    old = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    store.save_source_health({"weibo": {"fails": 0, "last_ok": old, "last_count": 15}})
    found = alerts.check()
    assert any(a["kind"] == "source_silent" for a in found)


def test_healthy_source_is_quiet(tmpdb):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    store.save_source_health({"hackernews": {"fails": 0, "last_ok": now, "last_count": 12}})
    assert [a for a in alerts.check() if a["kind"].startswith("source_")] == []


def test_missing_daily_is_an_error(tmpdb):
    found = alerts.check()
    assert any(a["kind"] == "edition_missing" and a["severity"] == "error" for a in found)


def test_existing_daily_is_not_a_missing_alert(tmpdb):
    store.save_edition("daily", store.today_str(), entries=20)
    found = alerts.check()
    assert not any(a["kind"] == "edition_missing" for a in found)


def test_before_deadline_is_not_an_alert(tmpdb, monkeypatch):
    monkeypatch.setattr(alerts, "_now", lambda: datetime.now().replace(hour=7, minute=0))
    assert not any(a["kind"] == "edition_missing" for a in alerts.check())


def test_edition_gap_is_flagged(tmpdb):
    """只有已经出过刊之后的日子才算"缺期"——空库不该一上来就报缺 7 期。"""
    from datetime import datetime, timedelta

    today = datetime.now()
    store.save_edition("daily", (today - timedelta(days=2)).strftime("%Y-%m-%d"), entries=5)
    store.save_edition("daily", store.today_str(), entries=10)
    found = alerts.check()
    gap = [a for a in found if a["kind"] == "edition_gap"]
    assert gap, "中间那天确实缺了，要报"


def test_fresh_database_does_not_report_gaps(tmpdb):
    """空库只报"今天没出刊"，不报"缺了 N 期"。"""
    found = alerts.check()
    assert not any(a["kind"] == "edition_gap" for a in found)


def test_alert_is_recorded_only_once(tmpdb):
    found = alerts.check()
    fresh = alerts.record(found)
    assert len(fresh) == len(found)
    again = alerts.record(alerts.check())
    assert again == [], "同一天同一条告警不能重复发"


def test_render_marks_severity(tmpdb):
    store.save_edition("daily", store.today_str(), entries=1)
    subject, body = alerts.render([
        {"kind": "edition_missing", "severity": "error", "message": "没出刊"},
        {"kind": "source_silent", "severity": "warn", "message": "微博哑了"},
    ])
    assert "告警" in subject
    assert "❌" in body and "⚠️" in body


def test_run_never_raises_and_reports_counts(tmpdb):
    result = alerts.run(notify=False)
    assert "found" in result
    assert result["sent"] == "skipped"


def test_run_sends_only_when_something_is_fresh(tmpdb, monkeypatch):
    calls = {"n": 0}

    def fake_send(found):
        calls["n"] += 1
        return "mail-sent(test)"

    monkeypatch.setattr(alerts, "send", fake_send)
    alerts.run(notify=True)
    assert calls["n"] == 1, "有新告警应当发信"

    alerts.run(notify=True)
    assert calls["n"] == 1, "同一批告警不该发第二次"


def test_rating_failure_ratio_from_payload(tmpdb):
    store.save_edition("daily", store.today_str(), entries=1)
    payload = {"stats": {"attention": {"scored": 10, "failed": 8}}}
    found = alerts.check(payload)
    assert any(a["kind"] == "rating_failures" for a in found)
