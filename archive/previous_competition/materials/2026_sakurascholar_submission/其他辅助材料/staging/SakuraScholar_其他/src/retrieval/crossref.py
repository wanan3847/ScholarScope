"""
CrossRef 后端（免费、无需 key、覆盖全学科含 DOI 元数据）

真实接入：
    https://api.crossref.org/works?query=...&select=title,abstract,DOI,...
    速率限制：无 key 约 2 req/s；有 mailto 可进入礼貌池
"""

from __future__ import annotations

import re
from typing import List, Optional

from retrieval.base import BaseRetrieval, RawPaper


class CrossRefBackend(BaseRetrieval):
    """CrossRef API 适配器。"""

    name = "crossref"
    BASE_URL = "https://api.crossref.org/works"
    _last_call_ts: float = 0.0
    _MIN_INTERVAL = 0.3  # ~3 req/s

    def __init__(self, use_mock: bool = True, mailto: str = ""):
        super().__init__(use_mock=use_mock)
        self.mailto = mailto or "sakura-scholar@example.com"

    async def _respect_rate_limit(self) -> None:
        import asyncio, time
        now = time.monotonic()
        elapsed = now - self._last_call_ts
        if elapsed < self._MIN_INTERVAL:
            await asyncio.sleep(self._MIN_INTERVAL - elapsed)
        self._last_call_ts = time.monotonic()

    @staticmethod
    def _clean_query(query: str) -> str:
        """清理查询：去掉中文（CrossRef 不支持中文检索），保留英文部分。

        对于 "造斜率 OR build-up rate OR directional drilling" 这类扩展查询，
        只取第一个完整英文短语作为主查询，避免宽泛匹配导致召回大量不相关论文。
        """
        if " OR " in query or " AND " in query:
            tokens = re.split(r"\s+(?:OR|AND)\s+", query)
            en_tokens = [t.strip().strip('"') for t in tokens
                         if t.strip() and not re.search(r"[\u4e00-\u9fa5]", t)]
            if not en_tokens:
                return ""
            # 取第一个英文短语作为主查询（最具体的术语，如 "build-up rate"）
            # 这样 CrossRef 会优先返回标题/摘要精确匹配该短语的论文
            return en_tokens[0]
        if re.search(r"[\u4e00-\u9fa5]", query):
            # 中文查询：提取英文部分
            en_match = re.findall(r"[a-zA-Z][a-zA-Z\s\-]+", query)
            return en_match[0].strip() if en_match else ""
        return query.strip()

    async def search_papers(self, query: str, top_k: int = 10) -> List[RawPaper]:
        if self.use_mock:
            await self._sleep(15)
            return self._generate_mock_papers(query, top_k)
        cleaned = self._clean_query(query)
        if not cleaned:
            return []
        cached = self._cache_get(query, top_k)
        if cached is not None:
            return cached
        try:
            import aiohttp  # type: ignore
        except ImportError:
            return []
        await self._respect_rate_limit()
        # 用 query.bibliographic 让标题/摘要/容器标题同时参与匹配，
        # 比默认 query 字段相关性更准；filter 限定期刊论文，过滤掉新闻/报告
        params = {
            "query.bibliographic": cleaned,
            "rows": min(top_k, 25),
            "select": "title,abstract,DOI,published,author,container-title,URL,type",
            "filter": "type:journal-article",
            "sort": "relevance",
        }
        if self.mailto:
            params["mailto"] = self.mailto
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
                async with session.get(self.BASE_URL, params=params) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
        except Exception:
            return []
        items = (data.get("message") or {}).get("items", [])
        out: List[RawPaper] = []
        for item in items:
            title = (item.get("title") or [""])[0] or ""
            if not title:
                continue
            # 过滤低质量/非论文条目：书籍、报告、数据集等不进候选池
            itype = (item.get("type") or "").lower()
            if itype in {"book", "book-section", "book-chapter", "reference-book",
                         "monograph", "edited-book", "report", "dataset",
                         "standard", "posted-content"}:
                continue
            # 标题过短的噪声（如 "Editorial" / 单字）直接丢弃
            if len(title.split()) < 3:
                continue
            abstract = (item.get("abstract") or "").strip()
            # CrossRef 摘要常含 JATS XML 标签，清理
            abstract = re.sub(r"<[^>]+>", "", abstract)
            doi = item.get("DOI", "") or ""
            year = 0
            pub = item.get("published") or {}
            dp = pub.get("date-parts") or [[0]]
            if dp and dp[0]:
                year = dp[0][0] or 0
            authors = []
            for a in (item.get("author") or [])[:10]:
                name = (a.get("given", "") + " " + a.get("family", "")).strip()
                if name:
                    authors.append(name)
            venue = (item.get("container-title") or [""])[0] or ""
            url = item.get("URL", "") or (f"https://doi.org/{doi}" if doi else "")
            paper_id = doi or title.lower()[:50]
            paper = RawPaper(
                title=title,
                abstract=abstract,
                paper_id=paper_id,
                doi=doi,
                year=year,
                authors=authors,
                venue=venue,
                url=url,
                source=self.name,
            )
            out.append(paper)
            self._mock_corpus[paper_id] = paper
        self._cache_set(query, top_k, out)
        return out

    async def get_paper(self, paper_id: str) -> Optional[RawPaper]:
        if self.use_mock:
            await self._sleep(5)
            return self._mock_corpus.get(paper_id)
        # 按 DOI 查询
        try:
            import aiohttp  # type: ignore
        except ImportError:
            return None
        await self._respect_rate_limit()
        url = f"{self.BASE_URL}/{paper_id}"
        params = {}
        if self.mailto:
            params["mailto"] = self.mailto
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
        except Exception:
            return None
        item = data.get("message") or {}
        title = (item.get("title") or [""])[0] or ""
        if not title:
            return None
        abstract = re.sub(r"<[^>]+>", "", (item.get("abstract") or "").strip())
        doi = item.get("DOI", "") or ""
        year = 0
        pub = item.get("published") or {}
        dp = pub.get("date-parts") or [[0]]
        if dp and dp[0]:
            year = dp[0][0] or 0
        authors = []
        for a in (item.get("author") or [])[:10]:
            name = (a.get("given", "") + " " + a.get("family", "")).strip()
            if name:
                authors.append(name)
        venue = (item.get("container-title") or [""])[0] or ""
        paper = RawPaper(
            title=title,
            abstract=abstract,
            paper_id=doi or title.lower()[:50],
            doi=doi,
            year=year,
            authors=authors,
            venue=venue,
            url=item.get("URL", "") or (f"https://doi.org/{doi}" if doi else ""),
            source=self.name,
        )
        return paper

    async def get_references(self, paper_id: str) -> List[RawPaper]:
        if self.use_mock:
            await self._sleep(10)
            base = self._mock_corpus.get(paper_id)
            if not base:
                return []
            return [self._mock_corpus[r] for r in base.references if r in self._mock_corpus]
        # 真实：/works/{doi} 记录自带 reference 数组（含 DOI / 标题）
        paper = await self.get_paper(paper_id)
        if paper is None:
            return []
        try:
            import aiohttp  # type: ignore
        except ImportError:
            return []
        await self._respect_rate_limit()
        url = f"{self.BASE_URL}/{paper_id}"
        params = {"mailto": self.mailto} if self.mailto else {}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
        except Exception:
            return []
        item = data.get("message") or {}
        out: List[RawPaper] = []
        for ref in item.get("reference") or []:
            doi = ref.get("DOI", "") or ""
            title = ref.get("article-title", "") or ""
            if not title:
                # unstructured 里有时带标题，尽力提取
                un = ref.get("unstructured", "") or ""
                title = un.split(",")[0].strip()[:160]
            year = 0
            if ref.get("year"):
                try:
                    year = int(ref["year"])
                except (TypeError, ValueError):
                    year = 0
            if not doi and not title:
                continue
            p = RawPaper(
                title=title or f"Reference {ref.get('key', '')}",
                abstract="",
                paper_id=doi or title.lower()[:50],
                doi=doi,
                year=year,
                source=self.name + "_ref",
            )
            out.append(p)
            if doi:
                self._mock_corpus[doi] = p
        return out

    async def get_citations(self, paper_id: str) -> List[RawPaper]:
        if self.use_mock:
            await self._sleep(10)
            base = self._mock_corpus.get(paper_id)
            if not base:
                return []
            return [self._mock_corpus[c] for c in base.citations if c in self._mock_corpus]
        return []  # CrossRef 不直接提供引用列表
