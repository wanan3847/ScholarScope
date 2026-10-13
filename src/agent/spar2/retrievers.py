"""多通道检索器：arXiv API / OpenAlex / CrossRef / 本地 PaSa 语义语料。"""

from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from concurrent.futures import as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests

# 连接复用：OpenAlex / CrossRef 请求较多，复用 Session 避免每次 TLS 握手
_REQ_SESSION = requests.Session()

try:
    import arxiv as _arxiv
except Exception:  # pragma: no cover
    _arxiv = None


def _end_year(end_date: str) -> str:
    return (end_date or "")[:4] or str(datetime.now().year)


_ARXIV_STOP = {
    "the", "a", "an", "of", "on", "in", "and", "or", "is", "are", "to",
    "for", "that", "this", "with", "from", "by", "at", "as", "was",
    "were", "be", "been", "has", "have", "had", "do", "does", "did",
    "which", "what", "how", "why", "who", "whose", "using", "used",
    "use", "papers", "paper", "works", "work", "studies", "study",
    "show", "showed", "explored", "explore", "within", "realm", "area",
    "related", "similar", "find", "give", "me", "can", "could", "would",
    "should", "their", "they", "them", "these", "those", "some", "many",
    "more", "most", "than", "into", "over", "under", "after", "before",
    "large", "small", "based", "method", "methods", "approach", "approaches",
}


def _arxiv_keyword_queries(keywords: List[str], max_q: int = 10) -> List[str]:
    """arXiv 布尔查询构造：多词技术短语优先，连字符词补去连字符变体。

    要点：
    - 每个关键词短语内部词级 AND（如 "data pruning" → all:"data" AND all:"pruning"），
      "data"/"training" 等在组合中保留判别力；
    - arXiv 索引把 "data-efficient" 当整体 token，分词版匹配不到，
      因此额外生成 (all:"data-efficient" OR all:"dataefficient") 变体；
    - 多词短语排在单判别词之前，避免通用词把技术短语挤出预算。
    """
    multi: List[tuple] = []
    singles: List[str] = []
    for kw in keywords:
        raw = (kw or "").lower().strip()
        words = [t for t in re.findall(r"[a-z0-9]+", raw)
                 if len(t) > 2 and t not in _ARXIV_STOP]
        if len(words) >= 2:
            multi.append((raw, words))
        elif len(words) == 1 and words[0] not in singles:
            singles.append(words[0])
    out: List[str] = []
    for raw, words in multi[:8]:
        out.append("(" + " AND ".join(f'all:"{w}"' for w in words) + ")")
        for h in re.findall(r"[a-z0-9]+-[a-z0-9]+", raw)[:2]:
            flat = h.replace("-", "")
            q = f'(all:"{h}" OR all:"{flat}")'
            if q not in out:
                out.append(q)
    for i in range(0, len(singles) - 1, 2):
        out.append(f'(all:"{singles[i]}" AND all:"{singles[i+1]}")')
    return list(dict.fromkeys(out))[:max_q]


def extract_title_terms(docs: List[dict], top_n: int = 6) -> List[str]:
    """从已找到论文的标题中提取判别性词（不依赖 LLM，供第二轮检索用）。

    已相关论文的标题词是查询词汇的天然补充：如 "Distilling Step-by-Step"
    会贡献 "distilling"/"step-by-step" 等原查询没有的词。
    """
    freq: Dict[str, int] = {}
    seen: Dict[str, str] = {}
    for d in docs[:8]:
        title = (d.get("title") or "").lower()
        for t in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", title):
            if len(t) > 3 and t not in _ARXIV_STOP:
                freq[t] = freq.get(t, 0) + 1
                seen.setdefault(t, title[:80])
    # 取出现频次低（判别性强）的词，但至少 2 个标题共现的优先
    candidates = sorted(freq.items(), key=lambda kv: (kv[1], -len(kv[0])))
    out = [t for t, _ in candidates if freq[t] <= 2][:top_n]
    # 若不够，补高频词
    for t, _ in sorted(freq.items(), key=lambda kv: -kv[1]):
        if len(out) >= top_n:
            break
        if t not in out:
            out.append(t)
    return out


