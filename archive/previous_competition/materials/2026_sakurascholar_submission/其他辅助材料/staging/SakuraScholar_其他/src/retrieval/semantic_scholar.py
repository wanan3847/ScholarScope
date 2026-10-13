"""
Semantic Scholar 后端（真实 API + Mock 双模）

真实接入（无需 API key，公开端点）：
    https://api.semanticscholar.org/graph/v1/paper/search
    https://api.semanticscholar.org/graph/v1/paper/{paper_id}
    https://api.semanticscholar.org/graph/v1/paper/{paper_id}/references
    https://api.semanticscholar.org/graph/v1/paper/{paper_id}/citations

速率限制（无 key）：
    - 100 次 / 5 分钟（共享池）
    有 key 时：1 次/秒，5000 次/5 分钟

切换：
    SemanticScholarBackend(use_mock=False)        # 无 key 公开端点
    SemanticScholarBackend(use_mock=False, api_key="xxx")  # 带 key
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
import time
from typing import List, Optional

from retrieval.base import BaseRetrieval, RawPaper


class SemanticScholarBackend(BaseRetrieval):
    """Semantic Scholar Graph API 适配器（真实 + Mock）。"""

    name = "semantic_scholar"
    BASE_URL = "https://api.semanticscholar.org/graph/v1"
    # 无 key 时的速率限制：约 100 次/5min = 1 次/3s
    _RATE_LIMIT_NO_KEY = 3.0
    _last_call_ts: float = 0.0
    # 匿名共享池 429 严重：按事件循环各建一把锁，串行 + 退避，避免并发打爆限流。
    # 不能用模块级单例锁——asyncio.run 每次新建事件循环，跨循环复用锁会抛
    # "bound to a different event loop"。
    _GLOBAL_LOCKS: dict = {}
    _MAX_RETRIES = 2
    _CIRCUIT_LOCK = threading.Lock()
    _circuit_state = {"open_until": 0.0, "fails": 0}

    SEARCH_FIELDS = "title,abstract,year,authors,venue,externalIds,corpusId,url,publicationTypes,citationCount"
    PAPER_FIELDS = "title,abstract,year,authors,venue,externalIds,corpusId,url,publicationTypes,citationCount,referenceCount"
    REFS_FIELDS = "title,abstract,year,authors,venue,externalIds,corpusId,url"

    def __init__(self, use_mock: bool = True, api_key: str = ""):
        super().__init__(use_mock=use_mock)
        from agent.api_settings import get_api_setting
        # 支持 .env 里的 S2_API_KEY（.env.example 已声明该变量）
        self.api_key = api_key or get_api_setting("s2_key", "S2_API_KEY")
        # 速率限制：无 key 时间隔更长
        self._min_interval = 0.5 if self.api_key else self._RATE_LIMIT_NO_KEY

    @classmethod
    def _global_lock(cls) -> asyncio.Lock:
        """获取当前事件循环对应的串行锁（不同循环互不干扰）。"""
        loop = asyncio.get_running_loop()
        key = id(loop)
        lock = cls._GLOBAL_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            cls._GLOBAL_LOCKS[key] = lock
        return lock

    def _circuit_breaker(self) -> bool:
        """连续 429 熔断：一段时间内直接跳过 S2，避免拖慢整条流水线。"""
        with type(self)._CIRCUIT_LOCK:
            return time.time() < type(self)._circuit_state["open_until"]

    def _record_429(self) -> None:
        cls = type(self)
        with cls._CIRCUIT_LOCK:
            cls._circuit_state["fails"] += 1
            if cls._circuit_state["fails"] >= 3:
                cls._circuit_state["open_until"] = time.time() + 300.0  # 熔断 5 分钟
                cls._circuit_state["fails"] = 0

    def _record_ok(self) -> None:
        cls = type(self)
        with cls._CIRCUIT_LOCK:
            cls._circuit_state["fails"] = 0
            cls._circuit_state["open_until"] = 0.0

    # ------------------------------------------------------------------ #
    # 速率控制
    # ------------------------------------------------------------------ #
    async def _respect_rate_limit(self) -> None:
        """确保两次调用间隔不小于 _min_interval 秒。"""
        now = time.monotonic()
        elapsed = now - self._last_call_ts
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
        self._last_call_ts = time.monotonic()

    def _headers(self) -> dict:
        return {"x-api-key": self.api_key} if self.api_key else {}

    # ------------------------------------------------------------------ #
    # 真实 API 调用
    # ------------------------------------------------------------------ #
    async def _api_get(self, url: str, params: dict) -> Optional[dict]:
        """发起 GET 请求，带 429/5xx 指数退避重试；最终失败返回 None。"""
        if self._circuit_breaker():
            return None
        try:
            import aiohttp  # type: ignore
        except ImportError:
            try:
                import urllib.request
                import urllib.parse
                import json as _json
                # 同步回退（无 aiohttp 时）
                full_url = f"{url}?{urllib.parse.urlencode(params)}"
                req = urllib.request.Request(full_url, headers=self._headers())
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return _json.loads(resp.read().decode("utf-8"))
            except Exception:
                return None
        # 串行化所有 S2 请求（匿名共享池并发必 429）
        async with self._global_lock():
            await self._respect_rate_limit()
            for attempt in range(self._MAX_RETRIES):
                try:
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
                        async with session.get(url, params=params, headers=self._headers()) as resp:
                            if resp.status == 200:
                                self._record_ok()
                                return await resp.json()
                            if resp.status in (429, 500, 502, 503, 504):
                                if resp.status == 429:
                                    self._record_429()
                                retry_after = resp.headers.get("Retry-After")
                                wait = min(2.0 ** attempt, 4.0)
                                if retry_after and retry_after.isdigit():
                                    wait = min(float(retry_after), 4.0)
                                logger = __import__("logging").getLogger(__name__)
                                logger.warning(
                                    "[S2] %s 限流/错误(status=%s)，第 %d 次退避 %.1fs",
                                    self.name, resp.status, attempt + 1, wait,
                                )
                                await asyncio.sleep(wait)
                                continue
                            return None
                except Exception:
                    if attempt == self._MAX_RETRIES - 1:
                        return None
                    await asyncio.sleep(1.5 ** attempt)
            return None

    # ------------------------------------------------------------------ #
    # 抽象接口实现
    # ------------------------------------------------------------------ #
    async def search_papers(self, query: str, top_k: int = 10) -> List[RawPaper]:
        if self.use_mock:
            await self._sleep(15)
            return self._generate_mock_papers(query, top_k)

        cached = self._cache_get(query, top_k)
        if cached is not None:
            return cached

        url = f"{self.BASE_URL}/paper/search"
        params = {
            "query": query,
            "limit": min(top_k, 100),
            "fields": self.SEARCH_FIELDS,
        }
        data = await self._api_get(url, params)
        if not data:
            return []
        out: List[RawPaper] = []
        for item in data.get("data", []):
            paper = self._parse_paper(item)
            if paper:
                out.append(paper)
                self._mock_corpus[paper.paper_id] = paper
        self._cache_set(query, top_k, out)
        return out

    async def get_paper(self, paper_id: str) -> Optional[RawPaper]:
        if self.use_mock:
            await self._sleep(5)
            return self._mock_corpus.get(paper_id)
        # 真实：支持 paperId / arxivId / doi 前缀
        pid = self._normalize_id(paper_id)
        url = f"{self.BASE_URL}/paper/{pid}"
        params = {"fields": self.PAPER_FIELDS}
        data = await self._api_get(url, params)
        if not data:
            return None
        return self._parse_paper(data)

    async def get_references(self, paper_id: str) -> List[RawPaper]:
        """获取参考文献（PaSa crawler 关键依赖）。"""
        if self.use_mock:
            await self._sleep(10)
            base = self._mock_corpus.get(paper_id)
            if not base:
                return []
            return [self._mock_corpus[r] for r in base.references if r in self._mock_corpus]
        pid = self._normalize_id(paper_id)
        url = f"{self.BASE_URL}/paper/{pid}/references"
        params = {"fields": self.REFS_FIELDS, "limit": 50}
        data = await self._api_get(url, params)
        if not data:
            return []
        out: List[RawPaper] = []
        for item in data.get("data", []):
            # references 返回 {citedPaper: {...}}
            cited = item.get("citedPaper", item)
            paper = self._parse_paper(cited)
            if paper:
                out.append(paper)
                self._mock_corpus[paper.paper_id] = paper
        return out

    async def get_citations(self, paper_id: str) -> List[RawPaper]:
        """获取引用本文的论文。"""
        if self.use_mock:
            await self._sleep(10)
            base = self._mock_corpus.get(paper_id)
            if not base:
                return []
            return [self._mock_corpus[c] for c in base.citations if c in self._mock_corpus]
        pid = self._normalize_id(paper_id)
        url = f"{self.BASE_URL}/paper/{pid}/citations"
        params = {"fields": self.REFS_FIELDS, "limit": 50}
        data = await self._api_get(url, params)
        if not data:
            return []
        out: List[RawPaper] = []
        for item in data.get("data", []):
            citing = item.get("citingPaper", item)
            paper = self._parse_paper(citing)
            if paper:
                out.append(paper)
                self._mock_corpus[paper.paper_id] = paper
        return out

    # ------------------------------------------------------------------ #
    # 解析辅助
    # ------------------------------------------------------------------ #
    def _parse_paper(self, item: dict) -> Optional[RawPaper]:
        """把 S2 API 返回的 dict 转成 RawPaper。"""
        if not item or not item.get("title"):
            return None
        ext = item.get("externalIds", {}) or {}
        paper_id = ext.get("ArXiv", "") or item.get("paperId", "")
        # arXiv ID 去掉版本号（gold 用裸 ID，如 1910.10683 而非 1910.10683v1）
        arxiv_id = re.sub(r"v\d+$", "", paper_id) if paper_id else ""
        corpus_id = item.get("corpusId")
        doi = ext.get("DOI", "")
        venue = item.get("venue", "") or ""
        # S2 有时 venue 为空但 publicationVenue 有
        if not venue:
            pv = item.get("publicationVenue") or {}
            venue = pv.get("name", "") if isinstance(pv, dict) else ""
        authors = [a.get("name", "") for a in item.get("authors", []) or [] if a.get("name")]
        return RawPaper(
            title=item.get("title", ""),
            abstract=item.get("abstract", "") or "",
            paper_id=paper_id,
            arxiv_id=arxiv_id,
            s2_corpus_id=str(corpus_id) if corpus_id else "",
            doi=doi,
            year=item.get("year") or 0,
            authors=authors,
            venue=venue,
            url=item.get("url", "") or (f"https://arxiv.org/abs/{paper_id}" if ext.get("ArXiv") else ""),
            source=self.name,
        )

    @staticmethod
    def _normalize_id(paper_id: str) -> str:
        """把各种 id 格式归一化成 S2 接受的格式。"""
        pid = paper_id.strip()
        # 已经是 S2 paperId（40 位 hex）
        if len(pid) == 40 and all(c in "0123456789abcdef" for c in pid.lower()):
            return pid
        # arXiv ID
        if pid.startswith("arxiv:") or "/" in pid or pid.startswith("arxiv_"):
            clean = pid.replace("arxiv:", "").replace("arxiv_", "")
            return f"ARXIV:{clean}"
        # 裸 arXiv ID（如 2205.09991 / 2205.09991v2）——此前会落空导致引文查询失败
        if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", pid):
            return f"ARXIV:{pid}"
        # DOI
        if pid.startswith("10."):
            return f"DOI:{pid}"
        if pid.startswith("doi:"):
            return f"DOI:{pid[4:]}"
        return pid
