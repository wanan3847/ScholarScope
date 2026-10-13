"""
ScholarScope 智能论文检索 Agent 包。

子模块：
    spar2          - SPAR2 引擎（核心实现）
    orchestrator   - 顶层编排器（简化版）
"""

from agent.orchestrator import Orchestrator
from agent.spar2.engine import SPAR2Engine

__all__ = [
    "Orchestrator",
    "SPAR2Engine",
]
