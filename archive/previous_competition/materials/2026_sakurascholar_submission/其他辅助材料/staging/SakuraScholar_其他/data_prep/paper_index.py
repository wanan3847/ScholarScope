#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
paper_index.py
==============

科研场景下复杂学术查询智能检索赛题——论文库索引脚本。

功能
----
1. 从 3 个数据源的 ``gold_papers`` 中抽取所有唯一论文 (paper_id)。
2. 优先用本地 ``cs_paper_2nd.zip`` 查全文 (若可解压)；不可用时改用标题文件
   ``id2paper.json``。
3. 对本地查不到的论文，调用 Semantic Scholar Graph API 拉取元数据
   (title/abstract/year/venue/authors)。
4. 缓存为 ``data/paper_index/papers.jsonl``，每行一篇论文。
5. 构建基于 ``title + abstract`` 的 embedding 索引：
   - 若本机存在 ``sentence-transformers`` 与 ``faiss``，则用 ``all-MiniLM-L6-v2`` + FAISS
   - 否则自动回退到 numpy + 词袋哈希 (无外部依赖) + 暴力检索

输出
----
- ``data/paper_index/papers.jsonl``    每行一篇 paper (jsonl)
- ``data/paper_index/faiss.index``     FAISS 索引或 numpy 暴力索引 (npy)
- ``data/paper_index/id_map.json``     corpus_id -> 行号
- ``data/paper_index/papers_meta.json`` 全量统计 (id 数、有 abstract 的、查不到的)

使用示例
--------
::

    python paper_index.py --root /Users/yangyazhou/SakuraPaper
    python paper_index.py --use-api    # 联网拉 S2 元数据
    python paper_index.py --no-api     # 仅本地
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import os
import pickle
import re
import sys
import time
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from tqdm import tqdm

# ---------------------------------------------------------------------------
# 可选依赖 (faiss / sentence-transformers)
# ---------------------------------------------------------------------------

try:
    import faiss  # type: ignore
    _HAS_FAISS = True
except Exception:  # noqa: BLE001
    faiss = None
    _HAS_FAISS = False

try:
    from sentence_transformers import SentenceTransformer  # type: ignore
    _HAS_ST = True
except Exception:  # noqa: BLE001
    SentenceTransformer = None
    _HAS_ST = False

try:
    import requests  # type: ignore
    _HAS_REQUESTS = True
except Exception:  # noqa: BLE001
    requests = None
    _HAS_REQUESTS = False

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------

logger = logging.getLogger("paper_index")


def setup_logging(level: str = "INFO") -> None:
    fmt = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class Paper:
    """统一后的论文元数据。"""

    paper_id: str
    title: str = ""
    abstract: str = ""
    year: int | None = None
    venue: str = ""
    authors: list[str] = field(default_factory=list)
    source: str = ""  # "local" / "s2_api" / "id2paper"


# ---------------------------------------------------------------------------
# 唯一论文抽取
# ---------------------------------------------------------------------------


def collect_unique_paper_ids(unified_jsonl: Path) -> dict[str, str]:
    """扫描 unified jsonl，收集所有唯一 paper_id。

    兼容 DOI 与 arxiv id；返回 {paper_id: source} 字典 (source 仅用于统计)。
    """
    out: dict[str, str] = {}
    if not unified_jsonl.exists():
        logger.error("未找到 %s", unified_jsonl)
        return out
    with unified_jsonl.open(encoding="utf-8") as fh:
        for line in tqdm(fh, desc="scan ids", dynamic_ncols=True):
            try:
                rec = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            for gp in rec.get("gold_papers", []):
                pid = str(gp.get("paper_id", "")).strip()
                if pid and pid not in out:
                    out[pid] = rec.get("source", "")
    logger.info("收集到 %d 个唯一 paper_id", len(out))
    return out


# ---------------------------------------------------------------------------
# 本地数据源：id2paper.json
# ---------------------------------------------------------------------------


def load_id2paper(path: Path) -> dict[str, str]:
    """读取 ``id2paper.json``，容错处理可能存在的语法错误。"""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8", errors="ignore")
    try:
        data = json.loads(text)
        return {str(k).strip(): str(v).strip() for k, v in data.items()}
    except json.JSONDecodeError as e:
        logger.warning("id2paper.json 解析失败: %s，尝试用 regex 补救", e)
        out: dict[str, str] = {}
        # 逐行匹配 "arxiv_id": "title"  形式
        for m in re.finditer(r'"([\d.]+)"\s*:\s*"((?:\\.|[^"\\])*)"', text):
            out[m.group(1)] = m.group(2).encode().decode("unicode_escape", errors="ignore")
        logger.info("regex 补救得到 %d 条", len(out))
        return out


# ---------------------------------------------------------------------------
# 本地数据源：cs_paper_2nd.zip (尽量安全打开)
# ---------------------------------------------------------------------------


