"""
研索 ScholarScope Web 服务

基于 FastAPI 提供 REST API，供前端使用界面调用。

端点：
    GET  /                  → 项目展示首页
    GET  /app               → 搜索使用界面
    POST /api/search        → 执行搜索（核心）
    GET  /api/paper/{id}    → 论文详情
    GET  /api/references/{id} → 参考文献
    GET  /api/citations/{id}  → 引用本文的论文
    POST /api/feedback      → 提交反馈事件
    GET  /api/feedback/report → 反馈统计报告
    GET  /api/health        → 健康检查
    GET  /api/benchmarks    → 列出可用 benchmark
    POST /api/eval          → 触发评测（后台）
    GET  /api/stats         → 系统统计

启动：
    uvicorn web.app:app --host 0.0.0.0 --port 8765 --reload
    或 python -m web.app
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# 路径修正
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent.feedback_loop import FeedbackCollector, FeedbackEvent, RewardComputer
from agent.orchestrator import DEFAULT_INNOVATION_FLAGS, Orchestrator
from evaluation.runner import BENCHMARK_REGISTRY, list_benchmarks

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# 静态资源路径
# ------------------------------------------------------------------ #
WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"
TEMPLATES_DIR = WEB_DIR / "templates"


# ------------------------------------------------------------------ #
# 请求/响应模型
# ------------------------------------------------------------------ #

class SearchRequest(BaseModel):
    query: str
    backends: Optional[List[str]] = None
    use_real_api: bool = False
    ablation: Optional[List[str]] = None  # ["qag", "mcs"]
    top_k: int = 0  # 0 = 不截断
    format: str = "json"  # json / three_part
    llm_model: str = ""  # 指定 LLM 模型名（对应 /api/llm/models 中的 name），空则用默认


class FeedbackRequest(BaseModel):
    query: str = ""
    paper_id: str
    event_type: str  # click / copy / cite / skip / hide / star
    star_value: Optional[int] = None
    user_id: str = "web-anonymous"
    session_id: str = "web"


class EvalRequest(BaseModel):
    benchmark: str = "sparbench"
    test_file: Optional[str] = None
    include_structural_check: bool = True
    use_real_api: bool = False  # 真实检索（CrossRef/S2/arXiv），否则 Mock
    limit: int = 0  # 0=全量；>0 只跑前 N 条（快速评测）


# ------------------------------------------------------------------ #
# 全局状态
# ------------------------------------------------------------------ #

_feedback_collector = FeedbackCollector()
_last_search_result: Optional[Dict[str, Any]] = None

# LLM 转发路由器（懒加载）
_llm_router = None
_LLM_CONFIG_FILE = ROOT / "data" / "llm_config.json"


def _load_llm_config() -> list:
    """读取持久化的 LLM 配置（register/register_preset 后重启不丢失）。"""
    try:
        if _LLM_CONFIG_FILE.exists():
            return json.loads(_LLM_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("读取 LLM 配置失败")
    return []


def _save_llm_config() -> None:
    """把当前路由器的模型配置写入磁盘。"""
    router = _get_llm_router()
    cfg = []
    for ep in router._endpoints.values():  # type: ignore[attr-defined]
        if ep.name in ("mock",):
            continue
        cfg.append({
            "name": ep.name,
            "model": ep.model,
            "base_url": ep.base_url,
            "api_key": ep.api_key,
            "priority": ep.priority,
        })
    try:
        _LLM_CONFIG_FILE.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        logger.exception("保存 LLM 配置失败")


def _get_llm_router():
    """获取全局 LLM 路由器（首次调用时自动初始化）。"""
    global _llm_router
    if _llm_router is None:
        from llm.router import get_default_router
        _llm_router = get_default_router()
        # 恢复持久化的模型配置（env 启动的默认端点已存在则跳过）
        for item in _load_llm_config():
            try:
                if item.get("name") not in _llm_router._endpoints:  # type: ignore[attr-defined]
                    _llm_router.register(
                        name=item["name"],
                        model=item.get("model", ""),
                        base_url=item.get("base_url", ""),
                        api_key=item.get("api_key", ""),
                        enabled=bool(item.get("base_url")),
                        priority=item.get("priority", 0),
                    )
            except Exception:
                logger.exception("恢复 LLM 配置失败: %s", item.get("name"))
    return _llm_router


# ------------------------------------------------------------------ #
# FastAPI 应用
# ------------------------------------------------------------------ #

app = FastAPI(
    title="研索 ScholarScope",
    description="科研场景下复杂学术查询的智能论文搜索与推荐系统",
    version="1.0.0",
)

# 静态文件
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ------------------------------------------------------------------ #
# 页面路由
# ------------------------------------------------------------------ #

@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """项目介绍首页。"""
    html_path = TEMPLATES_DIR / "index.html"
    if not html_path.exists():
        return HTMLResponse("<h1>templates/index.html not found</h1>", status_code=404)
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/app", response_class=HTMLResponse)
async def app_page() -> HTMLResponse:
    """搜索使用界面。"""
    html_path = TEMPLATES_DIR / "app.html"
    if not html_path.exists():
        return HTMLResponse("<h1>templates/app.html not found</h1>", status_code=404)
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ #
# API 端点
# ------------------------------------------------------------------ #

@app.get("/api/health")
async def health() -> Dict:
    return {"status": "ok", "service": "ScholarScope", "version": "1.0.0"}


@app.get("/api/innovations")
async def get_innovations() -> Dict:
    """返回 15 个创新模块及其开关状态。"""
    return {
        "innovations": [
            {"key": k, "enabled": v, "name": _INNOVATION_NAMES.get(k, k)}
            for k, v in DEFAULT_INNOVATION_FLAGS.items()
        ]
    }


@app.post("/api/search")
def search(req: SearchRequest) -> Dict[str, Any]:
    """执行搜索（核心端点，同步以兼容 orchestrator 内部的 asyncio.run）。"""
    global _last_search_result
    import concurrent.futures

    # 获取 LLM 实例：优先用请求指定的模型，否则用默认路由器
    llm = None
    if req.llm_model:
        router = _get_llm_router()
        llm = router.get(req.llm_model)

    # SPAR2 引擎：始终走真实多通道检索（arXiv/OpenAlex/CrossRef/本地语义），
    # req.backends / req.use_real_api / req.ablation 为兼容旧接口保留（不生效）。
    # Web 模式 deadline 60s（评测模式用 170s），保证用户不会等太久
    # Web 模式：保留原 SPAR2 体系，但小服务器上只跑第一轮（含五通道 + 判分），
    # 第二轮/RefChain 留给评测模式；deadline 70s + 单次 LLM 30s 硬超时，
    # 保证在 Cloudflare 100s 内稳定返回
    orch = Orchestrator(llm_chat=llm, deadline_seconds=70.0, max_rounds=1,
                         max_judge=40, local_top_k=200)

    # 超时保护：外部 API 可能很慢，最多等 75 秒
    SEARCH_TIMEOUT = 95
    # 不用 with 语句，避免超时后等待后台线程结束才返回响应
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(orch.sync_run, req.query)
        result = future.result(timeout=SEARCH_TIMEOUT)
    except concurrent.futures.TimeoutError:
        logger.warning("Search timed out after %ds for query: %s", SEARCH_TIMEOUT, req.query)
        executor.shutdown(wait=False)  # 不等待，立即返回 504
        raise HTTPException(
            status_code=504,
            detail=f"搜索超时（{SEARCH_TIMEOUT}s），外部 API 响应过慢。请稍后重试或缩小查询范围。"
        )
    except Exception as e:
        logger.exception("search failed")
        executor.shutdown(wait=False)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # 正常情况下等 future 完成（已经完成所以不阻塞）
        try:
            executor.shutdown(wait=False)
        except Exception:
            pass

    try:
        # top_k 截断
        if req.top_k and req.top_k > 0:
            result["papers"] = result["papers"][: req.top_k]

        # SPAR2 引擎只输出 score，前端统一读 final_score（展示/星图用）
        for p in result.get("papers", []):
            if p.get("final_score") is None:
                p["final_score"] = p.get("score", 0.0)
            p["select_score"] = None
            p["rerank_score"] = None

        # 三件套
        if req.format == "three_part":
            from agent.graph_synthesizer import generate_three_part_output, records_to_nodes
            from data.schemas import RelationshipEdge
            nodes = records_to_nodes(result["papers"])
            edges = [RelationshipEdge(**e) for e in result.get("relationships", [])]
            bundle = generate_three_part_output(req.query, nodes, edges)
            result["three_part"] = bundle

        _last_search_result = result
        return result
    except Exception as e:
        logger.exception("search post-processing failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/paper/{paper_id:path}")
def get_paper(paper_id: str, use_real_api: bool = Query(False)) -> Dict:
    """获取论文详情。"""
    from retrieval import get_retrieval_backend
    backend = get_retrieval_backend("semantic_scholar", use_mock=not use_real_api)
    import asyncio
    paper = asyncio.run(backend.get_paper(paper_id))
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper.to_dict()


@app.get("/api/references/{paper_id:path}")
def get_references(paper_id: str, use_real_api: bool = Query(False)) -> List[Dict]:
    """获取参考文献。"""
    from retrieval import get_retrieval_backend
    backend = get_retrieval_backend("semantic_scholar", use_mock=not use_real_api)
    import asyncio
    papers = asyncio.run(backend.get_references(paper_id))
    return [p.to_dict() for p in papers]


@app.get("/api/citations/{paper_id:path}")
def get_citations(paper_id: str, use_real_api: bool = Query(False)) -> List[Dict]:
    """获取引用本文的论文。"""
    from retrieval import get_retrieval_backend
    backend = get_retrieval_backend("semantic_scholar", use_mock=not use_real_api)
    import asyncio
    papers = asyncio.run(backend.get_citations(paper_id))
    return [p.to_dict() for p in papers]


@app.post("/api/feedback")
async def submit_feedback(req: FeedbackRequest) -> Dict:
    """提交反馈事件。"""
    etype = req.event_type.lower()
    if etype == "click":
        _feedback_collector.record_click(req.query, req.paper_id, user_id=req.user_id, session_id=req.session_id)
    elif etype == "copy":
        _feedback_collector.record_copy(req.query, req.paper_id, user_id=req.user_id, session_id=req.session_id)
    elif etype == "cite":
        _feedback_collector.record_cite(req.query, req.paper_id, user_id=req.user_id, session_id=req.session_id)
    elif etype == "skip":
        _feedback_collector.record_skip(req.query, req.paper_id, user_id=req.user_id, session_id=req.session_id)
    elif etype == "hide":
        _feedback_collector.record_hide(req.query, req.paper_id, user_id=req.user_id, session_id=req.session_id)
    elif etype == "star":
        _feedback_collector.record_star(req.query, req.paper_id, star=req.star_value or 5, user_id=req.user_id, session_id=req.session_id)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown event_type: {etype}")
    # 自动落盘
    _feedback_collector.flush_to_file(str(ROOT / "data" / "feedback.jsonl"))
    return {"status": "ok", "total_events": len(_feedback_collector.events) + _count_feedback_file()}


@app.get("/api/feedback/report")
async def feedback_report() -> Dict:
    """反馈统计报告。"""
    fb_path = ROOT / "data" / "feedback.jsonl"
    if not fb_path.exists():
        return {"total_events": 0, "message": "No feedback yet"}
    events = FeedbackCollector.load_from_file(str(fb_path))
    computer = RewardComputer()
    per_paper = computer.compute_per_paper(events)
    per_query = computer.compute_per_query(events)
    car = computer.citation_adoption_rate(events)
    return {
        "total_events": len(events),
        "unique_papers": len(per_paper),
        "unique_queries": len(per_query),
        "citation_adoption_rate": round(car, 4),
        "per_paper_reward": per_paper,
        "per_query_reward": per_query,
    }


@app.get("/api/benchmarks")
async def benchmarks() -> List[Dict]:
    """列出可用 benchmark。"""
    return list_benchmarks()


@app.post("/api/eval")
def run_eval(req: EvalRequest) -> Dict:
    """触发评测。

    同步端点：FastAPI 自动放到线程池跑，避免 async 端点里调
    orchestrator.run() 内部的 asyncio.run() 报 "cannot be called
    from a running event loop"。
    """
    from evaluation.runner import EvaluationRunner
    test_file = req.test_file
    if not test_file and req.benchmark:
        info = BENCHMARK_REGISTRY.get(req.benchmark)
        if not info:
            raise HTTPException(status_code=400, detail=f"Unknown benchmark: {req.benchmark}")
        test_file = info["path"]
        if not Path(test_file).exists():
            raise HTTPException(status_code=404, detail=f"Benchmark file not found: {test_file}")
    if not test_file or not Path(test_file).exists():
        raise HTTPException(status_code=400, detail="test_file not found")

    runner = EvaluationRunner(use_real_api=req.use_real_api, limit=req.limit)
    report = runner.evaluate(
        test_file=test_file,
        benchmark_name=req.benchmark or Path(test_file).stem,
        include_structural_check=req.include_structural_check,
    )
    return report


# ------------------------------------------------------------------ #
# LLM 模型路由管理 API
# ------------------------------------------------------------------ #

class LLMRegisterRequest(BaseModel):
    name: str
    model: str = "qwen3:8b"
    base_url: str = "http://localhost:11434/v1"
    api_key: str = ""
    enabled: bool = True
    priority: int = 0


class LLMTestRequest(BaseModel):
    name: str
    prompt: str = "你好，用一句话介绍你自己"


@app.get("/api/llm/models")
async def list_llm_models() -> Dict:
    """列出所有已注册的 LLM 模型端点。"""
    router = _get_llm_router()
    return {"models": router.list_endpoints()}


@app.post("/api/llm/register")
async def register_llm_model(req: LLMRegisterRequest, token: str = "") -> Dict:
    """注册一个新的 LLM 模型端点（仅管理员可操作，保护已有 key 配置）。"""
    if not _is_admin(token):
        raise HTTPException(status_code=403, detail="仅管理员可配置大模型")
    router = _get_llm_router()
    router.register(
        name=req.name,
        model=req.model,
        base_url=req.base_url,
        api_key=req.api_key or os.getenv("OPENAI_API_KEY", ""),
        enabled=req.enabled,
        priority=req.priority,
    )
    _save_llm_config()
    return {"status": "ok", "models": router.list_endpoints()}


@app.post("/api/llm/unregister/{name}")
async def unregister_llm_model(name: str, token: str = "") -> Dict:
    """移除一个 LLM 模型端点（仅管理员）。"""
    if not _is_admin(token):
        raise HTTPException(status_code=403, detail="仅管理员可删除模型")
    router = _get_llm_router()
    router.unregister(name)
    _save_llm_config()
    return {"status": "ok", "models": router.list_endpoints()}


@app.post("/api/llm/test")
async def test_llm_model(req: LLMTestRequest) -> Dict:
    """测试指定 LLM 模型端点是否可用。"""
    import time
    router = _get_llm_router()
    try:
        llm = router.get(req.name)
        t0 = time.time()
        result = llm.complete(req.prompt)
        elapsed = round(time.time() - t0, 3)
        return {
            "status": "ok",
            "name": req.name,
            "response": result[:300],
            "elapsed_seconds": elapsed,
        }
    except Exception as e:
        logger.exception("LLM 测试失败: %s", e)
        return {"status": "error", "name": req.name, "error": str(e)}


@app.get("/api/stats")
async def stats() -> Dict:
    """系统统计。"""
    return {
        "feedback_events": _count_feedback_file(),
        "innovations": {k: v for k, v in DEFAULT_INNOVATION_FLAGS.items()},
        "benchmarks": list_benchmarks(),
        "last_search_papers": len(_last_search_result["papers"]) if _last_search_result else 0,
    }


# ------------------------------------------------------------------ #
# LLM 预设模型（多模型一键接入）
# ------------------------------------------------------------------ #

@app.get("/api/llm/presets")
async def list_llm_presets() -> Dict:
    """列出所有预设 LLM 提供商（含聚合路由 OpenRouter/SiliconFlow）。"""
    from llm.openai_compat import list_presets, AGGREGATOR_MODELS
    presets = list_presets()
    # 标记是否为聚合路由
    for p in presets:
        p["is_aggregator"] = p["key"] in ("openrouter", "siliconflow")
        if p["is_aggregator"]:
            p["models"] = AGGREGATOR_MODELS.get(p["key"], [])
    return {"presets": presets}


@app.get("/api/llm/aggregator_models/{provider}")
async def list_aggregator_models(provider: str) -> Dict:
    """获取聚合路由（OpenRouter/SiliconFlow）的可用模型列表。"""
    from llm.openai_compat import AGGREGATOR_MODELS
    if provider not in AGGREGATOR_MODELS:
        raise HTTPException(status_code=400, detail=f"未知聚合路由: {provider}")
    return {"provider": provider, "models": AGGREGATOR_MODELS[provider]}


class LLMPresetRegisterRequest(BaseModel):
    provider: str       # openai/deepseek/qwen_api/glm/moonshot/ollama
    api_key: str = ""   # 云端 API 必填，Ollama 留空
    model: str = ""     # 可覆盖预设默认模型
    priority: int = 10


@app.post("/api/llm/register_preset")
async def register_preset(req: LLMPresetRegisterRequest, token: str = "") -> Dict:
    """一键注册预设模型（自动填 base_url + 默认 model；仅管理员）。"""
    if not _is_admin(token):
        raise HTTPException(status_code=403, detail="仅管理员可配置大模型")
    from llm.openai_compat import PRESETS
    preset = PRESETS.get(req.provider)
    if not preset:
        raise HTTPException(status_code=400, detail=f"未知 provider: {req.provider}")
    router = _get_llm_router()
    model = req.model or preset["model"]
    # ★ 前端不传 key 时自动读取后端 .env 的 key（避免"配好了却 401/离线"）
    api_key = req.api_key or os.getenv(preset.get("env_key", ""), "")
    router.register(
        name=req.provider,
        model=model,
        base_url=preset["base_url"],
        api_key=api_key,
        enabled=True,
        priority=req.priority,
    )
    _save_llm_config()
    return {
        "status": "ok",
        "registered": {
            "name": req.provider,
            "model": model,
            "base_url": preset["base_url"],
            "api_key_loaded": bool(api_key),
        },
        "models": router.list_endpoints(),
    }


# ------------------------------------------------------------------ #
# 收藏夹 / 已阅 / BibTeX 导出（让反馈真正有用）
# ------------------------------------------------------------------ #

def _load_feedback_events() -> list:
    """加载所有反馈事件。"""
    fb_path = ROOT / "data" / "feedback.jsonl"
    if not fb_path.exists():
        return []
    out = []
    for line in fb_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _user_papers_by_event(event_type: str, user_id: str = "web-anonymous") -> list:
    """按事件类型聚合用户的论文 id 列表（去重，按时间倒序）。"""
    events = _load_feedback_events()
    seen = {}
    for e in events:
        if e.get("event_type") == event_type and e.get("user_id", "web-anonymous") == user_id:
            pid = e.get("paper_id", "")
            if pid and pid not in seen:
                seen[pid] = e.get("timestamp", 0)
    return sorted(seen.keys(), key=lambda p: seen[p], reverse=True)


@app.get("/api/favorites")
async def get_favorites(user_id: str = "web-anonymous", folder_id: str = "") -> Dict:
    """获取用户的收藏夹（带论文详情，支持按文件夹过滤）。

    folder_id 参数语义：
      - 空/不传  → 不过滤，返回全部
      - "unfiled" → 仅返回未分类
      - "fXXX"   → 仅返回该文件夹下的
    """
    from agent.collections import list_favorites, get_cached_paper
    from retrieval import get_retrieval_backend
    # 归一化："unfiled" → ""（未分类）；空字符串且未显式传参 → None（不过滤）
    if folder_id == "unfiled":
        filter_fid = ""  # 未分类
    elif folder_id:
        filter_fid = folder_id
    else:
        filter_fid = None  # 不过滤
    result = list_favorites(user_id if user_id != "web-anonymous" else None,
                            folder_id=filter_fid)
    papers = []
    backend = get_retrieval_backend("semantic_scholar", use_mock=True)
    for item in result["favorites"]:
        pid = item["paper_id"]
        # 优先用缓存元数据
        cached = get_cached_paper(pid)
        if cached and cached.get("title"):
            # 补全缺失字段（旧缓存可能没有 url/authors/venue）
            if not cached.get("url"):
                if cached.get("arxiv_id"):
                    cached["url"] = f"https://arxiv.org/abs/{cached['arxiv_id']}"
                elif cached.get("doi"):
                    cached["url"] = f"https://doi.org/{cached['doi']}"
            cached.setdefault("authors", [])
            cached.setdefault("venue", "")
            papers.append({
                **cached,
                "paper_id": pid,
                "added_at": item.get("added_at"),
                "folder_id": item.get("folder_id"),
                "note": item.get("note", ""),
            })
            continue
        # 兜底：从 retrieval backend 获取
        try:
            p = await backend.get_paper(pid)
            if p:
                papers.append({**p.to_dict(),
                               "paper_id": pid,
                               "added_at": item.get("added_at"),
                               "folder_id": item.get("folder_id"),
                               "note": item.get("note", "")})
            else:
                papers.append({"arxiv_id": pid, "title": pid,
                               "paper_id": pid,
                               "added_at": item.get("added_at"),
                               "note": "详情不可用"})
        except Exception as e:
            logger.warning("get_paper(%s) 失败: %s", pid, e)
            papers.append({"arxiv_id": pid, "title": pid,
                           "paper_id": pid,
                           "added_at": item.get("added_at"),
                           "note": "详情不可用"})
    return {"favorites": papers, "total": result["total"]}


# ------------------------------------------------------------------ #
# 收藏夹批量导入（Zotero / BibTeX / RIS / CSV / EndNote JSON）
# 注意：必须注册在 /api/favorites/{paper_id:path} 通配路由之前，
# 否则 POST /api/favorites/import 会被当成收藏一篇 id=import 的论文。
# ------------------------------------------------------------------ #

class FavoriteImportItem(BaseModel):
    """单条导入项。前端解析后逐条传入。"""
    id: str = ""              # arxiv_id / doi / 自定义 id
    title: str = ""
    authors: List[str] = []
    year: Optional[int] = None
    venue: str = ""
    doi: str = ""
    url: str = ""
    abstract: str = ""
    note: str = ""


class FavoriteImportRequest(BaseModel):
    """批量导入请求。"""
    items: List[FavoriteImportItem]
    source: str = "zotero"   # zotero / bibtex / ris / csv / json
    user_id: str = "web-anonymous"
    session_id: str = "web-import"


@app.post("/api/favorites/import")
async def import_favorites(req: FavoriteImportRequest) -> Dict:
    """批量导入论文到收藏夹。

    前端把 BibTeX / RIS / CSV / Zotero JSON 解析成统一的 items 列表后调用本接口。
    每条 item 会：
        1. 写入 collections 存储（按 user_id 隔离）
        2. 缓存论文详情到 paper_cache.json + retrieval backend mock_corpus
    """
    from agent.collections import add_favorite as _add, _cache_paper_meta
    from retrieval import get_retrieval_backend
    from retrieval.base import RawPaper

    backend = get_retrieval_backend("semantic_scholar", use_mock=True)
    ok_count = 0
    skipped = 0
    username = req.user_id if req.user_id != "web-anonymous" else None
    for item in req.items:
        pid = item.id or item.doi or item.title
        if not pid:
            skipped += 1
            continue
        # 1) 写入 collections 存储
        paper_meta = {
            "title": item.title or pid,
            "authors": item.authors or [],
            "year": item.year,
            "venue": item.venue or "",
            "doi": item.doi or "",
            "url": item.url or "",
            "abstract": item.abstract or "",
            "arxiv_id": pid if "arxiv" in (item.url or "").lower() else "",
            "id": pid,
        }
        _add(username, pid, paper_meta=paper_meta)
        # 2) 缓存到 retrieval backend mock_corpus（供 BibTeX 导出、关系图查询使用）
        if item.title or item.authors:
            try:
                paper = RawPaper(
                    title=item.title or pid,
                    abstract=item.abstract or "",
                    paper_id=pid,
                    doi=item.doi or "",
                    year=item.year or 0,
                    authors=item.authors or [],
                    venue=item.venue or "",
                    url=item.url or "",
                    source="import",
                )
                backend._mock_corpus[pid] = paper
                try:
                    from retrieval.base import _GLOBAL_PAPER_CORPUS
                    _GLOBAL_PAPER_CORPUS[pid] = paper
                except Exception:
                    pass
            except Exception as e:
                logger.warning("缓存导入论文失败: %s", e)
        ok_count += 1
    return {
        "status": "ok",
        "imported": ok_count,
        "skipped": skipped,
        "total": len(req.items),
    }


@app.post("/api/favorites/{paper_id:path}")
async def add_favorite(paper_id: str, body: Dict = None, user_id: str = "web-anonymous") -> Dict:
    """添加收藏。body: {paper_meta?: {...}, folder_id?: "f1"}"""
    from agent.collections import add_favorite as _add
    body = body or {}
    paper_meta = body.get("paper_meta") if isinstance(body, dict) else None
    folder_id = body.get("folder_id") if isinstance(body, dict) else None
    return _add(user_id if user_id != "web-anonymous" else None,
                paper_id, paper_meta=paper_meta, folder_id=folder_id)


@app.delete("/api/favorites/{paper_id:path}")
async def remove_favorite(paper_id: str, user_id: str = "web-anonymous") -> Dict:
    """从收藏夹移除（真正从存储中删除）。"""
    from agent.collections import remove_favorite as _remove
    return _remove(user_id if user_id != "web-anonymous" else None, paper_id)


@app.get("/api/favorites/check/{paper_id:path}")
async def check_favorited(paper_id: str, user_id: str = "web-anonymous") -> Dict:
    """检查某篇论文是否已收藏。"""
    from agent.collections import is_favorited
    return {"favorited": is_favorited(user_id if user_id != "web-anonymous" else None, paper_id)}


@app.get("/api/read_papers")
async def get_read_papers(user_id: str = "web-anonymous") -> Dict:
    """获取已阅论文 id 列表。"""
    from agent.collections import list_read_papers
    return list_read_papers(user_id if user_id != "web-anonymous" else None)


@app.post("/api/read_papers/{paper_id:path}")
async def add_read_paper(paper_id: str, user_id: str = "web-anonymous") -> Dict:
    """标记为已阅。"""
    from agent.collections import add_read_paper as _add
    return _add(user_id if user_id != "web-anonymous" else None, paper_id)


@app.delete("/api/read_papers/{paper_id:path}")
async def remove_read_paper(paper_id: str, user_id: str = "web-anonymous") -> Dict:
    """取消已阅。"""
    from agent.collections import remove_read_paper as _remove
    return _remove(user_id if user_id != "web-anonymous" else None, paper_id)


@app.get("/api/read_papers/check/{paper_id:path}")
async def check_read(paper_id: str, user_id: str = "web-anonymous") -> Dict:
    """检查某篇论文是否已阅。"""
    from agent.collections import is_read
    return {"read": is_read(user_id if user_id != "web-anonymous" else None, paper_id)}


# ------------------------------------------------------------------ #
# 收藏夹文件夹管理
# ------------------------------------------------------------------ #

@app.get("/api/folders")
async def list_folders(user_id: str = "web-anonymous") -> Dict:
    """列出所有文件夹。"""
    from agent.collections import list_folders as _list
    return _list(user_id if user_id != "web-anonymous" else None)


@app.get("/api/folders/default")
async def get_default_folder(user_id: str = "web-anonymous") -> Dict:
    """获取默认收藏文件夹。"""
    from agent.collections import get_default_folder as _get
    return _get(user_id if user_id != "web-anonymous" else None)


@app.post("/api/folders")
async def create_folder(body: Dict, user_id: str = "web-anonymous") -> Dict:
    """创建文件夹。body: {name: str, description?: str}"""
    from agent.collections import create_folder as _create
    name = body.get("name", "") if isinstance(body, dict) else ""
    desc = body.get("description", "") if isinstance(body, dict) else ""
    return _create(user_id if user_id != "web-anonymous" else None, name, desc)


@app.put("/api/folders/default")
async def set_default_folder(body: Dict, user_id: str = "web-anonymous") -> Dict:
    """设置默认收藏文件夹。body: {folder_id: str}（"" 表示未分类）。"""
    from agent.collections import set_default_folder as _set
    folder_id = body.get("folder_id", "") if isinstance(body, dict) else ""
    return _set(user_id if user_id != "web-anonymous" else None, folder_id)


@app.delete("/api/folders/{folder_id}")
async def delete_folder(folder_id: str, user_id: str = "web-anonymous") -> Dict:
    """删除文件夹。"""
    from agent.collections import delete_folder as _delete
    return _delete(user_id if user_id != "web-anonymous" else None, folder_id)


@app.put("/api/folders/{folder_id}")
async def rename_folder(folder_id: str, body: Dict, user_id: str = "web-anonymous") -> Dict:
    """重命名文件夹。body: {name: str}"""
    from agent.collections import rename_folder as _rename
    name = body.get("name", "") if isinstance(body, dict) else ""
    return _rename(user_id if user_id != "web-anonymous" else None, folder_id, name)


@app.post("/api/folders/{folder_id}/papers/{paper_id:path}")
async def move_paper_to_folder(folder_id: str, paper_id: str,
                                user_id: str = "web-anonymous") -> Dict:
    """把论文移到指定文件夹。"""
    from agent.collections import move_paper_to_folder as _move
    # folder_id 为 "unfiled" 时表示移到未分类
    fid = None if folder_id == "unfiled" else folder_id
    return _move(user_id if user_id != "web-anonymous" else None, paper_id, fid)


# ------------------------------------------------------------------ #
# 使用文档（管理员可编辑）
# ------------------------------------------------------------------ #

_DOCS_FILE = ROOT / "data" / "docs_content.json"

_DEFAULT_DOCS = [
    {
        "title": "快速上手",
        "body": "在搜索框输入你想查的问题（可以带限定，如「RAG 2023 年之后的综述」），点搜索。\n"
                "系统会同时从 arXiv、OpenAlex、CrossRef、Semantic Scholar 和本地语义库检索，"
                "再用大模型逐篇判断相关性，通常 1-2 分钟出结果。\n"
                "如果提示超时，多半是外部接口慢，稍后重试或把问题说简单一点。",
    },
    {
        "title": "收藏夹",
        "body": "点卡片上的「收藏」把论文存起来。\n"
                "在「管理文件夹」里可以新建文件夹，并选一个「默认收藏文件夹」——"
                "之后新收藏的论文会自动进这个文件夹，不用每次手动移动。\n"
                "收藏列表里每篇论文都有下拉菜单，可以随时移到别的文件夹或移回未分类。",
    },
    {
        "title": "导入 / 导出",
        "body": "导入：从 Zotero / EndNote / Mendeley 等软件导出 BibTeX (.bib)、RIS、CSV 或 JSON 文件，"
                "拖进「导入 / 导出」页的框里即可，导入的论文进当前账号的收藏夹。\n"
                "导出：先选导出范围（全部 / 某个文件夹），再点对应的格式按钮。"
                "在某个文件夹里导出时，文件名就是文件夹名（比如 tabpfn.bib）。",
    },
    {
        "title": "账号",
        "body": "点右上角「登录」注册或登录。\n"
                "登录后收藏、已阅、文件夹、导入导出都按账号隔离，彼此看不到对方的数据；"
                "未登录时是匿名账号，数据只在这台浏览器上。\n"
                "已登录时再点右上角按钮进入「账号」面板，可以修改密码或退出登录。",
    },
    {
        "title": "设置",
        "body": "「设置 → 检索通道」：搜索固定使用 5 路检索，不用配置。\n"
                "同一页下方可以填 OpenAlex API Key / 邮箱和 Semantic Scholar Key（可选，额度更稳），"
                "填完点保存即可，不用改服务器文件。\n"
                "「⚙️ 配置大模型」：预设里一键添加 DeepSeek / Ollama 等，或自定义 OpenAI 兼容端点。",
    },
    {
        "title": "常见问题",
        "body": "- 搜索超时：外部 API 慢或额度用完，稍后重试。\n"
                "- 文献星图没有连线：这批结果里论文之间关联弱，换个更具体的关键词。\n"
                "- 觉得字小：界面默认已放大 15%，需要再调告诉我即可。",
    },
]


def _load_docs() -> list:
    """读取可编辑的文档内容；文件不存在或损坏时用默认内容。"""
    if not _DOCS_FILE.exists():
        return list(_DEFAULT_DOCS)
    try:
        data = json.loads(_DOCS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list) and data:
            return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取 docs_content.json 失败: %s", e)
    return list(_DEFAULT_DOCS)


def _is_admin(token: str) -> bool:
    """文档管理员：SAKURA_ADMIN_USERS / SAKURA_ADMIN_USER 指定的用户名。"""
    from agent.collections import verify_token
    username = verify_token(token) if token else None
    if not username:
        return False
    admins = [u.strip() for u in os.getenv("SAKURA_ADMIN_USERS", "").split(",") if u.strip()]
    admins.append(os.getenv("SAKURA_ADMIN_USER", "admin"))
    return username in admins


# ------------------------------------------------------------------ #
# 外部 API 配置（OpenAlex / Semantic Scholar，设置面板可改）
# ------------------------------------------------------------------ #

@app.get("/api/settings/api")
async def get_api_settings(token: str = "") -> Dict:
    """返回 API 配置（key 脱敏）+ 是否已登录。"""
    from agent.api_settings import load_api_config, mask_key
    from agent.collections import verify_token
    cfg = load_api_config()
    return {
        "status": "ok",
        "logged_in": bool(verify_token(token)) if token else False,
        "openalex_key": mask_key(cfg.get("openalex_key")),
        "openalex_email": cfg.get("openalex_email", ""),
        "s2_key": mask_key(cfg.get("s2_key")),
    }


@app.put("/api/settings/api")
async def update_api_settings(req: Dict, token: str = "") -> Dict:
    """保存 API 配置（需登录）。body: {openalex_key?, openalex_email?, s2_key?}"""
    from agent.api_settings import save_api_config
    from agent.collections import verify_token
    if not verify_token(token or ""):
        raise HTTPException(status_code=401, detail="请先登录")
    if not _is_admin(token):
        raise HTTPException(status_code=403, detail="仅管理员可修改 API 配置")
    if not isinstance(req, dict):
        raise HTTPException(status_code=400, detail="请求格式错误")
    try:
        cfg = save_api_config(
            openalex_key=req.get("openalex_key"),
            openalex_email=req.get("openalex_email"),
            s2_key=req.get("s2_key"),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"status": "ok", "configured": {k: bool(v) for k, v in cfg.items()}}


@app.on_event("startup")
async def _seed_admin_user() -> None:
    """启动时预置内置管理员账号（默认 admin / admin123，可用 .env 覆盖）。"""
    try:
        from agent.collections import ensure_admin_user
        ensure_admin_user(
            username=os.getenv("SAKURA_ADMIN_USER", "admin"),
            password=os.getenv("SAKURA_ADMIN_PASSWORD", "admin123"),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("预置管理员账号失败: %s", e)


@app.get("/api/docs")
async def get_docs(token: str = "") -> Dict:
    """获取使用文档内容；返回当前用户是否有编辑权限。"""
    return {"status": "ok", "sections": _load_docs(), "can_edit": _is_admin(token)}


@app.put("/api/docs")
async def update_docs(req: Dict, token: str = "") -> Dict:
    """管理员保存文档内容。body: {sections: [{title, body}]}"""
    if not _is_admin(token):
        raise HTTPException(status_code=403, detail="仅管理员可编辑文档")
    sections = req.get("sections") if isinstance(req, dict) else None
    if not isinstance(sections, list) or not sections:
        raise HTTPException(status_code=400, detail="sections 不能为空")
    cleaned = []
    for s in sections:
        if not isinstance(s, dict):
            continue
        title = str(s.get("title", "")).strip()
        body = str(s.get("body", "")).strip()
        if title or body:
            cleaned.append({"title": title or "未命名", "body": body})
    if not cleaned:
        raise HTTPException(status_code=400, detail="文档内容不能为空")
    try:
        _DOCS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _DOCS_FILE.write_text(
            json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as e:
        logger.error("保存 docs_content.json 失败: %s", e)
        raise HTTPException(status_code=500, detail="保存失败")
    return {"status": "ok", "sections": cleaned}


# ------------------------------------------------------------------ #
# 用户认证（本地账号 + 密码 hash）
# ------------------------------------------------------------------ #

class AuthRequest(BaseModel):
    username: str
    password: str


@app.post("/api/auth/register")
async def auth_register(req: AuthRequest) -> Dict:
    """注册新用户。"""
    from agent.collections import register_user
    result = register_user(req.username, req.password)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["detail"])
    return result


@app.post("/api/auth/login")
async def auth_login(req: AuthRequest) -> Dict:
    """登录。"""
    from agent.collections import login_user
    # 安全网：管理员账号被误删时，登录尝试会自动用 .env 配置重建（幂等）
    try:
        from agent.collections import ensure_admin_user
        ensure_admin_user(
            username=os.getenv("SAKURA_ADMIN_USER", "admin"),
            password=os.getenv("SAKURA_ADMIN_PASSWORD", "admin123"),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("重建管理员账号失败: %s", e)
    result = login_user(req.username, req.password)
    if result["status"] == "error":
        raise HTTPException(status_code=401, detail=result["detail"])
    return result


class ChangePasswordRequest(BaseModel):
    token: str = ""
    old_password: str = ""
    new_password: str = ""


@app.post("/api/auth/change-password")
async def auth_change_password(req: ChangePasswordRequest) -> Dict:
    """修改密码。"""
    from agent.collections import change_password
    result = change_password(req.token, req.old_password, req.new_password)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["detail"])
    return result


@app.post("/api/auth/logout")
async def auth_logout(token: str = "") -> Dict:
    """登出。"""
    from agent.collections import logout_user
    return logout_user(token)


@app.get("/api/auth/me")
async def auth_me(token: str = "") -> Dict:
    """获取当前登录用户。"""
    from agent.collections import verify_token
    username = verify_token(token) if token else None
    if username:
        return {"logged_in": True, "username": username}
    return {"logged_in": False, "username": ""}

@app.get("/api/export/bibtex")
async def export_bibtex(paper_id: str) -> Dict:
    """导出指定论文的 BibTeX 引用格式。"""
    import re
    from agent.collections import get_cached_paper
    from retrieval import get_retrieval_backend

    # 优先从缓存获取（收藏夹保存的元数据）
    d = get_cached_paper(paper_id)
    if not d or not d.get("title"):
        # 回退到 retrieval backend
        backend = get_retrieval_backend("semantic_scholar", use_mock=True)
        paper = await backend.get_paper(paper_id)
        if paper:
            d = paper.to_dict()
    if not d or not d.get("title"):
        raise HTTPException(status_code=404, detail="Paper not found")

    # cite key: 第一作者姓 + 年份 + 标题首词（只保留字母数字）
    authors_list = d.get("authors") or []
    first_author = authors_list[0] if authors_list else "Anonymous"
    last_name = re.sub(r'[^a-z0-9]', '', first_author.split()[-1].lower()) if first_author else "anon"
    year = d.get("year") or 2024
    first_word = re.sub(r'[^a-z0-9]', '', (d.get("title") or "untitled").split()[0].lower())
    cite_key = f"{last_name or 'anon'}{year}{first_word or 'untitled'}"

    authors_str = " and ".join(authors_list) if authors_list else "Anonymous"
    # 构造 BibTeX（只输出非空字段）
    lines = [
        f"@article{{{cite_key},",
        f"  title     = {{{d.get('title', '')}}},",
        f"  author    = {{{authors_str}}},",
        f"  year      = {{{year}}},",
    ]
    if d.get("venue"):
        lines.append(f"  journal   = {{{d['venue']}}},")
    if d.get("arxiv_id"):
        lines.append(f"  eprint    = {{{d['arxiv_id']}}},")
    if d.get("doi"):
        lines.append(f"  doi       = {{{d['doi']}}},")
    # 构造 URL（回退推导）
    url = d.get("url") or ""
    if not url:
        if d.get("arxiv_id"):
            url = f"https://arxiv.org/abs/{d['arxiv_id']}"
        elif d.get("doi"):
            url = f"https://doi.org/{d['doi']}"
    if url:
        lines.append(f"  url       = {{{url}}},")
    lines.append("}")
    bibtex = "\n".join(lines)
    return {"bibtex": bibtex, "cite_key": cite_key}


# ------------------------------------------------------------------ #
# 辅助
# ------------------------------------------------------------------ #

def _count_feedback_file() -> int:
    fb_path = ROOT / "data" / "feedback.jsonl"
    if not fb_path.exists():
        return 0
    return sum(1 for line in fb_path.read_text(encoding="utf-8").splitlines() if line.strip())


# 创新机制中文名映射（SPAR2 常驻机制）
_INNOVATION_NAMES = {
    "spar2_bfs_iterative": "① 迭代检索（BFS 多轮）",
    "spar2_doc_query": "② 文档驱动查询生成",
    "spar2_refchain_bi": "③ RefChain 双向引文扩展",
    "spar2_bge_prescreen": "④ BGE 语义预筛 + 语义保底",
    "spar2_multi_channel": "⑤ 多通道检索",
    "spar2_deadline_filter": "⑥ 评测截止日期过滤",
}


# ------------------------------------------------------------------ #
# 直接运行
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "web.app:app",
        host="0.0.0.0",
        port=8765,
        reload=True,
        log_level="info",
    )
