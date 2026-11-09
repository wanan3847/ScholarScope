"""Source-grounded project retrieval with persistent full-text/vector index."""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from sqlalchemy import JSON, Column, ForeignKey, String, Table, Text, delete, insert, select, text

from workspace.store import WorkspaceError, digest, normalized

MODEL = os.getenv("SCHOLARSCOPE_EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")


def terms(value):
    words = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", str(value).casefold())
    stop = {"a", "an", "the", "is", "are", "of", "in", "for", "to", "and", "we", "with", "this", "what", "how", "were", "was", "does", "can"}
    tokens = [w for w in words if w not in stop and not re.match(r"^[\u4e00-\u9fff]", w)]
    for w in words:
        if re.match(r"^[\u4e00-\u9fff]", w):
            tokens.extend(w[i:i+2] for i in range(max(1, len(w)-1)))
    return tokens


def sources(store, pid, actor):
    papers = store.items(pid, actor, "paper")
    docs = store.items(pid, actor, "document")
    chunks = []
    for paper in papers:
        available = [d for d in docs if d["data"].get("paper_id") == paper["id"]]
        for scope in ("title", "abstract"):
            value = str(paper["data"].get(scope) or "")
            if value.strip():
                for n, chunk in enumerate(split_text(value)):
                    chunks.append({"id": digest(paper["id"] + scope + str(n))[:40], "text": chunk,
                        "source": {"paper_id": paper["id"], "scope": scope, "title": paper["label"], "source_hash": digest(value)}})
        for doc in available:
            for page in doc["data"].get("pages", []):
                for n, chunk in enumerate(split_text(page.get("text", ""))):
                    chunks.append({"id": digest(doc["id"] + str(page["number"]) + str(n))[:40], "text": chunk,
                        "source": {"paper_id": paper["id"], "document_id": doc["id"], "page": page["number"],
                                   "scope": "fulltext", "title": paper["label"], "source_hash": digest(page["text"])}})
    return chunks


def split_text(value, size=900, overlap=120):
    value = normalized(value)
    return [value[i:i+size] for i in range(0, len(value), size-overlap) if value[i:i+size].strip()]


def embeddings(values, timeout=24):
    if not values or os.getenv("SCHOLARSCOPE_DISABLE_EMBEDDINGS") == "1":
        return None
    with tempfile.TemporaryDirectory(prefix="scholarscope-embed-") as tmp:
        source = Path(tmp) / "input.json"
        result = Path(tmp) / "vectors.json"
        source.write_text(json.dumps(values, ensure_ascii=False))
        try:
            process = subprocess.run([sys.executable, "-m", "workspace.knowledge", "--embed", str(source), str(result)],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=timeout,
                env={**os.environ, "TOKENIZERS_PARALLELISM": "false"})
            if process.returncode or not result.exists():
                return None
            vectors = json.loads(result.read_text())
            if len(vectors) != len(values) or not all(v and all(math.isfinite(float(x)) for x in v) for v in vectors):
                return None
            return vectors
        except Exception:
            return None


