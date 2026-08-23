#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stats.py
========

科研场景下复杂学术查询智能检索赛题——数据统计脚本。

对 ``unified_queries/all_queries.jsonl`` 与 ``paper_index/papers.jsonl`` 做
全方位统计，输出到 ``data_prep/outputs/stats/``：

- ``summary.json``           全部指标 (json)
- ``summary.md``             人类可读报告 (markdown)
- ``figures/``               可选：matplotlib 图表

统计维度
--------
- 各数据集样本数
- 唯一论文数
- 论文年份分布
- 学科分布 (从 source 字段推断)
- 查询长度分布 (字符 & token)
- gold_papers 长度分布
- 字段缺失率 (query / gold_papers / abstract / authors / year)
- LitQA2 选项数与正确答案位置分布

使用示例
--------
::

    python stats.py --root /Users/yangyazhou/SakuraPaper
    python stats.py --no-figures
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from tqdm import tqdm

logger = logging.getLogger("stats")


def setup_logging(level: str = "INFO") -> None:
    fmt = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------


def safe_mean(xs: list[float]) -> float:
    return float(statistics.mean(xs)) if xs else 0.0


def safe_median(xs: list[float]) -> float:
    return float(statistics.median(xs)) if xs else 0.0


_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def estimate_tokens(s: str) -> int:
    return len(_TOKEN_RE.findall(s or ""))


