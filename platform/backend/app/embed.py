import hashlib, numpy as np
DIM = 384
def embed(text: str) -> list[float]:
    """Dependency-free hashing embedder. Swap in sentence-transformers/CLIP for production quality."""
    v = np.zeros(DIM)
    for w in text.lower().split():
        h = int(hashlib.md5(w.encode()).hexdigest(), 16)
        v[h % DIM] += 1 if (h >> 8) & 1 else -1
    n = np.linalg.norm(v)
    return (v / n if n else v).tolist()