class ProjectIndex:
    def __init__(self, store):
        self.store = store
        pg = store.engine.dialect.name == "postgresql"
        if pg:
            from pgvector.sqlalchemy import Vector
            with store.engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        self.table = Table("research_chunks", store.meta,
            Column("id", String(40), primary_key=True),
            Column("project_id", String(40), ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False, index=True),
            Column("text", Text, nullable=False), Column("content_hash", String(64), nullable=False),
            Column("source", JSON, nullable=False), Column("model", String(200), nullable=False),
            Column("embedding", Vector() if pg else JSON, nullable=True), extend_existing=True)
        self.table.create(store.engine, checkfirst=True)
        if pg:
            with store.engine.begin() as conn:
                conn.execute(text("CREATE INDEX IF NOT EXISTS research_chunks_fts ON research_chunks USING gin (to_tsvector('simple', text))"))
        else:
            with store.engine.begin() as conn:
                conn.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS research_chunks_fts USING fts5(id UNINDEXED, project_id UNINDEXED, text)"))
        from workspace.migrations import record_migration
        record_migration(store.engine, 2, "persistent full-text and semantic chunk index")

    def ensure(self, pid, actor, rebuild_vectors=False):
        data = sources(self.store, pid, actor)
        if len(data) > 6000:
            raise WorkspaceError("当前项目全文超过本次索引预算，请按课题拆分")
        with self.store.engine.connect() as conn:
            old = {r._mapping["id"]: dict(r._mapping) for r in conn.execute(select(self.table).where(self.table.c.project_id == pid))}
        changed = [r for r in data if r["id"] not in old or old[r["id"]]["content_hash"] != digest(r["text"]) or old[r["id"]]["source"] != r["source"]
                   or rebuild_vectors and old[r["id"]]["model"] != MODEL]
        # Already-indexed embeddings are reused across requests and restarts.
        vectors = embeddings([r["text"] for r in changed]) if changed else []
        records = []
        changed_map = {r["id"]: i for i, r in enumerate(changed)}
        for r in data:
            previous = old.get(r["id"])
            if r["id"] in changed_map:
                vector = vectors[changed_map[r["id"]]] if vectors else None
                model = MODEL if vector else "keyword"
            else:
                vector, model = previous["embedding"], previous["model"]
            records.append({"id": r["id"], "project_id": pid, "text": r["text"], "content_hash": digest(r["text"]),
                            "source": r["source"], "model": model, "embedding": vector})
        if changed or set(old) != {r["id"] for r in data}:
            with self.store.engine.begin() as conn:
                conn.execute(delete(self.table).where(self.table.c.project_id == pid))
                if records:
                    conn.execute(insert(self.table), records)
                if self.store.engine.dialect.name == "sqlite":
                    conn.execute(text("DELETE FROM research_chunks_fts WHERE project_id=:pid"), {"pid": pid})
                    for r in records:
                        conn.execute(text("INSERT INTO research_chunks_fts (id,project_id,text) VALUES (:id,:pid,:text)"),
                                     {"id": r["id"], "pid": pid, "text": r["text"]})
        return records

    def retrieve(self, pid, actor, question, limit=8, paper_ids=None):
        if not question.strip():
            raise WorkspaceError("请填写研究问题")
        rows = self.ensure(pid, actor)
        if paper_ids:
            rows = [r for r in rows if r["source"]["paper_id"] in paper_ids]
        if not rows:
            return {"mode": "no_sources", "passages": []}
        query_terms = set(terms(question))
        fts_hits = set()
        if query_terms:
            with self.store.engine.connect() as conn:
                if self.store.engine.dialect.name == "sqlite":
                    expression = " OR ".join('"' + t.replace('"', '""') + '"' for t in sorted(query_terms)[:80])
                    fts_hits = set(conn.execute(text("SELECT id FROM research_chunks_fts WHERE research_chunks_fts MATCH :q AND project_id=:pid ORDER BY rank LIMIT 400"),
                                                {"q": expression, "pid": pid}).scalars())
                else:
                    expression = " | ".join(sorted(query_terms)[:80])
                    fts_hits = set(conn.execute(text("SELECT id FROM research_chunks WHERE project_id=:pid AND to_tsvector('simple', text) @@ to_tsquery('simple', :q) LIMIT 400"),
                                                {"q": expression, "pid": pid}).scalars())
        qvector = embeddings([question]) if any(r["embedding"] is not None and r["model"] == MODEL for r in rows) else None
        semantic = bool(qvector)
        if qvector and self.store.engine.dialect.name == "postgresql":
            with self.store.engine.connect() as conn:
                semantic_ids = set(conn.execute(select(self.table.c.id).where(self.table.c.project_id == pid,
                    self.table.c.model == MODEL, self.table.c.embedding.is_not(None)).order_by(
                    self.table.c.embedding.cosine_distance(qvector[0])).limit(250)).scalars())
            rows = [r for r in rows if r["id"] in semantic_ids or r["id"] in fts_hits]
        ranked = []
        for row in rows:
            bag = Counter(terms(row["text"]))
            lexical = sum(math.log1p(bag[t]) for t in query_terms if t in bag) / max(1, len(query_terms))
            if row["id"] in fts_hits:
                lexical += .05
            similarity = 0
            if qvector and row["embedding"] is not None and row["model"] == MODEL:
                similarity = sum(float(a) * float(b) for a, b in zip(qvector[0], row["embedding"]))
            if lexical <= 0 and similarity < .28:
                continue
            ranked.append((lexical + max(0, similarity) * .7, row))
        ranked.sort(key=lambda x: x[0], reverse=True)
        # Internal retrieval relevance is not a public paper recommendation score.
        return {"mode": "semantic_hybrid" if semantic else "keyword_degraded", "passages": [
            {"text": row["text"], **row["source"], "chunk_id": row["id"]}
            for _, row in ranked[:max(1, min(limit, 30))]]}


if __name__ == "__main__" and len(sys.argv) > 3 and sys.argv[1] == "--embed":
    try:
        import torch
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        from sentence_transformers import SentenceTransformer
        allow = os.getenv("SCHOLARSCOPE_ALLOW_MODEL_DOWNLOAD") == "1"
        model = SentenceTransformer(MODEL, local_files_only=not allow, trust_remote_code=False, device="cpu")
        values = json.loads(Path(sys.argv[2]).read_text())
        vectors = model.encode(values, batch_size=32, normalize_embeddings=True, show_progress_bar=False).tolist()
        Path(sys.argv[3]).write_text(json.dumps(vectors))
    except Exception:
        sys.exit(1)
