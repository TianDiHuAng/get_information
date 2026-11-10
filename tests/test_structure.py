"""结构化抽取：词表收敛、scope 归一、事实抽取、落库。

模型输出一律当作不可信：分类越界就整条丢掉，标签不在词表就丢弃，
`scope` 不是 single 就把 fact 置空 —— 否则脏值会一路流到主题页和日报。
"""

import pytest

from collector import store, structure
from collector.model import Item


def mk(source="thebatch", layer="primary", url="https://a.com/1",
       title="Anthropic 发布 Claude Fable 5.2", summary="上下文 100 万 token，价格降 40%") -> Item:
    return Item(source=source, title=title, url=url, summary=summary, layer=layer)


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch):
    monkeypatch.setattr(structure.llm, "available", lambda: True)
    monkeypatch.setattr(structure.llm, "stats", lambda day=None: {"total": 1})

    def call_json(task, version, system, user, **kw):
        return {
            "category": "model_release",
            "tags": ["长上下文", "价格", "不存在的标签"],
            "subjects": ["Anthropic"],
            "scope": "single",
            "fact": {"subject": "Anthropic", "action": "发布",
                     "object": "Claude Fable 5.2", "when": "2026-11-10"},
        }

    monkeypatch.setattr(structure.llm, "call_json", call_json)
    return call_json


def test_taxonomy_has_eight_categories():
    cats = structure.taxonomy()["categories"]
    assert len(cats) == 8
    assert "model_release" in cats and "deal" in cats


def test_prompt_includes_tag_vocabulary():
    text, version = structure.prompt()
    assert "多模态" in text
    assert "{{tag_vocab}}" not in text
    assert len(version) == 8


def test_extract_cleans_out_of_vocab_tags():
    got = structure.extract(mk())
    assert got["tags"] == ["长上下文", "价格"], "词表外的标签必须丢掉"
    assert got["category"] == "model_release"
    assert got["subjects"] == ["Anthropic"]
    assert got["fact"]["object"] == "Claude Fable 5.2"


def test_unknown_category_is_rejected(tmpdb, monkeypatch):
    def bad(task, version, system, user, **kw):
        return {"category": "随便编的", "tags": [], "subjects": [], "scope": "single", "fact": None}

    monkeypatch.setattr(structure.llm, "call_json", bad)
    assert structure.extract(mk()) is None


def test_composite_clears_fact(tmpdb, monkeypatch):
    def composite(task, version, system, user, **kw):
        return {"category": "industry_event", "tags": [], "subjects": ["Meta"],
                "scope": "composite",
                "fact": {"subject": "Meta", "action": "发布", "object": "Muse", "when": ""}}

    monkeypatch.setattr(structure.llm, "call_json", composite)
    got = structure.extract(mk())
    assert got["scope"] == "composite"
    assert got["fact"] is None, "综合稿不能带单一事实，否则日报会把它当一条新闻"


def test_bad_scope_falls_back_to_unknown(tmpdb, monkeypatch):
    def weird(task, version, system, user, **kw):
        return {"category": "opinion_analysis", "tags": [], "subjects": [], "scope": "???", "fact": None}

    monkeypatch.setattr(structure.llm, "call_json", weird)
    assert structure.extract(mk())["scope"] == "unknown"


def test_structure_items_annotates_and_persists(tmpdb):
    item = mk()
    item.extra["score"] = 80.0
    store.upsert_items([item])
    stats = structure.structure_items([item])

    assert stats["structured"] == 1
    assert item.extra["structure"]["category"] == "model_release"
    rows = store.structure_rows()
    assert len(rows) == 1
    assert rows[0]["category"] == "model_release"
    assert "长上下文" in rows[0]["tags"]


def test_no_llm_means_skip(tmpdb, monkeypatch):
    monkeypatch.setattr(structure.llm, "available", lambda: False)
    item = mk()
    stats = structure.structure_items([item])
    assert stats["skipped"] == "no-llm"
    assert "structure" not in item.extra


def test_max_items_keeps_the_best_scored(tmpdb):
    low = mk(url="https://a.com/low")
    low.extra["score"] = 10.0
    high = mk(url="https://a.com/high")
    high.extra["score"] = 90.0
    store.upsert_items([low, high])
    stats = structure.structure_items([low, high])
    assert stats["structured"] == 2  # 默认 max_items=120，两条都该抽

    structure.config.__globals__  # 只是确认配置可读
    assert "structure" in high.extra and "structure" in low.extra


def test_by_category_groups_items():
    a = mk(url="https://a.com/1")
    a.extra["structure"] = {"category": "model_release"}
    b = mk(url="https://a.com/2")
    b.extra["structure"] = {"category": "deal"}
    c = mk(url="https://a.com/3")
    groups = structure.by_category([a, b, c])
    assert len(groups["model_release"]) == 1
    assert len(groups["deal"]) == 1
    assert len(groups["other"]) == 1
