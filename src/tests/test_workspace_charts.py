import io
import zipfile
import pytest
from PIL import Image
from workspace.store import WorkspaceStore, WorkspaceError
from workspace import charts, presentations


@pytest.fixture
def chart(tmp_path):
    store = WorkspaceStore("sqlite:///" + str(tmp_path / "charts.sqlite3"))
    p = store.create_project("alice", "Metric comparison")
    paper = store.add_paper(p["id"], "alice", {"title": "Controlled metric source", "doi": "10.1000/chart", "abstract": "The neural model achieves RMSE of 0.08. A baseline reports RMSE of 0.12."})
    e1 = store.add_evidence(p["id"], "alice", {"paper_id": paper["id"], "quote": "The neural model achieves RMSE of 0.08.", "field": "metrics", "confirmed": True})
    e2 = store.add_evidence(p["id"], "alice", {"paper_id": paper["id"], "quote": "A baseline reports RMSE of 0.12.", "field": "metrics", "confirmed": True})
    c = charts.save_chart(store, p["id"], "alice", {"title": "Controlled RMSE", "type": "bar", "labels": ["Neural", "Baseline"],
        "series": [{"name": "RMSE", "values": [.08, .12], "evidence_ids": [e1["id"], e2["id"]]}], "origin": "reported", "x_label": "Method", "y_label": "RMSE (unit not reported)"})
    return store, p["id"], c, e1


def test_numbers_must_be_reported_and_units_explicit(chart):
    store, pid, c, e = chart
    assert c["validation"]["invalid_sources"] == 0
    with pytest.raises(WorkspaceError):
        charts.save_chart(store, pid, "alice", {**c["data"], "series": [{"name": "Fake improvement", "values": [.01, .12], "evidence_ids": c["data"]["series"][0]["evidence_ids"]}]})
    with pytest.raises(WorkspaceError):
        charts.save_chart(store, pid, "alice", {**c["data"], "series": [{"values": [.08, .12]}]})
    with pytest.raises(WorkspaceError):
        charts.save_chart(store, pid, "alice", {**c["data"], "y_label": ""})
    derived = charts.save_chart(store, pid, "alice", {**c["data"], "origin": "derived", "provenance_note": "Researcher normalization to baseline; this is not directly reported.", "series": [{"name": "Normalized", "values": [.08 / .12, 1], "evidence_ids": c["data"]["series"][0]["evidence_ids"]}]})
    assert derived["data"]["origin"] == "derived"


def test_actual_svg_png_include_axes_values_and_provenance(chart):
    store, pid, c, e = chart
    svg, mime = charts.export_chart(store, pid, "alice", c["id"], "svg")
    assert mime == "image/svg+xml" and b"Controlled RMSE" in svg and b"unit not reported" in svg
    assert b"Controlled metric source" in svg and e["id"].encode() in svg
    png, _ = charts.export_chart(store, pid, "alice", c["id"], "png")
    image = Image.open(io.BytesIO(png))
    assert image.width >= 2000 and image.height >= 1000
    assert "Controlled metric source" in image.info["Description"]


def test_native_ppt_chart_reuse_and_source_invalidation(chart):
    store, pid, c, e = chart
    deck = presentations.save_deck(store, pid, "alice", {"title": "Chart reuse", "slides": [{"title": "RMSE comparison", "layout": "chart", "chart_id": c["id"], "bullets": []}], "theme": presentations.THEMES[0]})
    assert deck["data"]["chart_ids"] == [c["id"]]
    assert deck["citations"] and deck["data"]["evidence_ids"]
    blob, _ = presentations.export_deck(store, pid, "alice", deck["id"], "pptx")
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        chart_files = [n for n in z.namelist() if n.startswith("ppt/charts/chart") and n.endswith(".xml")]
        assert chart_files and "0.08" in z.read(chart_files[0]).decode()
        assert any(n.endswith(".xlsx") for n in z.namelist())
    changed = charts.save_chart(store, pid, "alice", {**c["data"], "title": "Revised chart title"}, c["id"], c["revision"])
    updated = presentations.deck_view(store, pid, "alice", store.item(pid, "alice", deck["id"], "presentation"))
    assert updated["data"]["stale"] and updated["validation"]["invalid_charts"] == 1
    store.add_evidence(pid, "alice", {**e["data"], "confirmed": True, "note": "Rechecked"}, e["id"], e["revision"])
    with pytest.raises(WorkspaceError) as error:
        charts.export_chart(store, pid, "alice", c["id"], "svg")
    assert error.value.status == 409
