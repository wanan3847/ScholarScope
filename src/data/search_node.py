"""
SearchNode - SPAR 风格搜索节点

参考：SPAR (Search-Augmented Reasoning)
每个 SearchNode 是一轮"广度优先"搜索的状态：
    - context_query   : 经过上下文重写后的检索 query
    - survey_focus    : 当前轮关注的子主题
    - papers          : 这一轮召回的 paper 列表
    - depth           : BFS 深度
    - parent_id       : 父节点（构成搜索树）
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SearchNode:
    """SPAR 风格搜索节点。"""

    context_query: str                       # 上下文重写后的 query
    survey_focus: str = ""                   # 本轮聚焦的子主题
    papers: List[str] = field(default_factory=list)  # paper arxiv_id 列表
    depth: int = 0
    parent_id: Optional[str] = None
    children_ids: List[str] = field(default_factory=list)
    node_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "context_query": self.context_query,
            "survey_focus": self.survey_focus,
            "papers": self.papers,
            "depth": self.depth,
            "parent_id": self.parent_id,
            "children_ids": self.children_ids,
        }
