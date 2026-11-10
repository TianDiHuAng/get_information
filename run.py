"""一次跑完：抓取 → 去重 → 打分 → 注意力评分 → 输出 JSON + 静态站 + 日报。

与之前相比的三处变化（都是为了「可评测、可恢复、不重复」）：
1. 采集后落 SQLite（`data/radar.db`），每条有身份与出现记录，跨天重复可查；
2. 老的关键词分之后再加一层「注意力评分」（LLM 五轴，见 collector/rating.py），
   LLM 不可用时自动退回老分，不影响出刊；
3. 日报选完条目后写「已报」记录，最近 7 天报过的不再出现。

用法：
    python run.py              # 正常一轮
    python run.py --skip-rate  # 跳过 LLM 评分（调样式/断网时用）
    python run.py --no-mail    # 不发日报与周报月报邮件
    python run.py --dry-push   # 不发告警与突发的即时推送（只看不发）
    python run.py --fresh      # 忽略断点状态，强制重新抓取
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from collector import (alerts, board, breaking, events, export, offline, rating, report, share,
                       site, state, store, structure, timeline, topics)
from collector import pushmail
from collector.identity import item_identity
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


def main(skip_rate: bool = False, send_mail_enabled: bool = True,
         fresh: bool = False, dry_push: bool = False) -> None:
    day = store.today_str()
    try:
        store.migrate()
    except Exception as e:
        print(f"存储层初始化失败（继续，但会失去跨天去重）: {type(e).__name__}: {e}")

    # 断点续跑：抓到一半挂了，重跑时不用再抓一遍网络。
    # 只续"抓取"这一段 —— 模型阶段有回执保护，重跑很快也不花钱。
    payload = None
    if not fresh and "pipeline" in store.stages_done(day):
        if not state.path(day).exists():
            print("      续跑: 没有状态文件，重新抓")
        elif state.is_stale(day):
            print("      续跑: 状态文件太旧（超过 12 小时），重新抓")
        else:
            payload = state.load(day)
            if payload:
                print(f"      续跑: 复用 {len(payload['items'])} 条已抓条目（跳过抓取与正文）")
            else:
                print("      续跑: 状态文件读不出来，重新抓")

    if payload is None:
        stage = _stage("pipeline", day)
        payload = run()
        _done(stage)
        try:
            state.save(payload, day)
            state.prune()
        except Exception as e:
            print(f"      状态保存失败（不影响本轮）: {type(e).__name__}: {e}")

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

    # 评分 / 结构 / 事件都写进了各自的表，但**从库里读的地方**（周报、月报、时间线）
    # 只看 items.extra —— 这里补写一次，让库里的 extra 成为完整的一份。
    stage = _stage("persist", day)
    try:
        store.upsert_items(payload["items"], day)
    except Exception as e:
        print(f"      回写条目失败: {type(e).__name__}: {e}")
    _done(stage)

    # 评分 / 结构 / 事件都要往 Item.extra 上写，到这里才算完 —— 转 dict 交给下游
    stage = _stage("translate", day)
    payload["items"] = [i.to_dict() for i in payload["items"]]
    # 给每条挂上库内 id：首页卡片要指向站内的 /items/<id>.html（和 AIHOT 一致）
    try:
        ids = store.ids_for([item_identity(it["url"]) for it in payload["items"]])
        for it in payload["items"]:
            it["extra"]["db_id"] = ids.get(item_identity(it["url"]))
    except Exception as e:
        print(f"      站点 id 映射失败（卡片将指向原文）: {type(e).__name__}: {e}")
    payload["stats"]["translate"] = translate_items(payload["items"])
    _done(stage)

    # 分享图：给邮件/RSS 转发用的预览图（不调模型）
    try:
        payload["stats"]["share"] = share.build(payload, ROOT / "site")
        sh = payload["stats"]["share"]
        if sh.get("file"):
            print(f"      分享图: {Path(sh['file']).name}（{sh['bytes'] // 1024} KB）")
    except Exception as e:
        print(f"      分享图生成失败: {type(e).__name__}: {e}")

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

    # 多出口：RSS / JSON / llms.txt（都从同一份 payload 生成，不重新判断）
    stage = _stage("export", day)
    try:
        ex = export.build(payload, ROOT / "site")
        payload["stats"]["export"] = ex
        print(f"      出口: {len(ex.get('files') or [])} 个文件"
              f"（feed {ex.get('feeds', 0)} 个 · API · llms.txt）")
    except Exception as e:
        print(f"      出口生成失败: {type(e).__name__}: {e}")
    _done(stage)

    # 本地看板：源健康 / 评分分布 / 成本 / 舆论场
    stage = _stage("board", day)
    try:
        bd = board.build(payload, ROOT / "site")
        payload["stats"]["board"] = bd
        print(f"      看板: board.html（告警 {bd['alerts']} 条 · "
              f"官方 {bd['discourse']['official']} 条 / 国内 {bd['discourse']['domestic']} 条）")
    except Exception as e:
        print(f"      看板生成失败: {type(e).__name__}: {e}")
    _done(stage)

    # 长期时间线 + 叙事对比（只读库，不调模型）
    stage = _stage("timeline", day)
    try:
        tl = timeline.build(ROOT / "site")
        payload["stats"]["timeline"] = tl
        print(f"      时间线: {tl['events']} 个事件 / {tl['subjects']} 个主体 / "
              f"{tl['narratives']} 组跨渠道叙事")
    except Exception as e:
        print(f"      时间线生成失败: {type(e).__name__}: {e}")
    _done(stage)

    # 主题页 / 标签页：把结构化结果变成能翻的页面
    stage = _stage("topics", day)
    try:
        tp = topics.build(ROOT / "site")
        payload["stats"]["topics"] = tp
        print(f"      主题: {tp['pages']} 个页面（{tp['categories']} 分类 / {tp['tags']} 标签）")
    except Exception as e:
        print(f"      主题页生成失败: {type(e).__name__}: {e}")
    _done(stage)

    # 周报月报要等日报写完「已报」记录之后才能编 —— 提前跑出来永远是 0 件。
    # 它们的生成逻辑挪到 digest 之后（见下面）。

    # 单文件离线归档：断网/换机时能带走的一份
    stage = _stage("offline", day)
    try:
        off = offline.build(payload, ROOT / "site")
        payload["stats"]["offline"] = off
        print(f"      离线版: offline.html（{off['bytes'] // 1024} KB）")
    except Exception as e:
        print(f"      离线归档生成失败: {type(e).__name__}: {e}")
    _done(stage)

    stage = _stage("digest", day)
    digest = build_digest(payload, lmarena=lmarena, aa=aa)
    try:  # 记「已报」与本期出刊：下一轮这些条目在日报里不再出现，也能判缺期
        picks = digest_picked(payload)
        marked = store.mark_reported(picks, day, slot="digest")
        store.save_edition("daily", day, entries=len(picks))
    except Exception:
        marked = 0
    _done(stage)

    # 周报月报：从日报汇编（必须在 digest 之后 —— 它读的是"今天进了日报"的记录）
    stage = _stage("reports", day)
    try:
        rm = report.build_all(day)
        payload["stats"]["reports"] = rm
        print(f"      周报: {rm['weekly']['events']} 件（{rm['weekly']['reports']} 条报道）"
              f" · 月报: {rm['monthly']['events']} 件")
    except Exception as e:
        print(f"      周报月报生成失败: {type(e).__name__}: {e}")
    _done(stage)

    # 整站页面：精选之外的全部模块（全部动态/热门/文章页/日报/周报/月报/事件/搜索/静态页）
    stage = _stage("site", day)
    try:
        sp = site.build(payload, ROOT / "site", day)
        payload["stats"]["site"] = sp
        print(f"      站点: {sp.get('pages', 0)} 个页面"
              f"（全部 {sp.get('all', {}).get('items', 0)} 条 / 文章 {sp.get('items', {}).get('items', 0)} 篇"
              f" / 热门 {sp.get('hot', {}).get('events', 0)} 个事件）")
    except Exception as e:
        print(f"      站点页面生成失败: {type(e).__name__}: {e}")
    _done(stage)

    # 周一发周报、每月 1 号发月报：不然它们只躺在 data/ 里没人看
    try:
        today = datetime.now()
        due = []
        if today.weekday() == 0:
            due.append(("weekly", "周报"))
        if today.day == 1:
            due.append(("monthly", "月报"))
        for kind, label in due:
            info = (payload["stats"].get("reports") or {}).get(kind) or {}
            path = Path(info.get("file") or "")
            if not path.is_file():
                continue
            if not send_mail_enabled:
                print(f"      {label}: 已生成（--no-mail，未发送）")
                continue
            subject = f"[信息雷达] {label} · {info['range'][0]} ~ {info['range'][1]}"
            print(f"      {label}推送: {pushmail.send_text(subject, path.read_text(encoding='utf-8'))}")
    except Exception as e:
        print(f"      周报月报推送失败: {type(e).__name__}: {e}")

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

    stage = _stage("alerts", day)
    try:
        alert_result = alerts.run(payload, notify=not dry_push)
        found = int(alert_result.get("found") or 0)
        if found:
            print(f"      告警: {found} 条（新增 {alert_result.get('fresh', 0)}，"
                  f"{alert_result.get('sent')}）")
    except Exception as e:
        print(f"      告警检查失败: {type(e).__name__}: {e}")
    _done(stage)

    # 突发即时推：够格的立刻发，不等第二天早上
    stage = _stage("breaking", day)
    try:
        br = breaking.run(payload["items"], notify=not dry_push)
        if br.get("picked"):
            print(f"      突发: {br['picked']} 条 → {br.get('sent')}")
    except Exception as e:
        print(f"      突发推送失败: {type(e).__name__}: {e}")
    _done(stage)

    # 整轮跑完才清状态：中途挂了下次还能接着来
    try:
        state.discard(day)
    except Exception:
        pass


if __name__ == "__main__":
    main(skip_rate="--skip-rate" in sys.argv,
         send_mail_enabled="--no-mail" not in sys.argv,
         fresh="--fresh" in sys.argv,
         dry_push="--dry-push" in sys.argv)
