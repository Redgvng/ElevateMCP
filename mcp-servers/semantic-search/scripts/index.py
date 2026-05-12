#!/usr/bin/env python3
"""Index a directory for semantic search. Incremental, free, local."""
from __future__ import annotations
import argparse
import math
import os
import pickle
import re
import sys
from collections import Counter
from pathlib import Path

# Force venv Python for fastembed deps
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from _common import (  # noqa: E402
    cache_dir_for, iter_files, read_text, chunk_file,
    load_manifest, save_manifest, VENV_PY,
)


def relaunch_in_venv():
    """If we're not already in the venv, exec into it."""
    if VENV_PY.exists() and Path(sys.executable).resolve() != VENV_PY.resolve():
        os.execv(str(VENV_PY), [str(VENV_PY), *sys.argv])


def try_fastembed():
    try:
        from fastembed import TextEmbedding  # type: ignore
        return TextEmbedding
    except ImportError:
        return None


def install_fastembed() -> bool:
    """One-shot: install fastembed in our venv. Returns True on success."""
    import subprocess
    pip = VENV_PY.parent / "pip"
    if not pip.exists():
        print("[index] No venv found at ~/.commandcode/venv — falling back to TF-IDF.", file=sys.stderr)
        return False
    print("[index] Installing fastembed (one-time, ~150 MB of deps)...", file=sys.stderr)
    res = subprocess.run([str(pip), "install", "--quiet", "fastembed"], capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[index] fastembed install failed: {res.stderr[:300]}", file=sys.stderr)
        return False
    return True


# ----------------- Backend: fastembed -----------------

def index_with_fastembed(target: Path, cache: Path, manifest: dict, rebuild: bool):
    from fastembed import TextEmbedding  # type: ignore
    import numpy as np

    model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")

    chunks_path = cache / "chunks.pkl"
    embeds_path = cache / "embeds.npy"

    if rebuild or not chunks_path.exists():
        all_chunks = []
        manifest = {"files": {}, "backend": "fastembed"}
    else:
        with chunks_path.open("rb") as f:
            all_chunks = pickle.load(f)

    chunks_by_file = {}
    for c in all_chunks:
        chunks_by_file.setdefault(c["file"], []).append(c)

    seen = set()
    new_or_updated = []
    for path, mtime in iter_files(target):
        rel = str(path.relative_to(target))
        seen.add(rel)
        prev = manifest["files"].get(rel)
        if prev and prev["mtime"] == mtime:
            continue
        text = read_text(path)
        if text is None:
            continue
        chunks_by_file[rel] = []
        for s, e, body in chunk_file(text, path):
            chunks_by_file[rel].append({"file": rel, "start": s, "end": e, "text": body})
        manifest["files"][rel] = {"mtime": mtime}
        new_or_updated.append(rel)

    # Drop deleted files
    deleted = [r for r in list(chunks_by_file.keys()) if r not in seen]
    for r in deleted:
        del chunks_by_file[r]
        manifest["files"].pop(r, None)

    all_chunks = [c for f in chunks_by_file.values() for c in f]
    print(f"[index] {len(seen)} files, {len(all_chunks)} chunks. Updated: {len(new_or_updated)}, deleted: {len(deleted)}", file=sys.stderr)

    if not all_chunks:
        print("[index] No chunks. Nothing to embed.", file=sys.stderr)
        return

    print(f"[index] Embedding {len(all_chunks)} chunks (fastembed BGE-small)...", file=sys.stderr)
    texts = [c["text"] for c in all_chunks]
    vectors = list(model.embed(texts, batch_size=64))
    arr = np.array(vectors, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    arr = arr / norms

    np.save(embeds_path, arr)
    with chunks_path.open("wb") as f:
        pickle.dump(all_chunks, f)
    save_manifest(cache, manifest)
    print(f"[index] OK — saved to {cache}", file=sys.stderr)


# ----------------- Backend: TF-IDF (fallback) -----------------

WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def tokenize(text: str) -> list[str]:
    # split camelCase and snake_case
    out = []
    for tok in WORD_RE.findall(text):
        parts = re.split(r"_+", tok)
        for p in parts:
            sub = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", p).split()
            out.extend(s.lower() for s in sub if len(s) > 2)
    return out


def index_with_tfidf(target: Path, cache: Path, _manifest: dict, _rebuild: bool):
    print("[index] Backend: TF-IDF (fastembed unavailable).", file=sys.stderr)
    chunks = []
    df = Counter()
    for path, _ in iter_files(target):
        text = read_text(path)
        if text is None:
            continue
        rel = str(path.relative_to(target))
        for s, e, body in chunk_file(text, path):
            tokens = tokenize(body)
            if not tokens:
                continue
            tf = Counter(tokens)
            chunks.append({"file": rel, "start": s, "end": e, "text": body, "tf": dict(tf)})
            for term in tf:
                df[term] += 1

    n = max(len(chunks), 1)
    idf = {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}

    with (cache / "chunks.pkl").open("wb") as f:
        pickle.dump(chunks, f)
    with (cache / "idf.pkl").open("wb") as f:
        pickle.dump(idf, f)
    save_manifest(cache, {"files": {}, "backend": "tfidf"})
    print(f"[index] OK — {len(chunks)} chunks indexed (TF-IDF) at {cache}", file=sys.stderr)


# ----------------- Main -----------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", help="Directory to index")
    ap.add_argument("--rebuild", action="store_true", help="Wipe cache and rebuild from scratch")
    ap.add_argument("--no-install", action="store_true", help="Don't try to install fastembed")
    args = ap.parse_args()

    target = Path(args.dir).resolve()
    if not target.is_dir():
        print(f"[index] Not a directory: {target}", file=sys.stderr)
        sys.exit(2)

    relaunch_in_venv()

    cache = cache_dir_for(target)
    if args.rebuild:
        for f in cache.glob("*"):
            f.unlink()

    manifest = load_manifest(cache)

    TextEmbedding = try_fastembed()
    if TextEmbedding is None and not args.no_install:
        if install_fastembed():
            TextEmbedding = try_fastembed()

    if TextEmbedding is not None:
        index_with_fastembed(target, cache, manifest, args.rebuild)
    else:
        index_with_tfidf(target, cache, manifest, args.rebuild)


if __name__ == "__main__":
    main()
