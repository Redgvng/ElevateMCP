#!/usr/bin/env python3
"""MCP server: semantic code search.

Indexes a directory of source code with embeddings (fastembed BGE-small,
fully offline after first model fetch), then answers natural-language
queries with ranked file:line snippets. Falls back to TF-IDF if fastembed
unavailable.

Cache directory configurable via MCP_TOOLKIT_CACHE env var (default
~/.cache/mcp-toolkit/semantic-search).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("semantic-search")

# Use the same Python that runs this server (must have fastembed/numpy installed).
VENV_PY = sys.executable
# Scripts ship next to this server file.
SCRIPTS = Path(__file__).parent / "scripts"
# Cache: respect XDG conventions, override via env var.
CACHE = Path(os.environ.get(
    "MCP_TOOLKIT_CACHE",
    str(Path.home() / ".cache" / "mcp-toolkit" / "semantic-search"),
))


def _run(cmd: list[str], timeout: int = 600) -> tuple[int, str, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


@mcp.tool()
def index(directory: str, rebuild: bool = False) -> str:
    """Index a directory for semantic search. Incremental — re-runs only re-embed changed files.

    Run this once per repo, then `query` to search by intent. Indexes are cached at
    ~/.commandcode/semantic-cache/<sha1(dir)>/. First run on a fresh directory
    downloads the embedding model (~50 MB, one time).

    Args:
        directory: Absolute path to the directory to index.
        rebuild: If True, wipe the existing cache and re-embed everything.

    Returns:
        Status output from the indexer.
    """
    d = Path(directory).expanduser().resolve()
    if not d.is_dir():
        return f"error: not a directory: {directory}"
    cmd = [VENV_PY, str(SCRIPTS / "index.py"), str(d)]
    if rebuild:
        cmd.append("--rebuild")
    rc, out, err = _run(cmd, timeout=900)
    msg = err.strip() or out.strip() or "done"
    return f"[{'OK' if rc == 0 else f'ERR rc={rc}'}] {msg}"


@mcp.tool()
def query(directory: str, q: str, k: int = 8) -> str:
    """Search the indexed directory by intent (natural language).

    Use this instead of grep when looking by *meaning* rather than exact tokens.
    The directory must have been indexed first via `index`.

    Args:
        directory: Absolute path to a previously-indexed directory.
        q: Natural-language query (e.g. "where do we hash passwords", "rate limit middleware").
        k: Number of top results to return. Default 8.

    Returns:
        Ranked snippets with score, file:line, and code excerpt. Empty if no index found.
    """
    d = Path(directory).expanduser().resolve()
    if not d.is_dir():
        return f"error: not a directory: {directory}"
    cmd = [VENV_PY, str(SCRIPTS / "query.py"), str(d), q, "--k", str(k)]
    rc, out, err = _run(cmd, timeout=60)
    if rc != 0:
        return f"error: {err.strip() or out.strip()}"
    return out.strip() or "(no results)"


@mcp.tool()
def list_indexes() -> str:
    """List all directories currently indexed for semantic search.

    Returns:
        One line per cached index: <directory>  <chunks>  <backend>
    """
    if not CACHE.exists():
        return "(no indexes yet — run index() first)"
    import json as _json
    lines = []
    for d in sorted(CACHE.iterdir()):
        manifest = d / "manifest.json"
        if not manifest.exists():
            continue
        try:
            m = _json.loads(manifest.read_text())
        except Exception:
            continue
        n_files = len(m.get("files", {}))
        backend = m.get("backend", "?")
        # try to find original dir from a heuristic — we don't store it directly
        # Could add later; for now just print cache hash
        lines.append(f"  {d.name}  files={n_files}  backend={backend}")
    return "Indexed directories:\n" + ("\n".join(lines) if lines else "  (empty)")


if __name__ == "__main__":
    mcp.run()
