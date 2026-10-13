"""ScholarScope MCP Server — 把检索/收藏/评测能力暴露为标准 MCP 工具。

岗位化改造 P0：对齐 JD 高频关键词「MCP / 工具调用 / 多智能体」，
可在 Claude Code / Cursor / 任意 MCP 客户端中直接调用：

    python mcp_server.py --transport stdio
    python mcp_server.py --transport sse --port 8766

工具清单：
    - search_papers     多通道检索（arXiv/OpenAlex/CrossRef/S2/本地语义 + LLM 判分）
    - get_paper         论文详情
    - get_references    参考文献（RefChain 引用方向）
    - get_citations     引用该文的论文（RefChain 被引方向）
    - save_favorite     收藏论文（按用户隔离）
    - list_favorites    列出收藏
    - run_eval          跑官方 benchmark 评测（F1/Recall）
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

# 让 `python src/mcp_server.py` 与 `python -m mcp.server` 都能 import
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT.parent / ".env")
except Exception:
    pass

from mcp.server.mcpserver import MCPServer

from agent.collections import add_favorite, list_favorites as list_favs
from agent.orchestrator import Orchestrator
from llm.router import get_default_router

mcp = MCPServer("ScholarScope", instructions=(
    "科研场景学术论文检索系统。搜索论文用 search_papers；"
    "查详情/引文用 get_paper/get_references/get_citations；"
    "收藏与个人库用 save_favorite/list_favorites；"
    "跑官方测试集评测用 run_eval。"
))

# 与 Web 搜索一致的引擎配置：Web deadline 70s、首轮检索 + 判分
SEARCH_DEADLINE = 70.0
SEARCH_MAX_ROUNDS = 1
SEARCH_MAX_JUDGE = 40
SEARCH_LOCAL_TOP_K = 200
SEARCH_TIMEOUT = 95


def _get_llm(model: str = ""):
    """获取 LLM 实例；空则走默认路由（无可用端点时自动降级 MockLLM）。"""
    try:
        router = get_default_router()
        return router.get(model or None)
    except Exception:
        return None


def _run_with_timeout(fn, timeout: float) -> Any:
    """线程池 + 超时保护：外部 API 慢时返回友好错误而非挂死。"""
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return executor.submit(fn).result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        raise TimeoutError(f"搜索超时（{timeout:.0f}s），外部 API 响应过慢，请稍后重试")
    finally:
        executor.shutdown(wait=False)


def _paper_to_markdown(p: Dict) -> str:
    title = p.get("title", "").strip() or "(无标题)"
    year = p.get("year") or ""
    venue = p.get("venue") or ""
    score = p.get("final_score", p.get("score", 0.0))
    pid = p.get("arxiv_id") or p.get("doi") or p.get("s2_corpus_id") or p.get("id", "")
    return f"- **{title}**（{year}）| {venue} | score={score:.3f} | id={pid}"


def _papers_summary(result: Dict) -> str:
    papers = result.get("papers", [])[:20]
    if not papers:
        return "未检索到相关论文。"
    lines = [f"返回 {len(papers)} 篇候选论文（按相关性排序）：", ""]
    for i, p in enumerate(papers, 1):
        lines.append(f"{i}. {_paper_to_markdown(p)}")
    lines.append("")
    metrics = result.get("metrics") or result.get("stats") or {}
    lines.append(f"指标：API 调用 {metrics.get('api_calls', 0)} 次 / "
                 f"token {metrics.get('tokens', 0)} / 耗时 {metrics.get('latency') or metrics.get('elapsed_seconds', 0):.1f}s")
    innovations = metrics.get("innovations_used", [])
    if innovations:
        lines.append(f"启用的机制：{', '.join(innovations)}")
    return "\n".join(lines)


# ------------------------------------------------------------------ #
# 工具：检索
# ------------------------------------------------------------------ #

@mcp.tool()
def search_papers(query: str, top_k: int = 10, before_date: str = "",
                  llm_model: str = "") -> str:
    """多通道检索论文：查询理解 → arXiv/OpenAlex/CrossRef/S2/本地语义 5 通道召回
    → BGE 语义预筛 → LLM 批量判分 → 排序输出。

    Args:
        query: 学术查询（可复杂，如 "diffusion models for RL planning"）
        top_k: 返回条数上限
        before_date: 截止日期过滤（YYYY-MM-DD，空则不过滤）
        llm_model: LLM 模型名（空 = 默认路由；deepseek/qwen/glm/ollama 等）
    """
    orch = Orchestrator(
        llm_chat=_get_llm(llm_model),
        deadline_seconds=SEARCH_DEADLINE,
        max_rounds=SEARCH_MAX_ROUNDS,
        max_judge=SEARCH_MAX_JUDGE,
        local_top_k=SEARCH_LOCAL_TOP_K,
    )
    result = _run_with_timeout(
        lambda: orch.sync_run(query, before_date), SEARCH_TIMEOUT
    )
    result["papers"] = result.get("papers", [])[: max(1, top_k)]
    for p in result["papers"]:
        if p.get("final_score") is None:
            p["final_score"] = p.get("score", 0.0)
    summary = _papers_summary(result)
    detail = json.dumps(
        {"query": query, "papers": result["papers"],
         "metrics": result.get("metrics") or result.get("stats") or {}},
        ensure_ascii=False, default=str,
    )
    return f"{summary}\n\n<detail>\n{detail}\n</detail>"


# ------------------------------------------------------------------ #
# 工具：论文详情与引文（RefChain）
# ------------------------------------------------------------------ #

def _fetch_papers(paper_id: str, method: str, use_real_api: bool) -> List[Dict]:
    """通过 Semantic Scholar 后端取详情/引文；离线时回退本地缓存。"""
    from retrieval import get_retrieval_backend
    backend = get_retrieval_backend("semantic_scholar", use_mock=not use_real_api)
    try:
        if method == "get_paper":
            paper = asyncio.run(backend.get_paper(paper_id))
            return [paper.to_dict()] if paper else []
        coro = backend.get_references if method == "get_references" else backend.get_citations
        papers = asyncio.run(coro(paper_id))
        return [p.to_dict() for p in papers]
    except Exception:
        if method == "get_paper":
            from agent.collections import get_cached_paper
            cached = get_cached_paper(paper_id)
            return [cached] if cached else []
        return []


@mcp.tool()
def get_paper(paper_id: str, use_real_api: bool = False) -> str:
    """获取论文详情（标题/摘要/年份/作者/来源）。

    Args:
        paper_id: arXiv ID 或 DOI 或 S2 corpusId
        use_real_api: 是否走真实 Semantic Scholar API（False 时用离线 Mock/缓存）
    """
    papers = _fetch_papers(paper_id, "get_paper", use_real_api)
    if not papers:
        return f"未找到论文：{paper_id}"
    return json.dumps(papers[0], ensure_ascii=False, indent=2, default=str)


@mcp.tool()
def get_references(paper_id: str, use_real_api: bool = False) -> str:
    """获取某篇论文的参考文献（RefChain 引用方向扩展）。

    Args:
        paper_id: arXiv ID 或 DOI 或 S2 corpusId
        use_real_api: 是否走真实 Semantic Scholar API
    """
    papers = _fetch_papers(paper_id, "get_references", use_real_api)
    if not papers:
        return f"未找到参考文献：{paper_id}"
    return json.dumps(papers, ensure_ascii=False, indent=2, default=str)


@mcp.tool()
def get_citations(paper_id: str, use_real_api: bool = False) -> str:
    """获取引用某篇论文的论文（RefChain 被引方向扩展）。

    Args:
        paper_id: arXiv ID 或 DOI 或 S2 corpusId
        use_real_api: 是否走真实 Semantic Scholar API
    """
    papers = _fetch_papers(paper_id, "get_citations", use_real_api)
    if not papers:
        return f"未找到引用该文的论文：{paper_id}"
    return json.dumps(papers, ensure_ascii=False, indent=2, default=str)


# ------------------------------------------------------------------ #
# 工具：收藏 / 个人库
# ------------------------------------------------------------------ #

@mcp.tool()
def save_favorite(paper_id: str, user_id: str = "mcp-user",
                  title: str = "", folder_id: str = "") -> str:
    """收藏一篇论文到个人库（按 user_id 隔离，可在 Web /app 收藏夹看到）。

    Args:
        paper_id: 论文 ID（arXiv/DOI/S2）
        user_id: 用户名（默认 mcp-user）
        title: 论文标题（可选，便于展示）
        folder_id: 目标文件夹 ID（空 = 默认文件夹）
    """
    meta = {"title": title} if title else None
    result = add_favorite(
        user_id, paper_id, paper_meta=meta, folder_id=folder_id or None
    )
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def list_favorites(user_id: str = "mcp-user") -> str:
    """列出某个用户的收藏论文。

    Args:
        user_id: 用户名（默认 mcp-user）
    """
    data = list_favs(user_id)
    items = data.get("favorites", [])
    if not items:
        return "收藏夹为空。"
    lines = [f"共 {data.get('total', 0)} 篇收藏：", ""]
    for it in items:
        lines.append(f"- {it['paper_id']}（添加于 {it.get('added_at', '')}）")
    return "\n".join(lines)


# ------------------------------------------------------------------ #
# 工具：评测
# ------------------------------------------------------------------ #

@mcp.tool()
def run_eval(benchmark: str = "real_scholar", n: int = 3,
             real: bool = False, llm: str = "mock") -> str:
    """跑官方 benchmark 评测，返回 F1/Recall/Precision。

    Args:
        benchmark: 测试集名 real_scholar / auto_scholar / paper_finder / litqa2 / sparbench
        n: 评测条数（默认 3，快速验证）
        real: 是否真实检索（False 用离线语料，快且免费）
        llm: LLM 模型（mock 免费离线；deepseek/qwen/glm 等）
    """
    bench_map = {
        "real_scholar": "real_scholar", "auto_scholar": "auto_scholar",
        "paper_finder": "paper_finder", "litqa2": "litqa2", "sparbench": "sparbench",
    }
    if benchmark not in bench_map:
        return f"未知 benchmark：{benchmark}，可选 {list(bench_map)}"
    out = Path(tempfile.mkstemp(suffix=".json")[1])
    script = ROOT / "run_eval.py"
    args = [sys.executable, str(script), "--n", str(n),
            "--benchmarks", benchmark, "--llm", llm,
            "--output", str(out)]
    if real:
        args.append("--real")
    async def _run_proc():
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        return await proc.communicate()

    stdout, _ = asyncio.run(_run_proc())
    try:
        data = json.loads(out.read_text(encoding="utf-8"))
        report = data.get(benchmark, {}) or {}
        macro = report.get("macro_metrics", {})
        lines = [f"评测完成：{benchmark}（n={n}，llm={llm}）", ""]
        lines.append(f"- F1@10 = {macro.get('f1@10')} / Recall@20 = {macro.get('recall@20')} "
                     f"/ Precision@10 = {macro.get('precision@10')}")
        eff = report.get("efficiency", {})
        if eff:
            lines.append(f"- API 调用 {eff.get('avg_api_calls', 0)} 次 / "
                         f"token {eff.get('avg_tokens', 0)} / P50 {eff.get('p50_latency', 0)}s")
        return "\n".join(lines)
    except Exception as e:
        tail = (stdout or b"").decode("utf-8", "ignore")[-800:]
        return f"评测失败：{e}\n{tail}"


# ------------------------------------------------------------------ #
# CLI 入口
# ------------------------------------------------------------------ #

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="ScholarScope MCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    parser.add_argument("--port", type=int, default=8766, help="SSE 传输端口")
    args = parser.parse_args()
    if args.transport == "sse":
        import asyncio
        asyncio.run(mcp.run_sse_async(host="127.0.0.1", port=args.port))
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
