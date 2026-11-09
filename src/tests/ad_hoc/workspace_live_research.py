"""Actual 2024–2026 well-log search and source-derived files; no default data."""
import io
import json
import logging
import os
import sys
import tempfile
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
repo = Path(__file__).resolve().parents[3]
logging.disable(logging.CRITICAL)
operator_config = repo / "src/data/llm_config.json"
with tempfile.TemporaryDirectory(prefix="scholarscope-live-research-") as tmp:
    root = Path(tmp)
    if operator_config.exists():
        target = root / "llm_config.json"; target.write_bytes(operator_config.read_bytes()); target.chmod(0o600)
    os.environ["SCHOLARSCOPE_DATA_DIR"] = tmp
    os.environ["SCHOLARSCOPE_WORKSPACE_DIR"] = tmp
    os.environ["SCHOLARSCOPE_DISABLE_EMBEDDINGS"] = "1"
    from agent.orchestrator import Orchestrator
    from web.app import _get_llm_router
    from workspace.store import WorkspaceStore, WorkspaceError
    from workspace.documents import ObjectStore
    from workspace import research_tools, writing, presentations, review, sources
    from workspace.backup import backup_archive, restore_archive
    query = "近三年（2024–2026）基于测井曲线预测孔隙度、渗透率的深度学习方法，目标 30 篇；deep learning well logs porosity permeability prediction"
    engine = Orchestrator(llm_chat=_get_llm_router().get(), max_output=50, practical_limit=30, deadline_seconds=50, max_rounds=2, max_judge=24)
    result = engine.sync_run(query, "20261231")
    selected = []
    for p in result.get("papers", []):
        try: year = int(p.get("year"))
        except (ValueError, TypeError): continue
        if 2024 <= year <= 2026: selected.append(p)
    output = repo / ".cache/live-research"; output.mkdir(parents=True, exist_ok=True)
    store = WorkspaceStore(); pid = store.create_project("live-integration-check", "真实测井场景验收", query=query)["id"]
    objects = ObjectStore()
    imported = [store.add_paper(pid, "live-integration-check", p) for p in selected]
    summary = {"date": "2026-10-14", "query": query, "requested_count": 30, "actual_count": len(imported),
        "ranking_mode": result.get("stats", {}).get("ranking_mode"), "papers": [{"title": p["data"]["title"], "doi": p["data"].get("doi"), "year": p["data"].get("year"), "source": p["data"].get("source"), "reason": p["data"].get("recommendation_reason"), "evidence": p["data"].get("evidence")} for p in imported],
        "count_boundary": "实际匹配不足目标时保留真实数量；未补造论文。", "files": [], "pdfs": []}
    for p in imported[:3]:
        links = sources.oa_links(store, pid, "live-integration-check", p["id"])
        for link in links["links"][:1]:
            try:
                doc = sources.attach_remote_pdf(store, objects, pid, "live-integration-check", p["id"], link["url"])
                summary["pdfs"].append({"title": p["label"], "pages": doc["data"]["page_count"], "source_url": doc["data"]["source_url"]})
                break
            except WorkspaceError: pass
        if summary["pdfs"]: break
    matrix = research_tools.extract_matrix(store, pid, "live-integration-check")
    summary["evidence_count"] = len(store.items(pid, "live-integration-check", "evidence"))
    summary["verification"] = review.inspect_project(store, pid, "live-integration-check")
    if summary["evidence_count"]:
        manuscript = writing.generate_manuscript(store, pid, "live-integration-check", "review")
        deck = presentations.generate_deck(store, pid, "live-integration-check", "meeting")
        for item, formats in ((manuscript, ("docx", "pdf", "md")), (deck, ("pptx", "html"))):
            for fmt in formats:
                exporter = writing.export_manuscript if item["kind"] == "manuscript" else presentations.export_deck
                blob, _ = exporter(store, pid, "live-integration-check", item["id"], fmt)
                path = output / (item["kind"] + "." + fmt); path.write_bytes(blob); summary["files"].append(path.name)
                if fmt == "docx":
                    from docx import Document
                    assert Document(io.BytesIO(blob)).paragraphs
                if fmt == "pdf":
                    from pypdf import PdfReader
                    assert PdfReader(io.BytesIO(blob)).pages
                if fmt == "pptx":
                    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                        assert len([n for n in archive.namelist() if __import__('re').fullmatch(r"ppt/slides/slide\d+\.xml", n)]) == 12
        # Demonstrate source mutation invalidates the actual generated outputs.
        evidence = store.items(pid, "live-integration-check", "evidence")[0]
        store.add_evidence(pid, "live-integration-check", {**evidence["data"], "note": "Changed during real integration validation"}, evidence["id"], evidence["revision"])
        assert store.item(pid, "live-integration-check", manuscript["id"])["data"]["stale"]
        assert store.item(pid, "live-integration-check", deck["id"])["data"]["stale"]
        summary["dependency_invalidation"] = True
    else: summary["output_boundary"] = "没有可用原文证据，未生成虚构综述或 PPT。"
    store.set_member(pid, "live-integration-check", "second-reader", "viewer")
    reopened = WorkspaceStore(); assert len(reopened.items(pid, "second-reader", "paper")) == len(imported)
    try: reopened.put(pid, "second-reader", "review", "Unauthorized write", {})
    except WorkspaceError as error: assert error.status == 403
    else: raise AssertionError("Viewer wrote project data")
    archive = root / "backup.zip"; backup_archive(store, objects, archive)
    restored = WorkspaceStore("sqlite:///" + str(root / "restored.db"))
    restore_archive(restored, ObjectStore(root / "restored-objects"), archive)
    assert len(restored.items(pid, "second-reader", "paper")) == len(imported)
    summary["restart_and_restore"] = True
    summary["confirmation_boundary"] = "该验收为自动化集成检查；草稿摘录未冒称已由研究者逐项确认。"
    (output / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({k: summary[k] for k in ("requested_count", "actual_count", "ranking_mode", "evidence_count", "files", "pdfs", "restart_and_restore", "count_boundary")}, ensure_ascii=False, indent=2))
