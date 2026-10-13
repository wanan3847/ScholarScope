"""F1 底层优化回归测试：判分质量 + 候选上限 + 补判逻辑。"""

from __future__ import annotations

import inspect
import time

from agent.spar2 import judge as judge_mod
from agent.spar2 import query_planner
from agent.spar2 import retrievers
from agent.spar2.engine import SPAR2Engine
from agent.spar2.normalize import merge_candidates


def test_judge_prompt_is_three_dimension():
    assert "Topic match" in judge_mod._PROMPT
    assert "Method relevance" in judge_mod._PROMPT
    assert "Intent coverage" in judge_mod._PROMPT


def test_judge_abstract_window_600():
    docs = [{"title": "T", "abstract": "x" * 1000}]
    seen = {}

    def fake_chat(prompt, **kw):
        seen["prompt"] = prompt
        return "0.8\n0.6\n0.9\n"

    scores = judge_mod.judge_docs("query", docs * 3, fake_chat, batch_size=3)
    assert scores == [0.8, 0.6, 0.9]
    assert "x" * 600 in seen["prompt"]
    assert "x" * 601 not in seen["prompt"]


def test_parse_scores_tolerates_extra_text():
    raw = """Here are the scores:
0.85
0.42
0.00
"""
    assert judge_mod._parse_scores(raw, 3) == [0.85, 0.42, 0.0]


def test_retriever_candidate_caps_raised():
    sig_arxiv = inspect.signature(retrievers.search_arxiv)
    assert sig_arxiv.parameters["max_results"].default == 120
    sig_oa = inspect.signature(retrievers.search_openalex)
    assert sig_oa.parameters["per_page"].default == 40
    sig_cr = inspect.signature(retrievers.search_crossref)
    assert sig_cr.parameters["rows"].default == 50


def test_semantic_scholar_channel_registered():
    assert hasattr(retrievers, "search_semantic_scholar")
    sig = inspect.signature(retrievers.search_semantic_scholar)
    assert "keywords" in sig.parameters
    assert "phrases" in sig.parameters


def test_merge_candidates_aliases_arxiv_doi_same_paper():
    """同一论文分别以 arXiv / DOI key 出现时必须合并为一条。"""
    arxiv_doc = {"arxiv_id": "2309.04564", "doi": "", "title": "When Less is More",
                 "ids": ["2309.04564"], "sources": ["arxiv"]}
    doi_doc = {"arxiv_id": "", "doi": "10.48550/arxiv.2309.04564",
               "title": "When Less is More", "ids": ["10.48550/arxiv.2309.04564"],
               "sources": ["crossref"]}
    merged = merge_candidates([[arxiv_doc], [doi_doc]])
    assert len(merged) == 1
    doc = next(iter(merged.values()))
    assert doc["arxiv_id"] == "2309.04564"
    assert doc["doi"] == "10.48550/arxiv.2309.04564"
    assert "2309.04564" in doc["ids"]
    assert "10.48550/arxiv.2309.04564" in doc["ids"]
    assert doc["sources"] == ["arxiv", "crossref"]


def test_engine_defaults_for_recall():
    engine = SPAR2Engine()
    assert engine.local_top_k == 800
    assert engine.max_judge >= 250
    assert callable(getattr(engine, "sync_run", None))


def test_judge_deadline_short_circuits_without_llm():
    docs = [{"title": "Alpha Beta Gamma", "abstract": "alpha beta gamma delta"},
            {"title": "Other Topic", "abstract": "unrelated text here"}]
    called = {"n": 0}

    def fake_chat(prompt, **kw):
        called["n"] += 1
        raise AssertionError("deadline 已过，不应再调用 LLM")

    # deadline 在过去 → 全部走词法降级
    scores = judge_mod.judge_docs("alpha beta", docs, fake_chat,
                                  batch_size=1, deadline=time.monotonic() - 1)
    assert called["n"] == 0
    assert len(scores) == 2
    assert scores[0] > scores[1]  # 词法分对含查询词的论文更高


def test_judge_accepts_worker_override():
    docs = [{"title": "T", "abstract": "x"}]
    seen = {}

    def fake_chat(prompt, **kw):
        seen["workers"] = kw.get("workers", "default")
        return "0.5\n"

    scores = judge_mod.judge_docs("q", docs, fake_chat, batch_size=1, max_workers=8)
    assert scores == [0.5]


class _FakeLLM:
    def __init__(self, base_url):
        self.ep = type("EP", (), {"base_url": base_url})()

    def chat(self, messages, **kw):
        return "0.9\n0.1\n"


def test_engine_detects_local_ollama_mode():
    local = SPAR2Engine(llm_chat=_FakeLLM("http://localhost:11434/v1"))
    assert local.local_mode is True
    assert local.judge_batch_size == 6
    cloud = SPAR2Engine(llm_chat=_FakeLLM("https://api.deepseek.com/v1"))
    assert cloud.local_mode is False
    assert cloud.judge_batch_size == 12


def test_query_planner_fallback_extracts_discriminative_terms():
    fb = query_planner.extract_keywords_fallback(
        "Give me papers which show that using a smaller dataset in large language "
        "model pre-training can result in better models")
    assert fb["keywords"], "兜底必须产出关键词"
    assert fb["queries"], "兜底必须产出检索短语"
    joined = " ".join(fb["keywords"] + fb["queries"]).lower()
    assert "dataset" in joined
    assert "language" in joined
    assert "pre-training" in joined or "pretraining" in joined


def test_plan_query_falls_back_when_llm_empty():
    def dead_llm(prompt, **kw):
        return None
    plan = query_planner.plan_query("diffusion models for robot planning", dead_llm)
    assert plan["keywords"]
    assert plan["queries"]
    assert plan["fallback_used"] is True


def test_plan_query_merges_llm_and_fallback():
    def fake_llm(prompt, **kw):
        return '{"keywords": ["diffusion policy"], "queries": ["diffusion policy learning for robots"]}'
    plan = query_planner.plan_query("diffusion models for robot planning", fake_llm)
    assert plan["fallback_used"] is False
    assert "diffusion policy" in plan["keywords"]
    assert any("robot" in k or "plan" in k for k in plan["keywords"])  # 兜底词已并入


def test_plan_query_double_pass_unions_keywords():
    calls = {"n": 0}

    def fake_llm(prompt, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return '{"keywords": ["diffusion policy"], "queries": ["diffusion policy for robots"]}'
        return '{"keywords": ["behavior cloning"], "queries": ["imitation learning for manipulation"]}'

    plan = query_planner.plan_query("diffusion models for robot planning", fake_llm)
    assert calls["n"] == 2
    assert plan["plan_calls"] == 2
    assert "diffusion policy" in plan["keywords"]
    assert "behavior cloning" in plan["keywords"]
    assert "imitation learning for manipulation" in plan["queries"]


def test_rerank_top_n_reorders_and_falls_back():
    engine = SPAR2Engine()
    docs = [{"title": f"Paper {i} about topic", "abstract": "x" * 100} for i in range(15)]

    def fake_chat(prompt, **kw):
        return "5\n3\n9\n1\n7\n2\n8\n4\n6\n10\n"

    reranked = engine._rerank_top_n("topic query", docs, fake_chat)
    assert len(reranked) == 15
    assert reranked[0] is docs[4]   # 编号 5 → docs[4]
    assert reranked[1] is docs[2]   # 编号 3 → docs[2]
    assert reranked[9] is docs[9]   # 编号 10 → docs[9]

    # 解析失败 → 返回空列表，调用方保持原排序
    assert engine._rerank_top_n("q", docs, lambda p, **kw: "hello world") == []
