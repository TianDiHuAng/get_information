"""阅读反馈 → 兴趣权重 → 排序微调。

三条值得守住的性质（都有测试）：
1. 同一身份同一天改主意，只保留最后一次（否则一正一负互相抵消）；
2. 证据太少的词不参与加权（点一次不该改变口味）；
3. 幅度有上限，而且**不碰入选门槛**——它只让同分条目换先后。
"""

import pytest

from collector import prefs, store
from collector.identity import item_identity
from collector.model import Item


def mk(url="https://a/1", source="thebatch", category="model_release",
       tags=("开源",), subjects=("Anthropic",)) -> Item:
    it = Item(source=source, title="某模型发布新闻标题足够长", url=url, layer="primary")
    it.extra["score"] = 60.0
    it.extra["structure"] = {"category": category, "tags": list(tags),
                             "subjects": list(subjects), "scope": "single"}
    return it


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    monkeypatch.setattr(prefs, "config", lambda: {
        "enabled": True,
        "kinds": {"up": 1.0, "down": -1.2, "open": 0.25},
        "scale": 0.08, "days": 60, "min_evidence": 2, "max_terms": 300,
    })


def test_terms_come_from_structure():
    terms = prefs.terms_of(mk())
    assert "cat:model_release" in terms
    assert "tag:开源" in terms
    assert "sub:Anthropic" in terms


def test_terms_work_for_db_rows_too():
    """反馈是在 HTTP 请求里记的，那里只有 dict，没有 Item 对象。"""
    row = {"source": "thebatch",
           "extra": {"structure": {"category": "model_release", "tags": ["开源"],
                                   "subjects": ["Anthropic"]}}}
    assert "cat:model_release" in prefs.terms_of(row)


def test_terms_fall_back_to_source_without_structure():
    it = mk()
    it.extra.pop("structure")
    assert prefs.terms_of(it) == ["src:thebatch"]


def persist(items) -> None:
    """把条目和它的结构化结果一起落库 —— 服务器端只能从库里查到这两样。"""
    store.upsert_items(items)
    ids = store.ids_for([item_identity(i.url) for i in items])
    rows = []
    for it in items:
        item_id = ids[item_identity(it.url)]
        st = it.extra["structure"]
        rows.append({"item_id": item_id, **st})
    store.save_structures(rows)


def test_record_stores_terms_for_known_item(tmpdb):
    it = mk()
    persist([it])
    got = prefs.record(it.url, "up")
    assert got["ok"] is True
    assert "cat:model_release" in got["terms"]
    rows = store.feedback_rows()
    assert len(rows) == 1 and rows[0]["kind"] == "up"


def test_record_rejects_unknown_kind_and_item(tmpdb):
    it = mk()
    persist([it])
    assert prefs.record(it.url, "love")["ok"] is False
    assert prefs.record("https://never-seen.example/x", "up")["ok"] is False


def test_same_day_change_of_mind_overwrites(tmpdb):
    it = mk()
    persist([it])
    prefs.record(it.url, "up")
    prefs.record(it.url, "down")
    rows = store.feedback_rows()
    assert len(rows) == 1 and rows[0]["kind"] == "down"


def test_min_evidence_guard(tmpdb):
    """只点了一次的词不参与加权。"""
    it = mk()
    persist([it])
    prefs.record(it.url, "up")
    assert prefs.weights() == {}


def test_weights_grow_with_evidence(tmpdb):
    items = [mk(url=f"https://a/{i}") for i in range(3)]
    persist(items)
    for it in items:
        prefs.record(it.url, "up")
    w = prefs.weights()
    assert w["cat:model_release"] == pytest.approx(1.0)
    assert w["tag:开源"] == pytest.approx(1.0)


def test_down_votes_cancel_out(tmpdb):
    items = [mk(url=f"https://a/{i}") for i in range(2)]
    persist(items)
    prefs.record(items[0].url, "up")
    prefs.record(items[1].url, "down")
    w = prefs.weights()
    # 1.0 + (-1.2) = -0.2，除以 2 次证据 → -0.1
    assert w["cat:model_release"] == pytest.approx(-0.1)


def test_boost_is_bounded_and_explained():
    it = mk()
    factor, hits = prefs.boost(it, {"cat:model_release": 1.0})
    assert factor == pytest.approx(1.08)
    assert hits == ["cat:model_release"]


def test_boost_returns_one_without_evidence():
    factor, hits = prefs.boost(mk(), {})
    assert (factor, hits) == (1.0, [])


def test_apply_scales_score_and_records_reason():
    it = mk()
    stats = prefs.apply([it], {"cat:model_release": 1.0, "tag:开源": 1.0})
    assert stats["boosted"] == 1
    assert it.extra["score"] == pytest.approx(64.8)  # 60 * 1.08
    assert it.extra["pref"]["factor"] == pytest.approx(1.08)
    assert "cat:model_release" in it.extra["pref"]["terms"]


def test_negative_preference_lowers_rank():
    liked = mk(url="https://a/1")
    disliked = mk(url="https://a/2", category="deal")
    prefs.apply([liked, disliked], {"cat:model_release": 1.0, "cat:deal": -1.0})
    assert liked.extra["score"] > disliked.extra["score"]


def test_apply_is_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(prefs, "config", lambda: {"enabled": False})
    it = mk()
    assert prefs.apply([it])["boosted"] == 0
    assert it.extra["score"] == 60.0
    assert "pref" not in it.extra


def test_disabled_weights_are_empty(monkeypatch):
    monkeypatch.setattr(prefs, "config", lambda: {"enabled": False})
    assert prefs.weights() == {}
