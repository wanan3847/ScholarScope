import copy
import io
import json
import pytest
from reportlab.pdfgen.canvas import Canvas
from workspace.store import WorkspaceStore, WorkspaceError
from workspace.documents import ObjectStore
from workspace.vault import IntegrationVault
from workspace import zotero, skills


class Response:
    def __init__(self, data=None, status=200, version=2, blob=None):
        self.data, self.status_code, self.blob = data, status, blob
        self.headers = {"Last-Modified-Version": str(version)}
    def json(self): return copy.deepcopy(self.data)
    def iter_content(self, size): yield self.blob
    def close(self): pass


class API:
    def __init__(self, pdf):
        self.calls = []; self.pdf = pdf; self.version = 2
        self.items = {"ABCD2345": {"key": "ABCD2345", "version": 2, "data": {"itemType": "journalArticle", "title": "Controlled Zotero source", "DOI": "10.1000/zotero-source", "abstractNote": "The dataset contains 120 samples.", "creators": [{"creatorType": "author", "name": "Test Author"}], "date": "2025", "publicationTitle": "Controlled venue", "url": "", "tags": [{"tag": "well-log"}], "collections": ["COLL2345"]}}}
        self.attachment = {"key": "FILE2345", "version": 2, "data": {"itemType": "attachment", "parentItem": "ABCD2345", "contentType": "application/pdf", "linkMode": "imported_file", "filename": "controlled.pdf"}}
        self.status = None; self.crash_after_post = False
    def request(self, method, url, **kw):
        self.calls.append((method, url, copy.deepcopy(kw)))
        assert kw["headers"]["Zotero-API-Version"] == "3" and url.startswith("https://api.zotero.org/users/123")
        assert kw.get("allow_redirects") is False
        if self.status: return Response({}, self.status)
        path = url.split("/users/123", 1)[1]
        if path == "/collections": return Response([{"key": "COLL2345", "data": {"name": "Controlled collection"}}])
        if path.endswith("/file"): return Response(blob=self.pdf)
        if path.endswith("/children"): return Response([self.attachment])
        if method == "GET" and path == "/items":
            since = kw["params"].get("since", 0)
            return Response([i for i in self.items.values() if i["version"] > since], version=self.version)
        key = path.rsplit("/", 1)[-1]
        if method == "GET": return Response(self.items[key], version=self.items[key]["version"]) if key in self.items else Response({}, 404)
        if method == "PATCH":
            assert int(kw["headers"]["If-Unmodified-Since-Version"]) == self.items[key]["version"]
            self.items[key]["data"].update(kw["json"]); self.version += 1; self.items[key]["version"] = self.version
            return Response(status=204, version=self.version)
        if method == "POST":
            assert len(kw["headers"]["Zotero-Write-Token"]) == 32
            d = kw["json"][0]; key = d["key"]; self.version += 1
            self.items[key] = {"key": key, "version": self.version, "data": d}
            if self.crash_after_post:
                self.crash_after_post = False
                import requests
                raise requests.ConnectionError("Controlled disconnect")
            return Response({"successful": {"0": self.items[key]}})
        raise AssertionError(method + path)


@pytest.fixture
def setup(tmp_path):
    store = WorkspaceStore("sqlite:///" + str(tmp_path / "zotero.db")); pid = store.create_project("alice", "Sync")["id"]
    vault = IntegrationVault(tmp_path / "private")
    out = io.BytesIO(); c = Canvas(out); c.drawString(50, 700, "The dataset contains 120 samples."); c.save()
    api = API(out.getvalue()); factory = lambda r: zotero.ZoteroClient(r, session=api)
    config = {"library_type": "users", "library_id": "123", "api_key": "ControlledContractOnlyKey123456", "allow_write": True}
    zotero.configure(store, pid, "alice", config, vault)
    return store, pid, vault, api, factory, ObjectStore(tmp_path / "objects")


def test_account_encryption_incremental_pdf_tags_collections_and_acl(setup):
    store, pid, vault, api, factory, objects = setup
    result = zotero.sync(store, pid, "alice", attachments=True, vault=vault, client_factory=factory, objects=objects)
    assert result["last_report"]["complete"] and result["last_report"]["attachments"] == 1
    papers = store.items(pid, "alice", "paper"); assert len(papers) == 1
    assert papers[0]["data"]["tags"] == ["well-log"] and papers[0]["data"]["collection_ids"]
    assert store.items(pid, "alice", "document")[0]["data"]["page_count"] == 1
    assert b"ControlledContractOnlyKey" not in (vault.root / "integrations.json").read_bytes()
    assert (vault.root / "integrations.key").stat().st_mode & 0o777 == 0o600
    assert "api_key" not in json.dumps(result) and "ControlledContractOnlyKey" not in json.dumps(store.events(pid, "alice"))
    reopened = IntegrationVault(vault.root)
    again = zotero.sync(store, pid, "alice", attachments=True, vault=reopened, client_factory=factory, objects=objects)
    assert again["version"] == 2 and again["last_report"]["imported"] == 0 and len(store.items(pid, "alice", "document")) == 1
    store.set_member(pid, "alice", "bob", "editor")
    assert zotero.status(store, pid, "bob", vault)["configured"] is False
    store.set_member(pid, "alice", "reader", "viewer")
    with pytest.raises(WorkspaceError): zotero.status(store, pid, "reader", vault)
    with pytest.raises(WorkspaceError): zotero.status(store, pid, "web-anonymous", vault)
    assert len(skills.registry()) == 10 and all(s["available"] for s in skills.registry())


