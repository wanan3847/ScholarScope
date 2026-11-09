"""Black-box user journeys against the real ASGI app, without socket/listen access.

Only storage locations and model availability are isolated. HTTP endpoints,
auth, database, workers, parsers and exporters are real. This does not certify
browser interactions or cloud/model quality. See docs/testing/user-acceptance.md.
"""
import io
import json
import re
import subprocess
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas

pytestmark = pytest.mark.user_acceptance
PASSWORD = "ControlledUserJourneyPassword123"
QUOTE = "The dataset contains 120 samples."
PAPER = {
    "title": "Controlled acceptance fixture: well-log prediction",
    "doi": "10.1000/acceptance/slash-id", "year": 2025,
    "authors": ["Controlled Author"],
    "abstract": "We propose a neural network for permeability from well logs. "
    + QUOTE + " Results show RMSE of 0.08. However, validation is limited to one field.",
}


class Journey:
    def __init__(self, client, tokens, directory):
        self.client, self.tokens, self.directory = client, tokens, directory
        self.root = "/api/workspace/projects/" + self.json("POST", "/api/workspace/projects", {
            "title": "Controlled user acceptance project", "query": "neural well logs samples",
        })["id"]

    def response(self, method, path, data=None, *, actor="owner", status=200, **kwargs):
        headers = {"Authorization": "Bearer " + self.tokens[actor]} if actor else {}
        if data is not None: kwargs["json"] = data
        result = self.client.request(method, path, headers=headers, **kwargs)
        assert result.status_code == status, f"{method} {path}: expected {status}, got {result.status_code}"
        return result

    def json(self, method, path, data=None, **kwargs):
        return self.response(method, path, data, **kwargs).json()

    def material(self, pdf=False):
        paper = self.json("POST", self.root + "/papers", {"paper": PAPER})
        if not pdf: return paper, None
        out = io.BytesIO(); canvas = Canvas(out)
        canvas.drawString(50, 750, "1. Methods")
        canvas.drawString(50, 710, "We propose a neural network for permeability from well logs.")
        canvas.drawString(50, 670, "RMSE = sqrt(mean squared error)")
        canvas.showPage(); canvas.drawString(50, 750, "2. Results")
        canvas.drawString(50, 710, QUOTE); canvas.save()
        doc = self.json("POST", self.root + "/papers/" + paper["id"] + "/pdf",
            files={"file": ("controlled-paper.pdf", out.getvalue(), "application/pdf")})
        return paper, doc

    def extract(self):
        return self.json("POST", self.root + "/matrix/extract", {})

    def evidence(self):
        self.extract()
        return next(e for e in self.json("GET", self.root + "/items?kind=evidence")["items"] if e["data"]["field"] == "sample_size")


