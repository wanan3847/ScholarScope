import io
import re
import zipfile
import pytest
from workspace.store import WorkspaceStore, WorkspaceError
from workspace import presentations, research_tools


@pytest.fixture
def presentation(tmp_path):
    store = WorkspaceStore("sqlite:///" + str(tmp_path / "slides.sqlite3"))
    p = store.create_project("alice", "Well-log research", query="Deep neural porosity and permeability prediction")
    paper = store.add_paper(p["id"], "alice", {"title": "Controlled neural study", "doi": "10.1000/slides-test", "authors": ["Test Author"], "year": 2025,
        "abstract": "We propose a neural network for well logs. The dataset contains 120 samples. Results show RMSE of 0.08. However, validation is limited to one field."})
    research_tools.extract_matrix(store, p["id"], "alice")
    deck = presentations.generate_deck(store, p["id"], "alice")
    return store, p["id"], paper, deck


def test_generated_twelve_slides_source_and_editable_objects(presentation):
    store, pid, paper, deck = presentation
    assert len(deck["data"]["slides"]) == 12
    assert deck["validation"]["invalid_citations"] == 0
    assert deck["citations"] and all(c["quote"] in paper["data"]["abstract"] for c in deck["citations"])
    blob, mime = presentations.export_deck(store, pid, "alice", deck["id"], "pptx")
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        slide_paths = sorted(n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n))
        assert len(slide_paths) == 12
        xml = "\n".join(z.read(n).decode() for n in slide_paths)
        assert "120 samples" in xml and "10.1000/slides-test" in xml
        assert "<p:sp>" in xml and "<a:t>" in xml
        assert not any(n.startswith("ppt/media/") and not n.endswith("/") for n in z.namelist())
        notes = "\n".join(z.read(n).decode() for n in z.namelist() if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", n))
        assert "Abstract source" in notes and "human review: pending" in notes


def test_theme_edit_versions_stale_and_foreign_evidence(presentation):
    store, pid, paper, deck = presentation
    p = store.project(pid, "alice")
    theme = presentations.set_brand(store, pid, "alice", {**presentations.THEMES[0], "name": "Controlled brand", "accent": "224466"}, p["revision"])
    assert store.project(pid, "alice")["settings"]["presentation_brand"]["accent"] == "224466"
    changed = presentations.save_deck(store, pid, "alice", {**deck["data"], "title": "Edited deck", "theme": theme}, deck["id"], deck["revision"])
    assert changed["revision"] == 2
    assert len(store.items(pid, "alice", "presentation_version")) == 2
    with pytest.raises(WorkspaceError) as e:
        presentations.save_deck(store, pid, "alice", deck["data"], deck["id"], deck["revision"])
    assert e.value.status == 409
    store.add_paper(pid, "alice", {**paper["data"], "abstract": "Corrected source with different metrics."})
    view = presentations.deck_view(store, pid, "alice", store.item(pid, "alice", deck["id"], "presentation"))
    assert view["data"]["stale"] and view["validation"]["invalid_citations"]
    with pytest.raises(WorkspaceError):
        presentations.clean_slides(store, pid, "alice", [{"title": "Foreign", "bullets": [{"text": "Fake source", "evidence_id": "foreign"}]}])
    with pytest.raises(WorkspaceError):
        presentations.clean_theme({"accent": 'red; url("unsafe")'})


def test_real_html_and_markdown_exports_escape_researcher_text(presentation):
    store, pid, paper, deck = presentation
    data = deck["data"]
    data["slides"][0]["title"] = '<script>alert("unsafe")</script>'
    changed = presentations.save_deck(store, pid, "alice", data, deck["id"], deck["revision"])
    html, _ = presentations.export_deck(store, pid, "alice", deck["id"], "html")
    assert b'<script>alert(' not in html and b'&lt;script&gt;' in html
    assert html.count(b'<section class="slide"') == 12
    md, _ = presentations.export_deck(store, pid, "alice", deck["id"], "md")
    assert "120 samples" in md.decode() and "Controlled neural study" in md.decode()


def test_real_members_share_edits_with_revision_conflict_and_viewer_readonly(presentation):
    store, pid, paper, deck = presentation
    store.set_member(pid, "alice", "editor", "editor")
    store.set_member(pid, "alice", "reader", "viewer")
    changed = presentations.save_deck(store, pid, "editor", {**deck["data"], "title": "Shared project deck"}, deck["id"], deck["revision"])
    assert store.item(pid, "reader", deck["id"])["label"] == "Shared project deck"
    assert changed["data"]["edited_by"] == "editor"
    with pytest.raises(WorkspaceError) as conflict:
        presentations.save_deck(store, pid, "alice", deck["data"], deck["id"], deck["revision"])
    assert conflict.value.status == 409
    with pytest.raises(WorkspaceError) as forbidden:
        presentations.save_deck(store, pid, "reader", changed["data"], deck["id"], changed["revision"])
    assert forbidden.value.status == 403
    assert len(store.items(pid, "alice", "presentation_version")) == 2
