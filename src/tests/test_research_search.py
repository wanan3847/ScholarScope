"""Research search contracts: factual results, relevance and graceful failure."""
import copy
import json

from agent import research_search as research


def setup_sources(monkeypatch, docs):
    for name in ("search_arxiv", "search_crossref", "search_semantic_scholar", "search_local", "search_europe_pmc", "search_scopus"):
        monkeypatch.setattr(research.retrievers, name, lambda *a, **kw: [])
    monkeypatch.setattr(research.retrievers, "search_openalex", lambda *a, **kw: copy.deepcopy(docs))
    monkeypatch.setattr(research.retrievers, "semantic_scores", lambda q, texts: [0.0] * len(texts))
    monkeypatch.setattr(research, "_enrich_abstracts", lambda docs: None)


def paper(title, doi="10.1000/a", year="2024", citations=0):
    return {"title": title, "doi": doi, "year": year, "abstract": title,
            "sources": ["openalex"], "cited_by": citations}


def test_failure_returns_real_empty_results(monkeypatch):
    setup_sources(monkeypatch, [])
    def fail(*a, **kw):
        raise RuntimeError("source offline")
    monkeypatch.setattr(research.retrievers, "search_arxiv", fail)
    result = research.ResearchSearchEngine(llm_chat=lambda *a, **kw: None).run("graph neural network")
    assert result["papers"] == []
    assert result["stats"]["ranking_mode"] == "semantic_fallback"


def test_citations_do_not_override_direct_match(monkeypatch):
    setup_sources(monkeypatch, [paper("Graph neural network molecular prediction", citations=0),
                               paper("Neural language generation", "10.1000/b", citations=100000)])
    result = research.ResearchSearchEngine(llm_chat=lambda *a, **kw: None).run("graph neural molecular prediction")
    assert result["papers"][0]["doi"] == "10.1000/a"
    assert "score" not in result["papers"][0]


def test_year_constraints_apply_to_all_sources(monkeypatch):
    setup_sources(monkeypatch, [paper("Graph methods", year="2020"),
                               paper("Graph methods latest", "10.1000/b", year="2024"),
                               paper("Graph methods undated", "10.1000/c", year="")])
    result = research.ResearchSearchEngine(llm_chat=lambda *a, **kw: None).run("graph methods", year_from=2023)
    assert [p["doi"] for p in result["papers"]] == ["10.1000/b"]


def test_evidence_selection_rejects_invented_and_duplicate_entries(monkeypatch):
    setup_sources(monkeypatch, [paper("Graph neural network molecular prediction")])
    def chat(prompt, **kw):
        if prompt.startswith("Translate"):
            return json.dumps({"keywords": ["graph neural network"], "queries": ["graph neural molecular prediction"]})
        return json.dumps({"papers": [
            {"index": 99, "reason": "不存在", "evidence": "invented"},
            {"index": 1, "reason": "虚构结果", "evidence": "cures all diseases"},
            {"index": 1, "reason": "研究分子预测的图神经网络。", "evidence": "molecular prediction"},
            {"index": 1, "reason": "重复", "evidence": "molecular prediction"}]})
    result = research.ResearchSearchEngine(llm_chat=chat).run("graph neural molecular prediction")
    assert len(result["papers"]) == 1
    assert result["papers"][0]["evidence"] == "molecular prediction"
    assert result["stats"]["ranking_mode"] == "evidence_selection"


def test_valid_exclusion_does_not_force_irrelevant_recommendations(monkeypatch):
    setup_sources(monkeypatch, [paper("Graph methods")])
    def chat(prompt, **kw):
        return '{"papers": []}' if prompt.startswith("Select") else '{}'
    result = research.ResearchSearchEngine(llm_chat=chat).run("graph methods for molecules")
    assert result["papers"] == []
    assert result["stats"]["ranking_mode"] == "evidence_selection"


def test_duplicate_titles_and_doi_versions_are_merged(monkeypatch):
    docs = [paper("Graph methods"), paper("Graph methods", "https://doi.org/10.1000/A"),
            paper("Graph methods", "10.1000/b")]
    setup_sources(monkeypatch, docs)
    result = research.ResearchSearchEngine(llm_chat=lambda *a, **kw: None).run("graph methods")
    assert len(result["papers"]) == 1
    assert result["papers"][0]["url"] == "https://doi.org/10.1000/a"


