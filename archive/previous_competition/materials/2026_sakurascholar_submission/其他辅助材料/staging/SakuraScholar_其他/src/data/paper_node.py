"""
PaperNode - PaSa 风格的树节点

参考：PaSa (Paper Search) by Yale 等
每个 PaperNode 是一篇候选论文的容器，挂在搜索树中：
    root
      ├─ child (depth=1)
      │    ├─ child (depth=2)
      │    └─ ...
      └─ ...

字段说明：
    - title / abstract / sections: 论文基本信息
    - arxiv_id: 主键（如果存在）
    - depth: 在搜索树中的深度
    - child: 子节点（引用了该论文的论文）
    - select_score: PaSa Selector 给出的 True 概率
    - source: 来自哪个检索后端
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class PaperNode:
    """PaSa 风格的论文树节点。"""

    title: str
    abstract: str = ""
    arxiv_id: str = ""
    doi: str = ""
    s2_corpus_id: str = ""
    year: int = 0
    authors: List[str] = field(default_factory=list)
    venue: str = ""
    sections: List[str] = field(default_factory=list)
    references: List[str] = field(default_factory=list)   # arxiv_id 列表
    citations: List[str] = field(default_factory=list)    # arxiv_id 列表
    url: str = ""

    # 树结构相关
    depth: int = 0
    parent_id: Optional[str] = None
    child_ids: List[str] = field(default_factory=list)

    # 评分
    select_score: float = 0.0   # PaSa Selector 概率
    rerank_score: float = 0.0  # Hidden State 重排分数
    final_score: float = 0.0   # 综合分数（用于最终排序）
    authority_score: float = 0.0
    timeliness_score: float = 0.0
    # ⑨ NRD 3-类分数
    positive_score: float = 0.0
    negative_score: float = 0.0
    neutral_score: float = 0.0
    # ⑮ MCS 元认知分数
    confidence_score: float = 0.0
    evidence_score: float = 0.0
    familiarity_score: float = 0.0

    # 元数据
    source: str = ""            # 检索后端
    semantic_score: float = 0.0  # 本地向量召回分数（无向量时为 0）
    node_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # ------------------------------------------------------------------ #
    # 工厂方法
    # ------------------------------------------------------------------ #
    @classmethod
    def from_dict(cls, data: Dict) -> "PaperNode":
        """从 dict 构造，方便从原始 API 响应转换。"""
        return cls(
            title=data.get("title", ""),
            abstract=data.get("abstract", ""),
            arxiv_id=data.get("arxiv_id", ""),
            doi=data.get("doi", ""),
            s2_corpus_id=str(data.get("s2_corpus_id", "") or ""),
            year=int(data.get("year", 0) or 0),
            authors=list(data.get("authors", [])),
            venue=data.get("venue", ""),
            sections=list(data.get("sections", [])),
            references=list(data.get("references", [])),
            citations=list(data.get("citations", [])),
            url=data.get("url", ""),
            source=data.get("source", ""),
            semantic_score=float(data.get("semantic_score", 0.0) or 0.0),
        )

    def to_dict(self) -> Dict:
        """转 dict，方便 JSON 序列化。"""
        return {
            "node_id": self.node_id,
            "title": self.title,
            "abstract": self.abstract,
            "arxiv_id": self.arxiv_id,
            "doi": self.doi,
            "s2_corpus_id": self.s2_corpus_id,
            "year": self.year,
            "authors": self.authors,
            "venue": self.venue,
            "sections": self.sections,
            "references": self.references,
            "citations": self.citations,
            "url": self.url,
            "depth": self.depth,
            "parent_id": self.parent_id,
            "child_ids": self.child_ids,
            "select_score": round(self.select_score, 4),
            "rerank_score": round(self.rerank_score, 4),
            "final_score": round(self.final_score, 4),
            "authority_score": round(self.authority_score, 4),
            "timeliness_score": round(self.timeliness_score, 4),
            "source": self.source,
            "semantic_score": round(self.semantic_score, 4),
        }

    @property
    def ids(self) -> List[str]:
        """论文的所有可用 ID（含归一化变体），供评测匹配与多 ID 输出。"""
        from retrieval.base import normalize_arxiv_id, normalize_doi
        variants: List[str] = []

        def _add(v: str) -> None:
            v = (v or "").strip()
            if v and v not in variants:
                variants.append(v)

        _add(self.arxiv_id)
        _add(normalize_arxiv_id(self.arxiv_id))
        _add(self.doi)
        _add(normalize_doi(self.doi))
        _add(self.s2_corpus_id)
        return variants

    # ------------------------------------------------------------------ #
    # 树操作
    # ------------------------------------------------------------------ #
    def add_child(self, child: "PaperNode") -> None:
        """挂载子节点。"""
        child.parent_id = self.node_id
        child.depth = self.depth + 1
        self.child_ids.append(child.node_id)

    def short_repr(self, max_abstract: int = 200) -> str:
        """调试用的简短字符串。"""
        abs_short = (self.abstract or "")[:max_abstract]
        return (
            f"[{self.source}] {self.title}\n"
            f"  - id={self.arxiv_id} year={self.year}\n"
            f"  - score={self.select_score:.3f} depth={self.depth}\n"
            f"  - {abs_short}{'...' if len(self.abstract) > max_abstract else ''}"
        )
