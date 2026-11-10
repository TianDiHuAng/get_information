"""后台：口令校验、内容诊断筛选、各标签页能渲染。

后台是只读的，所以测试重点不是"能不能写坏数据"，而是：
1. **口令比较要正确且不泄露信息**（错口令一律回登录页，不给差异提示）；
2. 各标签页在空库和满库下都不炸；
3. 内容诊断的筛选口径（过门槛 / 预筛拦截 / 评分失败）不能互相串。
"""

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


def test_build_writes_static_copy(tmpdb, tmp_path):
    out = admin.build(tmp_path)
    from pathlib import Path

    path = Path(out["file"])
    assert path.exists() and path.name == "admin.html"
    assert "只读诊断视图" in path.read_text(encoding="utf-8")