# ------------------------------------------------------------------ #
# arXiv
# ------------------------------------------------------------------ #
def search_arxiv(keywords: List[str], phrases: List[str] = None,
                 end_date: str = "", max_results: int = 120) -> List[Dict]:
    """arXiv API 检索：每个精确 AND 组合/短语独立请求，避免被通用词挤掉。"""
    if not _arxiv or (not keywords and not phrases):
        return []
    phrases = phrases or []
    queries: List[str] = _arxiv_keyword_queries(keywords)
    budgets: List[int] = [60] * len(queries)
    # 语义短语独立请求
    for p in phrases[:4]:
        q = f'(all:"{p}")'
        if q not in queries:
            queries.append(q)
            budgets.append(40)
    if not queries:
        return []
    out: Dict[str, Dict] = {}
    client = _arxiv.Client(delay_seconds=0.3)
    for attempt in range(3):
        got = 0
        try:
            for q, budget in zip(queries, budgets):
                kwargs = {"query": q, "max_results": min(budget, max_results),
                          "sort_by": _arxiv.SortCriterion.Relevance,
                          "sort_order": _arxiv.SortOrder.Descending}
                if end_date:
                    try:
                        kwargs["end_date"] = datetime.strptime(end_date, "%Y%m%d").date()
                    except Exception:
                        pass
                results = _arxiv_results_with_timeout(client, kwargs, timeout=15)
                for r in results:
                    aid = r.entry_id.split("/")[-1].split("v")[0]
                    year = r.published.strftime("%Y") if r.published else ""
                    if end_date and year and int(year) > int(_end_year(end_date)):
                        continue
                    # 提取作者列表
                    authors = []
                    try:
                        authors = [str(a.name) for a in r.authors or [] if a.name]
                    except Exception:
                        pass
                    out[aid] = {
                        "arxiv_id": aid,
                        "title": (r.title or "").replace("\n", " ").strip(),
                        "abstract": (r.summary or "").replace("\n", " ").strip(),
                        "year": year,
                        "authors": authors,
                        "venue": "arXiv",
                        "url": r.entry_id or f"https://arxiv.org/abs/{aid}",
                        "cited_by": 0,
                        "ids": [aid],
                        "sources": ["arxiv"],
                    }
                got += 1
        except Exception:
            pass
        if got == len(queries):
            break
    return list(out.values())


def _arxiv_results_with_timeout(client, kwargs: Dict, timeout: int = 15) -> list:
    """arXiv 查询加硬超时（export.arxiv.org 偶发长时间挂起）。"""
    def _run():
        return list(client.results(_arxiv.Search(**kwargs), offset=0))
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(_run)
        try:
            return future.result(timeout=timeout)
        except FutureTimeout:
            return []
    finally:
        pool.shutdown(wait=False)  # 不等待可能挂起的 arXiv 连接


# ------------------------------------------------------------------ #
# OpenAlex
# ------------------------------------------------------------------ #
def _openalex_params(search: str, end_date: str, per_page: int,
                     extra_filter: str = "") -> Dict:
    start = int(datetime.now().year) - 20
    end = _end_year(end_date)
    pub_filter = f"publication_year:{start}-{end}"
    if extra_filter:
        pub_filter = f"{pub_filter},{extra_filter}"
    params = {
        "search": search,
        "sort": "cited_by_count:desc",
        "filter": pub_filter if extra_filter else f"{pub_filter}",
        "per-page": per_page,
    }
    email = os.getenv("OPENALEX_EMAIL", "")
    key = os.getenv("OPENALEX_API_KEY", "")
    if key:
        params["api_key"] = key
    elif email:
        params["mailto"] = email
    return params


