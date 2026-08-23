"""
⑩ SSCP — Self-Supervised Citation Pretraining（§4.8.1）

引文图自监督预训练。

核心创新：首次把"引文图"作为学术 embedding 的 SSL 目标。

SSL 目标：
    - Positive pair: (paper_i, paper_j)  其中 j ∈ i.references 或 j.cites i
    - Negative pair: 随机采样
    - 损失: contrastive InfoNCE
"""

from __future__ import annotations

import hashlib
import math
import random
from typing import List, Tuple

from data.paper_node import PaperNode


def _hash_to_vec(text: str, dim: int = 16) -> List[float]:
    """文本 -> 确定向量（模拟 encoder）。"""
    # 用多次 hash 生成 dim 维向量
    vec = []
    for i in range(dim):
        h = hashlib.md5(f"{text}_{i}".lower().encode("utf-8")).digest()
        val = ((h[0] / 255.0) * 2 - 1)
        vec.append(val)
    # 归一化
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _cosine(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def info_nce(
    z_i: List[float],
    z_pos: List[List[float]],
    z_neg: List[List[float]],
    temperature: float = 0.07,
) -> float:
    """
    InfoNCE 对比损失。

    L = -log(exp(sim(z_i, z_pos) / τ) /
              (exp(sim(z_i, z_pos) / τ) + Σ exp(sim(z_i, z_neg) / τ)))
    """
    if not z_pos:
        return 0.0

    # 正样本 logit（取第一个正样本）
    pos_sim = _cosine(z_i, z_pos[0]) / temperature

    # 负样本 logits
    neg_sims = [_cosine(z_i, z_neg_j) / temperature for z_neg_j in z_neg] if z_neg else []

    # 分母 = exp(pos) + Σ exp(neg)
    max_logit = max(pos_sim, max(neg_sims) if neg_sims else pos_sim)
    pos_exp = math.exp(pos_sim - max_logit)
    neg_exp_sum = sum(math.exp(ns - max_logit) for ns in neg_sims)

    denom = pos_exp + neg_exp_sum
    if denom == 0:
        return 0.0

    loss = -math.log(pos_exp / denom)
    return loss


class SSCPModel:
    """
    Self-Supervised Citation Pretraining Model。

    MVP 实现：用 hash 向量模拟 encoder，InfoNCE 损失。
    真实实现：用 Qwen2.5-7B encoder + InfoNCE loss。
    """

    def __init__(self, dim: int = 16, temperature: float = 0.07):
        self.dim = dim
        self.temperature = temperature
        self.encoder = _hash_to_vec  # MVP: hash 模拟
        # 训练统计
        self.training_loss: List[float] = []

    # ------------------------------------------------------------------ #
    # 编码
    # ------------------------------------------------------------------ #
    def encode(self, paper: PaperNode) -> List[float]:
        """编码一篇论文。"""
        text = f"{paper.title} {paper.abstract or ''}"
        return self.encoder(text, dim=self.dim)

    def encode_text(self, text: str) -> List[float]:
        """编码一段文本。"""
        return self.encoder(text, dim=self.dim)

    # ------------------------------------------------------------------ #
    # 训练步骤
    # ------------------------------------------------------------------ #
    def train_step(
        self,
        anchor: PaperNode,
        positive_papers: List[PaperNode],
        negative_papers: List[PaperNode],
    ) -> float:
        """
        单步训练：
            anchor: 锚点论文
            positive_papers: 引文图正样本（references + citations）
            negative_papers: 随机采样负样本
        """
        z_i = self.encode(anchor)
        z_pos = [self.encode(p) for p in positive_papers]
        z_neg = [self.encode(p) for p in negative_papers]

        loss = info_nce(z_i, z_pos, z_neg, self.temperature)
        self.training_loss.append(loss)
        return loss

    # ------------------------------------------------------------------ #
    # 完整训练
    # ------------------------------------------------------------------ #
    def train(
        self,
        papers: List[PaperNode],
        paper_pool: dict | None = None,
        epochs: int = 1,
        neg_per_anchor: int = 5,
    ) -> List[float]:
        """
        在论文集上做自监督预训练。

        papers: 训练集
        paper_pool: arxiv_id -> PaperNode 映射（用于查找引文图正样本）
        """
        pool = paper_pool or {}
        all_losses: List[float] = []

        for epoch in range(epochs):
            random.shuffle(papers)
            for paper in papers:
                # 正样本：references + citations 中的论文
                pos_ids = paper.references + paper.citations
                pos_papers = [pool[pid] for pid in pos_ids if pid in pool]

                if not pos_papers:
                    continue

                # 负样本：随机采样
                neg_papers = random.sample(
                    [p for p in papers if p.arxiv_id != paper.arxiv_id],
                    min(neg_per_anchor, len(papers) - 1),
                )

                loss = self.train_step(paper, pos_papers, neg_papers)
                all_losses.append(loss)

        return all_losses

    # ------------------------------------------------------------------ #
    # 检索
    # ------------------------------------------------------------------ #
    def retrieve(
        self,
        query: str,
        papers: List[PaperNode],
        top_k: int = 10,
    ) -> List[Tuple[float, PaperNode]]:
        """用训练好的 encoder 做检索。"""
        q_vec = self.encode_text(query)
        scored = []
        for p in papers:
            p_vec = self.encode(p)
            sim = _cosine(q_vec, p_vec)
            scored.append((sim, p))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]
