"""Private exported artifacts retain their source revisions and real bytes."""
import io
import json
import zipfile
from workspace.store import WorkspaceError
from workspace.documents import ObjectStore
from workspace import writing, presentations, charts, research_tools


def export_artifact(store, objects, pid, actor, target_id, fmt):
    item = store.item(pid, actor, target_id)
    kind = item["kind"]
    exporters = {"manuscript": writing.export_manuscript, "presentation": presentations.export_deck, "chart": charts.export_chart}
    if kind not in exporters:
        raise WorkspaceError("该资料不支持此产物导出")
    if item["data"].get("stale"):
        raise WorkspaceError("来源已变化，请核对并保存产物后导出", 409)
    blob, mime = exporters[kind](store, pid, actor, target_id, fmt)
    file = objects.put(blob, fmt)
    sources = []
    for eid in item["data"].get("evidence_ids", []):
        e = store.item(pid, actor, eid, "evidence")
        if not store.verify_evidence(pid, actor, eid)["valid"]:
            raise WorkspaceError("产物含失效证据，请先核对", 409)
        sources.append({"evidence_id": eid, "revision": e["revision"], "source_hash": e["data"]["source_hash"],
            "paper_id": e["data"]["paper_id"], "document_id": e["data"].get("document_id"), "page": e["data"].get("page"), "quote": e["data"]["quote"]})
    return store.put(pid, actor, "artifact", item["label"] + "." + fmt, {**file, "mime": mime, "format": fmt,
        "target_id": target_id, "target_kind": kind, "target_revision": item["revision"], "sources": sources,
        "evidence_ids": item["data"].get("evidence_ids", []), "chart_ids": item["data"].get("chart_ids", []), "stale": False})


def artifact_file(store, objects, pid, actor, aid):
    item = store.item(pid, actor, aid, "artifact")
    d = item["data"]
    target = store.item(pid, actor, d["target_id"])
    if d.get("stale") or target["revision"] != d["target_revision"]:
        raise WorkspaceError("来源或产物版本已变化，请重新生成导出文件", 409)
    for source in d["sources"]:
        current = store.item(pid, actor, source["evidence_id"], "evidence")
        if current["revision"] != source["revision"] or not store.verify_evidence(pid, actor, current["id"])["valid"]:
            raise WorkspaceError("导出文件引用已变化，请重新生成", 409)
    return objects.get(d["object_key"]), d["mime"]


def artifact_bundle(store, objects, pid, actor, ids=None):
    rows = [r for r in store.items(pid, actor, "artifact") if ids is None or r["id"] in ids]
    if not rows:
        raise WorkspaceError("项目尚无已保存的导出产物")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        manifest = []
        for r in rows:
            blob, _ = artifact_file(store, objects, pid, actor, r["id"])
            name = r["id"] + "." + r["data"]["format"]
            z.writestr(name, blob)
            manifest.append({"file": name, "title": r["label"], **r["data"]})
        z.writestr("sources.json", json.dumps({"project_id": pid, "artifacts": manifest}, ensure_ascii=False, indent=2))
    return out.getvalue(), "application/zip"
