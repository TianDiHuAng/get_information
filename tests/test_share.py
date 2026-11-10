"""分享图与转发预览。

两件事值得守住：
1. **没有中文字体就不画图** —— 画一堆方块比没有图更糟；
2. 折行按像素宽度算，中文没有空格，`textwrap` 那套用不了。

图片本身用 Pillow 生成，测试只校验尺寸与文件存在（不比对像素）。
"""

import pytest

from collector import share


def test_wrap_breaks_by_pixel_width():
    font = share._font(28)
    if font is None:
        pytest.skip("本机没有中文字体")
    lines = share._wrap("信息雷达每天采集 AI 前沿信息并编排成一份日报", font, 240, 2)
    assert 1 <= len(lines) <= 2
    assert all(isinstance(l, str) and l for l in lines)


def test_wrap_empty_text():
    font = share._font(28)
    if font is None:
        pytest.skip("本机没有中文字体")
    assert share._wrap("", font, 200, 2) == []
    assert share._wrap(None, font, 200, 2) == []


def test_wrap_respects_max_lines():
    font = share._font(28)
    if font is None:
        pytest.skip("本机没有中文字体")
    lines = share._wrap("字" * 200, font, 200, 3)
    assert len(lines) == 3


def test_build_writes_a_1200x630_png(tmp_path):
    payload = {"items": [{"title": "头条新闻标题", "source": "hackernews",
                          "extra": {"score": 90}, "layer": "rank", "url": "https://a/1",
                          "summary": "摘要内容", "published": ""}],
               "stats": {"generated_at": "2026-11-10T09:00:00+08:00", "sources_ok": 7}}
    out = share.build(payload, tmp_path)
    if out.get("skipped"):
        pytest.skip(f"跳过出图：{out['skipped']}")
    from PIL import Image

    path = tmp_path / "og.png"
    assert path.exists()
    with Image.open(path) as img:
        assert img.size == (share.WIDTH, share.HEIGHT)


def test_build_skips_gracefully_without_font(tmp_path, monkeypatch):
    monkeypatch.setattr(share, "_font", lambda size, bold=False: None)
    out = share.build({"items": [], "stats": {}}, tmp_path)
    assert out == {"skipped": "no-cjk-font"}


def test_og_tags_include_image_and_twitter_card(monkeypatch):
    monkeypatch.setattr(share, "og_tags", share.og_tags)  # 保持真实实现
    tags = share.og_tags("标题", "描述", "/board.html")
    assert 'property="og:image"' in tags
    assert 'name="twitter:card"' in tags
    assert "summary_large_image" in tags
    assert "og.png" in tags


def test_og_tags_escape_quotes():
    tags = share.og_tags('标题"带引号', "描述")
    assert 'og:title" content="标题&quot;带引号"' in tags
