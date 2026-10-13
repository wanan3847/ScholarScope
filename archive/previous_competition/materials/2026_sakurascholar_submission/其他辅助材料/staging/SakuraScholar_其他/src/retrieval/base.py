"""
检索后端抽象基类

所有具体后端（Semantic Scholar / OpenAlex / PubMed / arXiv）都继承 BaseRetrieval，
并实现：
    - async search_papers(query, top_k) -> List[RawPaper]
    - async get_paper(paper_id)         -> RawPaper
    - async get_references(paper_id)    -> List[RawPaper]
    - async get_citations(paper_id)     -> List[RawPaper]

MVP 阶段默认 use_mock=True，子类提供 mock 数据；
真实使用时切换 use_mock=False + 填入 API key 即可。
"""

from __future__ import annotations

import abc
import asyncio
import hashlib
import random
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ------------------------------------------------------------------ #
# 论文 ID 归一化工具（跨后端 / 评测共用）
#
# 不同后端返回的同一篇论文可能带不同 ID 形式：
#   arXiv:2205.09991v2 / 2205.09991 / 2205.09991v2
#   DOI:10.1234/abc / 10.1234/ABC
#   S2 corpusId: 265660036（数字串）
# 归一化后统一为裸 ID，保证评测匹配与去重可靠。
# ------------------------------------------------------------------ #

_ARXIV_RE = re.compile(r"^\s*(?:arxiv:)?(\d{4}\.\d{4,5})(?:v\d+)?\s*$", re.IGNORECASE)
_ARXIV_OLD_RE = re.compile(r"^\s*(?:arxiv:)?([a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?\s*$", re.IGNORECASE)
_DOI_RE = re.compile(r"^\s*(?:doi:)?(10\.\S+?)\s*$", re.IGNORECASE)
_CORPUS_RE = re.compile(r"^\s*(\d{5,12})\s*$")
_ARXIV_DOI_RE = re.compile(r"^10\.48550/arxiv\.(\d{4}\.\d{4,5})(?:v\d+)?$", re.IGNORECASE)


def normalize_arxiv_id(value: str) -> str:
    """arXiv ID → 裸 ID（去前缀、去版本），如 'arXiv:2205.09991v2' → '2205.09991'。"""
    if not value:
        return ""
    m = _ARXIV_RE.match(value) or _ARXIV_OLD_RE.match(value)
    return m.group(1).lower() if m else value.strip().lower().replace("arxiv:", "")


def normalize_doi(value: str) -> str:
    """DOI → 小写裸 DOI（去 doi: 前缀）。"""
    if not value:
        return ""
    v = value.strip()
    m = _DOI_RE.match(v)
    if m:
        return m.group(1).lower()
    v = v.lower()
    if v.startswith("doi:"):
        v = v[4:]
    return v


def normalize_paper_id(value: str) -> str:
    """通用归一化：先按 arXiv，再按 DOI，否则小写去除空白。"""
    if not value:
        return ""
    # arXiv 的 DOI 形式（10.48550/arxiv.2205.09991）→ 裸 arXiv ID
    m = _ARXIV_DOI_RE.match(value.strip())
    if m:
        return m.group(1).lower()
    v = normalize_arxiv_id(value)
    if v != value.strip():
        return v
    v = normalize_doi(value)
    if v != value.strip():
        return v
    return value.strip().lower()


def paper_id_variants(paper: "RawPaper") -> List[str]:
    """一篇论文的所有可用 ID（含归一化形式），供评测匹配与输出。"""
    out: List[str] = []

    def _add(v: str) -> None:
        v = (v or "").strip()
        if not v or v in out:
            return
        out.append(v)

    _add(paper.arxiv_id)
    _add(normalize_arxiv_id(paper.arxiv_id))
    _add(normalize_arxiv_id(paper.paper_id))
    _add(paper.doi)
    _add(normalize_doi(paper.doi))
    _add(normalize_paper_id(paper.doi))  # arXiv DOI → 裸 arXiv ID
    _add(paper.s2_corpus_id)
    _add(paper.paper_id)
    return out


