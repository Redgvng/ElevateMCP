#!/usr/bin/env python3
"""ElevateMCP gateway — single-process host for all 19 MCP servers.

Loads each server module once (shared Python interpreter) and re-registers
their tools in one FastMCP instance, reducing RAM from ~1 GB (19 processes)
to ~90-100 MB (1 process).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# _registry.py lives next to this file — add its dir to path
sys.path.insert(0, str(Path(__file__).parent))
from _registry import RENAMES, TOOLS  # noqa: E402

mcp = FastMCP("ElevateMCP")
_SERVERS_DIR = Path(__file__).parent.parent
_THIS = sys.modules[__name__]


def _load(name: str):
    """Import mcp-servers/<name>/server.py as an isolated module."""
    key = f"_gw_{name.replace('-', '_')}"
    if key in sys.modules:
        return sys.modules[key]
    path = _SERVERS_DIR / name / "server.py"
    spec = importlib.util.spec_from_file_location(key, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


for _srv, _fns in TOOLS.items():
    try:
        _mod = _load(_srv)
    except ImportError:
        # Optional dep absent (e.g. playwright for browser-inspect) — skip gracefully
        continue
    _rn = RENAMES.get(_srv, {})
    for _fn_name in _fns:
        _fn = getattr(_mod, _fn_name, None)
        if _fn is None:
            continue
        _gw_name = _rn.get(_fn_name, _fn_name)
        mcp.tool(name=_gw_name)(_fn)
        setattr(_THIS, _gw_name, _fn)  # expose as module attribute for tests + direct calls


if __name__ == "__main__":
    mcp.run()
