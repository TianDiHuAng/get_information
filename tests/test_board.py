"""看板与舆论场：算得对、不因为脏数据崩。

看板最容易骗人的地方是"图很好看但口径错了"，所以这里重点测三件事：
1. 直方图分档边界（100 分要落在最后一档，不能越界）；
2. 舆论场用**主体/标签**去重，而不是文章数 —— 十家中文号转同一件事只算一个主体；
3. 缺字段（没有 structure、没有 attention）时不能抛异常。
"""

import pytest

from collector import board


def mk(url="https://a/1", region="overseas", layer="primary", title="标题",
       subjects=("Anthropic",), tags=("开源",), category="model_release",
       att_score=None) -> dict:
    extra = {"score": 60}
    if category or subjects or tags:
        extra["structure"] = {"category": category, "tags": list(tags),
                              "subjects": list(subjects)}
    if att_score is not None:
        extra["attention"] = {"available": True, "score": att_score}
    return {"source": "thebatch", "title": title, "url": url, "layer": layer,
            "region": region, "summary": "", "published": "", "extra": extra}


def test_histogram_boundaries():
    hist = board.histogram([0, 19.9, 20, 99.9, 100])
    assert hist[0]["n"] == 2      # 0 与 19.9
    assert hist[1]["n"] == 1      # 20
    assert hist[4]["n"] == 2      # 99.9 与 100（100 不能落进第 6 档）


def test_histogram_ignores_none_and_garbage():
    hist = board.histogram([None, "x", 50])
    assert sum(b["n"] for b in hist) == 1


def test_discourse_splits_official_and_domestic():
    items = [
        mk(region="overseas", layer="primary", subjects=("Anthropic",)),
        mk(region="domestic", layer="social", subjects=("Anthropic",), url="https://b/1"),
        mk(region="domestic", layer="social", subjects=("字节",), url="https://b/2"),
    ]
    d = board.discourse(items)
    assert d["official_items"] == 1 and d["domestic_items"] == 2
    assert "anthropic" in d["both"]
    assert any("字节" in k for k in d["domestic_only"])


def test_discourse_ignores_media_and_rank():
    """国内媒体、国外榜单都不算"官方发布"或"国内讨论"。"""
    items = [mk(region="domestic", layer="rank", url="https://c/1"),
             mk(region="overseas", layer="rank", url="https://c/2")]
    d = board.discourse(items)
    assert d["official_items"] == 0 and d["domestic_items"] == 0


def test_discourse_counts_subjects_not_articles():
    """十家中文号转同一件事，只算一个主体。"""
    items = [mk(region="domestic", layer="social", subjects=("字节",), url=f"https://d/{i}")
             for i in range(10)]
    d = board.discourse(items)
    assert d["domestic_items"] == 10
    assert len([k for k in d["domestic_only"] if "字节" in k]) == 1


def test_compute_survives_items_without_structure(tmpdb):
    data = board.compute({"items": [{"title": "t", "url": "u", "extra": {}}],
                          "stats": {}})
    assert data["items"] == 1
    assert data["categories"] == {"未结构化": 1}
    assert data["attention"]["scored"] == 0


def test_compute_collects_category_counts(tmpdb):
    items = [mk(url="https://e/1", category="model_release"),
             mk(url="https://e/2", category="model_release"),
             mk(url="https://e/3", category="deal")]
    data = board.compute({"items": items, "stats": {}})
    assert data["categories"]["model_release"] == 2
    assert data["categories"]["deal"] == 1


def test_compute_exposes_llm_and_extract(tmpdb, monkeypatch):
    monkeypatch.setattr(board.llm, "stats", lambda day=None: {"total": 12, "hit": 3})
    data = board.compute({"items": [], "stats": {"extract": {"body": 5}}})
    assert data["llm"]["total"] == 12
    assert data["extract"]["body"] == 5


def test_render_is_self_contained_html():
    html = board.render(board.compute({"items": [mk()], "stats": {}}))
    assert html.startswith("<!doctype html>")
    assert "<style>" in html and "<script" not in html   # 不依赖外部资源
    assert "中文舆论场" in html


def test_build_writes_file(tmp_path):
    out = board.build({"items": [mk()], "stats": {}}, tmp_path)
    from pathlib import Path

    path = Path(out["file"])
    assert path.exists() and path.name == "board.html"
    assert path.read_text(encoding="utf-8").startswith("<!doctype html>")