def _parse_openalex_work(w: Dict) -> Optional[Dict]:
    ext = w.get("ids") or {}
    arxiv = ""
    if ext.get("arxiv"):
        arxiv = str(ext["arxiv"]).split("/")[-1].split("v")[0]
    doi = ""
    if ext.get("doi"):
        doi = str(ext["doi"]).replace("https://doi.org/", "").lower()
    # OpenAlex 常见形态：arXiv 论文只有 DOI 10.48550/arxiv.XXXX → 提取 arXiv ID
    if not arxiv and doi.startswith("10.48550/arxiv."):
        arxiv = doi.split("10.48550/arxiv.", 1)[1].split("v")[0]
    title = (w.get("title") or "").strip()
    abstract = w.get("abstract_inverted_index")
    if isinstance(abstract, dict):
        # 倒排索引重建摘要文本
        pos = []
        for word, idxs in abstract.items():
            for i in idxs:
                pos.append((i, word))
        pos.sort()
        abstract = " ".join(w for _, w in pos)
    if isinstance(abstract, str):
        abstract = abstract.strip()
    else:
        abstract = ""
    # 提取作者和期刊信息
    authors = []
    try:
        for a in (w.get("authorships") or []):
            name = ((a.get("author") or {}).get("display_name") or "").strip()
            if name:
                authors.append(name)
    except Exception:
        pass
    venue = ""
    try:
        primary = w.get("primary_location") or {}
        src = primary.get("source") or {}
        venue = (src.get("display_name") or "").strip()
    except Exception:
        pass
    # 构造 URL
    url = ""
    if ext.get("doi"):
        url = str(ext["doi"]) if str(ext["doi"]).startswith("http") else f"https://doi.org/{ext['doi']}"
    elif w.get("doi"):
        url = w["doi"] if str(w["doi"]).startswith("http") else f"https://doi.org/{w['doi']}"
    elif arxiv:
        url = f"https://arxiv.org/abs/{arxiv}"
    doc = {
        "arxiv_id": arxiv,
        "doi": doi,
        "title": title,
        "abstract": abstract,
        "year": str(w.get("publication_year") or ""),
        "authors": authors,
        "venue": venue,
        "url": url,
        "cited_by": int(w.get("cited_by_count") or 0),
        "openalex_id": w.get("id") or "",
        "ids": [],
        "sources": ["openalex"],
    }
    if arxiv:
        doc["ids"].append(arxiv)
    if doi:
        doc["ids"].append(doi)
    if w.get("id"):
        doc["ids"].append(str(w["id"]))
    return doc if (title or arxiv or doi) else None


