#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
unify_data.py
=============

科研场景下复杂学术查询智能检索赛题——数据准备主脚本。

本脚本读取三个核心数据源 (AutoScholarQuery / paper_finder_bench / LitQA2)，
将它们统一格式化后输出到 ``data_prep/outputs/unified_queries/`` 目录。

输出文件
--------
- ``all_queries.jsonl``       全部统一后的查询
- ``train.jsonl``             训练子集 (默认 80%)
- ``test.jsonl``              测试子集 (默认 20%)
- ``by_source/*.jsonl``       按数据源拆分
- ``by_type/*.jsonl``         按查询类型 (survey/specific/metadata/semantic) 拆分
- ``README.md``               数据说明

每行统一格式 (jsonl)
--------------------
.. code-block:: json

    {
      "id":        "query_auto_xxx",            // 全局唯一 ID
      "query":     "自然语言查询",              // 用户的查询文本
      "type":      "survey" | "specific" | "metadata" | "semantic",
      "source":    "autoscholar" | "paper_finder_bench" | "litqa2",
      "gold_papers": [
          {"paper_id": "1909.11740",
           "title":    "...",
           "abstract": "...",
           "year":     2019,
           "venue":    "arXiv",
           "authors":  ["..."]}
      ],
      "distractors":       [...],   // 仅 LitQA2
      "options":           [...],   // 仅 LitQA2
      "correct_answer":    "...",   // 仅 LitQA2
      "scorer_criteria":   {...},   // 仅 paper_finder_bench
      "original_id":       "..."    // 原始 ID，便于回溯
    }

使用示例
--------
::

    python unify_data.py --root /Users/yangyazhou/SakuraPaper
    python unify_data.py --test-ratio 0.2 --seed 13
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from tqdm import tqdm

# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------

logger = logging.getLogger("unify_data")


def setup_logging(level: str = "INFO") -> None:
    """配置日志输出格式。

    Args:
        level: 日志等级 (DEBUG/INFO/WARNING/ERROR)。
    """
    fmt = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ---------------------------------------------------------------------------
# 统一格式定义
# ---------------------------------------------------------------------------


@dataclass
class GoldPaper:
    """统一后的"标准答案论文"数据结构。"""

    paper_id: str
    title: str = ""
    abstract: str = ""
    year: int | None = None
    venue: str = ""
    authors: list[str] = field(default_factory=list)


@dataclass
class UnifiedQuery:
    """统一后的查询结构。"""

    id: str
    query: str
    type: str
    source: str
    gold_papers: list[dict[str, Any]] = field(default_factory=list)
    distractors: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)
    correct_answer: str = ""
    scorer_criteria: dict[str, Any] = field(default_factory=dict)
    original_id: str = ""

    def to_jsonl(self) -> str:
        """序列化为单行 JSON。"""
        return json.dumps(asdict(self), ensure_ascii=False)


# ---------------------------------------------------------------------------
# 数据加载器 (per source)
# ---------------------------------------------------------------------------


def load_autoscholar(root: Path) -> list[UnifiedQuery]:
    """读取 ``data/PaSa/AutoScholarQuery/{train,test,dev}.jsonl``。

    每条记录的字段：
        - question       自然语言查询
        - answer         相关论文标题列表
        - answer_arxiv_id 相关论文 arxiv id 列表
        - qid            原始 ID
        - source_meta    元信息 (published_time)

    Returns:
        统一后的 UnifiedQuery 列表。
    """
    base = root / "data" / "PaSa" / "AutoScholarQuery"
    out: list[UnifiedQuery] = []
    for split in ("train", "test", "dev"):
        fp = base / f"{split}.jsonl"
        if not fp.exists():
            logger.warning("[AutoScholar] 缺失文件: %s，跳过", fp)
            continue
        logger.info("[AutoScholar] 加载 %s", fp)
        with fp.open(encoding="utf-8") as fh:
            lines = fh.readlines()
        for raw in tqdm(lines, desc=f"autoscholar.{split}", dynamic_ncols=True):
            rec = json.loads(raw)
            qid = rec.get("qid") or f"AutoScholarQuery_{split}_?"
            titles: list[str] = rec.get("answer", []) or []
            arxiv_ids: list[str] = rec.get("answer_arxiv_id", []) or []
            gold: list[dict[str, Any]] = []
            # 配对 title / arxiv_id，长度不一致时按索引对齐，多余的留空
            for i, t in enumerate(titles):
                pid = arxiv_ids[i] if i < len(arxiv_ids) else ""
                gp = GoldPaper(
                    paper_id=str(pid or "").strip(),
                    title=t,
                )
                gold.append(asdict(gp))
            uq = UnifiedQuery(
                id=f"query_auto_{qid}",
                query=rec.get("question", "").strip(),
                type="survey",  # 询问"相关工作"是典型的综述类查询
                source="autoscholar",
                gold_papers=gold,
                original_id=qid,
            )
            out.append(uq)
    return out


def _pfb_type(query_id: str) -> str:
    """根据 paper_finder_bench 的前缀推断查询类型。"""
    prefix = query_id.split("_", 1)[0].lower()
    mapping = {
        "semantic": "semantic",
        "specific": "specific",
        "metadata": "metadata",
        "litqa2": "specific",  # 4 选 1 题，归入 specific
    }
    return mapping.get(prefix, "specific")


def load_paper_finder_bench(root: Path) -> list[UnifiedQuery]:
    """读取 ``data/asta-bench/tasks/paper_finder_bench/{test,validation}_2025_05.json``。

    原始记录为 list[dict]，每个 dict 含 ``input`` 和 ``scorer_criteria``。
    ``scorer_criteria`` 可能是 ``known_to_be_good`` + ``known_to_be_bad`` + ``relevance_criteria``
    (semantic) 或 ``corpus_ids`` (specific/metadata) 两种结构。
    """
    base = root / "data" / "asta-bench" / "tasks" / "paper_finder_bench"
    out: list[UnifiedQuery] = []
    for fname in ("test_2025_05.json", "validation_2025_05.json"):
        fp = base / fname
        if not fp.exists():
            logger.warning("[paper_finder_bench] 缺失文件: %s，跳过", fp)
            continue
        logger.info("[paper_finder_bench] 加载 %s", fp)
        with fp.open(encoding="utf-8") as fh:
            data = json.load(fh)
        for rec in tqdm(data, desc=f"pfb.{fname}", dynamic_ncols=True):
            inp = rec.get("input", {})
            qid = inp.get("query_id", "").strip()
            if not qid:
                continue
            sc = rec.get("scorer_criteria", {}) or {}
            # gold_papers 优先取 corpus_ids，其次 known_to_be_good
            gold_ids: list[str] = []
            if "corpus_ids" in sc:
                gold_ids = list(sc["corpus_ids"])
            elif "known_to_be_good" in sc:
                gold_ids = list(sc["known_to_be_good"])
            gold_papers = [
                asdict(GoldPaper(paper_id=str(pid).strip())) for pid in gold_ids
            ]
            # scorer_criteria 只保留原始有效字段 (剔除 corpus_ids/known_to_be_good 以免冗余)
            sc_out: dict[str, Any] = {}
            for k in ("known_to_be_bad", "relevance_criteria"):
                if k in sc:
                    sc_out[k] = sc[k]
            uq = UnifiedQuery(
                id=f"query_pfb_{qid}",
                query=inp.get("query", "").strip(),
                type=_pfb_type(qid),
                source="paper_finder_bench",
                gold_papers=gold_papers,
                scorer_criteria=sc_out,
                original_id=qid,
            )
            out.append(uq)
    return out


def load_litqa2(root: Path) -> list[UnifiedQuery]:
    """读取 ``data/litqa2/LitQA2/*.parquet`` 并关联 ``labbench/litqa2_mapping.json``。

    parquet 字段：id, question, ideal, distractors, sources (DOI list), ...
    mapping 提供 corpus_ids 以关联到 S2 论文。
    """
    pq_fp = root / "data" / "litqa2" / "LitQA2" / "train-00000-of-00001.parquet"
    map_fp = root / "data" / "asta-bench" / "tasks" / "labbench" / "litqa2_mapping.json"

    if not pq_fp.exists():
        logger.error("[LitQA2] 缺失文件: %s", pq_fp)
        return []
    logger.info("[LitQA2] 加载 %s", pq_fp)
    df = pd.read_parquet(pq_fp)
    mapping: dict[str, dict[str, Any]] = {}
    if map_fp.exists():
        with map_fp.open(encoding="utf-8") as fh:
            mlst = json.load(fh)
        mapping = {x["id"]: x for x in mlst}
        logger.info("[LitQA2] 加载 litqa2_mapping (%d 条)", len(mapping))
    else:
        logger.warning("[LitQA2] 未找到 litqa2_mapping.json，gold_papers 将只填 DOI")

    out: list[UnifiedQuery] = []
    for _, row in tqdm(df.iterrows(), total=len(df), desc="litqa2", dynamic_ncols=True):
        qid = str(row["id"])
        question = str(row["question"]).strip()
        ideal = str(row["ideal"]).strip()
        # distractors 在 parquet 中以 numpy array 存储，转换为 list[str]
        try:
            distractors = [str(x) for x in list(row["distractors"])]
        except Exception:  # noqa: BLE001
            distractors = []
        # sources (DOI) 同上
        try:
            sources = [str(x) for x in list(row["sources"]) if x]
        except Exception:  # noqa: BLE001
            sources = []
        # 关联 mapping
        m = mapping.get(qid, {})
        corpus_ids: list[str] = list(m.get("corpus_ids", []) or [])
        s2_dois: list[str] = list(m.get("s2_doi", []) or [])
        gold: list[dict[str, Any]] = []
        # 优先用 corpus_id (Semantic Scholar 论文 ID)
        for pid in corpus_ids:
            gold.append(asdict(GoldPaper(paper_id=str(pid))))
        # 若无 corpus_id 但有 DOI，则用 DOI 兜底
        if not gold and s2_dois:
            for doi in s2_dois:
                gold.append(asdict(GoldPaper(paper_id=doi, venue="doi")))
        elif not gold and sources:
            for doi in sources:
                gold.append(asdict(GoldPaper(paper_id=doi, venue="doi")))

        # 构建 4 选 1 选项：合并 ideal + distractors
        opts = [ideal] + distractors
        # 打乱顺序但记录正确选项的位置——这里我们保留原顺序，正确答案始终在第一个
        # 调用方在使用时可以自行重排
        uq = UnifiedQuery(
            id=f"query_litqa_{qid}",
            query=question,
            type="specific",  # 4 选 1 单选，归入 specific
            source="litqa2",
            gold_papers=gold,
            distractors=distractors,
            options=opts,
            correct_answer=ideal,
            original_id=qid,
        )
        out.append(uq)
    return out


# ---------------------------------------------------------------------------
# 落盘逻辑
# ---------------------------------------------------------------------------


def write_jsonl(path: Path, rows: Iterable[UnifiedQuery]) -> int:
    """将 UnifiedQuery 列表写入 jsonl 文件，返回写入行数。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(r.to_jsonl() + "\n")
            n += 1
    return n


def train_test_split(
    items: list[UnifiedQuery], test_ratio: float, seed: int
) -> tuple[list[UnifiedQuery], list[UnifiedQuery]]:
    """分层 (按 source) 随机划分 train/test。

    Args:
        items:      全部 UnifiedQuery。
        test_ratio: 测试集占比，0~1。
        seed:       随机种子。

    Returns:
        (train, test) 两个列表。
    """
    rng = random.Random(seed)
    by_src: dict[str, list[UnifiedQuery]] = {}
    for x in items:
        by_src.setdefault(x.source, []).append(x)
    train, test = [], []
    for src, lst in by_src.items():
        rng.shuffle(lst)
        k = max(1, int(round(len(lst) * test_ratio))) if len(lst) > 1 else 0
        # 当某 source 只有 1 条时全部进 train
        if len(lst) <= 1:
            train.extend(lst)
            continue
        test.extend(lst[:k])
        train.extend(lst[k:])
        logger.info(
            "  [split] source=%s total=%d train=%d test=%d",
            src, len(lst), len(lst) - k, k,
        )
    return train, test


def write_readme(
    out_dir: Path,
    total: int,
    by_source: dict[str, int],
    by_type: dict[str, int],
    train: int,
    test: int,
) -> None:
    """生成 unified_queries/README.md。"""
    fp = out_dir / "README.md"
    lines: list[str] = []
    lines.append("# 统一查询数据 (unified_queries)\n")
    lines.append("> 由 `unify_data.py` 整合自 3 个核心数据源，用于智能论文搜索与推荐赛题的训练与评测。\n")
    lines.append("## 1. 文件结构\n")
    lines.append("```")
    lines.append("unified_queries/")
    lines.append("├── all_queries.jsonl    # 全部统一记录 (jsonl)")
    lines.append("├── train.jsonl          # 80% 训练子集")
    lines.append("├── test.jsonl           # 20% 测试子集")
    lines.append("├── by_source/           # 按数据源拆分")
    lines.append("│   ├── autoscholar.jsonl")
    lines.append("│   ├── paper_finder_bench.jsonl")
    lines.append("│   └── litqa2.jsonl")
    lines.append("├── by_type/             # 按查询类型拆分")
    lines.append("│   ├── survey.jsonl")
    lines.append("│   ├── specific.jsonl")
    lines.append("│   ├── metadata.jsonl")
    lines.append("│   └── semantic.jsonl")
    lines.append("└── README.md            # 本文件")
    lines.append("```\n")

    lines.append("## 2. 统一字段\n")
    lines.append("| 字段 | 类型 | 说明 |")
    lines.append("| ---- | ---- | ---- |")
    lines.append("| `id` | str | 全局唯一 ID，前缀 `query_auto_` / `query_pfb_` / `query_litqa_` |")
    lines.append("| `query` | str | 自然语言查询 |")
    lines.append("| `type` | str | `survey` / `specific` / `metadata` / `semantic` |")
    lines.append("| `source` | str | `autoscholar` / `paper_finder_bench` / `litqa2` |")
    lines.append("| `gold_papers` | list[dict] | 标准答案论文列表 |")
    lines.append("| `distractors` | list[str] | (仅 LitQA2) 干扰项 |")
    lines.append("| `options` | list[str] | (仅 LitQA2) 4 个选项 |")
    lines.append("| `correct_answer` | str | (仅 LitQA2) 正确答案文本 |")
    lines.append("| `scorer_criteria` | dict | (仅 paper_finder_bench) 评分细则 |")
    lines.append("| `original_id` | str | 数据源内 ID，便于回溯 |")
    lines.append("")

    lines.append("## 3. 统计概览\n")
    lines.append(f"- 总记录数：**{total}**")
    lines.append(f"- 训练集：**{train}** 条")
    lines.append(f"- 测试集：**{test}** 条\n")
    lines.append("### 按数据源\n")
    for k, v in sorted(by_source.items()):
        lines.append(f"- `{k}`: {v} 条")
    lines.append("\n### 按查询类型\n")
    for k, v in sorted(by_type.items()):
        lines.append(f"- `{k}`: {v} 条")
    lines.append("")

    lines.append("## 4. 类型定义\n")
    lines.append("- **survey**    — 综述/主题类查询 (如 '请给我推荐关于 X 的论文')")
    lines.append("- **specific**  — 明确论文标题/作者/DOI 或 4 选 1 知识问答")
    lines.append("- **metadata**  — 元数据/作者年份类 (如 '2012 年 David Harel 的论文')")
    lines.append("- **semantic**  — 主题语义类，需结合多篇论文的相关性进行评估")
    lines.append("")

    lines.append("## 5. 数据样例 (jsonl)\n")
    lines.append("```jsonl")
    lines.append('{"id": "query_auto_AutoScholarQuery_train_0", "query": "What works are related to the field of image retrieval?", "type": "survey", "source": "autoscholar", "gold_papers": [{"paper_id": "1909.11740", "title": "UNITER: UNiversal Image-TExt Representation Learning", "abstract": "", "year": null, "venue": "", "authors": []}], "distractors": [], "options": [], "correct_answer": "", "scorer_criteria": {}, "original_id": "AutoScholarQuery_train_0"}')
    lines.append("```")
    lines.append("")

    lines.append("## 6. 字段取值说明\n")
    lines.append("- `gold_papers[].paper_id`：")
    lines.append("    - AutoScholarQuery → arxiv id (字符串)")
    lines.append("    - paper_finder_bench → Semantic Scholar `corpus_id` (字符串)")
    lines.append("    - LitQA2 → 优先 S2 `corpus_id`；否则用 DOI 兜底")
    lines.append("- `scorer_criteria`：")
    lines.append("    - 包含 `known_to_be_bad` (负例 corpus_id) 和 `relevance_criteria` (加权评分项列表)")
    lines.append("- `options[0]` 固定为正确答案，其余为干扰项 (LitQA2 专用)")
    lines.append("")

    fp.write_text("\n".join(lines), encoding="utf-8")
    logger.info("已写入 README: %s", fp)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="将 3 个核心数据源统一格式化为 jsonl 训练/评测数据集",
    )
    p.add_argument(
        "--root", type=Path, default=Path("/Users/yangyazhou/SakuraPaper"),
        help="仓库根目录 (含 data/ 子目录)",
    )
    p.add_argument(
        "--out", type=Path,
        default=Path("/Users/yangyazhou/SakuraPaper/data_prep/outputs/unified_queries"),
        help="输出目录",
    )
    p.add_argument("--test-ratio", type=float, default=0.2, help="测试集占比 (默认 0.2)")
    p.add_argument("--seed", type=int, default=42, help="随机种子 (默认 42)")
    p.add_argument(
        "--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.log_level)
    root: Path = args.root
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("开始加载 3 个数据源 ...")
    autos = load_autoscholar(root)
    pfb = load_paper_finder_bench(root)
    lit = load_litqa2(root)
    all_items: list[UnifiedQuery] = autos + pfb + lit
    logger.info(
        "加载完成: autoscholar=%d, paper_finder_bench=%d, litqa2=%d, total=%d",
        len(autos), len(pfb), len(lit), len(all_items),
    )
    if not all_items:
        logger.error("未加载到任何记录，请检查数据源路径。")
        return 1

    # 去重：保留首次出现的 id
    seen: set[str] = set()
    dedup: list[UnifiedQuery] = []
    for x in all_items:
        if x.id in seen:
            continue
        seen.add(x.id)
        dedup.append(x)
    if len(dedup) != len(all_items):
        logger.warning("发现重复 id，去重: %d -> %d", len(all_items), len(dedup))
    all_items = dedup

    # 写 all_queries.jsonl
    n_all = write_jsonl(out_dir / "all_queries.jsonl", all_items)
    logger.info("已写入 all_queries.jsonl: %d 条", n_all)

    # 划分 train/test
    train, test = train_test_split(all_items, args.test_ratio, args.seed)
    write_jsonl(out_dir / "train.jsonl", train)
    write_jsonl(out_dir / "test.jsonl", test)
    logger.info("train=%d, test=%d", len(train), len(test))

    # by_source
    by_src_dir = out_dir / "by_source"
    by_src_dir.mkdir(parents=True, exist_ok=True)
    src_counter: dict[str, int] = {}
    for src in sorted({x.source for x in all_items}):
        rows = [x for x in all_items if x.source == src]
        src_counter[src] = write_jsonl(by_src_dir / f"{src}.jsonl", rows)

    # by_type
    by_type_dir = out_dir / "by_type"
    by_type_dir.mkdir(parents=True, exist_ok=True)
    type_counter: dict[str, int] = {}
    for tp in ("survey", "specific", "metadata", "semantic"):
        rows = [x for x in all_items if x.type == tp]
        if rows:
            type_counter[tp] = write_jsonl(by_type_dir / f"{tp}.jsonl", rows)
        else:
            type_counter[tp] = 0

    # 全量统计
    type_counter_full = dict(Counter(x.type for x in all_items))

    write_readme(
        out_dir,
        total=len(all_items),
        by_source=src_counter,
        by_type=type_counter_full,
        train=len(train),
        test=len(test),
    )

    logger.info("全部完成 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
