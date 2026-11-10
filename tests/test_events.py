"""事件聚簇：粗排、判定、复核、合并、热度、代表稿。

全部用假 LLM，不联网不花钱。重点回归 **LG 那两条** ——
它们在 11-10 的日报里重复出现过，标题相似度只有 0.50，靠标题永远合不了。
"""

import pytest

from collector import events, store
from collector.identity import title_similar
from collector.model import Item


def mk(url: str, title: str, source: str = "google_news", layer: str = "search",
       summary: str = "", published: str = "2026-11-10T09:00:00+00:00") -> Item:
    return Item(source=source, title=title, url=url, layer=layer, summary=summary,
                published=published, region="domestic")


LG_A = "LG免费开放K-EXAONE2.5模型API - 汽车之家"
LG_B = "LG AI Research 开放 K-EXAONE 2.5 模型免费 API 访问 - Unite.AI"


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch):
    """默认：两条同源新闻判成同一次发生；其余一律无关。"""
    monkeypatch.setattr(events.llm, "available", lambda: True)

    def call_json(task, version, system, user, **kw):
        if task == "group-review":
            return {"agree": True, "relation": "SAME_OCCURRENCE", "confidence": 0.9, "why": "同一发布"}
        if "LG" in user and ("K-EXAONE" in user or "K-EXAONE" in user.replace(" ", "")):
            return {"a": "LG 开放 K-EXAONE 2.5 API", "b": "LG 开放 K-EXAONE 2.5 API",
                    "relation": "SAME_OCCURRENCE", "difference": "", "confidence": 0.93}
        return {"a": "A", "b": "B", "relation": "UNRELATED", "difference": "不同的事",
                "confidence": 0.9}

    monkeypatch.setattr(events.llm, "call_json", call_json)
    return call_json


def test_lg_pair_is_below_title_threshold():
    """这条断言是整件事的动机：标题相似度只有 0.5，比标题永远合不了。"""
    assert title_similar(LG_A, LG_B) < 0.72


def test_tokens_keep_rare_entities():
    t = events.tokens(LG_A)
    assert "k-exaone" in t or "exaone" in t
    assert "lg" in t


def test_idf_weights_rare_tokens_more():
    common = {"a", "b"}
    rare = {"k-exaone", "2.5"}
    idf = events.build_idf([common, common, common, rare])
    assert idf["k-exaone"] > idf["a"]


def test_pair_score_prefers_shared_rare_tokens():
    idf = {"a": 1.0, "k-exaone": 3.0, "2.5": 3.0}
    high = events.pair_score({"k-exaone", "2.5", "a"}, {"k-exaone", "2.5"}, idf)
    low = events.pair_score({"a", "b"}, {"a", "c"}, idf)
    assert high > low


def test_cluster_merges_same_event_and_picks_representative(tmpdb):
    a = mk("https://news.google.com/rss/articles/AAA?oc=5", LG_A, summary="LG 宣布开放 API")
    b = mk("https://news.google.com/rss/articles/BBB?oc=5", LG_B, summary="LG AI Research 开放访问")
    store.upsert_items([a, b])
    stats = events.cluster_items([a, b])

    assert stats["events"] == 1
    assert stats["merged"] == 1
    assert a.extra["event_id"] == b.extra["event_id"]
    assert a.extra["event_size"] == 2
    # 代表稿只有一个；另一条被标 False
    reps = [x for x in (a, b) if x.extra["event_representative"]]
    assert len(reps) == 1


def test_cluster_keeps_unrelated_apart(tmpdb):
    a = mk("https://example.com/1", "OpenAI 发布 GPT-6", source="thebatch", layer="primary")
    b = mk("https://example.com/2", "英伟达发布新显卡驱动", source="hackernews", layer="rank")
    store.upsert_items([a, b])
    stats = events.cluster_items([a, b])
    # 单篇不建事件壳（event_id 为 None），但各自都是自己的代表
    assert stats["events"] == 0
    assert a.extra["event_id"] is None and b.extra["event_id"] is None
    assert a.extra["event_size"] == 1 and b.extra["event_size"] == 1


def test_pair_decisions_are_cached_not_repaid(tmpdb):
    a = mk("https://news.google.com/rss/articles/AAA?oc=5", LG_A)
    b = mk("https://news.google.com/rss/articles/BBB?oc=5", LG_B)
    store.upsert_items([a, b])
    first = events.cluster_items([a, b])
    assert first["pairs_new"] >= 1

    # 第二轮：同一对已经在库里，不应再花模型钱
    second = events.cluster_items([a, b])
    assert second["pairs_new"] == 0
    assert second["pairs_judged"] >= 1


