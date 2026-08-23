"""Lightweight Crawler-Selector: PaSa-inspired but LLM-based to save tokens."""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Tuple

# Crawler prompt: generate search queries from user query
_CRAWLER_PROMPT = """Given a research query, generate 3-5 focused search queries that would find relevant papers.
Each query should be specific and use academic terminology.

User Query: {q}

Output format (one query per line):
query1
query2
query3
"""

# Selector prompt: binary relevance judgment (yes/no) with minimal context
_SELECTOR_PROMPT = """Is this paper relevant to the query? Answer YES or NO only.

Query: {q}
Paper Title: {title}

Answer:"""


def crawler_generate_queries(query: str, llm_chat: Callable) -> List[str]:
    """Generate 3-5 focused search queries using LLM."""
    prompt = _CRAWLER_PROMPT.format(q=query.strip())
    resp = llm_chat(prompt, max_tokens=200)
    if not resp:
        return []
    
    queries = [line.strip() for line in resp.split('\n') if line.strip()]
    # Filter empty and deduplicate
    seen = set()
    result = []
    for q in queries[:5]:
        q_clean = re.sub(r'^\d+[\.\)]\s*', '', q).strip()  # Remove numbering
        if q_clean and q_clean.lower() not in seen:
            seen.add(q_clean.lower())
            result.append(q_clean)
    return result


def selector_judge(query: str, title: str, llm_chat: Callable) -> bool:
    """Binary relevance judgment: YES/NO."""
    prompt = _SELECTOR_PROMPT.format(q=query.strip()[:200], title=title.strip()[:150])
    resp = llm_chat(prompt, max_tokens=10)
    if not resp:
        return False
    return 'YES' in resp.upper()[:10]


def crawl_and_select(
    query: str,
    initial_papers: List[Dict],
    llm_chat: Callable,
    search_fn: Callable[[List[str]], List[Dict]],
    max_iterations: int = 2,
    max_papers_per_iter: int = 30,
) -> List[Dict]:
    """
    Crawler-Selector loop:
    1. Crawler generates queries from current relevant papers
    2. Search with new queries
    3. Selector judges each new paper (binary YES/NO, cheap)
    4. Repeat
    
    Args:
        query: User query
        initial_papers: Initial retrieval results
        llm_chat: LLM function
        search_fn: Function that takes list of queries and returns papers
        max_iterations: Max crawl-select iterations
        max_papers_per_iter: Max papers to select per iteration
    
    Returns:
        List of selected relevant papers
    """
    selected = []
    seen_ids = set()
    
    # Initial selection
    for p in initial_papers[:max_papers_per_iter]:
        pid = p.get('arxiv_id') or p.get('doi') or p.get('title', '')
        if pid in seen_ids:
            continue
        seen_ids.add(pid)
        
        # Quick selector judgment (binary, ~10 tokens)
        if selector_judge(query, p.get('title', ''), llm_chat):
            selected.append(p)
    
    # Crawl-select iterations
    for iteration in range(max_iterations):
        if len(selected) >= 20:  # Enough papers
            break
        
        # Crawler: generate new queries from top relevant papers
        top_relevant = sorted(selected, key=lambda x: x.get('_score', 0), reverse=True)[:3]
        if not top_relevant:
            break
        
        # Build context for crawler
        context_titles = [p.get('title', '') for p in top_relevant]
        crawler_query = f"{query}\n\nRelevant papers found:\n" + "\n".join(f"- {t}" for t in context_titles)
        
        new_queries = crawler_generate_queries(crawler_query, llm_chat)
        if not new_queries:
            break
        
        # Search with new queries
        new_papers = search_fn(new_queries)
        
        # Selector: judge new papers
        for p in new_papers[:max_papers_per_iter]:
            pid = p.get('arxiv_id') or p.get('doi') or p.get('title', '')
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            
            if selector_judge(query, p.get('title', ''), llm_chat):
                p['_score'] = 1.0  # Binary score
                selected.append(p)
    
    return selected
