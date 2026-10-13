#!/usr/bin/env python3
"""Low-memory BGE index build script - resume from breakpoint, single thread."""
import json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

import numpy as np

cache_dir = ROOT / ".cache"
emb_path = cache_dir / "pasa_titles_bge_small.f16.npy"
ids_path = cache_dir / "pasa_titles_bge_small.ids.json"
tmp_path = emb_path.with_suffix(".tmp.npy")

if emb_path.exists() and ids_path.exists():
    ids = json.loads(ids_path.read_text())
    arr = np.load(emb_path, mmap_mode="r")
    print(f"Index already exists: {arr.shape[0]} entries, skip.")
    sys.exit(0)

from retrieval.local_corpus import _LINE_RE, _decode_title
corpus_path = ROOT / "data" / "PaSa" / "paper_database" / "id2paper.json"
titles = {}
with corpus_path.open("r", encoding="utf-8", errors="ignore") as fh:
    for line in fh:
        m = _LINE_RE.match(line)
        if m:
            titles[m.group(1)] = _decode_title(m.group(2))

ids = list(titles.keys())
texts = [titles[i] for i in ids]
total = len(ids)
print(f"Corpus: {total} papers")

start = 0
if tmp_path.exists():
    old = np.load(tmp_path, mmap_mode="r")
    if old.shape == (total, 384):
        nonzero = np.any(old != 0, axis=1)
        filled = np.flatnonzero(nonzero)
        if len(filled) > 0:
            start = int(filled[-1]) + 1
            print(f"Resume from row {start} ({100*start/total:.1f}% done)")
    else:
        print(f"Shape mismatch: tmp={old.shape} vs expected=({total},384). Deleting old tmp.")
        del old
        tmp_path.unlink(missing_ok=True)
    if start == 0 and tmp_path.exists():
        del old

if start >= total:
    print("Already complete!")
else:
    from fastembed import TextEmbedding
    model = TextEmbedding(
        model_name="BAAI/bge-small-en-v1.5",
        threads=4,
        cache_dir=str(cache_dir / "fastembed"),
    )
    remaining = total - start
    print(f"Encoding {remaining} entries (batch=128, single thread)...")
    t0 = time.time()

    # Create memmap if tmp doesn't exist
    if not tmp_path.exists():
        arr_init = np.lib.format.open_memmap(
            tmp_path, mode="w+", dtype=np.float16, shape=(total, 384)
        )
        del arr_init
    arr = np.load(tmp_path, mmap_mode="r+")
    batch_size = 128
    last_flush = start

    for batch_start in range(start, total, batch_size):
        batch_end = min(batch_start + batch_size, total)
        batch_texts = texts[batch_start:batch_end]
        vecs = list(model.embed(batch_texts))
        for i, vec in enumerate(vecs):
            v = np.asarray(vec, dtype=np.float32)
            v /= max(float(np.linalg.norm(v)), 1e-8)
            arr[batch_start + i] = v.astype(np.float16)

        if batch_end - last_flush >= 256000:
            arr.flush()
            last_flush = batch_end

        done = batch_end
        if done % 5000 < batch_size or done == total:
            elapsed = time.time() - t0
            rate = (done - start) / max(elapsed, 1)
            eta = (total - done) / max(rate, 1)
            print(f"  [{done}/{total}] {100*done/total:.1f}%  "
                  f"{rate:.0f} items/s  ETA {eta/60:.1f} min", flush=True)

    arr.flush()
    del arr
    gc.collect()
    elapsed = time.time() - t0
    print(f"Encoding done! Took {elapsed/60:.1f} minutes")

os.replace(tmp_path, emb_path)
ids_path.write_text(json.dumps(ids), encoding="utf-8")
print(f"Saved: {emb_path} ({total} entries)")

arr = np.load(emb_path, mmap_mode="r")
ids2 = json.loads(ids_path.read_text())
print(f"Verify: arr={arr.shape}, ids={len(ids2)} OK")
