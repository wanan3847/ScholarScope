"""Project/role/quote/version regression using isolated real database/files."""
from __future__ import annotations

import io
import pytest

from workspace.store import WorkspaceError, WorkspaceStore
from workspace.documents import ObjectStore, attach_pdf, parse_pdf


@pytest.fixture
def store(tmp_path):
    return WorkspaceStore("sqlite:///" + str(tmp_path / "workspace.sqlite3"))


def make_paper(store, pid, actor="alice"):
    return store.add_paper(pid, actor, {"doi": "10.1000/workspace-test", "title": "Controlled test: neural permeability prediction",
        "authors": ["Test Author"], "year": 2024,
        "abstract": "We use a neural network to predict permeability from well logs. The dataset contains 120 samples."})


def pdf_bytes():
    from reportlab.pdfgen.canvas import Canvas
    blob = io.BytesIO()
    canvas = Canvas(blob)
    canvas.drawString(50, 790, "1. Methods")
    canvas.drawString(50, 750, "We use a neural network to predict permeability.")
    canvas.showPage()
    canvas.drawString(50, 790, "2. Results")
    canvas.drawString(50, 750, "The dataset contains 120 samples.")
    canvas.save()
    return blob.getvalue()


def test_projects_persist_isolated_and_archive(store):
    p = store.create_project("alice", "Porosity", query="neural well logs")
    assert store.projects("bob") == []
    with pytest.raises(WorkspaceError) as e:
        store.project(p["id"], "bob")
    assert e.value.status == 404
    again = WorkspaceStore(str(store.engine.url))
    assert again.project(p["id"], "alice")["query"] == "neural well logs"
    again.update_project(p["id"], "alice", {"archived": 1}, 1)
    assert again.projects("alice") == []
    assert len(again.projects("alice", archived=True)) == 1


def test_member_roles_and_optimistic_versions(store):
    p = store.create_project("alice", "Team")
    store.set_member(p["id"], "alice", "bob", "viewer")
    assert store.projects("bob")[0]["role"] == "viewer"
    with pytest.raises(WorkspaceError) as e:
        make_paper(store, p["id"], "bob")
    assert e.value.status == 403
    store.set_member(p["id"], "alice", "bob", "editor")
    paper = make_paper(store, p["id"], "bob")
    with pytest.raises(WorkspaceError) as e:
        store.set_member(p["id"], "bob", "carol", "editor")
    assert e.value.status == 403
    store.put(p["id"], "alice", "paper", paper["label"], {**paper["data"], "tags": ["core"]}, paper["id"], 1)
    with pytest.raises(WorkspaceError) as e:
        store.put(p["id"], "bob", "paper", paper["label"], paper["data"], paper["id"], 1)
    assert e.value.status == 409
    store.set_member(p["id"], "alice", "bob", "remove")
    assert store.projects("bob") == []


def test_canonical_metadata_and_no_fabricated_evidence(store):
    p = store.create_project("alice", "Evidence")
    paper = make_paper(store, p["id"])
    again = store.add_paper(p["id"], "alice", {"doi": "https://doi.org/10.1000/WORKSPACE-TEST", "title": paper["label"], "arxiv_id": "2401.12345v2"})
    assert paper["id"] == again["id"]
    assert len(store.items(p["id"], "alice", "paper")) == 1
    assert "arxiv:2401.12345" in again["data"]["aliases"]
    with pytest.raises(WorkspaceError):
        store.add_evidence(p["id"], "alice", {"paper_id": paper["id"], "quote": "Achieved 99% accuracy"})
    e = store.add_evidence(p["id"], "alice", {"paper_id": paper["id"], "field": "sample_size", "quote": "The dataset contains 120 samples.", "value": "120", "confirmed": True})
    assert store.verify_evidence(p["id"], "alice", e["id"])["valid"]
    assert e["data"]["scope"] == "abstract"
    assert e["data"]["value_status"] == "extract"
    with pytest.raises(WorkspaceError):
        store.add_evidence(p["id"], "alice", {"paper_id": paper["id"], "quote": e["data"]["quote"], "scope": "fulltext"})


def test_evidence_updates_invalidate_dependent_outputs(store):
    p = store.create_project("alice", "Dependencies")
    paper = make_paper(store, p["id"])
    e = store.add_evidence(p["id"], "alice", {"paper_id": paper["id"], "quote": "The dataset contains 120 samples.", "field": "samples"})
    draft = store.put(p["id"], "alice", "manuscript", "Review", {"evidence_ids": [e["id"]], "content": "An evidence draft"})
    deck = store.put(p["id"], "alice", "presentation", "Meeting", {"evidence_ids": [e["id"]], "slides": []})
    store.add_evidence(p["id"], "alice", {**e["data"], "note": "Rechecked", "confirmed": True}, e["id"], e["revision"])
    assert store.item(p["id"], "alice", draft["id"])["data"]["stale"]
    assert store.item(p["id"], "alice", deck["id"])["data"]["stale"]
    with pytest.raises(WorkspaceError):
        store.remove(p["id"], "alice", paper["id"])


def test_source_changes_break_old_evidence_and_invalidate_drafts(store):
    p = store.create_project("alice", "Changing sources")
    paper = make_paper(store, p["id"])
    e = store.add_evidence(p["id"], "alice", {"paper_id": paper["id"], "quote": "The dataset contains 120 samples."})
    draft = store.put(p["id"], "alice", "manuscript", "Dependent review", {"evidence_ids": [e["id"]]})
    store.add_paper(p["id"], "alice", {**paper["data"], "abstract": "Updated source: 150 samples were enrolled."})
    assert not store.verify_evidence(p["id"], "alice", e["id"])["valid"]
    assert store.item(p["id"], "alice", draft["id"])["data"]["stale"]


