"""行业包：把"这个站是什么行业"变成一份可切换、可校验的配置。

AIHOT 的 `docs/customize.md` 把换行业拆成八件事（站名文案 / 分类标签主题 /
信源 / 提示词 / 门槛 / 品牌 / 页面文案 / 模型）。这个模块管住其中最容易出错的
那部分：**跨文件的引用一致性**。

三种用法：

    industry.settings()            当前行业（站点名、slogan、出刊时间、门槛）
    industry.pack_path("taxonomy.yaml")   先找行业包，找不到退回 config/
    industry.validate()            体检：列出所有"改了一半"的地方

为什么要有"包"：换行业不是改值，是换一整套判断标准。把 `config/` 原样改掉，
想换回来就得靠 Git 回滚。包的做法是 `industry/<slug>/` 覆盖 `config/` 同名文件，
`config/industry.yaml` 里一行 `pack:` 切换 —— 原来的始终在。
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).parent.parent
CONFIG = ROOT / "config"
PACKS = ROOT / "industry"
SETTINGS_PATH = CONFIG / "industry.yaml"

# 换行业必须存在的提示词（缺一个，对应阶段就会静默降级）
REQUIRED_PROMPTS = (
    "prefilter.md", "attention-score.md", "structure.md",
    "group-pair.md", "group-review.md",
)

_DEFAULTS: dict[str, Any] = {
    "name": "Z-Bit",
    "tagline": "今日 AI 热点与大模型动态精选",
    "description": "每天一份 AI 情报日报",
    "locale": "zh-CN",
    "pack": "",
    "edition": {"daily": "09:00", "weekly": "周一", "monthly": "1 日"},
    "tiers": {"T1": 58, "T1_5": 66, "T2": 68},
    "browse_floor": 40,
}

_cache: dict[str, Any] = {}


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def settings(reload: bool = False) -> dict[str, Any]:
    """当前行业设置。没写 `config/industry.yaml` 时用默认值。"""
    if _cache.get("settings") and not reload:
        return _cache["settings"]
    data = dict(_DEFAULTS)
    if SETTINGS_PATH.exists():
        raw = _read_yaml(SETTINGS_PATH)
        for key, value in raw.items():
            if key in ("edition", "tiers") and isinstance(value, dict):
                merged = dict(_DEFAULTS.get(key) or {})
                merged.update(value)
                data[key] = merged
            else:
                data[key] = value
    # 环境变量优先：同一个代码库可以同时跑多个行业站
    env_pack = os.environ.get("RADAR_PACK", "").strip()
    if env_pack:
        data["pack"] = env_pack
    # 行业包自己的站名文案（pack.yaml），覆盖 config/industry.yaml 的同名字段
    pack_name = str(data.get("pack") or "").strip()
    if pack_name:
        meta = _read_yaml(PACKS / pack_name / "pack.yaml")
        if meta:
            data.update({k: v for k, v in meta.items() if k != "pack"})
    _cache["settings"] = data
    return data


def pack() -> Path | None:
    """当前行业包目录；没配或不存在时返回 None（表示只用 config/）。"""
    name = str(settings().get("pack") or "").strip()
    if not name:
        return None
    folder = PACKS / name
    return folder if folder.is_dir() else None


def pack_path(name: str) -> Path:
    """按"包优先、config 兜底"定位一个配置文件。"""
    current = pack()
    if current:
        candidate = current / name
        if candidate.exists():
            return candidate
    return CONFIG / name


def load(name: str) -> dict[str, Any]:
    """读一份可能被行业包覆盖的 YAML。"""
    return _read_yaml(pack_path(name))


def available() -> list[str]:
    if not PACKS.exists():
        return []
    return sorted(p.name for p in PACKS.iterdir() if p.is_dir())


# --------------------------------------------------------------------------- #
# 体检
# --------------------------------------------------------------------------- #

def _issue(level: str, code: str, message: str, hint: str = "") -> dict[str, str]:
    return {"level": level, "code": code, "message": message, "hint": hint}


def validate() -> list[dict[str, str]]:
    """把"改了一半"的地方都找出来。返回问题列表，空表示这份行业包是自洽的。

    检查的都是真实会出问题的联动：
    - 分类 key 进了网址，改了就是死链
    - 提示词里的枚举和 taxonomy 不一致，模型会输出页面不认识的类别
    - 主题引用了不存在的标签，那个主题页会永远为空
    - 信源指向不存在的实体，热度去重会把同一家公司算成两家
    """
    issues: list[dict[str, str]] = []
    conf = settings()

    # 1. 基本信息
    for field, label in (("name", "站名"), ("tagline", "一句话说明")):
        if not str(conf.get(field) or "").strip():
            issues.append(_issue("error", "meta.empty", f"{label}为空", "改 config/industry.yaml"))
    daily = str((conf.get("edition") or {}).get("daily") or "")
    if daily and not re.fullmatch(r"\d{2}:\d{2}", daily):
        issues.append(_issue("error", "meta.edition", f"日报时间 `{daily}` 不是 HH:MM",
                             "出刊时间是排程与告警共用的，写成 09:00 这种整点"))

    # 2. 分类
    taxonomy = load("taxonomy.yaml")
    raw_categories = taxonomy.get("categories") or []
    if isinstance(raw_categories, dict):
        categories = [{"key": k, **(v if isinstance(v, dict) else {})}
                      for k, v in raw_categories.items()]
    else:
        categories = raw_categories
    if not categories:
        issues.append(_issue("error", "taxonomy.empty", "taxonomy.yaml 里没有 categories",
                             "至少要有 k-12 个分类，页面、RSS、主题页都依赖它"))
    keys = []
    for row in categories:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip()
        if not key:
            issues.append(_issue("error", "taxonomy.key", f"分类缺 key：{row}", ""))
            continue
        if key in keys:
            issues.append(_issue("error", "taxonomy.dup", f"分类 key 重复：{key}",
                                 "key 会进 /feed/category/<key>.xml，不能重"))
        keys.append(key)
        if not str(row.get("label") or "").strip():
            issues.append(_issue("warn", "taxonomy.label", f"分类 {key} 缺中文名", ""))

    # 3. 提示词里的类别枚举
    structure = pack_path("prompts/structure.md")
    if structure.exists():
        text = structure.read_text(encoding="utf-8")
        for key in keys:
            if key not in text:
                issues.append(_issue(
                    "warn", "prompt.category",
                    f"分类 `{key}` 没有出现在 prompts/structure.md 里",
                    "模型不会输出这个类别，对应的分类页会一直是空的"))

    # 4. 主题引用
    topics = load("topics.yaml")
    rows = topics.get("topics") if isinstance(topics.get("topics"), list) else topics.get("items")
    tag_vocab = set()
    for row in (taxonomy.get("tags") or []):
        if isinstance(row, dict) and row.get("key"):
            tag_vocab.add(str(row["key"]))
        elif isinstance(row, str):
            tag_vocab.add(row)
    alias_vocab = set(tag_vocab)
    for row in (taxonomy.get("tags") or []):
        if isinstance(row, dict):
            alias_vocab.update(str(a) for a in (row.get("aliases") or []))
    entity_ids = {str(e.get("id")) for e in (taxonomy.get("entities") or []) if isinstance(e, dict)}
    for topic in (rows or []):
        if not isinstance(topic, dict):
            continue
        slug = topic.get("slug") or topic.get("key") or "?"
        for tag in (topic.get("tags") or []):
            if tag_vocab and str(tag) not in alias_vocab:
                issues.append(_issue("warn", "topic.tag",
                                     f"主题 `{slug}` 引用了未知标签 `{tag}`",
                                     "这个主题页会永远为空"))
        if topic.get("entity") and entity_ids and str(topic["entity"]) not in entity_ids:
            issues.append(_issue("warn", "topic.entity",
                                 f"主题 `{slug}` 引用了未知实体 `{topic['entity']}`", ""))

    # 5. 信源
    try:
        from .sources import REGISTRY

        ids = {s.get("id") for s in REGISTRY}
        for src in REGISTRY:
            owner = src.get("owner_entity_id")
            if owner and entity_ids and str(owner) not in entity_ids:
                issues.append(_issue("warn", "source.owner",
                                     f"信源 `{src.get('id')}` 的 owner_entity_id=`{owner}` 不存在",
                                     "热度会把它当成另一家参与方"))
            if not src.get("tier"):
                issues.append(_issue("warn", "source.tier",
                                     f"信源 `{src.get('id')}` 没有 tier",
                                     "没有分级就只会按默认门槛判，官方一手会被误杀"))
        overrides = load("sources.yaml").get("sources") or []
        for row in overrides:
            if isinstance(row, dict) and row.get("id") and row["id"] not in ids:
                issues.append(_issue("error", "source.unknown",
                                     f"sources.yaml 里的 `{row['id']}` 在代码里没有抓取器", ""))
    except Exception as e:
        issues.append(_issue("warn", "source.load", f"读信源失败：{e}", ""))

    # 6. 门槛
    tiers = conf.get("tiers") or {}
    raw_conf = _read_yaml(SETTINGS_PATH) if SETTINGS_PATH.exists() else {}
    if conf.get("pack") and "tiers" not in raw_conf:
        # 换了行业却沿用 AI 行业校准出来的门槛 —— 这是最容易忘、后果最大的一步
        issues.append(_issue(
            "warn", "threshold.uncalibrated",
            "这个行业包没有自己的门槛，正在沿用 AI 行业的 T1/T1_5/T2",
            "换行业必须重新标金标再定门槛，见 docs/customize.md 第 5 节"))

    # 6b. 分级门槛与 scoring.yaml 是否漂移
    try:
        scoring = load("scoring.yaml")
        layer_thr = scoring.get("thresholds") or {}
        for tier, layer in (("T1", "primary"), ("T1_5", "rank"), ("T2", "broad")):
            a, b = tiers.get(tier), layer_thr.get(layer)
            if a is not None and b is not None and int(a) != int(b):
                issues.append(_issue(
                    "warn", "threshold.drift",
                    f"{tier} 写的是 {a}，但 scoring.yaml 的 {layer} 是 {b}",
                    "两处都写门槛会漂移；建议只改 config/industry.yaml 的 tiers，或把这里对齐"))
    except Exception:
        pass

    # 7. 提示词文件
    for name in REQUIRED_PROMPTS:
        if not pack_path(f"prompts/{name}").exists():
            issues.append(_issue("error", "prompt.missing", f"缺 prompts/{name}", ""))

    # 8. 改用词规则
    wording_path = pack_path("wording.yaml")
    if wording_path.exists():
        data = _read_yaml(wording_path)
        for row in (data.get("rules") or []):
            pattern = str((row or {}).get("pattern") or "")
            if not pattern:
                continue
            try:
                re.compile(pattern)
            except re.error as e:
                issues.append(_issue("error", "wording.regex",
                                     f"wording.yaml 的正则写坏了：{pattern}（{e}）", ""))
    return issues


def summary(issues: list[dict[str, str]]) -> str:
    errors = sum(1 for i in issues if i["level"] == "error")
    warns = sum(1 for i in issues if i["level"] == "warn")
    if not issues:
        return "行业包自洽：没有发现问题。"
    lines = [f"{errors} 个错误 · {warns} 个提醒"]
    for issue in issues:
        flag = "✗" if issue["level"] == "error" else "!"
        line = f"  {flag} [{issue['code']}] {issue['message']}"
        if issue.get("hint"):
            line += f"\n      → {issue['hint']}"
        lines.append(line)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 建包与切换
# --------------------------------------------------------------------------- #

_SCAFFOLD_TAXONOMY = """# {name} 的分类。key 会进网址（/feed/category/<key>.xml），上线后不要改。
categories:
  - key: policy
    label: 政策
  - key: market
    label: 市场
  - key: player
    label: 机构
  - key: tech
    label: 技术
  - key: opinion
    label: 观点

