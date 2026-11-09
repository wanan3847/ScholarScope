"""Generated drafts, edits, versions and exported files share real citations."""
import io
import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from workspace.store import WorkspaceStore, WorkspaceError
from workspace import writing, research_tools


@pytest.fixture
def draft(tmp_path):
    store = WorkspaceStore("sqlite:///" + str(tmp_path / "writer.sqlite3"))
    p = store.create_project("alice", "Porosity methods", query="Neural prediction from well logs")
    paper = store.add_paper(p["id"], "alice", {"title": "Controlled porosity study", "doi": "10.1000/writer-test", "year": 2025,
        "authors": ["Test Author"], "abstract": "We propose a neural network for porosity. The dataset contains 120 samples. Results show RMSE of 0.08. However, evaluation is limited to one field."})
    research_tools.extract_matrix(store, p["id"], "alice")
    manuscript = writing.generate_manuscript(store, p["id"], "alice")
    return store, p["id"], paper, manuscript


def test_draft_real_references_and_no_unsourced_metrics(draft):
    store, pid, paper, m = draft
    assert m["references"][0]["paper"]["doi"] == "10.1000/writer-test"
    assert m["validation"]["invalid_citations"] == 0
    assert m["validation"]["missing_sections"] == []
    assert m["validation"]["abstract_missing"]
    assert m["citations"]
    for c in m["citations"]:
        assert c["quote"] in paper["data"]["abstract"]
        assert c["valid"] and not c["confirmed"]
    content = json.dumps(m["data"]["content"])
    assert "0.08" in content and "99%" not in content
    assert m["data"]["generation_mode"] == "verified_evidence_draft"


def test_versions_restore_conflicts_and_permissions(draft):
    store, pid, paper, m = draft
    store.set_member(pid, "alice", "bob", "editor")
    original = writing.versions(store, pid, "alice", m["id"])[0]
    assert original["data"]["version"] == 1
    changed = writing.save_manuscript(store, pid, "bob", {**m["data"], "title": "Team revised title", "abstract": "Researcher abstract", "keywords": ["porosity", "well logs"]}, m["id"], m["revision"])
    assert changed["label"] == "Team revised title"
    assert not changed["validation"]["abstract_missing"]
    with pytest.raises(WorkspaceError) as e:
        writing.save_manuscript(store, pid, "alice", m["data"], m["id"], m["revision"])
    assert e.value.status == 409
    assert len(writing.versions(store, pid, "alice", m["id"])) == 2
    restored = writing.restore_version(store, pid, "alice", m["id"], original["id"], changed["revision"])
    assert restored["label"] == m["label"] and restored["revision"] == 3
    writing.add_comment(store, pid, "bob", m["id"], "Check sample size", "120 samples")
    with pytest.raises(WorkspaceError):
        writing.add_comment(store, pid, "bob", m["id"], "Fake anchor", "999 samples")
    store.set_member(pid, "alice", "carol", "viewer")
    with pytest.raises(WorkspaceError) as e:
        writing.save_manuscript(store, pid, "carol", restored["data"], m["id"], restored["revision"])
    assert e.value.status == 403
    assert len(writing.versions(store, pid, "alice", m["id"])) == 3


def test_source_change_stales_editor_and_export_record(draft):
    store, pid, paper, m = draft
    e = store.item(pid, "alice", m["citations"][0]["evidence_id"], "evidence")
    store.add_evidence(pid, "alice", {**e["data"], "confirmed": True}, e["id"], e["revision"])
    changed = writing.manuscript_view(store, pid, "alice", store.item(pid, "alice", m["id"], "manuscript"))
    assert changed["data"]["stale"] and changed["validation"]["invalid_citations"] > 0
    # Saving text cannot falsely claim that old citation versions were rechecked.
    resaved = writing.save_manuscript(store, pid, "alice", changed["data"], m["id"], changed["revision"])
    assert resaved["data"]["stale"]
    blob, _ = writing.export_manuscript(store, pid, "alice", m["id"], "md")
    assert "存在已变化的来源引用" in blob.decode()


def test_docx_pdf_markdown_open_with_original_sources(draft):
    from docx import Document
    from pypdf import PdfReader
    store, pid, _, m = draft
    md, _ = writing.export_manuscript(store, pid, "alice", m["id"], "md")
    assert "[1]" in md.decode() and "10.1000/writer-test" in md.decode()
    docx, _ = writing.export_manuscript(store, pid, "alice", m["id"], "docx")
    text = "\n".join(p.text for p in Document(io.BytesIO(docx)).paragraphs)
    assert "120 samples" in text and "参考文献" in text
    pdf, _ = writing.export_manuscript(store, pid, "alice", m["id"], "pdf")
    pages = PdfReader(io.BytesIO(pdf)).pages
    assert pages and "120 samples" in "\n".join(p.extract_text() for p in pages)
    evidence=store.items(pid,"alice","evidence")
    method=next(e for e in evidence if e['data']['field']=='method')
    metric=next(e for e in evidence if e['data']['field']=='metrics')
    combined=writing.save_manuscript(store,pid,"alice",{**m['data'],'content':{'type':'doc','content':[
        {'type':'paragraph','content':[writing.text_node('Method and evaluation '),writing.citation_node(method),writing.citation_node(metric)]}]}},m['id'],m['revision'])
    assert len(combined['data']['evidence_ids'])==2 and len(combined['citations'])==2
    blocks=writing.export_blocks(combined)
    assert blocks[0]['text']=='Method and evaluation [1]'
    assert any(method['data']['quote'] in b['text'] for b in blocks)
    assert any(metric['data']['quote'] in b['text'] for b in blocks)


def test_forged_foreign_citations_and_active_html_rejected(draft):
    store, pid, paper, m = draft
    other = store.create_project("bob", "Private sources")
    p = store.add_paper(other["id"], "bob", {"title": "Private", "abstract": "A private result is verified."})
    e = store.add_evidence(other["id"], "bob", {"paper_id": p["id"], "quote": "A private result is verified."})
    with pytest.raises(WorkspaceError):
        writing.save_manuscript(store, pid, "alice", {"title": "Forged", "content": {"type": "doc", "content": [{"type": "paragraph", "content": [writing.citation_node(e)]}]}})
    with pytest.raises(WorkspaceError):
        writing.save_manuscript(store, pid, "alice", {"title": "Unsafe", "content": {"type": "doc", "content": [{"type": "iframe"}]}})
    content = writing.clean_content(store, pid, "alice", {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Unsafe link", "marks": [{"type": "link", "attrs": {"href": "javascript:alert(1)"}}]}]}]})
    assert "javascript" not in str(content)


def test_version_save_is_atomic_under_two_editors(draft):
    store, pid, _, m = draft
    store.set_member(pid, "alice", "bob", "editor")
    def update(actor):
        try:
            return writing.save_manuscript(store, pid, actor, {**m["data"], "title": actor + " edit"}, m["id"], m["revision"])["revision"]
        except WorkspaceError as e:
            return e.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(update, ["alice", "bob"])) == [2, 409]
    assert len(writing.versions(store, pid, "alice", m["id"])) == 2
