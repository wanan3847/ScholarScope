"""
PubMed 后端（MVP mock 实现）

真实接入：
    https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=...
    https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=...
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from retrieval.base import BaseRetrieval, RawPaper


class PubMedBackend(BaseRetrieval):
    """PubMed E-utilities 适配器。"""

    name = "pubmed"
    BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def __init__(self, use_mock: bool = True, api_key: str = ""):
        super().__init__(use_mock=use_mock)
        self.api_key = api_key

    async def search_papers(self, query: str, top_k: int = 10) -> List[RawPaper]:
        if self.use_mock:
            await self._sleep(25)
            return self._generate_mock_papers(query, top_k)
        cached = self._cache_get(query, top_k)
        if cached is not None:
            return cached
        try:
            import aiohttp  # type: ignore
        except ImportError:
            return []
        params = {"db": "pubmed", "term": query, "retmax": min(top_k, 25), "retmode": "json"}
        if self.api_key:
            params["api_key"] = self.api_key
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            # 1) esearch 拿 idlist
            async with session.get(f"{self.BASE_URL}/esearch.fcgi", params=params) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
            ids = (data.get("esearchresult") or {}).get("idlist", [])
            if not ids:
                return []
            # 2) esummary 拿标题/作者/年份/venue
            sum_params = {"db": "pubmed", "id": ",".join(ids), "retmode": "json"}
            if self.api_key:
                sum_params["api_key"] = self.api_key
            summaries: Dict[str, dict] = {}
            try:
                async with session.get(f"{self.BASE_URL}/esummary.fcgi", params=sum_params) as resp:
                    if resp.status == 200:
                        sd = await resp.json()
                        summaries = sd.get("result", {}) or {}
            except Exception:
                pass
            # 3) efetch(xml) 拿摘要（esummary 不含摘要）
            abstracts = await self._fetch_abstracts(session, ids)
        out: List[RawPaper] = []
        for pid in ids:
            s = summaries.get(pid, {}) or {}
            title = s.get("title", "") or ""
            authors = [
                (a.get("name", "") or "")
                for a in s.get("authors", []) or []
                if a.get("name")
            ]
            venue = ""
            for aid in s.get("articleids", []) or []:
                if aid.get("idtype") == "pubmed":
                    continue
                if aid.get("value"):
                    venue = aid.get("value", "")
                    break
            year = 0
            pubdate = s.get("pubdate", "") or ""
            if pubdate:
                m = re.search(r"(\d{4})", pubdate)
                if m:
                    year = int(m.group(1))
            doi = ""
            for aid in s.get("articleids", []) or []:
                if aid.get("idtype") == "doi":
                    doi = aid.get("value", "") or ""
                    break
            abstract = abstracts.get(pid, "") or ""
            paper = RawPaper(
                title=title or f"PubMed:{pid}",
                abstract=abstract,
                paper_id=pid,
                doi=doi,
                year=year,
                authors=authors,
                venue=venue,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
                source=self.name,
            )
            out.append(paper)
            self._mock_corpus[pid] = paper
        self._cache_set(query, top_k, out)
        return out

    async def _fetch_abstracts(self, session, ids: List[str]) -> Dict[str, str]:
        """efetch(xml) 解析摘要。失败返回空 dict。"""
        out: Dict[str, str] = {}
        try:
            import aiohttp  # type: ignore
            params = {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}
            if self.api_key:
                params["api_key"] = self.api_key
            async with session.get(f"{self.BASE_URL}/efetch.fcgi", params=params) as resp:
                if resp.status != 200:
                    return out
                xml_text = await resp.text()
            # 轻量 XML 解析（避免依赖 lxml）
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml_text)
            for art in root.findall(".//PubmedArticle"):
                pmid_node = art.find(".//PMID")
                if pmid_node is None or not pmid_node.text:
                    continue
                pmid = pmid_node.text.strip()
                # 摘要可能在 <Abstract><AbstractText>...</AbstractText></Abstract>
                abs_parts = []
                for at in art.findall(".//Abstract/AbstractText"):
                    label = at.get("Label", "")
                    txt = "".join(at.itertext()).strip()
                    if txt:
                        abs_parts.append(f"{label}: {txt}" if label else txt)
                if abs_parts:
                    out[pmid] = " ".join(abs_parts)
        except Exception:
            pass
        return out

    async def get_paper(self, paper_id: str) -> Optional[RawPaper]:
        if self.use_mock:
            await self._sleep(5)
            return self._mock_corpus.get(paper_id)
        return None

    async def get_references(self, paper_id: str) -> List[RawPaper]:
        # PubMed 不直接提供 references 列表；mock 模式沿用默认实现
        if self.use_mock:
            await self._sleep(10)
            base = self._mock_corpus.get(paper_id)
            if not base:
                return []
            return [self._mock_corpus[r] for r in base.references if r in self._mock_corpus]
        return []

    async def get_citations(self, paper_id: str) -> List[RawPaper]:
        if self.use_mock:
            await self._sleep(10)
            base = self._mock_corpus.get(paper_id)
            if not base:
                return []
            return [self._mock_corpus[c] for c in base.citations if c in self._mock_corpus]
        return []