def percentile(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs_sorted = sorted(xs)
    k = (len(xs_sorted) - 1) * p
    f, c = int(k), int(k) + 1
    if c >= len(xs_sorted):
        return xs_sorted[-1]
    if f < 0:
        return xs_sorted[0]
    return xs_sorted[f] + (xs_sorted[c] - xs_sorted[f]) * (k - f)


def compute_query_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    """查询级统计。"""
    by_source: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    qlens_char: list[int] = []
    qlens_tok: list[int] = []
    gold_lens: list[int] = []
    n_with_query = 0
    n_with_gold = 0
    n_with_options = 0
    n_with_criteria = 0
    option_counts: Counter[int] = Counter()
    n_litqa_correct_first = 0
    n_litqa_total = 0
    for r in records:
        by_source[r.get("source", "unknown")] += 1
        by_type[r.get("type", "unknown")] += 1
        q = r.get("query") or ""
        if q:
            n_with_query += 1
            qlens_char.append(len(q))
            qlens_tok.append(estimate_tokens(q))
        gp = r.get("gold_papers") or []
        if gp:
            n_with_gold += 1
            gold_lens.append(len(gp))
        if r.get("options"):
            n_with_options += 1
            option_counts[len(r["options"])] += 1
        if r.get("scorer_criteria"):
            n_with_criteria += 1
        if r.get("source") == "litqa2":
            n_litqa_total += 1
            if r.get("options") and r.get("correct_answer"):
                if r["options"][0] == r["correct_answer"]:
                    n_litqa_correct_first += 1
    return {
        "total": len(records),
        "by_source": dict(by_source),
        "by_type": dict(by_type),
        "query_length": {
            "n_with_query": n_with_query,
            "char_mean": safe_mean(qlens_char),
            "char_median": safe_median(qlens_char),
            "char_p95": percentile(qlens_char, 0.95),
            "char_max": max(qlens_char) if qlens_char else 0,
            "token_mean": safe_mean(qlens_tok),
            "token_p95": percentile(qlens_tok, 0.95),
        },
        "gold_papers": {
            "n_with_gold": n_with_gold,
            "len_mean": safe_mean(gold_lens),
            "len_median": safe_median(gold_lens),
            "len_p95": percentile(gold_lens, 0.95),
            "len_max": max(gold_lens) if gold_lens else 0,
        },
        "n_with_options": n_with_options,
        "n_with_criteria": n_with_criteria,
        "option_counts": dict(option_counts),
        "litqa2": {
            "total": n_litqa_total,
            "correct_first_ratio": (n_litqa_correct_first / n_litqa_total)
            if n_litqa_total else 0.0,
        },
    }


def compute_paper_stats(papers: list[dict[str, Any]]) -> dict[str, Any]:
    """论文级统计。"""
    by_source: Counter[str] = Counter()
    by_year: Counter[int] = Counter()
    n_with_abstract = 0
    n_with_authors = 0
    n_with_venue = 0
    n_with_title = 0
    for p in papers:
        src = p.get("source") or "missing"
        by_source[src] += 1
        y = p.get("year")
        if isinstance(y, int):
            by_year[y] += 1
        if p.get("abstract"):
            n_with_abstract += 1
        if p.get("authors"):
            n_with_authors += 1
        if p.get("venue"):
            n_with_venue += 1
        if p.get("title"):
            n_with_title += 1
    n = len(papers)
    return {
        "total": n,
        "by_source": dict(by_source),
        "by_year": {str(k): v for k, v in sorted(by_year.items())},
        "with_abstract": n_with_abstract,
        "with_authors": n_with_authors,
        "with_venue": n_with_venue,
        "with_title": n_with_title,
        "missing_ratio": {
            "abstract": 1 - (n_with_abstract / n) if n else 0,
            "authors": 1 - (n_with_authors / n) if n else 0,
            "venue": 1 - (n_with_venue / n) if n else 0,
            "title": 1 - (n_with_title / n) if n else 0,
        },
    }


def compute_field_missing(records: list[dict[str, Any]]) -> dict[str, Any]:
    """字段缺失率。"""
    fields = ("id", "query", "type", "source", "gold_papers", "distractors",
              "options", "correct_answer", "scorer_criteria")
    out: dict[str, Any] = {}
    n = max(len(records), 1)
    for f in fields:
        miss = 0
        for r in records:
            v = r.get(f)
            if v is None or v == "" or v == [] or v == {}:
                miss += 1
        out[f] = miss / n
    return out


# ---------------------------------------------------------------------------
# 可选可视化
# ---------------------------------------------------------------------------


def make_figures(stats: dict[str, Any], out_dir: Path) -> list[Path]:
    """生成 matplotlib 图，返回生成的文件路径列表 (失败时返回空)。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore
    except Exception as e:  # noqa: BLE001
        logger.warning("matplotlib 不可用 (%s)，跳过图表生成", e)
        return []
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    # 1) by_source 柱状图
    qs = stats["queries"]
    plt.figure(figsize=(6, 4))
    items = sorted(qs["by_source"].items())
    plt.bar([k for k, _ in items], [v for _, v in items])
    plt.title("Queries by source")
    plt.xticks(rotation=20)
    plt.tight_layout()
    fp = fig_dir / "queries_by_source.png"
    plt.savefig(fp, dpi=120)
    plt.close()
    paths.append(fp)

    # 2) by_type 柱状图
    plt.figure(figsize=(6, 4))
    items = sorted(qs["by_type"].items())
    plt.bar([k for k, _ in items], [v for _, v in items])
    plt.title("Queries by type")
    plt.tight_layout()
    fp = fig_dir / "queries_by_type.png"
    plt.savefig(fp, dpi=120)
    plt.close()
    paths.append(fp)

    # 3) year 分布
    ps = stats.get("papers", {})
    by_year = ps.get("by_year", {})
    if by_year:
        years = sorted(by_year.keys())
        counts = [by_year[y] for y in years]
        plt.figure(figsize=(8, 4))
        plt.bar(years, counts)
        plt.title("Papers by year")
        plt.xticks(rotation=45)
        plt.tight_layout()
        fp = fig_dir / "papers_by_year.png"
        plt.savefig(fp, dpi=120)
        plt.close()
        paths.append(fp)
    return paths


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------


def write_markdown_report(stats: dict[str, Any], figures: list[Path], out_dir: Path) -> None:
    fp = out_dir / "summary.md"
    lines: list[str] = []
    lines.append("# 数据统计报告 (summary)\n")
    lines.append("> 由 `stats.py` 自动生成。\n")

    qs = stats["queries"]
    lines.append("## 1. 查询统计\n")
    lines.append(f"- 总记录数：**{qs['total']}**")
    lines.append("- 按数据源：")
    for k, v in sorted(qs["by_source"].items()):
        lines.append(f"  - `{k}`: {v}")
    lines.append("- 按查询类型：")
    for k, v in sorted(qs["by_type"].items()):
        lines.append(f"  - `{k}`: {v}")
    lines.append("")
    qlen = qs["query_length"]
    lines.append("### 查询长度\n")
    lines.append(f"- 字符数：mean={qlen['char_mean']:.1f}, median={qlen['char_median']}, "
                 f"p95={qlen['char_p95']}, max={qlen['char_max']}")
    lines.append(f"- token 数：mean={qlen['token_mean']:.1f}, p95={qlen['token_p95']}")
    lines.append("")
    g = qs["gold_papers"]
    lines.append("### gold_papers 长度\n")
    lines.append(f"- mean={g['len_mean']:.2f}, median={g['len_median']}, "
                 f"p95={g['len_p95']}, max={g['len_max']}")
    lines.append("")
    if qs["option_counts"]:
        lines.append("### 选项数分布 (LitQA2)\n")
        for k, v in sorted(qs["option_counts"].items(), key=lambda x: int(x[0])):
            lines.append(f"- {k} 项: {v} 条")
        lines.append("")

    if "papers" in stats:
        ps = stats["papers"]
        lines.append("## 2. 论文统计\n")
        lines.append(f"- 唯一论文数：**{ps['total']}**")
        lines.append("- 元数据来源：")
        for k, v in sorted(ps["by_source"].items()):
            lines.append(f"  - `{k}`: {v}")
        lines.append(f"- 含 abstract：{ps['with_abstract']}")
        lines.append(f"- 含 authors：{ps['with_authors']}")
        lines.append(f"- 含 venue：{ps['with_venue']}")
        lines.append("")
        lines.append("### 字段缺失率\n")
        for k, v in ps["missing_ratio"].items():
            lines.append(f"- `{k}`: {v*100:.1f}%")
        lines.append("")

    lines.append("## 3. 字段缺失率 (queries)\n")
    for k, v in sorted(stats["field_missing"].items()):
        lines.append(f"- `{k}`: {v*100:.1f}%")
    lines.append("")

    if figures:
        lines.append("## 4. 图表\n")
        for fig in figures:
            rel = fig.relative_to(out_dir)
            lines.append(f"![{fig.stem}]({rel})")
        lines.append("")

    fp.write_text("\n".join(lines), encoding="utf-8")
    logger.info("已写入报告: %s", fp)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="统一数据集统计")
    p.add_argument("--root", type=Path, default=Path("/Users/yangyazhou/SakuraPaper"))
    p.add_argument(
        "--out", type=Path,
        default=Path("/Users/yangyazhou/SakuraPaper/data_prep/outputs/stats"),
    )
    p.add_argument("--no-figures", action="store_true", help="跳过图表生成")
    p.add_argument("--log-level", default="INFO")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.log_level)
    args.out.mkdir(parents=True, exist_ok=True)

    unified_fp = args.root / "data_prep" / "outputs" / "unified_queries" / "all_queries.jsonl"
    papers_fp = args.root / "data_prep" / "outputs" / "paper_index" / "papers.jsonl"
    if not unified_fp.exists():
        logger.error("找不到 %s，请先运行 unify_data.py", unified_fp)
        return 1

    # 读 unified
    logger.info("读取 %s", unified_fp)
    records: list[dict[str, Any]] = []
    with unified_fp.open(encoding="utf-8") as fh:
        for line in tqdm(fh, desc="load unified", dynamic_ncols=True):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    # 读 papers
    papers: list[dict[str, Any]] = []
    if papers_fp.exists():
        logger.info("读取 %s", papers_fp)
        with papers_fp.open(encoding="utf-8") as fh:
            for line in tqdm(fh, desc="load papers", dynamic_ncols=True):
                line = line.strip()
                if not line:
                    continue
                try:
                    papers.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    else:
        logger.warning("未找到 %s，跳过论文统计", papers_fp)

    # 计算
    stats: dict[str, Any] = {
        "queries": compute_query_stats(records),
        "field_missing": compute_field_missing(records),
    }
    if papers:
        stats["papers"] = compute_paper_stats(papers)

    # 写 summary.json
    (args.out / "summary.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    logger.info("已写入 summary.json")

    # 图表
    figures: list[Path] = []
    if not args.no_figures:
        figures = make_figures(stats, args.out)
        for f in figures:
            logger.info("已生成图表: %s", f)

    # 报告
    write_markdown_report(stats, figures, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