def search_openalex(keywords: List[str], phrases: List[str] = None,
                    end_date: str = "", per_page: int = 40) -> List[Dict]:
    """OpenAlex 检索：
    - title_and_abstract.search（词面精确，相关度排序）对每个关键词一次；
    - 再用 2 组组合关键词做全文 search（语义召回）；
    429 自动切 api_key。"""
    if not keywords and not phrases:
        return []
    phrases = phrases or []
    out: Dict[str, Dict] = {}
    base = "https://api.openalex.org/works"

    def _get(params: Dict):
        for attempt in range(2):  # 减少重试次数（429 时不再等太久）
            try:
                resp = _REQ_SESSION.get(base, params=params, timeout=10)
            except Exception:
                return None
            if resp.status_code == 429:
                key = os.getenv("OPENALEX_API_KEY", "")
                if key and "api_key" not in params:
                    params["api_key"] = key
                    params.pop("mailto", None)
                    continue
                return None  # 429 直接放弃，不重试
            if resp.status_code != 200:
                return None
            return resp
        return None

    def _absorb(resp) -> None:
        for w in resp.json().get("results", []):
            doc = _parse_openalex_work(w)
            if doc:
                key_id = doc["arxiv_id"] or doc["doi"] or doc["openalex_id"]
                if key_id and key_id not in out:
                    out[key_id] = doc

    # 三组检索并行执行，OpenAlex 请求从 ~90s 压到 ~20s
    def _run_query(params: Dict):
        resp = _get(params)
        return resp

    start = int(datetime.now().year) - 20
    end = _end_year(end_date)
    pub_filter = f"publication_year:{start}-{end}"
    from agent.api_settings import get_api_setting
    email = get_api_setting("openalex_email", "OPENALEX_EMAIL", "")
    # 只有明确启用付费key时才使用，否则用mailto免费通道
    use_paid = get_api_setting("openalex_use_paid_key", "OPENALEX_USE_PAID_KEY", "0").lower() in {"1", "true", "yes"}
    key = get_api_setting("openalex_key", "OPENALEX_API_KEY") if use_paid else ""
    auth = {"api_key": key} if key else ({"mailto": email} if email else {})

    tasks: List[Dict] = []
    # 精简任务：只保留 title_and_abstract + 全文 search（去掉 title.search 重复请求）
    for kw in keywords[:4]:
        tasks.append({"filter": f"title_and_abstract.search:{kw},{pub_filter}",
                      "per-page": max(per_page, 60)})
    for combo in (phrases[:4] or [" ".join(keywords[:4])]):
        tasks.append({"search": combo, "filter": pub_filter,
                      "per-page": max(per_page, 80),
                      "sort": "relevance_score:desc"})

    pool = ThreadPoolExecutor(max_workers=4)
    try:
        futures = [pool.submit(_run_query, {**t, **auth}) for t in tasks]
        for fut in as_completed(futures):
            resp = fut.result()
            if resp is not None:
                _absorb(resp)
    finally:
        pool.shutdown(wait=False)
    return list(out.values())


# ------------------------------------------------------------------ #
# CrossRef
# ------------------------------------------------------------------ #
def search_crossref(keywords: List[str], phrases: List[str] = None,
                    rows: int = 50) -> List[Dict]:
    """CrossRef 书目检索：返回 DOI/标题（服务 litqa2/paper_finder 的 DOI gold）。"""
    if not keywords and not phrases:
        return []
    phrases = phrases or []
    qs = phrases[:3] or [" ".join(keywords[:4])]
    out: Dict[str, Dict] = {}
    for q in qs:
        try:
            resp = _REQ_SESSION.get("https://api.crossref.org/works",
                                    params={"query.bibliographic": q, "rows": rows},
                                    timeout=15)
            if resp.status_code != 200:
                continue
            for it in resp.json().get("message", {}).get("items", []):
                title = (it.get("title") or [""])[0] if it.get("title") else ""
                year = ""
                issued = it.get("issued", {}).get("date-parts", [[None]])[0][0]
                if issued:
                    year = str(issued)
                doi = (it.get("DOI") or "").lower()
                if not doi and not title:
                    continue
                key = doi or "title:" + title.lower()
                # 提取作者
                authors = []
                try:
                    for a in (it.get("author") or []):
                        name = (a.get("given") or "") + " " + (a.get("family") or "")
                        name = name.strip()
                        if name:
                            authors.append(name)
                except Exception:
                    pass
                # 构造 URL
                cr_url = ""
                if doi:
                    cr_url = f"https://doi.org/{doi}"
                # 提取期刊名（venue）
                cr_venue = ""
                try:
                    cr_venue = (it.get("container-title") or [""])[0] or ""
                except Exception:
                    pass
                out[key] = {
                    "arxiv_id": "",
                    "doi": doi,
                    "title": title.strip(),
                    "abstract": "",
                    "year": year,
                    "authors": authors,
                    "venue": cr_venue,
                    "url": cr_url,
                    "cited_by": int(it.get("is-referenced-by-count") or 0),
                    "ids": [doi] if doi else [],
                    "sources": ["crossref"],
                }
        except Exception:
            continue
    return list(out.values())


