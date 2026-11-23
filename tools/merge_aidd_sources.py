"""把 baize-aidd 的 sources.json 转成 Get_Information 的 feeds.yaml 条目。

用法：python tools/merge_aidd_sources.py [--probe /tmp/aidd-probe.txt] [--sources <sources.json>]

- 只取 kind=rss 的源（web_list/json_list 本项目采集器不支持）
- 若有探针结果，过滤掉失败的源
- 输出可直接粘进 industry/aidd/feeds.yaml 的 YAML 行
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SOURCES_URL = "https://raw.githubusercontent.com/TianDiHuAng/baize-aidd/main/industry/sources.json"


def load_sources(path: str | None) -> list[dict]:
    if path:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    else:
        data = json.load(urllib.request.urlopen(SOURCES_URL, timeout=30))
    return [s for s in data["sources"] if s["kind"] == "rss"]


def parse_probe(path: str | None) -> set[str]:
    """从探针输出里提取失败的 URL（取 path 段做前缀匹配）。"""
    failed: set[str] = set()
    if not path:
        return failed
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("×") or line.startswith("✗"):
            # 形如 "×   www.nature.com/xxx   0 条 ... url: https://..."
            m = re.search(r"url:\s*(\S+)", line)
            if m:
                failed.add(m.group(1))
            else:
                # 退而求其次：取第二列 path
                parts = line.split()
                if len(parts) > 1:
                    failed.add(parts[1])
    return failed


def tier_to_layer(tier: str) -> str:
    return {"T1": "primary", "T1_5": "primary", "T2": "broad"}.get(tier or "", "broad")


def region_of(url: str) -> str:
    return "domestic" if any(c in url for c in ("cn/", ".cn", "zhihu", "weibo", "xtalpi", "drugtimes")) else "overseas"


def slug(source_id: str) -> str:
    """rss-nature-biotech → nature_biotech；去掉 rss- 前缀，连字符转下划线。"""
    s = re.sub(r"^rss-", "", source_id)
    return re.sub(r"[^a-z0-9]", "_", s.lower()).strip("_")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="")
    ap.add_argument("--probe", default="")
    args = ap.parse_args()

    sources = load_sources(args.sources or None)
    failed = parse_probe(args.probe or None)
    # 探针里的失败 URL 是截断 path，用 URL 的 host+path 前 20 字符匹配
    # 探针实测失败的源（403/404），用 URL 里的独特片段精确排除。
    # 不用解析探针文本——它的 url 列被截断到 20 字符，会产生假前缀。
    FAIL_MARKERS = (
        "broadinstitute.org",
        "fda.gov/about-fda",           # 3 个 FDA feed 全部 404
        "pharmaceutical-technology.com",
        "clinicaltrialsarena.com",
        "insitro.com",
        "medcitynews.com",
    )
    def is_failed(url: str) -> bool:
        return any(marker in url for marker in FAIL_MARKERS)

    print("# 来自 baize-aidd 的 AIDD 源（已按本项目探针过滤）")
    out = []
    for s in sources:
        url = s["config"]["feedUrl"]
        if is_failed(url):
            print(f"# SKIP (探针失败): {s['name']} {url}", file=sys.stderr)
            continue
        sid = slug(s["id"])
        layer = tier_to_layer(s.get("tier", ""))
        region = region_of(url)
        proxy = "true" if region == "overseas" else "false"
        # 从 tags 推断 limit：预印本/期刊给多点
        limit = 12
        tags = s.get("tags") or []
        if "期刊" in tags or "预印本" in tags:
            limit = 10
        name = s["name"].replace('"', "'")
        out.append(
            f'  - {{id: {sid}, name: "{name}", url: "{url}", '
            f'region: {region}, layer: {layer}, limit: {limit}, proxy: {proxy}}}'
        )
    print("\n".join(out))
    print(f"\n# 生成 {len(out)} 条可用源", file=sys.stderr)


if __name__ == "__main__":
    main()
