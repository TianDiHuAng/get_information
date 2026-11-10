from dataclasses import dataclass, field, asdict


@dataclass
class Item:
    """统一条目模型：所有源都要归一化成这个结构。"""

    source: str          # 源 id，如 hackernews
    title: str
    url: str
    layer: str = "broad"  # broad(广谱) | rank(榜单) | search(搜索) | social(社媒)
    region: str = "overseas"  # overseas(国外) | domestic(国内)
    published: str = ""   # ISO8601
    summary: str = ""
    heat: float | None = None
    lang: str = "zh"
    author: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "Item":
        """从 dict 还原。`to_dict` 的逆操作，用于在阶段之间中转。"""
        return cls(
            source=str(raw.get("source") or ""),
            title=str(raw.get("title") or ""),
            url=str(raw.get("url") or ""),
            layer=str(raw.get("layer") or "broad"),
            region=str(raw.get("region") or "overseas"),
            published=str(raw.get("published") or ""),
            summary=str(raw.get("summary") or ""),
            heat=raw.get("heat"),
            lang=str(raw.get("lang") or "zh"),
            author=str(raw.get("author") or ""),
            extra=dict(raw.get("extra") or {}),
        )