@pytest.fixture
def user_journey(tmp_path, monkeypatch):
    import agent.collections as accounts
    import web.app as web
    import workspace.store as store
    import workspace.runtime as runtime
    from llm.router import LLMRouter
    for attr, name in [("_USERS_FILE", "users.json"), ("_COLLECTIONS_FILE", "collections.json"),
            ("_READ_PAPERS_FILE", "read.json"), ("_PAPER_CACHE_FILE", "cache.json")]:
        monkeypatch.setattr(accounts, attr, tmp_path / name)
    monkeypatch.setenv("SCHOLARSCOPE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SCHOLARSCOPE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("SCHOLARSCOPE_DATABASE_URL", "sqlite:///" + str(tmp_path / "workspace.sqlite3"))
    monkeypatch.setenv("SCHOLARSCOPE_DISABLE_EMBEDDINGS", "1")
    monkeypatch.setenv("SCHOLARSCOPE_DISABLE_AI", "1")
    for key in list(__import__("os").environ):
        if key.startswith("SCHOLARSCOPE_S3") or key in ("DEEPSEEK_API_KEY", "SAKURA_ADMIN_PASSWORD"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SAKURA_ADMIN_USER", "uat-admin")
    monkeypatch.setenv("SAKURA_ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setattr(store, "_store", None)
    monkeypatch.setattr(runtime, "_instance", None)
    monkeypatch.setattr(web, "_llm_router", LLMRouter())
    monkeypatch.setattr(web, "_LLM_CONFIG_FILE", tmp_path / "llm_config.json")
    with TestClient(web.app) as client:
        tokens = {}
        for name in ("owner", "editor", "viewer", "outsider"):
            result = client.post("/api/auth/register", json={"username": "uat-" + name, "password": PASSWORD})
            assert result.status_code == 200
            tokens[name] = result.json()["token"]
        admin = client.post("/api/auth/login", json={"username": "uat-admin", "password": PASSWORD})
        assert admin.status_code == 200
        tokens["admin"] = admin.json()["token"]
        yield Journey(client, tokens, tmp_path)
    if store._store: store._store.engine.dispose()


def test_u01_register_login_change_password_and_logout(user_journey):
    j = user_journey
    assert j.json("GET", "/api/auth/me")["username"] == "uat-owner"
    j.response("POST", "/api/auth/register", {"username": "uat-owner", "password": PASSWORD}, status=400)
    j.response("POST", "/api/auth/login", {"username": "uat-owner", "password": "wrong"}, actor=None, status=401)
    j.json("POST", "/api/auth/change-password", {"token": j.tokens["owner"], "old_password": PASSWORD, "new_password": PASSWORD + "Changed"})
    j.response("POST", "/api/auth/login", {"username": "uat-owner", "password": PASSWORD}, actor=None, status=401)
    fresh = j.json("POST", "/api/auth/login", {"username": "uat-owner", "password": PASSWORD + "Changed"}, actor=None)
    j.tokens["owner"] = fresh["token"]
    j.json("POST", "/api/auth/logout")
    assert not j.json("GET", "/api/auth/me")["logged_in"]
    j.response("GET", j.root, status=401)


def test_u02_private_favorites_folders_read_and_doi_routes(user_journey):
    j = user_journey; doi = PAPER["doi"]
    folder = j.json("POST", "/api/folders", {"name": "Methods"})["folder"]
    j.json("PUT", "/api/folders/default", {"folder_id": folder["id"]})
    j.json("POST", "/api/favorites/" + doi, {"paper_meta": PAPER})
    j.json("POST", "/api/read_papers/" + doi)
    assert j.json("GET", "/api/favorites")["favorites"][0]["folder_id"] == folder["id"]
    assert doi in [p["paper_id"] for p in j.json("GET", "/api/read_papers")["papers"]]
    assert j.json("GET", "/api/favorites?user_id=uat-owner", actor="outsider")["total"] == 0
    assert j.json("GET", "/api/read_papers?user_id=uat-owner", actor="outsider")["papers"] == []
    j.json("PUT", "/api/folders/" + folder["id"], {"name": "Reviewed methods"})
    j.json("DELETE", "/api/folders/" + folder["id"])
    assert j.json("GET", "/api/folders/default")["folder_id"] == ""
    j.json("DELETE", "/api/read_papers/" + doi)
    j.json("DELETE", "/api/favorites/" + doi)
    assert j.json("GET", "/api/favorites")["total"] == 0


def test_u03_project_edit_archive_members_and_conflict(user_journey):
    j = user_journey
    p = j.json("GET", j.root)
    changed = j.json("PATCH", j.root, {"revision": p["revision"], "data": {"description": "Persistent researcher notes"}})
    j.response("PATCH", j.root, {"revision": p["revision"], "data": {"description": "Stale edit"}}, status=409)
    j.json("PUT", j.root + "/members", {"username": "uat-editor", "role": "editor"})
    assert j.json("GET", j.root, actor="editor")["description"] == "Persistent researcher notes"
    j.response("PUT", j.root + "/members", {"username": "uat-viewer", "role": "viewer"}, actor="editor", status=403)
    j.response("GET", j.root, actor="outsider", status=404)
    p = j.json("GET", j.root)
    j.json("PATCH", j.root, {"revision": p["revision"], "data": {"archived": True}})
    assert not j.json("GET", "/api/workspace/projects")["projects"]
    assert len(j.json("GET", "/api/workspace/projects?archived=true")["projects"]) == 1


def test_u04_import_dedupe_organization_and_reference_files(user_journey):
    j = user_journey; paper, _ = j.material()
    j.json("POST", j.root + "/paper-import", {"data": {"papers": [PAPER, PAPER]}})
    assert len(j.json("GET", j.root + "/items?kind=paper")["items"]) == 1
    collection = j.json("POST", j.root + "/collections", {"data": {"title": "Neural methods"}})
    p = j.json("GET", j.root + "/items?kind=paper")["items"][0]
    j.json("PUT", j.root + "/papers/" + p["id"] + "/organization", {"revision": p["revision"], "data": {
        "tags": ["neural", "well logs"], "collection_ids": [collection["id"]], "favorite": True, "read": True}})
    for fmt in ("bib", "ris", "json", "csv"):
        r = j.response("GET", j.root + "/references/export/" + fmt)
        assert PAPER["doi"] in r.text and "private" in r.headers["cache-control"]
    j.response("GET", j.root + "/references/export/invalid", status=400)


def test_u05_pdf_upload_actual_bytes_pages_and_invalid_upload(user_journey):
    from pypdf import PdfReader
    j = user_journey; paper, doc = j.material(pdf=True)
    assert doc["data"]["page_count"] == 2
    assert QUOTE in doc["data"]["pages"][1]["text"]
    download = j.response("GET", j.root + "/documents/" + doc["id"] + "/file")
    assert len(PdfReader(io.BytesIO(download.content)).pages) == 2
    assert "no-store" in download.headers["cache-control"]
    j.response("GET", j.root + "/documents/" + doc["id"] + "/file", actor="outsider", status=404)
    j.response("POST", j.root + "/papers/" + paper["id"] + "/pdf", files={"file": ("fake.pdf", b"Not a PDF", "application/pdf")}, status=400)
    assert len(j.json("GET", j.root + "/items?kind=document")["items"]) == 1


def test_u06_page_evidence_confirmation_and_forged_quote(user_journey):
    j = user_journey; paper, doc = j.material(pdf=True)
    data = {"paper_id": paper["id"], "document_id": doc["id"], "page": 2, "quote": QUOTE, "confirmed": True}
    evidence = j.json("POST", j.root + "/evidence", {"data": data})
    assert j.json("GET", j.root + "/evidence/" + evidence["id"] + "/verify")["valid"]
    assert evidence["data"]["confirmed_by"] == "uat-owner"
    j.response("POST", j.root + "/evidence", {"data": {**data, "quote": "The dataset contains 999 samples."}}, status=400)
    assert len(j.json("GET", j.root + "/items?kind=evidence")["items"]) == 1


def test_u07_matrix_custom_columns_manual_review_rerun_and_files(user_journey):
    from openpyxl import load_workbook
    j = user_journey; j.material(pdf=True)
    m = j.extract(); cell = m["rows"][0]["cells"]["sample_size"]
    assert cell["value"] == "120 samples" and cell["source_valid"]
    j.json("PUT", j.root + "/matrix/cells/" + cell["id"], {"revision": cell["revision"], "data": {
        **cell["evidence"]["data"], "value": "120 samples (human checked)", "confirmed": True}})
    assert j.extract()["rows"][0]["cells"]["sample_size"]["value"] == "120 samples (human checked)"
    csv = j.response("GET", j.root + "/matrix/export/csv").text
    assert "120 samples (human checked)" in csv
    xlsx = load_workbook(io.BytesIO(j.response("GET", j.root + "/matrix/export/xlsx").content))
    assert xlsx.sheetnames == ["证据矩阵", "原文出处"]
    p = j.json("GET", j.root)
    j.json("PUT", j.root + "/matrix/columns", {"revision": p["revision"], "columns": [
        {"id": "sample_size", "label": "Sample size"}, {"id": "custom", "label": "Field limits", "description": "limited field"}]})
    assert "custom" in j.extract()["rows"][0]["cells"]


def test_u08_question_sources_no_evidence_and_viewer_read_only(user_journey):
    j = user_journey
    empty = j.json("POST", j.root + "/questions", {"question": "What dataset contains samples?"})
    assert not empty["citations"] and "没有找到足够依据" in empty["answer"]
    j.material(pdf=True)
    answer = j.json("POST", j.root + "/questions", {"question": "What dataset contains samples?"})
    assert answer["data"]["citations"] and "evidence_excerpts" in answer["data"]["mode"]
    for c in answer["data"]["citations"]:
        assert c["quote"] in PAPER["abstract"] or c["quote"] == "RMSE = sqrt(mean squared error)"
    j.json("PUT", j.root + "/members", {"username": "uat-viewer", "role": "viewer"})
    before = len(j.json("GET", j.root + "/items")["items"])
    result = j.json("POST", j.root + "/questions", {"question": "What dataset contains samples?"}, actor="viewer")
    assert result["citations"] and len(j.json("GET", j.root + "/items")["items"]) == before


def test_u09_two_reviewer_screening_and_separate_suggestions(user_journey):
    j = user_journey; paper, _ = j.material()
    j.json("PUT", j.root + "/members", {"username": "uat-editor", "role": "editor"})
    p = j.json("GET", j.root)
    j.json("PUT", j.root + "/screening/criteria", {"revision": p["revision"], "data": {
        "include": "Neural well-log prediction", "exclude": "Non well-log studies", "reviewers": 2}})
    j.json("POST", j.root + "/screening/suggestions")
    assert not j.json("GET", j.root + "/items?kind=screening")["items"]
    j.json("POST", j.root + "/screening", {"paper_id": paper["id"], "decision": "include", "reason": "Methods match"})
    result = j.json("POST", j.root + "/screening", {"paper_id": paper["id"], "decision": "exclude", "reason": "Needs full-text decision"}, actor="editor")
    assert result["rows"][0]["status"] == "conflict"
    j.response("POST", j.root + "/screening", {"paper_id": paper["id"], "decision": "invalid"}, status=400)


def test_u10_writer_edit_conflict_comment_restore_and_real_exports(user_journey):
    from docx import Document
    from pypdf import PdfReader
    j = user_journey; j.material(); j.extract()
    m = j.json("POST", j.root + "/manuscripts/generate", {})
    assert m["data"]["generation_mode"] == "verified_evidence_draft" and m["citations"]
    versions = j.json("GET", j.root + "/manuscripts/" + m["id"] + "/versions")["versions"]
    changed = j.json("PUT", j.root + "/manuscripts/" + m["id"], {"revision": m["revision"], "data": {**m["data"], "title": "Researcher revised review"}})
    j.response("PUT", j.root + "/manuscripts/" + m["id"], {"revision": m["revision"], "data": m["data"]}, status=409)
    j.json("POST", j.root + "/manuscripts/" + m["id"] + "/comments", {"text": "Check samples before submission"})
    restored = j.json("POST", j.root + "/manuscripts/" + m["id"] + "/restore", {"revision": changed["revision"], "data": {"version_id": versions[0]["id"]}})
    assert restored["revision"] == 3 and restored["label"] == m["label"]
    path = j.root + "/manuscripts/" + m["id"] + "/export/"
    assert PAPER["doi"] in j.response("GET", path + "md").text
    doc = Document(io.BytesIO(j.response("GET", path + "docx").content))
    assert "120 samples" in "\n".join(p.text for p in doc.paragraphs)
    pdf = PdfReader(io.BytesIO(j.response("GET", path + "pdf").content))
    assert "120 samples" in "\n".join(p.extract_text() for p in pdf.pages)


def test_u11_presentation_edit_versions_native_pptx_and_html_escape(user_journey):
    j = user_journey; j.material(); j.extract()
    deck = j.json("POST", j.root + "/presentations/generate", {})
    assert len(deck["data"]["slides"]) == 12
    data = json.loads(json.dumps(deck["data"]))
    data["slides"][0]["title"] = "<script>controlled</script>"
    edited = j.json("PUT", j.root + "/presentations/" + deck["id"], {"revision": deck["revision"], "data": data})
    assert edited["revision"] == 2
    j.response("PUT", j.root + "/presentations/" + deck["id"], {"revision": deck["revision"], "data": data}, status=409)
    path = j.root + "/presentations/" + deck["id"] + "/export/"
    html = j.response("GET", path + "html").text
    assert "<script>controlled</script>" not in html and "&lt;script&gt;" in html
    z = zipfile.ZipFile(io.BytesIO(j.response("GET", path + "pptx").content))
    slides = [n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
    text = "\n".join(z.read(n).decode() for n in slides)
    assert len(slides) == 12 and "<p:sp>" in text and "120 samples" in text


def test_u12_chart_valid_numbers_native_reuse_and_rejected_fabrication(user_journey):
    from PIL import Image
    j = user_journey; j.material(); e = j.evidence()
    spec = {"title": "Reported samples", "type": "bar", "labels": ["Study"], "origin": "reported",
        "x_label": "Study", "y_label": "Sample count (samples)", "series": [{"name": "Samples", "values": [120], "evidence_ids": [e["id"]]}]}
    chart = j.json("POST", j.root + "/charts", {"data": spec})
    j.response("POST", j.root + "/charts", {"data": {**spec, "series": [{"name": "Samples", "values": [999], "evidence_ids": [e["id"]]}]}}, status=400)
    assert Image.open(io.BytesIO(j.response("GET", j.root + "/charts/" + chart["id"] + "/export/png").content)).width >= 2000
    assert "Sample count" in j.response("GET", j.root + "/charts/" + chart["id"] + "/export/svg").text
    deck = j.json("POST", j.root + "/presentations", {"data": {"title": "Reused reported data", "slides": [{"title": "Reported samples", "layout": "chart", "chart_id": chart["id"], "bullets": []}]}})
    pptx = zipfile.ZipFile(io.BytesIO(j.response("GET", j.root + "/presentations/" + deck["id"] + "/export/pptx").content))
    assert any(n.startswith("ppt/charts/") and n.endswith(".xml") for n in pptx.namelist())
    assert any(n.endswith(".xlsx") for n in pptx.namelist())


def test_u13_source_changes_stale_manuscript_deck_and_artifact(user_journey):
    j = user_journey; j.material(); j.extract()
    m = j.json("POST", j.root + "/manuscripts/generate", {})
    deck = j.json("POST", j.root + "/presentations/generate", {})
    artifact = j.json("POST", j.root + "/artifacts", {"data": {"target_id": m["id"], "format": "docx"}})
    j.response("GET", j.root + "/artifacts/" + artifact["id"] + "/file")
    bundle = zipfile.ZipFile(io.BytesIO(j.response("GET", j.root + "/artifact-bundle").content))
    assert json.loads(bundle.read("sources.json"))["artifacts"][0]["sources"]
    e = next(e for e in j.json("GET", j.root + "/items?kind=evidence")["items"] if e["id"] in m["data"]["evidence_ids"])
    j.json("PUT", j.root + "/evidence/" + e["id"], {"revision": e["revision"], "data": {**e["data"], "note": "Rechecked"}})
    assert j.json("GET", j.root + "/manuscripts/" + m["id"])["data"]["stale"]
    assert j.json("GET", j.root + "/presentations/" + deck["id"])["data"]["stale"]
    j.response("GET", j.root + "/artifacts/" + artifact["id"] + "/file", status=409)


def test_u14_viewer_permission_matrix_downloads_and_revocation(user_journey):
    j = user_journey; paper, doc = j.material(pdf=True)
    j.json("PUT", j.root + "/members", {"username": "uat-viewer", "role": "viewer"})
    for path in (j.root, j.root + "/items", j.root + "/matrix", j.root + "/documents/" + doc["id"] + "/file"):
        j.response("GET", path, actor="viewer")
    for method, suffix, payload in [("POST", "/papers", {"paper": PAPER}), ("POST", "/matrix/extract", {}),
            ("POST", "/manuscripts/generate", {}), ("POST", "/presentations/generate", {}),
            ("POST", "/tasks", {"title": "Forbidden"}), ("PUT", "/zotero", {"library_type": "users", "library_id": "123", "api_key": "ControlledZoteroKey123456"})]:
        j.response(method, j.root + suffix, payload, actor="viewer", status=403)
    j.json("PUT", j.root + "/members", {"username": "uat-viewer", "role": "remove"})
    j.response("GET", j.root, actor="viewer", status=404)


def test_u15_model_settings_real_admin_boundary_saved_key_and_priority(user_journey):
    j = user_journey
    assert all(p["models"] for p in j.json("GET", "/api/llm/presets")["presets"])
    setup = {"provider": "deepseek", "model": "deepseek-flash", "api_key": "ControlledConfigOnlyKey123456", "priority": 30}
    j.response("POST", "/api/llm/register_preset", setup, status=403)
    j.json("POST", "/api/llm/register_preset", setup, actor="admin")
    j.json("POST", "/api/llm/register_preset", {**setup, "api_key": "", "priority": 40}, actor="admin")
    assert "ControlledConfigOnlyKey" not in j.response("GET", "/api/llm/models").text
    saved = json.loads((j.directory / "llm_config.json").read_text())
    assert saved[0]["api_key"] == setup["api_key"] and saved[0]["priority"] == 40
    j.json("POST", "/api/llm/unregister/deepseek", actor="admin")
    assert not j.json("GET", "/api/llm/models")["models"]


def test_u16_zotero_saved_not_verified_private_encrypted_and_writes_disabled(user_journey):
    j = user_journey
    config = {"library_type": "users", "library_id": "123", "api_key": "ControlledZoteroKey123456", "allow_write": False}
    result = j.json("PUT", j.root + "/zotero", config)
    assert result["configured"] and result["connection_check"] is None
    assert config["api_key"] not in json.dumps(result)
    assert config["api_key"].encode() not in (j.directory / "integrations.json").read_bytes()
    j.json("PUT", j.root + "/members", {"username": "uat-editor", "role": "editor"})
    assert not j.json("GET", j.root + "/zotero", actor="editor")["configured"]
    report = j.json("POST", j.root + "/zotero/sync", {"direction": "push"})
    assert report["last_report"]["errors"] and not report["last_report"]["exported"]
    j.json("DELETE", j.root + "/zotero")
    assert not j.json("GET", j.root + "/zotero")["configured"]


def test_u17_monitor_workflow_validation_and_fulltext_already_available(user_journey):
    j = user_journey; j.material(pdf=True)
    monitor = j.json("POST", j.root + "/monitors", {"data": {"query": "Neural well logs", "year_from": 2024, "year_to": 2026, "interval_hours": 0}})
    assert monitor["data"]["next_due"] is None and not monitor["data"]["interval_hours"]
    workflow = j.json("POST", j.root + "/workflows", {"data": {"title": "Source check", "steps": [{"id": "matrix", "tool": "matrix"}]}})
    assert workflow["data"]["steps"][0]["tool"] == "matrix"
    j.response("POST", j.root + "/workflows", {"data": {"title": "Invalid tool", "steps": [{"tool": "shell"}]}}, status=400)
    assert len(j.json("GET", "/api/workspace/skills")["skills"]) == 10
    acquired = j.json("POST", j.root + "/acquire")
    assert acquired["records"][0]["status"] == "already_available"


def test_u18_task_actual_workers_confirmation_and_output_files(user_journey):
    j = user_journey; j.material()
    task = j.json("POST", j.root + "/tasks", {"title": "Controlled full research task", "steps": [
        {"id": "matrix", "tool": "matrix"}, {"id": "verify", "tool": "verify"},
        {"id": "draft", "tool": "manuscript"}, {"id": "word", "tool": "export", "inputs": {"target_id": {"from_step": "draft"}, "format": "docx"}}]})
    def until(statuses):
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            current = next(t for t in j.json("GET", j.root + "/tasks")["tasks"] if t["id"] == task["id"])
            if current["data"]["status"] in statuses: return current
            time.sleep(.05)
        pytest.fail("Task did not reach expected user-visible status within 25 seconds")
    waiting = until({"awaiting_confirmation", "failed"})
    assert waiting["data"]["status"] == "awaiting_confirmation"
    assert not j.json("GET", j.root + "/items?kind=manuscript")["items"]
    j.json("POST", j.root + "/tasks/" + task["id"] + "/approve")
    done = until({"completed", "failed"})
    assert done["data"]["status"] == "completed"
    artifact = j.json("GET", j.root + "/items?kind=artifact")["items"][0]
    z = zipfile.ZipFile(io.BytesIO(j.response("GET", j.root + "/artifacts/" + artifact["id"] + "/file").content))
    assert b"120 samples" in z.read("word/document.xml")


def test_u19_invalid_search_and_private_network_inputs(user_journey):
    j = user_journey; paper, _ = j.material()
    j.response("POST", "/api/search", {"query": " "}, status=422)
    j.response("POST", "/api/search", {"query": "well logs", "year_from": 2026, "year_to": 2024}, status=422)
    j.response("POST", j.root + "/papers/" + paper["id"] + "/remote-pdf", {"data": {"url": "http://127.0.0.1/private.pdf"}}, status=400)
    j.response("POST", j.root + "/questions", {"question": ""}, status=422)
    assert not j.json("GET", j.root + "/items?kind=document")["items"]


@pytest.mark.parametrize("fmt", ["bib", "ris", "json", "csv"])
def test_u20_actual_frontend_file_parser_and_api_roundtrip(user_journey, fmt):
    j = user_journey
    original = {**PAPER, "title": '受控文献：孔隙度, 渗透率与 "模型"', "authors": ["Researcher A", "张三"]}
    source = j.json("POST", j.root + "/papers", {"paper": original})
    blob = j.response("GET", j.root + "/references/export/" + fmt).content
    path = j.directory / ("references." + fmt); path.write_bytes(blob)
    module = Path(__file__).resolve().parents[2] / "frontend/src/import.js"
    code = "import fs from 'node:fs'; const {parseImport}=await import(process.argv[1]); process.stdout.write(JSON.stringify(parseImport(fs.readFileSync(process.argv[2],'utf8'),process.argv[2])));"
    parsed = json.loads(subprocess.run(["node", "--input-type=module", "-e", code, module.as_uri(), str(path)], check=True, capture_output=True, text=True).stdout)
    assert len(parsed) == 1 and parsed[0]["doi"] == original["doi"]
    assert parsed[0]["title"] == source["data"]["title"] and parsed[0]["year"] == original["year"]
    assert QUOTE in parsed[0]["abstract"]
    target = "/api/workspace/projects/" + j.json("POST", "/api/workspace/projects", {"title": "Imported bibliography"})["id"]
    for _ in range(2): j.json("POST", target + "/paper-import", {"data": {"papers": parsed}})
    imported = j.json("GET", target + "/items?kind=paper")["items"]
    assert len(imported) == 1 and imported[0]["data"]["doi"] == original["doi"]


def test_u21_search_provider_fault_is_sanitized_and_does_not_return_fake_papers(user_journey, monkeypatch, caplog):
    """Inject an external-stage exception, exercising the actual HTTP failure path."""
    import web.app as web
    marker = "ControlledSensitiveProviderMarker123456"
    class FailedProvider:
        def __init__(self, **kwargs): pass
        def sync_run(self, *args): raise RuntimeError(marker)
    monkeypatch.setattr(web, "Orchestrator", FailedProvider)
    response = user_journey.client.post("/api/search", json={"query": "neural well logs"})
    assert response.status_code == 503
    assert marker not in response.text and marker not in caplog.text
    assert "papers" not in response.json()
