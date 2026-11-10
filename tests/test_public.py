"""站点根目录的固定文件：robots / manifest / openapi / security / sitemap。

这些文件最容易漏 —— 页面都能看了，但搜索引擎抓不到、PWA 装不上、
接口说不清。所以它们有测试，且占位符必须真的被替换掉。
"""

import json

from collector import export


def test_build_public_writes_all_files(tmp_path):
    written = export.build_public(tmp_path, "https://example.com", {"items": 12}, ["a", "b"])
    for name in ("robots.txt", "manifest.webmanifest", ".well-known/security.txt",
                 "openapi-v1.json", "sitemap.xml"):
        assert (tmp_path / name).exists(), name
        assert name in written


def test_robots_disallows_admin_and_points_sitemap(tmp_path):
    export.build_public(tmp_path, "https://example.com", {"items": 1}, [])
    text = (tmp_path / "robots.txt").read_text(encoding="utf-8")
    assert "Disallow: /admin" in text
    assert "Sitemap: https://example.com/sitemap.xml" in text
    assert "{{" not in text                  # 占位符必须都被替换


def test_manifest_is_valid_json_with_site_name(tmp_path):
    export.build_public(tmp_path, "https://example.com", {"items": 1}, [])
    data = json.loads((tmp_path / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert data["name"] and "{{" not in json.dumps(data, ensure_ascii=False)
    assert data["start_url"] == "/"


def test_openapi_describes_the_real_endpoints(tmp_path):
    export.build_public(tmp_path, "https://example.com", {"items": 1}, [])
    spec = json.loads((tmp_path / "openapi-v1.json").read_text(encoding="utf-8"))
    assert spec["openapi"].startswith("3.")
    assert "/api/v1/latest.json" in spec["paths"]
    assert "/api/feedback" in spec["paths"]
    assert spec["servers"][0]["url"] == "https://example.com"


def test_sitemap_lists_pages(tmp_path):
    export.build_public(tmp_path, "https://example.com", {"items": 1}, [])
    text = (tmp_path / "sitemap.xml").read_text(encoding="utf-8")
    assert text.startswith("<?xml")
    assert text.count("<url>") >= 10
    assert "https://example.com/all.html" in text


def test_public_files_use_industry_settings(tmp_path, monkeypatch):
    """换行业后 robots/manifest 里的站名要跟着变。"""
    from collector import industry

    monkeypatch.setattr(industry, "settings", lambda reload=False: {
        "name": "法律热点", "description": "法律人的每日必读", "tagline": "",
        "locale": "zh-CN", "edition": {"daily": "08:30"}, "pack": "",
    })
    export.build_public(tmp_path, "https://law.example", {"items": 1}, [])
    assert "# 法律热点" in (tmp_path / "robots.txt").read_text(encoding="utf-8")
    manifest = json.loads((tmp_path / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["name"] == "法律热点"
