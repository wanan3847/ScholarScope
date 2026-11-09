import io
import json
import stat
import zipfile
import pytest
from workspace.store import WorkspaceStore, WorkspaceError
from workspace.documents import ObjectStore, attach_pdf
from workspace.backup import backup_archive, restore_archive
from workspace.knowledge import ProjectIndex
from workspace.migrations import versions


def test_portable_backup_restore_real_objects_and_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHOLARSCOPE_DISABLE_EMBEDDINGS", "1")
    source = WorkspaceStore("sqlite:///" + str(tmp_path / "source.db")); objects = ObjectStore(tmp_path / "original")
    p = source.create_project("alice", "Backup project")
    paper = source.add_paper(p["id"], "alice", {"title": "Controlled backup document", "abstract": "The dataset contains 120 samples."})
    from reportlab.pdfgen.canvas import Canvas
    blob = io.BytesIO(); c = Canvas(blob); c.drawString(50, 750, "The dataset contains 120 samples."); c.save()
    doc = attach_pdf(source, objects, p["id"], "alice", paper["id"], "source.pdf", blob.getvalue())
    e = source.add_evidence(p["id"], "alice", {"paper_id": paper["id"], "document_id": doc["id"], "page": 1, "quote": "The dataset contains 120 samples."})
    source.set_member(p["id"], "alice", "bob", "viewer")
    ProjectIndex(source).retrieve(p["id"], "alice", "dataset")
    runtime = tmp_path / "runtime"; runtime.mkdir(); (runtime / "users.json").write_text('{"users":[]}')
    from workspace.vault import IntegrationVault
    IntegrationVault(runtime).put("alice", p["id"], {"api_key": "controlled-private-backup-only"})
    output = tmp_path / "backup.zip"
    result = backup_archive(source, objects, output, runtime)
    assert result == {"projects": 1, "items": 3, "objects": 1}
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    dest = WorkspaceStore("sqlite:///" + str(tmp_path / "restored.db")); target_objects = ObjectStore(tmp_path / "restored"); target_runtime = tmp_path / "restored-runtime"
    assert restore_archive(dest, target_objects, output, target_runtime)["projects"] == 1
    assert dest.verify_evidence(p["id"], "bob", e["id"])["valid"]
    assert target_objects.get(doc["data"]["object_key"]) == blob.getvalue()
    assert (target_runtime / "users.json").read_text() == '{"users":[]}'
    assert IntegrationVault(target_runtime).get("alice", p["id"])["api_key"] == "controlled-private-backup-only"
    assert stat.S_IMODE((target_runtime / "integrations.key").stat().st_mode) == 0o600
    assert ProjectIndex(dest).retrieve(p["id"], "alice", "dataset")["passages"]
    assert [v["version"] for v in versions(dest.engine)] == [1, 2]
    with pytest.raises(WorkspaceError) as error:
        restore_archive(dest, target_objects, output)
    assert error.value.status == 409
    with pytest.raises(WorkspaceError):
        backup_archive(source, objects, output)


def test_tampered_file_rejected_before_restore(tmp_path):
    store = WorkspaceStore("sqlite:///" + str(tmp_path / "empty.db")); objects = ObjectStore(tmp_path / "dest")
    from workspace.backup import dump_database
    data = dump_database(store)
    fake_key = "00/" + "0" * 64 + ".pdf"
    data["tables"]["research_items"] = [{"kind": "document", "data": {"object_key": fake_key}}]
    source = tmp_path / "bad.zip"
    with zipfile.ZipFile(source, "w") as z:
        z.writestr("database.json", json.dumps(data)); z.writestr("objects/" + fake_key, b"tampered")
    with pytest.raises(WorkspaceError):
        restore_archive(store, objects, source)
    assert not objects.root.exists()
