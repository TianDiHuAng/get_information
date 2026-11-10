"""一次跑完：抓取 → 去重 → 打分 → 注意力评分 → 输出 JSON + 静态站 + 日报。

与之前相比的三处变化（都是为了「可评测、可恢复、不重复」）：
1. 采集后落 SQLite（`data/radar.db`），每条有身份与出现记录，跨天重复可查；
2. 老的关键词分之后再加一层「注意力评分」（LLM 五轴，见 collector/rating.py），
   LLM 不可用时自动退回老分，不影响出刊；
3. 日报选完条目后写「已报」记录，最近 7 天报过的不再出现。

用法：
    python run.py              # 正常一轮
    python run.py --skip-rate  # 跳过 LLM 评分（调样式/断网时用）
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from collector import events, rating, store, structure
from collector.archive import save as save_archive
from collector.digest import build as build_digest
from collector.digest import picked as digest_picked
from collector.health import update as update_health
from collector.history import append as append_history
from collector.history import load as load_history
from collector.leaderboards import fetch as fetch_lmarena
from collector.leaderboards import fetch_aa, update_aa
from collector.leaderboards import update as update_lmarena
from collector.papers import run as papers_weekly
from collector.pipeline import run
from collector.pushmail import send as send_mail
from collector.render import render
from collector.translate import translate_items

ROOT = Path(__file__).parent


def _stage(name: str, day: str):
    """阶段记录：中断后能看出停在哪一步，而不是只有一个 traceback。"""
    try:
        return store.run_start(day, name)
    except Exception:
        return None


def _done(run_id, status: str = "ok", detail: str | None = None) -> None:
    if run_id is None:
        return
    try:
        store.run_finish(run_id, status, detail)
    except Exception:
        pass


def main(skip_rate: bool = False, send_mail_enabled: bool = True) -> None:
    day = store.today_str()
    try:
        store.migrate()
    except Exception as e:
        print(f"存储层初始化失败（继续，但会失去跨天去重）: {type(e).__name__}: {e}")

    stage = _stage("pipeline", day)
    payload = run()
    _done(stage)

    # 注意力评分：LLM 不可用/预算耗尽/结果不明时，老分原样保留
    if skip_rate:
        payload["stats"]["attention"] = {"skipped": "cli"}
    else:
        stage = _stage("rating", day)
        try:
            payload["stats"]["attention"] = rating.rate_items(payload["items"], day=day)
        except Exception as e:
            payload["stats"]["attention"] = {"error": f"{type(e).__name__}: {e}"}
            _done(stage, "error", str(e))
            stage = None
        _done(stage)

    stage = _stage("translate", day)
    payload["stats"]["translate"] = translate_items(payload["items"])
    _done(stage)

    # 结构化：分类 / 标签 / 主体 / 是不是一条具体新闻（喂主题页、事件、防幻觉）
    if skip_rate:
        payload["stats"]["structure"] = {"skipped": "cli"}
    else:
        stage = _stage("structure", day)
        try:
            payload["stats"]["structure"] = structure.structure_items(payload["items"], day=day)
        except Exception as e:
            payload["stats"]["structure"] = {"error": f"{type(e).__name__}: {e}"}
            _done(stage, "error", str(e))
            stage = None
        _done(stage)

    # 事件聚簇：同一件事的多篇报道收成一个事件，日报只出代表稿
    if skip_rate:
        payload["stats"]["events"] = {"skipped": "cli"}
    else:
        stage = _stage("events", day)
        try:
            payload["stats"]["events"] = events.cluster_items(payload["items"], day=day)
        except Exception as e:
            payload["stats"]["events"] = {"error": f"{type(e).__name__}: {e}"}
            _done(stage, "error", str(e))
            stage = None
        _done(stage)

    payload["stats"]["health"] = update_health(payload["stats"])
    try:
        store.save_source_health(payload["stats"]["health"])
    except Exception:
        pass
    append_history(payload["stats"])  # 当日快照，喂给趋势图

    lmarena = update_lmarena(fetch_lmarena())  # 榜单快照（官方 HF 镜像，失败用缓存）
    aa = update_aa(fetch_aa())  # AA 智能指数快照（免费 API，失败用缓存）

    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "items.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    stage = _stage("render", day)
    out = render(payload, ROOT / "site" / "index.html", history=load_history(7),
                 lmarena=lmarena, aa=aa)
    arch = save_archive(payload, out, ROOT, datetime.now().strftime("%Y-%m-%d"))
    _done(stage)

    stage = _stage("digest", day)
    digest = build_digest(payload, lmarena=lmarena, aa=aa)
    try:  # 记「已报」：下一轮这些条目在日报里不再出现
        marked = store.mark_reported(digest_picked(payload), day, slot="digest")
    except Exception:
        marked = 0
    _done(stage)

    print(f"[4/4] 已生成 {out}  ({len(payload['items'])} 条)")
    print(f"      日报: {digest}（记已报 {marked} 条）")
    if arch.get("page"):
        print(f"      归档: {arch['page']}")

    att = payload["stats"].get("attention") or {}
    if att.get("scored"):
        print(f"      评分: {att['scored']} 条打分 / {att['selected']} 条过门槛 / "
              f"{att['blocked']} 条预筛拦截 / {att.get('failed', 0)} 条失败")
        llm_stats = att.get("llm") or {}
        if llm_stats.get("total"):
            print(f"      调用: {llm_stats['total']} 次（命中回执 {llm_stats.get('hit', 0)}），"
                  f"token {llm_stats.get('tokens', 0)}")

    ev = payload["stats"].get("events") or {}
    if ev.get("events"):
        print(f"      事件: {ev['events']} 个（合并 {ev['merged']} 条 / "
              f"多篇事件 {ev.get('clusters', 0)} 个）· 判定 {ev.get('pairs_judged', 0)} 对"
              f"（新增 {ev.get('pairs_new', 0)}）")

    st = payload["stats"].get("structure") or {}
    if st.get("structured"):
        cats = st.get("categories") or {}
        top = "、".join(f"{k}×{v}" for k, v in sorted(cats.items(), key=lambda kv: -kv[1])[:3])
        print(f"      结构: {st['structured']} 条（{top}）· "
              f"综合稿 {str((st.get('scopes') or {}).get('composite', 0))} 条")

    if send_mail_enabled:
        try:
            print(f"      推送: {send_mail(digest, payload['stats'], payload=payload, lmarena=lmarena, aa=aa)}")
        except Exception as e:  # 推送失败不影响采集
            print(f"      推送失败: {type(e).__name__}: {e}")
    else:
        print("      推送: 已跳过（--no-mail）")

    try:
        print(f"      周报: {papers_weekly()}")
    except Exception as e:
        print(f"      周报失败: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main(skip_rate="--skip-rate" in sys.argv, send_mail_enabled="--no-mail" not in sys.argv)
