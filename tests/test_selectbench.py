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


def test_label_records_split_and_stratum(gold_file):
    ids = seed(2)
    selectbench.label(ids[0], "select", split="holdout")
    selectbench.label(ids[1], "reject", split="development")
    rows = selectbench.load()
    splits = {(r["samplingContext"]["benchmarkSplit"]) for r in rows}
    assert splits == {"holdout", "development"}
    # 分层默认取分类
    assert rows[0]["samplingContext"]["samplingStratum"] == "model_release"


def test_new_format_carries_source_facts(gold_file):
    ids = seed(1)
    selectbench.label(ids[0], "select")
    row = selectbench.load()[0]
    assert row["sourceFacts"]["sourceTier"] == "T1"       # primary
    assert row["sourceFacts"]["firstParty"] is True
    assert row["material"]["title"].startswith("第 0 条")


def test_stats_count_splits(gold_file):
    ids = seed(2)
    selectbench.label(ids[0], "select", split="holdout")
    selectbench.label(ids[1], "reject", split="development")
    st = selectbench.stats()
    assert st["split_holdout"] == 1 and st["split_development"] == 1


def test_eval_reads_new_format_with_split(gold_file):
    """评测脚本要能读 material/sourceFacts/samplingContext，并按 split 过滤。"""
    import importlib.util
    from pathlib import Path

    ids = seed(2)
    selectbench.label(ids[0], "select", split="holdout")
    selectbench.label(ids[1], "reject", split="development")

    spec = importlib.util.spec_from_file_location(
        "eval_selection", Path(__file__).resolve().parents[1] / "tools" / "eval_selection.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    cases = module.load_cases(gold_file)
    assert len(cases) == 2
    assert {c["split"] for c in cases} == {"holdout", "development"}
    assert all(c["item"]["title"] for c in cases)
    dev = [c for c in cases if c["split"] == "development"]
    assert len(dev) == 1 and dev[0]["gold"] is False


def test_per_stratum_grouping(tmp_path):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "eval_selection", Path(__file__).resolve().parents[1] / "tools" / "eval_selection.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    results = [
        {"case_id": "a", "gold": True, "predicted": True, "stratum": "release"},
        {"case_id": "b", "gold": False, "predicted": True, "stratum": "release"},
        {"case_id": "c", "gold": False, "predicted": False, "stratum": "noise"},
    ]
    groups = module.per_stratum(results)
    assert groups["release"]["valid"] == 2
    assert groups["release"]["accuracy"] == pytest.approx(0.5)
    assert groups["noise"]["accuracy"] == pytest.approx(1.0)


def test_tier_decides_the_threshold(gold_file):
    """金标带 sourceTier=T1 时必须用一手门槛（58），而不是默认 68。"""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "eval_selection", Path(__file__).resolve().parents[1] / "tools" / "eval_selection.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    raw = {"title": "某条官方发布", "url": "https://a/1", "summary": "", "body": ""}
    as_t1 = module.to_item(raw, tier="T1")
    as_t2 = module.to_item(raw, tier="T2")
    assert as_t1.layer == "primary" and as_t2.layer == "broad"

    from collector import rating

    conf = rating.config()
    assert rating.threshold_for(as_t1, conf) == conf["thresholds"]["primary"]
    assert rating.threshold_for(as_t2, conf) == conf["thresholds"]["broad"]


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


def test_stratified_sample_covers_every_stratum():
    """每个分类都要有样本 —— 只按分数挑会让发布类占满。"""
    items = []
    for i, (cat, score) in enumerate([("model_release", 80), ("research_paper", 50),
                                      ("tutorial_explainer", 30), ("deal", 60)]):
        items.append({"title": f"t{i}", "structure": {"category": cat},
                      "extra": {"score": score}, "attention": {}})
    picked = selectbench.stratified_sample(items, per_stratum=1)
    cats = {p["structure"]["category"] for p in picked}
    assert cats == {"model_release", "research_paper", "tutorial_explainer", "deal"}


def test_stratified_sample_respects_cap_and_prefers_band():
    items = [{"title": f"n{i}", "structure": {"category": "noise"},
              "extra": {"score": 95 if i == 0 else 50 + i}, "attention": {}} for i in range(6)]
    picked = selectbench.stratified_sample(items, per_stratum=2, band=(40, 90))
    assert len(picked) == 2
    # 层内优先门槛附近的（50、51），而不是 95 那条离得很远的
    assert all(40 <= p["extra"]["score"] <= 90 for p in picked)


def test_stratified_sample_skips_items_without_scores():
    items = [{"title": "a", "structure": {"category": "x"}, "extra": {}, "attention": {}}]
    assert selectbench.stratified_sample(items) == []
