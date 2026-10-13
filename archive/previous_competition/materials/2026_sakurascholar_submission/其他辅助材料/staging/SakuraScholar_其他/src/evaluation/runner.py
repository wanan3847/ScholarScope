"""
评测 Runner

按 §6 评测方案实现：
    - 支持 4 个真实 benchmark + 自建 SPARBench
    - 输出 P@K / R@K / F1@K（K=5/10/20）
    - 效率指标：API 调用数 / Token / 端到端延时（P50/P99）
    - 结构化指标：JSON / Markdown / HTML 三件套共现率
    - 消融对比支持

支持的数据格式（自动归一化为 {query, gold_ids, qid}）：
    - SakuraScholar 原生: {query, gold_ids: [...], qid?}
    - PaSa AutoScholarQuery / RealScholarQuery:
        {question, answer: [...], answer_arxiv_id: [...], qid}
    - AstaBench paper_finder_bench:
        {input: {query_id, query}, scorer_criteria: {known_to_be_good: [...]}}
    - AstaBench LitQA2:
        {id, question, corpus_ids: [...], s2_doi: [...]}
    - SPARBench: {query, gold_ids, qid, source, difficulty}

调用 Orchestrator 跑出预测，输出聚合指标 + 详细记录。
"""

from __future__ import annotations

import json
import logging
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.orchestrator import Orchestrator
from evaluation.metrics import compute_all_metrics

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Benchmark 注册表（§6.1 测试集）
# ------------------------------------------------------------------ #
# 数据集放在 src/data/benchmarks/ 下，便于统一管理
_BENCHMARK_ROOT = Path(__file__).resolve().parent.parent / "data" / "benchmarks"

BENCHMARK_REGISTRY: Dict[str, Dict[str, str]] = {
    "auto_scholar": {
        "name": "AutoScholarQuery",
        "path": str(_BENCHMARK_ROOT / "AutoScholarQuery" / "test.jsonl"),
        "desc": "PaSa 评测集（~5K 条），验证 BFS 树",
        "reference": "PaSa-7B Recall@20 = 0.708",
    },
    "real_scholar": {
        "name": "RealScholarQuery",
        "path": str(_BENCHMARK_ROOT / "RealScholarQuery" / "test.jsonl"),
        "desc": "PaSa 真实场景指标（50 条）",
        "reference": "PaSa-7B Recall@20 = 0.733",
    },
    "paper_finder": {
        "name": "paper_finder_bench",
        "path": str(_BENCHMARK_ROOT / "paper_finder_bench" / "test_2025_05.json"),
        "desc": "AstaBench 官方 SOTA benchmark（~500 条）",
        "reference": "AstaBench leaderboard",
    },
    "litqa2": {
        "name": "LitQA2",
        "path": str(_BENCHMARK_ROOT / "litqa2" / "test.jsonl"),
        "desc": "评测召回细节（~200 条）",
        "reference": "LabEval",
    },
    "sparbench": {
        "name": "SPARBench",
        "path": str(_BENCHMARK_ROOT / "SPARBench" / "test.jsonl"),
        "desc": "自建：抽样 AutoScholarQuery + RealScholarQuery（100 条）",
        "reference": "SPAR F1 = 0.38",
    },
}


def list_benchmarks() -> List[Dict[str, str]]:
    """列出所有可用 benchmark（带路径是否存在标志）。"""
    out = []
    for key, info in BENCHMARK_REGISTRY.items():
        out.append({
            "key": key,
            "name": info["name"],
            "path": info["path"],
            "desc": info["desc"],
            "reference": info.get("reference", ""),
            "available": Path(info["path"]).exists(),
        })
    return out


# ------------------------------------------------------------------ #
# Runner
# ------------------------------------------------------------------ #