# 标签词表：topic 页与页脚标签都从这里取
tags: []

# 公司/机构名录：热度去重与"主体"字段用
entities: []

# 总述免核对词（出现在摘要里不算专有名词）
plain_terms: []
"""

_SCAFFOLD_PROMPT = """# 评分标准（{name}）

> 这是新行业的起点，**每一句都要按你的判断改**。原样保留只会得到 AI 行业的判断。

## 这份材料值不值得看

按五个维度各打 0–10 分：

- **sig 份量**：影响多少人、多大范围
- **nov 增量**：有没有新事实（不是旧闻重发、不是观点复述）
- **cred 证据**：有没有可核查的一手来源
- **reson 共鸣**：这个行业的人会不会讨论
- **act 可用**：读者能不能据此做点什么

## 什么必须正常评价

- （写三条：你行业里真正重要的消息长什么样）

## 什么必须压住

- （写三条：你行业里典型的水文长什么样）

## 输出

只输出 JSON：{{"axes": {{"sig":0,"nov":0,"cred":0,"reson":0,"act":0}}, "itype":"", "reason":"一句话说明为什么这个分"}}
"""

_SCAFFOLD_WORDING = """# 改用词：标题/摘要/推荐理由里出现这些词时，让模型只改这些词。
# 每项一个正则和一个改法；写不出来就留空，不影响出刊。
rules: []
#  - pattern: "赋能"
#    replace: "帮助"
"""


def scaffold(slug: str, name: str, *, force: bool = False) -> dict[str, Any]:
    """建一个行业包骨架。已经存在就拒绝（除非 force）。"""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,40}", slug or ""):
        return {"ok": False, "error": "slug 只能用a-z 0-9 _ -，最长 40"}
    folder = PACKS / slug
    if folder.exists() and not force:
        return {"ok": False, "error": f"{folder} 已存在；要覆盖加 --force"}

    (folder / "prompts").mkdir(parents=True, exist_ok=True)
    (folder / "taxonomy.yaml").write_text(
        _SCAFFOLD_TAXONOMY.format(name=name), encoding="utf-8")
    (folder / "wording.yaml").write_text(_SCAFFOLD_WORDING, encoding="utf-8")
    (folder / "prompts" / "attention-score.md").write_text(
        _SCAFFOLD_PROMPT.format(name=name), encoding="utf-8")
    # 其它提示词先拷一份，改起来比从零写快
    for prompt in REQUIRED_PROMPTS:
        target = folder / "prompts" / prompt
        if target.exists():
            continue
        source = CONFIG / "prompts" / prompt
        if source.exists():
            shutil.copyfile(source, target)
    return {"ok": True, "pack": str(folder), "files": sorted(
        str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file())}


def use(slug: str) -> dict[str, Any]:
    """把 config/industry.yaml 的 pack 指向某个包（空串 = 用 config/ 原值）。"""
    if slug and not (PACKS / slug).is_dir():
        return {"ok": False, "error": f"没有这个包：{slug}"}
    data = _read_yaml(SETTINGS_PATH) if SETTINGS_PATH.exists() else {}
    data["pack"] = slug
    lines = ["# 当前行业。切换行业包就改 pack；留空表示直接用 config/ 下的文件。"]
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{key}:")
            for k, v in value.items():
                lines.append(f"  {k}: {v}")
        else:
            lines.append(f"{key}: {value if value is not None else ''}")
    SETTINGS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _cache.clear()
    return {"ok": True, "pack": slug or "(config/)"}
