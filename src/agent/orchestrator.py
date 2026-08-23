"""Simplified Orchestrator for SPAR2 integration."""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from typing import Any, Dict, List, Optional

# Simplified orchestrator that only uses SPAR2
from agent.spar2.engine import SPAR2Engine, SPAR2_FEATURES


# SPAR2 引擎实际生效的核心机制（供 Web 创新模块面板展示）。
# 与旧 15 大创新模块的开关不同：这些机制在当前引擎中常驻开启。
DEFAULT_INNOVATION_FLAGS = {k: True for k in SPAR2_FEATURES}


class Orchestrator:
    """Simplified orchestrator that delegates to SPAR2 engine."""

    def __init__(self, llm_chat=None, max_output=20, judge_threshold=0.25,
                 max_judge=250, local_top_k=500, deadline_seconds=170.0, max_rounds=3):
        # Handle different LLM types - if it's a BaseLLM subclass, wrap it
        actual_llm_chat = llm_chat
        if llm_chat and hasattr(llm_chat, 'chat'):
            # If llm_chat is a BaseLLM instance, wrap its chat method
            def llm_wrapper(prompt, **kwargs):
                from llm.base import LLMMessage
                messages = [LLMMessage(role="user", content=prompt)]
                return llm_chat.chat(messages, **kwargs)
            actual_llm_chat = llm_wrapper
        
        # Use SPAR2 as the primary engine
        self.spar2 = SPAR2Engine(
            llm_chat=actual_llm_chat,
            max_output=max_output,
            judge_threshold=judge_threshold,
            max_judge=max_judge,
            local_top_k=local_top_k,
            deadline_seconds=deadline_seconds,
            max_rounds=max_rounds
        )
        self.logger = logging.getLogger(__name__)

    async def run(self, query: str, before_date: str = "") -> Dict:
        """Run the orchestrator."""
        try:
            # Delegate to SPAR2 engine
            result = self.spar2.run(query, before_date)
            return result
        except Exception as e:
            self.logger.error(f"Orchestrator error: {e}")
            # Fallback: return minimal result
            return {
                "query": query,
                "papers": [],
                "metrics": {"api_calls": 0, "tokens": 0, "latency": 0.0},
            }

    def sync_run(self, query: str, before_date: str = "") -> Dict:
        """Synchronous run method."""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        
        if loop and loop.is_running():
            # If in event loop, return coroutine
            return self.run(query, before_date)
        else:
            # Otherwise run synchronously
            return asyncio.run(self.run(query, before_date))
