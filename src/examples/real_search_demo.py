"""
SakuraScholar 真实搜索 Demo

使用真实 Semantic Scholar + OpenAlex API 跑端到端 pipeline，
无需任何 API key（S2 无 key 限速 3s/次，OpenAlex 无 key 也可用）。

演示内容：
    1. 单条真实查询跑全 pipeline（含 PaSa Crawler 迭代检索）
    2. 输出三件套：JSON + Markdown 表格 + HTML 关系图
    3. 与 MockLLM 对比同一查询的差异
    4. 展示效率统计（API 调用数 / Token / 延时）

运行：
    cd /Users/yangyazhou/SakuraPaper/src
    python examples/real_search_demo.py

    # 指定查询
    python examples/real_search_demo.py --query "retrieval augmented generation survey"

    # 指定 LLM provider（需配置对应 API key）
    SAKURA_LLM_PROVIDER=deepseek python examples/real_search_demo.py

注意：
    - 真实 API 会受网络与速率限制影响，单查询可能耗时 10-60 秒
    - 如需离线快速验证，请用 examples/run_demo.py（全 Mock）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.orchestrator import Orchestrator

OUTPUT_DIR = Path(__file__).resolve().parent / "real_demo_output"


# ------------------------------------------------------------------ #
# 演示查询集
# ------------------------------------------------------------------ #
DEFAULT_QUERIES = [
    {
        "query": "retrieval augmented generation survey",
        "type": "survey",
        "note": "综述类：测试 RefChain 演化 + 多源召回",
    },
    {
        "query": "papers using reinforcement learning for LLM agent training",
        "type": "specific",
        "note": "特定主题：测试 Selector 精确筛选",
    },
    {
        "query": "PaSa An LLM Agent for Comprehensive Academic Paper Search",
        "type": "specific",
        "note": "已知论文：测试引用网络扩展",
    },
]


def run_real_search(query: str, use_mock_llm: bool = True) -> dict:
    """跑真实检索 pipeline。

    Args:
        query: 自然语言查询
        use_mock_llm: True=用 MockLLM（默认），False=用配置的 LLM provider
    """
    print(f"\n>>> 初始化 Orchestrator（real_api=True）")
    orch = Orchestrator(
        backends=["semantic_scholar", "openalex"],
        use_mock_retrieval=False,  # 关键：启用真实 API
        innovation_flags=None,     # 默认全部启用
    )
    # 如果要用真实 LLM，覆盖 orch 内部的 llm
    if not use_mock_llm:
        from config import settings
        from llm import get_llm
        provider = settings.llm_provider or "mock"
        if provider != "mock":
            print(f">>> 使用真实 LLM: {provider}")
            orch.llm = get_llm(provider)
            # 同步替换子模块的 llm（如果它们引用了 orch.llm）
            if hasattr(orch, "crawler") and orch.crawler:
                orch.crawler.llm = orch.llm
            if hasattr(orch, "selector") and orch.selector:
                orch.selector.llm = orch.llm
            if hasattr(orch, "query_understanding") and orch.query_understanding:
                orch.query_understanding.llm = orch.llm

    print(f">>> 开始检索: {query}")
    t0 = time.time()
    result = orch.run(query)
    elapsed = time.time() - t0
    result["stats"]["wall_clock_seconds"] = round(elapsed, 2)
    return result


def render_report(query: str, result: dict, mock_result: dict | None) -> str:
    """生成 Markdown 报告。"""
    lines = []
    lines.append(f"# SakuraScholar 真实搜索报告\n")
    lines.append(f"**Query**: {query}\n")
    lines.append(f"**检索后端**: Semantic Scholar + OpenAlex（真实 API）\n")
    lines.append(f"**时间**: {result['stats'].get('wall_clock_seconds', 0)}s\n")

    lines.append(f"\n## 效率统计\n")
    stats = result["stats"]
    lines.append(f"- API 调用数: {stats.get('api_calls', 0)}")
    lines.append(f"- Token 消耗: {stats.get('tokens', 0)}")
    lines.append(f"- 端到端延时: {stats.get('elapsed_seconds', 0)}s")
    lines.append(f"- 后端使用: {stats.get('backends_used', [])}")
    lines.append(f"- 创新模块启用: {stats.get('innovations_used', [])}")

    lines.append(f"\n## 查询理解\n")
    intent = result.get("intent", {})
    lines.append(f"- Intent: {intent.get('intent', '')}")
    lines.append(f"- Keywords: {intent.get('keywords', [])}")
    if intent.get("sub_queries"):
        lines.append(f"- 子查询:")
        for sq in intent["sub_queries"][:5]:
            lines.append(f"  - [{sq.get('intent', '?')}] {sq.get('text', '')[:80]}")

    lines.append(f"\n## 召回论文（Top 10）\n")
    papers = result.get("papers", [])[:10]
    if not papers:
        lines.append("(无召回)")
    else:
        lines.append("| # | Title | Year | Source | Score |")
        lines.append("| --- | --- | --- | --- | --- |")
        for i, p in enumerate(papers, 1):
            title = (p.get("title") or "")[:60].replace("|", "\\|")
            lines.append(
                f"| {i} | {title} | {p.get('year', '?')} | "
                f"{p.get('source', '?')} | {p.get('final_score', 0):.3f} |"
            )

    # 扩展字段
    if result.get("timeline"):
        lines.append(f"\n## ⑦ TET 时间线\n")
        for tl in result["timeline"][:5]:
            lines.append(f"- **{tl.get('year', '?')}**: {tl.get('theme', '')}")

    if result.get("disagreement"):
        d = result["disagreement"]
        lines.append(f"\n## ⑥ DBE 分歧集成\n")
        lines.append(f"- 共识: {len(d.get('consensus', []))} 篇")
        lines.append(f"- 分歧: {len(d.get('disagreement', []))} 篇")

    if result.get("meta_scores"):
        ms = result["meta_scores"]
        lines.append(f"\n## ⑮ MCS 元认知\n")
        if isinstance(ms, dict):
            for k, v in list(ms.items())[:3]:
                lines.append(f"- {k}: {v}")

    # 与 Mock 对比
    if mock_result:
        lines.append(f"\n## 真实 API vs MockLLM 对比\n")
        lines.append(f"| 指标 | 真实 API | MockLLM |")
        lines.append(f"| --- | --- | --- |")
        lines.append(f"| 召回数 | {len(result.get('papers', []))} | {len(mock_result.get('papers', []))} |")
        lines.append(f"| API 调用 | {result['stats'].get('api_calls', 0)} | {mock_result['stats'].get('api_calls', 0)} |")
        lines.append(f"| Token | {result['stats'].get('tokens', 0)} | {mock_result['stats'].get('tokens', 0)} |")
        lines.append(f"| 延时 | {result['stats'].get('elapsed_seconds', 0)}s | {mock_result['stats'].get('elapsed_seconds', 0)}s |")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="SakuraScholar 真实搜索 Demo")
    parser.add_argument(
        "--query", type=str, default="",
        help="指定查询（默认跑 3 条示例查询）",
    )
    parser.add_argument(
        "--use-real-llm", action="store_true",
        help="使用配置的真实 LLM（需 API key），默认用 MockLLM",
    )
    parser.add_argument(
        "--compare-mock", action="store_true", default=True,
        help="同时跑 MockLLM 版本做对比（默认开启）",
    )
    parser.add_argument(
        "--output-dir", type=str, default=str(OUTPUT_DIR),
        help=f"输出目录（默认 {OUTPUT_DIR}）",
    )
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    queries = [{"query": args.query, "type": "custom", "note": "用户指定"}] if args.query else DEFAULT_QUERIES
    use_mock_llm = not args.use_real_llm

    print(f"\n{'='*60}")
    print(f"SakuraScholar 真实搜索 Demo")
    print(f"={'='*58}")
    print(f"查询数: {len(queries)}")
    print(f"LLM 模式: {'MockLLM' if use_mock_llm else '真实 LLM'}")
    print(f"检索后端: Semantic Scholar + OpenAlex（真实 API）")
    print(f"输出目录: {out_dir.absolute()}")
    print(f"{'='*60}\n")

    all_results = []
    for idx, q in enumerate(queries, 1):
        query_text = q["query"]
        print(f"\n[{idx}/{len(queries)}] type={q.get('type', '?')}")
        print(f"  Q: {query_text}")
        print(f"  Note: {q.get('note', '')}")

        # 真实 API
        try:
            result = run_real_search(query_text, use_mock_llm=use_mock_llm)
            print(f"  -> 真实 API: {len(result['papers'])} papers, "
                  f"api_calls={result['stats']['api_calls']}, "
                  f"tokens={result['stats']['tokens']}, "
                  f"elapsed={result['stats'].get('wall_clock_seconds', 0)}s")
            for p in result["papers"][:3]:
                print(f"     - [{p['source']}] ({p.get('year', '?')}) {p['title'][:70]}")
        except Exception as e:
            print(f"  ✗ 真实 API 失败: {e}")
            result = {"query": query_text, "papers": [], "stats": {},
                      "intent": {}, "error": str(e)}

        # Mock 对比
        mock_result = None
        if args.compare_mock and use_mock_llm:
            try:
                print(f"  >>> 跑 MockLLM 对比...")
                mock_orch = Orchestrator(use_mock_retrieval=True)
                mock_result = mock_orch.run(query_text)
                print(f"  -> Mock: {len(mock_result['papers'])} papers, "
                      f"api_calls={mock_result['stats']['api_calls']}, "
                      f"tokens={mock_result['stats']['tokens']}")
            except Exception as e:
                print(f"  ✗ Mock 失败: {e}")

        # 写入三件套
        safe_name = "".join(c if c.isalnum() else "_" for c in query_text[:40]).strip("_")
        base = out_dir / f"q{idx:02d}_{safe_name}"

        # JSON
        (base.with_suffix(".json")).write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        # Markdown 报告
        report = render_report(query_text, result, mock_result)
        (base.with_suffix(".md")).write_text(report, encoding="utf-8")

        # HTML 关系图
        try:
            from agent.graph_synthesizer import generate_three_part_output, records_to_nodes
            from data.schemas import RelationshipEdge
            nodes = records_to_nodes(result.get("papers", []))
            edges = [RelationshipEdge(**e) for e in result.get("relationships", [])]
            bundle = generate_three_part_output(query_text, nodes, edges)
            (base.with_suffix(".html")).write_text(
                bundle["graph_html"], encoding="utf-8",
            )
            (base.with_suffix(".clusters.json")).write_text(
                json.dumps(bundle["cluster_summary"], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            print(f"  ⚠ 三件套生成失败: {e}")

        all_results.append({
            "query": query_text,
            "real": result,
            "mock": mock_result,
        })

    # 汇总
    summary = {
        "total_queries": len(queries),
        "real_total_api_calls": sum(
            r["real"].get("stats", {}).get("api_calls", 0) for r in all_results
        ),
        "real_total_tokens": sum(
            r["real"].get("stats", {}).get("tokens", 0) for r in all_results
        ),
        "real_total_papers": sum(
            len(r["real"].get("papers", [])) for r in all_results
        ),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\n{'='*60}")
    print(f"Demo 完成")
    print(f"{'='*60}")
    print(f"总查询数: {summary['total_queries']}")
    print(f"真实 API 总调用: {summary['real_total_api_calls']}")
    print(f"真实 API 总 Token: {summary['real_total_tokens']}")
    print(f"真实 API 总召回论文: {summary['real_total_papers']}")
    print(f"输出目录: {out_dir.absolute()}")
    print(f"  - 每条查询: q##_*.json / .md / .html / .clusters.json")
    print(f"  - 汇总: summary.json")


if __name__ == "__main__":
    main()