def test_web_uses_existing_agent_and_applies_request_constraints(monkeypatch):
    from fastapi.testclient import TestClient
    import web.app as web
    monkeypatch.setattr(web, "_get_llm_router", lambda: type("Router", (), {"get": lambda self, name: None})())
    configured = {}
    class FakeAgent:
        def __init__(self, **kwargs):
            configured.update(kwargs)
        def sync_run(self, query, before_date):
            configured["query"] = query
            configured["before_date"] = before_date
            return {"engine": "spar2", "papers": [
                paper("Graph neural molecular prediction", year="2024"),
                paper("Older graph methods", "10.1000/b", year="2020"),
                paper("Undated graph methods", "10.1000/c", year=""),
            ], "stats": {"ranking_mode": "practical_agent_selection"}, "relationships": []}
    monkeypatch.setattr(web, "Orchestrator", FakeAgent)
    client = TestClient(web.app)
    result = client.post("/api/search", json={"query": "graph molecular", "year_from": 2023})
    assert result.status_code == 200
    assert result.json()["engine"] == "spar2"
    assert result.json()["papers"][0]["doi"] == "10.1000/a"
    assert len(result.json()["papers"]) == 1
    assert configured["max_output"] == 50
    assert configured["max_rounds"] == 2
    assert configured["before_date"] == ""
    assert configured["year_from"] == 2023
    assert client.post("/api/search", json={"query": "graph", "year_from": 2025, "year_to": 2020}).status_code == 422
    assert client.post("/api/search", json={"query": "   "}).status_code == 422


def test_orchestrator_orders_by_practical_use_and_checks_evidence(monkeypatch):
    from agent.orchestrator import Orchestrator
    agent = Orchestrator(llm_chat=lambda prompt, **kw: json.dumps({"papers": [
        {"index": 3, "reason": "与目标研究无直接关联，应排除。", "evidence": "social network analysis"},
        {"index": 4, "reason": "与主题相关。", "evidence": "molecular property prediction"},
        {"index": 2, "reason": "提供与目标条件一致的可复现实验步骤。", "evidence": "reproducible experimental protocol"},
        {"index": 1, "reason": "应该引用", "evidence": "not in paper"},
    ]}), max_output=50)
    monkeypatch.setattr(agent.spar2, "run", lambda query, before_date: {
        "engine": "spar2", "stats": {}, "papers": [
            {"title": "Popular but tangential", "abstract": "A broad discussion.", "score": 0.99, "cited_by": 90000},
            {"title": "Practical assay protocol", "abstract": "A reproducible experimental protocol for the target assay.", "score": 0.18, "cited_by": 0},
            {"title": "Graph neural networks for social network analysis", "abstract": "A study of social network analysis.", "score": 0.2, "cited_by": 0},
            {"title": "DIG-Mol: Molecular Property Prediction_supp1-123.pdf", "abstract": "Supporting material for molecular property prediction.", "score": .3},
        ]})
    result = agent.sync_run("find a practical assay protocol")
    assert [p["title"] for p in result["papers"]] == ["Practical assay protocol"]
    assert "score" not in result["papers"][0]
    assert result["papers"][0]["evidence"] == "reproducible experimental protocol"
    assert result["stats"]["ranking_mode"] == "practical_agent_selection"
    assert "Score" not in result["table"]
    assert "score" not in result["comparison"][0]


def test_spar2_returns_empty_when_every_retrieval_source_fails(monkeypatch):
    from agent.spar2 import engine as spar2
    for name in ("search_arxiv", "search_openalex", "search_local",
                 "search_crossref", "search_semantic_scholar", "search_europe_pmc", "search_scopus"):
        monkeypatch.setattr(spar2.retrievers, name, lambda *args, **kwargs: [])
    monkeypatch.setattr(spar2.retrievers, "semantic_scores", lambda *args, **kwargs: [])
    agent = spar2.SPAR2Engine(llm_chat=lambda *args, **kwargs: "{}",
                              max_output=5, max_judge=0,
                              deadline_seconds=2, max_rounds=1)
    result = agent.run("test query")
    assert result["papers"] == []


