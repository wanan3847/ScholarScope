"""
arXiv 后端（真实 API + Mock 双模）

真实接入：
    https://export.arxiv.org/api/query?search_query=...
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import List, Optional

from retrieval.base import BaseRetrieval, RawPaper


class ArxivBackend(BaseRetrieval):
    """arXiv API 适配器。"""

    name = "arxiv"
    BASE_URL = "https://export.arxiv.org/api/query"
    _last_call_ts: float = 0.0
    _MIN_INTERVAL = 0.5  # arXiv 建议 ≤ 1 req/3s，这里保守 0.5
    _MAX_RETRIES = 2
    _TIMEOUT = 10.0
    _circuit_state = {"open_until": 0.0, "fails": 0}

    def __init__(self, use_mock: bool = True):
        super().__init__(use_mock=use_mock)

    def _circuit_breaker(self) -> bool:
        return time.time() < type(self)._circuit_state["open_until"]

    def _record_fail(self) -> None:
        st = type(self)._circuit_state
        st["fails"] += 1
        if st["fails"] >= 3:
            st["open_until"] = time.time() + 300.0
            st["fails"] = 0

    def _record_ok(self) -> None:
        st = type(self)._circuit_state
        st["fails"] = 0
        st["open_until"] = 0.0

    async def _respect_rate_limit(self) -> None:
        import asyncio, time
        now = time.monotonic()
        elapsed = now - self._last_call_ts
        if elapsed < self._MIN_INTERVAL:
            await asyncio.sleep(self._MIN_INTERVAL - elapsed)
        self._last_call_ts = time.monotonic()

    @staticmethod
    def _build_search_query(query: str) -> str:
        """构造 arXiv search_query。

        - 含 AND 的查询：用 AND 连接（提高精度，要求所有词都出现）
        - 含 OR 的扩展查询：用 OR 连接（提高召回，任一词出现即可）
        - 单一短语：用引号包裹，避免空格被当 AND 拆词
        - 去掉中文（arXiv 不支持中文检索，中文字符会导致 0 结果）
        """
        q = query.strip()
        # 优先处理 AND 查询（精度优先）
        if " AND " in q:
            tokens = re.split(r"\s+AND\s+", q)
            en_tokens = [t.strip().strip('"') for t in tokens
                         if t.strip() and not re.search(r"[\u4e00-\u9fa5]", t)]
            en_tokens = [t[:-1] if t.lower().endswith("s") and len(t) > 4 else t
                         for t in en_tokens]
            if not en_tokens:
                return ""
            return " AND ".join(f'all:"{t}"' for t in en_tokens if t)
        if " OR " in q:
            # 扩展查询：去掉中文 token，保留英文
            tokens = re.split(r"\s+OR\s+", q)
            en_tokens = [t.strip().strip('"') for t in tokens
                         if t.strip() and not re.search(r"[\u4e00-\u9fa5]", t)]
            if not en_tokens:
                return ""
            # 用 OR 连接，每个 token 用引号包裹
            return " OR ".join(f'all:"{t}"' for t in en_tokens if t)
        # 单一查询：拆成词项 AND。把整个 3~6 词 query 包成精确短语会让
        # arXiv 召回接近 0；PaSa 的搜索行为本质也是关键词组合检索。
        if re.search(r"[\u4e00-\u9fa5]", q):
            # 中文查询：提取英文部分
            en_match = re.findall(r"[a-zA-Z][a-zA-Z\s\-]+", q)
            if en_match:
                return f'all:"{en_match[0].strip()}"'
            return ""
        tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9-]{1,}", q)]
        stop = {"the", "a", "an", "of", "on", "in", "and", "or", "to", "for",
                "with", "from", "by", "using", "use", "papers", "paper"}
        normalized = []
        for token in tokens:
            if token in stop:
                continue
            if token.endswith("ies") and len(token) > 5:
                token = token[:-3] + "y"
            elif token.endswith("s") and not token.endswith("ss") and len(token) > 4:
                token = token[:-1]
            if token not in normalized:
                normalized.append(token)
        tokens = normalized[:6]
        return " AND ".join(f'all:"{t}"' for t in tokens) if tokens else ""

    async def search_papers(
        self, query: str, top_k: int = 10, before_date: str = ""
    ) -> List[RawPaper]:
        if self.use_mock:
            await self._sleep(15)
            return self._generate_mock_papers(query, top_k)
        if self._circuit_breaker():
            return []
        try:
            import aiohttp  # type: ignore
        except ImportError:
            return []
        sq = self._build_search_query(query)
        if not sq:
            return []
        digits = re.sub(r"\D", "", before_date or "")[:8]
        if len(digits) == 8:
            sq = f"({sq}) AND submittedDate:[000000000000 TO {digits}2359]"
        cache_query = f"{query}\n@before:{before_date}" if before_date else query
        cached = self._cache_get(cache_query, top_k)
        if cached is not None:
            return cached
        await self._respect_rate_limit()
        params = {"search_query": sq, "max_results": min(top_k, 25), "sortBy": "relevance"}
        papers: List[RawPaper] = []
        for attempt in range(self._MAX_RETRIES):
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self._TIMEOUT)) as session:
                    async with session.get(self.BASE_URL, params=params) as resp:
                        if resp.status != 200:
                            self._record_fail()
                            await asyncio.sleep(1.0)
                            continue
                        text = await resp.text()
                papers = self._parse_atom(text)
                if papers:
                    self._record_ok()
                    break
                self._record_fail()
                await asyncio.sleep(1.0)
            except Exception:
                self._record_fail()
                await asyncio.sleep(1.0)
        self._cache_set(cache_query, top_k, papers)
        return papers

    def _parse_atom(self, xml_text: str) -> List[RawPaper]:
        """解析 arXiv Atom XML 返回 RawPaper 列表。"""
        out: List[RawPaper] = []
        try:
            import xml.etree.ElementTree as ET
            # arXiv 用多个命名空间，用 local-name 匹配避免命名空间问题
            root = ET.fromstring(xml_text)
            ns = {"a": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("a:entry", ns):
                title_node = entry.find("a:title", ns)
                title = (title_node.text or "").strip().replace("\n", " ") if title_node is not None else ""
                summary_node = entry.find("a:summary", ns)
                abstract = (summary_node.text or "").strip().replace("\n", " ") if summary_node is not None else ""
                id_node = entry.find("a:id", ns)
                raw_id = (id_node.text or "").strip() if id_node is not None else ""
                # http://arxiv.org/abs/2301.12345v1 → 2301.12345
                arxiv_id = ""
                m = re.search(r"arxiv\.org/abs/([^/]+?)(v\d+)?$", raw_id)
                if m:
                    arxiv_id = m.group(1)
                if not arxiv_id:
                    continue
                published_node = entry.find("a:published", ns)
                year = 0
                if published_node is not None and published_node.text:
                    m = re.search(r"(\d{4})", published_node.text)
                    if m:
                        year = int(m.group(1))
                authors = []
                for author in entry.findall("a:author", ns):
                    name_node = author.find("a:name", ns)
                    if name_node is not None and name_node.text:
                        authors.append(name_node.text.strip())
                # arXiv 分类作为 venue
                categories = []
                for cat in entry.findall("{http://arxiv.org/schemas/atom}primary_category"):
                    term = cat.get("term", "")
                    if term:
                        categories.append(term)
                venue = categories[0] if categories else "arXiv"
                link = ""
                for l in entry.findall("a:link", ns):
                    if l.get("type") == "text/html" or "abs" in (l.get("href") or ""):
                        link = l.get("href", "")
                        break
                if not link:
                    link = f"https://arxiv.org/abs/{arxiv_id}"
                paper = RawPaper(
                    title=title,
                    abstract=abstract,
                    paper_id=arxiv_id,
                    doi="",
                    arxiv_id=arxiv_id,
                    year=year,
                    authors=authors,
                    venue=venue,
                    url=link,
                    source=self.name,
                )
                out.append(paper)
                self._mock_corpus[arxiv_id] = paper
        except Exception:
            pass
        return out

    async def get_paper(self, paper_id: str) -> Optional[RawPaper]:
        if self.use_mock:
            await self._sleep(5)
            return self._mock_corpus.get(paper_id)
        # 真实模式：通过 id_list 查询
        try:
            import aiohttp  # type: ignore
        except ImportError:
            return None
        await self._respect_rate_limit()
        params = {"id_list": paper_id, "max_results": 1}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.get(self.BASE_URL, params=params) as resp:
                    if resp.status != 200:
                        return None
                    text = await resp.text()
            papers = self._parse_atom(text)
            return papers[0] if papers else None
        except Exception:
            return None

    async def get_references(self, paper_id: str) -> List[RawPaper]:
        if self.use_mock:
            await self._sleep(10)
            base = self._mock_corpus.get(paper_id)
            if not base:
                return []
            return [self._mock_corpus[r] for r in base.references if r in self._mock_corpus]
        return []  # arXiv API 不直接提供参考文献

    async def get_citations(self, paper_id: str) -> List[RawPaper]:
        if self.use_mock:
            await self._sleep(10)
            base = self._mock_corpus.get(paper_id)
            if not base:
                return []
            return [self._mock_corpus[c] for c in base.citations if c in self._mock_corpus]
        return []  # arXiv API 不直接提供引用列表