# ------------------------------------------------------------------ #
# Semantic Scholar（语义检索：词面不重叠的语义型 gold 最依赖此通道）
# ------------------------------------------------------------------ #
def search_semantic_scholar(keywords: List[str], phrases: List[str] = None,
                            limit: int = 100, timeout: int = 15) -> List[Dict]:
    """S2 /graph/v1/paper/search 语义检索。

    匿名可用（429 时静默降级）；带 S2_API_KEY 时走独立配额。
    返回 doc 带 corpusId，直接服务 paper_finder 的 corpusId gold。
    """
    if not keywords and not phrases:
        return []
    phrases = phrases or []
    queries = [" ".join(keywords[:4])]
    for q in phrases[:2]:
        q = (q or "").strip()
        if q and q not in queries:
            queries.append(q)
    if not queries:
        return []
    import httpx
    key = os.getenv("S2_API_KEY", "")
    headers = {"x-api-key": key} if key else {}
    out: Dict[str, Dict] = {}
    for q in queries:
        resp = None
        for attempt in range(2):  # 减少重试（429 时快速放弃）
            try:
                resp = httpx.get(
                    "https://api.semanticscholar.org/graph/v1/paper/search",
                    params={
                        "query": q,
                        "limit": limit,
                        "fields": "title,abstract,externalIds,corpusId,citationCount,publicationDate,authors,url,venue",
                    },
                    headers=headers, timeout=timeout,
                )
                if resp.status_code == 429:
                    break  # 429 直接放弃，不重试
                if resp.status_code != 200:
                    break
                break
            except Exception:
                break
        if resp is None or resp.status_code != 200:
            continue
        try:
            for p in resp.json().get("data", []) or []:
                ext = p.get("externalIds") or {}
                arxiv = str(ext.get("ArXiv") or "").split("v")[0]
                doi = str(ext.get("DOI") or "").lower().replace("https://doi.org/", "")
                cid = p.get("corpusId")
                if not cid and not arxiv and not doi:
                    continue
                pub_date = str(p.get("publicationDate") or "")
                ids = []
                if arxiv:
                    ids.append(arxiv)
                if doi:
                    ids.append(doi)
                if cid:
                    ids.append(str(cid))
                # 提取作者
                s2_authors = []
                try:
                    for a in (p.get("authors") or []):
                        name = (a.get("name") or "").strip()
                        if name:
                            s2_authors.append(name)
                except Exception:
                    pass
                s2_url = (p.get("url") or "").strip()
                s2_venue = (p.get("venue") or "").strip()
                doc = {
                    "arxiv_id": arxiv,
                    "doi": doi,
                    "title": (p.get("title") or "").strip(),
                    "abstract": (p.get("abstract") or "").strip(),
                    "year": pub_date[:4],
                    "authors": s2_authors,
                    "venue": s2_venue,
                    "url": s2_url or (f"https://arxiv.org/abs/{arxiv}" if arxiv else (f"https://doi.org/{doi}" if doi else "")),
                    "cited_by": int(p.get("citationCount") or 0),
                    "ids": ids,
                    "sources": ["semantic_scholar"],
                }
                key_id = arxiv or doi or ("s2:" + str(cid))
                if key_id and key_id not in out:
                    out[key_id] = doc
        except Exception:
            continue
        time.sleep(0.3)  # 查询间留少量间隔，避免触发限流
    return list(out.values())


# ------------------------------------------------------------------ #
# 本地 PaSa 语料（BGE-small 语义 + 词法倒排，离线零成本）
# ------------------------------------------------------------------ #
_LOCAL_BACKEND = None


def _get_local_backend():
    global _LOCAL_BACKEND
    if _LOCAL_BACKEND is None:
        try:
            from retrieval.local_corpus import LocalCorpusBackend
            backend = LocalCorpusBackend(use_mock=False)
            backend._ensure_index()
            if os.getenv("SAKURA_LOCAL_SEMANTIC", "0").lower() not in {"0", "false", "no"}:
                backend._ensure_embeddings()
            _LOCAL_BACKEND = backend
        except Exception:
            _LOCAL_BACKEND = False
    return _LOCAL_BACKEND if _LOCAL_BACKEND else None