def test_two_sided_changes_require_explicit_resolution_and_versioned_push(setup):
    store, pid, vault, api, factory, objects = setup
    zotero.sync(store, pid, "alice", vault=vault, client_factory=factory)
    p = store.items(pid, "alice", "paper")[0]
    store.put(pid, "alice", "paper", "Local revised title", {**p["data"], "title": "Local revised title"}, p["id"], p["revision"])
    api.items["ABCD2345"]["data"]["title"] = "Remote revised title"; api.items["ABCD2345"]["version"] = 3; api.version = 3
    conflict = zotero.sync(store, pid, "alice", vault=vault, client_factory=factory)
    assert len(conflict["conflicts"]) == 1 and store.item(pid, "alice", p["id"])["label"] == "Local revised title"
    zotero.resolve(store, pid, "alice", "ABCD2345", "local", vault=vault, client_factory=factory)
    assert api.items["ABCD2345"]["data"]["title"] == "Local revised title"
    assert not zotero.status(store, pid, "alice", vault)["conflicts"]
    fresh = store.add_paper(pid, "alice", {"title": "Controlled new local source", "doi": "10.1000/local-export", "authors": ["A. Author"], "year": 2024})
    api.crash_after_post = True
    first = zotero.sync(store, pid, "alice", "push", vault=vault, client_factory=factory)
    assert not first["last_report"]["complete"] and first["last_report"]["errors"]
    second = zotero.sync(store, pid, "alice", "push", vault=vault, client_factory=factory)
    assert second["last_report"]["complete"] and len(api.items) == 2
    assert sum(m == "POST" for m, u, kw in api.calls) == 1
    assert any(v["paper_id"] == fresh["id"] for v in vault.get("alice", pid)["mappings"].values())


def test_rate_limit_and_disabled_writes_preserve_progress_without_fabrication(setup):
    store, pid, vault, api, factory, objects = setup
    api.status = 429
    result = zotero.sync(store, pid, "alice", vault=vault, client_factory=factory)
    assert not result["last_report"]["complete"] and not store.items(pid, "alice", "paper")
    api.status = None
    zotero.configure(store, pid, "alice", {"library_type": "users", "library_id": "123", "allow_write": False}, vault)
    before = len(api.calls)
    result = zotero.sync(store, pid, "alice", "push", vault=vault, client_factory=factory)
    assert result["last_report"]["errors"] and len(api.calls) == before


def test_connection_check_is_read_only_account_scoped_and_reset_by_new_key(setup):
    store, pid, vault, api, factory, objects = setup
    assert zotero.status(store, pid, "alice", vault)["connection_check"] is None
    result = zotero.check_connection(store, pid, "alice", vault=vault, client_factory=factory)
    assert result["connection_check"]["ok"]
    assert all(method == "GET" for method, url, kw in api.calls)
    assert not store.items(pid, "alice", "paper") and not result["last_report"]
    assert "ControlledContractOnlyKey" not in json.dumps(result)
    store.set_member(pid, "alice", "bob", "editor")
    with pytest.raises(WorkspaceError): zotero.check_connection(store, pid, "bob", vault=vault, client_factory=factory)
    zotero.configure(store, pid, "alice", {"library_type": "users", "library_id": "123", "api_key": "NewControlledContractKey123456"}, vault)
    assert zotero.status(store, pid, "alice", vault)["connection_check"] is None
    api.status = 403
    result = zotero.check_connection(store, pid, "alice", vault=vault, client_factory=factory)
    assert not result["connection_check"]["ok"] and not store.items(pid, "alice", "paper")


def test_rejected_item_does_not_block_other_exports_or_leak_remote_message(setup):
    store, pid, vault, api, factory, objects = setup
    bad = store.add_paper(pid, "alice", {"title": "Rejected source"})
    good = store.add_paper(pid, "alice", {"title": "Valid source"})
    original = api.request
    def response(method, url, **kw):
        if method == "POST" and kw["json"][0]["title"] == "Rejected source":
            return Response({"failed": {"0": {"code": 400, "message": "Invalid collections; secret ControlledContractOnlyKey123456"}}})
        return original(method, url, **kw)
    api.request = response
    result = zotero.sync(store, pid, "alice", "push", vault=vault, client_factory=factory)
    report = result["last_report"]
    assert not report["complete"] and report["exported"] == 1
    assert "400" in report["errors"][0]["message"] and "collections" in report["errors"][0]["message"]
    assert "ControlledContractOnlyKey" not in json.dumps(report)
    record = vault.get("alice", pid)
    assert bad["id"] in record["pending_push"] and good["id"] not in record["pending_push"]
    api.request = original
    retry = zotero.sync(store, pid, "alice", "push", vault=vault, client_factory=factory)
    assert retry["last_report"]["complete"] and len(api.items) == 3


def test_unchanged_write_result_is_confirmed_and_recovery_auth_failure_never_posts(setup):
    store, pid, vault, api, factory, objects = setup
    paper = store.add_paper(pid, "alice", {"title": "Already saved remote source"})
    original = api.request
    def response(method, url, **kw):
        result = original(method, url, **kw)
        if method == "POST": return Response({"unchanged": {"0": kw["json"][0]["key"]}})
        return result
    api.request = response
    result = zotero.sync(store, pid, "alice", "push", vault=vault, client_factory=factory)
    assert result["last_report"]["complete"] and result["mapped_count"] == 1
    assert any(method == "GET" and "/items/" in url for method, url, kw in api.calls)
    second = store.add_paper(pid, "alice", {"title": "Pending export"})
    record = vault.get("alice", pid)
    record["pending_push"][second["id"]] = {"key": "NEWK2345", "token": "a" * 32, "submitted": True}
    vault.put("alice", pid, record); api.calls.clear(); api.status = 403
    result = zotero.sync(store, pid, "alice", "push", vault=vault, client_factory=factory)
    assert result["last_report"]["errors"] and all(method == "GET" for method, url, kw in api.calls)
