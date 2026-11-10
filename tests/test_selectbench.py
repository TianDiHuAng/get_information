"""标注台：只写 data/gold.jsonl，且写出来的格式评测脚本必须能直接读。

这条最容易被忽略：标注页面自嗨了半天，`tools/eval_selection.py` 读不进去就等于没标。
所以这里有个集成测试，直接用评测脚本的 `load_cases` 读我们写出来的文件。
"""

import json

import pytest

from collector import selectbench, store
from collector.model import Item


@pytest.fixture(autouse=True)
def gold_file(tmp_path, monkeypatch, tmpdb):
    # 必须带上 tmpdb：否则 store 会写进真实数据库（踩过一次，误插了 3 条假条目）
    monkeypatch.setattr(selectbench, "DATA", tmp_path)
    return tmp_path / "gold.jsonl"


def seed(n=3):
    items = []
    for i in range(n):
        it = Item(source="anthropic", title=f"第 {i} 条新闻标题足够长", url=f"https://a/{i}",
                  layer="primary", summary="摘要内容", published="2026-11-10T08:00:00+08:00")
        it.extra["score"] = 70 + i
        it.extra["attention"] = {"available": True, "score": 80 + i, "threshold": 58,
                                 "itype": "model_release", "reason": "正式发布"}
        it.extra["structure"] = {"category": "model_release", "tags": [], "subjects": []}
        items.append(it)
    store.upsert_items(items)
    return [int(r["id"]) for r in store.all_items()]


def test_labelling_writes_a_row(gold_file):
    ids = seed()
    expected = store.item_detail(ids[0])["title"]
    out = selectbench.label(ids[0], "select")
    assert out["ok"] and out["labelled"] == 1
    rows = selectbench.load()
    assert rows[0]["gold"]["decision"] == "select"
    assert rows[0]["item"]["title"] == expected


def test_relabelling_updates_instead_of_duplicating(gold_file):
    ids = seed()
    selectbench.label(ids[0], "select")
    selectbench.label(ids[0], "reject")
    rows = selectbench.load()
    assert len(rows) == 1
    assert rows[0]["gold"]["decision"] == "reject"


def test_invalid_decision_is_refused(gold_file):
    ids = seed()
    assert selectbench.label(ids[0], "maybe")["ok"] is False
    assert selectbench.load() == []


def test_unknown_item_is_refused(gold_file):
    seed()
    assert selectbench.label(99999, "select")["ok"] is False


def test_clear_removes_the_row(gold_file):
    ids = seed()
    selectbench.label(ids[0], "select")
    assert selectbench.clear(ids[0])["ok"] is True
    assert selectbench.load() == []


def test_stats_counts_decisions(gold_file):
    ids = seed(3)
    selectbench.label(ids[0], "select")
    selectbench.label(ids[1], "reject")
    selectbench.label(ids[2], "either")
    st = selectbench.stats()
    assert st["select"] == 1 and st["reject"] == 1 and st["either"] == 1 and st["total"] == 3


def test_candidates_put_unlabelled_first(gold_file):
    ids = seed(3)
    selectbench.label(ids[0], "select")
    rows = selectbench.candidates()
    assert rows[0]["decision"] == ""          # 未标的排在前面
    assert any(r["decision"] == "select" for r in rows)


def test_case_id_is_stable(gold_file):
    ids = seed()
    first = selectbench.label(ids[0], "select")["caseId"]
    store.upsert_items([Item(source="anthropic", title="第 0 条新闻标题足够长（改过）",
                             url="https://a/0", layer="primary")])
    second = selectbench.label(ids[0], "reject")["caseId"]
    assert first == second


def test_bad_lines_are_skipped(gold_file, tmp_path):
    gold_file.write_text('{"caseId":"ok","gold":{"decision":"select"}}\n不是 JSON\n', encoding="utf-8")
    rows = selectbench.load()
    assert len(rows) == 1 and rows[0]["caseId"] == "ok"


def test_written_file_is_readable_by_the_eval_script(gold_file, tmp_path):
    """最重要的一条：标注页面写出来的文件，评测脚本要能直接读。"""
    import importlib.util
    from pathlib import Path

    ids = seed(2)
    selectbench.label(ids[0], "select")
    selectbench.label(ids[1], "reject")

    spec = importlib.util.spec_from_file_location(
        "eval_selection", Path(__file__).resolve().parents[1] / "tools" / "eval_selection.py")
    if spec is None or spec.loader is None:
        pytest.skip("找不到评测脚本")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    cases = module.load_cases(gold_file)
    assert len(cases) == 2
    assert {c["gold"] for c in cases} == {True, False}
    assert all(c["item"]["title"] for c in cases)


def test_admin_tab_renders_buttons(tmpdb, gold_file):
    from collector import admin

    ids = seed(2)
    selectbench.label(ids[0], "select")
    doc = admin.render(tab="better")
    assert 'data-label=' in doc and 'data-decision="reject"' in doc
    assert "/api/gold" in doc
    assert "已标" in doc
