# tests/test_gateway.py
"""Gateway: tools registered, renames correct, dispatch works end-to-end."""
from __future__ import annotations

import json

import pytest
from mcp.server.fastmcp import FastMCP

from helpers import load_server

RENAMED = [
    "ss_query", "sql_query",
    "git_status", "git_diff",
    "scan_status",
    "env_diff", "env_check",
]
# Bare conflicting names must NOT exist in the gateway
BARE_CONFLICTS = ["query", "status", "diff"]


@pytest.fixture(scope="module")
def gw():
    return load_server("gateway")


# ── Structure ──────────────────────────────────────────────────────────────────

def test_gateway_is_fastmcp(gw):
    assert isinstance(gw.mcp, FastMCP)


def test_renamed_tools_present(gw):
    for name in RENAMED:
        assert hasattr(gw, name) and callable(getattr(gw, name)), (
            f"missing renamed tool: '{name}'"
        )


def test_bare_conflicts_absent(gw):
    for name in BARE_CONFLICTS:
        assert not hasattr(gw, name), (
            f"ambiguous bare name '{name}' leaked into gateway module"
        )


def test_non_conflicting_tools_present(gw):
    for name in ["log", "multi_edit", "run", "parse", "apply",
                 "index", "scan_staged", "required"]:
        assert hasattr(gw, name) and callable(getattr(gw, name)), (
            f"missing non-conflicting tool: '{name}'"
        )


# ── Dispatch ───────────────────────────────────────────────────────────────────

def test_dispatch_env_check(gw, tmp_path):
    (tmp_path / ".env").write_text("FOO=bar\n")
    (tmp_path / "app.ts").write_text("process.env.FOO\n")
    data = json.loads(gw.env_check(str(tmp_path)))
    assert "summary" in data
    assert data["summary"]["severity"] == "ok"


def test_dispatch_env_diff(gw, tmp_path):
    (tmp_path / ".env").write_text("A=1\nB=2\n")
    (tmp_path / ".env.example").write_text("A=\n")
    data = json.loads(gw.env_diff(str(tmp_path)))
    assert "B" in data["only_in_env"]


def test_dispatch_scan_status(gw):
    data = json.loads(gw.scan_status())
    assert data["mode"] in ("gitleaks", "builtin")


def test_dispatch_git_status(gw):
    repo = str(__import__("pathlib").Path(__file__).parent.parent)
    result = gw.git_status(repo)
    data = json.loads(result)
    assert "branch" in data or "error" in data
