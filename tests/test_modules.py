"""模块系统：框架只读清单，不导入模块本身。

这一条是架构约束，不是功能：`collector/site.py` 里不该出现任何具体模块的名字。
所以除了功能测试，还有一条"框架不依赖模块"的检查。
"""

import textwrap

import pytest

from collector import modules


@pytest.fixture(autouse=True)
def temp_modules(tmp_path, monkeypatch):
    root = tmp_path / "modules"
    root.mkdir()
    manifest = tmp_path / "site_modules.yaml"
    monkeypatch.setattr(modules, "MODULES_DIR", root)
    monkeypatch.setattr(modules, "MANIFEST", manifest)
    yield root, manifest


def write_module(root, name, body):
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "module.py").write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return folder


def test_empty_manifest_means_no_modules(temp_modules):
    assert modules.manifest() == []
    assert modules.all_modules() == []


def test_manifest_reads_names_in_order(temp_modules):
    _, manifest = temp_modules
    manifest.write_text("modules:\n  - name: b\n  - name: a\n", encoding="utf-8")
    assert modules.manifest() == ["b", "a"]


def test_load_reads_module_file(temp_modules):
    root, _ = temp_modules
    write_module(root, "demo", """
        NAME = "demo"
        TITLE = "演示"
        HREF = "/demo.html"
    """)
    mod = modules.load("demo")
    assert mod and mod.TITLE == "演示"


def test_missing_module_returns_none(temp_modules):
    assert modules.load("nope") is None


def test_broken_module_does_not_crash(temp_modules):
    root, _ = temp_modules
    write_module(root, "broken", "raise RuntimeError('模块写坏了')\n")
    assert modules.load("broken") is None       # 静默失败，不拖垮整站


def test_nav_entries_group_by_section(temp_modules):
    root, manifest = temp_modules
    write_module(root, "lb", """
        NAME = "lb"
        TITLE = "榜单"
        HREF = "/lb.html"
        SECTION = "模型"
        ICON = "chart"
    """)
    manifest.write_text("modules:\n  - name: lb\n", encoding="utf-8")
    entries = modules.nav_entries()
    assert entries == [("模型", (("/lb.html", "榜单", "chart"),))]


def test_build_all_collects_results_and_isolates_failures(temp_modules):
    root, manifest = temp_modules
    write_module(root, "ok", """
        NAME = "ok"

        def build(root, payload, day):
            return {"built": True}
    """)
    write_module(root, "bad", """
        NAME = "bad"

        def build(root, payload, day):
            raise ValueError("boom")
    """)
    manifest.write_text("modules:\n  - name: ok\n  - name: bad\n", encoding="utf-8")
    out = modules.build_all(root, {}, "2026-11-10")
    assert out["ok"] == {"built": True}
    assert "error" in out["bad"]


def test_framework_does_not_name_any_module():
    """架构约束：引擎代码里不能写死某个模块的名字。"""
    from pathlib import Path

    site_src = (Path(__file__).resolve().parents[1] / "collector" / "site.py").read_text(
        encoding="utf-8")
    assert "leaderboard" not in site_src.lower()
    assert "free-tokens" not in site_src.lower()
