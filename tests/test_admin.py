"""后台：口令校验、内容诊断筛选、各标签页能渲染。

后台是只读的，所以测试重点不是"能不能写坏数据"，而是：
1. **口令比较要正确且不泄露信息**（错口令一律回登录页，不给差异提示）；
2. 各标签页在空库和满库下都不炸；
3. 内容诊断的筛选口径（过门槛 / 预筛拦截 / 评分失败）不能互相串。
"""

import json

import pytest

from collector import admin, store
from collector.model import Item


@pytest.fixture(autouse=True)
def token_file(tmp_path, monkeypatch):
    path = tmp_path / "admin_token.txt"
    monkeypatch.setattr(admin, "TOKEN_PATH", path)
    monkeypatch.setattr(admin, "DATA", tmp_path / "data")
    return path


def seed():
    good = Item(source="anthropic", title="Anthropic 发布 Claude Fable 5.2", url="https://a/1",
                layer="primary", summary="官方公告", published="2026-11-10T08:00:00+08:00")
    good.extra["score"] = 80
    good.extra["attention"] = {"available": True, "score": 82, "threshold": 58,
                               "selected": True, "itype": "model_release", "reason": "正式发布"}
    bad = Item(source="hackernews", title="某条被预筛拦下的内容", url="https://a/2", layer="rank")
    bad.extra["score"] = 30
    bad.extra["attention"] = {"available": False, "label": "BLOCK"}
    failed = Item(source="x", title="某条评分失败的条目", url="https://a/3", layer="social")
    failed.extra["score"] = 40
    for it in (good, bad, failed):
        it.extra["structure"] = {"category": "model_release", "tags": [], "subjects": []}
    store.upsert_items([good, bad, failed])


def test_token_is_created_once(token_file):
    first = admin.token()
    assert first and token_file.exists()
    assert admin.token() == first          # 第二次读到同一个


def test_check_accepts_only_exact_token(token_file):
    value = admin.token()
    assert admin.check(value) is True
    assert admin.check(value + "x") is False
    assert admin.check(value[:-1]) is False
    assert admin.check("") is False
    assert admin.check(None) is False


def test_runs_section_empty_is_readable(tmpdb):
    doc = admin.render(tab="runs")
    assert "今天还没有运行记录" in doc
    assert "后台" in doc


def test_content_filter_selected(tmpdb):
    seed()
    rows = admin.content(only="selected")
    assert [r["title"] for r in rows] == ["Anthropic 发布 Claude Fable 5.2"]
    assert rows[0]["score"] == 82 and rows[0]["threshold"] == 58


def test_content_filter_blocked(tmpdb):
    seed()
    rows = admin.content(only="blocked")
    assert [r["title"] for r in rows] == ["某条被预筛拦下的内容"]


def test_content_filter_failed(tmpdb):
    seed()
    rows = admin.content(only="failed")
    assert [r["title"] for r in rows] == ["某条评分失败的条目"]


def test_content_all_returns_everything(tmpdb):
    seed()
    assert len(admin.content(only="all")) == 3


def test_content_tabs_mark_current(tmpdb):
    seed()
    doc = admin.render(tab="content", only="blocked")
    assert 'class="on">预筛拦截</a>' in doc
    assert "某条被预筛拦下的内容" in doc


def test_config_snapshot_reads_scoring_thresholds():
    snap = admin.config_snapshot()
    assert snap["thresholds"]                       # 有门槛
    assert snap["score_calls"] in (1, 2, 3)
    assert "model" in snap


def test_evaluations_summarise_reports(tmp_path, monkeypatch):
    folder = tmp_path / "data" / "eval"
    folder.mkdir(parents=True)
    (folder / "selection-20261110.json").write_text(
        '{"model":"m","report":{"total":8,"valid":8,"coverage":1.0,"accuracy":0.625,'
        '"complete_accuracy":0.625,"f1":0.5},"sweep":[1,2]}', encoding="utf-8")
    rows = admin.evaluations()
    assert rows and rows[0]["kind"] == "selection"
    assert rows[0]["accuracy"] == pytest.approx(0.625)


def test_evaluations_empty_when_no_reports():
    assert admin.evaluations() == []


def test_render_all_tabs_do_not_crash(tmpdb):
    seed()
    for tab in ("runs", "sources", "content", "evals", "llm", "config", "alerts"):
        doc = admin.render(tab=tab)
        assert doc.startswith("<!doctype html>")
        assert "后台" in doc


