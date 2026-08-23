#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
load_unified.py
===============

科研场景下复杂学术查询智能检索赛题——统一数据加载器。

提供简洁的 API 给训练 / 评测脚本调用：

- ``load_queries(split='train')``   读取统一后的查询
- ``paper_index_lookup(paper_id)``   查论文元数据
- ``compute_f1(predicted, gold)``    F1 分数

使用示例
--------

.. code-block:: python

    from load_unified import load_queries, paper_index_lookup, compute_f1

    train = load_queries("train")
    for q in train[:3]:
        print(q["id"], q["type"], q["query"][:60])

    paper = paper_index_lookup("1909.11740")
    print(paper["title"])

    print(compute_f1(["A", "B"], ["A", "C"]))

亦可作为 CLI 调用：

::

    python load_unified.py --split test --limit 3
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Iterable, Literal

logger = logging.getLogger("load_unified")

# ---------------------------------------------------------------------------
# 默认路径
# ---------------------------------------------------------------------------

DEFAULT_ROOT = Path("/Users/yangyazhou/SakuraPaper")
DEFAULT_UNIFIED_DIR = DEFAULT_ROOT / "data_prep" / "outputs" / "unified_queries"
DEFAULT_PAPER_INDEX_DIR = DEFAULT_ROOT / "data_prep" / "outputs" / "paper_index"


# ---------------------------------------------------------------------------
# 核心 API
# ---------------------------------------------------------------------------


def _resolve_unified_dir(root: Path | None = None) -> Path:
    """解析 unified_queries 输出目录。"""
    if root is None:
        return DEFAULT_UNIFIED_DIR
    return root / "data_prep" / "outputs" / "unified_queries"


def _resolve_paper_index_dir(root: Path | None = None) -> Path:
    if root is None:
        return DEFAULT_PAPER_INDEX_DIR
    return root / "data_prep" / "outputs" / "paper_index"


def load_queries(
    split: Literal["train", "test", "all", "autoscholar", "paper_finder_bench", "litqa2",
                   "survey", "specific", "metadata", "semantic"] = "train",
    root: Path | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """加载统一后的查询数据。

    Args:
        split: 数据子集。可选 ``train`` / ``test`` / ``all`` / ``by_source`` 子名 /
               ``by_type`` 子名。
        root:  仓库根目录，None 时使用默认。
        limit: 仅返回前 N 条，便于快速测试。

    Returns:
        list[dict]，每条对应统一格式的查询。
    """
    base = _resolve_unified_dir(root)
    # 决定文件路径
    if split in ("train", "test", "all"):
        fp = base / f"{split}.jsonl"
    elif split in ("autoscholar", "paper_finder_bench", "litqa2"):
        fp = base / "by_source" / f"{split}.jsonl"
    elif split in ("survey", "specific", "metadata", "semantic"):
        fp = base / "by_type" / f"{split}.jsonl"
    else:
        raise ValueError(f"未知的 split: {split}")
    if not fp.exists():
        raise FileNotFoundError(f"找不到 {fp}，请先运行 unify_data.py")

    out: list[dict[str, Any]] = []
    with fp.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if limit is not None and i >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning("第 %d 行解析失败: %s", i + 1, e)
    return out


def _load_paper_index_impl(root: Path | None = None) -> dict[str, dict[str, Any]]:
    """读取 papers.jsonl 为 {paper_id: paper_dict}。"""
    base = _resolve_paper_index_dir(root)
    fp = base / "papers.jsonl"
    if not fp.exists():
        raise FileNotFoundError(
            f"找不到 {fp}，请先运行 paper_index.py"
        )
    out: dict[str, dict[str, Any]] = {}
    with fp.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                p = json.loads(line)
            except json.JSONDecodeError:
                continue
            pid = str(p.get("paper_id", "")).strip()
            if pid:
                out[pid] = p
    return out


_PAPER_INDEX_CACHE: dict[str, dict[str, Any]] | None = None


def paper_index_lookup(paper_id: str, root: Path | None = None) -> dict[str, Any] | None:
    """通过 paper_id 查论文元数据；未命中时返回 None。

    结果会被缓存 (进程内) 以加速多次查询。
    """
    global _PAPER_INDEX_CACHE
    if _PAPER_INDEX_CACHE is None:
        _PAPER_INDEX_CACHE = _load_paper_index_impl(root)
    return _PAPER_INDEX_CACHE.get(str(paper_id).strip())


def compute_f1(predicted: Iterable[str], gold: Iterable[str]) -> float:
    """计算 predicted vs gold 的 F1 分数 (调和平均)。

    空 gold 或空 predicted 时返回 0。
    """
    pset = {str(x) for x in predicted if x}
    gset = {str(x) for x in gold if x}
    if not gset or not pset:
        return 0.0
    tp = len(pset & gset)
    if tp == 0:
        return 0.0
    precision = tp / len(pset)
    recall = tp / len(gset)
    return 2 * precision * recall / (precision + recall)


def reset_cache() -> None:
    """清空 paper index 缓存 (测试 / 多 root 切换时使用)。"""
    global _PAPER_INDEX_CACHE
    _PAPER_INDEX_CACHE = None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="加载统一数据并打印样例 / 统计",
    )
    p.add_argument("--root", type=Path, default=None)
    p.add_argument(
        "--split", default="train",
        choices=["train", "test", "all", "autoscholar", "paper_finder_bench", "litqa2",
                 "survey", "specific", "metadata", "semantic"],
    )
    p.add_argument("--limit", type=int, default=3)
    p.add_argument("--log-level", default="INFO")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(message)s",
    )
    rows = load_queries(split=args.split, root=args.root, limit=args.limit)
    print(f"== split={args.split}  count={len(rows)} ==")
    for r in rows:
        print(json.dumps({k: r.get(k) for k in ("id", "type", "source", "query")},
                         ensure_ascii=False)[:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