def search_local(query: str, top_k: int = 200) -> List[Dict]:
    """本地语料语义召回 top-K（标题向量），失败返回 []。
    自动通过 OpenAlex 补全摘要，提升 LLM 判分质量。"""
    backend = _get_local_backend()
    if backend is None:
        return []
    try:
        ids = backend._semantic_rank(query, top_k)
        out = []
        for pid in ids:
            title = backend._titles.get(pid, "")
            if not title:
                continue
            out.append({
                "arxiv_id": pid,
                "title": title,
                "abstract": "",
                "year": "",
                "cited_by": 0,
                "ids": [pid],
                "sources": ["local_corpus"],
            })
        # 批量从 OpenAlex 补全摘要（单次 API 调用）
        _enrich_local_abstracts(out)
        return out
    except Exception:
        return []


def _enrich_local_abstracts(docs: List[Dict]) -> None:
    """通过 OpenAlex arXiv filter 批量获取本地检索结果的摘要。"""
    if not docs:
        return
    arxiv_ids = [d["arxiv_id"] for d in docs if d.get("arxiv_id")][:80]
    if not arxiv_ids:
        return
    try:
        ids_param = "|".join(f"arxiv:{aid}" for aid in arxiv_ids)
        params: dict = {
            "filter": ids_param,
            "per_page": len(arxiv_ids),
            "select": "ids,abstract_inverted_index",
        }
        email = os.getenv("OPENALEX_EMAIL", "")
        key = os.getenv("OPENALEX_API_KEY", "")
        if key:
            params["api_key"] = key
        elif email:
            params["mailto"] = email
        resp = requests.get("https://api.openalex.org/works", params=params, timeout=15)
        if resp.status_code != 200:
            return
        # 构建 arxiv_id -> abstract 映射
        abstract_map: Dict[str, str] = {}
        for w in resp.json().get("results", []):
            ext_ids = w.get("ids") or {}
            arxiv_raw = ext_ids.get("arxiv", "")
            if arxiv_raw:
                aid = str(arxiv_raw).split("/")[-1].split("v")[0]
                abstract = w.get("abstract_inverted_index")
                if isinstance(abstract, dict):
                    pos = []
                    for word, idxs in abstract.items():
                        for i in idxs:
                            pos.append((i, word))
                    pos.sort()
                    abstract_map[aid] = " ".join(w for _, w in pos)
        # 回填摘要
        for d in docs:
            aid = d.get("arxiv_id", "")
            if aid in abstract_map and abstract_map[aid]:
                d["abstract"] = abstract_map[aid]
    except Exception:
        pass


_EMBED_MODEL = None


def _get_embed_model():
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        from fastembed import TextEmbedding
        _EMBED_MODEL = TextEmbedding(
            model_name=os.getenv("SAKURA_LOCAL_EMBED_MODEL", "BAAI/bge-small-en-v1.5"),
            threads=int(os.getenv("SAKURA_LOCAL_EMBED_THREADS", "8")),
            cache_dir=str(Path(__file__).resolve().parents[2] / ".cache" / "fastembed"),
        )
    return _EMBED_MODEL


def semantic_scores(query: str, texts: List[str]) -> List[float]:
    """BGE-small 余弦相似度（本地、零 API 成本）；失败返回全 0。"""
    if not texts:
        return []
    try:
        import numpy as np
        model = _get_embed_model()
        q = np.asarray(next(model.embed([query])), dtype=np.float32)
        q /= max(float(np.linalg.norm(q)), 1e-8)
        out = []
        for vec in model.embed([t[:512] or " " for t in texts], batch_size=64):
            v = np.asarray(vec, dtype=np.float32)
            v /= max(float(np.linalg.norm(v)), 1e-8)
            out.append(float(v @ q))
        return out
    except Exception:
        return [0.0] * len(texts)
