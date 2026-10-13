"""SPAR2：基于成熟 SPAR 架构改造的竞赛提分引擎。

与旧 Orchestrator 完全独立；通过 run_eval.py --engine spar2 接入评测。
"""

from agent.spar2.engine import SPAR2Engine

__all__ = ["SPAR2Engine"]
