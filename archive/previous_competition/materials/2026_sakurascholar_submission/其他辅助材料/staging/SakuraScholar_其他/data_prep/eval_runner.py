#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_runner.py
==============

科研场景下复杂学术查询智能检索赛题——评测器。

输入
----
- 评测集 (默认 ``data_prep/outputs/unified_queries/test.jsonl``)
- 检索系统输出 (json/jsonl)，每条记录形如：

    {
      "id":        "query_xxx",
      "papers":    [{"paper_id": "...", "score": 0.93, "markdown_evidence": "..."}, ...],
      "answer":    "...",                 // (可选) 4 选 1 答案 (LitQA2)
      "metrics":   {"api_calls": 4, "tokens": 1234, "latency_sec": 5.6}
    }

输出
----
- ``data/eval_results/metrics.json``    汇总指标
- ``data/eval_results/per_query.jsonl``  每条详情
- ``data/eval_results/report.md``       人类可读报告

计算指标
--------
- Precision@K (K=20, 50, 100)
- Recall@K    (K=20, 50, 100)
- F1          (gold vs predicted 的调和平均)
- mean API calls / tokens / latency

使用示例
--------
::

    python eval_runner.py \\
        --predictions runs/my_run/predictions.jsonl \\
        --out-dir /Users/yangyazhou/SakuraPaper/data_prep/outputs/eval_results
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from tqdm import tqdm

logger = logging.getLogger("eval_runner")


def setup_logging(level: str = "INFO") -> None:
    fmt = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def compute_f1(predicted: Iterable[str], gold: Iterable[str]) -> float:
    """F1 (precision × recall 的调和平均)。空 gold 时返回 0。"""
    pset = {str(x) for x in predicted if x}
    gset = {str(x) for x in gold if x}
    if not gset:
        return 0.0
    if not pset:
        return 0.0
    tp = len(pset & gset)
    if tp == 0:
        return 0.0
    precision = tp / len(pset)
    recall = tp / len(gset)
    return 2 * precision * recall / (precision + recall)


def compute_precision_at_k(predicted: list[str], gold: set[str], k: int) -> float:
    if k <= 0 or not predicted:
        return 0.0
    top = predicted[:k]
    if not gold:
        return 0.0
    return sum(1 for x in top if x in gold) / min(k, len(top))


def compute_recall_at_k(predicted: list[str], gold: set[str], k: int) -> float:
    if k <= 0 or not gold or not predicted:
        return 0.0
    top = predicted[:k]
    hit = sum(1 for x in top if x in gold)
    return hit / len(gold)


def safe_mean(xs: list[float]) -> float:
    return float(statistics.mean(xs)) if xs else 0.0


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.exists():
        logger.error("文件不存在: %s", path)
        return out
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning("解析失败: %s ...", e)
    return out


def load_predictions(path: Path) -> dict[str, dict[str, Any]]:
    """支持 jsonl 与 json (list[dict]) 两种格式。返回 {id: pred}。"""
    if not path.exists():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8")
    text_stripped = text.strip()
    out: dict[str, dict[str, Any]] = {}
    if text_stripped.startswith("["):
        # json list
        arr = json.loads(text_stripped)
        for rec in arr:
            rid = str(rec.get("id", "")).strip()
            if rid:
                out[rid] = rec
    else:
        # jsonl
        for line in text_stripped.splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = str(rec.get("id", "")).strip()
            if rid:
                out[rid] = rec
    return out


# ---------------------------------------------------------------------------
# 评测主体
# ---------------------------------------------------------------------------


KS = (20, 50, 100)


@dataclass
class PerQueryMetrics:
    id: str
    n_pred: int
    n_gold: int
    n_hit: int
    f1: float
    p_at_20: float
    p_at_50: float
    p_at_100: float
    r_at_20: float
    r_at_50: float
    r_at_100: float
    api_calls: int = 0
    tokens: int = 0
    latency_sec: float = 0.0
    answer_correct: bool | None = None


def evaluate_one(q: dict[str, Any], pred: dict[str, Any] | None) -> PerQueryMetrics:
    qid = q["id"]
    gold_ids = [str(g.get("paper_id", "")).strip() for g in q.get("gold_papers", [])]
    gold_set = {g for g in gold_ids if g}
    if pred is None:
        return PerQueryMetrics(
            id=qid, n_pred=0, n_gold=len(gold_set), n_hit=0, f1=0.0,
            p_at_20=0.0, p_at_50=0.0, p_at_100=0.0,
            r_at_20=0.0, r_at_50=0.0, r_at_100=0.0,
        )

    # 兼容两种预测结构
    if "papers" in pred and isinstance(pred["papers"], list):
        pred_ids = [str(p.get("paper_id", "")).strip() for p in pred["papers"]]
    else:
        pred_ids = [str(x).strip() for x in pred.get("paper_ids", [])]
    pred_ids = [p for p in pred_ids if p]
    n_hit = len({p for p in pred_ids if p in gold_set})

    f1 = compute_f1(pred_ids, gold_ids)
    p20 = compute_precision_at_k(pred_ids, gold_set, 20)
    p50 = compute_precision_at_k(pred_ids, gold_set, 50)
    p100 = compute_precision_at_k(pred_ids, gold_set, 100)
    r20 = compute_recall_at_k(pred_ids, gold_set, 20)
    r50 = compute_recall_at_k(pred_ids, gold_set, 50)
    r100 = compute_recall_at_k(pred_ids, gold_set, 100)

    metrics_block = pred.get("metrics", {}) or {}
    api_calls = int(metrics_block.get("api_calls", 0) or 0)
    tokens = int(metrics_block.get("tokens", 0) or 0)
    latency = float(metrics_block.get("latency_sec", 0.0) or 0.0)

    # LitQA2 答案正确性
    answer_correct: bool | None = None
    if q.get("source") == "litqa2" and "answer" in pred:
        ans = str(pred.get("answer", "")).strip()
        correct = str(q.get("correct_answer", "")).strip()
        answer_correct = ans.lower() == correct.lower()

    return PerQueryMetrics(
        id=qid, n_pred=len(pred_ids), n_gold=len(gold_set), n_hit=n_hit,
        f1=f1, p_at_20=p20, p_at_50=p50, p_at_100=p100,
        r_at_20=r20, r_at_50=r50, r_at_100=r100,
        api_calls=api_calls, tokens=tokens, latency_sec=latency,
        answer_correct=answer_correct,
    )


