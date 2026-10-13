"""RefChain 引用扩展：从判分后的种子论文抓 OpenAlex 参考文献/施引文献 + CrossRef 参考文献，1 跳。"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeout
from typing import Dict, List

import requests

from agent.spar2.retrievers import _parse_openalex_work


def _openalex_headers() -> Dict:
    params = {}
    key = os.getenv("OPENALEX_API_KEY", "")
    email = os.getenv("OPENALEX_EMAIL", "")
    if key:
        params["api_key"] = key
    elif email:
        params["mailto"] = email
    return params


def expand_citations(seed_docs: List[dict], max_seeds: int = 8,
                     refs_per_seed: int = 30, end_date: str = "",
                     deadline: float | None = None) -> List[dict]:
    """对种子论文做 1 跳引用/被引扩展，返回新候选（含标题/DOI/arXiv）。

    deadline：time.monotonic() 刻度的绝对截止时间；每次网络请求前检查，
    超时立即返回已收集的候选，避免 RefChain 把整条流水线拖过 deadline。
    """
    if not seed_docs:
        return []

    def _expired() -> bool:
        return deadline is not None and time.monotonic() >= deadline

    def _left(default: float = 1.0) -> float:
        if deadline is None:
            return default
        return max(0.1, deadline - time.monotonic())

    out: List[dict] = []
    end = int(end_date[:4]) if end_date else 9999

    def _absorb_work(work: dict) -> None:
        from agent.spar2.retrievers import _parse_openalex_work
        doc = _parse_openalex_work(work)
        if not doc:
            return
        if end < 9999 and doc.get("year"):
            try:
                if int(str(doc["year"])[:4]) > end:
                    return
            except Exception:
                pass
        doc["sources"] = ["citation_expand"]
        out.append(doc)

    # 1) OpenAlex 引用 + 被引
    oa_ids = [d.get("openalex_id") for d in seed_docs if d.get("openalex_id")]
    ref_oa_ids: List[str] = []
    for oid in oa_ids[:max_seeds]:
        if _expired():
            break
        try:
            resp = requests.get(
                f"https://api.openalex.org/works/{requests.utils.quote(oid)}",
                params={"select": "referenced_works", **_openalex_headers()},
                timeout=30,
            )
            if resp.status_code == 200:
                ref_oa_ids.extend((resp.json().get("referenced_works") or [])[:refs_per_seed])
        except Exception:
            continue
        try:
            resp = requests.get(
                "https://api.openalex.org/works",
                params={"filter": f"cites:{oid.split('/')[-1]}", "per-page": refs_per_seed,
                        "select": "id,title,ids,abstract_inverted_index,publication_year,cited_by_count",
                        **_openalex_headers()},
                timeout=30,
            )
            if resp.status_code == 200:
                for w in resp.json().get("results", []):
                    _absorb_work(w)
        except Exception:
            continue
    ref_oa_ids = list(dict.fromkeys(ref_oa_ids))[:60]

    def _fetch_ref(rid: str):
        try:
            resp = requests.get(
                f"https://api.openalex.org/works/{requests.utils.quote(rid)}",
                params={"select": "id,title,ids,abstract_inverted_index,publication_year,cited_by_count",
                        **_openalex_headers()},
                timeout=20,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    pool = ThreadPoolExecutor(max_workers=8)
    try:
        futures = [pool.submit(_fetch_ref, rid) for rid in ref_oa_ids]
        try:
            for fut in as_completed(futures, timeout=_left(20.0)):
                work = fut.result()
                if work is not None:
                    _absorb_work(work)
        except FutureTimeout:
            pass  # 超时：只取已完成的引用候选
        finally:
            for fut in futures:
                fut.cancel()
    finally:
        pool.shutdown(wait=False)  # 不等慢引用请求，让 RefChain 受 deadline 约束

    # 2) CrossRef 参考文献 + 被引（DOI 种子，主要服务 litqa2/paper_finder 的 DOI gold）
    for seed in seed_docs[:max_seeds]:
        if _expired():
            break
        doi = (seed.get("doi") or "").lower()
        if not doi:
            continue
        # 2a) references 方向（该论文引用了哪些论文）
        try:
            resp = requests.get(
                f"https://api.crossref.org/works/{requests.utils.quote(doi)}/references",
                timeout=30,
            )
            if resp.status_code == 200:
                for ref in resp.json().get("message", {}).get("reference", [])[:refs_per_seed]:
                    ref_doi = (ref.get("DOI") or "").lower()
                    ref_title = ref.get("article-title") or ref.get("unstructured") or ""
                    if not ref_doi and not ref_title:
                        continue
                    out.append({
                        "arxiv_id": "",
                        "doi": ref_doi,
                        "title": str(ref_title).strip()[:200],
                        "abstract": "",
                        "year": str(ref.get("year") or ""),
                        "cited_by": 0,
                        "ids": [ref_doi] if ref_doi else [],
                        "sources": ["citation_expand"],
                    })
        except Exception:
            pass
        # 2b) cited_by 方向（该论文被哪些论文引用）
        try:
            resp = requests.get(
                "https://api.crossref.org/works",
                params={
                    "filter": f"references:{doi}",
                    "rows": refs_per_seed,
                    "select": "DOI,title,abstract,published-print,issued,is-referenced-by-count",
                },
                timeout=30,
            )
            if resp.status_code == 200:
                for item in resp.json().get("message", {}).get("items", [])[:refs_per_seed]:
                    item_doi = (item.get("DOI") or "").lower()
                    item_title = ""
                    if item.get("title"):
                        item_title = str(item["title"][0] or "").strip()[:200]
                    item_abstract = ""
                    if item.get("abstract"):
                        item_abstract = str(item["abstract"])[:400]
                    item_year = ""
                    if item.get("published-print", {}).get("date-parts"):
                        parts = item["published-print"]["date-parts"][0]
                        item_year = str(parts[0]) if parts else ""
                    elif item.get("issued", {}).get("date-parts"):
                        parts = item["issued"]["date-parts"][0]
                        item_year = str(parts[0]) if parts else ""
                    out.append({
                        "arxiv_id": "",
                        "doi": item_doi,
                        "title": item_title,
                        "abstract": item_abstract,
                        "year": item_year,
                        "cited_by": item.get("is-referenced-by-count") or 0,
                        "ids": [item_doi] if item_doi else [],
                        "sources": ["citation_expand"],
                    })
        except Exception:
            pass
    return out
