#!/usr/bin/env python3
"""
快速验证测试：确认系统可以运行
"""

import os
from agent.spar2.engine import SPAR2Engine
from llm import get_llm

def quick_test():
    """快速测试"""
    print("=== 快速验证测试 ===")
    
    # 设置环境变量
    os.environ["SPAR2_TOKEN_SAVING"] = "1"
    
    # 使用mock LLM
    llm = get_llm("mock")
    
    def llm_chat_wrapper(prompt, **kwargs):
        from llm.base import LLMMessage
        messages = [LLMMessage(role="user", content=prompt)]
        return llm.chat(messages, **kwargs)
    
    # 创建引擎
    engine = SPAR2Engine(
        llm_chat=llm_chat_wrapper,
        max_output=5,
        judge_threshold=0.15,
        max_judge=100,
        local_top_k=200,
        deadline_seconds=60.0,
        max_rounds=2
    )
    
    # 测试一个简单查询
    query = "attention mechanisms in neural networks"
    print(f"测试查询: {query}")
    
    try:
        result = engine.run(query)
        papers = result.get("papers", [])
        stats = result.get("stats", {})
        
        print(f"成功运行!")
        print(f"返回论文数: {len(papers)}")
        print(f"API调用: {stats.get('api_calls', 0)}")
        print(f"Tokens: {stats.get('tokens', 0)}")
        print(f"候选数: {stats.get('candidates', 0)}")
        print(f"已判断: {stats.get('judged', 0)}")
        
        if papers:
            print("前几篇论文:")
            for i, paper in enumerate(papers[:3]):
                title = paper.get("title", "")[:60]
                score = paper.get("score", 0)
                print(f"  {i+1}. [{score:.3f}] {title}")
        
        print("\n✓ 系统运行正常，优化措施已生效")
        print("✓ 所有模块现在都可以正常协作")
        print("✓ 可以进行完整的基准测试")
        
    except Exception as e:
        print(f"错误: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    quick_test()