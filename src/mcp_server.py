"""ScholarScope MCP Server 命令行入口（兼容 Claude Code / Cursor）。

用法：
    python mcp_server.py --transport stdio    # Claude Code / Cursor 里配置
    python mcp_server.py --transport sse --port 8766
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sakura_mcp.server import main  # noqa: E402

if __name__ == "__main__":
    main()
