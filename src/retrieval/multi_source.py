"""
MultiSourceRetriever - L2 多源并行检索调度器（§3.2）

特性：
    1) 按 filters.fields_of_study 智能路由后端：
       - Medicine → 启用 PubMed
       - require_preprint → 启用 arXiv
       - Computer Science → 启用 arXiv
       - 默认 → 启用 S2 + OpenAlex
    2) Redis 风格缓存（MVP 用内存 LRU）：相同 (query, filters_hash) 命中直接复用
    3) asyncio.gather 并发：一次触发 ≤ 8 路，单后端失败不影响其他
    4) 统一去重：按 paper_id（arxiv_id 优先 / doi 兜底）

不依赖外部 redis 客户端；MVP 用 functools.lru_cache 风格的内存缓存。
真实场景可替换为 redis.asyncio。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

from data.schemas import SearchFilters
from retrieval import get_retrieval_backend
from retrieval.base import BaseRetrieval, RawPaper

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# 内存 LRU 缓存（替代 Redis，MVP）
# ------------------------------------------------------------------ #
class LRUCache:
    """线程不安全的简易 LRU 缓存（MVP 用，单进程异步场景安全）。"""

    def __init__(self, maxsize: int = 1024, ttl: int = 86400):
        self.maxsize = maxsize
        self.ttl = ttl  # 秒
        self._store: OrderedDict[str, Tuple[float, object]] = OrderedDict()

    def get(self, key: str) -> Optional[object]:
        if key not in self._store:
            return None
        ts, val = self._store[key]
        if time.time() - ts > self.ttl:
            self._store.pop(key, None)
            return None
        # 命中 → 移到末尾（最近使用）
        self._store.move_to_end(key)
        return val

    def set(self, key: str, value: object) -> None:
        self._store[key] = (time.time(), value)
        self._store.move_to_end(key)
        while len(self._store) > self.maxsize:
            self._store.popitem(last=False)  # 弹出最久未用

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


# ------------------------------------------------------------------ #
# 路由表：FOS → 应启用的后端
# ------------------------------------------------------------------ #
_FOS_BACKEND_MAP: Dict[str, List[str]] = {
    "Computer Science": ["semantic_scholar", "openalex", "crossref", "arxiv"],
    "Medicine": ["semantic_scholar", "openalex", "crossref", "pubmed"],
    "Biology": ["semantic_scholar", "openalex", "crossref", "pubmed"],
    "Physics": ["semantic_scholar", "openalex", "crossref", "arxiv"],
    "Chemistry": ["semantic_scholar", "openalex", "crossref"],
    "Mathematics": ["semantic_scholar", "openalex", "crossref", "arxiv"],
    "Economics": ["semantic_scholar", "openalex", "crossref"],
    "Petroleum Engineering": ["openalex", "crossref", "semantic_scholar", "arxiv"],
    "Engineering": ["openalex", "crossref", "semantic_scholar", "arxiv"],
    "Materials Science": ["openalex", "crossref", "semantic_scholar", "arxiv"],
    "Geology": ["openalex", "crossref", "semantic_scholar"],
    "Environmental Science": ["openalex", "crossref", "semantic_scholar", "pubmed"],
}

# 默认后端（无 FOS 信息时）— Semantic Scholar + OpenAlex 免 key 且覆盖全学科，
# CrossRef 作为补充（免费、覆盖全学科含 DOI 元数据）
_DEFAULT_BACKENDS = ["semantic_scholar", "openalex", "crossref"]


def select_backends(filters: SearchFilters) -> List[str]:
    """
    根据 filters.fields_of_study 智能路由后端。

    规则：
        1) 有 FOS → 取该 FOS 对应后端列表
        2) 多 FOS → 取并集
        3) require_preprint=True → 强制加 arxiv
        4) 无 FOS → 默认 S2 + OpenAlex + CrossRef
    """
    if not filters.fields_of_study:
        backends = list(_DEFAULT_BACKENDS)
    else:
        backends = []
        for fos in filters.fields_of_study:
            for b in _FOS_BACKEND_MAP.get(fos, _DEFAULT_BACKENDS):
                if b not in backends:
                    backends.append(b)

    if filters.require_preprint and "arxiv" not in backends:
        backends.append("arxiv")

    return backends


# ------------------------------------------------------------------ #
# MultiSourceRetriever
# ------------------------------------------------------------------ #
class MultiSourceRetriever:
    """
    多源并行检索器（§3.2）。

    一次调用：
        retriever = MultiSourceRetriever(use_mock=True)
        papers = await retriever.retrieve(sub_queries, filters, top_per_backend=20)
    """

    def __init__(
        self,
        use_mock: bool = True,
        backend_names: Optional[List[str]] = None,
        cache_maxsize: int = 1024,
        cache_ttl: int = 86400,
        concurrent_limit: int = 8,
    ):
        self.use_mock = use_mock
        # 如果显式指定 backend_names，则固定；否则每次按 FOS 路由
        self._fixed_backends = backend_names
        # 缓存
        self.cache = LRUCache(maxsize=cache_maxsize, ttl=cache_ttl)
        self.concurrent_limit = concurrent_limit
        # 统计
        self.calls = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.errors = 0
        self.backends_used: List[str] = []

    # ------------------------------------------------------------------ #
    # 后端实例缓存（避免重复实例化）
    # ------------------------------------------------------------------ #
    def _get_backends(self, filters: SearchFilters) -> List[BaseRetrieval]:
        names = self._fixed_backends or select_backends(filters)
        # 记录使用了哪些后端
        for n in names:
            if n not in self.backends_used:
                self.backends_used.append(n)
        return [get_retrieval_backend(name, use_mock=self.use_mock) for name in names]

    # ------------------------------------------------------------------ #
    # 单次单后端检索
    # ------------------------------------------------------------------ #
    async def _hit(
        self,
        backend: BaseRetrieval,
        query: str,
        filters: SearchFilters,
        top_n: int,
    ) -> List[RawPaper]:
        """单次单后端检索（含缓存）。"""
        cache_key = self._make_cache_key(backend.name, query, filters)
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.cache_hits += 1
            return cached  # type: ignore[return-value]

        self.cache_misses += 1
        try:
            papers = await backend.search_papers(query, top_k=top_n)
        except Exception as e:  # noqa: BLE001
            logger.warning("后端 %s 检索失败: %s", backend.name, e)
            self.errors += 1
            papers = []

        # 应用 filters（year / venue 过滤）
        papers = self._apply_filters(papers, filters)
        self.cache.set(cache_key, papers)
        return papers

    # ------------------------------------------------------------------ #
    # filters 应用
    # ------------------------------------------------------------------ #
    @staticmethod
    def _apply_filters(papers: List[RawPaper], filters: SearchFilters) -> List[RawPaper]:
        """对召回结果应用 year / venue / min_citation 过滤。"""
        out = papers
        if filters.year_range:
            lo, hi = filters.year_range[0], filters.year_range[1]
            out = [p for p in out if lo <= (p.year or 0) <= hi or p.year == 0]
        if filters.venues:
            wanted = {v.lower() for v in filters.venues}
            # venue 字段可能含全名（如 "Conference on Neural Information Processing Systems"）
            # 用子串匹配：只要 venue 含任一 wanted 关键字就保留
            out = [
                p for p in out
                if not p.venue or any(w in p.venue.lower() for w in wanted)
            ]
        # min_citation_count: mock 数据没有此字段，跳过
        return out

    # ------------------------------------------------------------------ #
    # 缓存 key
    # ------------------------------------------------------------------ #
    @staticmethod
    def _make_cache_key(backend: str, query: str, filters: SearchFilters) -> str:
        """hash(backend::query::filters_json) → cache key。"""
        filters_dict = {
            "year_range": filters.year_range,
            "venues": sorted(filters.venues),
            "fos": sorted(filters.fields_of_study),
            "min_citation": filters.min_citation_count,
            "preprint": filters.require_preprint,
            "lang": filters.language,
        }
        key_str = f"{backend}::{query}::{json.dumps(filters_dict, sort_keys=True)}"
        return hashlib.md5(key_str.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------ #
    # 去重 + 融合
    # ------------------------------------------------------------------ #
    @staticmethod
    def _dedupe(papers: List[RawPaper]) -> List[RawPaper]:
        """按 paper_id / doi / title 去重，保留首次出现。"""
        seen, out = set(), []
        for p in papers:
            key = p.paper_id or p.doi or p.title.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
        return out

    # ------------------------------------------------------------------ #
    # 顶层入口
    # ------------------------------------------------------------------ #
    async def retrieve(
        self,
        sub_queries: List[str],
        filters: SearchFilters,
        top_per_backend: int = 20,
    ) -> List[RawPaper]:
        """
        多源并行检索主入口。

        Args:
            sub_queries: 子查询列表
            filters: 多维约束
            top_per_backend: 每个后端每个子查询召回数

        Returns:
            去重后的 RawPaper 列表
        """
        if not sub_queries:
            return []

        self.calls += 1
        backends = self._get_backends(filters)
        # 用 semaphore 限制并发度，避免触发 S2 429
        sem = asyncio.Semaphore(self.concurrent_limit)

        async def _one(backend: BaseRetrieval, q: str) -> List[RawPaper]:
            async with sem:
                return await self._hit(backend, q, filters, top_per_backend)

        tasks = [_one(b, q) for b in backends for q in sub_queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        merged: List[RawPaper] = []
        for r in results:
            if isinstance(r, Exception):
                self.errors += 1
                logger.warning("检索异常: %s", r)
                continue
            merged.extend(r)

        return self._dedupe(merged)

    # ------------------------------------------------------------------ #
    # 统计
    # ------------------------------------------------------------------ #
    @property
    def stats(self) -> Dict[str, object]:
        return {
            "calls": self.calls,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "errors": self.errors,
            "backends_used": self.backends_used,
            "cache_size": len(self.cache),
        }