def aggregate(per_query: list[PerQueryMetrics]) -> dict[str, Any]:
    n = len(per_query)
    f1s = [x.f1 for x in per_query]
    p20 = [x.p_at_20 for x in per_query]
    p50 = [x.p_at_50 for x in per_query]
    p100 = [x.p_at_100 for x in per_query]
    r20 = [x.r_at_20 for x in per_query]
    r50 = [x.r_at_50 for x in per_query]
    r100 = [x.r_at_100 for x in per_query]
    api = [x.api_calls for x in per_query if x.api_calls]
    tokens = [x.tokens for x in per_query if x.tokens]
    lat = [x.latency_sec for x in per_query if x.latency_sec]
    ans_correct = [x.answer_correct for x in per_query if x.answer_correct is not None]
    ans_acc = safe_mean([1.0 if v else 0.0 for v in ans_correct]) if ans_correct else None

    summary = {
        "n_queries": n,
        "f1": safe_mean(f1s),
        "precision@20": safe_mean(p20),
        "precision@50": safe_mean(p50),
        "precision@100": safe_mean(p100),
        "recall@20": safe_mean(r20),
        "recall@50": safe_mean(r50),
        "recall@100": safe_mean(r100),
        "mean_api_calls": safe_mean(api),
        "mean_tokens": safe_mean(tokens),
        "mean_latency_sec": safe_mean(lat),
        "litqa2_accuracy": ans_acc,
    }
    # 按 source 聚合
    by_source: dict[str, list[PerQueryMetrics]] = defaultdict(list)
    # 我们没有 source 信息，需要在 per_query 里扩展；这里跳过
    return summary


def write_report(summary: dict[str, Any], per_query: list[PerQueryMetrics], out_dir: Path) -> None:
    fp = out_dir / "report.md"
    lines: list[str] = []
    lines.append("# 评测报告 (eval_report)\n")
    lines.append("> 由 `eval_runner.py` 自动生成。\n")
    lines.append("## 汇总指标\n")
    lines.append("| 指标 | 数值 |")
    lines.append("| ---- | ---- |")
    for k, v in summary.items():
        if isinstance(v, float):
            lines.append(f"| `{k}` | {v:.4f} |")
        else:
            lines.append(f"| `{k}` | {v} |")
    lines.append("")
    lines.append("## 详情 (前 10 条)\n")
    lines.append("| id | n_pred | n_gold | n_hit | F1 | P@20 | R@20 | api | tokens | latency(s) |")
    lines.append("| -- | ------ | ------ | ----- | -- | ---- | ---- | --- | ------ | ---------- |")
    for x in per_query[:10]:
        lines.append(
            f"| `{x.id}` | {x.n_pred} | {x.n_gold} | {x.n_hit} | {x.f1:.3f} | "
            f"{x.p_at_20:.3f} | {x.r_at_20:.3f} | {x.api_calls} | {x.tokens} | {x.latency_sec:.2f} |"
        )
    fp.write_text("\n".join(lines), encoding="utf-8")
    logger.info("已写入报告: %s", fp)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="检索系统统一评测器")
    p.add_argument(
        "--gold", type=Path,
        default=Path("/Users/yangyazhou/SakuraPaper/data_prep/outputs/unified_queries/test.jsonl"),
        help="金标 jsonl 路径 (默认 test.jsonl)",
    )
    p.add_argument(
        "--predictions", type=Path, required=True,
        help="系统输出 json 或 jsonl",
    )
    p.add_argument(
        "--out-dir", type=Path,
        default=Path("/Users/yangyazhou/SakuraPaper/data_prep/outputs/eval_results"),
        help="输出目录",
    )
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.log_level)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    gold = load_jsonl(args.gold)
    if not gold:
        logger.error("金标为空：%s", args.gold)
        return 1
    preds = load_predictions(args.predictions)
    logger.info("金标: %d, 预测: %d", len(gold), len(preds))

    per_query: list[PerQueryMetrics] = []
    for q in tqdm(gold, desc="evaluate", dynamic_ncols=True):
        pred = preds.get(q["id"])
        per_query.append(evaluate_one(q, pred))

    summary = aggregate(per_query)
    summary["n_predicted"] = len(preds)
    summary["n_uncovered"] = sum(1 for x in per_query if x.n_pred == 0)

    # 落盘
    (args.out_dir / "metrics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    with (args.out_dir / "per_query.jsonl").open("w", encoding="utf-8") as fh:
        for x in per_query:
            fh.write(json.dumps(x.__dict__, ensure_ascii=False) + "\n")
    write_report(summary, per_query, args.out_dir)
    logger.info("汇总: %s", json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