def open_local_zip(path: Path) -> zipfile.ZipFile | None:
    """安全打开 zip。损坏时返回 None。"""
    if not path.exists():
        return None
    try:
        return zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        logger.warning("无法打开 zip %s: %s", path, e)
        return None


# ---------------------------------------------------------------------------
# Semantic Scholar API
# ---------------------------------------------------------------------------


S2_FIELDS = "title,abstract,year,venue,authors"
S2_HEADERS = {"User-Agent": "SakuraPaper-DataPrep/1.0"}


def fetch_s2_metadata(paper_id: str, timeout: float = 15.0) -> Paper | None:
    """通过 Semantic Scholar Graph API 获取元数据。

    Args:
        paper_id: arxiv id (e.g. ``1909.11740``) 或 S2 corpus_id。
        timeout:  HTTP 超时。

    Returns:
        Paper 实例；失败时返回 None。
    """
    if not _HAS_REQUESTS:
        return None
    url = None
    pid = paper_id.strip()
    if pid.isdigit():
        url = f"https://api.semanticscholar.org/graph/v1/paper/{pid}"
    elif re.match(r"^\d{4}\.\d{4,5}$", pid):
        # arxiv id
        url = f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{pid}"
    elif pid.startswith("DOI:") or pid.startswith("10."):
        did = pid[4:] if pid.startswith("DOI:") else pid
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{did}"
    if not url:
        return None
    try:
        resp = requests.get(url, params={"fields": S2_FIELDS}, headers=S2_HEADERS, timeout=timeout)
    except requests.RequestException as e:  # type: ignore[attr-defined]
        logger.debug("S2 request error for %s: %s", pid, e)
        return None
    if resp.status_code != 200:
        logger.debug("S2 %s status=%d", pid, resp.status_code)
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    authors = []
    for a in data.get("authors", []) or []:
        name = a.get("name")
        if name:
            authors.append(name)
    venue = ""
    v = data.get("venue")
    if isinstance(v, str):
        venue = v
    return Paper(
        paper_id=pid,
        title=data.get("title", "") or "",
        abstract=data.get("abstract", "") or "",
        year=data.get("year"),
        venue=venue,
        authors=authors,
        source="s2_api",
    )


# ---------------------------------------------------------------------------
# Embedding 后端
# ---------------------------------------------------------------------------


def _hash_token(token: str, dim: int) -> int:
    """稳定的 token -> 维度 哈希函数。"""
    h = hashlib.md5(token.encode("utf-8")).digest()
    return int.from_bytes(h[:4], "big") % dim


class HashingBowEmbedder:
    """轻量回退 embedding：词袋 + 哈希投影 (无外部依赖)。"""

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim
        self.token_re = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,}")

    def encode(self, texts: list[str]) -> np.ndarray:
        arr = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for tok in self.token_re.findall(t.lower()):
                arr[i, _hash_token(tok, self.dim)] += 1.0
            norm = np.linalg.norm(arr[i])
            if norm > 0:
                arr[i] /= norm
        return arr