def test_empty_agent_result_contains_no_score_table(monkeypatch):
    from agent.orchestrator import Orchestrator
    agent = Orchestrator(llm_chat=lambda *args, **kwargs: "{}")
    monkeypatch.setattr(agent.spar2, "run", lambda query, before_date: {
        "engine": "spar2", "stats": {}, "papers": []})
    result = agent.sync_run("no results")
    assert result["stats"]["ranking_mode"] == "no_results"
    assert "Score" not in result["table"]


def test_agent_fallback_uses_query_terms_instead_of_score_order(monkeypatch):
    from agent.orchestrator import Orchestrator
    agent = Orchestrator(llm_chat=lambda *args, **kwargs: "{}", max_output=5)
    monkeypatch.setattr(agent.spar2, "run", lambda query, before_date: {
        "engine": "spar2", "stats": {"keywords": ["assay", "experimental"]}, "papers": [
            {"title": "Popular social network analysis", "abstract": "A broad graph study.", "score": .99},
            {"title": "Practical assay protocol", "abstract": "Experimental protocol for the target assay.", "score": .1},
        ]})
    result = agent.sync_run("practical assay protocol")
    assert result["papers"][0]["title"] == "Practical assay protocol"
    assert "assay" in result["papers"][0]["evidence"]
    assert result["papers"][0]["evidence"] in result["papers"][0]["abstract"]
    assert "score" not in result["papers"][0]
    assert result["stats"]["ranking_mode"] == "agent_retrieval_fallback"


def test_explicit_method_and_target_constraints_and_thirty_paper_selection(monkeypatch):
    from agent.orchestrator import Orchestrator
    agent = Orchestrator(llm_chat=lambda *a, **kw: "{}", max_output=50, practical_limit=30)
    valid = [{"title": "Controlled deep learning well logs permeability prediction " + str(i), "abstract": "A convolutional neural network predicts permeability from well logs."} for i in range(35)]
    irrelevant = [
        {"title": "Factor analysis of porosity and permeability from well logs", "abstract": "The method uses factor analysis."},
        {"title": "Deep learning prediction of missing well logs", "abstract": "A transformer fills missing log curves."},
        {"title": "Deep learning for permeability from core data", "abstract": "The study uses laboratory core images."},
    ]
    monkeypatch.setattr(agent.spar2, "run", lambda *a: {"stats": {"keywords": ["well logs", "permeability"]}, "papers": irrelevant + valid})
    result = agent.sync_run("deep learning well logs porosity permeability prediction")
    assert len(result["papers"]) == 30 and all(p["title"].startswith("Controlled") for p in result["papers"])
    monkeypatch.setattr(agent.spar2, "run", lambda *a: {"stats": {}, "papers": irrelevant})
    assert agent.sync_run("基于测井曲线预测孔隙度、渗透率的深度学习方法")["papers"] == []


def test_well_log_property_intent_checks_input_output_roles():
    from agent.research_intent import matches
    query='deep learning well logs porosity permeability prediction'
    assert matches(query,{'title':'CNN well logs permeability prediction','abstract':'A convolutional model predicts permeability from well logs.'})
    assert not matches(query,{'title':'Deep-learning missing well-log predictions','abstract':'We use LSTM with well logs to reconstruct missing neutron porosity logs.'})
    assert not matches(query,{'title':'Physics-constrained LSTM-UNet for seismic porosity prediction','abstract':'Prior approaches use well logs. We predict porosity from seismic data.'})
    assert not matches(query,{'title':'Rock typing using deep learning','abstract':'A review mentions porosity, permeability and well logs.'})
    assert not matches(query,{'title':'ANN permeability prediction','abstract':'This study applies artificial neural networks to well logs. These results aid users of deep learning.'})
    assert matches(query,{'title':'Comparative well log permeability modeling','abstract':'In this research, CNN and CNN-LSTM were compared using well logs to predict permeability.'})
