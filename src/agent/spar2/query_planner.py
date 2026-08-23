"""QueryPlanner：把自然语言查询规划成判别性技术关键词（短短语，适配词法引擎）。"""

from __future__ import annotations

import json
import re
from typing import Callable, Dict, List

_PROMPT = '''Academic search planner: Extract search terms from research query.

Format: {{"keywords": ["keyword1", "keyword2"], "queries": ["query1", "query2"]}}

Rules:
- keywords: 8-10 technical terms/phrases (2-5 words) from the RESEARCH AREA,
  including standard terminology and common synonyms of the underlying concepts
  (e.g. "data pruning", "data selection", "deduplication", "data-efficient training")
- queries: 6-8 search phrases (5-10 words); EACH query must contain at least one
  specific technical term above, and queries must cover DIFFERENT sub-topics/methods
- Do NOT just paraphrase the question; extract the technical concepts it implies
- Avoid generics ("papers", "show", "give", "study", "using")

Query: {q}'''


# 无 LLM 兜底用停用词（疑问词/元词/连接词）
_FALLBACK_STOP = {
    "give", "me", "papers", "paper", "show", "shows", "shown", "using", "use",
    "used", "find", "finding", "list", "share", "shares", "shared", "insights",
    "insight", "about", "which", "what", "how", "why", "who", "whose", "where",
    "that", "this", "these", "those", "there", "their", "them", "they", "are",
    "can", "could", "would", "should", "does", "did", "have", "has", "had",
    "with", "without", "from", "into", "onto", "over", "under", "than", "then",
    "the", "a", "an", "of", "on", "in", "and", "or", "to", "for", "by", "at",
    "as", "is", "was", "were", "be", "been", "result", "results",
    "more", "most", "new", "recent", "related", "similar", "some", "any",
    "all", "paper", "papers", "benchmark", "benchmarks",
}


def _clean_tokens(text: str) -> List[str]:
    """查询清洗：小写、去标点/停用词，保留判别性技术词。"""
    raw = re.findall(r"[a-z0-9][a-z0-9\-\.\+]*", (text or "").lower())
    return [t for t in raw if len(t) > 2 and t not in _FALLBACK_STOP]


def _fallback_phrases(query: str, tokens: List[str]) -> List[str]:
    """无 LLM 时生成词法检索短语（原文清洗版 + 判别词组合）。"""
    cleaned = " ".join(tokens)
    out: List[str] = []
    if cleaned:
        out.append(cleaned)
    if len(tokens) >= 2:
        out.append(" ".join(tokens[:2]))
    if len(tokens) >= 4:
        out.append(" ".join(tokens[2:4]))
    if len(tokens) >= 6:
        out.append(" ".join(tokens[4:6]))
    return out


def extract_keywords_fallback(query: str) -> Dict:
    """纯规则判别词提取（LLM 不可用时保底，也并入 LLM 结果扩大召回）。"""
    tokens = _clean_tokens(query)
    keywords = list(dict.fromkeys(tokens))[:10]
    # 常见构词：把相邻判别词组成 2-3 词短语当关键词
    if len(tokens) >= 2:
        joined = " ".join(tokens[:4])
        if joined not in keywords:
            keywords.append(joined[:60])
    phrases = _fallback_phrases(query, tokens)
    return {"keywords": keywords, "queries": phrases}


def _bigrams_from_queries(queries: List[str], max_n: int = 8) -> List[str]:
    """从查询短语中提取判别性 bigram 关键词（如 "data pruning improves ..." → "data pruning"）。"""
    out: List[str] = []
    for q in queries:
        words = [t for t in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", (q or "").lower())
                 if len(t) > 2 and t not in _FALLBACK_STOP]
        for i in range(len(words) - 1):
            bg = f"{words[i]} {words[i+1]}"
            if bg not in out:
                out.append(bg)
        if len(out) >= max_n:
            break
    return out[:max_n]


def _parse_json_response(text: str) -> Dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"```$", "", text)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


def plan_query(query: str, llm_chat: Callable,
               double_pass: bool = True) -> Dict:
    """返回 {"keywords": [...], "queries": [...]}；LLM 失败/输出差时用规则兜底，
    并把规则词并入 LLM 输出（扩大召回、提高对弱模型的鲁棒性）。"""
    prompt = _PROMPT.format(q=query.strip())
    resp1 = llm_chat(prompt, max_tokens=2000)
    data1 = _parse_json_response(resp1 or "")
    llm_kw = [str(k).strip() for k in (data1.get("keywords") or []) if str(k).strip()]
    llm_q = [str(qq).strip() for qq in (data1.get("queries") or []) if str(qq).strip()]
    # 双规划合并：第二次调用取并集，降低单次规划波动（关键词/短语差异）
    resp2 = None
    if double_pass and (llm_kw or llm_q):
        resp2 = llm_chat(prompt, max_tokens=2000)
        data2 = _parse_json_response(resp2 or "")
        llm_kw += [str(k).strip() for k in (data2.get("keywords") or []) if str(k).strip()]
        llm_q += [str(qq).strip() for qq in (data2.get("queries") or []) if str(qq).strip()]
    llm_kw = list(dict.fromkeys(llm_kw))[:12]
    llm_q = list(dict.fromkeys(llm_q))[:12]
    fb = extract_keywords_fallback(query)
    # LLM 技术词优先 → 查询短语 bigram → 规则兜底词填底：
    # 兜底词若排前会挤掉 LLM 的判别词（如 "data pruning"）
    bigrams = _bigrams_from_queries(llm_q)
    keywords = list(dict.fromkeys(llm_kw + bigrams + fb["keywords"]))[:14]
    queries = list(dict.fromkeys(llm_q + fb["queries"]))[:10]
    return {"keywords": keywords, "queries": queries,
            "llm_raw": [resp1, resp2] if resp2 else resp1,
            "plan_calls": 2 if resp2 else 1,
            "fallback_used": not llm_kw}


# ------------------------------------------------------------------ #
# 文档驱动查询生成（迭代搜索第二轮用）
# ------------------------------------------------------------------ #
_DOC_QUERY_PROMPT = '''Generate related search queries based on found papers.

Original Query: {q}

Found Papers (titles + abstracts):
{doc_summaries}

Generate 4-5 new search queries (5-8 words each) that:
- Use DIFFERENT terms from original query
- Cover related methods/topics from papers above
- Prefer concrete technical terminology (method names, standard concepts)
- Are "paper title style" phrases
- Include technical terms for academic search

Format: {{"queries": ["q1", "q2", "q3"]}}
Avoid repeating original query.'''


def generate_queries_from_docs(query: str, top_docs: List[dict],
                               llm_chat: Callable) -> List[str]:
    """根据已找到的高分论文生成新的搜索查询（迭代搜索第二轮用）。
    失败返回空列表（不影响流程）。"""
    if not top_docs:
        return []
    summaries = []
    for i, d in enumerate(top_docs[:5]):
        title = (d.get("title") or "").strip()
        abstract = (d.get("abstract") or "").strip()[:200]
        summaries.append(f"[{i+1}] {title}\n{abstract}")
    prompt = _DOC_QUERY_PROMPT.format(
        q=query.strip(),
        doc_summaries="\n\n".join(summaries),
    )
    try:
        resp = llm_chat(prompt, max_tokens=500)  # Reduced token usage
        data = _parse_json_response(resp or "")
        queries = data.get("queries") or []
        queries = [str(qq).strip() for qq in queries if str(qq).strip()]
        queries = list(dict.fromkeys(queries))[:4]  # Reduced from 5 to 4
        return queries
    except Exception:
        return []
