"""
ScholarScope 端到端 Demo

演示 5 个真实学术查询的完整 pipeline 运行。
不依赖任何外部 API key，开箱即跑。

运行：
    cd /Users/yangyazhou/SakuraPaper/src
    python examples/run_demo.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.orchestrator import Orchestrator

SAMPLE_QUERIES_PATH = Path(__file__).parent / "sample_queries.json"
SAMPLE_OUTPUT_PATH = Path(__file__).parent / "sample_output.json"


def main():
    """跑 demo：逐条 query 跑 pipeline，打印统计信息。"""
    queries = json.loads(SAMPLE_QUERIES_PATH.read_text(encoding="utf-8"))
    print(f"\n========== ScholarScope Demo ==========")
    print(f"查询数: {len(queries)}")
    print(f"=========================================\n")

    orch = Orchestrator()
    results = []
    for idx, q in enumerate(queries, 1):
        query_text = q["query"]
        query_type = q.get("type", "general")
        print(f"\n[{idx}/{len(queries)}] type={query_type}")
        print(f"  Q: {query_text}")
        t0 = time.time()
        out = orch.sync_run(query_text)
        elapsed = time.time() - t0
        print(f"  -> top {len(out['papers'])} papers "
              f"(api_calls={out['stats']['api_calls']}, "
              f"tokens={out['stats']['tokens']}, "
              f"elapsed={elapsed:.2f}s)")
        for p in out["papers"][:3]:
            print(f"     - [{p['source']}] {p['title'][:80]}")
        results.append(out)

    # 写入 sample_output 作为 reference
    SAMPLE_OUTPUT_PATH.write_text(
        json.dumps(results[:1], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n参考输出已写入 {SAMPLE_OUTPUT_PATH}")
    print("\n========== Demo 完成 ==========")


if __name__ == "__main__":
    main()
