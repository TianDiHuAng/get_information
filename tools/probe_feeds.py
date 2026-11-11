"""探针：一次测一批 RSS，只报告能用的。

扩源不能靠"我觉得这个站有 RSS" —— 一半会 404、一半会返回空 feed、
还有的返回 HTML 错误页。所以先测，再决定写不写进配置。

用法：
    python tools/probe_feeds.py                 # 测内置候选清单
    python tools/probe_feeds.py --file x.txt    # 一行一个 url
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector import sources  # noqa: E402

# (id, 名称, url, region, layer)
CANDIDATES = [
    # —— 官方 / 实验室 ——
    ("openai_news", "OpenAI News", "https://openai.com/news/rss.xml", "overseas", "primary"),
    ("meta_ai", "Meta AI", "https://ai.meta.com/blog/rss/", "overseas", "primary"),
    ("hf_blog", "Hugging Face 博客", "https://huggingface.co/blog/feed.xml", "overseas", "primary"),
    ("nvidia_blog", "NVIDIA 博客", "https://blogs.nvidia.com/feed/", "overseas", "primary"),
    ("aws_ml", "AWS 机器学习", "https://aws.amazon.com/blogs/machine-learning/feed/", "overseas", "primary"),
    ("apple_ml", "Apple 机器学习", "https://machinelearning.apple.com/rss.xml", "overseas", "primary"),
    ("cohere_blog", "Cohere", "https://cohere.com/blog/rss.xml", "overseas", "primary"),
    ("databricks", "Databricks", "https://www.databricks.com/blog/feed", "overseas", "primary"),
    ("bair", "Berkeley BAIR", "https://bair.berkeley.edu/blog/feed.xml", "overseas", "primary"),
    ("mit_ai", "MIT News AI", "https://news.mit.edu/rss/topic/artificial-intelligence2", "overseas", "primary"),
    ("stanford_hai", "Stanford HAI", "https://hai.stanford.edu/news/rss.xml", "overseas", "primary"),
    # —— 媒体 ——
    ("techcrunch_ai", "TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", "overseas", "broad"),
    ("verge_ai", "The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "overseas", "broad"),
    ("venturebeat_ai", "VentureBeat AI", "https://venturebeat.com/category/ai/feed/", "overseas", "broad"),
    ("mit_tr", "MIT Technology Review", "https://www.technologyreview.com/feed/", "overseas", "broad"),
    ("wired_ai", "Wired AI", "https://www.wired.com/feed/tag/ai/latest/rss", "overseas", "broad"),
    ("engadget", "Engadget", "https://www.engadget.com/rss.xml", "overseas", "broad"),
    ("ainews", "AI News", "https://www.artificialintelligence-news.com/feed/", "overseas", "broad"),
    ("decoder", "The Decoder", "https://the-decoder.com/feed/", "overseas", "broad"),
    ("marktechpost", "MarkTechPost", "https://www.marktechpost.com/feed/", "overseas", "broad"),
    ("siliconangle", "SiliconANGLE", "https://siliconangle.com/feed/", "overseas", "broad"),
    ("importai", "Import AI", "https://importai.substack.com/feed", "overseas", "broad"),
    ("thebatch_feed", "The Batch", "https://www.deeplearning.ai/the-batch/feed/", "overseas", "broad"),
    ("bensbites", "Ben's Bites", "https://bensbites.beehiiv.com/feed", "overseas", "broad"),
    ("tldr_ai", "TLDR AI", "https://tldr.tech/api/rss/ai", "overseas", "broad"),
    # —— 研究者 ——
    ("jalammar", "Jay Alammar", "https://jalammar.github.io/feed.xml", "overseas", "primary"),
    ("eugeneyan", "Eugene Yan", "https://eugeneyan.com/rss/", "overseas", "primary"),
    ("huyenchip", "Chip Huyen", "https://huyenchip.com/feed.xml", "overseas", "primary"),
    ("fastai", "fast.ai", "https://www.fast.ai/feed.xml", "overseas", "primary"),
    ("ruder", "Sebastian Ruder", "https://www.ruder.io/rss/", "overseas", "primary"),
    # —— 国内 ——
    ("jiqizhixin", "机器之心", "https://www.jiqizhixin.com/rss", "domestic", "broad"),
    ("qbitai", "量子位", "https://www.qbitai.com/feed", "domestic", "broad"),
    ("infoq_cn", "InfoQ 中文", "https://www.infoq.cn/feed", "domestic", "broad"),
    ("huxiu", "虎嗅", "https://www.huxiu.com/rss/0.xml", "domestic", "broad"),
    ("tmtpost", "钛媒体", "https://www.tmtpost.com/rss.xml", "domestic", "broad"),
    ("geekpark", "极客公园", "https://www.geekpark.net/rss", "domestic", "broad"),
    ("oschina", "开源中国", "https://www.oschina.net/news/rss", "domestic", "broad"),
]


def probe(one: tuple[str, str, str, str, str], timeout: int = 20) -> dict:
    sid, name, url, region, layer = one
    started = time.time()
    try:
        text = sources.get_text(url, timeout=timeout, use_proxy=True)
        items = sources.parse_feed(text)
        return {"id": sid, "name": name, "url": url, "region": region, "layer": layer,
                "ok": bool(items), "count": len(items),
                "first": (items[0].get("title") or "")[:50] if items else "",
                "seconds": round(time.time() - started, 1)}
    except Exception as e:
        return {"id": sid, "name": name, "url": url, "region": region, "layer": layer,
                "ok": False, "count": 0, "error": f"{type(e).__name__}: {str(e)[:60]}",
                "seconds": round(time.time() - started, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    todo = CANDIDATES
    if args.file:
        lines = Path(args.file).read_text(encoding="utf-8").splitlines()
        todo = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            url = parts[0]
            todo.append((parts[1] if len(parts) > 1 else url.split("//")[-1][:20],
                         parts[2] if len(parts) > 2 else url, url,
                         parts[3] if len(parts) > 3 else "overseas",
                         parts[4] if len(parts) > 4 else "broad"))

    good, bad = [], []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(probe, one): one for one in todo}
        for done, fut in enumerate(as_completed(futures), 1):
            row = fut.result()
            (good if row["ok"] else bad).append(row)
            mark = "OK " if row["ok"] else "×  "
            print(f"{mark} {row['id']:<18} {row['count']:>3} 条  {row['seconds']:>4}s  "
                  f"{row.get('first') or row.get('error','')}")

    print(f"\n可用 {len(good)} / 共 {len(todo)}")
    if good:
        print("\n=== 可直接粘进 config/feeds.yaml ===")
        for row in sorted(good, key=lambda r: (-r["count"], r["id"])):
            print(f'  - {{id: {row["id"]}, name: "{row["name"]}", url: "{row["url"]}", '
                  f'region: {row["region"]}, layer: {row["layer"]}, limit: 8, proxy: true}}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
