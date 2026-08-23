#!/usr/bin/env python3
"""
一次性脚本：批量预填充 S2 corpusId 缓存。

用法：
    python3 scripts/prefill_s2_cache.py   # 在仓库根目录执行

功能：
    - 遍历本地已知论文列表（PaSa 数据库 + 评测集 gold）
    - 对每个 arXiv ID / DOI，调用 S2 API 获取 corpusId
    - 增量写入 src/data/s2_corpus_id_cache.json（与 run_eval.py 共用）
    - S2 429 时自动退避，恢复后继续

前提：
    - S2 API 可用（非 429 状态）
    - 已有 src/data/s2_corpus_id_cache.json（由 run_eval.py 创建）
"""

import json
import sys
import time
from pathlib import Path
from typing import Dict, List

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / "src" / "data" / "s2_corpus_id_cache.json"
S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"


def load_cache() -> Dict[str, str]:
    """加载现有 S2 corpusId 缓存。"""
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except Exception:
            return {}
    return {}


def save_cache(cache: Dict[str, str]):
    """保存 S2 corpusId 缓存。"""
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2))


def collect_paper_ids() -> List[Dict[str, str]]:
    """
    收集本地已知论文的 arXiv ID 和 DOI 列表。
    
    来源：
    1. data/PaSa/paper_database/id2paper.json（arXiv ID → 标题）
    2. src/data/benchmarks/ 下各评测集的 gold 数据（json/jsonl 递归）
    """
    papers = []
    seen = set()

    def _add(arxiv: str = "", doi: str = "") -> None:
        """去重添加一篇论文（arxiv/doi 至少有一个）。"""
        arxiv = (arxiv or "").strip()
        doi = (doi or "").strip().lower()
        if arxiv:
            key = f"arxiv:{arxiv}"
            if key not in seen:
                seen.add(key)
                papers.append({"arxiv_id": arxiv, "doi": doi})
        elif doi:
            key = f"doi:{doi}"
            if key not in seen:
                seen.add(key)
                papers.append({"arxiv_id": "", "doi": doi})

    # 1) PaSa 论文数据库
    pasa_db = ROOT / "data" / "PaSa" / "paper_database"
    id2paper = pasa_db / "id2paper.json" if pasa_db.exists() else None
    if id2paper and id2paper.exists():
        try:
            db = json.loads(id2paper.read_text(encoding="utf-8", errors="ignore"))
            if isinstance(db, dict):
                for arxiv in db:
                    _add(arxiv=arxiv)
            else:
                print(f"  [WARN] {id2paper} 不是 dict 格式")
        except Exception as e:
            print(f"  [WARN] 读取 {id2paper} 失败: {e}")

    # 2) 评测集 gold 数据
    bench_dir = ROOT / "src" / "data" / "benchmarks"
    if bench_dir.exists():
        for data_file in bench_dir.rglob("*"):
            if data_file.suffix not in (".json", ".jsonl") or data_file.name.startswith("."):
                continue
            try:
                if data_file.suffix == ".jsonl":
                    items = [json.loads(line) for line in data_file.read_text(encoding="utf-8").splitlines() if line.strip()]
                else:
                    raw = json.loads(data_file.read_text(encoding="utf-8", errors="ignore"))
                    items = raw if isinstance(raw, list) else [raw]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    # 常见 gold 字段：gold_ids / answer_arxiv_id / s2_doi / doi / arxiv_id
                    for arxiv in (item.get("gold_ids") or item.get("answer_arxiv_id") or []):
                        _add(arxiv=arxiv)
                    dois = item.get("s2_doi")
                    if not dois and item.get("doi"):
                        dois = [item.get("doi")]
                    for doi in (dois or []):
                        _add(doi=doi)
            except Exception as e:
                print(f"  [WARN] 读取 {data_file} 失败: {e}")

    return papers


def query_s2_batch(papers: List[Dict[str, str]], cache: Dict[str, str], batch_size: int = 50):
    """
    批量查询 S2 API 获取 corpusId，增量写入缓存。
    
    Args:
        papers: 论文列表，每项包含 arxiv_id 和 doi
        cache: 现有缓存（会被修改）
        batch_size: 每批查询数量（S2 限制 500）
    """
    # 过滤出未缓存的论文
    uncached = []
    for p in papers:
        arxiv = p.get("arxiv_id") or ""
        doi = p.get("doi") or ""
        
        # 检查是否已缓存
        if arxiv and f"arxiv:{arxiv}" in cache:
            continue
        if doi and f"doi:{doi}" in cache:
            continue
        
        # 构造 S2 查询 ID
        if arxiv:
            uncached.append({"id": f"ARXIV:{arxiv}", "arxiv": arxiv, "doi": doi})
        elif doi:
            uncached.append({"id": f"DOI:{doi}", "arxiv": arxiv, "doi": doi})
    
    if not uncached:
        print("✓ 所有论文已缓存，无需查询")
        return
    
    print(f"待查询: {len(uncached)} 篇论文")
    
    # 分批查询
    for i in range(0, len(uncached), batch_size):
        batch = uncached[i:i + batch_size]
        ids = [p["id"] for p in batch]
        
        # S2 batch API
        try:
            resp = requests.post(
                S2_BATCH_URL,
                params={"fields": "externalIds"},
                json={"ids": ids},
                timeout=30,
            )
            
            if resp.status_code == 429:
                print(f"  [429] S2 API 限流，等待 60 秒...")
                time.sleep(60)
                continue
            
            if resp.status_code != 200:
                print(f"  [ERROR] S2 API 返回 {resp.status_code}: {resp.text[:200]}")
                continue
            
            results = resp.json().get("data") or []
            
            # 提取 corpusId 并写入缓存
            for paper_info, s2_result in zip(batch, results):
                if not s2_result:
                    continue
                corpus_id = s2_result.get("corpusId")
                if not corpus_id:
                    continue
                
                # 写入缓存（arXiv 和 DOI 都映射到 corpusId）
                if paper_info.get("arxiv"):
                    cache[f"arxiv:{paper_info['arxiv']}"] = str(corpus_id)
                if paper_info.get("doi"):
                    cache[f"doi:{paper_info['doi']}"] = str(corpus_id)
            
            # 增量保存
            save_cache(cache)
            print(f"  [{i + len(batch)}/{len(uncached)}] 已缓存 {len(cache)} 条")
            
            # 避免触发限流
            time.sleep(1)
        
        except Exception as e:
            print(f"  [ERROR] 批量查询失败: {e}")
            continue


def main():
    print("=" * 60)
    print("S2 corpusId 批量预填充脚本")
    print("=" * 60)
    
    # 加载现有缓存
    cache = load_cache()
    print(f"现有缓存: {len(cache)} 条")
    
    # 收集论文 ID
    print("\n收集本地论文 ID...")
    papers = collect_paper_ids()
    print(f"收集到: {len(papers)} 篇论文")
    
    # 批量查询 S2
    print("\n开始批量查询 S2 API...")
    query_s2_batch(papers, cache)
    
    # 最终统计
    cache = load_cache()
    print("\n" + "=" * 60)
    print(f"✓ 完成！缓存总数: {len(cache)} 条")
    print(f"缓存文件: {CACHE_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    main()
