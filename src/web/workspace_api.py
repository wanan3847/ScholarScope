"""Authenticated workspace endpoints; domain logic lives in workspace modules."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from workspace.store import WorkspaceError, get_store
from workspace.documents import MAX_UPLOAD, ObjectStore, attach_pdf
from workspace import research_tools as research
from workspace.knowledge import ProjectIndex
from workspace import writing
from workspace import presentations
from workspace import charts
from workspace import artifacts, review, skills, library, sources, zotero, monitoring
from workspace.runtime import get_runtime

router = APIRouter(prefix="/api/workspace", tags=["research workspace"])


def actor(request: Request):
    """Identity is derived from the session, never a username in client data."""
    authorization = request.headers.get("authorization", "")
    token = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
    if token:
        from agent.collections import verify_token
        username = verify_token(token)
        if not username:
            raise HTTPException(401, "登录状态已失效，请重新登录")
        return username
    return "web-anonymous"


def call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except WorkspaceError as e:
        raise HTTPException(e.status, str(e)) from None


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=10000)
    query: str = Field(default="", max_length=10000)


class ProjectUpdate(BaseModel):
    revision: int
    data: dict


class PaperCreate(BaseModel):
    paper: dict


class EvidenceCreate(BaseModel):
    data: dict
    revision: int | None = None


class MemberUpdate(BaseModel):
    username: str
    role: str


class MatrixColumns(BaseModel):
    columns: list[dict]
    revision: int


class MatrixExtract(BaseModel):
    paper_ids: list[str] | None = None
    column_ids: list[str] | None = None


class ResearchQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    paper_ids: list[str] | None = None


class ScreeningDecision(BaseModel):
    paper_id: str
    decision: str
    stage: str = "title_abstract"
    reason: str = Field(default="", max_length=5000)
    revision: int | None = None


class ManuscriptGenerate(BaseModel):
    template: str = "review"
    evidence_ids: list[str] | None = None


class ManuscriptComment(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    anchor: str = Field(default="", max_length=2000)


class DeckGenerate(BaseModel):
    purpose: str = "meeting"
    evidence_ids: list[str] | None = None


class TaskCreate(BaseModel):
    title: str = Field(default="", max_length=200)
    query: str = Field(default="", max_length=4000)
    search: bool = False
    deep: bool = False
    steps: list[dict] | None = None


class ZoteroConfig(BaseModel):
    library_type: str
    library_id: str
    collection_key: str = ""
    api_key: str = Field(default="", max_length=128)
    allow_write: bool = False


class ZoteroSync(BaseModel):
    direction: str = "pull"
    attachments: bool = False


class ZoteroConflict(BaseModel):
    choice: str


@router.get("/projects/{pid}/zotero")
def zotero_status(pid: str, user=Depends(actor)):
    return call(zotero.status, get_store(), pid, user)


@router.put("/projects/{pid}/zotero")
def zotero_config(pid: str, req: ZoteroConfig, user=Depends(actor)):
    return call(zotero.configure, get_store(), pid, user, req.model_dump())


@router.delete("/projects/{pid}/zotero")
def zotero_disconnect(pid: str, user=Depends(actor)):
    return call(zotero.disconnect, get_store(), pid, user)


@router.post("/projects/{pid}/zotero/sync")
def zotero_sync(pid: str, req: ZoteroSync, user=Depends(actor)):
    return call(zotero.sync, get_store(), pid, user, req.direction, req.attachments)


@router.post("/projects/{pid}/zotero/check")
def zotero_check(pid: str, user=Depends(actor)):
    return call(zotero.check_connection, get_store(), pid, user)


@router.post("/projects/{pid}/zotero/conflicts/{key}")
def zotero_conflict(pid: str, key: str, req: ZoteroConflict, user=Depends(actor)):
    return call(zotero.resolve, get_store(), pid, user, key, req.choice)


@router.get("/skills")
def skill_registry():
    return {"skills": call(skills.registry), "tools": skills.TOOLS}


@router.post("/projects/{pid}/monitors")
def monitor_save(pid: str, req: EvidenceCreate, user=Depends(actor)):
    return call(monitoring.save_monitor, get_store(), pid, user, req.data, req.data.get("id"), req.revision)


@router.post("/projects/{pid}/monitors/{mid}/check")
def monitor_check(pid: str, mid: str, user=Depends(actor)):
    runtime = get_runtime()
    task = call(monitoring.enqueue, runtime, pid, user, mid)
    runtime.start()
    return task


@router.get("/projects/{pid}/papers/{paper_id:path}/related")
def paper_related(pid: str, paper_id: str, user=Depends(actor)):
    return call(monitoring.related, get_store(), pid, user, paper_id)


@router.post("/projects/{pid}/workflows")
def save_workflow(pid: str, req: EvidenceCreate, user=Depends(actor)):
    store = get_store()
    def save():
        title = str(req.data.get("title", "")).strip()
        if not title or len(title) > 200: raise WorkspaceError("工作流需为 1–200 个字符的名称")
        planned = skills.plan(store, pid, user, {"steps": req.data.get("steps", [])})
        data = {"version": "1.0.0", "license": "project-authored", "steps": [{k: s[k] for k in ("id", "tool", "inputs", "confirm")} for s in planned], "updated_by": user}
        return store.put(pid, user, "workflow", title, data, req.data.get("id"), req.revision)
    return call(save)


@router.post("/projects/{pid}/tasks")
def task_create(pid: str, req: TaskCreate, user=Depends(actor)):
    runtime = get_runtime()
    task = call(runtime.create, pid, user, req.model_dump())
    runtime.start()
    return task


@router.get("/projects/{pid}/tasks")
def task_list(pid: str, user=Depends(actor)):
    return {"tasks": call(get_store().items, pid, user, "task")}


@router.post("/projects/{pid}/tasks/{tid}/{action}")
def task_action(pid: str, tid: str, action: str, user=Depends(actor)):
    runtime = get_runtime()
    result = call(runtime.action, pid, user, tid, action)
    runtime.start()
    return result


@router.post("/projects/{pid}/review")
def project_review(pid: str, critical: bool = True, user=Depends(actor)):
    return call(review.save_review, get_store(), pid, user, critical=critical)


@router.post("/projects/{pid}/artifacts")
def create_artifact(pid: str, req: EvidenceCreate, user=Depends(actor)):
    return call(artifacts.export_artifact, get_store(), ObjectStore(), pid, user, req.data.get("target_id"), req.data.get("format", "md"))


@router.get("/projects/{pid}/artifacts/{aid}/file")
def artifact_file(pid: str, aid: str, user=Depends(actor)):
    item = call(get_store().item, pid, user, aid, "artifact")
    blob, mime = call(artifacts.artifact_file, get_store(), ObjectStore(), pid, user, aid)
    return Response(blob, media_type=mime, headers={"Content-Disposition": f'attachment; filename="artifact.{item["data"]["format"]}"', "Cache-Control": "private, no-store"})


@router.get("/projects/{pid}/artifact-bundle")
def artifact_bundle(pid: str, user=Depends(actor)):
    blob, mime = call(artifacts.artifact_bundle, get_store(), ObjectStore(), pid, user)
    return Response(blob, media_type=mime, headers={"Content-Disposition": 'attachment; filename="research-artifacts.zip"', "Cache-Control": "private, no-store"})


@router.get("/projects")
def projects(archived: bool = False, user=Depends(actor)):
    return {"projects": call(get_store().projects, user, archived)}


@router.post("/projects")
def create_project(req: ProjectCreate, user=Depends(actor)):
    return call(get_store().create_project, user, **req.model_dump())


@router.get("/projects/{pid}")
def project(pid: str, user=Depends(actor)):
    return call(get_store().project, pid, user)


@router.patch("/projects/{pid}")
def update_project(pid: str, req: ProjectUpdate, user=Depends(actor)):
    return call(get_store().update_project, pid, user, req.data, req.revision)


@router.get("/projects/{pid}/members")
def members(pid: str, user=Depends(actor)):
    return {"members": call(get_store().members, pid, user)}


@router.put("/projects/{pid}/members")
def set_member(pid: str, req: MemberUpdate, user=Depends(actor)):
    from agent.collections import _load_users
    if not any(u.get("username") == req.username for u in _load_users().get("users", [])):
        raise HTTPException(400, "该账号尚未注册")
    return {"members": call(get_store().set_member, pid, user, req.username, req.role)}


@router.get("/projects/{pid}/items")
def items(pid: str, kind: str | None = None, user=Depends(actor)):
    # Credentials/configurations are never included in the generic data view.
    if kind == "integration":
        raise HTTPException(400, "连接配置请使用专用接口")
    rows = call(get_store().items, pid, user, kind)
    return {"items": [r for r in rows if r["kind"] != "integration"]}


@router.post("/projects/{pid}/papers")
def add_paper(pid: str, req: PaperCreate, user=Depends(actor)):
    return call(get_store().add_paper, pid, user, req.paper)


@router.post("/projects/{pid}/doi")
def project_doi(pid: str, req: EvidenceCreate, user=Depends(actor)):
    store = get_store()
    def add():
        with store.engine.connect() as conn: store._access(conn, pid, user, edit=True)
        return store.add_paper(pid, user, sources.lookup_doi(req.data.get("doi", "")))
    return call(add)


@router.get("/projects/{pid}/papers/{paper_id:path}/oa")
def project_oa(pid: str, paper_id: str, user=Depends(actor)):
    return call(sources.oa_links, get_store(), pid, user, paper_id)


@router.post("/projects/{pid}/papers/{paper_id:path}/remote-pdf")
def remote_pdf(pid: str, paper_id: str, req: EvidenceCreate, user=Depends(actor)):
    return call(sources.attach_remote_pdf, get_store(), ObjectStore(), pid, user, paper_id, req.data.get("url", ""))


@router.put("/projects/{pid}/papers/{paper_id:path}/organization")
def organize_paper(pid: str, paper_id: str, req: EvidenceCreate, user=Depends(actor)):
    return call(library.organize_paper, get_store(), pid, user, paper_id, req.data, req.revision)


@router.post("/projects/{pid}/collections")
def project_collection(pid: str, req: EvidenceCreate, user=Depends(actor)):
    return call(library.create_collection, get_store(), pid, user, req.data.get("title", ""))


@router.post("/projects/{pid}/paper-import")
def project_import(pid: str, req: EvidenceCreate, user=Depends(actor)):
    return call(library.import_papers, get_store(), pid, user, req.data.get("papers"))


@router.get("/projects/{pid}/references/export/{fmt}")
def project_references_export(pid: str, fmt: str, collection_id: str | None = None, user=Depends(actor)):
    blob, mime = call(library.export_references, get_store(), pid, user, fmt, collection_id)
    return Response(blob, media_type=mime, headers={"Content-Disposition": f'attachment; filename="project-references.{fmt}"', "Cache-Control": "private, no-store"})


@router.get("/projects/{pid}/matrix/export/{fmt}")
def project_matrix_export(pid: str, fmt: str, user=Depends(actor)):
    blob, mime = call(library.export_matrix, get_store(), pid, user, fmt)
    return Response(blob, media_type=mime, headers={"Content-Disposition": f'attachment; filename="evidence-matrix.{fmt}"', "Cache-Control": "private, no-store"})


@router.delete("/projects/{pid}/items/{item_id}")
def remove_item(pid: str, item_id: str, user=Depends(actor)):
    call(get_store().remove, pid, user, item_id)
    return {"status": "ok"}


@router.post("/projects/{pid}/evidence")
def add_evidence(pid: str, req: EvidenceCreate, user=Depends(actor)):
    return call(get_store().add_evidence, pid, user, req.data)


@router.put("/projects/{pid}/evidence/{eid}")
def update_evidence(pid: str, eid: str, req: EvidenceCreate, user=Depends(actor)):
    return call(get_store().add_evidence, pid, user, req.data, eid, req.revision)


@router.get("/projects/{pid}/evidence/{eid}/verify")
def verify_evidence(pid: str, eid: str, user=Depends(actor)):
    return call(get_store().verify_evidence, pid, user, eid)


@router.get("/projects/{pid}/events")
def events(pid: str, user=Depends(actor)):
    return {"events": call(get_store().events, pid, user)}


@router.post("/projects/{pid}/papers/{paper_id:path}/pdf")
def upload_pdf(pid: str, paper_id: str, file: UploadFile = File(...), user=Depends(actor)):
    blob = file.file.read(MAX_UPLOAD + 1)
    return call(attach_pdf, get_store(), ObjectStore(), pid, user, paper_id, file.filename or "paper.pdf", blob)


@router.get("/projects/{pid}/documents/{did}/file")
def document_file(pid: str, did: str, user=Depends(actor)):
    d = call(get_store().item, pid, user, did, "document")
    blob = call(ObjectStore().get, d["data"]["object_key"])
    return Response(blob, media_type="application/pdf", headers={"Content-Disposition": "inline; filename=paper.pdf", "Cache-Control": "private, no-store"})


@router.get("/projects/{pid}/documents/{did}")
def document(pid: str, did: str, user=Depends(actor)):
    return call(get_store().item, pid, user, did, "document")


@router.get("/projects/{pid}/matrix")
def matrix(pid: str, user=Depends(actor)):
    return call(research.matrix, get_store(), pid, user)


@router.put("/projects/{pid}/matrix/columns")
def matrix_columns(pid: str, req: MatrixColumns, user=Depends(actor)):
    return call(research.set_columns, get_store(), pid, user, req.columns, req.revision)


@router.post("/projects/{pid}/matrix/extract")
def matrix_extract(pid: str, req: MatrixExtract, user=Depends(actor)):
    return call(research.extract_matrix, get_store(), pid, user, req.paper_ids, req.column_ids)


@router.put("/projects/{pid}/matrix/cells/{cid}")
def matrix_cell(pid: str, cid: str, req: EvidenceCreate, user=Depends(actor)):
    return call(research.edit_cell, get_store(), pid, user, cid, req.data, req.revision)


@router.post("/projects/{pid}/retrieve")
def retrieve(pid: str, req: ResearchQuestion, user=Depends(actor)):
    return call(ProjectIndex(get_store()).retrieve, pid, user, req.question, paper_ids=req.paper_ids)


@router.post("/projects/{pid}/index")
def rebuild_index(pid: str, user=Depends(actor)):
    store = get_store()
    def rebuild():
        with store.engine.connect() as conn:
            store._access(conn, pid, user, edit=True)
        rows = ProjectIndex(store).ensure(pid, user, rebuild_vectors=True)
        return {"chunks": len(rows), "semantic_chunks": sum(r["embedding"] is not None for r in rows)}
    return call(rebuild)


@router.post("/projects/{pid}/questions")
def question(pid: str, req: ResearchQuestion, user=Depends(actor)):
    return call(research.answer_question, get_store(), pid, user, req.question, req.paper_ids)


@router.get("/projects/{pid}/screening")
def screening(pid: str, user=Depends(actor)):
    return call(research.screening, get_store(), pid, user)


@router.post("/projects/{pid}/screening/suggestions")
def screening_suggestions(pid:str,user=Depends(actor)):
    return call(research.suggest_screening,get_store(),pid,user)


@router.post("/projects/{pid}/acquire")
def acquire_sources(pid:str,user=Depends(actor)):
    from workspace.deep_research import acquire
    result=call(acquire,get_store(),pid,user)
    call(get_store().put,pid,user,"acquisition_report","开放全文获取记录",result)
    return result


@router.put("/projects/{pid}/screening/criteria")
def screening_criteria(pid: str, req: ProjectUpdate, user=Depends(actor)):
    return call(research.set_screening_criteria, get_store(), pid, user, req.data, req.revision)


@router.post("/projects/{pid}/screening")
def screening_decision(pid: str, req: ScreeningDecision, user=Depends(actor)):
    return call(research.record_screening, get_store(), pid, user, **req.model_dump())


@router.get("/writing-templates")
def writing_templates():
    return {"templates": writing.TEMPLATES}


@router.get("/projects/{pid}/writing-templates")
def project_writing_templates(pid: str, user=Depends(actor)):
    store = get_store()
    return {"templates": call(writing.templates, store, pid, user), "project_revision": call(store.project, pid, user)["revision"]}


@router.put("/projects/{pid}/writing-templates")
def project_writing_template(pid: str, req: ProjectUpdate, user=Depends(actor)):
    return call(writing.set_template, get_store(), pid, user, req.data, req.revision)


@router.post("/projects/{pid}/manuscripts/generate")
def generate_manuscript(pid: str, req: ManuscriptGenerate, user=Depends(actor)):
    return call(writing.generate_manuscript, get_store(), pid, user, req.template, req.evidence_ids)


@router.post("/projects/{pid}/manuscripts")
def create_manuscript(pid: str, req: EvidenceCreate, user=Depends(actor)):
    return call(writing.save_manuscript, get_store(), pid, user, req.data)


@router.get("/projects/{pid}/manuscripts/{mid}")
def manuscript(pid: str, mid: str, user=Depends(actor)):
    store = get_store()
    return call(lambda: writing.manuscript_view(store, pid, user, store.item(pid, user, mid, "manuscript")))


@router.put("/projects/{pid}/manuscripts/{mid}")
def save_manuscript(pid: str, mid: str, req: EvidenceCreate, user=Depends(actor)):
    return call(writing.save_manuscript, get_store(), pid, user, req.data, mid, req.revision)


@router.get("/projects/{pid}/manuscripts/{mid}/versions")
def manuscript_versions(pid: str, mid: str, user=Depends(actor)):
    return {"versions": call(writing.versions, get_store(), pid, user, mid)}


@router.post("/projects/{pid}/manuscripts/{mid}/restore")
def restore_manuscript(pid: str, mid: str, req: EvidenceCreate, user=Depends(actor)):
    return call(writing.restore_version, get_store(), pid, user, mid, req.data.get("version_id"), req.revision)


@router.get("/projects/{pid}/manuscripts/{mid}/export/{fmt}")
def manuscript_export(pid: str, mid: str, fmt: str, user=Depends(actor)):
    blob, mime = call(writing.export_manuscript, get_store(), pid, user, mid, fmt)
    return Response(blob, media_type=mime, headers={"Content-Disposition": f'attachment; filename="manuscript.{fmt}"', "Cache-Control": "private, no-store"})


@router.post("/projects/{pid}/manuscripts/{mid}/comments")
def manuscript_comment(pid: str, mid: str, req: ManuscriptComment, user=Depends(actor)):
    return call(writing.add_comment, get_store(), pid, user, mid, req.text, req.anchor)


@router.get("/presentation-templates")
def presentation_templates():
    return {"themes": presentations.THEMES, "purposes": presentations.PURPOSES}


@router.put("/projects/{pid}/presentation-brand")
def presentation_brand(pid: str, req: ProjectUpdate, user=Depends(actor)):
    return call(presentations.set_brand, get_store(), pid, user, req.data, req.revision)


@router.post("/projects/{pid}/presentations/generate")
def generate_presentation(pid: str, req: DeckGenerate, user=Depends(actor)):
    return call(presentations.generate_deck, get_store(), pid, user, req.purpose, req.evidence_ids)


@router.post("/projects/{pid}/presentations")
def create_presentation(pid: str, req: EvidenceCreate, user=Depends(actor)):
    return call(presentations.save_deck, get_store(), pid, user, req.data)


@router.get("/projects/{pid}/presentations/{did}")
def presentation(pid: str, did: str, user=Depends(actor)):
    store = get_store()
    return call(lambda: presentations.deck_view(store, pid, user, store.item(pid, user, did, "presentation")))


@router.put("/projects/{pid}/presentations/{did}")
def save_presentation(pid: str, did: str, req: EvidenceCreate, user=Depends(actor)):
    return call(presentations.save_deck, get_store(), pid, user, req.data, did, req.revision)


@router.get("/projects/{pid}/presentations/{did}/versions")
def presentation_versions(pid: str, did: str, user=Depends(actor)):
    store = get_store()
    call(store.item, pid, user, did, "presentation")
    return {"versions": sorted([r for r in call(store.items, pid, user, "presentation_version") if r["data"]["presentation_id"] == did], key=lambda r: r["data"]["version"], reverse=True)}


@router.post("/projects/{pid}/presentations/{did}/restore")
def presentation_restore(pid: str, did: str, req: EvidenceCreate, user=Depends(actor)):
    store = get_store()
    v = call(store.item, pid, user, req.data.get("version_id"), "presentation_version")
    if v["data"]["presentation_id"] != did:
        raise HTTPException(400, "版本不属于当前演示文稿")
    return call(presentations.save_deck, store, pid, user, v["data"]["snapshot"], did, req.revision)


@router.get("/projects/{pid}/presentations/{did}/export/{fmt}")
def presentation_export(pid: str, did: str, fmt: str, user=Depends(actor)):
    blob, mime = call(presentations.export_deck, get_store(), pid, user, did, fmt)
    return Response(blob, media_type=mime, headers={"Content-Disposition": f'attachment; filename="research-slides.{fmt}"', "Cache-Control": "private, no-store"})


@router.post("/projects/{pid}/charts")
def create_chart(pid: str, req: EvidenceCreate, user=Depends(actor)):
    return call(charts.save_chart, get_store(), pid, user, req.data)


@router.put("/projects/{pid}/charts/{cid}")
def save_chart(pid: str, cid: str, req: EvidenceCreate, user=Depends(actor)):
    return call(charts.save_chart, get_store(), pid, user, req.data, cid, req.revision)


@router.get("/projects/{pid}/charts/{cid}")
def chart(pid: str, cid: str, user=Depends(actor)):
    store = get_store()
    return call(lambda: charts.chart_view(store, pid, user, store.item(pid, user, cid, "chart")))


@router.get("/projects/{pid}/charts/{cid}/export/{fmt}")
def chart_export(pid: str, cid: str, fmt: str, user=Depends(actor)):
    blob, mime = call(charts.export_chart, get_store(), pid, user, cid, fmt)
    return Response(blob, media_type=mime, headers={"Content-Disposition": f'inline; filename="research-chart.{fmt}"', "Cache-Control": "private, no-store"})


@router.get("/projects/{pid}/documents/{did}/tables/{page}/{tid}")
def table_analysis(pid: str, did: str, page: int, tid: str, user=Depends(actor)):
    return call(charts.element_analysis, get_store(), pid, user, did, page, "table", tid)


@router.get("/projects/{pid}/documents/{did}/elements/{page}/{kind}/{eid}")
def element_analysis(pid: str, did: str, page: int, kind: str, eid: str, user=Depends(actor)):
    return call(charts.element_analysis, get_store(), pid, user, did, page, kind, eid)


@router.post("/projects/{pid}/documents/{did}/elements/{page}/{kind}/{eid}/analyze")
def interpret_element(pid:str,did:str,page:int,kind:str,eid:str,user=Depends(actor)):
    return call(charts.element_analysis,get_store(),pid,user,did,page,kind,eid,visual=True)
