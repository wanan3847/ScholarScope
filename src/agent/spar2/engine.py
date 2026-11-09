"""SPAR2Engine：SPAR 架构（查询理解→多源检索→LLM判分→RefChain→排序）的落地实现。"""

from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Callable, Dict, List

import requests

from agent.spar2 import crawler_selector as cs_mod
from agent.spar2 import expand as expand_mod
from agent.spar2 import judge as judge_mod
from agent.spar2 import llm as llm_mod
from agent.spar2 import query_planner
from agent.spar2 import retrievers
from agent import graph_synthesizer as graph_synth
from agent.spar2.normalize import merge_candidates


# SPAR2 引擎常驻机制（Web 创新面板 / stats 展示用）。
SPAR2_FEATURES = {
    "spar2_bfs_iterative": "迭代检索（最多 2+ 轮 BFS）",
    "spar2_doc_query": "文档驱动查询生成",
    "spar2_refchain_bi": "RefChain 双向引文扩展（引用+被引）",
    "spar2_bge_prescreen": "BGE 语义预筛 + 语义保底",
    "spar2_multi_channel": "多通道检索（arXiv/OpenAlex/CrossRef/本地）",
    "spar2_deadline_filter": "评测截止日期过滤",
}

_RERANK_PROMPT = """Rank the following papers by relevance to the query.
Query: {q}

Papers:
{papers}

Output the numbers of the {out} most relevant papers, one number per line,
most relevant first. Numbers only, no explanations."""


class _CountingChat:
    """包装 LLM 调用，统计次数与 token。"""

    def __init__(self, chat: Callable):
        self._chat = chat
        self.calls = 0
        self.tokens = 0

    def __call__(self, prompt: str, **kw) -> str | None:
        self.calls += 1
        self.tokens += llm_mod.estimate_tokens(prompt)
        return self._chat(prompt, **kw)


def _enrich_abstracts(docs: List[dict]) -> None:
    """从 OpenAlex 批量获取缺失摘要（单次 API 调用，提升 LLM 判分质量）。
    同时支持 openalex_id / arxiv_id / doi 查询。"""
    need_oa = []
    need_arxiv = []
    need_doi = []
    for d in docs:
        if (d.get("abstract") or "").strip():
            continue
        if d.get("openalex_id"):
            need_oa.append(d)
        elif d.get("arxiv_id"):
            need_arxiv.append(d)
        elif d.get("doi"):
            need_doi.append(d)
        if len(need_oa) + len(need_arxiv) + len(need_doi) >= 60:
            break
    if not need_oa and not need_arxiv and not need_doi:
        return
    # 构建 filter 参数
    filters = []
    if need_oa:
        oa_ids = "|".join(d["openalex_id"].split("/")[-1] for d in need_oa)
        filters.append("openalex:" + oa_ids)
    if need_arxiv:
        arxiv_ids = "|".join(f"arxiv:{d['arxiv_id']}" for d in need_arxiv)
        filters.append(arxiv_ids)
    if need_doi:
        doi_ids = "|".join(f"doi:{d['doi']}" for d in need_doi)
        filters.append(doi_ids)
    if not filters:
        return
    try:
        import os as _os
        params: dict = {
            "filter": ",".join(filters),
            "per_page": max(50, len(need_oa) + len(need_arxiv) + len(need_doi)),
            "select": "ids,abstract_inverted_index",
        }
        key = _os.getenv("OPENALEX_API_KEY", "")
        email = _os.getenv("OPENALEX_EMAIL", "")
        if key:
            params["api_key"] = key
        elif email:
            params["mailto"] = email
        resp = requests.get("https://api.openalex.org/works", params=params, timeout=15)
        if resp.status_code != 200:
            return
        # 构建 arxiv_id -> abstract / openalex_id -> abstract / doi -> abstract 映射
        arxiv_map: Dict[str, str] = {}
        oa_map: Dict[str, str] = {}
        doi_map: Dict[str, str] = {}
        for w in resp.json().get("results", []):
            ext_ids = w.get("ids") or {}
            abstract_raw = w.get("abstract_inverted_index")
            abstract = ""
            if isinstance(abstract_raw, dict):
                pos = []
                for word, idxs in abstract_raw.items():
                    for i in idxs:
                        pos.append((i, word))
                pos.sort()
                abstract = " ".join(wd for _, wd in pos)
            if not abstract:
                continue
            arxiv_raw = ext_ids.get("arxiv", "")
            if arxiv_raw:
                aid = str(arxiv_raw).split("/")[-1].split("v")[0]
                arxiv_map[aid] = abstract
            oa_id = ext_ids.get("openalex", "")
            if oa_id:
                oa_map[oa_id.split("/")[-1]] = abstract
            doi_raw = ext_ids.get("doi", "")
            if doi_raw:
                doi_map[str(doi_raw).replace("https://doi.org/", "").lower()] = abstract
        # 回填摘要
        for d in need_oa:
            oa_key = d["openalex_id"].split("/")[-1]
            if oa_key in oa_map:
                d["abstract"] = oa_map[oa_key]
        for d in need_arxiv:
            aid = d["arxiv_id"].split("v")[0]
            if aid in arxiv_map:
                d["abstract"] = arxiv_map[aid]
        for d in need_doi:
            doi_key = d["doi"].lower()
            if doi_key in doi_map:
                d["abstract"] = doi_map[doi_key]
    except Exception:
        pass


