"""Verify all 9 MCP servers + gateway can be imported without errors."""
from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP

from helpers import load_server

ALL_SERVERS = [
    "multiedit",
    "semantic-search",
    "git",
    "test-runner",
    "sql",
    "diff-apply",
    "browser-inspect",
    "secret-scan",
    "env-doctor",
    "cve-search",
    "gateway",
]

# These need optional deps (playwright) — skip if not installed
OPTIONAL_DEP_SERVERS = {"browser-inspect"}

EXPECTED_TOOLS = {
    "multiedit": {"multi_edit", "multi_file_edit"},
    "semantic-search": {"index", "query", "list_indexes"},
    "git": {"log", "diff", "blame", "find_commits_touching", "branches", "status", "show"},
    "test-runner": {"run", "list_tests"},
    "sql": {"query", "tables", "describe", "explain"},
    "diff-apply": {"parse", "dry_run", "apply"},
    "browser-inspect": {"screenshot", "dom", "console", "network", "eval_js", "click_and_capture"},
    "secret-scan": {"status", "scan_staged", "scan_diff", "scan_history", "scan_file", "add_pattern"},
    "env-doctor": {"check", "diff", "required", "template_gen"},
    "cve-search": {"cve_status", "search_cve", "get_cve", "stack_audit", "web_attack_surface", "sync"},
    "gateway": {
        # Renamed tools
        "ss_query", "sql_query",
        "git_status", "git_diff",
        "scan_status",
        "env_diff", "env_check",
        # Non-conflicting sample
        "log", "multi_edit", "run", "parse", "apply",
        "index", "scan_staged", "required",
        "cve_status", "search_cve", "stack_audit",
    },
}


@pytest.mark.parametrize("name", ALL_SERVERS)
def test_server_imports_cleanly(name):
    try:
        mod = load_server(name)
    except ImportError as exc:
        if name in OPTIONAL_DEP_SERVERS:
            pytest.skip(f"optional dep missing: {exc}")
        raise
    assert isinstance(mod.mcp, FastMCP), f"{name}: 'mcp' is not a FastMCP instance"


@pytest.mark.parametrize("name,tools", EXPECTED_TOOLS.items())
def test_server_exports_tool_functions(name, tools):
    try:
        mod = load_server(name)
    except ImportError as exc:
        if name in OPTIONAL_DEP_SERVERS:
            pytest.skip(f"optional dep missing: {exc}")
        raise
    for fn_name in tools:
        assert hasattr(mod, fn_name) and callable(getattr(mod, fn_name)), (
            f"{name}: missing tool function '{fn_name}'"
        )
