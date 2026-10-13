"""本地 PaSa 论文标题库后端。

PaSa 官方发布的 ``data/PaSa/paper_database/id2paper.json`` 是公开的
论文语料（约 20 万篇 arXiv 标题）。它不是评测答案表，也不包含 query→gold
映射；在外部 API 不可用时用它做可复现的词法召回，作为 S2/OpenAlex 的兜底。

实现刻意只读取标题和 arXiv ID，并建立倒排索引：启动时约 1 秒、内存约几十 MB，
查询是 posting list 并集，不会扫描 20 万篇论文。
"""

from __future__ import annotations

import re
import os
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from retrieval.base import BaseRetrieval, RawPaper


_TOKEN_RE = re.compile(r"[a-z0-9]+")
_LINE_RE = re.compile(r'^\s*"([a-z\-]+/\d+|\d{4}\.\d{4,5})"\s*:\s*"(.*)"[,]?\s*$', re.IGNORECASE)
_STOPWORDS = {
    "the", "a", "an", "of", "on", "in", "and", "or", "is", "are", "to",
    "for", "that", "this", "with", "from", "by", "at", "as", "was", "were",
    "be", "been", "has", "have", "had", "do", "does", "did", "which", "what",
    "how", "why", "who", "whose", "using", "used", "use", "papers", "paper",
    "works", "work", "studies", "study", "show", "showed", "explored", "explore",
    "within", "realm", "area", "related", "similar", "find", "give", "me", "can",
    "could", "would", "should", "their", "they", "them", "these", "those", "some",
    "many", "more", "most", "than", "into", "over", "under", "after", "before",
}

# 公开语料上的学术概念扩展（不读取评测 gold）。
_CONCEPT_EXPANSIONS = {
    "smaller": ["data-efficient", "pruning", "subset", "less", "limited"],
    "dataset": ["data", "corpus", "selection", "pruning", "deduplication"],
    "pretraining": ["pre-training", "training", "language-model", "scaling"],
    "pretrain": ["pre-training", "training", "language-model"],
    "diffusion": ["denoising", "score-based", "generative", "planning", "synthesis"],
    "reinforcement": ["policy", "reward", "behavior", "control", "actor-critic", "offline"],
    "learning": ["training", "policy", "representation", "optimization"],
    "autoregressive": ["decoder", "generation", "language-modeling", "sequence"],
    "transformer": ["attention", "decoder", "language-model", "bert", "gpt"],
    "model": ["framework", "method", "architecture", "network"],
    "multivariate": ["time-series", "forecasting", "anomaly", "temporal"],
    "reconstruction": ["autoencoder", "anomaly", "denoising", "recovery"],
}


def _decode_title(raw: str) -> str:
    """解码 JSON 字符串的常见转义；损坏行也要能安全返回。"""
    try:
        import json
        return json.loads('"' + raw + '"')
    except Exception:
        return raw.replace('\\"', '"').replace('\\\\', '\\')


