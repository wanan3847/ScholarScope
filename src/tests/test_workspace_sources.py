import io
import json
import socket
import pytest
from reportlab.pdfgen.canvas import Canvas
from workspace.store import WorkspaceStore, WorkspaceError
from workspace.documents import ObjectStore
from workspace import sources, network
from agent.spar2 import retrievers
from agent import api_settings


class Response:
    def __init__(self, data, status=200): self.data, self.status_code = data, status
    def json(self): return self.data


def test_europe_pmc_crossref_and_authorized_scopus_use_real_response_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(api_settings, "_CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.delenv("SCOPUS_API_KEY", raising=False)
    requests = []
    def get(url, **kw):
        requests.append((url, kw))
        if "europepmc" in url: return Response({"resultList": {"result": [{"title": "Controlled biology source", "doi": "10.1000/epmc-test", "id": "12345", "source": "MED", "pubYear": "2025", "abstractText": "<p>Neural models predict tissue properties.</p>", "isOpenAccess": "Y", "authorList": {"author": [{"fullName": "Test Author"}]}, "fullTextUrlList": {"fullTextUrl": [{"documentStyle": "pdf", "availability": "Open access", "url": "https://example.org/controlled.pdf"}]}}]}})
        if "crossref" in url: return Response({"message": {"items": [{"title": ["Controlled Crossref source"], "DOI": "10.1000/crossref-test", "abstract": "<jats:p>Actual abstract text from fixture.</jats:p>", "issued": {"date-parts": [[2025]]}}]}})
        return Response({"search-results": {"entry": [{"dc:title": "Controlled licensed title", "eid": "2-s2.0-controlled", "prism:doi": "10.1000/scopus-test", "prism:coverDate": "2025-06-01", "dc:creator": "Test Author"}]}})
    monkeypatch.setattr(retrievers._REQ_SESSION, "get", get)
    paper = retrievers.search_europe_pmc(["neural"], end_date="20251231")[0]
    assert paper["abstract"] == "Neural models predict tissue properties." and paper["pdf_url"].endswith("controlled.pdf")
    assert "2025-12-31" in requests[0][1]["params"]["query"]
    assert retrievers.search_crossref(["neural"])[0]["abstract"] == "Actual abstract text from fixture."
    assert retrievers.search_scopus(["neural"]) == []
    monkeypatch.setenv("SCOPUS_API_KEY", "controlled-contract-only")
    licensed = retrievers.search_scopus(["neural"])[0]
    assert licensed["year"] == "2025" and licensed["abstract"] == "" and licensed["sources"] == ["scopus"]
    assert "X-ELS-APIKey" in requests[-1][1]["headers"]
    monkeypatch.setattr(retrievers._REQ_SESSION, "get", lambda *a, **kw: Response({}, 429))
    assert retrievers.search_europe_pmc(["neural"]) == [] and retrievers.search_scopus(["neural"]) == []


def test_public_target_rejects_private_reserved_and_embedded_credentials(monkeypatch):
    for ip in ("127.0.0.1", "10.0.0.8", "169.254.169.254", "100.64.1.1", "::1", "224.0.0.1"):
        monkeypatch.setattr(socket, "getaddrinfo", lambda *a, address=ip, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))])
        with pytest.raises(WorkspaceError): network.public_target("https://example.org/source.pdf")
    for url in ("http://example.org/file", "https://user:password@example.org/file", "https://example.org:8000/file", "file:///tmp/file"):
        with pytest.raises(WorkspaceError): network.public_target(url)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.1.1", 443))])
    monkeypatch.setattr(network.requests, "get", lambda *a, **kw: Response({"Answer": [{"type": 1, "data": "169.254.169.254"}]}))
    with pytest.raises(WorkspaceError): network.public_target("https://example.org/file")
    monkeypatch.setattr(network.requests, "get", lambda *a, **kw: Response({"Answer": [{"type": 1, "data": "93.184.216.34"}]}))
    assert network.public_target("https://example.org/file")[2] == "93.184.216.34"


def test_doi_real_metadata_remote_pdf_dedup_provenance_and_permissions(tmp_path, monkeypatch):
    monkeypatch.setattr(api_settings, "_CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(sources.requests, "get", lambda *a, **kw: Response({"message": {"DOI": "10.1000/doi-source", "title": ["Controlled DOI source"], "abstract": "<p>The dataset contains 120 samples.</p>", "author": [{"given": "Test", "family": "Author"}], "issued": {"date-parts": [[2025]]}}}))
    metadata = sources.lookup_doi("https://doi.org/10.1000/doi-source")
    assert metadata["abstract"] == "The dataset contains 120 samples." and metadata["year"] == 2025
    store = WorkspaceStore("sqlite:///" + str(tmp_path / "sources.db")); p = store.create_project("alice", "Sources")
    paper = store.add_paper(p["id"], "alice", metadata)
    out = io.BytesIO(); canvas = Canvas(out); canvas.drawString(50, 750, "The dataset contains 120 samples."); canvas.save()
    fetch = lambda url: {"bytes": out.getvalue(), "url": "https://example.org/controlled.pdf?temporary-token=controlled", "content_type": "application/pdf"}
    doc = sources.attach_remote_pdf(store, ObjectStore(tmp_path), p["id"], "alice", paper["id"], "https://example.org/controlled.pdf", fetcher=fetch)
    assert doc["data"]["source_url"] == "https://example.org/controlled.pdf" and doc["data"]["acquisition"] == "remote_public_pdf"
    again = sources.attach_remote_pdf(store, ObjectStore(tmp_path), p["id"], "alice", paper["id"], "https://example.org/controlled.pdf", fetcher=fetch)
    assert doc["id"] == again["id"] and len(store.items(p["id"], "alice", "document")) == 1
    store.set_member(p["id"], "alice", "reader", "viewer")
    with pytest.raises(WorkspaceError) as error: sources.attach_remote_pdf(store, ObjectStore(tmp_path), p["id"], "reader", paper["id"], "https://example.org/a.pdf", fetcher=fetch)
    assert error.value.status == 403
