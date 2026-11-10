"""突发即时推与多通道。

两条容易出错的规则，各有用例守着：
1. **没有可信时间就不算突发** —— 猜一个时间会半夜叫醒你；
2. **只在至少一个通道成功时才记"已推"** —— 否则通道临时挂了，这条就永远推不出去。
"""

from datetime import datetime, timedelta, timezone

import pytest

from collector import breaking, push, store


def mk(url="https://a/1", score=95, layer="primary", hours_ago=1.0,
       available=True, deal=False, title="OpenAI 发布新模型") -> dict:
    published = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat() \
        if hours_ago is not None else ""
    return {"source": "thebatch", "title": title, "url": url, "layer": layer,
            "region": "overseas", "summary": "摘要", "published": published,
            "extra": {"deal": deal,
                      "attention": {"available": available, "score": score,
                                    "itype": "model_release", "axes": {"sig": 9},
                                    "reason": "正式发布"}}}


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    monkeypatch.setattr(breaking, "rules", lambda: {
        "enabled": True, "min_score": 85, "max_age_hours": 12,
        "only_primary": True, "max_per_run": 2, "quiet_hours": [23, 8],
    })
    yield


def test_selects_high_score_fresh_primary():
    got = breaking.select([mk()], pushed=set())
    assert len(got) == 1


def test_rejects_low_score():
    assert breaking.select([mk(score=70)], pushed=set()) == []


def test_rejects_stale():
    assert breaking.select([mk(hours_ago=20)], pushed=set()) == []


def test_rejects_without_trustworthy_time():
    """没有发布时间就不知道新不新，宁可漏报也不半夜叫人。"""
    assert breaking.select([mk(hours_ago=None)], pushed=set()) == []


def test_official_host_counts_as_first_party():
    """HN 上的 Anthropic 官方博客必须算一手 —— 那恰恰是最该推的。"""
    conf = {"only_primary": True, "official_hosts": ["anthropic.com"]}
    item = mk(layer="rank", url="https://www.anthropic.com/news/x")
    assert breaking.is_official(item, conf) is True


def test_media_host_is_not_official():
    conf = {"only_primary": True, "official_hosts": ["anthropic.com"]}
    assert breaking.is_official(mk(layer="rank", url="https://sspai.com/post/1"), conf) is False


def test_subdomain_matches_but_lookalike_does_not():
    conf = {"official_hosts": ["anthropic.com"]}
    assert breaking.is_official(mk(layer="rank", url="https://blog.anthropic.com/a"), conf) is True
    assert breaking.is_official(mk(layer="rank", url="https://notanthropic.com/a"), conf) is False


def test_rejects_media_when_only_primary():
    assert breaking.select([mk(layer="rank")], pushed=set()) == []


def test_media_allowed_when_configured(monkeypatch):
    monkeypatch.setattr(breaking, "rules", lambda: {
        "enabled": True, "min_score": 85, "max_age_hours": 12,
        "only_primary": False, "max_per_run": 2, "quiet_hours": [],
    })
    assert len(breaking.select([mk(layer="rank")], pushed=set())) == 1


def test_rejects_unscored_and_deals():
    assert breaking.select([mk(available=False)], pushed=set()) == []
    assert breaking.select([mk(deal=True)], pushed=set()) == []


def test_never_pushes_the_same_item_twice():
    item = mk()
    assert breaking.select([item], pushed={"url:https://a/1"}) == []


def test_limit_is_respected():
    items = [mk(url=f"https://a/{i}", score=95 - i) for i in range(5)]
    assert len(breaking.select(items, pushed=set())) == 2


def test_highest_score_first():
    items = [mk(url="https://a/low", score=86), mk(url="https://a/high", score=99)]
    assert breaking.select(items, pushed=set())[0]["url"] == "https://a/high"


def test_quiet_hours_span_midnight():
    assert breaking.in_quiet_hours(datetime(2026, 11, 10, 23, 30)) is True
    assert breaking.in_quiet_hours(datetime(2026, 11, 10, 2, 0)) is True
    assert breaking.in_quiet_hours(datetime(2026, 11, 10, 9, 0)) is False


def test_run_is_silent_during_quiet_hours():
    result = breaking.run([mk()], now=datetime(2026, 11, 10, 2, 0))
    assert result == {"skipped": "quiet-hours"}


def test_run_marks_pushed_only_after_success(tmpdb, monkeypatch):
    monkeypatch.setattr(breaking, "in_quiet_hours", lambda now=None: False)
    sent = {}

    def fake_send(subject, text, only=None):
        sent["subject"] = subject
        sent["text"] = text
        return {"telegram": "telegram-sent"}

    monkeypatch.setattr(breaking.push, "send", fake_send)
    result = breaking.run([mk()], now=datetime.now(timezone.utc))
    assert result["picked"] == 1 and result["marked"] is True
    assert "OpenAI 发布新模型" in sent["text"]
    assert "url:https://a/1" in store.pushed_identities("breaking")


def test_failed_channels_do_not_mark_pushed(tmpdb, monkeypatch):
    monkeypatch.setattr(breaking, "in_quiet_hours", lambda now=None: False)
    monkeypatch.setattr(breaking.push, "send",
                        lambda subject, text, only=None: {"telegram": "telegram-failed: Timeout"})
    result = breaking.run([mk()], now=datetime.now(timezone.utc))
    assert result["marked"] is False
    assert store.pushed_identities("breaking") == set()


def test_push_channels_reflect_config(monkeypatch):
    monkeypatch.setattr(push, "config", lambda: {"channels": {
        "email": True,
        "telegram": {"enabled": True, "bot_token": "t", "chat_id": "c"},
        "webhook": {"enabled": True, "url": ""},
    }})
    assert push.channels() == ["email", "telegram"]


def test_push_with_no_channel_is_silent(monkeypatch):
    monkeypatch.setattr(push, "config", lambda: {"channels": {}})
    assert push.send("s", "t") == {"status": "no-channel"}


def test_one_channel_failure_does_not_stop_others(monkeypatch):
    monkeypatch.setattr(push, "config", lambda: {"channels": {"email": True, "telegram": {
        "enabled": True, "bot_token": "t", "chat_id": "c"}}})

    def boom(subject, text):
        raise RuntimeError("smtp down")

    monkeypatch.setitem(push._SENDERS, "email", boom)
    monkeypatch.setitem(push._SENDERS, "telegram", lambda s, t: "telegram-sent")
    got = push.send("s", "t")
    assert got["email"].startswith("error")
    assert got["telegram"] == "telegram-sent"