class EvaluationRunner:
    """端到端评测 Runner（含效率与结构化指标）。"""

    def __init__(
        self,
        orchestrator: Orchestrator | None = None,
        use_real_api: bool = False,
        limit: int = 0,
    ):
        """初始化 Runner。

        Args:
            orchestrator: 自定义 Orchestrator；不传则按 use_real_api 自动构造
            use_real_api: 是否启用真实检索后端（CrossRef/S2/arXiv）
            limit: 评测样本数上限；0 表示全量
        """
        if orchestrator is not None:
            self.orchestrator = orchestrator
        else:
            self.orchestrator = Orchestrator(use_mock_retrieval=not use_real_api)
        self.limit = limit

    # ------------------------------------------------------------------ #
    # 数据加载与格式归一化
    # ------------------------------------------------------------------ #
    @staticmethod
    def _load_jsonl(path: str) -> List[Dict]:
        """加载 JSONL（每行一个 JSON 对象）。

        带格式自动探测：如果首行不是合法 JSON（可能整个文件是 JSON 数组），
        回退到整体 JSON 解析。
        """
        items: List[Dict] = []
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        # 尝试按 JSONL 解析
        try:
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
            if items:
                return items
        except json.JSONDecodeError:
            items = []
        # 回退：整体当作 JSON 数组解析
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for key in ("items", "data", "queries", "test"):
                    if key in data and isinstance(data[key], list):
                        return data[key]
        except json.JSONDecodeError:
            pass
        raise ValueError(f"无法解析 {path}：既不是合法 JSONL 也不是 JSON 数组")

    @staticmethod
    def _load_json_or_jsonl(path: str) -> List[Dict]:
        """支持 .jsonl（每行一条）和 .json（数组或 {items:[...]}）。"""
        suffix = Path(path).suffix.lower()
        if suffix == ".jsonl":
            return EvaluationRunner._load_jsonl(path)
        # .json
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("items", "data", "queries", "test"):
                if key in data and isinstance(data[key], list):
                    return data[key]
        raise ValueError(f"无法解析 {path} 的 JSON 结构")

    @staticmethod
    def _normalize_item(raw: Dict) -> Dict:
        """把不同来源的评测项归一化为 {query, gold_ids, qid, source_format}。

        支持的数据格式见模块 docstring。
        """
        # 1) SakuraScholar 原生：{query, gold_ids, qid?}
        if "query" in raw and "gold_ids" in raw:
            return {
                "query": raw["query"],
                "gold_ids": list(raw.get("gold_ids") or []),
                "qid": str(raw.get("qid") or ""),
                "source_format": "sakura",
                "raw": raw,
            }

        # 2) PaSa: {question, answer_arxiv_id, qid}
        if "question" in raw and "answer_arxiv_id" in raw:
            gold = list(raw.get("answer_arxiv_id") or [])
            # 兼容 arxiv_id 缺失时用 answer 标题匹配
            if not gold and raw.get("answer"):
                gold = list(raw["answer"])
            return {
                "query": raw["question"],
                "gold_ids": gold,
                "qid": str(raw.get("qid") or ""),
                "source_format": "pasa",
                "raw": raw,
            }

        # 3) AstaBench paper_finder_bench: {input:{query_id, query}, scorer_criteria:{known_to_be_good}}
        if "input" in raw and isinstance(raw["input"], dict) and "query" in raw["input"]:
            scorer = raw.get("scorer_criteria") or {}
            # semantic 类用 known_to_be_good，specific/metadata 类用 corpus_ids
            gold = list(scorer.get("known_to_be_good") or [])
            gold += [g for g in (scorer.get("corpus_ids") or []) if g not in gold]
            return {
                "query": raw["input"]["query"],
                "gold_ids": gold,
                "qid": str(raw["input"].get("query_id") or ""),
                "source_format": "paper_finder_bench",
                "raw": raw,
            }

        # 4) AstaBench LitQA2: {id, question, corpus_ids, s2_doi}
        if "question" in raw and ("corpus_ids" in raw or "s2_doi" in raw):
            gold = list(raw.get("corpus_ids") or [])
            gold += [g for g in (raw.get("s2_doi") or []) if g not in gold]
            return {
                "query": raw["question"],
                "gold_ids": [str(g) for g in gold],
                "qid": str(raw.get("id") or ""),
                "source_format": "litqa2",
                "raw": raw,
            }

        # 5) 兜底：尝试常见字段
        query = raw.get("query") or raw.get("question") or raw.get("q") or ""
        gold = (raw.get("gold_ids") or raw.get("gold")
                or raw.get("answer_arxiv_id") or raw.get("answer")
                or raw.get("known_to_be_good") or [])
        return {
            "query": query,
            "gold_ids": list(gold),
            "qid": str(raw.get("qid") or raw.get("id") or ""),
            "source_format": "unknown",
            "raw": raw,
        }

    # ------------------------------------------------------------------ #
    # 结构化检测（§6.2 结构化 10%）
    # ------------------------------------------------------------------ #
    @staticmethod
    def _check_structural(result: Dict) -> Dict[str, bool]:
        """检测输出是否含 JSON / Markdown 表格 / HTML 关系图三件套。"""
        has_json = bool(result.get("papers"))
        has_table = result.get("table") is not None
        has_relationships = bool(result.get("relationships"))
        # 进一步：是否有 query_graph（QaG）/ timeline（TET）等扩展结构
        has_extensions = any(
            result.get(k) is not None
            for k in ("query_graph", "timeline", "disagreement", "meta_scores", "qdar")
        )
        return {
            "has_json": has_json,
            "has_table": has_table,
            "has_relationships": has_relationships,
            "has_extensions": has_extensions,
            "three_part": has_json and has_table and has_relationships,
        }

    # ------------------------------------------------------------------ #
    # 效率统计
    # ------------------------------------------------------------------ #
    @staticmethod
    def _percentile(values: List[float], p: float) -> float:
        """简单百分位（p=0.5 即 P50，p=0.99 即 P99）。"""
        if not values:
            return 0.0
        s = sorted(values)
        k = max(0, min(len(s) - 1, int(round(p * (len(s) - 1)))))
        return round(s[k], 4)

    # ------------------------------------------------------------------ #
    # 主入口
    # ------------------------------------------------------------------ #
    def evaluate(
        self,
        test_file: str,
        output_file: str | None = None,
        k_values: List[int] | None = None,
        benchmark_name: str = "",
        include_structural_check: bool = False,
    ) -> Dict:
        """
        跑评测：
            - test_file: jsonl/json，每行 {query, gold_ids}
            - output_file: 详细结果输出
            - benchmark_name: 用于报告归档
            - include_structural_check: 是否检测三件套

        返回：聚合指标 dict（含 macro / efficiency / structural）
        """
        items = self._load_json_or_jsonl(test_file)
        # 归一化所有 item（兼容 PaSa / AstaBench / LitQA2 等异构格式）
        items = [self._normalize_item(it) for it in items]
        # 样本上限（快速评测）
        if self.limit and self.limit > 0:
            items = items[: self.limit]
        k_values = k_values or [5, 10, 20]

        detailed: List[Dict[str, Any]] = []
        agg = {
            "benchmark": benchmark_name or Path(test_file).stem,
            "total": len(items),
            "succeeded": 0,
            "failed": 0,
            "queries_with_hit": 0,
            "total_api_calls": 0,
            "total_tokens": 0,
            "total_elapsed": 0.0,
        }
        macro_metrics: Dict[str, float] = {}
        # 效率统计
        latency_list: List[float] = []
        token_list: List[int] = []
        api_call_list: List[int] = []
        # 结构化统计
        struct_counts = {
            "has_json": 0,
            "has_table": 0,
            "has_relationships": 0,
            "has_extensions": 0,
            "three_part": 0,
        }
        # 来源格式统计（看用了多少种数据源）
        format_counts: Dict[str, int] = {}

        for idx, item in enumerate(items):
            query = item.get("query", "")
            gold = item.get("gold_ids", []) or []
            qid = item.get("qid", "")
            source_format = item.get("source_format", "unknown")
            format_counts[source_format] = format_counts.get(source_format, 0) + 1
            if not query:
                continue
            logger.info("[eval %d/%d] (qid=%s fmt=%s) %s",
                        idx + 1, len(items), qid, source_format, query)
            try:
                # PaSa 公开集提供检索截止日期；参考实现同样将其作为
                # end_date 传给搜索引擎，避免评测发布后的论文污染排序。
                raw_meta = item.get("raw", {}).get("source_meta", {}) or {}
                before_date = str(raw_meta.get("published_time") or "")
                result = self.orchestrator.run(query, before_date=before_date)
                # 预测 ID 归一化：arxiv_id 优先，无则降级到 title
                # 与 PaSa gold（answer_arxiv_id）对齐
                pred_ids = []
                pred_variants: List[List[str]] = []
                for p in result.get("papers", []):
                    pid = p.get("arxiv_id", "") or p.get("doi", "") or p.get("title", "")
                    pred_ids.append(pid)
                    variants = list(p.get("ids") or [])
                    if pid and pid not in variants:
                        variants.insert(0, pid)
                    pred_variants.append(variants)
                metrics = compute_all_metrics(pred_ids, gold, k_values, pred_variants)
                for k, v in metrics.items():
                    macro_metrics[k] = macro_metrics.get(k, 0.0) + v
                if any(metrics.get(f"f1@{kk}", 0.0) > 0.0 for kk in k_values):
                    agg["queries_with_hit"] = agg.get("queries_with_hit", 0) + 1

                stats = result.get("stats", {})
                api_calls = stats.get("api_calls", 0)
                tokens = stats.get("tokens", 0)
                elapsed = stats.get("elapsed_seconds", 0.0)

                agg["succeeded"] += 1
                agg["total_api_calls"] += api_calls
                agg["total_tokens"] += tokens
                agg["total_elapsed"] += elapsed
                latency_list.append(elapsed)
                token_list.append(tokens)
                api_call_list.append(api_calls)

                entry = {
                    "qid": qid,
                    "query": query,
                    "gold_ids": gold,
                    "pred_ids": pred_ids,
                    "source_format": source_format,
                    "metrics": metrics,
                    "stats": stats,
                }

                # 结构化检测
                if include_structural_check:
                    struct = self._check_structural(result)
                    for k, v in struct.items():
                        if v:
                            struct_counts[k] += 1
                    entry["structural"] = struct

                # 扩展字段统计
                extensions = {}
                for key in ("query_graph", "timeline", "disagreement",
                            "meta_scores", "clarifications"):
                    val = result.get(key)
                    if val is not None:
                        extensions[key] = (len(val) if hasattr(val, "__len__")
                                            else 1)
                if extensions:
                    entry["extensions"] = extensions

                detailed.append(entry)

            except Exception as e:  # noqa: BLE001
                logger.exception("eval 失败: %s", query)
                agg["failed"] += 1
                detailed.append({"query": query, "error": str(e)})

        # 取平均
        n = max(1, agg["succeeded"])
        macro_metrics = {k: round(v / n, 4) for k, v in macro_metrics.items()}

        # 效率统计
        efficiency = {
            "avg_api_calls": round(agg["total_api_calls"] / n, 2),
            "avg_tokens": round(agg["total_tokens"] / n, 2),
            "avg_latency_seconds": round(agg["total_elapsed"] / n, 4),
            "p50_latency_seconds": self._percentile(latency_list, 0.5),
            "p99_latency_seconds": self._percentile(latency_list, 0.99),
            "p50_tokens": int(self._percentile(token_list, 0.5)) if token_list else 0,
            "p99_tokens": int(self._percentile(token_list, 0.99)) if token_list else 0,
            "p50_api_calls": int(self._percentile(api_call_list, 0.5)) if api_call_list else 0,
            "p99_api_calls": int(self._percentile(api_call_list, 0.99)) if api_call_list else 0,
        }

        # 结构化统计（百分比）
        structural = {}
        if include_structural_check:
            for k, v in struct_counts.items():
                structural[k] = {
                    "count": v,
                    "ratio": round(v / n, 4),
                }

        report = {
            "summary": agg,
            "macro_metrics": macro_metrics,
            "efficiency": efficiency,
        }
        if structural:
            report["structural"] = structural
        if format_counts:
            report["data_source_breakdown"] = format_counts

        # 参考 baseline（如果 benchmark 命中注册表）
        for key, info in BENCHMARK_REGISTRY.items():
            if info["name"] == report["summary"]["benchmark"] or key == report["summary"]["benchmark"]:
                report["reference"] = {
                    "name": info["name"],
                    "metric": info.get("reference", ""),
                }
                break

        if output_file:
            Path(output_file).write_text(
                json.dumps(
                    {"report": report, "detailed": detailed},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
            logger.info("评测结果写入 %s", output_file)

        return report

    # ------------------------------------------------------------------ #
    # 多 benchmark 联跑
    # ------------------------------------------------------------------ #
    def evaluate_multi(
        self,
        benchmark_keys: List[str],
        output_dir: str = ".",
        k_values: List[int] | None = None,
        include_structural_check: bool = True,
    ) -> Dict[str, Dict]:
        """对多个 benchmark 联跑，每个单独输出报告 + 汇总对比表。"""
        results: Dict[str, Dict] = {}
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        for key in benchmark_keys:
            info = BENCHMARK_REGISTRY.get(key)
            if not info:
                logger.warning("未知 benchmark: %s", key)
                continue
            if not Path(info["path"]).exists():
                logger.warning("benchmark 文件不存在: %s 跳过", info["path"])
                continue
            logger.info("===== 评测 %s =====", info["name"])
            out_file = str(out_dir / f"eval_report_{key}.json")
            report = self.evaluate(
                test_file=info["path"],
                output_file=out_file,
                k_values=k_values,
                benchmark_name=info["name"],
                include_structural_check=include_structural_check,
            )
            results[key] = report

        # 汇总对比表
        if results:
            comparison = []
            for key, rep in results.items():
                macro = rep.get("macro_metrics", {})
                eff = rep.get("efficiency", {})
                comparison.append({
                    "benchmark": rep["summary"]["benchmark"],
                    "total": rep["summary"]["total"],
                    "succeeded": rep["summary"]["succeeded"],
                    "f1@10": macro.get("f1@10", 0.0),
                    "recall@20": macro.get("recall@20", 0.0),
                    "precision@10": macro.get("precision@10", 0.0),
                    "p50_latency": eff.get("p50_latency_seconds", 0.0),
                    "p99_latency": eff.get("p99_latency_seconds", 0.0),
                    "avg_tokens": eff.get("avg_tokens", 0),
                })
            summary_path = out_dir / "eval_summary.json"
            summary_path.write_text(
                json.dumps(comparison, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("多 benchmark 汇总写入 %s", summary_path)

        return results
