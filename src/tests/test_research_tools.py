"""Research results must have real, current sources; decisions stay independent."""
import pytest
from sqlalchemy import text
from workspace.store import WorkspaceStore, WorkspaceError
from workspace.knowledge import ProjectIndex
from workspace import research_tools as tools


@pytest.fixture
def research(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHOLARSCOPE_DISABLE_EMBEDDINGS", "1")
    store = WorkspaceStore("sqlite:///" + str(tmp_path / "research.sqlite3"))
    p = store.create_project("alice", "Well-log comparison")
    paper = store.add_paper(p["id"], "alice", {"title": "Controlled neural well-log study", "doi": "10.1000/research-tools",
        "abstract": "We propose a neural network for porosity prediction from well logs. The dataset contains 120 samples. Results show RMSE of 0.08. However, testing is limited to one field."})
    return store, p["id"], paper


def test_matrix_missing_values_quotes_and_manual_rerun(research):
    store, pid, paper = research
    matrix = tools.extract_matrix(store, pid, "alice")
    cells = matrix["rows"][0]["cells"]
    assert cells["sample_size"]["value"] == "120 samples"
    assert cells["sample_size"]["source_valid"]
    assert cells["sample_size"]["evidence"]["data"]["scope"] == "abstract"
    assert cells["metrics"]["value"] == "Results show RMSE of 0.08."
    for c in cells.values():
        if c["evidence"]:
            assert c["evidence"]["data"]["quote"] in paper["data"]["abstract"]
    col = {"id": "funding", "label": "Funding", "description": "funding grant sponsor"}
    custom = tools.set_columns(store, pid, "alice", [col], matrix["project_revision"])
    result = tools.extract_matrix(store, pid, "alice")
    cell = result["rows"][0]["cells"]["funding"]
    assert cell["value"] is None and cell["evidence"] is None
    with pytest.raises(WorkspaceError):
        tools.edit_cell(store, pid, "alice", cell["id"], {"quote": "Funded by NASA", "value": "NASA"}, cell["revision"])
    updated = tools.edit_cell(store, pid, "alice", cell["id"], {"quote": "The dataset contains 120 samples.", "value": "Researcher comment based on 120 samples", "confirmed": True, "comment": "Reclassified by researcher"}, cell["revision"])
    assert updated["data"]["manual"]
    assert tools.extract_matrix(store, pid, "alice")["rows"][0]["cells"]["funding"]["value"] == updated["data"]["value"]
    with pytest.raises(WorkspaceError) as e:
        tools.edit_cell(store, pid, "alice", cell["id"], {"quote": "The dataset contains 120 samples."}, cell["revision"])
    assert e.value.status == 409


def test_persistent_retrieval_and_source_invalidation(research):
    store, pid, paper = research
    other = store.create_project("bob", "Private")
    store.add_paper(other["id"], "bob", {"title": "Private unrelated paper", "abstract": "A private permeability dataset has 999 samples."})
    index = ProjectIndex(store)
    result = index.retrieve(pid, "alice", "porosity dataset")
    assert result["mode"] == "keyword_degraded"
    assert result["passages"] and all(r["paper_id"] == paper["id"] for r in result["passages"])
    assert all("score" not in r for r in result["passages"])
    with store.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM research_chunks_fts WHERE project_id=:pid"), {"pid": pid}).scalar() == 2
    assert not index.retrieve(pid, "alice", "unrelated galaxies migration")["passages"]
    answer = tools.answer_question(store, pid, "alice", "porosity dataset")
    assert answer["data"]["citations"]
    for c in answer["data"]["citations"]:
        assert store.verify_evidence(pid, "alice", c["evidence_id"])["valid"]
    store.add_paper(pid, "alice", {**paper["data"], "abstract": "A corrected porosity dataset contains 150 samples."})
    assert store.item(pid, "alice", answer["id"])["data"]["stale"]
    assert "120 samples" not in str(index.retrieve(pid, "alice", "dataset")["passages"])
    with pytest.raises(WorkspaceError):
        index.retrieve(pid, "bob", "dataset")


def test_viewer_can_query_but_cannot_change_or_save(research):
    store, pid, _ = research
    store.set_member(pid, "alice", "bob", "viewer")
    answer = tools.answer_question(store, pid, "bob", "porosity dataset")
    assert answer["citations"] and answer["citations"][0]["evidence_id"] is None
    assert not store.items(pid, "alice", "answer")
    assert not store.items(pid, "alice", "evidence")
    with pytest.raises(WorkspaceError) as e:
        tools.extract_matrix(store, pid, "bob")
    assert e.value.status == 403


def test_title_only_cannot_support_research_findings(research):
    store, pid, paper = research
    store.put(pid, "alice", "paper", paper["label"], {**paper["data"], "abstract": ""}, paper["id"], paper["revision"])
    answer = tools.answer_question(store, pid, "alice", "well log study")
    assert answer["mode"] == "title_only"
    assert not answer["citations"]
    assert not store.items(pid, "alice", "evidence")


def test_dual_reviewer_conflict_stages_and_revision(research):
    store, pid, paper = research
    store.set_member(pid, "alice", "bob", "editor")
    result = tools.record_screening(store, pid, "alice", paper["id"], "include", "title_abstract", "Relevant object and method")
    assert result["rows"][0]["status"] == "pending"
    with pytest.raises(WorkspaceError):
        tools.record_screening(store, pid, "bob", paper["id"], "exclude", "title_abstract", "")
    result = tools.record_screening(store, pid, "bob", paper["id"], "exclude", "title_abstract", "No external validation")
    assert result["flow"]["conflicts"] == 1
    vote = next(v for v in result["rows"][0]["decisions"] if v["data"]["reviewer"] == "bob")
    result = tools.record_screening(store, pid, "bob", paper["id"], "include", "title_abstract", "Agreement after rechecking scope", vote["revision"])
    assert result["flow"]["included"] == 1
    with pytest.raises(WorkspaceError) as e:
        tools.record_screening(store, pid, "bob", paper["id"], "exclude", "title_abstract", "Stale change", vote["revision"])
    assert e.value.status == 409
    with pytest.raises(WorkspaceError):
        tools.record_screening(store, pid, "alice", paper["id"], "include", "fulltext", "No actual PDF")
    # A new stage requires new independent decisions; summary consensus is not reused.
    store.put(pid, "alice", "document", "Controlled parsed source", {"paper_id": paper["id"], "pages": [{"number": 1, "text": "Actual test source."}]})
    result = tools.record_screening(store, pid, "alice", paper["id"], "include", "fulltext", "Methods verified")
    assert result["rows"][0]["status"] == "pending"
    assert len(result["rows"][0]["decisions"]) == 3
