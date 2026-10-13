"""LLM 调用硬超时保护。

引擎的 deadline 无法掐断正在进行的 HTTP 请求（httpx 单次超时默认 180s），
慢 LLM 会把整条流水线拖爆。这里用线程 + result(timeout) 给单次 LLM 调用
加硬上限，超时返回 None，由调用方走兜底（词法分 / 规则查询）。
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional


def llm_call_timeout() -> float:
    return float(os.getenv("SAKURA_LLM_CALL_TIMEOUT", "30"))


def bounded_call(fn: Callable, *args: Any, timeout: Optional[float] = None,
                 **kwargs: Any) -> Optional[Any]:
    """在独立线程里调用 fn(*args, **kwargs)，超时返回 None（不等待线程收尾）。"""
    limit = timeout if timeout is not None else llm_call_timeout()
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        fut = pool.submit(fn, *args, **kwargs)
        try:
            return fut.result(timeout=limit)
        except Exception:
            return None
    finally:
        pool.shutdown(wait=False)
