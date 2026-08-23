#!/usr/bin/env python3
"""
构建本地语义索引，以提高检索效率
"""

import os
from retrieval.local_corpus import LocalCorpusBackend

def build_index():
    """构建本地语义索引"""
    # 设置环境变量启用语义索引
    os.environ["SAKURA_LOCAL_SEMANTIC"] = "1"
    os.environ["SAKURA_LOCAL_EMBED_RESUME"] = "1"
    
    print("正在构建本地语义索引...")
    try:
        backend = LocalCorpusBackend(use_mock=False)
        print("本地语义索引构建完成")
        print(f"标题数量: {len(backend._titles)}")
        print(f"嵌入可用: {backend._embeddings is not None}")
    except Exception as e:
        print(f"构建本地语义索引时出错: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    build_index()