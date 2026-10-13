import time
from fastembed import TextEmbedding
from retrieval.local_corpus import LocalCorpusBackend

if __name__ == "__main__":
    b = LocalCorpusBackend(use_mock=True); b._ensure_index()
    m = TextEmbedding(model_name="BAAI/bge-small-en-v1.5", threads=2)
    st=time.time(); n=0
    for _ in m.embed(list(b._titles.values())[:10000], batch_size=1024, parallel=4): n += 1
    print(n, time.time()-st, flush=True)
