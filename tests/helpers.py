"""Shared helper: load a standalone server.py by name."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SERVERS_DIR = Path(__file__).parent.parent / "mcp-servers"


def load_server(name: str):
    """Return the module for mcp-servers/<name>/server.py.

    Uses sys.modules as a cache so repeated calls are cheap.
    Raises ImportError for servers with uninstalled optional deps.
    """
    mod_key = f"_mcp_test_{name.replace('-', '_')}"
    if mod_key in sys.modules:
        return sys.modules[mod_key]
    path = SERVERS_DIR / name / "server.py"
    spec = importlib.util.spec_from_file_location(mod_key, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_key] = mod
    spec.loader.exec_module(mod)
    return mod
