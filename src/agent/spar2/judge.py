"""LLM 批量相关性判分器（SPAR similarity_code_v4 的批量版）。"""

from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List

PARSE_FAILURES = 0
_DEBUG_DUMPED = 0

_PROMPT = """Rate each paper's relevance to the query (0-1), scoring three dimensions:
- Topic match: how directly the paper's topic addresses the query's subject
- Method relevance: whether the method/approach matches what the query asks about
- Intent coverage: how much of the query's multi-part intent the paper covers

Final score = weighted judgment across the three dimensions. Guidelines:
- 0.9-1.0: Direct answer to the query on all core aspects
- 0.6-0.8: Highly relevant, covers core aspects
- 0.4-0.5: Partially related, covers some aspects
- 0.2-0.3: Same broad area, tangential
- 0.0-0.1: Irrelevant

Query: {q_short}
Papers:
{papers}

Output: One score per line (paper order preserved), nothing else. Max 2 decimal places."""

_LEX_STOP = {
    "the", "a", "an", "of", "on", "in", "and", "or", "is", "are", "to", "for",
    "that", "this", "with", "from", "by", "at", "as", "was", "were", "be",
    "been", "has", "have", "had", "do", "does", "did", "which", "what", "how",
    "why", "who", "whose", "using", "used", "use", "papers", "paper", "works",
    "work", "studies", "study", "show", "showed", "explored", "explore",
    "within", "realm", "area", "related", "similar", "find", "give", "me",
    "can", "could", "would", "should", "their", "they", "them", "these",
    "those", "some", "many", "more", "most", "than", "into", "over", "under",
}


def _tokens(text: str):
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(t) > 2 and t not in _LEX_STOP}


def lexical_score(query: str, doc: dict) -> float:
    qt = _tokens(query)
    if not qt:
        return 0.0
    dt = _tokens(doc.get("title", "")) | _tokens(doc.get("abstract", ""))
    if not dt:
        return 0.0
    return len(qt & dt) / len(qt)


def _parse_scores(text: str, n: int) -> List[float] | None:
    text = (text or "").strip()
    # 行式解析：每行一个数字（鲁棒，容忍多余文本）
    nums = [float(x) for x in re.findall(r"\b0(?:\.\d+)?\b|\b1(?:\.0+)?\b", text)]
    if len(nums) >= n:
        return [max(0.0, min(1.0, x)) for x in nums[:n]]
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        scores = data.get("scores")
        if not isinstance(scores, list) or len(scores) != n:
            return None
        return [max(0.0, min(1.0, float(s))) for s in scores]
    except Exception:
        return None


def judge_docs(query: str, docs: List[dict], llm_chat: Callable,
               batch_size: int = 12, deadline: float | None = None,
               max_workers: int = 4,
               call_timeout: float | None = None) -> List[float]:
    """批量判分；LLM 失败或超 deadline 时降级为词法分。

    deadline：绝对时间戳（time.monotonic() 刻度），用于慢速本地模型
    在判分过程中也能按硬超时截断，避免单次判分拖垮整条流水线。
    返回与 docs 等长的分数列表。
    """
    scores: List[float] = []
    batches = list(range(0, len(docs), batch_size))

    def _judge_batch(start: int) -> List[float]:
        if deadline is not None and time.monotonic() >= deadline:
            return [lexical_score(query, d) for d in docs[start:start + batch_size]]
        batch = docs[start:start + batch_size]
        lines = []
        for i, d in enumerate(batch):
            title = (d.get("title") or "").strip()
            abstract = (d.get("abstract") or "").strip()[:600]
            lines.append(f"[{i}] Title: {title}\nAbstract: {abstract}".strip())
        query_short = query.strip()[:400]
        prompt = _PROMPT.format(q=query.strip(), q_short=query_short, papers="\n\n".join(lines))
        from agent.spar2.llm_guard import bounded_call
        resp = bounded_call(llm_chat, prompt, max_tokens=max(60,len(batch)*12), timeout=call_timeout, timeout_seconds=call_timeout or 30)
        if resp is None:
            # LLM 超时：直接词法兜底，不重试（避免慢调用拖爆 deadline）
            return [lexical_score(query, d) for d in batch]
        parsed = _parse_scores(resp, len(batch))
        if parsed is not None:
            return parsed
        global _DEBUG_DUMPED
        if os.getenv("SAKURA_JUDGE_DEBUG", "0") == "1" and _DEBUG_DUMPED < 3:
            _DEBUG_DUMPED += 1
            try:
                with open(f"/tmp/judge_fail_{_DEBUG_DUMPED}.txt", "w", encoding="utf-8") as f:
                    f.write(f"PROMPT_LEN={len(prompt)}\nRESP={repr(resp)[:3000]}\n")
            except Exception:
                pass
        # 解析失败：重试一次
        global PARSE_FAILURES
        PARSE_FAILURES += 1
        resp2 = bounded_call(llm_chat, prompt, max_tokens=max(60,len(batch)*12), timeout=call_timeout, timeout_seconds=call_timeout or 30)
        if resp2 is None:
            return [lexical_score(query, d) for d in batch]
        parsed2 = _parse_scores(resp2, len(batch))
        if parsed2 is not None:
            return parsed2
        PARSE_FAILURES += 1
        return [lexical_score(query, d) for d in batch]

    # 按波提交：每波最多 max_workers 个批次并行；一波结束后检查 deadline，
    # 超时则剩余批次直接转词法分（避免晚提交的批次把整条流水线拖爆）
    wave = max_workers
    for w0 in range(0, len(batches), wave):
        if deadline is not None and time.monotonic() >= deadline:
            for s in batches[w0:]:
                scores.extend(lexical_score(query, d)
                              for d in docs[s:s + batch_size])
            break
        wave_batches = batches[w0:w0 + wave]
        with ThreadPoolExecutor(max_workers=len(wave_batches)) as pool:
            ordered = {s: None for s in wave_batches}
            futures = {pool.submit(_judge_batch, s): s for s in wave_batches}
            for fut in as_completed(futures):
                ordered[futures[fut]] = fut.result()
        for s in wave_batches:
            scores.extend(ordered[s])
    return scores
