"""DOI/OA resolution uses actual provider metadata; downloads never invent files."""
import re
from urllib.parse import quote, urlsplit, urlunsplit
import requests
from workspace.store import WorkspaceError, normalized
from workspace.documents import attach_pdf
from workspace.network import fetch_public
from agent.api_settings import get_api_setting
from agent.spar2.retrievers import _plain_abstract


def lookup_doi(doi):
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/|^doi:\s*", "", str(doi), flags=re.I).strip().lower()
    if not re.fullmatch(r"10\.\d{4,9}/\S{1,2000}", doi): raise WorkspaceError("请输入有效 DOI")
    headers = {}
    token = get_api_setting("crossref_token", "CROSSREF_API_TOKEN")
    if token: headers["Crossref-Plus-API-Token"] = "Bearer " + token
    try:
        response = requests.get("https://api.crossref.org/works/" + quote(doi, safe=""), headers=headers, timeout=8)
        if response.status_code != 200: raise WorkspaceError("暂未取得该 DOI 的真实书目信息", 503)
        data = response.json()["message"]
        title = (data.get("title") or [""])[0]
        if not title or str(data.get("DOI", "")).lower() != doi: raise WorkspaceError("DOI 返回的书目信息不一致", 503)
        return {"title": title, "doi": doi, "abstract": _plain_abstract(data.get("abstract", "")),
            "authors": [normalized(a.get("given", "") + " " + a.get("family", "")) for a in data.get("author", [])],
            "year": data.get("issued", {}).get("date-parts", [[None]])[0][0], "venue": (data.get("container-title") or [""])[0],
            "url": "https://doi.org/" + doi, "source": "crossref_doi"}
    except WorkspaceError: raise
    except Exception: raise WorkspaceError("DOI 元数据服务暂不可用", 503) from None


def oa_links(store, pid, actor, paper_id):
    paper = store.item(pid, actor, paper_id, "paper")["data"]
    links, seen = [], set()
    def add(url, source, license=None):
        if not url or url in seen or not str(url).startswith("https://"): return
        seen.add(url); links.append({"url": url, "source": source, "license": license or "许可未提供，请核对来源", "access": "provider_reported_open"})
    arxiv = str(paper.get("arxiv_id", ""))
    if re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-zA-Z.-]+/\d{7})(?:v\d+)?", arxiv): add("https://arxiv.org/pdf/" + arxiv, "arxiv")
    if paper.get("is_oa"): add(paper.get("pdf_url"), paper.get("source") or "retrieved_oa")
    doi = paper.get("doi")
    if doi:
        try:
            params = {}
            key = get_api_setting("openalex_key", "OPENALEX_API_KEY")
            if key: params["api_key"] = key
            response = requests.get("https://api.openalex.org/works/" + quote("https://doi.org/" + doi, safe=""), params=params, timeout=6)
            if response.status_code == 200:
                work = response.json()
                for l in work.get("locations", []) + [work.get("best_oa_location") or {}]:
                    if l.get("is_oa"): add(l.get("pdf_url"), "openalex", l.get("license"))
        except Exception: pass
        email = get_api_setting("unpaywall_email", "UNPAYWALL_EMAIL")
        if email:
            try:
                response = requests.get("https://api.unpaywall.org/v2/" + quote(doi, safe=""), params={"email": email}, timeout=6)
                if response.status_code == 200:
                    for l in response.json().get("oa_locations", []): add(l.get("url_for_pdf"), "unpaywall", l.get("license"))
            except Exception: pass
    return {"paper_id": paper_id, "links": links[:20], "message": "仅提供数据库报告的开放链接；实际下载仍需文件与来源核验。" if links else "未取得可用的开放 PDF 链接；可上传你有权读取的原文。"}


def attach_remote_pdf(store, objects, pid, actor, paper_id, url, *, fetcher=fetch_public):
    with store.engine.connect() as conn: store._access(conn, pid, actor, edit=True)
    store.item(pid, actor, paper_id, "paper")
    result = fetcher(url)
    blob = result["bytes"]
    document = attach_pdf(store, objects, pid, actor, paper_id, "open-source.pdf", blob)
    parsed = urlsplit(result["url"])
    clean_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return store.put(pid, actor, "document", document["label"], {**document["data"], "source_url": clean_url, "acquired_by": actor,
        "acquisition": "remote_public_pdf"}, document["id"], document["revision"])
