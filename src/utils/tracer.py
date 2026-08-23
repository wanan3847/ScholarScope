"""
Token Budget + LangSmith 风格 Trace（§5.2 §5.4）

特性：
    1) Token 预算管理：单查询 20K 输入 + 6K 输出硬上限，超出自动降级
    2) LangSmith 风格 trace：记录每个 LLM 调用的 prompt / output / token / latency
    3) 逐模块打点：统计每个子模块的 token 消耗

用法：
    tracer = Tracer(token_budget=20000)
    with tracer.span("L1_query_understanding") as span:
        result = llm.complete(prompt)
        span.record_llm_call(prompt, result, tokens=1234)

    budget = tracer.check_budget()
    if budget.exceeded:
        # 降级策略
        ...
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Token 预算
# ------------------------------------------------------------------ #

@dataclass
class TokenBudget:
    """单次查询的 Token 预算。"""

    input_limit: int = 20000       # §5.2: 20K 输入
    output_limit: int = 6000       # §5.2: 6K 输出
    input_used: int = 0
    output_used: int = 0

    @property
    def input_exceeded(self) -> bool:
        return self.input_used > self.input_limit

    @property
    def output_exceeded(self) -> bool:
        return self.output_used > self.output_limit

    @property
    def exceeded(self) -> bool:
        return self.input_exceeded or self.output_exceeded

    @property
    def input_remaining(self) -> int:
        return max(0, self.input_limit - self.input_used)

    @property
    def output_remaining(self) -> int:
        return max(0, self.output_limit - self.output_used)

    @property
    def input_ratio(self) -> float:
        return self.input_used / self.input_limit if self.input_limit > 0 else 0.0

    def consume(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        self.input_used += input_tokens
        self.output_used += output_tokens

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input_limit": self.input_limit,
            "output_limit": self.output_limit,
            "input_used": self.input_used,
            "output_used": self.output_used,
            "input_exceeded": self.input_exceeded,
            "output_exceeded": self.output_exceeded,
            "exceeded": self.exceeded,
        }


# ------------------------------------------------------------------ #
# Span - 单个模块的 trace
# ------------------------------------------------------------------ #

@dataclass
class Span:
    """单个模块调用的 trace span。"""

    name: str                                  # 模块名（如 "L1_query_understanding"）
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    api_calls: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    # 详细 LLM 调用记录（LangSmith 风格）
    llm_traces: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def elapsed_ms(self) -> float:
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000

    def record_llm_call(
        self,
        prompt: str,
        output: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: str = "",
    ) -> None:
        """记录一次 LLM 调用（LangSmith 风格）。"""
        self.llm_calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.llm_traces.append({
            "prompt_preview": prompt[:200],        # 只存前 200 字符避免内存爆
            "output_preview": output[:200],
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model": model,
            "timestamp": time.time(),
        })

    def record_api_call(self, n: int = 1) -> None:
        self.api_calls += n

    def set_metadata(self, key: str, value: Any) -> None:
        self.metadata[key] = value

    def finish(self) -> None:
        self.end_time = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "llm_calls": self.llm_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "api_calls": self.api_calls,
            "metadata": self.metadata,
            "llm_traces_count": len(self.llm_traces),
        }


# ------------------------------------------------------------------ #
# Tracer - 顶层 trace 收集器
# ------------------------------------------------------------------ #

class Tracer:
    """
    LangSmith 风格的端到端 trace 收集器。

    用法：
        tracer = Tracer(token_budget=20000)

        with tracer.span("L1") as s:
            out = llm.complete(prompt)
            s.record_llm_call(prompt, out, input_tokens=100, output_tokens=20)

        with tracer.span("L2") as s:
            ...

        report = tracer.report()
        if tracer.budget.exceeded:
            logger.warning("Token 预算超限：%s", tracer.budget.to_dict())
    """

    def __init__(
        self,
        token_budget: int = 20000,
        output_budget: int = 6000,
        enable_detailed_traces: bool = True,
    ):
        self.budget = TokenBudget(
            input_limit=token_budget,
            output_limit=output_budget,
        )
        self.enable_detailed_traces = enable_detailed_traces
        self.spans: List[Span] = []
        self._current_span: Optional[Span] = None

    @contextmanager
    def span(self, name: str) -> Iterator[Span]:
        """上下文管理器：自动记录 span 开始/结束。"""
        span = Span(name=name)
        self.spans.append(span)
        prev = self._current_span
        self._current_span = span
        try:
            yield span
        finally:
            span.finish()
            self._current_span = prev

    def consume_tokens(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        """消费 token 预算。"""
        self.budget.consume(input_tokens, output_tokens)
        if self._current_span:
            self._current_span.input_tokens += input_tokens
            self._current_span.output_tokens += output_tokens

    def record_llm_call(
        self,
        prompt: str,
        output: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: str = "",
    ) -> None:
        """记录 LLM 调用（自动归到当前 span）。

        注意：只对 budget 消费一次，span 的 token 计数由
        Span.record_llm_call 统一维护，避免双计数。
        """
        self.budget.consume(input_tokens, output_tokens)
        if self._current_span:
            if self.enable_detailed_traces:
                self._current_span.record_llm_call(
                    prompt, output, input_tokens, output_tokens, model,
                )
            else:
                # 不存详细 trace，但仍需累计计数
                self._current_span.llm_calls += 1
                self._current_span.input_tokens += input_tokens
                self._current_span.output_tokens += output_tokens

    def check_budget(self) -> TokenBudget:
        """返回当前预算状态。"""
        return self.budget

    def should_degrade(self, threshold: float = 0.9) -> bool:
        """
        是否应该触发降级。

        降级策略（§5.2）：
            - input_ratio > threshold → 截断上下文 / 改用更小模型
            - exceeded → 跳过可选模块（如 HS / RefChain）
        """
        return self.budget.input_ratio > threshold or self.budget.exceeded

    # ------------------------------------------------------------------ #
    # 报告
    # ------------------------------------------------------------------ #

    def report(self) -> Dict[str, Any]:
        """生成 trace 报告（LangSmith 风格）。"""
        total_input = sum(s.input_tokens for s in self.spans)
        total_output = sum(s.output_tokens for s in self.spans)
        total_llm_calls = sum(s.llm_calls for s in self.spans)
        total_api_calls = sum(s.api_calls for s in self.spans)
        total_elapsed = sum(s.elapsed_ms for s in self.spans)

        return {
            "summary": {
                "total_spans": len(self.spans),
                "total_llm_calls": total_llm_calls,
                "total_api_calls": total_api_calls,
                "total_input_tokens": total_input,
                "total_output_tokens": total_output,
                "total_elapsed_ms": round(total_elapsed, 2),
            },
            "budget": self.budget.to_dict(),
            "spans": [s.to_dict() for s in self.spans],
            "degraded": self.should_degrade(),
        }

    def module_breakdown(self) -> Dict[str, Dict[str, Any]]:
        """按模块统计 token 消耗（用于定位最贵的模块）。"""
        breakdown: Dict[str, Dict[str, Any]] = {}
        for s in self.spans:
            breakdown[s.name] = {
                "llm_calls": s.llm_calls,
                "input_tokens": s.input_tokens,
                "output_tokens": s.output_tokens,
                "total_tokens": s.input_tokens + s.output_tokens,
                "elapsed_ms": round(s.elapsed_ms, 2),
                "api_calls": s.api_calls,
            }
        return breakdown

    def save_to_file(self, path: str) -> None:
        """把 trace 报告写入 JSON 文件。"""
        import json
        from pathlib import Path

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            json.dumps(self.report(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Trace 报告写入 %s", path)


# ------------------------------------------------------------------ #
# 全局单例（可选）
# ------------------------------------------------------------------ #

_global_tracer: Optional[Tracer] = None


def get_global_tracer() -> Tracer:
    """获取全局 Tracer 单例。"""
    global _global_tracer
    if _global_tracer is None:
        _global_tracer = Tracer()
    return _global_tracer


def reset_global_tracer(
    token_budget: int = 20000,
    output_budget: int = 6000,
) -> Tracer:
    """重置全局 Tracer（每次 query 开始时调用）。"""
    global _global_tracer
    _global_tracer = Tracer(
        token_budget=token_budget,
        output_budget=output_budget,
    )
    return _global_tracer
