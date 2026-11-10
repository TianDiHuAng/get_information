"""安全阀与公开席位。

安全阀最容易写错的地方是**默认值**：推送默认关（误触代价最大），
采集与模型默认开（否则日常运行要记着开）。测试把这三条钉住。

席位规则解决"同一个事件在 RSS 里出现五遍"——机器出口每条新闻只出一条。
"""

import pytest

from collector import publication, valves


# —— 安全阀 —— #

def test_defaults(monkeypatch):
    for key in ("RADAR_COLLECT", "RADAR_MODEL", "RADAR_PUSH"):
        monkeypatch.delenv(key, raising=False)
    assert valves.enabled("collect") is True
    assert valves.enabled("model") is True
    assert valves.enabled("push") is False      # 推送默认关，必须显式打开


@pytest.mark.parametrize("raw,expected", [
    ("1", True), ("true", True), ("YES", True), ("on", True),
    ("0", False), ("false", False), ("NO", False), ("off", False),
])
def test_explicit_values(monkeypatch, raw, expected):
    monkeypatch.setenv("RADAR_COLLECT", raw)
    assert valves.enabled("collect") is expected


def test_garbage_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("RADAR_PUSH", "随便写的")
    assert valves.enabled("push") is False


def test_describe_lists_all_three(monkeypatch):
    monkeypatch.delenv("RADAR_PUSH", raising=False)
    text = valves.describe()
    for name in ("collect", "model", "push"):
        assert name in text


def test_pipeline_skips_network_when_collect_off(monkeypatch):
    from collector import pipeline

    monkeypatch.setenv("RADAR_COLLECT", "0")
    called = []
    monkeypatch.setattr(pipeline, "build_fetchers",
                        lambda: [("a", lambda: called.append("a") or [])])
    items, errors, counts, ok = pipeline.fetch_all()
    assert items == [] and called == []       # 一次网络都没发


def test_llm_returns_none_when_model_off(monkeypatch):
    from collector import llm

    monkeypatch.setenv("RADAR_MODEL", "0")
    assert llm.call_json("t", "v", "s", "u") is None
    assert llm.call_text("t", "v", "s", "u") is None


# —— 公开席位 —— #

def item(title, url, source="x", score=0, layer="broad", event=None, published="2026-11-10"):
    return {"title": title, "url": url, "source": source, "layer": layer,
            "published": published,
            "extra": {"attention": {"score": score}, "event_id": event}}


def test_export_requires_evidence():
    assert publication.has_evidence(item("标题", "https://a/1"))
    assert not publication.has_evidence(item("", "https://a/1"))
    assert not publication.has_evidence(item("标题", ""))
    assert not publication.has_evidence(item("标题", "https://a/1", source=""))


def test_same_event_keeps_highest_score():
    rows = [item("低分稿", "https://a/1", score=40, event=7),
            item("高分稿", "https://a/2", score=90, event=7)]
    out = publication.for_export(rows)
    assert len(out) == 1 and out[0]["title"] == "高分稿"


def test_same_event_tie_prefers_first_party():
    rows = [item("媒体稿", "https://a/1", score=80, layer="broad", event=7),
            item("官方稿", "https://a/2", score=80, layer="primary", event=7)]
    out = publication.for_export(rows)
    assert len(out) == 1 and out[0]["title"] == "官方稿"


def test_items_without_event_are_all_kept():
    rows = [item("甲", "https://a/1", score=10), item("乙", "https://a/2", score=20)]
    assert len(publication.for_export(rows)) == 2


def test_export_sorted_by_score():
    rows = [item("低", "https://a/1", score=10), item("高", "https://a/2", score=90)]
    out = publication.for_export(rows)
    assert [o["title"] for o in out] == ["高", "低"]


def test_summary_counts_merged():
    rows = [item("甲", "https://a/1", score=10, event=1),
            item("乙", "https://a/2", score=20, event=1),
            item("丙", "https://a/3", score=30)]
    assert publication.summary(rows) == {"in": 3, "out": 2, "merged": 1}
