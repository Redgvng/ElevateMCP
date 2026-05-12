"""Shared utilities for semantic-search index/query."""
from __future__ import annotations
import hashlib
import json
import os
import re
from pathlib import Path

CACHE_ROOT = Path.home() / ".commandcode" / "semantic-cache"
VENV_PY = Path.home() / ".commandcode" / "venv" / "bin" / "python3"

SKIP_DIRS = {
    ".git", "node_modules", "dist", "build", ".next", ".nuxt", "coverage",
    "__pycache__", ".pytest_cache", ".turbo", ".cache", "vendor", "target",
    ".venv", "venv", ".idea", ".vscode", ".commandcode",
}
SKIP_EXT = {
    ".lock", ".lockb", ".min.js", ".map", ".png", ".jpg", ".jpeg", ".gif",
    ".webp", ".svg", ".pdf", ".zip", ".tar", ".gz", ".woff", ".woff2", ".ttf",
    ".ico", ".bin", ".so", ".dylib", ".dll", ".exe", ".class", ".jar",
    ".onnx", ".pt", ".pth", ".pkl", ".npy", ".npz", ".db", ".sqlite",
}
SKIP_FILES = {"package-lock.json", "bun.lock", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock"}
MAX_BYTES = 200_000
CHUNK_LINES = 40
CHUNK_OVERLAP = 8


def cache_dir_for(target: Path) -> Path:
    h = hashlib.sha1(str(target.resolve()).encode()).hexdigest()[:16]
    d = CACHE_ROOT / h
    d.mkdir(parents=True, exist_ok=True)
    return d


def iter_files(root: Path):
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn in SKIP_FILES:
                continue
            ext = Path(fn).suffix.lower()
            if ext in SKIP_EXT:
                continue
            p = Path(dirpath) / fn
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_size == 0 or st.st_size > MAX_BYTES:
                continue
            yield p, st.st_mtime


def is_text(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            chunk = f.read(2048)
        if b"\x00" in chunk:
            return False
        try:
            chunk.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return True
    except OSError:
        return False


def read_text(path: Path) -> str | None:
    if not is_text(path):
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def chunk_file(text: str, path: Path):
    """Yield (start_line, end_line, chunk_text)."""
    lines = text.splitlines()
    if not lines:
        return
    n = len(lines)
    step = CHUNK_LINES - CHUNK_OVERLAP
    i = 0
    while i < n:
        j = min(i + CHUNK_LINES, n)
        body = "\n".join(lines[i:j]).strip()
        if body:
            yield (i + 1, j, body)
        if j == n:
            break
        i += step


def load_manifest(cache: Path) -> dict:
    f = cache / "manifest.json"
    if f.exists():
        return json.loads(f.read_text())
    return {"files": {}, "backend": None}


def save_manifest(cache: Path, manifest: dict) -> None:
    (cache / "manifest.json").write_text(json.dumps(manifest, indent=2))
