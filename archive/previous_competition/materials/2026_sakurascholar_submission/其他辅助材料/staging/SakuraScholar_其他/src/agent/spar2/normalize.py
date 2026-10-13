"""ID 归一化与跨通道候选合并。"""

from __future__ import annotations

import re
from typing import Dict, List

_ARXIV_RE = re.compile(r"^(\d{4}\.\d{4,5})(?:v\d+)?$")


def norm_arxiv(s) -> str:
    """arXiv ID 归一化：去前缀、去版本、小写；非法返回空串。"""
    if not s:
        return ""
    v = str(s).strip().lower()
    v = v.replace("arxiv:", "").replace("abs/", "").replace("https://arxiv.org/", "")
    m = _ARXIV_RE.match(v)
    return m.group(1) if m else ""


def norm_doi(s) -> str:
    if not s:
        return ""
    v = str(s).strip().lower()
    for pre in ("https://doi.org/", "http://doi.org/", "doi:"):
        if v.startswith(pre):
            v = v[len(pre):]
    return v if v.startswith("10.") else ""


def _merge_doc(existing: Dict, new: Dict) -> Dict:
    """把另一通道的信息并入已有 doc（不覆盖已有值）。"""
    for k, val in (new or {}).items():
        if val and not existing.get(k):
            existing[k] = val
    ids = existing.setdefault("ids", [])
    for extra in (norm_arxiv(new.get("arxiv_id") or new.get("arxivId")),
                  norm_doi(new.get("doi"))):
        if extra and extra not in ids:
            ids.append(extra)
    for i in (new or {}).get("ids", []):
        if i and i not in ids:
            ids.append(i)
    srcs = existing.setdefault("sources", [])
    for s in (new or {}).get("sources", []):
        if s and s not in srcs:
            srcs.append(s)
    existing["cited_by"] = max(existing.get("cited_by") or 0,
                               (new or {}).get("cited_by") or 0)
    return existing


def merge_candidates(channels: List[List[Dict]]) -> Dict[str, Dict]:
    """按归一化 arXiv / DOI 去重合并；arXiv 与 DOI 互为别名（同论文双条目合并）；
    无 ID 时退回标题小写 key。"""
    merged: Dict[str, Dict] = {}
    by_arxiv: Dict[str, Dict] = {}
    by_doi: Dict[str, Dict] = {}

    def _record_aliases(doc: Dict, arxiv: str, doi: str) -> None:
        if arxiv:
            by_arxiv[arxiv] = doc
        if doi:
            by_doi[doi] = doc

    for docs in channels:
        for doc in docs or []:
            arxiv = norm_arxiv(doc.get("arxiv_id") or doc.get("arxivId"))
            doi = norm_doi(doc.get("doi"))
            # arXiv 的 DOI 形如 10.48550/arxiv.XXXX → 反解出 arXiv 别名
            if not arxiv and doi and doi.startswith("10.48550/arxiv."):
                arxiv = norm_arxiv(doi.split("10.48550/arxiv.", 1)[1])
            # 同论文别名合并：arXiv 或 DOI 任一命中已有条目即并入
            target = None
            if arxiv and arxiv in by_arxiv:
                target = by_arxiv[arxiv]
            elif doi and doi in by_doi:
                target = by_doi[doi]
            if target is not None:
                _merge_doc(target, doc)
                _record_aliases(target, arxiv, doi)
                continue
            key = arxiv or doi or ""
            if not key:
                title = str(doc.get("title") or "").strip().lower()
                if not title:
                    continue
                key = "title:" + title
            if key in merged:
                merged[key] = _merge_doc(merged[key], doc)
                _record_aliases(merged[key], arxiv, doi)
            else:
                doc["arxiv_id"] = arxiv
                doc["doi"] = doi
                doc.setdefault("ids", [])
                doc.setdefault("sources", [])
                doc["scores"] = []
                doc["score"] = 0.0
                doc["judged"] = False
                if arxiv and arxiv not in doc["ids"]:
                    doc["ids"].append(arxiv)
                if doi and doi not in doc["ids"]:
                    doc["ids"].append(doi)
                merged[key] = doc
                _record_aliases(doc, arxiv, doi)
    return merged
