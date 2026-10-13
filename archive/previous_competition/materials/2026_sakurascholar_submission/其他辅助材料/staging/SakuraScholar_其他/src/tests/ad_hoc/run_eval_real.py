"""用真实 API + Ollama 跑 1 条 RealScholarQuery，输出真实分数。"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from evaluation.runner import EvaluationRunner, BENCHMARK_REGISTRY
from evaluation.metrics import compute_all_metrics
from agent.orchestrator import Orchestrator
from llm.router import get_default_router

# 注册 Ollama
router = get_default_router()
router.register(
    name="ollama",
    model="qwen3:8b",
    base_url="http://localhost:11434/v1",
    priority=10,
)
llm = router.get("ollama")

# 加载 RealScholarQuery 第 1 条
runner = EvaluationRunner()
items = runner._load_json_or_jsonl(BENCHMARK_REGISTRY["real_scholar"]["path"])
item = runner._normalize_item(items[0])
print(f"Query: {item['query']}")
print(f"Gold IDs: {item['gold_ids']}")
print()

# 用真实 API + Ollama 跑
orch = Orchestrator(
    llm=llm,
    backends=["semantic_scholar", "openalex"],
    use_mock_retrieval=False,  # 真实 API
    innovation_flags={k: False for k in [
        "qag", "cac", "cadr", "hea", "dbe", "tet", "ace",
        "nrd", "sscp", "ccr", "sar", "nss", "aqr", "mcs", "apr",
    ]},  # 关闭所有创新模块，减少 LLM 调用
)

print("开始搜索（真实 API + Ollama qwen3:8b）...")
import time
t0 = time.time()
result = orch.run(item["query"])
elapsed = time.time() - t0

pred_ids = [p.get("arxiv_id", "") or p.get("doi", "") or p.get("title", "")
            for p in result.get("papers", [])]
metrics = compute_all_metrics(pred_ids, item["gold_ids"])

print(f"\n耗时: {elapsed:.1f}s")
print(f"返回论文数: {len(result.get('papers', []))}")
print(f"前 5 篇 pred_ids: {pred_ids[:5]}")
print(f"gold_ids: {item['gold_ids']}")
print(f"\n📊 真实分数:")
for k, v in metrics.items():
    print(f"  {k} = {v}")

stats = result.get("stats", {})
print(f"\n效率:")
print(f"  API 调用: {stats.get('api_calls', 0)}")
print(f"  Token: {stats.get('tokens', 0)}")
print(f"  延时: {stats.get('elapsed_seconds', 0):.2f}s")