def get_embedder(backend: str = "auto", model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
    """根据可用依赖选择 embedding 后端。

    Returns:
        (embedder, name) 元组。
    """
    if backend in ("auto", "sbert") and _HAS_ST:
        try:
            logger.info("使用 sentence-transformers: %s", model_name)
            return SentenceTransformer(model_name), f"sbert:{model_name}"
        except Exception as e:  # noqa: BLE001
            logger.warning("加载 sentence-transformers 失败: %s，回退到 hash bow", e)
    logger.info("使用 HashingBowEmbedder (回退后端)")
    return HashingBowEmbedder(512), "hash_bow"


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def build_paper_index(
    root: Path,
    out_dir: Path,
    use_api: bool,
    api_rps: float,
    limit: int | None,
) -> dict[str, Any]:
    """构建 paper index 主流程。

    Args:
        root:     仓库根目录。
        out_dir:  输出目录 (e.g. ``data_prep/outputs/paper_index``)。
        use_api:  是否联网调用 S2 API。
        api_rps:  S2 API 速率 (req/s)。
        limit:    限制最大处理论文数 (None=不限)。
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    unified_jsonl = root / "data_prep" / "outputs" / "unified_queries" / "all_queries.jsonl"
    id2paper_fp = root / "data" / "PaSa" / "paper_database" / "id2paper.json"
    zip_fp = root / "data" / "PaSa" / "paper_database" / "cs_paper_2nd.zip"

    # 1) 抽取唯一 paper id
    pid2src = collect_unique_paper_ids(unified_jsonl)
    pids = list(pid2src.keys())
    if limit:
        pids = pids[:limit]
        logger.info("限制最大处理数: %d", limit)

    # 2) 加载 id2paper
    id2title = load_id2paper(id2paper_fp)
    logger.info("id2paper 提供 %d 个标题", len(id2title))

    # 3) 安全打开 zip (尽量读)
    zf = open_local_zip(zip_fp)
    zip_names: set[str] = set(zf.namelist()) if zf else set()
    logger.info("cs_paper_2nd.zip 包含 %d 个文件", len(zip_names))

    # 4) 命中 / 查 S2
    papers: list[Paper] = []
    n_local = n_zip = n_api = n_missing = 0
    min_interval = 1.0 / max(api_rps, 0.1) if use_api else 0
    last_call = 0.0

    for pid in tqdm(pids, desc="build index", dynamic_ncols=True):
        # a) zip 命中
        if zf is not None:
            for cand in (f"{pid}.txt", f"{pid}.json", pid):
                if cand in zip_names:
                    try:
                        with zf.open(cand) as fh:
                            raw = fh.read(200_000).decode("utf-8", errors="ignore")
                        # 简单解析：第一行标题，后续为 abstract
                        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
                        title = lines[0] if lines else id2title.get(pid, "")
                        abstract = "\n".join(lines[1:]) if len(lines) > 1 else ""
                        papers.append(Paper(
                            paper_id=pid, title=title, abstract=abstract, source="local_zip",
                        ))
                        n_zip += 1
                        break
                    except Exception:  # noqa: BLE001
                        pass
            else:
                pass
            if papers and papers[-1].paper_id == pid:
                continue

        # b) id2paper 命中
        if pid in id2title:
            papers.append(Paper(paper_id=pid, title=id2title[pid], source="id2paper"))
            n_local += 1
            continue

        # c) S2 API
        if use_api:
            # 限速
            if min_interval > 0:
                now = time.time()
                wait = min_interval - (now - last_call)
                if wait > 0:
                    time.sleep(wait)
                last_call = time.time()
            meta = fetch_s2_metadata(pid)
            if meta is not None:
                papers.append(meta)
                n_api += 1
                continue
        n_missing += 1
        papers.append(Paper(paper_id=pid, source=""))

    # 5) 写 papers.jsonl
    fp_papers = out_dir / "papers.jsonl"
    with fp_papers.open("w", encoding="utf-8") as fh:
        for p in papers:
            fh.write(json.dumps(asdict(p), ensure_ascii=False) + "\n")
    logger.info("已写入 %s: %d 条", fp_papers, len(papers))

    # 6) 写 papers_meta.json (统计)
    has_abs = sum(1 for p in papers if p.abstract)
    meta = {
        "total": len(papers),
        "from_local_zip": n_zip,
        "from_id2paper": n_local,
        "from_s2_api": n_api,
        "missing": n_missing,
        "with_abstract": has_abs,
    }
    (out_dir / "papers_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    # 7) 构建 id_map.json
    id_map = {p.paper_id: i for i, p in enumerate(papers)}
    (out_dir / "id_map.json").write_text(json.dumps(id_map, ensure_ascii=False))

    # 8) Embedding
    embedder, embed_name = get_embedder()
    texts = [f"{p.title}\n{p.abstract}".strip() for p in papers]
    logger.info("Embedding 模型: %s, 文本数: %d", embed_name, len(texts))
    embeddings = embedder.encode(texts)  # type: ignore[union-attr]
    embeddings = np.asarray(embeddings, dtype=np.float32)
    if embeddings.ndim == 1:
        embeddings = embeddings.reshape(1, -1)

    # 9) 索引
    fp_index = out_dir / "faiss.index"
    if _HAS_FAISS:
        dim = embeddings.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(embeddings)
        faiss.write_index(index, str(fp_index))
        logger.info("已写入 FAISS 索引: %s (dim=%d)", fp_index, dim)
    else:
        # 回退：保存为 .npy + .pkl 元信息
        np.save(out_dir / "faiss.index", embeddings)
        with (out_dir / "faiss.index.pkl").open("wb") as fh:
            pickle.dump({"backend": embed_name, "dim": int(embeddings.shape[1])}, fh)
        logger.warning("未安装 faiss-cpu，已将 embedding 存为 numpy 数组: faiss.index.npy")
    return meta


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="构建论文库 embedding 索引")
    p.add_argument("--root", type=Path, default=Path("/Users/yangyazhou/SakuraPaper"))
    p.add_argument(
        "--out", type=Path,
        default=Path("/Users/yangyazhou/SakuraPaper/data_prep/outputs/paper_index"),
    )
    p.add_argument("--use-api", action="store_true", help="联网调用 Semantic Scholar API")
    p.add_argument("--no-api", dest="use_api", action="store_false")
    p.set_defaults(use_api=True)
    p.add_argument("--api-rps", type=float, default=1.0, help="S2 API 速率 req/s (默认 1)")
    p.add_argument("--limit", type=int, default=None, help="最多处理 N 个 paper_id")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.log_level)
    meta = build_paper_index(
        root=args.root,
        out_dir=args.out,
        use_api=args.use_api,
        api_rps=args.api_rps,
        limit=args.limit,
    )
    logger.info("统计: %s", json.dumps(meta, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
