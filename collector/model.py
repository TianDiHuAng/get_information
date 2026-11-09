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