class SPAR2Engine:
    """SPAR2 端到端引擎；接口与 EvaluationRunner 兼容（run(query, before_date)）。"""

    def __init__(self, llm_chat: Callable | None = None,
                 max_output: int = 20, judge_threshold: float = 0.25,
                 max_judge: int = 250, local_top_k: int = 800,
                 deadline_seconds: float = 170.0, max_rounds: int = 3,
                 llm_timeout_seconds: float | None = None):
        # 兼容 BaseLLM（带 .chat(messages, **kw)）与裸 prompt 函数两种接口
        self.local_mode = False
        if llm_chat is not None and hasattr(llm_chat, "chat"):
            base = llm_chat
            ep = getattr(base, "ep", None)
            if ep and "11434" in (getattr(ep, "base_url", "") or ""):
                self.local_mode = True  # 本地 ollama：判分批次更小、权重更偏 BGE
            def _prompt_chat(prompt: str, **kw):
                from llm.base import LLMMessage
                return base.chat([LLMMessage(role="user", content=prompt)], **kw)
            self._llm: Callable = _prompt_chat
        else:
            self._llm = llm_chat or llm_mod.chat
        self.judge_batch_size = 6 if self.local_mode else 12
        self.llm_timeout_seconds = float(
            llm_timeout_seconds if llm_timeout_seconds is not None
            else (12 if self.local_mode else os.getenv("SAKURA_LLM_CALL_TIMEOUT", "30")))
        self.max_output = max_output
        self.judge_threshold = judge_threshold
        self.max_judge = max_judge
        self.local_top_k = local_top_k
        self.deadline_seconds = float(os.getenv("SPAR2_DEADLINE", str(deadline_seconds)))
        self.max_rounds = int(os.getenv("SPAR2_MAX_ROUNDS", str(max_rounds)))
        
        # 为节省token而调整参数，但仍需保证一定召回
        # 如果设置了节省token模式，则适当调整参数以平衡召回和token消耗
        if os.getenv("SPAR2_TOKEN_SAVING", "0") == "1":
            # 降低判断阈值以提高召回，补偿token节省带来的精度损失
            self.judge_threshold = max(0.15, judge_threshold * 0.8)
            self.max_judge = min(300, max_judge * 1.2)  # 适度增加判断数量以补偿低阈值

    def run(self, query: str, before_date: str = "") -> Dict:
        t0 = time.time()
        # judge_docs 用 time.monotonic() 比较 deadline，必须用单调时钟
        deadline_abs = time.monotonic() + self.deadline_seconds
        judge_mod.PARSE_FAILURES = 0
        counter = _CountingChat(self._llm)
        retrieval_calls = 0
        from agent.research_intent import matches,year_bounds
        research_query=getattr(self,"research_query",None) or query

        def _over_deadline() -> bool:
            return time.time() - t0 > self.deadline_seconds

        # 1) 查询规划（1 次 LLM）
        plan = query_planner.plan_query(query, counter,
                                        double_pass=not self.local_mode,
                                        timeout=self.llm_timeout_seconds)
        keywords = plan.get("keywords") or []
        phrases = plan.get("queries") or []
        start_year,end_year=year_bounds(research_query,getattr(self,"year_from",0),int(before_date[:4]) if before_date else 0)
        if not before_date and end_year:before_date=f"{end_year}1231"
        def eligible(doc):
            if not matches(research_query,doc):return False
            if not start_year and not end_year:return True
            try:year=int(str(doc.get("year") or 0)[:4])
            except (ValueError,TypeError):return False
            return bool(year and (not start_year or year>=start_year) and (not end_year or year<=end_year))

        # ==============================================================
        # 迭代搜索循环（最多 2 轮：第一轮原始查询，第二轮文档驱动查询）
        # ==============================================================
        all_docs: List[dict] = []  # 累积候选池（跨轮合并）
        all_docs_map: Dict[str, dict] = {}  # key -> doc 去重
        total_judged = 0
        round_queries_log = list(phrases)  # 记录所有轮次的查询

        for search_round in range(self.max_rounds):
            if _over_deadline():
                break

            if search_round == 0:
                # --- Round 1: 核心通道检索（并行执行，大幅缩短等待）---
                r1_keywords, r1_phrases = keywords, phrases
                
                # 各源共用墙上时钟预算，单源失败不阻塞其他真实结果。
                _RETRIEVAL_TIMEOUT = min(40,max(1,self.deadline_seconds-(time.time()-t0)))
                _retrieval_deadline = time.time() + _RETRIEVAL_TIMEOUT
                pool = ThreadPoolExecutor(max_workers=7)
                try:
                    f_arxiv = pool.submit(retrievers.search_arxiv,
                                          r1_keywords, r1_phrases, end_date=before_date,start_year=start_year)
                    f_openalex = pool.submit(retrievers.search_openalex,
                                             r1_keywords, r1_phrases, end_date=before_date,start_year=start_year or None)
                    f_local = pool.submit(retrievers.search_local,
                                          query, self.local_top_k)
                    f_crossref = pool.submit(retrievers.search_crossref,
                                             r1_keywords[:3], r1_phrases[:3],start_year=start_year,end_date=before_date)
                    f_s2 = pool.submit(retrievers.search_semantic_scholar,
                                       r1_keywords, r1_phrases)
                    f_epmc = pool.submit(retrievers.search_europe_pmc,
                                         r1_keywords, r1_phrases, end_date=before_date)
                    f_scopus = pool.submit(retrievers.search_scopus,
                                           r1_keywords, r1_phrases)
                    
                    def _safe_result(future, default=None):
                        try:
                            # 共用同一墙上时钟：5 个通道并行，总等待不超过 _RETRIEVAL_TIMEOUT
                            remaining = max(0.0, _retrieval_deadline - time.time())
                            return future.result(timeout=remaining)
                        except (FutureTimeout, Exception):
                            return default or []
                    
                    arxiv_results = _safe_result(f_arxiv)
                    openalex_results = _safe_result(f_openalex)
                    local_results = _safe_result(f_local)
                    crossref_results = _safe_result(f_crossref)
                    s2_results = _safe_result(f_s2)
                    epmc_results = _safe_result(f_epmc)
                    scopus_results = _safe_result(f_scopus)
                finally:
                    pool.shutdown(wait=False)  # 不等慢通道，40s 硬超时真正生效
                retrieval_calls += 7
                
                # 没有来源返回真实论文时保留空候选；不构造占位文献。
                new_channels = [arxiv_results, openalex_results, local_results,
                                crossref_results, s2_results, epmc_results, scopus_results]
            else:
                # 剩余时间不足 30s 时跳过第二轮（web 模式 85s 内必须返回）
                if self.deadline_seconds - (time.time() - t0) < 30:
                    break
                # --- Round 2+: 文档驱动查询 ---
                # 即使没有高度相关文档也要继续搜索，避免过早终止
                if self.local_mode:
                    # 本地模型判分区分度低：按 BGE 语义分选种子（更可靠的信号）
                    top_relevant = sorted([d for d in all_docs if eligible(d)],
                                          key=lambda d: (d.get("_sem") or 0.0),
                                          reverse=True)[:5]
                else:
                    top_relevant = [d for d in all_docs
                                    if d.get("judged")
                                    and eligible(d)
                                    and d.get("score", 0) >= self.judge_threshold]
                    top_relevant.sort(key=lambda d: (d.get("_final") or 0.0,
                                                     d.get("_sem") or 0.0),
                                      reverse=True)
                    top_relevant = top_relevant[:5]
                
                # 如果没有找到高度相关文档，使用预筛选的文档作为种子
                if not top_relevant:
                    # 使用预筛选得分最高的文档作为种子
                    pre_ranked = [d for d in all_docs if not d.get("judged") and eligible(d)]
                    pre_ranked.sort(key=lambda x: x.get("_pre", 0.0), reverse=True)
                    top_relevant = pre_ranked[:3]
                    
                # 如果仍然没有相关文档，基于原始查询扩展新查询
                if not top_relevant:
                    # 使用原始查询的变体继续搜索
                    doc_queries = query_planner.focused_research_queries(research_query)[search_round:search_round+3] or [query]
                else:
                    doc_queries = query_planner.generate_queries_from_docs(
                        research_query, top_relevant, counter,
                        timeout=min(self.llm_timeout_seconds,max(.1,deadline_abs-time.monotonic()-15)))
                    if not doc_queries:
                        # 如果无法从文档生成查询，使用原始查询的变体
                        doc_queries = query_planner.focused_research_queries(research_query)[search_round:search_round+3] or [query]
                # 已找到论文标题的判别词（零成本确定性补充，弥补弱模型词汇不足）
                title_terms = retrievers.extract_title_terms(top_relevant)
                round_queries_log.extend(doc_queries)
                doc_kws = list(doc_queries) + title_terms
                # Start the wait window after query generation, not before it.
                _retrieval_deadline=min(t0+self.deadline_seconds,time.time()+28)
                if search_round == 1:
                    # 第二轮同样并行 + 硬超时（arXiv 查询多，同步跑可能拖死 deadline）
                    pool = ThreadPoolExecutor(max_workers=3)
                    try:
                        f_arxiv = pool.submit(retrievers.search_arxiv,
                                              doc_kws, doc_queries, end_date=before_date,start_year=start_year)
                        f_openalex = pool.submit(retrievers.search_openalex,
                                                 doc_kws, doc_queries, end_date=before_date,start_year=start_year)
                        f_local = pool.submit(retrievers.search_local,
                                              " ".join(doc_queries), self.local_top_k)
                        new_channels = [_safe_result(f) for f in (f_arxiv, f_openalex, f_local)]
                    finally:
                        pool.shutdown(wait=False)
                    retrieval_calls += 3
                else:
                    # Round 3+: 只走 arXiv + 本地
                    pool = ThreadPoolExecutor(max_workers=2)
                    try:
                        f_arxiv = pool.submit(retrievers.search_arxiv,
                                              doc_kws, doc_queries, end_date=before_date,start_year=start_year)
                        f_local = pool.submit(retrievers.search_local,
                                              " ".join(doc_queries), self.local_top_k)
                        new_channels = [_safe_result(f) for f in (f_arxiv, f_local)]
                    finally:
                        pool.shutdown(wait=False)
                    retrieval_calls += 2

            # --- 合并新检索结果到全局候选池 ---
            new_merged = merge_candidates(new_channels)
            new_docs = []
            for k, d in new_merged.items():
                if start_year:
                    try:
                        if int(str(d.get("year") or 0)[:4])<start_year:continue
                    except (ValueError,TypeError):continue
                if k not in all_docs_map:
                    all_docs_map[k] = d
                    new_docs.append(d)

            if not new_docs and search_round > 0:
                break  # 第二轮没有新候选，退出

            all_docs.extend(new_docs)

            # --- 预筛 + 语义排序（仅对新论文计算 BGE） ---
            for d in new_docs:
                d["_lex"] = judge_mod.lexical_score(research_query, d)
            if new_docs:
                new_sem_texts = [
                    f"{d.get('title') or ''}. {(d.get('abstract') or '')[:400]}".strip()
                    for d in new_docs
                ]
                new_sem_scores = retrievers.semantic_scores(research_query, new_sem_texts)
            else:
                new_sem_scores = []
            for d, s in zip(new_docs, new_sem_scores):
                d["_sem"] = s
                d["_pre"] = 0.75*s + 0.25*d["_lex"]

            # --- 选出本轮待判分论文（按 _pre 排序 + 语义保底） ---
            unjudged = [d for d in all_docs if not d.get("judged")]
            unjudged.sort(key=lambda d: d.get("_pre", 0.0), reverse=True)
            # 第一轮少判一些（留时间给第二轮），后续轮次多判
            # 本地模式：把判分预算让给第二轮（文档驱动查询补词汇），
            # 第一轮少判一些，保证第二轮在 deadline 内能跑
            round_cap = (120 if self.local_mode else 200) if search_round > 0 \
                else (90 if self.local_mode else 170)
            round_budget = int(min(self.max_judge, round_cap))
            shortlist = unjudged[: round_budget]
            # 语义保底 - 更宽松的阈值以提高召回
            shortlist_keys = {d.get("arxiv_id") or d.get("doi") or "title:" + str(d.get("title") or "").lower()
                             for d in shortlist}
            # 降低语义阈值以提高召回，增加保底数量
            sem_floor_cap = 12 if self.local_mode else 60
            sem_floor = [d for d in unjudged if d not in shortlist
                         and (d.get("_sem") or 0) >= 0.40][:sem_floor_cap]
            for d in sem_floor:
                k = d.get("arxiv_id") or d.get("doi") or "title:" + str(d.get("title") or "").lower()
                if k not in shortlist_keys:
                    shortlist.append(d)
                    shortlist_keys.add(k)

            # --- 摘要补全：从 OpenAlex 批量获取缺失摘要（提升 LLM 判分质量） ---
            from agent.spar2.llm_guard import bounded_call
            direct=[d for d in unjudged if eligible(d)]
            missing=[d for d in unjudged if not d.get("abstract") and d not in direct]
            shortlist=(direct+missing)[:round_budget]
            bounded_call(_enrich_abstracts, shortlist, timeout=min(5.0, self.llm_timeout_seconds))
            retrieval_calls += 1
            # Eligible studies must not be crowded out of the finite judge/output
            # budgets by high lexical scores on an unrelated research task.
            direct=[d for d in all_docs if not d.get("judged") and eligible(d)]
            shortlist=sorted(direct,key=lambda d:d.get("_pre",0),reverse=True)[:round_budget]

            # --- LLM 批量判分 ---
            if shortlist and not _over_deadline():
                scores = judge_mod.judge_docs(
                    research_query, shortlist, counter,
                    batch_size=self.judge_batch_size, deadline=deadline_abs,
                    max_workers=1 if self.local_mode else 4,
                    call_timeout=self.llm_timeout_seconds)
                for d, s in zip(shortlist, scores):
                    d["score"] = float(s)
                    d["judged"] = True
                total_judged += len(shortlist)

            # --- 检查是否足够（第一轮不退出，确保第二轮执行） ---
            if search_round > 0:
                relevant_count = len([d for d in all_docs
                                      if d.get("judged") and d["score"] >= self.judge_threshold])
                if relevant_count >= self.max_output:
                    break

        # ============================================================== 
        # 批量筛选补足：继续处理预算外的候选
        # ==============================================================
        if not _over_deadline():
            unjudged = [d for d in all_docs if not d.get("judged") and eligible(d)]
            unjudged.sort(key=lambda d: d.get("_pre", 0.0), reverse=True)
            # 分块补判：deadline 内尽量多判（快模型能多判数百篇），
            # 够 10 篇相关即停；每块 60
            topup_cap = 400 if not self.local_mode else 0
            for chunk_start in range(0, min(len(unjudged), topup_cap), 80):
                if _over_deadline():
                    break
                chunk = unjudged[chunk_start:chunk_start + 80]
                if not chunk:
                    break
                chunk_scores = judge_mod.judge_docs(
                    research_query, chunk, counter,
                    batch_size=self.judge_batch_size, deadline=deadline_abs,
                    max_workers=1 if self.local_mode else 4,
                    call_timeout=self.llm_timeout_seconds)
                for d, s in zip(chunk, chunk_scores):
                    d["score"] = float(s)
                    d["judged"] = True
                total_judged += len(chunk)
                relevant_now = [d for d in all_docs
                                if d.get("judged") and d["score"] >= self.judge_threshold]
                if len(relevant_now) >= self.max_output:
                    break

        # ============================================================== 
        # 汇总排序（BGE 语义分加权：高语义相似度的论文获得额外加分）
        # ==============================================================
        for d in all_docs:
            base = d.get("score", 0.0) if d.get("judged") else 0.0
            if self.local_mode:
                # 本地模型判分区分度低：最终分 6:4 融合 LLM 判分与 BGE 语义分
                d["_final"] = 0.60 * base + 0.40 * (d.get("_sem") or 0.0)
            else:
                d["_final"] = base + 0.15 * max((d.get("_sem") or 0) - 0.5, 0)
        relevant = [d for d in all_docs if eligible(d) and d.get("judged") and d["score"] >= self.judge_threshold]
        
        # 如果没有找到满足阈值的相关文档，但有已判断的文档，选择最高分的
        if not relevant and any(d.get("judged") for d in all_docs):
            all_judged = [d for d in all_docs if d.get("judged") and eligible(d)]
            all_judged.sort(key=lambda d: d.get("score", 0.0), reverse=True)
            relevant = all_judged[:self.max_output]
        elif not relevant and not any(d.get("judged") for d in all_docs):
            # 如果没有任何已判断的文档，使用语义分数排序
            relevant = sorted([d for d in all_docs if eligible(d)], key=lambda d: d.get("_final", 0.0), reverse=True)
        relevant.sort(key=lambda d: d.get("_final",0.0),reverse=True)

        # 6) RefChain 引用扩展（1 跳；API 模式对高分种子再扩 1 跳，共 2 跳）
        ref_rounds = 2 if not self.local_mode else 1
        for _round in range(ref_rounds):
            if _over_deadline():
                break
            seeds = [d for d in relevant
                     if not d.get("_ref_expanded")
                     and (d.get("score") or 0) >= (0.8 if _round > 0 else 0.0)][:6]
            if not seeds:
                break
            for d in seeds:
                d["_ref_expanded"] = True
            # 每轮 RefChain 只花掉剩余预算的一半，给判分/精排/输出留时间
            remaining = max(0.0, deadline_abs - time.monotonic())
            if remaining<2:break
            ref_deadline = min(deadline_abs,time.monotonic() + remaining / (ref_rounds - _round) * 0.8)
            ref_docs = expand_mod.expand_citations(
                seeds, max_seeds=6, refs_per_seed=25, end_date=before_date,
                deadline=ref_deadline)
            retrieval_calls += min(len(seeds), 6)
            if not ref_docs:
                continue
            merged2 = merge_candidates([relevant, ref_docs])
            existing_keys = {d2["arxiv_id"] or d2["doi"]
                             or "title:" + str(d2.get("title") or "").lower()
                             for d2 in relevant}
            ref_candidates = [d for k, d in merged2.items()
                              if not d.get("judged") and k not in existing_keys and eligible(d)]
            if not ref_candidates:
                continue
            ref_cap = 40 if self.local_mode else 100
            # 引文候选本地补算 BGE 语义分（零 token 成本），供最终排序融合
            try:
                ref_sem = retrievers.semantic_scores(
                    research_query,
                    [f"{d.get('title') or ''}. {(d.get('abstract') or '')[:400]}".strip()
                     for d in ref_candidates[:ref_cap]])
                for d, s in zip(ref_candidates[:ref_cap], ref_sem):
                    d["_sem"] = s
            except Exception:
                pass
            ref_scores = judge_mod.judge_docs(
                research_query, ref_candidates[:ref_cap], counter,
                batch_size=self.judge_batch_size, deadline=deadline_abs,
                max_workers=1 if self.local_mode else 4,
                call_timeout=self.llm_timeout_seconds)
            for d, s in zip(ref_candidates[:ref_cap], ref_scores):
                d["score"] = float(s)
                d["judged"] = True
            relevant = sorted(relevant + [d for d in ref_candidates[:ref_cap]
                                          if d["score"] >= self.judge_threshold],
                              key=lambda d: d["score"],
                              reverse=True)

        # 7) top-N 相对精排（仅 API 模式：强模型相对排序可靠；
        #    本地弱模型的相对排序不稳定，跳过并把时间还给筛选）
        if (not self.local_mode and len(relevant) > 10
                and not _over_deadline()):
            reranked = self._rerank_top_n(research_query, relevant[:30], counter,
                timeout=min(self.llm_timeout_seconds,max(.1,deadline_abs-time.monotonic())))
            if reranked:
                order = {id(d): i for i, d in enumerate(reranked)}
                relevant.sort(key=lambda d: (order.get(id(d), 999),
                                             -(d.get("_final") or 0.0)))

        # 8) 终排 + 输出（end_date 已在通道层过滤，这里再兜底）
        end = int(before_date[:4]) if before_date else 9999
        papers = []
        seen_titles: set = set()  # 标题去重（避免 CrossRef 等通道返回重复论文）
        for d in relevant:
            if start_year:
                try:
                    if int(str(d.get("year") or 0)[:4])<start_year:continue
                except (ValueError,TypeError):continue
            if end < 9999 and d.get("year"):
                try:
                    if int(str(d["year"])[:4]) > end:
                        continue
                except Exception:
                    pass
            title = (d.get("title") or "").strip()
            if not title and not d.get("arxiv_id") and not d.get("doi"):
                continue
            # 标题去重：同一标题的论文只保留一次
            title_key = title.lower()
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            # 构造论文 URL（优先用检索层提供的，否则根据 ID 推导）
            paper_url = d.get("url") or ""
            if not paper_url:
                if d.get("arxiv_id"):
                    paper_url = f"https://arxiv.org/abs/{d['arxiv_id']}"
                elif d.get("doi"):
                    paper_url = f"https://doi.org/{d['doi']}"
            papers.append({
                "title": title,
                "arxiv_id": d.get("arxiv_id") or "",
                "doi": d.get("doi") or "",
                "paper_id": d.get("paper_id") or d.get("doi") or d.get("arxiv_id") or "",
                "pdf_url": d.get("pdf_url") or "",
                "is_oa": bool(d.get("is_oa")),
                "pmcid": d.get("pmcid") or "",
                "openalex_id": d.get("openalex_id") or "",
                "ids": list(d.get("ids") or []),
                "score": round(float(d.get("score") or 0.0), 4),
                "abstract": d.get("abstract") or "",
                "authors": list(d.get("authors") or []),
                "venue": d.get("venue") or "",
                "url": paper_url,
                "sources": d.get("sources") or [],
                "year": d.get("year") or "",
                "source": ", ".join(d.get("sources") or []) or d.get("source") or "",
            })
            if len(papers) >= self.max_output:
                break

        elapsed = round(time.time() - t0, 2)
        # 诊断转储：SAKURA_CAND_DUMP=1 时把候选池写入 /tmp（定位召回/排序问题）
        if os.getenv("SAKURA_CAND_DUMP") == "1":
            try:
                import json as _json
                with open("/tmp/spar2_cands.json", "w", encoding="utf-8") as _f:
                    _json.dump([
                        {"title": d.get("title"), "arxiv_id": d.get("arxiv_id"),
                         "doi": d.get("doi"), "sem": round(d.get("_sem") or 0, 4),
                         "lex": round(d.get("_lex") or 0, 4),
                         "pre": round(d.get("_pre") or 0, 4),
                         "judged": bool(d.get("judged")),
                         "score": d.get("score"),
                         "final": round(d.get("_final") or 0, 4)}
                        for d in all_docs], _f, ensure_ascii=False)
            except Exception:
                pass
        relationships = graph_synth.similarity_edges(papers)
        stats = {
            "api_calls": counter.calls,
            "tokens": counter.tokens,
            "elapsed_seconds": elapsed,
            "engine": "spar2",
            "candidates": len(all_docs),
            "judged": total_judged,
            "judge_parse_failures": judge_mod.PARSE_FAILURES,
            "keywords": keywords,
            "queries": round_queries_log,
            "llm_mode": "real" if (self._llm is not llm_mod.chat or llm_mod._API_KEY) else "mock",
            "retrieval_calls": retrieval_calls,
            "backends_used": sorted({
                s for d in all_docs for s in (d.get("sources") or []) if s
            }),
            "innovations_used": list(SPAR2_FEATURES.keys()),
        }
        return {
            "papers": papers,
            "stats": stats,
            "table": _make_table(papers),
            "comparison": graph_synth.make_comparison_table(papers),
            "relationships": relationships,
            "cluster_summary": graph_synth.make_cluster_summary(papers),
            "summary": graph_synth.make_summary(
                query, papers, candidates=len(all_docs), judged=total_judged),
            "intent": {
                "intent": "complex_search",
                "rewritten_query": query,
                "keyword_query": " ".join(keywords),
                "sub_queries": [{"text": p, "intent": "semantic"} for p in phrases],
                "search_filters": {},
            },
            "engine": "spar2",
        }

    def sync_run(self, query: str, before_date: str = "") -> Dict:
        """同步入口：与 EvaluationRunner/run_eval 的调用契约一致。"""
        return self.run(query, before_date)

    def _rerank_top_n(self, query: str, docs: List[dict],
                      counter: "_CountingChat",
                      n: int = 30, out: int = 10, timeout: float | None = None) -> List[dict]:
        """LLM 相对精排：从 top-n 候选中挑出最相关 out 篇并按其顺序置顶。
        解析失败返回空列表（调用方保持原排序，不额外重试省 token）。"""
        docs = docs[:n]
        if len(docs) <= out:
            return []
        lines = [
            f"[{i+1}] Title: {(d.get('title') or '').strip()}\n"
            f"Abstract: {(d.get('abstract') or '').strip()[:400]}"
            for i, d in enumerate(docs)
        ]
        prompt = _RERANK_PROMPT.format(
            q=query.strip()[:400], papers="\n\n".join(lines), out=out)
        from agent.spar2.llm_guard import bounded_call
        budget=self.llm_timeout_seconds if timeout is None else timeout
        resp = bounded_call(counter,prompt,max_tokens=300,timeout=budget,timeout_seconds=budget)
        nums: List[int] = []
        for x in re.findall(r"\b\d{1,2}\b", resp or ""):
            v = int(x)
            if 1 <= v <= len(docs) and v not in nums:
                nums.append(v)
        if len(nums) < max(5, min(out, len(docs))):
            return []  # 解析失败，保持原排序
        selected = [docs[v - 1] for v in nums[:out]]
        selected_ids = {id(d) for d in selected}
        rest = [d for d in docs if id(d) not in selected_ids]
        return selected + rest


def _make_table(papers: List[Dict]) -> str:
    rows = ["| # | Title | ID | Score |", "|---:|------|----|-------|"]
    for i, p in enumerate(papers[:10], 1):
        title = (p.get("title") or "")[:80].replace("|", "/")
        pid = p.get("arxiv_id") or p.get("doi") or "-"
        rows.append(f"| {i} | {title} | {pid} | {p.get('score', 0)} |")
    return "\n".join(rows)
