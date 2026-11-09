import io
import time
import zipfile
import pytest
from workspace.store import WorkspaceStore, WorkspaceError
from workspace.runtime import TaskRuntime, OperationStore, execute_tool
from workspace import research_tools, writing, skills, artifacts
from workspace.documents import ObjectStore


@pytest.fixture
def runtime_project(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHOLARSCOPE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("SCHOLARSCOPE_DATA_DIR", str(tmp_path / "accounts"))
    monkeypatch.setenv("SCHOLARSCOPE_DISABLE_EMBEDDINGS", "1")
    store = WorkspaceStore("sqlite:///" + str(tmp_path / "tasks.sqlite3"))
    project = store.create_project("alice", "Controlled task", query="neural well logs samples")
    paper = store.add_paper(project["id"], "alice", {"title": "Controlled neural task fixture", "doi": "10.1000/runtime-fixture",
        "abstract": "We propose a neural network for well logs. The dataset contains 120 samples. Results show RMSE of 0.08. However, validation is limited to one field."})
    store.set_member(project["id"], "alice", "bob", "viewer")
    return store, project["id"], paper


def until(runtime, pid, tid, statuses, timeout=20):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        row = runtime.store.item(pid, "alice", tid, "task")
        if row["data"]["status"] in statuses: return row
        time.sleep(.05)
    raise AssertionError("Task did not reach expected status: " + str(row["data"]))


def test_actual_process_checkpoint_restart_outputs_and_private_artifacts(runtime_project):
    store, pid, _ = runtime_project
    runtime = TaskRuntime(store, poll_seconds=.05)
    task = runtime.create(pid, "alice", {"steps": [
        {"id": "matrix", "tool": "matrix"}, {"id": "verify", "tool": "verify"},
        {"id": "draft", "tool": "manuscript"},
        {"id": "word", "tool": "export", "inputs": {"target_id": {"from_step": "draft"}, "format": "docx"}},
    ]})
    runtime.start()
    try:
        waiting = until(runtime, pid, task["id"], {"awaiting_confirmation", "failed"})
        assert waiting["data"]["status"] == "awaiting_confirmation"
        assert waiting["data"]["steps"][1]["result"]["report"]["valid"]
        assert not store.items(pid, "alice", "manuscript")
        with pytest.raises(WorkspaceError) as error: runtime.action(pid, "bob", task["id"], "approve")
        assert error.value.status == 403
    finally: runtime.stop()
    reopened = WorkspaceStore(str(store.engine.url))
    resumed = TaskRuntime(reopened, poll_seconds=.05)
    resumed.action(pid, "alice", task["id"], "approve")
    resumed.start()
    try:
        done = until(resumed, pid, task["id"], {"completed", "failed"})
        assert done["data"]["status"] == "completed"
        assert done["data"]["approvals"][0]["actor"] == "alice"
        assert len(done["data"]["outputs"]) == 2
        artifact = reopened.items(pid, "alice", "artifact")[0]
        blob, mime = artifacts.artifact_file(reopened, ObjectStore(), pid, "bob", artifact["id"])
        with zipfile.ZipFile(io.BytesIO(blob)) as z: assert b"120 samples" in z.read("word/document.xml")
        bundle, _ = artifacts.artifact_bundle(reopened, ObjectStore(), pid, "alice")
        with zipfile.ZipFile(io.BytesIO(bundle)) as z: assert "sources.json" in z.namelist()
        with pytest.raises(WorkspaceError): artifacts.artifact_file(reopened, ObjectStore(), pid, "mallory", artifact["id"])
        assert len(reopened.items(pid, "alice", "manuscript_version")) == 1
    finally: resumed.stop()


def test_confirmation_rechecks_changed_source_and_cancel_resume(runtime_project):
    store, pid, _ = runtime_project
    research_tools.extract_matrix(store, pid, "alice")
    runtime = TaskRuntime(store, poll_seconds=.05)
    task = runtime.create(pid, "alice", {"steps": [{"id": "verify", "tool": "verify"}]})
    runtime.start()
    try:
        until(runtime, pid, task["id"], {"awaiting_confirmation"})
        e = store.items(pid, "alice", "evidence")[0]
        store.add_evidence(pid, "alice", {**e["data"], "value": "Researcher corrected value"}, e["id"], e["revision"])
        with pytest.raises(WorkspaceError) as error: runtime.action(pid, "alice", task["id"], "approve")
        assert error.value.status == 409
        runtime.action(pid, "alice", task["id"], "recheck")
        until(runtime, pid, task["id"], {"awaiting_confirmation"})
        runtime.action(pid, "alice", task["id"], "cancel")
        assert store.item(pid, "alice", task["id"])["data"]["status"] == "cancelled"
        runtime.action(pid, "alice", task["id"], "resume")
        # A cancelled confirmation must return to its saved checkpoint.
        waiting = until(runtime, pid, task["id"], {"awaiting_confirmation", "failed"})
        assert waiting["data"]["status"] == "awaiting_confirmation"
    finally: runtime.stop()


def test_budgets_worker_cancellation_leases_and_no_duplicate_outputs(runtime_project):
    store, pid, _ = runtime_project
    research_tools.extract_matrix(store, pid, "alice")
    op = "controlled-operation:manuscript"
    first = execute_tool(OperationStore(str(store.engine.url), op), pid, "alice", "manuscript", {})
    second = execute_tool(OperationStore(str(store.engine.url), op), pid, "alice", "manuscript", {})
    assert first["output_id"] == second["output_id"] and len(store.items(pid, "alice", "manuscript_version")) == 1
    runtime = TaskRuntime(store, poll_seconds=.05)
    task = runtime.create(pid, "alice", {"steps": [{"id": "question", "tool": "question", "inputs": {"question": "well logs"}}]})
    data = task["data"]; data["steps"][0]["budget_seconds"] = .001
    store.put(pid, "alice", "task", task["label"], data, task["id"], task["revision"])
    runtime.start()
    try:
        failed = until(runtime, pid, task["id"], {"failed"})
        assert "预算" in failed["data"]["message"]
        assert failed["data"]["lease"] is None
        assert not store.items(pid, "alice", "answer")
        pending = runtime.create(pid, "alice", {"steps": [{"id": "q", "tool": "question", "inputs": {"question": "well logs"}}]})
        runtime.action(pid, "alice", pending["id"], "cancel")
        assert store.item(pid, "alice", pending["id"])["data"]["status"] == "cancelled"
    finally: runtime.stop()


def test_registry_contracts_and_source_invalidation(runtime_project):
    store, pid, paper = runtime_project
    registered = skills.registry()
    assert len(registered) == 10 and all(__import__('re').fullmatch(r"\d+\.\d+\.\d+",s["version"]) and s["license"] == "MIT" for s in registered)
    lookup=next(s for s in registered if s["id"]=="paper-lookup")
    assert {"research","acquire"} <= set(lookup["contracts"])
    assert next(s for s in registered if s["id"] == "pyzotero")["available"]
    runtime = TaskRuntime(store)
    for steps in ([{"id": "shell", "tool": "shell", "inputs": {"command": "unsafe"}}],
                  [{"id": "a", "tool": "export", "inputs": {"target_id": {"from_step": "later"}}}],
                  [{"id": "a", "tool": "manuscript"}]):
        with pytest.raises(WorkspaceError): runtime.create(pid, "alice", {"steps": steps})
    research_tools.extract_matrix(store, pid, "alice")
    draft = writing.generate_manuscript(store, pid, "alice")
    artifact = artifacts.export_artifact(store, ObjectStore(), pid, "alice", draft["id"], "md")
    store.add_paper(pid, "alice", {**paper["data"], "abstract": "Changed source text."})
    with pytest.raises(WorkspaceError) as error: artifacts.artifact_file(store, ObjectStore(), pid, "alice", artifact["id"])
    assert error.value.status == 409


def test_live_step_cancel_and_expired_restart_recovery(runtime_project):
    store, pid, _ = runtime_project
    runtime = TaskRuntime(store, poll_seconds=.03)
    task = runtime.create(pid, "alice", {"steps": [{"id": "question", "tool": "question", "inputs": {"question": "well logs"}}]})
    runtime.start()
    try:
        until(runtime, pid, task["id"], {"running"})
        cancelled = runtime.action(pid, "alice", task["id"], "cancel")
        assert cancelled["data"]["status"] == "cancelled"
        end = time.monotonic() + 5
        while time.monotonic() < end:
            cancelled = store.item(pid, "alice", task["id"])
            if not cancelled["data"].get("lease"): break
            time.sleep(.05)
        assert cancelled["data"]["lease"] is None
        assert cancelled["data"]["status"] == "cancelled"
    finally: runtime.stop()
    interrupted = runtime.create(pid, "alice", {"steps": [{"id": "matrix", "tool": "matrix"}]})
    d = interrupted["data"]
    d.update(status="running", lease="terminated-process", lease_until=time.time() - 60)
    d["steps"][0].update(status="running", attempts=1)
    store.put(pid, "alice", "task", interrupted["label"], d, interrupted["id"], interrupted["revision"])
    second = TaskRuntime(WorkspaceStore(str(store.engine.url)), poll_seconds=.03)
    second.start()
    try:
        until(second, pid, interrupted["id"], {"interrupted"})
        second.action(pid, "alice", interrupted["id"], "resume")
        done = until(second, pid, interrupted["id"], {"completed", "failed"})
        assert done["data"]["status"] == "completed"
        assert done["data"]["steps"][0]["attempts"] == 2
    finally: second.stop()
