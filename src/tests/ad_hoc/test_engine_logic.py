#!/usr/bin/env python3
"""
测试优化后的SPAR2引擎逻辑（使用mock LLM）
"""

import os
from agent.spar2.engine import SPAR2Engine
from llm import get_llm

def test_engine_logic():
    """测试引擎逻辑是否正常工作"""
    # 设置环境变量以启用token节省模式
    os.environ["SPAR2_TOKEN_SAVING"] = "1"
    
    # 使用mock LLM进行测试
    llm = get_llm("mock")
    
    # 包装LLM对象以提供可调用接口
    def llm_chat_wrapper(prompt, **kwargs):
        from llm.base import LLMMessage
        messages = [LLMMessage(role="user", content=prompt)]
        return llm.chat(messages, **kwargs)
    
    # 创建优化后的引擎
    engine = SPAR2Engine(
        llm_chat=llm_chat_wrapper,
        max_output=10,
        judge_threshold=0.20,  # 降低阈值以提高召回
        max_judge=200,         # 增加最大判断数
        local_top_k=500,       # 增加本地搜索范围
        deadline_seconds=120.0, # 增加时间限制
        max_rounds=2
    )
    
    # 测试查询
    test_queries = [
        "Give me papers which show that using a smaller dataset in large language model pre-training can result in better models than using bigger datasets.",
        "List all papers that use autoregressive transformer to generate text.",
        "Provide me with all papers that discuss reinforcement learning in games."
    ]
    
    for i, query in enumerate(test_queries):
        print(f"\n--- 测试查询 {i+1} ---")
        print(f"查询: {query[:100]}...")
        
        try:
            result = engine.run(query)
            papers = result.get("papers", [])
            stats = result.get("stats", {})
            
            print(f"返回论文数: {len(papers)}")
            print(f"API调用: {stats.get('api_calls', 0)}")
            print(f"Token使用: {stats.get('tokens', 0)}")
            print(f"候选总数: {stats.get('candidates', 0)}")
            print(f"已判断数: {stats.get('judged', 0)}")
            print(f"引擎: {stats.get('engine', 'unknown')}")
            
            if papers:
                print("前5篇论文:")
                for j, paper in enumerate(papers[:5]):
                    title = paper.get("title", "")[:80]
                    score = paper.get("score", 0)
                    print(f"  {j+1}. [{score:.3f}] {title}")
            else:
                print("未找到任何论文")
                
        except Exception as e:
            print(f"查询执行失败: {str(e)}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    test_engine_logic()