@dataclass
class RawPaper:
    """后端返回的原始论文结构。"""

    title: str
    abstract: str = ""
    paper_id: str = ""                 # 各家后端自己的 id
    doi: str = ""
    arxiv_id: str = ""                 # arXiv ID（仅 arXiv 后端设置，如 "2301.12345"
    s2_corpus_id: str = ""             # Semantic Scholar corpusId（paper_finder gold 格式）
    year: int = 0
    authors: List[str] = field(default_factory=list)
    venue: str = ""
    url: str = ""
    references: List[str] = field(default_factory=list)
    citations: List[str] = field(default_factory=list)
    source: str = ""
    semantic_score: float = 0.0       # 可选的本地向量召回分数

    def to_dict(self) -> Dict:
        return {
            "title": self.title,
            "abstract": self.abstract,
            "arxiv_id": self.arxiv_id or (self.paper_id if self._paper_id_is_arxiv() else ""),
            "doi": self.doi,
            "s2_corpus_id": self.s2_corpus_id,
            "year": self.year,
            "authors": self.authors,
            "venue": self.venue,
            "url": self.url,
            "references": self.references,
            "citations": self.citations,
            "source": self.source,
            "semantic_score": self.semantic_score,
            "paper_id": self.paper_id,
        }

    def _paper_id_is_arxiv(self) -> bool:
        """判断 paper_id 是否是 arXiv ID 格式（如 "2301.12345" 或 "2301.12345v1"）。"""
        if not self.paper_id:
            return False
        # arXiv ID 格式：YYMM.NNNNN 或 YYMM.NNNNNvN，或旧格式 subject-class/YYMMNNN
        if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", self.paper_id):
            return True
        return False

    def to_dict_variants(self) -> Dict:
        """to_dict + 归一化 ID 变体（供评测/输出多 ID 匹配）。"""
        d = self.to_dict()
        d["ids"] = paper_id_variants(self)
        return d


# 模块级全局论文缓存：所有后端实例共享，跨请求可查找
_GLOBAL_PAPER_CORPUS: Dict[str, RawPaper] = {}


