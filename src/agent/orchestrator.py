"""Simplified Orchestrator for SPAR2 integration."""

from __future__ import annotations

import asyncio
import copy
import logging
import time
import json
import re
from typing import Any, Dict, List, Optional

# Simplified orchestrator that only uses SPAR2
from agent.spar2.engine import SPAR2Engine, SPAR2_FEATURES


# SPAR2 引擎实际生效的核心机制（供 Web 创新模块面板展示）。
# 与旧 15 大创新模块的开关不同：这些机制在当前引擎中常驻开启。
DEFAULT_INNOVATION_FLAGS = {k: True for k in SPAR2_FEATURES}


class Orchestrator:
    """Simplified orchestrator that delegates to SPAR2 engine."""

    def __init__(self, llm_chat=None, max_output=20, judge_threshold=0.25,
                 max_judge=250, local_top_k=500, deadline_seconds=170.0,
                 max_rounds=3, llm_timeout_seconds=None, practical_limit=None, year_from=0, overall_budget_seconds=None,
                 research_query=None):
        # Let SPAR2 inspect the routed endpoint (especially local Ollama) so it
        # can apply the right batch sizes and per-call timeout.
        self.spar2 = SPAR2Engine(
            llm_chat=llm_chat,
            max_output=max_output,
            judge_threshold=judge_threshold,
            max_judge=max_judge,
            local_top_k=local_top_k,
            deadline_seconds=deadline_seconds,
            max_rounds=max_rounds,
            llm_timeout_seconds=llm_timeout_seconds,
        )
        self.practical_limit = max(1, min(int(practical_limit or max_output), 50))
        self.spar2.year_from=int(year_from or 0)
        self.research_query=research_query
        self.spar2.research_query=research_query
        self.overall_budget_seconds=overall_budget_seconds
        self.logger = logging.getLogger(__name__)

    async def run(self, query: str, before_date: str = "") -> Dict:
        """Run the orchestrator."""
        try:
            # SPAR2 performs query planning, multi-round retrieval and citation
            # expansion. Use its retrieved papers as evidence for a practical
            # final selection instead of exposing its internal relevance scores.
            started=time.monotonic()
            result = self.spar2.run(query, before_date)
            remaining=32 if self.overall_budget_seconds is None else max(0,self.overall_budget_seconds-(time.monotonic()-started))
            self._select_practical_papers(self.research_query or query, result, selection_timeout=min(32,remaining))
            return result
        except Exception:
            self.logger.error("Orchestrator unavailable; returning actual empty results")
            # Fallback: return minimal result
            return {
                "query": query,
                "papers": [],
                "metrics": {"api_calls": 0, "tokens": 0, "latency": 0.0},
            }

    def _select_practical_papers(self, query: str, result: Dict, *, selection_timeout=32) -> None:
        from agent.research_intent import matches, constraints
        papers = result.get("papers") or []
        if not papers:
            result.setdefault("stats", {})["ranking_mode"] = "no_results"
            self._refresh_outputs(query, result)
            return
        candidates = [paper for paper in papers if matches(query, paper)
                      if not re.search(
                          r"(?:^|[^a-z])supp(?:lement(?:ary)?|\d+)|supporting information|\b(?:erratum|correction|retraction)\b",
                          str(paper.get("title") or ""), re.I)][:min(50, self.practical_limit + 10)]
        if not candidates:
            result["papers"] = []
            result.setdefault("stats", {})["ranking_mode"] = "no_results"
            result["stats"]["unmet_constraints"] = [label for label, _ in constraints(query)]
            self._refresh_outputs(query, result)
            return
        limit = min(self.practical_limit, len(candidates))
        if selection_timeout<1:
            self._practical_fallback(query,candidates,result)
            self._refresh_outputs(query,result)
            return
        lines = []
        for i, paper in enumerate(candidates, 1):
            lines.append(
                f"[{i}] {paper.get('title', '')}\n"
                f"Year: {paper.get('year', '')}; Venue: {paper.get('venue', '')}\n"
                f"Abstract: {(paper.get('abstract') or '')[:500]}"
            )
        prompt = (
            "You are the literature-search agent inside ScholarScope. Select papers "
            "that will help the researcher make progress on this request. Rank by "
            "direct usefulness: requested method or population, usable evidence, "
            "implementation or evaluation detail, and explicit constraints. Include "
            "a foundational or survey paper only when it helps answer the request. "
            "Do not rank by citations, venue prestige, popularity, or numeric relevance "
            "scores. Exclude tangential work and output only papers you recommend; "
            "leave rejected papers out of the array. Use only supplied title and abstract; "
            "never invent claims. If the abstract is absent, state only what the title "
            "supports; do not infer a survey, method detail or finding unless the title "
            "says so. Return JSON only as {\"papers\":[{\"index\":1,"
            "\"reason\":\"brief Chinese practical reason\",\"evidence\":\"exact "
            "short phrase from title or abstract\"}]}, up to " + str(limit)
            + " papers in usefulness order.\n\n"
            f"Research request: {query}\n\nRetrieved papers:\n" + "\n\n".join(lines)
        )
        try:
            from agent.spar2.engine import _CountingChat
            from agent.spar2.llm_guard import bounded_call
            counter = _CountingChat(self.spar2._llm)
            raw = bounded_call(counter, prompt, max_tokens=min(4800, 220 + limit * 120), timeout=selection_timeout, timeout_seconds=max(.1,selection_timeout-.5))
            metrics = result.setdefault("stats", {})
            metrics["api_calls"] = metrics.get("api_calls", 0) + counter.calls
            metrics["tokens"] = metrics.get("tokens", 0) + counter.tokens
            match = re.search(r"\{.*\}", raw or "", re.S)
            data = json.loads(match.group()) if match else {}
            entries = data.get("papers", []) if isinstance(data, dict) else []
            selected, seen = [], set()
            for item in entries:
                if not isinstance(item, dict):
                    continue
                index = item.get("index")
                if type(index) is not int or not 1 <= index <= len(candidates) or index in seen:
                    continue
                paper = candidates[index - 1]
                evidence = item.get("evidence")
                reason = item.get("reason")
                source_text = f"{paper.get('title', '')} {paper.get('abstract', '')}"
                if not isinstance(evidence, str) or len(evidence.strip()) < 5 or evidence.casefold() not in source_text.casefold():
                    continue
                if not isinstance(reason, str) or not reason.strip():
                    continue
                if re.search(r"无关|不相关|不符合|不推荐|应排除|无直接关联|irrelevant|unrelated|not relevant", reason, re.I):
                    continue
                if not paper.get("abstract"):
                    phrase = evidence.strip()
                    if len(phrase) > 70:
                        phrase = phrase[:70].rsplit(" ", 1)[0] or phrase[:70]
                    phrase = phrase.rstrip(" ,;:-")
                    reason = f"标题涉及“{phrase}”，与检索主题有关；目前缺少摘要，具体内容请以原文核对。"
                paper["recommendation_reason"] = reason.strip()[:240]
                paper["evidence"] = evidence.strip()[:280]
                paper["evidence_level"] = "abstract" if paper.get("abstract") else "title"
                paper.pop("score", None)
                selected.append(paper)
                seen.add(index)
            if selected:
                result["papers"] = selected
                metrics["ranking_mode"] = "practical_agent_selection"
            else:
                self._practical_fallback(query, candidates, result)
        except Exception:
            self.logger.warning("Practical selection unavailable; using source-text fallback")
            self._practical_fallback(query, candidates, result)
        self._refresh_outputs(query, result)

    def _practical_fallback(self, query: str, candidates: List[Dict], result: Dict) -> None:
        terms = result.get("stats", {}).get("keywords") or query.split()
        terms = [str(term).strip().casefold() for term in terms if str(term).strip()]
        ranked = []
        for order, paper in enumerate(candidates):
            title = str(paper.get("title") or "").casefold()
            abstract = str(paper.get("abstract") or "").casefold()
            title_matches = [term for term in terms if term in title]
            abstract_matches = [term for term in terms if term in abstract]
            ranked.append((len(title_matches) * 2 + len(abstract_matches), order,
                           paper, title_matches, abstract_matches))
        ranked.sort(key=lambda row: (-row[0], row[1]))
        if any(row[0] for row in ranked):
            ranked = [row for row in ranked if row[0]]
        papers = []
        for _, _, paper, title_matches, abstract_matches in ranked[:self.practical_limit]:
            paper.pop("score", None)
            matches = title_matches or abstract_matches
            if matches:
                phrase = ", ".join(matches[:4])
                paper["recommendation_reason"] = f"标题或摘要直接涉及检索主题词：{phrase}。"
                original = str(paper.get("abstract") or paper.get("title") or "")
                sentences = re.split(r"(?<=[.!?。！？])\s+", original)
                supported = sorted(sentences, key=lambda s: sum(term in s.casefold() for term in matches), reverse=True)
                paper["evidence"] = (supported[0] if supported else original)[:280]
            else:
                paper["recommendation_reason"] = "由多源检索与引文扩展召回；最终选择模型暂不可用，请先核对摘要。"
            paper["evidence_level"] = "abstract" if paper.get("abstract") else "title"
            papers.append(paper)
        result["papers"] = papers
        result.setdefault("stats", {})["ranking_mode"] = "agent_retrieval_fallback"

    @staticmethod
    def _refresh_outputs(query: str, result: Dict) -> None:
        try:
            from agent import graph_synthesizer
            papers = result.get("papers", [])
            from agent.research_intent import scope_notes
            for paper in papers:paper["scope_notes"] = scope_notes(query,paper)
            result["relationships"] = graph_synthesizer.similarity_edges(papers)
            result["cluster_summary"] = graph_synthesizer.make_cluster_summary(papers)
            result["summary"] = f"共整理 {len(papers)} 篇推荐文献，顺序依据研究用途与标题、摘要中的证据。"
            rows = ["| # | Title | Year | Source |", "|---:|------|-----:|--------|"]
            comparison = []
            for i, paper in enumerate(papers, 1):
                title = (paper.get("title") or "")[:100].replace("|", "/")
                source = paper.get("source") or ", ".join(paper.get("sources") or [])
                rows.append(f"| {i} | {title} | {paper.get('year') or '-'} | {source or '-'} |")
                comparison.append({
                    "rank": i, "title": paper.get("title", ""),
                    "id": paper.get("arxiv_id") or paper.get("doi") or "",
                    "year": paper.get("year") or "", "venue": paper.get("venue") or "",
                    "source": source, "recommendation_reason": paper.get("recommendation_reason", ""),
                })
            result["table"] = "\n".join(rows)
            result["comparison"] = comparison
        except Exception:
            result["relationships"] = []

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