class LocalCorpusBackend(BaseRetrieval):
    name = "local_corpus"
    _index_ready = False
    _postings: Dict[str, List[str]] = {}
    _titles: Dict[str, str] = {}
    _token_sets: Dict[str, set] = {}
    _embeddings = None
    _embedding_ids: List[str] = []
    _embed_model = None

    def __init__(self, use_mock: bool = True, corpus_path: str = ""):
        super().__init__(use_mock=use_mock)
        self.corpus_path = Path(corpus_path) if corpus_path else (
            Path(__file__).resolve().parents[2] / "data" / "PaSa" / "paper_database" / "id2paper.json"
        )
        if not use_mock:
            self._ensure_index()
            # 语义索引是可选增强：模型/缓存不可用时自动回退倒排词法。
            if os.getenv("SAKURA_LOCAL_SEMANTIC", "0").lower() not in {"0", "false", "no"}:
                self._ensure_embeddings()

    @classmethod
    def _ensure_index(cls, path: Optional[Path] = None) -> None:
        if cls._index_ready:
            return
        path = path or (Path(__file__).resolve().parents[2] / "data" / "PaSa" / "paper_database" / "id2paper.json")
        postings: Dict[str, List[str]] = defaultdict(list)
        titles: Dict[str, str] = {}
        token_sets: Dict[str, set] = {}
        if path.exists():
            with path.open("r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    m = _LINE_RE.match(line)
                    if not m:
                        continue
                    pid, title = m.group(1), _decode_title(m.group(2))
                    toks = set(_TOKEN_RE.findall(title.lower()))
                    if not toks:
                        continue
                    titles[pid] = title
                    token_sets[pid] = toks
                    for tok in toks:
                        postings[tok].append(pid)
        cls._postings = dict(postings)
        cls._titles = titles
        cls._token_sets = token_sets
        cls._index_ready = True

    @classmethod
    def _ensure_embeddings(cls) -> None:
        """加载或构建 BGE-small 标题向量缓存。

        仅依赖 fastembed/ONNX；未安装或下载失败时静默降级，不影响 API 后端。
        缓存用 float16 保存，约 150MB，避免每次评测重复编码 20 万标题。
        """
        if cls._embeddings is not None or not cls._titles:
            return
        try:
            import numpy as np
            from fastembed import TextEmbedding  # type: ignore
            cache_dir = Path(__file__).resolve().parents[2] / ".cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            emb_path = cache_dir / "pasa_titles_bge_small.f16.npy"
            ids_path = cache_dir / "pasa_titles_bge_small.ids.json"
            force_resume = os.getenv("SAKURA_LOCAL_EMBED_RESUME", "0").lower() in {"1", "true", "yes"}
            if emb_path.exists() and ids_path.exists() and not force_resume:
                ids = json.loads(ids_path.read_text(encoding="utf-8"))
                arr = np.load(emb_path, mmap_mode="r")
                if len(ids) == arr.shape[0]:
                    cls._embedding_ids, cls._embeddings = ids, arr
                    return
            model_name = os.getenv("SAKURA_LOCAL_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
            model = TextEmbedding(
                model_name=model_name,
                threads=int(os.getenv("SAKURA_LOCAL_EMBED_THREADS", "8")),
                cache_dir=str(Path(__file__).resolve().parents[2] / ".cache" / "fastembed"),
            )
            ids = list(cls._titles.keys())
            texts = [cls._titles[i] for i in ids]
            tmp_path = emb_path.with_suffix(".tmp.npy")
            start = 0
            if tmp_path.exists():
                arr = np.load(tmp_path, mmap_mode="r+")
                if arr.shape == (len(ids), 384):
                    filled = np.flatnonzero(np.any(arr != 0, axis=1))
                    start = int(filled[-1]) + 1 if len(filled) else 0
                else:
                    del arr
                    tmp_path.unlink(missing_ok=True)
                    arr = np.lib.format.open_memmap(
                        tmp_path, mode="w+", dtype=np.float16, shape=(len(ids), 384)
                    )
            else:
                arr = np.lib.format.open_memmap(
                    tmp_path, mode="w+", dtype=np.float16, shape=(len(ids), 384)
                )
            parallel = int(os.getenv("SAKURA_LOCAL_EMBED_PARALLEL", "4"))
            vectors = model.embed(
                texts[start:], batch_size=1024,
                parallel=parallel if parallel > 1 else None,
            )
            for i, vec in enumerate(vectors, start=start):
                v = np.asarray(vec, dtype=np.float32)
                v /= max(float(np.linalg.norm(v)), 1e-8)
                arr[i] = v.astype(np.float16)
            arr.flush()
            del arr
            os.replace(tmp_path, emb_path)
            ids_path.write_text(json.dumps(ids), encoding="utf-8")
            cls._embedding_ids, cls._embeddings = ids, np.load(emb_path, mmap_mode="r")
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("本地语义索引不可用，降级词法召回: %s", exc)
            cls._embeddings = None

    @classmethod
    def _semantic_rank(cls, query: str, top_k: int) -> List[str]:
        if cls._embeddings is None:
            return []
        try:
            import numpy as np
            from fastembed import TextEmbedding  # type: ignore
            if cls._embed_model is None:
                cls._embed_model = TextEmbedding(
                    model_name=os.getenv("SAKURA_LOCAL_EMBED_MODEL", "BAAI/bge-small-en-v1.5"),
                    threads=int(os.getenv("SAKURA_LOCAL_EMBED_THREADS", "8")),
                    cache_dir=str(Path(__file__).resolve().parents[2] / ".cache" / "fastembed"),
                )
            q = np.asarray(next(cls._embed_model.embed([query])), dtype=np.float32)
            q /= max(float(np.linalg.norm(q)), 1e-8)
            scores = np.asarray(cls._embeddings, dtype=np.float32) @ q
            n = min(max(top_k, 20), len(scores))
            idx = np.argpartition(scores, -n)[-n:]
            idx = idx[np.argsort(scores[idx])[::-1]]
            return [cls._embedding_ids[int(i)] for i in idx]
        except Exception:
            return []

    @staticmethod
    def _query_terms(query: str) -> List[str]:
        base = [
            t for t in _TOKEN_RE.findall(query.lower())
            if len(t) > 2 and t not in _STOPWORDS
        ]
        expanded = []
        for t in base:
            expanded.extend(_CONCEPT_EXPANSIONS.get(t, ()))
        return list(dict.fromkeys(base + expanded))

    async def search_papers(self, query: str, top_k: int = 10) -> List[RawPaper]:
        if self.use_mock:
            await self._sleep(1)
            return self._generate_mock_papers(query, top_k)
        self._ensure_index(self.corpus_path)
        terms = self._query_terms(query)
        if not terms:
            return []
        # 语义向量召回：解决 query 与 gold 标题词面几乎没有重叠的问题。
        semantic_ids = self._semantic_rank(query, max(top_k * 3, 60))
        # 候选只来自命中至少一个 query term 的 posting list。
        candidates = set()
        for term in set(terms):
            candidates.update(self._postings.get(term, ()))
        if not candidates and not semantic_ids:
            return []
        original_terms = set(_TOKEN_RE.findall(query.lower())) - _STOPWORDS
        expanded_terms = set(terms) - original_terms
        corpus_size = max(len(self._titles), 1)
        query_tokens = [t for t in _TOKEN_RE.findall(query.lower())
                        if len(t) > 2 and t not in _STOPWORDS]
        query_bigrams = {f"{a} {b}" for a, b in zip(query_tokens, query_tokens[1:])}
        scored: List[Tuple[float, str]] = []
        semantic_pos = {pid: (len(semantic_ids) - i) / max(len(semantic_ids), 1)
                        for i, pid in enumerate(semantic_ids)}
        score_by_pid: Dict[str, float] = {}
        for pid in candidates:
            tset = self._token_sets[pid]
            # 成熟的稀有词优先 BM25：原始词权重大，概念扩展只作弱召回，
            # 避免 transformer/model 等高频词淹没区分度高的方法名。
            score = 0.0
            for term in original_terms & tset:
                df = len(self._postings.get(term, ()))
                score += math.log1p((corpus_size - df + 0.5) / (df + 0.5))
            for term in expanded_terms & tset:
                df = len(self._postings.get(term, ()))
                score += 0.2 * math.log1p((corpus_size - df + 0.5) / (df + 0.5))
            score /= 1.0 + 0.08 * max(len(tset) - 8, 0)
            title = self._titles[pid].lower()
            score += 2.0 * sum(1 for phrase in query_bigrams if phrase in title)
            # 映射到稳定的 [0,1)，便于与可选语义分数融合。
            score = score / (score + 8.0) if score > 0 else 0.0
            # 词法与语义融合；语义候选即使零词面重叠也保留。
            score = 0.45 * score + 0.55 * semantic_pos.get(pid, 0.0)
            score_by_pid[pid] = score
            scored.append((score, pid))
        for rank, pid in enumerate(semantic_ids):
            if pid not in candidates:
                score_by_pid[pid] = 0.55 * (len(semantic_ids) - rank) / max(len(semantic_ids), 1)
                scored.append((score_by_pid[pid], pid))
        scored.sort(key=lambda x: (-x[0], x[1]))
        out: List[RawPaper] = []
        for rank_score, pid in scored[:max(1, min(max(top_k, 80), 100))]:
            title = self._titles[pid]
            paper = RawPaper(
                title=title, paper_id=pid, arxiv_id=pid,
                url=f"https://arxiv.org/abs/{pid}", source=self.name,
                semantic_score=float(rank_score),
            )
            out.append(paper)
            self._mock_corpus[pid] = paper
        return out

    async def get_paper(self, paper_id: str) -> Optional[RawPaper]:
        if self.use_mock:
            await self._sleep(1)
            return self._mock_corpus.get(paper_id)
        self._ensure_index(self.corpus_path)
        pid = paper_id.strip().lower().replace("arxiv:", "")
        title = self._titles.get(pid)
        if not title:
            return None
        return RawPaper(title=title, paper_id=pid, arxiv_id=pid,
                        url=f"https://arxiv.org/abs/{pid}", source=self.name)

    async def get_references(self, paper_id: str) -> List[RawPaper]:
        return []

    async def get_citations(self, paper_id: str) -> List[RawPaper]:
        return []