class BaseRetrieval(abc.ABC):
    """检索后端基类。"""

    name: str = "base"

    def __init__(self, use_mock: bool = True):
        self.use_mock = use_mock
        # 所有后端实例共享同一个全局缓存
        self._mock_corpus = _GLOBAL_PAPER_CORPUS
        # 真实检索结果缓存：(name, query, top_k) -> (ts, papers)
        self._search_cache: Dict[tuple, tuple] = {}
        self._search_cache_ttl = 1800.0  # 30 分钟

    # ------------------------------------------------------------------ #
    # 检索缓存（效率优化：同进程内相同 query 不重复打 API）
    # ------------------------------------------------------------------ #
    def _cache_get(self, query: str, top_k: int):
        key = (self.name, query.strip().lower(), top_k)
        hit = self._search_cache.get(key)
        if hit and time.time() - hit[0] < self._search_cache_ttl:
            return hit[1]
        return None

    def _cache_set(self, query: str, top_k: int, papers: List[RawPaper]) -> None:
        key = (self.name, query.strip().lower(), top_k)
        self._search_cache[key] = (time.time(), papers)
        # 简单清理：超过 4096 条时丢弃最旧一半
        if len(self._search_cache) > 4096:
            items = sorted(self._search_cache.items(), key=lambda kv: kv[1][0])
            for k, _ in items[: len(items) // 2]:
                self._search_cache.pop(k, None)

    # ------------------------------------------------------------------ #
    # 抽象接口
    # ------------------------------------------------------------------ #
    @abc.abstractmethod
    async def search_papers(self, query: str, top_k: int = 10) -> List[RawPaper]:
        """根据 query 检索 top_k 论文。"""

    @abc.abstractmethod
    async def get_paper(self, paper_id: str) -> Optional[RawPaper]:
        """按 id 获取单篇论文。"""

    @abc.abstractmethod
    async def get_references(self, paper_id: str) -> List[RawPaper]:
        """获取参考文献列表。"""

    @abc.abstractmethod
    async def get_citations(self, paper_id: str) -> List[RawPaper]:
        """获取引用本文的论文列表。"""

    # ------------------------------------------------------------------ #
    # Mock 工具
    # ------------------------------------------------------------------ #
    def _deterministic_paper_id(self, query: str, salt: str = "") -> str:
        """基于 query 生成确定性的 mock id。"""
        h = hashlib.md5(f"{salt}|{query}".encode("utf-8")).hexdigest()[:10]
        return f"mock-{h}"

    def _generate_mock_papers(self, query: str, top_k: int) -> List[RawPaper]:
        """
        根据 query 确定性生成 mock 论文列表。
        保证：相同 query + 相同 top_k -> 完全相同结果。
        """
        seed = int(hashlib.md5(query.encode("utf-8")).hexdigest()[:8], 16)
        rng = random.Random(seed)

        # 把 query 切分成关键词
        q_tokens = [t for t in re.split(r"[^A-Za-z0-9\u4e00-\u9fa5]+", query) if len(t) > 2]
        q_keyword = " ".join(q_tokens[:3]) if q_tokens else query.strip()

        # 真实风格的论文标题模板
        title_templates = [
            "A Comprehensive Survey of {kw}",
            "{kw}: A Review and Future Directions",
            "Recent Advances in {kw}",
            "Towards Efficient {kw}: Methods and Evaluations",
            "{kw} in Practice: An Empirical Study",
            "Benchmarking {kw} Across Diverse Domains",
            "Exploring {kw}: Theory and Applications",
            "{kw}: State-of-the-Art and Open Challenges",
            "A Deep Dive into {kw}",
            "On the Effectiveness of {kw}",
            "{kw} Revisited: New Insights",
            "Improving {kw} with Novel Strategies",
            "{kw}: From Theory to Practice",
            "Understanding {kw}: A Systematic Review",
            "Advancing {kw} through Innovation",
        ]

        # 摘要模板
        abstract_templates = [
            "This paper presents a comprehensive study on {kw}. We propose a novel framework that significantly outperforms existing baselines across multiple benchmarks. Extensive experiments demonstrate the effectiveness and efficiency of our approach, achieving state-of-the-art results on standard datasets.",
            "We introduce a new method for {kw} that addresses key limitations in prior work. Our approach combines insights from multiple disciplines and offers substantial improvements in both accuracy and efficiency. We provide thorough ablation studies and analyses to validate each component of our contribution.",
            "This work investigates {kw} from a fresh perspective. We develop a robust methodology and conduct large-scale evaluation. The results reveal interesting patterns and suggest promising directions for future research in this area.",
            "Motivated by recent progress in {kw}, we present a comprehensive analysis and a practical system. Our method achieves competitive performance while maintaining simplicity and interpretability. We discuss the implications and outline key challenges that remain.",
            "In this paper, we tackle the problem of {kw} by proposing an integrated solution. We build upon established techniques and introduce targeted improvements. Extensive experimentation shows that our approach is effective across diverse settings.",
        ]

        venues = ["NeurIPS", "ICML", "ACL", "AAAI", "KDD", "EMNLP", "ICLR", "CVPR", "ICCV", "WWW", "SIGIR", "WSDM"]
        first_names = ["Alice", "Bob", "Carol", "David", "Eva", "Frank", "Grace", "Henry", "Irene", "Jack", "Karen", "Leo"]
        last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Chen", "Wang", "Li", "Zhang"]

        out: List[RawPaper] = []
        for i in range(top_k):
            paper_id = self._deterministic_paper_id(query, salt=f"{self.name}-{i}")
            year = 2018 + rng.randint(0, 8)
            n_authors = rng.randint(2, 5)
            authors = [f"{rng.choice(first_names)} {rng.choice(last_names)}" for _ in range(n_authors)]
            venue = rng.choice(venues)
            tpl = title_templates[i % len(title_templates)]
            a_tpl = abstract_templates[i % len(abstract_templates)]

            # 对特定位置用更具体的修饰
            modifier = ""
            if i == 0:
                modifier = " "
            elif i == 1:
                modifier = "Deep "
            elif i == 2:
                modifier = "Efficient "
            elif i == 3:
                modifier = "Scalable "

            title = tpl.format(kw=(modifier + q_keyword).strip() if q_keyword else "Research")
            abstract = a_tpl.format(kw=q_keyword or "this research topic")

            paper = RawPaper(
                title=title,
                abstract=abstract,
                paper_id=paper_id,
                year=year,
                authors=authors,
                venue=venue,
                url=f"https://example.org/{self.name}/{paper_id}",
                source=self.name,
            )
            paper.references = [
                self._deterministic_paper_id(query, salt=f"{self.name}-ref-{i}-{j}")
                for j in range(rng.randint(1, 4))
            ]
            paper.citations = [
                self._deterministic_paper_id(query, salt=f"{self.name}-cite-{i}-{j}")
                for j in range(rng.randint(0, 3))
            ]
            out.append(paper)
            self._mock_corpus[paper_id] = paper
        return out

    # ------------------------------------------------------------------ #
    # 默认实现
    # ------------------------------------------------------------------ #
    async def _safe_call(self, coro, default=None):
        """统一异常处理：单后端失败不应让整个 pipeline 崩溃。"""
        try:
            return await coro
        except Exception:  # noqa: BLE001
            return default if default is not None else []

    def _sleep(self, ms: int = 10):
        """mock 模式下模拟小延时，让异步 pipeline 真实感更强。"""
        return asyncio.sleep(ms / 1000.0)