def _write_report(tmp_path, name="selection-20261110.json") -> str:
    folder = tmp_path / "data" / "eval"
    folder.mkdir(parents=True, exist_ok=True)
    report = {
        "meta": {"split": "development", "n": 3},
        "models": {
            "m-a": {
                "summary": {"valid": 3, "labelled": 3, "accuracy": 0.667, "coverage": 1.0,
                            "complete_accuracy": 0.667, "f1": 0.8},
                "perStratum": {"release": {"accuracy": 1.0, "valid": 1},
                               "noise": {"accuracy": 0.5, "valid": 2}},
                "cases": [
                    {"case_id": "c1", "gold": True, "predicted": True, "avg": 80, "stratum": "release"},
                    {"case_id": "c2", "gold": False, "predicted": True, "avg": 62, "stratum": "noise"},
                    {"case_id": "c3", "gold": False, "predicted": False, "avg": 30, "stratum": "noise"},
                ],
            },
            "m-b": {
                "summary": {"valid": 3, "labelled": 3, "accuracy": 1.0, "coverage": 1.0,
                            "complete_accuracy": 1.0, "f1": 1.0},
                "perStratum": {"release": {"accuracy": 1.0, "valid": 1},
                               "noise": {"accuracy": 1.0, "valid": 2}},
                "cases": [
                    {"case_id": "c1", "gold": True, "predicted": True, "avg": 85, "stratum": "release"},
                    {"case_id": "c2", "gold": False, "predicted": False, "avg": 40, "stratum": "noise"},
                    {"case_id": "c3", "gold": False, "predicted": False, "avg": 35, "stratum": "noise"},
                ],
            },
        },
    }
    (folder / name).write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return name


@pytest.fixture
def eval_report(tmp_path, monkeypatch):
    monkeypatch.setattr(admin, "DATA", tmp_path / "data")
    return _write_report(tmp_path)


def test_eval_tab_lists_reports(eval_report):
    doc = admin.render(tab="evals")
    assert "selection-20261110.json" in doc
    assert "最好的模型" in doc


def test_eval_report_shows_models_and_cases(eval_report):
    doc = admin.render(tab="evals", report=eval_report)
    assert "m-a" in doc and "m-b" in doc
    assert "各模型" in doc and "按分层看准确率" in doc
    assert 'data-case="c1"' in doc and 'data-case="c2"' in doc


def test_eval_report_filters_wrong_cases(eval_report):
    wrong = admin.render(tab="evals", report=eval_report, outcome="wrong")
    assert 'data-case="c2"' in wrong      # m-a 把 c2 判错了
    right_only = admin.render(tab="evals", report=eval_report, outcome="right", stratum="noise")
    assert 'data-case="c3"' in right_only and 'data-case="c1"' not in right_only


def test_eval_report_disagree_filter(eval_report):
    doc = admin.render(tab="evals", report=eval_report, disagree=True)
    assert 'data-case="c2"' in doc        # 两个模型判断不同
    assert "只看分歧" in doc


def test_load_report_rejects_path_traversal(eval_report):
    assert admin.load_report("../secret.json") is None
    assert admin.load_report("sub/secret.json") is None
    assert admin.load_report("nope.json") is None
    assert admin.load_report("selection-20261110.json") is not None


def test_toggle_source_persists(tmpdb):
    store.save_source_health({"arxiv": {"fails": 0, "last_count": 12}})
    assert "arxiv" not in store.disabled_sources()

    result = admin.toggle_source("arxiv", False)
    assert result["ok"] is True
    assert "arxiv" in store.disabled_sources()
    # 健康记录不能被开关操作清掉
    row = [r for r in store.source_rows() if r["source"] == "arxiv"][0]
    assert row["last_count"] == 12 and row["enabled"] == 0

    admin.toggle_source("arxiv", True)
    assert "arxiv" not in store.disabled_sources()


def test_toggle_rejects_empty_source(tmpdb):
    assert admin.toggle_source("", True)["ok"] is False


def test_preview_runs_the_fetcher_without_saving(tmpdb, monkeypatch):
    from collector.model import Item

    item = Item(source="arxiv", title="一篇预览论文", url="https://arxiv.org/abs/1",
                published="2026-11-10T00:00:00+08:00")
    monkeypatch.setattr("collector.sources.build_fetchers",
                        lambda: [("arxiv", lambda: [item])])
    out = admin.preview_source("arxiv")
    assert out["ok"] and out["count"] == 1
    assert out["items"][0]["title"] == "一篇预览论文"
    # 不入库
    assert store.summary()["items"] == 0


def test_preview_handles_timeout(monkeypatch):
    import time

    monkeypatch.setattr("collector.sources.build_fetchers",
                        lambda: [("slow", lambda: time.sleep(3) or [])])
    out = admin.preview_source("slow", timeout=0.2)
    assert out["ok"] is False and "超时" in out["error"]


def test_preview_unknown_source(tmpdb, monkeypatch):
    monkeypatch.setattr("collector.sources.build_fetchers", lambda: [])
    out = admin.preview_source("nope")
    assert out["ok"] is False and "没有这个源" in out["error"]


def test_sources_tab_has_toggle_and_preview_buttons(tmpdb):
    store.save_source_health({"arxiv": {"fails": 0, "last_count": 12}})
    doc = admin.render(tab="sources")
    assert 'data-toggle="arxiv"' in doc
    assert 'data-preview="arxiv"' in doc
    assert "/api/source/toggle" in doc


def test_build_writes_static_copy(tmpdb, tmp_path):
    out = admin.build(tmp_path)
    from pathlib import Path

    path = Path(out["file"])
    assert path.exists() and path.name == "admin.html"
    assert "只读诊断视图" in path.read_text(encoding="utf-8")
