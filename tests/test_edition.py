"""成刊：规则编排（不调模型）。

重点验证四件事：
1. 一件事一条（同一事件只出代表稿）；
2. 老事件（最近 7 天报过）默认不再出现，多家仍在说才降级成快讯；
3. 同一信源最多 2 条正文，快讯不受此限；
4. 编排完全可复现：同样的输入，同样的一期。
"""

import pytest

from collector import digest, edition


def mk(url, title, source="hackernews", layer="rank", score=50.0, **extra):
    base = {"topic": True, "deal": False, "score": score}
    base.update(extra)
    return {"source": source, "title": title, "url": url, "layer": layer,
            "region": "overseas", "summary": f"{title} 的摘要", "extra": base}


def payload(items):
    return {"items": items, "stats": {"sources_ok": 5, "by_region": {}, "by_layer": {}}}


def test_event_has_one_representative():
    rep = mk("https://a/1", "Anthropic 发布 Fable 5.2", score=90,
             event_id=7, event_size=7, event_sources=4, event_representative=True)
    dup = mk("https://a/2", "Fable 5.2 上线", score=95, source="x",
             event_id=7, event_size=7, event_sources=4, event_representative=False)
    plan = edition.arrange(payload([dup, rep]))
    assert plan["lead"]["url"] == "https://a/1"
    assert dup["url"] not in plan["used"]


def test_blocked_items_never_enter():
    bad = mk("https://a/1", "某公司发布财报", score=99,
             attention={"label": "BLOCK", "available": False})
    good = mk("https://a/2", "OpenAI 发布新模型", score=40)
    plan = edition.arrange(payload([bad, good]))
    assert plan["lead"]["url"] == "https://a/2"


def test_deal_goes_to_its_own_section():
    deal = mk("https://a/1", "免费额度领取", score=99, deal=True)
    plan = edition.arrange(payload([deal]))
    assert plan["lead"] is None


def test_official_source_gets_a_bonus():
    official = mk("https://a/1", "官方发布", layer="primary", score=60)
    media = mk("https://a/2", "媒体转述", layer="rank", score=60, source="sspai")
    assert edition.importance(official) > edition.importance(media)


def test_more_participants_ranks_higher():
    wide = mk("https://a/1", "很多家在说", score=60, event_size=6, event_sources=6)
    narrow = mk("https://a/2", "只有一家", score=60, source="sspai")
    assert edition.importance(wide) > edition.importance(narrow)


def test_followup_is_penalised():
    fresh = mk("https://a/1", "新事", score=60)
    old = mk("https://a/2", "老事", score=60, repeat=True)
    assert edition.importance(fresh) > edition.importance(old)


def test_per_source_cap_in_body():
    items = [mk(f"https://a/{i}", f"标题 {i}", source="hackernews", score=60 - i) for i in range(6)]
    plan = edition.arrange(payload(items), body_n=8)
    total_hn = len([i for i in ([plan["lead"]] + plan["highlights"] + plan["body"]) if i["source"] == "hackernews"])
    assert total_hn <= edition.PER_SOURCE


def test_old_event_only_enters_briefs_when_many_still_talk():
    old_single = mk("https://a/1", "旧闻单来源", score=99, repeat=True, event_sources=1)
    old_many = mk("https://a/2", "旧闻多来源", score=80, repeat=True, event_sources=4)
    fresh = mk("https://a/3", "新事", score=50)
    plan = edition.arrange(payload([old_single, old_many, fresh]))
    assert plan["lead"]["url"] == "https://a/3"
    assert [i["url"] for i in plan["briefs"]] == ["https://a/2"]


def test_lead_and_highlights_split():
    items = [mk(f"https://a/{i}", f"新闻 {i}：某公司发布新一代模型与配套工具", score=80 - i, source=f"s{i}")
             for i in range(6)]
    plan = edition.arrange(payload(items))
    assert plan["lead"]["url"] == "https://a/0"
    assert [i["url"] for i in plan["highlights"]] == ["https://a/1", "https://a/2", "https://a/3"]
    assert plan["body"][0]["url"] == "https://a/4"


def test_short_title_is_penalised_not_dropped():
    """`太疯狂了` 这种只有情绪的标题不该占头条/看点，但也不该消失。"""
    empty_title = mk("https://a/1", "太疯狂了", score=95, source="x")
    real_title = mk("https://a/2", "Anthropic 发布 Claude Fable 5.2 与 Mythos 5.2", score=70)
    plan = edition.arrange(payload([empty_title, real_title]))
    assert plan["lead"]["url"] == "https://a/2", "空标题不能当头条"
    assert empty_title["url"] in [i["url"] for i in plan["body"]], "但也不该消失"
    assert edition.headline_eligible(empty_title) is False
    assert edition.headline_eligible(real_title) is True


def test_arrange_is_deterministic():
    items = [mk(f"https://a/{i}", f"新闻 {i}", score=50 + i % 3, source=f"s{i}") for i in range(8)]
    a = edition.arrange(payload(items))
    b = edition.arrange(payload(list(reversed(items))))
    assert [i["url"] for i in a["highlights"]] == [i["url"] for i in b["highlights"]]


def test_empty_day_is_handled():
    plan = edition.arrange(payload([]))
    assert plan["lead"] is None
    assert edition.render_md(plan, lambda it: "- x") == ["## 今日要闻", "", "- 今天没有值得入选的内容。", ""]


def test_rendered_md_has_no_duplicate_urls():
    items = [mk(f"https://a/{i}", f"新闻 {i}", score=80 - i, source=f"s{i}") for i in range(6)]
    plan = edition.arrange(payload(items))
    md = "\n".join(edition.render_md(plan, digest._line))
    for it in items:
        assert md.count(it["url"]) == 1, f"{it['url']} 在日报里出现了多次"


def test_digest_picks_match_the_plan():
    """`picked` 决定哪些条目算「已报」，必须和实际渲染出来的内容一致。"""
    items = [mk(f"https://a/{i}", f"新闻 {i}", score=80 - i, source=f"s{i}") for i in range(5)]
    p = payload(items)
    plan = edition.arrange(p)
    chosen = digest.picked(p)
    urls = {i["url"] for i in chosen}
    assert plan["lead"]["url"] in urls
    assert len(urls) == len(chosen), "不能重复记同一条"
