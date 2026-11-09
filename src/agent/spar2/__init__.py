"""SPAR2：多源论文检索组件与传统批量筛选流程。

在线工作台与 MCP 由 Orchestrator 调用 SPAR2Engine 完成查询规划、多轮检索和引文扩展。
"""

from agent.spar2.engine import SPAR2Engine

__all__ = ["SPAR2Engine"]
