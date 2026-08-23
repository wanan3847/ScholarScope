"""
快速评测脚本 - 对 PaSa/AstaBench 数据集跑前 N 条，输出真实分数。

用法：
    python run_eval.py [--n 10] [--benchmarks pasa_real sparbench litqa2]

说明：
    - 真实调用 Orchestrator（Mock 检索 + MockLLM），输出真实指标
    - F1 / Recall / Precision 按数据集 gold_ids 计算
    - 效率指标：API 调用数 / Token / 延时
    - 结构化指标：JSON / 关系图 / 表格 三件套共现率
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

# 路径
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 加载 .env 配置
try:
    from dotenv import load_dotenv
    _env_path = ROOT.parent / '.env'
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass

from evaluation.runner import EvaluationRunner, BENCHMARK_REGISTRY


# ------------------------------------------------------------------ #
# S2 corpusId 本地缓存（避免重复 429 失败）
# ------------------------------------------------------------------ #
_S2_CACHE_PATH = ROOT / "data" / "s2_corpus_id_cache.json"


def _load_s2_cache() -> dict:
    try:
        if _S2_CACHE_PATH.exists():
            return json.loads(_S2_CACHE_PATH.read_text())
    except Exception:
        pass
    return {}


def _save_s2_cache(cache: dict) -> None:
    try:
        _S2_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _S2_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
    except Exception:
        pass


def _resolve_s2_corpus_ids(pred_ids: list) -> dict:
    """把预测的 arxiv/doi id 映射到 Semantic Scholar corpusId（paper_finder gold 格式）。

    通过 S2 batch 接口（POST /graph/v1/paper/batch）批量解析；
    解析失败或限流时返回空映射，不影响其他评测。
    本地 JSON 缓存避免重复 429 失败。
    """
    import httpx

    # 先查本地缓存
    cache = _load_s2_cache()
    out = {}
    uncached_ids = []
    uncached_s2_ids = []
    index_by_original = {}
    for pid in pred_ids:
        pid = str(pid).strip()
        # 先查缓存
        cached_cid = cache.get(pid)
        if cached_cid:
            out[pid] = cached_cid
            continue
        # 构造 S2 ID
        if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", pid, re.IGNORECASE):
            s2_id = f"ARXIV:{pid}"
        elif pid.lower().startswith("arxiv:"):
            s2_id = "ARXIV:" + pid.split(":", 1)[1]
        elif pid.startswith("10."):
            s2_id = f"DOI:{pid}"
        else:
            continue
        index_by_original[pid] = len(uncached_s2_ids)
        uncached_ids.append(pid)
        uncached_s2_ids.append(s2_id)
    if not uncached_s2_ids:
        return out
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.post(
                "https://api.semanticscholar.org/graph/v1/paper/batch",
                params={"fields": "corpusId"},
                json={"ids": uncached_s2_ids},
            )
            if resp.status_code != 200:
                return out
            data = resp.json()
    except Exception:
        return out
    new_entries = 0
    for pid, pos in index_by_original.items():
        item = data[pos] if pos < len(data) else None
        if item and item.get("corpusId"):
            cid = str(item["corpusId"])
            out[pid] = cid
            cache[pid] = cid
            new_entries += 1
    # 增量持久化新映射
    if new_entries > 0:
        _save_s2_cache(cache)
    return out


def main():
    parser = argparse.ArgumentParser(description="快速评测")
    parser.add_argument("--n", type=int, default=10, help="每个 benchmark 跑前 N 条")
    parser.add_argument("--benchmarks", nargs="*",
                        default=["real_scholar", "sparbench", "litqa2"],
                        help="要评测的 benchmark key 列表")
    parser.add_argument("--output", type=str, default="eval_results.json",
                        help="输出文件")
    parser.add_argument("--real", action="store_true",
                        help="使用真实检索后端（S2/OpenAlex/arXiv/PubMed），慢但能匹配 gold_ids")
    parser.add_argument("--llm", type=str, default="",
                        help="指定已注册的 LLM 模型名（需先通过 /api/llm/register_preset 注册），空则用 MockLLM")
    parser.add_argument("--engine", type=str, default="orchestrator",
                        choices=["orchestrator", "spar2"],
                        help="评测引擎：orchestrator（旧自研流水线）| spar2（成熟 SPAR 架构改造，推荐）")
    args = parser.parse_args()

    print(f"\n{'='*70}")
    print(f"🌸 SakuraScholar 快速评测 (前 {args.n} 条 / benchmark)")
    print(f"   检索模式: {'真实 API' if args.real else 'Mock（arxiv_id 不会匹配 gold，分数为 0）'}")
    print(f"   LLM 模式: {args.llm or 'MockLLM'}")
    print(f"{'='*70}\n")

    # 初始化 orchestrator：按需启用真实检索 / 真实 LLM
    llm = None
    if args.llm:
        try:
            from llm.router import get_default_router
            router = get_default_router()
            llm = router.get(args.llm)
            print(f"✅ 已加载 LLM: {args.llm}")
        except Exception as e:
            print(f"⚠️  加载 LLM {args.llm} 失败，回退 MockLLM: {e}")
            llm = None

    if args.engine == "spar2":
        from agent.spar2 import SPAR2Engine
        print("🔧 评测引擎: SPAR2（SPAR 成熟架构 + 多通道检索/RefChain）")
        runner = EvaluationRunner(orchestrator=SPAR2Engine(llm_chat=llm))
    else:
        from agent.orchestrator import Orchestrator
        runner = EvaluationRunner(
            orchestrator=Orchestrator(
                llm_chat=llm,
                max_output=20,
                judge_threshold=0.20,
                max_judge=150,
                local_top_k=300,
                deadline_seconds=90.0,
                max_rounds=2
            )
        )
    all_results = {}

    for key in args.benchmarks:
        info = BENCHMARK_REGISTRY.get(key)
        if not info:
            print(f"⚠️  未知 benchmark: {key}")
            continue
        if not Path(info["path"]).exists():
            print(f"⚠️  文件不存在: {info['path']}")
            continue

        print(f"\n▶ 评测 {info['name']} ({key})")
        print(f"  路径: {info['path']}")
        print(f"  参考: {info.get('reference', '无')}")

        # 读取前 N 条
        items = runner._load_json_or_jsonl(info["path"])
        items = items[:args.n]
        # 归一化
        items = [runner._normalize_item(it) for it in items]
        print(f"  样本数: {len(items)}")

        # 跑评测
        t0 = time.time()
        report = _evaluate_subset(runner, items, info["name"], key)
        elapsed = time.time() - t0

        all_results[key] = report
        # 打印结果
        macro = report.get("macro_metrics", {})
        eff = report.get("efficiency", {})
        print(f"\n  📊 指标:")
        print(f"     F1@5        = {macro.get('f1@5', 0):.4f}")
        print(f"     F1@10       = {macro.get('f1@10', 0):.4f}")
        print(f"     Recall@10   = {macro.get('recall@10', 0):.4f}")
        print(f"     Recall@20   = {macro.get('recall@20', 0):.4f}")
        print(f"     Precision@10= {macro.get('precision@10', 0):.4f}")
        print(f"  ⚡ 效率:")
        print(f"     平均 API 调用 = {eff.get('avg_api_calls', 0):.1f}")
        print(f"     平均 Token    = {eff.get('avg_tokens', 0):.0f}")
        print(f"     P50 延时      = {eff.get('p50_latency_seconds', 0):.2f}s")
        print(f"  ⏱  总耗时: {elapsed:.1f}s")

    # 汇总表
    print(f"\n{'='*70}")
    print(f"📋 评测汇总")
    print(f"{'='*70}")
    print(f"{'Benchmark':<25} {'F1@10':<10} {'Recall@20':<12} {'P@10':<10} {'avg_calls':<12} {'P50(s)':<8}")
    print("-" * 70)
    for key, rep in all_results.items():
        macro = rep.get("macro_metrics", {})
        eff = rep.get("efficiency", {})
        name = rep.get("summary", {}).get("benchmark", key)
        print(f"{name:<25} {macro.get('f1@10', 0):<10.4f} {macro.get('recall@20', 0):<12.4f} "
              f"{macro.get('precision@10', 0):<10.4f} {eff.get('avg_api_calls', 0):<12.1f} "
              f"{eff.get('p50_latency_seconds', 0):<8.2f}")

    # 写入文件
    out_path = Path(args.output) if str(args.output).startswith("/") else ROOT / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n📁 详细结果写入: {out_path}")


def _evaluate_subset(runner: EvaluationRunner, items: list,
                     benchmark_name: str, benchmark_key: str) -> dict:
    """对 items 子集跑评测，返回聚合报告。"""
    from evaluation.metrics import compute_all_metrics

    k_values = [5, 10, 20]
    detailed = []
    agg = {
        "benchmark": benchmark_name,
        "total": len(items),
        "succeeded": 0,
        "failed": 0,
        "total_api_calls": 0,
        "total_tokens": 0,
        "total_elapsed": 0.0,
    }
    macro_metrics = {}
    latency_list = []
    token_list = []
    api_call_list = []

    for idx, item in enumerate(items):
        query = item.get("query", "")
        gold = item.get("gold_ids", []) or []
        qid = item.get("qid", "")
        if not query:
            continue
        print(f"  [{idx+1}/{len(items)}] qid={qid} :: {query[:60]}...", flush=True)
        try:
            raw_meta = item.get("raw", {}).get("source_meta", {}) or {}
            before_date = str(raw_meta.get("published_time") or "")
            result = runner.orchestrator.sync_run(query, before_date=before_date)
            pred_ids = []
            pred_variants = []
            for p in result.get("papers", []):
                pid = p.get("arxiv_id", "") or p.get("doi", "") or p.get("title", "")
                pred_ids.append(pid)
                variants = list(p.get("ids") or [])
                if pid and pid not in variants:
                    variants.insert(0, pid)
                pred_variants.append(variants)
            # paper_finder_bench 的 gold 是 S2 corpusId（数字）：
            # 把预测的 arxiv/doi id 原位映射成 corpusId 变体，保证 @5/@10 不丢位置
            if benchmark_key == "paper_finder":
                s2_map = _resolve_s2_corpus_ids(pred_ids)
                for i, pid in enumerate(pred_ids):
                    cid = s2_map.get(pid)
                    if cid and cid not in pred_variants[i]:
                        pred_variants[i].append(cid)
            metrics = compute_all_metrics(pred_ids, gold, k_values, pred_variants)
            for k, v in metrics.items():
                macro_metrics[k] = macro_metrics.get(k, 0.0) + v

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

            detailed.append({
                "qid": qid,
                "query": query,
                "gold_ids": gold,
                "pred_ids": pred_ids[:10],
                "metrics": metrics,
                "stats": stats,
            })
        except Exception as e:
            print(f"     ❌ 失败: {e}")
            agg["failed"] += 1
            detailed.append({"query": query, "error": str(e)})

    n = max(1, agg["succeeded"])
    macro_metrics = {k: round(v / n, 4) for k, v in macro_metrics.items()}

    efficiency = {
        "avg_api_calls": round(agg["total_api_calls"] / n, 2),
        "avg_tokens": round(agg["total_tokens"] / n, 2),
        "avg_latency_seconds": round(agg["total_elapsed"] / n, 4),
        "p50_latency_seconds": runner._percentile(latency_list, 0.5),
        "p99_latency_seconds": runner._percentile(latency_list, 0.99),
    }

    return {
        "summary": agg,
        "macro_metrics": macro_metrics,
        "efficiency": efficiency,
        "detailed": detailed,
        "reference": BENCHMARK_REGISTRY.get(benchmark_key, {}).get("reference", ""),
    }


if __name__ == "__main__":
    main()
