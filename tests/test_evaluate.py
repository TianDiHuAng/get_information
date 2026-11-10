"""评测指标：算得对，且不会让"少答"的模型刷分。

最关键的一条：**准确率 100% 但覆盖率 10% 的模型不该看起来很好**。
所以准确率与完整准确率必须分开算，`either` 不进分母，失败要算错。
"""

import pytest

from collector import evaluate


def r(gold, predicted, avg=None, case="c"):
    return {"case_id": case, "gold": gold, "predicted": predicted, "avg": avg}


def test_prf_basic():
    got = evaluate.prf(true_pos=6, false_pos=2, false_neg=2)
    assert got["precision"] == pytest.approx(0.75)
    assert got["recall"] == pytest.approx(0.75)
    assert got["f1"] == pytest.approx(0.75)


def test_prf_zero_denominators_do_not_crash():
    got = evaluate.prf(0, 0, 0)
    assert got == {"precision": 0.0, "recall": 0.0, "f1": 0.0}


def test_either_is_excluded_from_every_denominator():
    results = [r(True, True), r(False, False), r(None, True)]
    got = evaluate.summarize(results)
    assert got["total"] == 3 and got["either"] == 1 and got["labelled"] == 2
    assert got["accuracy"] == 1.0


def test_failures_hurt_complete_accuracy_not_accuracy():
    """只答 1 条且答对：准确率 100%，覆盖率 10%，完整准确率 10%。"""
    results = [r(True, True, avg=90)] + [r(True, None) for _ in range(9)]
    got = evaluate.summarize(results)
    assert got["accuracy"] == 1.0
    assert got["coverage"] == pytest.approx(0.1)
    assert got["complete_accuracy"] == pytest.approx(0.1)


def test_precision_recall_use_valid_predictions_only():
    results = [r(True, True), r(True, False), r(False, True), r(False, False), r(True, None)]
    got = evaluate.summarize(results)
    assert (got["tp"], got["fp"], got["fn"], got["tn"]) == (1, 1, 1, 1)
    assert got["precision"] == pytest.approx(0.5)
    assert got["recall"] == pytest.approx(0.5)


def test_select_rates_show_bias():
    results = [r(True, True), r(True, True), r(False, False)]
    got = evaluate.summarize(results)
    assert got["select_rate_gold"] == pytest.approx(2 / 3, abs=1e-4)
    assert got["select_rate_pred"] == pytest.approx(2 / 3, abs=1e-4)


def test_sweep_moves_predictions_with_the_threshold():
    results = [
        {"case_id": "a", "gold": True, "avg": 80, "predicted": True},
        {"case_id": "b", "gold": False, "avg": 70, "predicted": True},
    ]
    sweep = evaluate.sweep(results, lo=60, hi=90, step=10)
    by = {row["threshold"]: row for row in sweep}
    assert by[60]["selected"] == 2
    assert by[80]["selected"] == 1          # 只留 80 分那条
    assert by[80]["accuracy"] == 1.0        # 剩下的正是金标"选"
    assert by[90]["selected"] == 0


def test_sweep_skips_rows_without_scores():
    results = [{"case_id": "a", "gold": True, "avg": None, "predicted": None}]
    assert evaluate.sweep(results) == []


def test_best_threshold_prefers_higher_on_tie():
    sweep = [{"threshold": 60, "f1": 0.8}, {"threshold": 70, "f1": 0.8}]
    assert evaluate.best_threshold(sweep)["threshold"] == 60  # 同分取更严的那档


def test_diff_report_shows_delta():
    before = {"accuracy": 0.7, "f1": 0.6}
    after = {"accuracy": 0.75, "f1": 0.55}
    diff = evaluate.diff_report(before, after)
    assert diff["accuracy"]["delta"] == pytest.approx(0.05)
    assert diff["f1"]["delta"] == pytest.approx(-0.05)


def test_sample_prefers_scores_near_threshold():
    items = [{"url": f"u{i}", "extra": {"score": s}}
             for i, s in enumerate([5, 20, 45, 55, 65, 75, 85, 95])]
    picked = evaluate.sample_for_gold(items, n=4, band=(40, 90))
    assert all(40 <= i["extra"]["score"] <= 90 for i in picked)


def test_sample_returns_requested_count():
    items = [{"url": f"u{i}", "extra": {"score": 50 + i}} for i in range(30)]
    assert len(evaluate.sample_for_gold(items, n=10)) == 10


def test_sample_ignores_items_without_score():
    items = [{"url": "a", "extra": {}}, {"url": "b", "extra": {"score": 60}}]
    picked = evaluate.sample_for_gold(items, n=5)
    assert [i["url"] for i in picked] == ["b"]


def test_gold_line_shape_is_stable():
    line = evaluate.gold_line("case-001", {"title": "t", "url": "u", "source": "s",
                                           "extra": {"score": 66}})
    assert line["caseId"] == "case-001"
    assert line["gold"]["decision"] == ""
    assert line["item"]["title"] == "t"
    assert line["model_hint"]["score"] == 66
