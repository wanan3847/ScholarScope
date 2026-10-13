#!/usr/bin/env python3
"""
测试改进后的SPAR2引擎性能
"""

import os
import json
from agent.spar2.engine import SPAR2Engine
from llm import get_llm

def test_improved_engine():
    """测试改进后的引擎性能"""
    # 设置环境变量以启用token节省模式和本地语义索引
    os.environ["SPAR2_TOKEN_SAVING"] = "1"
    os.environ["SAKURA_LOCAL_SEMANTIC"] = "1"
    
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
        judge_threshold=0.15,  # 进一步降低阈值以提高召回
        max_judge=250,         # 增加最大判断数
        local_top_k=600,       # 增加本地搜索范围
        deadline_seconds=180.0, # 增加时间限制
        max_rounds=3
    )
    
    # 更多样化的测试查询
    test_queries = [
        "Give me papers which show that using a smaller dataset in large language model pre-training can result in better models than using bigger datasets.",
        "List all papers that use autoregressive transformer to generate text.",
        "Provide me with all papers that discuss reinforcement learning in games.",
        "Papers about attention mechanisms in neural networks.",
        "Research on self-supervised learning for computer vision."
    ]
    
    total_returned = 0
    
    for i, query in enumerate(test_queries):
        print(f"\n--- 测试查询 {i+1} ---")
        print(f"查询: {query[:80]}...")
        
        try:
            result = engine.run(query)
            papers = result.get("papers", [])
            stats = result.get("stats", {})
            
            print(f"返回论文数: {len(papers)}")
            print(f"API调用: {stats.get('api_calls', 0)}")
            print(f"Token使用: {stats.get('tokens', 0)}")
            print(f"候选总数: {stats.get('candidates', 0)}")
            print(f"已判断数: {stats.get('judged', 0)}")
            
            if papers:
                print("前3篇论文:")
                for j, paper in enumerate(papers[:3]):
                    title = paper.get("title", "")[:60]
                    score = paper.get("score", 0)
                    print(f"  {j+1}. [{score:.3f}] {title}")
                total_returned += len(papers)
            else:
                print("未找到任何论文")
                
        except Exception as e:
            print(f"查询执行失败: {str(e)}")
            import traceback
            traceback.print_exc()

    print(f"\n总计返回论文数: {total_returned}")
    print(f"平均每查询返回: {total_returned/len(test_queries):.2f} 篇")

if __name__ == "__main__":
    test_improved_engine()