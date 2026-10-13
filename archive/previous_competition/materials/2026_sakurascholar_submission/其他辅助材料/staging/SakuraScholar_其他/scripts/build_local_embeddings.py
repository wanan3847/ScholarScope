"""Build the optional PaSa local title embedding cache."""
import time
from retrieval.local_corpus import LocalCorpusBackend

if __name__ == "__main__":
    st = time.time()
    b = LocalCorpusBackend(use_mock=False)
    print(f"built={time.time()-st:.1f}s shape={getattr(b._embeddings, 'shape', None)}", flush=True)
