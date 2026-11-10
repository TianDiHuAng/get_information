"""测试夹具：把 store 的库指到临时目录，绝不碰 data/radar.db。"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector import store  # noqa: E402


@pytest.fixture()
def tmpdb(tmp_path, monkeypatch):
    """每个测试一份独立数据库，用完即弃。"""
    path = tmp_path / "radar.db"
    monkeypatch.setattr(store, "DB_PATH", path)
    store.migrate()
    return path