def test_review_runs_for_low_confidence(tmpdb, monkeypatch):
    calls = {"n": 0}

    def low(task, version, system, user, **kw):
        if task == "group-review":
            calls["n"] += 1
            return {"agree": True, "relation": "SAME_OCCURRENCE", "confidence": 0.95}
        return {"a": "A", "b": "B", "relation": "SAME_OCCURRENCE", "confidence": 0.5}

    monkeypatch.setattr(events.llm, "call_json", low)
    a = mk("https://example.com/1", LG_A)
    b = mk("https://example.com/2", LG_B)
    store.upsert_items([a, b])
    events.cluster_items([a, b])
    assert calls["n"] >= 1, "低置信度的合并必须复核"


def test_review_disagreement_blocks_merge(tmpdb, monkeypatch):
    def disagree(task, version, system, user, **kw):
        if task == "group-review":
            return {"agree": False, "relation": "SAME_OCCURRENCE", "confidence": 0.9, "why": "不同事"}
        return {"a": "A", "b": "B", "relation": "SAME_OCCURRENCE", "confidence": 0.5}

    monkeypatch.setattr(events.llm, "call_json", disagree)
    a = mk("https://example.com/1", LG_A)
    b = mk("https://example.com/2", LG_B)
    store.upsert_items([a, b])
    events.cluster_items([a, b])
    # 复核否决 → 不合并 → 两条都还是各自独立的单篇
    assert a.extra["event_id"] is None and b.extra["event_id"] is None
    assert a.extra["event_size"] == 1 and b.extra["event_size"] == 1


def test_no_llm_falls_back_to_similarity(tmpdb, monkeypatch):
    monkeypatch.setattr(events.llm, "available", lambda: False)
    a = mk("https://example.com/1", "苹果发布 M5 芯片，性能提升 40%")
    b = mk("https://example.com/2", "苹果发布 M5 芯片，性能提升 40%！")
    c = mk("https://example.com/3", LG_B)
    store.upsert_items([a, b, c])
    stats = events.cluster_items([a, b, c])
    assert stats["llm"] is False
    assert a.extra["event_id"] == b.extra["event_id"]  # 几乎一样的标题仍然合并
    assert a.extra["event_id"] != c.extra["event_id"]  # 但 LG 那两条不会被误合


def test_heat_uses_half_life_and_independent_participants():
    from datetime import datetime, timedelta, timezone

    conf = {"heat": {"window_hours": 48, "half_life_hours": 24, "min_participants": 2}}
    now = datetime.now(timezone.utc)
    members = [
        {"source": "thebatch", "published": now.isoformat()},
        {"source": "thebatch", "published": now.isoformat()},  # 同一家再来一篇：不额外加热
        {"source": "hackernews", "published": (now - timedelta(hours=24)).isoformat()},  # 半衰
    ]
    heat, participants = events.heat_of(members, conf)
    assert participants == 2
    assert heat == pytest.approx(1.5, abs=0.02)


def test_participant_groups_merge_matrix_accounts():
    from datetime import datetime, timezone

    conf = {"heat": {"window_hours": 48, "half_life_hours": 24, "min_participants": 2,
                     "participant_groups": {"weibo_matrix": ["weibo", "weibo2"]}}}
    now = datetime.now(timezone.utc).isoformat()
    members = [
        {"source": "weibo", "published": now},
        {"source": "weibo2", "published": now},
    ]
    _, participants = events.heat_of(members, conf)
    assert participants == 1, "同一矩阵的两个号只应算一个参与方"


def test_old_evidence_falls_outside_window():
    from datetime import datetime, timedelta, timezone

    conf = {"heat": {"window_hours": 48, "half_life_hours": 24, "min_participants": 2}}
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    heat, participants = events.heat_of([{"source": "x", "published": old}], conf)
    assert (heat, participants) == (0.0, 0)


def test_representative_first_collapses_one_event(tmpdb):
    a = mk("https://example.com/1", LG_A)
    b = mk("https://example.com/2", LG_B)
    store.upsert_items([a, b])
    events.cluster_items([a, b])
    payload = [a.to_dict(), b.to_dict()]
    kept = events.representative_first(payload)
    assert len(kept) == 1


def test_digest_skips_non_representative(tmpdb):
    from collector import digest

    a = mk("https://example.com/1", LG_A, source="google_news")
    b = mk("https://example.com/2", LG_B, source="google_news")
    a.extra["score"] = 60.0
    b.extra["score"] = 55.0
    store.upsert_items([a, b])
    events.cluster_items([a, b])
    payload = {"items": [a.to_dict(), b.to_dict()],
               "stats": {"sources_ok": 1, "by_region": {}, "by_layer": {}}}
    picked = digest.picked(payload)
    assert len(picked) == 1, "同一事件不该在日报里出现两次"
