"""Actual public DOI, Europe PMC and arXiv PDF check; isolated runtime data."""
import json
import os
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
with tempfile.TemporaryDirectory(prefix="scholarscope-public-source-") as tmp:
    os.environ["SCHOLARSCOPE_DATA_DIR"] = tmp
    os.environ["SCHOLARSCOPE_WORKSPACE_DIR"] = tmp
    os.environ["SCHOLARSCOPE_DISABLE_EMBEDDINGS"] = "1"
    from workspace.store import WorkspaceStore
    from workspace.documents import ObjectStore
    from workspace import sources
    from agent.spar2.retrievers import search_europe_pmc
    from workspace.network import fetch_public
    store = WorkspaceStore(); pid = store.create_project("public-source-check", "Actual public source check")["id"]
    metadata = sources.lookup_doi("10.1038/s41586-021-03819-2")
    assert "protein" in metadata["title"].lower()
    doi_paper = store.add_paper(pid, "public-source-check", metadata)
    oa = sources.oa_links(store, pid, "public-source-check", doi_paper["id"])
    paper = store.add_paper(pid, "public-source-check", {"title": "Attention Is All You Need", "arxiv_id": "1706.03762", "source": "public-arxiv-check"})
    links = sources.oa_links(store, pid, "public-source-check", paper["id"])
    assert links["links"][0]["url"] == "https://arxiv.org/pdf/1706.03762"
    document = sources.attach_remote_pdf(store, ObjectStore(), pid, "public-source-check", paper["id"], links["links"][0]["url"])
    assert document["data"]["page_count"] == 15
    assert "Attention" in document["data"]["pages"][0]["text"]
    epmc = search_europe_pmc(["protein structure prediction"], end_date="20261231")
    assert epmc and all(p.get("title") for p in epmc)
    import requests
    response = requests.get("https://api.zotero.org/itemTypes", headers={"Zotero-API-Version": "3"}, timeout=8)
    assert response.status_code == 200 and any(t["itemType"] == "journalArticle" for t in response.json())
    print(json.dumps({"status": "PASS", "doi_title": metadata["title"], "doi_oa_links": len(oa["links"]),
        "actual_arxiv_pdf_pages": document["data"]["page_count"], "actual_pdf_bytes": document["data"]["bytes"],
        "europe_pmc_actual_results": len(epmc), "zotero_official_public_api": response.status_code,
        "private_zotero_library": "not tested: no account credentials supplied"}, ensure_ascii=False, indent=2))
