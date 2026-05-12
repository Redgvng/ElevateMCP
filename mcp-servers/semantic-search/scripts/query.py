#!/usr/bin/env python3
"""Query a previously-indexed directory."""
from __future__ import annotations
import argparse
import math
import os
import pickle
import sys
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from _common import cache_dir_for, load_manifest, VENV_PY  # noqa: E402
from index import tokenize  # reuse tokenizer for tfidf  # noqa: E402


def relaunch_in_venv():
    if VENV_PY.exists() and Path(sys.executable).resolve() != VENV_PY.resolve():
        os.execv(str(VENV_PY), [str(VENV_PY), *sys.argv])


def query_fastembed(cache: Path, q: str, k: int):
    from fastembed import TextEmbedding  # type: ignore
    import numpy as np

    arr = np.load(cache / "embeds.npy")
    with (cache / "chunks.pkl").open("rb") as f:
        chunks = pickle.load(f)

    model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    qv = next(model.query_embed([q]))
    qv = np.array(qv, dtype=np.float32)
    qv = qv / (np.linalg.norm(qv) or 1.0)

    scores = arr @ qv
    idx = np.argsort(-scores)[:k]
    return [(float(scores[i]), chunks[i]) for i in idx]


def query_tfidf(cache: Path, q: str, k: int):
    with (cache / "chunks.pkl").open("rb") as f:
        chunks = pickle.load(f)
    with (cache / "idf.pkl").open("rb") as f:
        idf = pickle.load(f)

    qtokens = Counter(tokenize(q))
    if not qtokens:
        return []
    q_weights = {t: cnt * idf.get(t, 0.0) for t, cnt in qtokens.items()}
    q_norm = math.sqrt(sum(w * w for w in q_weights.values())) or 1.0

    results = []
    for c in chunks:
        tf = c.get("tf", {})
        if not tf:
            continue
        dot = 0.0
        d_norm_sq = 0.0
        for t, freq in tf.items():
            w = freq * idf.get(t, 0.0)
            d_norm_sq += w * w
            if t in q_weights:
                dot += w * q_weights[t]
        d_norm = math.sqrt(d_norm_sq) or 1.0
        score = dot / (d_norm * q_norm)
        if score > 0:
            results.append((score, c))
    results.sort(key=lambda x: -x[0])
    return results[:k]


def render(results, target: Path):
    if not results:
        print("(no results)")
        return
    for score, c in results:
        path = target / c["file"]
        print(f"=== {score:.3f} {path}:{c['start']}-{c['end']} ===")
        print(c["text"])
        print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", help="Indexed directory")
    ap.add_argument("query", help="Natural language query")
    ap.add_argument("--k", type=int, default=8)
    args = ap.parse_args()

    target = Path(args.dir).resolve()
    cache = cache_dir_for(target)
    manifest = load_manifest(cache)
    backend = manifest.get("backend")
    if not backend:
        print(f"[query] No index at {cache}. Run index.py first.", file=sys.stderr)
        sys.exit(2)

    relaunch_in_venv()

    if backend == "fastembed":
        results = query_fastembed(cache, args.query, args.k)
    elif backend == "tfidf":
        results = query_tfidf(cache, args.query, args.k)
    else:
        print(f"[query] Unknown backend: {backend}", file=sys.stderr)
        sys.exit(3)

    render(results, target)


if __name__ == "__main__":
    main()
