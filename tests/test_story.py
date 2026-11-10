"""事件综述：只在够料时写，写出来必须句句有依据。

综述是最容易"编"的一步 —— 模型很擅长补背景、补动机、补影响。
所以测试的重心是**核对**：编出来的词必须被 grounding 抓到并重写；
重写还不合格就不入库，宁可没有综述。
"""

import pytest

from collector import story, store


def rows(n=2, title="Anthropic 发布 Claude Fable 5.2", summary="官方宣布两个模型开放，价格下调 40%。"):
    return [{"event_id": 7, "event_title": title, "source": f"s{i}",
             "published": "2026-11-10", "item_title": title,
             "item_summary": summary, "item_id": i + 1} for i in range(n)]


@pytest.fixture(autouse=True)
def prompt_file(tmp_path, monkeypatch):
    path = tmp_path / "story-digest.md"
    path.write_text("写一段综述，只写材料里的事实。", encoding="utf-8")
    monkeypatch.setattr(story, "PROMPT_PATH", path)
    yield path


def test_requires_at_least_two_reports(monkeypatch):
    called = []
    monkeypatch.setattr("collector.llm.call_text", lambda *a, **k: called.append(1))
    out = story.generate(7, rows(1))
    assert out["ok"] is False and out["reason"] == "reports<2"
    assert called == []                      # 单篇不花这次钱


def test_grounded_text_is_accepted(monkeypatch):
    text = "Anthropic 发布 Claude Fable 5.2，价格下调 40%。"
    monkeypatch.setattr("collector.llm.call_text", lambda *a, **k: text)
    out = story.generate(7, rows())
    assert out["ok"] is True and out["text"].startswith("Anthropic")


def test_ungrounded_text_is_rewritten_once(monkeypatch):
    calls = []

    def fake(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            return "OpenAI 发布了 GPT-9，估值 5000 亿美元。"   # 原文里没有
        return "Anthropic 发布 Claude Fable 5.2，价格下调 40%。"

    monkeypatch.setattr("collector.llm.call_text", fake)
    out = story.generate(7, rows())
    assert len(calls) == 2                   # 重写一次
    assert out["ok"] is True


def test_still_ungrounded_after_retry_is_rejected(monkeypatch):
    monkeypatch.setattr("collector.llm.call_text",
                        lambda *a, **k: "OpenAI 发布了 GPT-9，估值 5000 亿美元。")
    out = story.generate(7, rows())
    assert out["ok"] is False
    assert out["reason"].startswith("ungrounded")


def test_empty_model_output_is_rejected(monkeypatch):
    monkeypatch.setattr("collector.llm.call_text", lambda *a, **k: "")
    out = story.generate(7, rows())
    assert out["ok"] is False and out["reason"] == "empty"


def test_save_and_get_roundtrip():
    store.migrate()
    story.save(7, "2026-11-10", "一段综述", model="m", sources=2)
    row = story.get(7)
    assert row["text"] == "一段综述" and row["sources"] == 2


def test_save_overwrites_same_event():
    store.migrate()
    story.save(7, "2026-11-10", "旧", sources=2)
    story.save(7, "2026-11-10", "新", sources=3)
    assert story.get(7)["text"] == "新"


def test_run_writes_for_multi_report_events(monkeypatch, tmpdb):
    store.migrate()
    monkeypatch.setattr("collector.llm.call_text",
                        lambda *a, **k: "Anthropic 发布 Claude Fable 5.2，价格下调 40%。")
    monkeypatch.setattr(story.store, "event_dump", lambda days=3, day=None: rows(2))
    out = story.run("2026-11-10", limit=5)
    assert out["events"] == 1 and out["written"] == 1
    assert story.get(7) is not None


def test_run_skips_already_written_today(monkeypatch, tmpdb):
    store.migrate()
    story.save(7, "2026-11-10", "已经有的一段", sources=2)
    monkeypatch.setattr(story.store, "event_dump", lambda days=3, day=None: rows(2))
    called = []
    monkeypatch.setattr("collector.llm.call_text", lambda *a, **k: called.append(1))
    out = story.run("2026-11-10", limit=5)
    assert out["skipped"] == 1 and out["written"] == 0
    assert called == []


def test_prompt_version_changes_with_content(prompt_file):
    _, v1 = story.prompt()
    prompt_file.write_text("换了一套写法", encoding="utf-8")
    _, v2 = story.prompt()
    assert v1 != v2


def test_citations_are_numbered_in_material():
    material = story._material(rows(3))
    assert "[1]" in material and "[2]" in material and "[3]" in material


def test_source_name_counts_as_grounded(monkeypatch):
    """综述里写「Hacker News 上出现讨论帖」是事实，来源名必须算进语料。"""
    rows_ = [{"event_id": 9, "event_title": "某事件", "source": "hackernews",
              "published": "2026-11-10", "item_title": "某标题",
              "item_summary": "某摘要", "item_id": 1},
             {"event_id": 9, "event_title": "某事件", "source": "sspai",
              "published": "2026-11-10", "item_title": "另一标题",
              "item_summary": "另一摘要", "item_id": 2}]
    monkeypatch.setattr("collector.llm.call_text",
                        lambda *a, **k: "Hacker News 上出现了关于某事件的讨论。")
    out = story.generate(9, rows_)
    assert out["ok"] is True
