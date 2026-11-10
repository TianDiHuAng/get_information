"""模块系统：只属于这个站的功能，一个功能一个文件夹。

对齐 AIHOT 的 `modules/` 设计（docs/architecture.md「模块」）：

- 一个功能一个文件夹 `modules/<名字>/`，里面必须有 `module.py`；
- 框架**不导入任何模块**，只读清单 `site_modules.yaml`，按名字动态加载；
- 模块自己带页面、导航项与构建函数；
- 合并上游更新时，不会和自己的功能冲突。

清单长这样（顺序就是导航里的顺序）：

```yaml
modules:
  - name: leaderboard
  - name: free_tokens
```

`module.py` 约定：

```python
NAME = "leaderboard"          # 必须和文件夹同名
TITLE = "模型榜"               # 导航里显示的名字
HREF = "/leaderboard.html"    # 页面地址
SECTION = "模型"               # 归到哪个导航分组（没有就新建）
ICON = "chart"                # 图标名（见 theme._ICONS）

def build(root, payload, day):   # 可选：生成页面
    ...
```
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).parent.parent
MODULES_DIR = ROOT / "modules"
MANIFEST = ROOT / "site_modules.yaml"


def manifest() -> list[str]:
    """清单里列的模块名（按顺序）。没清单就是空 —— 框架本身不带模块。"""
    try:
        data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    names = []
    for row in (data.get("modules") or []):
        if isinstance(row, str):
            names.append(row)
        elif isinstance(row, dict) and row.get("name"):
            names.append(str(row["name"]))
    return names


def load(name: str) -> Any | None:
    """按名字加载 `modules/<name>/module.py`。加载失败返回 None（不拖垮整站）。"""
    path = MODULES_DIR / name / "module.py"
    if not path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location(f"zbit_module_{name}", path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def all_modules() -> list[Any]:
    out = []
    for name in manifest():
        mod = load(name)
        if mod is not None:
            out.append(mod)
    return out


def nav_entries() -> list[tuple[str, tuple[tuple[str, str, str], ...]]]:
    """把模块的导航项并进 `theme.SECTIONS`。返回 [(分组名, ((href, label, icon), ...))]。"""
    groups: dict[str, list[tuple[str, str, str]]] = {}
    for mod in all_modules():
        href = getattr(mod, "HREF", "")
        title = getattr(mod, "TITLE", "")
        if not href or not title:
            continue
        section = str(getattr(mod, "SECTION", "更多"))
        groups.setdefault(section, []).append((href, title, str(getattr(mod, "ICON", "grid"))))
    return [(name, tuple(items)) for name, items in groups.items()]


def build_all(root: Path, payload: dict[str, Any] | None = None,
              day: str | None = None) -> dict[str, Any]:
    """逐个跑模块的 build()。一个模块失败不影响其它模块。"""
    stats: dict[str, Any] = {}
    for mod in all_modules():
        name = str(getattr(mod, "NAME", "?"))
        fn = getattr(mod, "build", None)
        if not callable(fn):
            continue
        try:
            stats[name] = fn(root, payload, day)
        except Exception as e:
            stats[name] = {"error": f"{type(e).__name__}: {e}"}
    return stats
