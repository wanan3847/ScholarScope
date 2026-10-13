"""
OpenAlex 后端（真实 API + Mock 双模）

真实接入（2026 起推荐免费 API key，openalex.org/settings/api，每日 $1 免费额度）：
    https://api.openalex.org/works?search=...
    https://api.openalex.org/works/{openalex_id}
    https://api.openalex.org/works?filter=cites:{openalex_id}      # 引用本文
    https://api.openalex.org/works?filter=cited_by:{openalex_id}   # 本文引用

速率限制：
    - 无 mailto：较低优先级池
    - 有 mailto：共享池，约 10 req/s
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import List, Optional

from retrieval.base import BaseRetrieval, RawPaper, _GLOBAL_PAPER_CORPUS


class OpenAlexBackend(BaseRetrieval):
    """OpenAlex API 适配器（真实 + Mock）。"""

    name = "openalex"
    BASE_URL = "https://api.openalex.org/works"
    _last_call_ts: float = 0.0
    _MIN_INTERVAL = 0.2  # 5 req/s

    def __init__(self, use_mock: bool = True, mailto: str = ""):
        super().__init__(use_mock=use_mock)
        from agent.api_settings import get_api_setting
        # OpenAlex 2026 起改为免费 key + 每日 $1 额度（openalex.org/settings/api）
        self.api_key = get_api_setting("openalex_key", "OPENALEX_API_KEY")
        # ★ 默认不带 key：带 api_key 会走"按次计费"通道，余额为 0 时直接 429；
        #   mailto Polite Pool 匿名额度独立（每日 $0.10），且不产生账单。
        #   显式设置 OPENALEX_USE_PAID_KEY=1 才启用付费 key。
        self.use_paid_key = get_api_setting("openalex_use_paid_key", "OPENALEX_USE_PAID_KEY", "0").lower() in ("1", "true", "yes")
        self.mailto = mailto or get_api_setting("openalex_email", "OPENALEX_EMAIL") or "sakura-scholar@example.com"
        self._MAX_RETRIES = 3
        self._circuit_open_until: float = 0.0
        self._consecutive_fail = 0

    def _circuit_breaker(self) -> bool:
        if time.time() < self._circuit_open_until:
            return True
        return False

    def _record_fail(self) -> None:
        self._consecutive_fail += 1
        if self._consecutive_fail >= 3:
            self._circuit_open_until = time.time() + 300.0
            self._consecutive_fail = 0

    def _record_ok(self) -> None:
        self._consecutive_fail = 0
        self._circuit_open_until = 0.0

    async def _respect_rate_limit(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_call_ts
        if elapsed < self._MIN_INTERVAL:
            await asyncio.sleep(self._MIN_INTERVAL - elapsed)
        self._last_call_ts = time.monotonic()

    def _params(self, extra: dict) -> dict:
        params = dict(extra)
        if self.mailto:
            params["mailto"] = self.mailto
        if self.use_paid_key and self.api_key:
            params["api_key"] = self.api_key
        return params

    async def _api_get(self, url: str, params: dict) -> Optional[dict]:
        if self._circuit_breaker():
            return None
        try:
            import aiohttp  # type: ignore
        except ImportError:
            try:
                import urllib.request
                import urllib.parse
                import json as _json
                full_url = f"{url}?{urllib.parse.urlencode(self._params(params))}"
                req = urllib.request.Request(full_url)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return _json.loads(resp.read().decode("utf-8"))
            except Exception:
                return None
        await self._respect_rate_limit()
        for attempt in range(self._MAX_RETRIES):
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
                    async with session.get(url, params=self._params(params)) as resp:
                        if resp.status == 200:
                            self._record_ok()
                            return await resp.json()
                        if resp.status in (429, 500, 502, 503, 504):
                            retry_after = resp.headers.get("Retry-After")
                            wait = min(2.0 ** attempt, 8.0)
                            if retry_after and retry_after.isdigit():
                                wait = min(float(retry_after), 8.0)
                            # 余额不足 / 长时间限流属"永久性"状态，重试无意义
                            try:
                                body = await resp.json()
                                if isinstance(body, dict) and "insufficient budget" in str(body.get("message", "")).lower():
                                    self._record_fail()
                                    return None
                            except Exception:
                                pass
                            self._record_fail()
                            await asyncio.sleep(wait)
                            continue
                        self._record_fail()
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
            await self._sleep(20)
            return self._generate_mock_papers(query, top_k)
        cached = self._cache_get(query, top_k)
        if cached is not None:
            return cached
        # 精度优先：title_and_abstract.search 只在标题/摘要内匹配（学术检索更准）；
        # 空结果时回退到全文 search
        params = {"filter": f"title_and_abstract.search:{query}", "per_page": min(top_k, 25)}
        data = await self._api_get(self.BASE_URL, params)
        if not data:
            data = await self._api_get(self.BASE_URL, {"search": query, "per_page": min(top_k, 25)})
        if not data:
            return []
        out: List[RawPaper] = []
        for item in data.get("results", []):
            paper = self._parse_work(item)
            if paper:
                out.append(paper)
                self._mock_corpus[paper.paper_id] = paper
        self._cache_set(query, top_k, out)
        return out

    async def get_paper(self, paper_id: str) -> Optional[RawPaper]:
        if self.use_mock:
            await self._sleep(5)
            return self._mock_corpus.get(paper_id)
        oid = self._normalize_id(paper_id)
        url = f"https://api.openalex.org/works/{oid}"
        data = await self._api_get(url, {})
        if not data:
            return None
        return self._parse_work(data)

    async def get_references(self, paper_id: str) -> List[RawPaper]:
        """本文引用了哪些论文（OpenAlex: cited_by 过滤）。"""
        if self.use_mock:
            await self._sleep(10)
            base = self._mock_corpus.get(paper_id)
            if not base:
                return []
            return [self._mock_corpus[r] for r in base.references if r in self._mock_corpus]
        oid = self._normalize_id(paper_id)
        # OpenAlex 用 filter=cited_by:{id} 表示"被 id 引用的"= id 的参考文献
        url = self.BASE_URL
        params = {"filter": f"cited_by:{oid}", "per_page": 25}
        data = await self._api_get(url, params)
        if not data:
            return []
        out: List[RawPaper] = []
        for item in data.get("results", []):
            paper = self._parse_work(item)
            if paper:
                out.append(paper)
                self._mock_corpus[paper.paper_id] = paper
        return out

    async def get_citations(self, paper_id: str) -> List[RawPaper]:
        """引用本文的论文（OpenAlex: cites 过滤）。"""
        if self.use_mock:
            await self._sleep(10)
            base = self._mock_corpus.get(paper_id)
            if not base:
                return []
            return [self._mock_corpus[c] for c in base.citations if c in self._mock_corpus]
        oid = self._normalize_id(paper_id)
        url = self.BASE_URL
        params = {"filter": f"cites:{oid}", "per_page": 25}
        data = await self._api_get(url, params)
        if not data:
            return []
        out: List[RawPaper] = []
        for item in data.get("results", []):
            paper = self._parse_work(item)
            if paper:
                out.append(paper)
                self._mock_corpus[paper.paper_id] = paper
        return out

    # ------------------------------------------------------------------ #
    # 解析辅助
    # ------------------------------------------------------------------ #
    def _parse_work(self, item: dict) -> Optional[RawPaper]:
        if not item or not item.get("title"):
            return None
        ids = item.get("ids", {}) or {}
        openalex_id = (ids.get("openalex") or "").replace("https://openalex.org/", "")
        doi_raw = item.get("doi") or ""
        doi = doi_raw.replace("https://doi.org/", "")
        # 优先用 arxiv id 作为 paper_id（与 PaSa/SPARBench gold_ids 对齐）
        arxiv_id = ids.get("arxiv") or ""
        if not arxiv_id and "arxiv" in doi.lower():
            # OpenAlex 常把 arxiv doi 写成 10.48550/arxiv.1909.05858
            import re
            m = re.search(r"arxiv\.(\d{4}\.\d{4,5})", doi, re.IGNORECASE)
            if m:
                arxiv_id = m.group(1)
        if arxiv_id:
            arxiv_id = arxiv_id.replace("https://arxiv.org/abs/", "").replace("arxiv:", "")
            # 去掉版本号 v1/v2
            import re
            arxiv_id = re.sub(r"v\d+$", "", arxiv_id)
            paper_id = arxiv_id
        else:
            paper_id = openalex_id
        # 摘要：OpenAlex 用倒排索引
        abstract = _reconstruct_abstract(item.get("abstract_inverted_index", {}))
        # 作者
        authors = [
            a.get("author", {}).get("display_name", "")
            for a in item.get("authorships", []) or []
            if a.get("author", {}).get("display_name")
        ]
        # venue
        venue = ""
        pl = item.get("primary_location") or {}
        if pl and isinstance(pl, dict):
            src = pl.get("source") or {}
            if isinstance(src, dict):
                venue = src.get("display_name", "") or ""
        # concepts → 用于 FOS 路由
        concepts = item.get("concepts", []) or []
        fos = [c.get("display_name", "") for c in concepts[:5] if c.get("display_name")]
        paper = RawPaper(
            title=item.get("title", ""),
            abstract=abstract,
            paper_id=paper_id,
            doi=doi,
            year=item.get("publication_year") or 0,
            authors=authors,
            venue=venue,
            url=item.get("doi") or (f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else ""),
            source=self.name,
        )
        # 同时存 openalex_id 用于后续 references/citations 查询
        paper.citations = [openalex_id] if openalex_id else []  # type: ignore[assignment]
        # 把 FOS 挂到 references 字段复用（OpenAlex 特有，下游可读）
        paper.references = fos  # type: ignore[assignment]
        return paper

    @staticmethod
    def _normalize_id(paper_id: str) -> str:
        """把任意 id 转成 OpenAlex 的 W 开头 id（用于 /works/{id} 查询）。

        若传入的是 arxiv id（如 2210.11416），先查全局缓存找对应 openalex id；
        若已是 W 开头，直接返回。
        """
        pid = paper_id.strip()
        if pid.startswith("https://openalex.org/"):
            return pid.split("/")[-1]
        if pid.startswith("W") and len(pid) >= 9:
            return pid
        # arxiv id：从全局缓存反查 openalex id
        cached = _GLOBAL_PAPER_CORPUS.get(pid)
        if cached and cached.citations:
            return cached.citations[0]  # 存的 openalex_id
        return pid


def _reconstruct_abstract(inv_index: dict) -> str:
    """OpenAlex 摘要为倒排索引，重建为可读文本。"""
    if not inv_index:
        return ""
    positions: list = []
    for word, locs in inv_index.items():
        for loc in locs:
            positions.append((loc, word))
    positions.sort()
    return " ".join(w for _, w in positions)
