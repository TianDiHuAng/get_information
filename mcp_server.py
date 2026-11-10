"""MCP 服务的入口：`python mcp_server.py`。

MCP 客户端（Claude Desktop / Cursor）用 stdio 连它，一行一个 JSON-RPC 对象。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector import mcp  # noqa: E402


def main() -> int:
    try:
        from collector import store

        store.migrate()
    except Exception:
        pass
    mcp.serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
