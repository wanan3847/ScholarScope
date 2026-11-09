import time
import pytest
from workspace.store import WorkspaceStore, WorkspaceError
from workspace.runtime import TaskRuntime
from workspace import monitoring


def test_saved_query_seen_vs_new_years_persistence_and_acl(tmp_path):
    store = WorkspaceStore("sqlite:///" + str(tmp_path / "monitor.db")); pid = store.create_project("alice", "Monitor")["id"]
    old = store.add_paper(pid, "alice", {"title": "Controlled existing source", "doi": "10.1000/existing", "year": 2024})
    monitor = monitoring.save_monitor(store, pid, "alice", {"query": "neural well logs", "year_from": 2024, "year_to": 2026, "add_new": True})
    rows = [old["data"], {"title": "Controlled discovered source", "doi": "10.1000/new", "year": 2025, "abstract": "Actual source abstract.", "evidence": "source abstract", "score": 999}, {"title": "Excluded old source", "doi": "10.1000/old", "year": 2020}]
    search = lambda q, n, hi: {"papers": rows}
    first = monitoring.check_monitor(store, pid, "alice", monitor["id"], "first-check", search=search)
    assert first["data"]["new_count"] == 1 and first["data"]["actual_count"] == 2
    assert "score" not in first["data"]["papers"][1]["paper"] and len(store.items(pid, "alice", "paper")) == 2
    assert monitoring.check_monitor(store, pid, "alice", monitor["id"], "first-check", search=search)["id"] == first["id"]
    reopened = WorkspaceStore("sqlite:///" + str(tmp_path / "monitor.db"))
    second = monitoring.check_monitor(reopened, pid, "alice", monitor["id"], "second-check", search=search)
    assert second["data"]["new_count"] == 0
    empty = monitoring.check_monitor(store, pid, "alice", monitor["id"], "empty", search=lambda *a: {"papers": []})
    assert empty["data"]["actual_count"] == 0 and "未补造" in empty["data"]["message"]
    store.set_member(pid, "alice", "reader", "viewer")
    with pytest.raises(WorkspaceError): monitoring.check_monitor(store, pid, "reader", monitor["id"], search=search)
    with pytest.raises(WorkspaceError): store.items(pid, "outsider", "monitor")


def test_scheduled_checks_claim_once_recover_pending_and_can_disable(tmp_path):
    store = WorkspaceStore("sqlite:///" + str(tmp_path / "schedule.db")); pid = store.create_project("alice", "Schedule")["id"]
    m = monitoring.save_monitor(store, pid, "alice", {"query": "saved research query", "interval_hours": 24})
    m = store.put(pid, "alice", "monitor", m["label"], {**m["data"], "next_due": time.time() - 1}, m["id"], m["revision"])
    runtime = TaskRuntime(store)
    monitoring.enqueue_due(runtime); monitoring.enqueue_due(runtime)
    assert len(store.items(pid, "alice", "task")) == 1
    m = store.item(pid, "alice", m["id"])
    assert m["data"]["task_id"] and m["data"]["next_due"] > time.time()
    assert monitoring.enqueue(runtime, pid, "alice", m["id"])["id"] == m["data"]["task_id"]
    monitoring.save_monitor(store, pid, "alice", {**m["data"], "interval_hours": 0}, m["id"], m["revision"])
    assert store.item(pid, "alice", m["id"])["data"]["next_due"] is None
    # A reservation interrupted before task creation is recovered after restart.
    m2 = monitoring.save_monitor(store, pid, "alice", {"query": "another query"})
    store.put(pid, "alice", "monitor", m2["label"], {**m2["data"], "queue_pending": True, "queue_token": "controlled-recovery", "queued_at": time.time() - 61}, m2["id"], m2["revision"])
    monitoring.enqueue_due(TaskRuntime(WorkspaceStore("sqlite:///" + str(tmp_path / "schedule.db"))))
    assert len(store.items(pid, "alice", "task")) == 2


def test_exploration_only_displays_provider_recorded_references(tmp_path, monkeypatch):
    store = WorkspaceStore("sqlite:///" + str(tmp_path / "related.db")); pid = store.create_project("alice", "Related")["id"]
    p = store.add_paper(pid, "alice", {"title": "Controlled selected source", "doi": "10.1000/related"})
    class Response:
        status_code = 200
        def __init__(self, data): self.data = data
        def json(self): return self.data
    def get(url, **kw):
        if "/works/" in url: return Response({"referenced_works": ["https://openalex.org/W123", "https://evil.example/private"]})
        assert kw["params"]["filter"] == "openalex_id:W123"
        return Response({"results": [{"id": "https://openalex.org/W123", "title": "Controlled cited source", "publication_year": 2024, "doi": "https://doi.org/10.1000/cited", "authorships": [], "cited_by_count": 10000}, {"id": "https://openalex.org/W999", "title": "Unrelated response"}]})
    monkeypatch.setattr(monitoring.requests, "get", get)
    result = monitoring.related(store, pid, "alice", p["id"])
    assert len(result["papers"]) == 1 and result["papers"][0]["relation"] == "referenced_by_selected"
    assert "citations" not in result["papers"][0]["paper"]
