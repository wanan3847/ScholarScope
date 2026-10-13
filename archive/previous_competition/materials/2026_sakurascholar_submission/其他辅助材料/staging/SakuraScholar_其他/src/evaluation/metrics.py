"""
评测指标

- precision_at_k
- recall_at_k
- f1_score
- token / latency 统计
"""

from __future__ import annotations

from typing import Iterable, List, Set

from retrieval.base import normalize_paper_id


def _to_set(ids: Iterable[str]) -> Set[str]:
    return {str(x) for x in ids if x}


def _gold_set(gold: List[str]) -> Set[str]:
    """gold 归一化：arXiv 去版本、DOI 小写、去前缀。"""
    return {normalize_paper_id(x) for x in gold if x}


def _paper_variants(paper_ids: List[str]) -> Set[str]:
    return {normalize_paper_id(x) for x in paper_ids if x}


def precision_at_k(
    predicted: List[str],
    gold: List[str],
    k: int = 10,
    predicted_variants: List[List[str]] | None = None,
) -> float:
    """
    Precision@K = |predicted[:k] ∩ gold| / k

    predicted_variants: 每篇论文的 ID 变体（arXiv/DOI/corpusId），任一命中即算中。
    """
    if k <= 0:
        return 0.0
    pred_topk = predicted[:k]
    gold_set = _gold_set(gold)
    if not pred_topk:
        return 0.0
    if predicted_variants is None:
        hit = sum(1 for p in pred_topk if normalize_paper_id(p) in gold_set)
    else:
        hit = 0
        for i in range(min(k, len(predicted_variants))):
            if gold_set & _paper_variants(predicted_variants[i]):
                hit += 1
    return hit / k


def recall_at_k(
    predicted: List[str],
    gold: List[str],
    k: int = 10,
    predicted_variants: List[List[str]] | None = None,
) -> float:
    """
    Recall@K = |predicted[:k] ∩ gold| / |gold|
    """
    if not gold:
        return 0.0
    pred_topk = predicted[:k]
    gold_set = _gold_set(gold)
    if predicted_variants is None:
        hit = sum(1 for p in pred_topk if normalize_paper_id(p) in gold_set)
    else:
        hit = 0
        for i in range(min(k, len(predicted_variants))):
            if gold_set & _paper_variants(predicted_variants[i]):
                hit += 1
    return hit / len(gold_set)


def f1_score(
    predicted: List[str],
    gold: List[str],
    k: int = 10,
    predicted_variants: List[List[str]] | None = None,
) -> float:
    """
    F1 = 2 * P@K * R@K / (P@K + R@K)
    """
    p = precision_at_k(predicted, gold, k, predicted_variants)
    r = recall_at_k(predicted, gold, k, predicted_variants)
    if p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


def compute_all_metrics(
    predicted: List[str],
    gold: List[str],
    k_values: List[int] | None = None,
    predicted_variants: List[List[str]] | None = None,
) -> dict:
    """
    一次性输出多组 K 值的 P / R / F1（支持多 ID 变体匹配）。
    """
    k_values = k_values or [5, 10, 20]
    out = {}
    for k in k_values:
        out[f"precision@{k}"] = round(
            precision_at_k(predicted, gold, k, predicted_variants), 4)
        out[f"recall@{k}"] = round(
            recall_at_k(predicted, gold, k, predicted_variants), 4)
        out[f"f1@{k}"] = round(
            f1_score(predicted, gold, k, predicted_variants), 4)
    return out
