"""结构化输出三件套 + 反馈闭环 + Web 启动回归测试。"""

from __future__ import annotations

import os
import tempfile

from agent import graph_synthesizer as gs
from agent.feedback_loop import FeedbackCollector, RewardComputer


_PAPERS = [
    {"title": "Planning with Diffusion for Flexible Behavior Synthesis",
     "arxiv_id": "2205.09991", "score": 0.92, "year": 2022,
     "source": "openalex,arxiv"},
    {"title": "Diffuser: Diffusion Policies as an Efficient Policy Class",
     "arxiv_id": "2202.03065", "score": 0.81, "year": 2022,
     "source": "openalex"},
    {"title": "Hierarchical Planning with Diffusion Models",
     "arxiv_id": "2304.10101", "score": 0.55, "year": 2023,
     "source": "arxiv"},
]


def test_similarity_edges_skip_unrelated():
    papers = _PAPERS + [
        {"title": "Quantum Error Correction with Surface Codes",
         "arxiv_id": "1111.1111", "score": 0.1, "year": 2011,
         "source": "arxiv"},
    ]
    edges = gs.similarity_edges(papers)
    assert edges, "相似论文之间应生成 similar 边"
    for e in edges:
        assert e["src"] != e["dst"]
        assert e["relation"] == "similar"
        assert 0.0 < e["weight"] <= 1.0


def test_markdown_table_and_comparison():
    md = gs.make_markdown_table(_PAPERS)
    assert md.startswith("| # | Title")
    assert len(md.splitlines()) == 5
    cmp_rows = gs.make_comparison_table(_PAPERS)
    assert len(cmp_rows) == 3
    assert cmp_rows[0]["rank"] == 1
    assert cmp_rows[0]["title"].startswith("Planning with Diffusion")


def test_cluster_and_summary():
    clusters = gs.make_cluster_summary(_PAPERS)
    assert clusters["total"] == 3
    assert any(c["count"] >= 1 for c in clusters["clusters"])
    summary = gs.make_summary("diffusion for planning", _PAPERS)
    assert "共整理 3 篇论文" in summary
    assert "高度相关 2 篇" in summary


def test_three_part_bundle():
    bundle = gs.generate_three_part_output("diffusion for planning", _PAPERS)
    assert set(bundle) >= {"json", "markdown_table", "graph_html",
                           "cluster_summary", "summary", "relationships"}
    assert len(bundle["json"]["papers"]) == 3
    assert bundle["relationships"]
    assert "<svg" in bundle["graph_html"]
    assert bundle["markdown_table"].splitlines()[0].startswith("| # |")


def test_feedback_loop_roundtrip_and_rewards():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "feedback.jsonl")
        col = FeedbackCollector()
        col.record_click("q1", "p1")
        col.record_star("q1", "p1", star=5)
        col.record_cite("q1", "p2")
        col.record_skip("q2", "p3")
        n = col.flush_to_file(path)
        assert n == 4
        events = FeedbackCollector.load_from_file(path)
        assert len(events) == 4
        comp = RewardComputer()
        per_paper = comp.compute_per_paper(events)
        assert per_paper["p1"] == 3.0  # click 1 + star 2
        assert per_paper["p2"] == 3.0  # cite
        assert per_paper["p3"] == -0.5  # skip
        assert 0.0 < comp.citation_adoption_rate(events) <= 1.0


def test_web_importable():
    """Web 服务模块可正常导入（修复 feedback_loop/graph_synthesizer 断链）。"""
    import web.app  # noqa: F401
    from agent.orchestrator import DEFAULT_INNOVATION_FLAGS
    assert "spar2_bfs_iterative" in DEFAULT_INNOVATION_FLAGS
