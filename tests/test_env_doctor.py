"""Unit tests for the env-doctor MCP server."""
from __future__ import annotations

import json

import pytest

from helpers import load_server


@pytest.fixture(scope="module")
def ed():
    return load_server("env-doctor")


@pytest.fixture
def project(tmp_path):
    """A minimal project: .env, .env.example, and a TypeScript file."""
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgres://localhost/test\n"
        "SECRET_KEY=abc123\n"
        "UNUSED_VAR=leftover\n"
    )
    (tmp_path / ".env.example").write_text(
        "DATABASE_URL=\n"
        "SECRET_KEY=\n"
    )
    (tmp_path / "app.ts").write_text(
        "const db = process.env.DATABASE_URL;\n"
        "const key = process.env.SECRET_KEY;\n"
        "const x = process.env.MISSING_VAR;\n"
    )
    return tmp_path


@pytest.fixture
def py_project(tmp_path):
    """Python project with os.getenv references."""
    (tmp_path / ".env").write_text("DB_URL=sqlite:///test.db\n")
    (tmp_path / "main.py").write_text(
        "import os\n"
        "db = os.getenv('DB_URL')\n"
        "secret = os.environ['MISSING_SECRET']\n"
    )
    return tmp_path


# ── check ─────────────────────────────────────────────────────────────────────

def test_check_returns_valid_json(ed, project):
    data = json.loads(ed.check(str(project)))
    assert "summary" in data


def test_check_counts_env_vars(ed, project):
    data = json.loads(ed.check(str(project)))
    assert data["env_count"] == 3
    assert data["example_count"] == 2


def test_check_detects_missing_in_env(ed, project):
    data = json.loads(ed.check(str(project)))
    assert "MISSING_VAR" in data["missing_in_env"]


def test_check_detects_unused_in_env(ed, project):
    data = json.loads(ed.check(str(project)))
    assert "UNUSED_VAR" in data["unused_in_env"]


def test_check_detects_undocumented(ed, project):
    data = json.loads(ed.check(str(project)))
    assert "UNUSED_VAR" in data["undocumented_in_example"]


def test_check_severity_critical_when_missing(ed, project):
    data = json.loads(ed.check(str(project)))
    assert data["summary"]["severity"] == "critical"


def test_check_severity_ok_when_clean(ed, tmp_path):
    (tmp_path / ".env").write_text("FOO=bar\n")
    (tmp_path / ".env.example").write_text("FOO=\n")
    (tmp_path / "app.js").write_text("process.env.FOO\n")
    data = json.loads(ed.check(str(tmp_path)))
    assert data["summary"]["severity"] == "ok"


def test_check_nonexistent_project(ed):
    data = json.loads(ed.check("/nonexistent/path/xyz123"))
    assert "error" in data


def test_check_python_patterns(ed, py_project):
    data = json.loads(ed.check(str(py_project)))
    assert "MISSING_SECRET" in data["missing_in_env"]


# ── diff ─────────────────────────────────────────────────────────────────────

def test_diff_only_in_env(ed, project):
    data = json.loads(ed.diff(str(project)))
    assert "UNUSED_VAR" in data["only_in_env"]


def test_diff_only_in_example(ed, tmp_path):
    (tmp_path / ".env").write_text("A=1\n")
    (tmp_path / ".env.example").write_text("A=\nB=\n")
    data = json.loads(ed.diff(str(tmp_path)))
    assert "B" in data["only_in_example"]


def test_diff_common_count(ed, project):
    data = json.loads(ed.diff(str(project)))
    assert data["common_count"] == 2


# ── required ─────────────────────────────────────────────────────────────────

def test_required_finds_ts_vars(ed, project):
    data = json.loads(ed.required(str(project)))
    names = {v["name"] for v in data["vars"]}
    assert {"DATABASE_URL", "SECRET_KEY", "MISSING_VAR"} <= names


def test_required_includes_location(ed, project):
    data = json.loads(ed.required(str(project)))
    for var in data["vars"]:
        assert "first_seen" in var
        assert ":" in var["first_seen"]


def test_required_empty_project(ed, tmp_path):
    data = json.loads(ed.required(str(tmp_path)))
    assert data["total"] == 0


# ── template_gen ──────────────────────────────────────────────────────────────

def test_template_gen_contains_vars(ed, project):
    result = ed.template_gen(str(project))
    assert "DATABASE_URL=" in result
    assert "SECRET_KEY=" in result
    assert "MISSING_VAR=" in result


def test_template_gen_has_comment_header(ed, project):
    result = ed.template_gen(str(project))
    assert result.startswith("#")


def test_template_gen_no_code(ed, tmp_path):
    result = ed.template_gen(str(tmp_path))
    assert "No env var references found" in result
