"""
Pydantic schemas - 跨模块共享的数据契约

为端到端 pipeline 制定统一的 JSON Schema，方便：
  - 评测（evaluation/runner.py）
  - Web/前端结果序列化（保持字段稳定）

本文件包含 15 大创新（§4.5-4.12）所需的全部数据结构。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PaperRecord(BaseModel):
    """统一对外的论文结构。"""

    model_config = ConfigDict(extra="ignore")

    title: str
    abstract: str = ""
    arxiv_id: str = ""
    doi: str = ""
    s2_corpus_id: str = ""              # Semantic Scholar corpusId（paper_finder gold 格式）
    ids: List[str] = Field(default_factory=list)  # 全部可用 ID（归一化变体）
    year: int = 0
    authors: List[str] = Field(default_factory=list)
    venue: str = ""
    url: str = ""
    source: str = ""                    # 来自哪个检索后端
    select_score: float = 0.0
    rerank_score: float = 0.0
    final_score: float = 0.0


class SubQuery(BaseModel):
    """查询分解后的子查询。"""

    text: str
    intent: str = "general"             # survey / specific / metadata / semantic
    priority: int = 0


class SearchFilters(BaseModel):
    """§3.1 多维约束 - 从 query 中识别的过滤项。"""

    year_range: Optional[List[int]] = None       # [2018, 2024]
    venues: List[str] = Field(default_factory=list)  # ["NeurIPS", "ICML"]
    fields_of_study: List[str] = Field(default_factory=list)  # ["CS", "Medicine"]
    min_citation_count: int = 0
    require_preprint: bool = False                # 是否需要 arXiv 预印本
    language: str = ""                            # zh / en


class QueryIntent(BaseModel):
    """查询理解模块的输出（§3.1 LLMProcessedQuery）。"""

    original_query: str
    intent: str = "general"
    sub_queries: List[SubQuery] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    # §3.1 扩展字段
    rewritten_query: str = ""                     # 给向量检索用的精简 query
    keyword_query: str = ""                       # 给 BM25 / API 用的关键词串（OR 连接）
    search_filters: SearchFilters = Field(default_factory=SearchFilters)
    high_level_outline: Optional[str] = None      # 综述的章节大纲
    needs_paper_recommendation: bool = True
    needs_table_comparison: bool = False


class PipelineStats(BaseModel):
    """单次 pipeline 调用的统计信息。"""

    model_config = ConfigDict(extra="ignore")

    api_calls: int = 0
    tokens: int = 0
    retrieval_calls: int = 0
    elapsed_seconds: float = 0.0
    backends_used: List[str] = Field(default_factory=list)
    innovations_used: List[str] = Field(default_factory=list)  # 15 大创新启用列表
    llm_mode: str = "mock"  # "real" | "mock"


class RelationshipEdge(BaseModel):
    """论文之间的引用 / 关联关系边。"""

    src: str
    dst: str
    relation: str = "cite"             # cite / co-cite / similar
    weight: float = 1.0


class ComparisonTable(BaseModel):
    """论文对比表（多模态输出）。"""

    columns: List[str]
    rows: List[List[str]] = Field(default_factory=list)


class OrchestratorResult(BaseModel):
    """端到端结果 - 最终交付给用户的 JSON。"""

    query: str
    intent: QueryIntent
    papers: List[PaperRecord] = Field(default_factory=list)
    relationships: List[RelationshipEdge] = Field(default_factory=list)
    table: Optional[ComparisonTable] = None
    summary: str = ""
    stats: PipelineStats = Field(default_factory=PipelineStats)
    # --- 15 大创新扩展字段 ---
    query_graph: Optional[Dict[str, Any]] = None          # ① QaG
    timeline: Optional[List[Dict[str, Any]]] = None       # ⑦ TET
    disagreement: Optional[Dict[str, Any]] = None         # ⑥ DBE
    meta_scores: Optional[Dict[str, Any]] = None          # ⑮ MCS
    clarifications: Optional[List[str]] = None            # ⑭ AQR
    qdar: Optional[Dict[str, Any]] = None                 # ⑯ QDAR 预算计划


# ================================================================== #
# ① QaG — Query-as-Graph（§4.5.1）
# ================================================================== #

class GraphEntity(BaseModel):
    """查询图中的实体节点。"""
    name: str
    entity_type: str = "concept"           # paper / method / dataset / task / concept
    aliases: List[str] = Field(default_factory=list)


class GraphRelation(BaseModel):
    """查询图中的关系边。"""
    head: str                               # 实体名
    tail: str                               # 实体名
    relation_type: str = "related_to"       # compared_to / evaluated_on / extends / applied_to
    weight: float = 1.0


class QueryGraph(BaseModel):
    """把自然语言 query 形式化为 (entities, relations, constraints) 三元组。"""
    entities: List[GraphEntity] = Field(default_factory=list)
    relations: List[GraphRelation] = Field(default_factory=list)
    constraints: Dict[str, Any] = Field(default_factory=dict)  # year=[2018,2022], task="NER"
    intent: str = "semantic"                # survey / compare / specific / metadata
    high_level_outline: Optional[str] = None
    original_query: str = ""


class SubTask(BaseModel):
    """QaG 分解出的原子子任务。"""
    task_type: str = "join"                 # join / filter / entity_lookup
    left: str = ""
    right: str = ""
    relation: str = ""
    filters: Dict[str, Any] = Field(default_factory=dict)
    query_text: str = ""                    # 用于 L2 检索的自然语言 query


# ================================================================== #
# ③ APR — Adaptive Pipeline Router（§4.5.3）
# ================================================================== #

class PipelineConfig(BaseModel):
    """子流水线配置 — 由 APR 路由器选择。"""
    skip_bfs: bool = False
    max_depth: int = 2
    skip_refchain: bool = False
    trigger_hs: bool = False
    alpha: float = 0.5                      # selector 权重
    beta: float = 0.5                       # rerank 权重
    label: str = "survey"                   # metadata / specific / compare / survey


# ================================================================== #
# ⑥ DBE — Disagreement Ensemble（§4.7.1）
# ================================================================== #

class AgentVote(BaseModel):
    """单个 Agent 对一篇 paper 的投票。"""
    agent_name: str
    paper_id: str
    score: float


class DisagreementResult(BaseModel):
    """DBE 输出：共识 / 分歧 / 置信度。"""
    consensus: List[str] = Field(default_factory=list)         # paper_ids
    disagreement: List[str] = Field(default_factory=list)     # paper_ids
    confidence: Dict[str, float] = Field(default_factory=dict) # paper_id -> [0,1]


# ================================================================== #
# ⑦ TET — Topic Evolution Tracking（§4.7.2）
# ================================================================== #

class TimelineEntry(BaseModel):
    """主题演化时间线中的单个年条目。"""
    year: int
    theme: str = ""
    paper_ids: List[str] = Field(default_factory=list)
    key_breakthrough: str = ""
    connections_to_next: List[str] = Field(default_factory=list)


# ================================================================== #
# ⑨ NRD — Negative-Result Detection（§4.7.4）
# ================================================================== #

class ThreeClassScore(BaseModel):
    """3-类 Selector 输出。"""
    positive: float = 0.0
    negative: float = 0.0
    neutral: float = 0.0

    @property
    def label(self) -> str:
        if self.positive >= self.negative and self.positive >= self.neutral:
            return "positive"
        if self.negative >= self.positive and self.negative >= self.neutral:
            return "negative"
        return "neutral"


# ================================================================== #
# ⑫ SAR — Stance-Aware Retrieval（§4.8.3）
# ================================================================== #

class StanceResult(BaseModel):
    """立场检测结果。"""
    supports: float = 0.0
    opposes: float = 0.0
    neutral: float = 0.0

    @property
    def label(self) -> str:
        if self.supports >= self.opposes and self.supports >= self.neutral:
            return "supports"
        if self.opposes >= self.supports and self.opposes >= self.neutral:
            return "opposes"
        return "neutral"


# ================================================================== #
# ⑮ MCS — Meta-Cognition Selector（§4.10.1）
# ================================================================== #

class MetaCognitionOutput(BaseModel):
    """元认知 Selector 输出。"""
    score: float = 0.0
    confidence: float = 0.0                 # [0,1]
    evidence: float = 0.0                   # [0,1]
    familiarity: float = 0.0               # [0,1]
    decision: str = "uncertain"            # high_confidence / guess / uncertain