def test_real_pdf_text_locations_and_storage(store, tmp_path):
    p = store.create_project("alice", "PDF")
    paper = make_paper(store, p["id"])
    objects = ObjectStore(tmp_path)
    blob = pdf_bytes()
    doc = attach_pdf(store, objects, p["id"], "alice", paper["id"], "paper.pdf", blob)
    assert doc["data"]["page_count"] == 2
    assert doc["data"]["status"] == "parsed"
    assert doc["data"]["outline"][0]["page"] == 1
    assert objects.get(doc["data"]["object_key"]) == blob
    assert attach_pdf(store, objects, p["id"], "alice", paper["id"], "again.pdf", blob)["id"] == doc["id"]
    span = doc["data"]["pages"][1]["spans"][1]
    e = store.add_evidence(p["id"], "alice", {"paper_id": paper["id"], "document_id": doc["id"], "page": 2,
        "span_id": span["id"], "quote": "The dataset contains 120 samples.", "field": "samples"})
    assert e["data"]["bbox"] == span["bbox"]
    assert store.verify_evidence(p["id"], "alice", e["id"])["location"]["page"] == 2
    with pytest.raises(WorkspaceError):
        store.add_evidence(p["id"], "alice", {"paper_id": paper["id"], "document_id": doc["id"], "page": 1, "quote": e["data"]["quote"]})
    with pytest.raises(WorkspaceError):
        objects.get("../../users.json")
    with pytest.raises(WorkspaceError):
        parse_pdf(b"not a PDF")


def test_workspace_api_authenticated_identity_and_real_pdf(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import agent.collections as users
    import web.workspace_api as api
    from web.app import app
    for attr, name in [("_USERS_FILE", "users.json"), ("_COLLECTIONS_FILE", "collections.json"), ("_READ_PAPERS_FILE", "read.json"), ("_PAPER_CACHE_FILE", "cache.json")]:
        monkeypatch.setattr(users, attr, tmp_path / name)
    local = WorkspaceStore("sqlite:///" + str(tmp_path / "api.sqlite3"))
    monkeypatch.setattr(api, "get_store", lambda: local)
    monkeypatch.setattr(api, "ObjectStore", lambda: ObjectStore(tmp_path))
    users.register_user("alice", "test-password")
    users.register_user("bob", "test-password")
    token = users.login_user("alice", "test-password")["token"]
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + token}
    p = client.post("/api/workspace/projects", headers=headers, json={"title": "Authenticated"}).json()
    assert p["owner"] == "alice"
    root = "/api/workspace/projects/" + p["id"]
    assert client.get(root + "?user_id=alice").status_code == 404
    assert client.get(root, headers={"Authorization": "Bearer invalid"}).status_code == 401
    paper = client.post(root + "/papers", headers=headers, json={"paper": {"title": "Test PDF", "doi": "10.1000/api-pdf"}}).json()
    doc = client.post(root + "/papers/" + paper["id"] + "/pdf", headers=headers,
        files={"file": ("test.pdf", pdf_bytes(), "application/pdf")})
    assert doc.status_code == 200, doc.text
    file_url = root + "/documents/" + doc.json()["id"] + "/file"
    assert client.get(file_url).status_code == 404
    assert client.get(file_url, headers=headers).content.startswith(b"%PDF")
    assert client.put(root + "/members", headers=headers, json={"username": "bob", "role": "viewer"}).status_code == 200
    bob = {"Authorization": "Bearer " + users.login_user("bob", "test-password")["token"]}
    assert client.get(root + "/items", headers=bob).status_code == 200
    assert client.post(root + "/papers", headers=bob, json={"paper": {"title": "Forbidden"}}).status_code == 403


def test_alternate_doi_publication_dedup_preserves_canonical_source(tmp_path):
    store=WorkspaceStore('sqlite:///'+str(tmp_path/'versions.db'))
    pid=store.create_project('alice','Versions')['id']
    title='Controlled dual attention residual model for porosity prediction from well logs'
    first=store.add_paper(pid,'alice',{'title':title,'doi':'10.1000/journal','authors':['Test Researcher'],'abstract':'The journal version reports RMSE of 0.08.'})
    second=store.add_paper(pid,'alice',{'title':title.upper(),'doi':'10.1000/preprint','authors':['Test Researcher'],'abstract':'The earlier preprint reports RMSE of 0.10.'})
    assert second['id']==first['id'] and len(store.items(pid,'alice','paper'))==1
    assert second['data']['doi']=='10.1000/journal' and second['data']['abstract']==first['data']['abstract']
    assert second['data']['related_versions'][0]['doi']=='10.1000/preprint'
    assert 'doi:10.1000/preprint' in second['data']['aliases']
    repeated=store.add_paper(pid,'alice',{'title':title,'doi':'10.1000/preprint','authors':['Test Researcher'],'abstract':'The earlier preprint reports RMSE of 0.10.'})
    assert repeated['data']['abstract']==first['data']['abstract']
    assert len(repeated['data']['related_versions'])==1
    different=store.add_paper(pid,'alice',{'title':title,'doi':'10.1000/different','authors':['Other Researcher']})
    assert different['id']!=first['id']
