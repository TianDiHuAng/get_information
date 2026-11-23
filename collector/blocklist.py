"""统一屏蔽词防火墙：一处配置，同时管网页隐藏、推送拦截与 AI 审核前跳过。

来自 freebie-radar 的 `enrich/blocklist.ts`。原实现是 DB 驱动（用户可在界面增删），
本项目保持「配置文件驱动」——规则写在 `config/blocklist.yaml`，改完下一轮自动生效，
不引入新的数据库表。

两种模式：
    keyword  子串匹配，走 SQL/内存都便宜，默认用这个
    regex    正则匹配，表达力强但慢，只在确有需要时用

scope 字段预留给「按源屏蔽」（如 `scope: linuxdo`），空/all 表示全局。

预设词表照搬原实现的 15 条，可在配置里 `preset: false` 关掉。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "blocklist.yaml"

# 常见非福利新闻/讨论噪音；原实现是「界面一键导入，不强制写入」，这里作为默认开启的基线
PRESET_NOISE_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("避坑", "keyword", "选购/消费避坑文章"),
    ("测评", "keyword", "产品长测/开箱"),
    ("横评", "keyword", "多款对比评测"),
    ("怎么选", "keyword", "选购攻略"),
    ("值得买吗", "keyword", "询问讨论"),
    ("致歉", "keyword", "品牌公告新闻"),
    ("股价", "keyword", "财经新闻"),
    ("油价", "keyword", "油价新闻"),
    ("漏电", "keyword", "维修讨论"),
    ("研学", "keyword", "消费吐槽"),
    ("冠军阵容", "keyword", "电竞资讯"),
    ("请问", "keyword", "提问帖"),
    ("求助", "keyword", "求助帖"),
    ("有没有", "keyword", "询问有没有"),
    ("求推荐", "keyword", "求推荐"),
    ("求一个", "keyword", "求资源"),
)


@dataclass(frozen=True)
class BlockRule:
    pattern: str
    mode: str = "keyword"
    scope: str = "all"
    note: str = ""
    regex: re.Pattern[str] | None = None

    def matches(self, text: str, source_id: str = "") -> bool:
        if self.scope not in ("all", "", "*") and self.scope != source_id:
            return False
        if self.mode == "regex" and self.regex is not None:
            return bool(self.regex.search(text))
        return self.pattern in text


def _compile(rule: dict) -> BlockRule:
    pattern = str(rule.get("pattern", "")).strip()
    mode = str(rule.get("mode", "keyword")).lower()
    scope = str(rule.get("scope", "all") or "all")
    regex = None
    if mode == "regex" and pattern:
        try:
            regex = re.compile(pattern, re.I)
        except re.error:
            # 失效正则降级为字面量子串，不让一条坏规则拦住整轮
            mode = "keyword"
    return BlockRule(pattern, mode, scope, str(rule.get("note", "")), regex)


def load_block_rules(path: Path | None = None) -> list[BlockRule]:
    """读取屏蔽规则；preset 默认开，可用 `preset: false` 关掉。"""
    path = path or CONFIG_PATH
    data: dict = {}
    if path.exists():
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, yaml.YAMLError):
            data = {}

    rules: list[BlockRule] = []
    if data.get("preset", True):
        rules.extend(BlockRule(p, m, "all", note) for p, m, note in PRESET_NOISE_PATTERNS)
    for raw in data.get("rules", []) or []:
        if isinstance(raw, dict) and raw.get("pattern"):
            rules.append(_compile(raw))
    return rules


def is_blocked(text: str, rules: list[BlockRule] | None = None, source_id: str = "") -> bool:
    """判断一条内容是否命中任一屏蔽规则。"""
    for rule in rules if rules is not None else load_block_rules():
        if rule.matches(text or "", source_id):
            return True
    return False
