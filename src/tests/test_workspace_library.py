import io
import json
import pytest
from openpyxl import load_workbook
from workspace.store import WorkspaceStore, WorkspaceError
from workspace import library, research_tools


def test_project_organization_import_aliases_and_real_exports(tmp_path):
    store = WorkspaceStore("sqlite:///" + str(tmp_path / "library.db")); p = store.create_project("alice", "Library")
    pid = p["id"]
    report = library.import_papers(store, pid, "alice", [
        {"title": "Controlled neural library", "doi": "10.1000/library-test", "arxiv_id": "2401.12345v1", "authors": ["Test Author"], "year": 2024, "abstract": "The dataset contains 120 samples."},
        {"title": "Controlled neural library", "doi": "https://doi.org/10.1000/library-test", "arxiv_id": "2401.12345v2", "authors": ["Test Author"]},
        {"doi": "10.1000/missing-title"},
    ])
    assert report["imported"] == 1 and report["failures"][0]["row"] == 3
    paper = store.items(pid, "alice", "paper")[0]
    assert paper["data"]["abstract"] == "The dataset contains 120 samples."
    collection = library.create_collection(store, pid, "alice", "Reservoir methods")
    edited = library.organize_paper(store, pid, "alice", paper["id"], {"tags": ["neural", "well logs"], "collection_ids": [collection["id"]], "bookmarked": True, "read": True}, paper["revision"])
    assert edited["data"]["bookmarked"] and edited["data"]["read"]
    for fmt in ("json", "ris", "csv", "bib"):
        blob, mime = library.export_references(store, pid, "alice", fmt, collection["id"])
        assert b"Controlled neural library" in blob and b"10.1000/library-test" in blob
        if fmt == "json": assert json.loads(blob)[0]["tags"] == ["neural", "well logs"]
    with pytest.raises(WorkspaceError): store.remove(pid, "alice", collection["id"])
    with pytest.raises(WorkspaceError) as conflict: library.organize_paper(store, pid, "alice", paper["id"], {}, paper["revision"])
    assert conflict.value.status == 409
    store.set_member(pid, "alice", "reader", "viewer")
    with pytest.raises(WorkspaceError) as forbidden: library.organize_paper(store, pid, "reader", paper["id"], {}, edited["revision"])
    assert forbidden.value.status == 403
    with pytest.raises(WorkspaceError): library.export_references(store, pid, "mallory", "json")


def test_excel_source_audit_and_formula_cells_are_text(tmp_path):
    store = WorkspaceStore("sqlite:///" + str(tmp_path / "matrix.db")); p = store.create_project("alice", "Matrix")
    store.add_paper(p["id"], "alice", {"title": "=HYPERLINK controlled title", "abstract": "The dataset contains 120 samples."})
    research_tools.extract_matrix(store, p["id"], "alice")
    blob, mime = library.export_matrix(store, p["id"], "alice", "xlsx")
    workbook = load_workbook(io.BytesIO(blob))
    assert workbook.sheetnames == ["证据矩阵", "原文出处"]
    cell = workbook["证据矩阵"]["A2"]
    assert cell.data_type == "s" and cell.value.startswith("'=")
    text = " ".join(str(c.value) for row in workbook["原文出处"] for c in row)
    assert "The dataset contains 120 samples." in text and "原文匹配" in text
    csv, _ = library.export_matrix(store, p["id"], "alice", "csv")
    assert b"120 samples" in csv and "来源哈希" in csv.decode("utf-8-sig")
