"""cve-search: import, tool presence, local-only operations (no NVD network calls)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from helpers import load_server


@pytest.fixture(scope="module")
def cve():
    return load_server("cve-search")


@pytest.fixture(scope="module")
def seeded_db(cve, tmp_path_factory):
    """Seed a minimal SQLite DB with 3 fake CVEs for dispatch tests."""
    import importlib
    db_path = tmp_path_factory.mktemp("cve") / "cve.db"
    # Monkey-patch _DB_PATH so the server uses the temp DB
    mod = cve
    mod._DB_PATH = db_path  # type: ignore[attr-defined]

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cves (
            cve_id TEXT PRIMARY KEY, description TEXT, cvss_score REAL,
            cvss_severity TEXT, attack_vector TEXT, attack_complexity TEXT,
            privileges_required TEXT, user_interaction TEXT,
            confidentiality TEXT, integrity TEXT, availability TEXT,
            cwe_ids TEXT, affected_cpes TEXT, published_date TEXT,
            modified_date TEXT, references_json TEXT, has_poc INTEGER DEFAULT 0,
            cached_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_cvss ON cves(cvss_score DESC);
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    conn.executemany("INSERT OR REPLACE INTO cves VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("CVE-2024-00001", "SQL injection in nextjs app allows RCE", 9.8, "CRITICAL",
         "NETWORK", "LOW", "NONE", "NONE", "HIGH", "HIGH", "HIGH",
         '["CWE-89"]', '["cpe:2.3:a:vercel:next.js:14.0:*"]',
         "2024-01-15T00:00:00.000", "2024-01-16T00:00:00.000",
         '[{"url":"https://github.com/poc/cve","tags":["Exploit"]}]', 1,
         datetime.now(timezone.utc).isoformat()),
        ("CVE-2024-00002", "XSS in prisma client logging output", 6.1, "MEDIUM",
         "NETWORK", "LOW", "NONE", "REQUIRED", "LOW", "LOW", "NONE",
         '["CWE-79"]', '["cpe:2.3:a:prisma:prisma:5.0:*"]',
         "2024-02-10T00:00:00.000", "2024-02-11T00:00:00.000",
         "[]", 0,
         datetime.now(timezone.utc).isoformat()),
        ("CVE-2023-00003", "Local privilege escalation in redis", 7.8, "HIGH",
         "LOCAL", "LOW", "LOW", "NONE", "HIGH", "HIGH", "HIGH",
         '["CWE-287"]', '["cpe:2.3:a:redis:redis:7.0:*"]',
         "2023-06-01T00:00:00.000", "2023-06-02T00:00:00.000",
         "[]", 0,
         datetime.now(timezone.utc).isoformat()),
    ])
    conn.commit()
    conn.close()
    return db_path


# ── Structure ──────────────────────────────────────────────────────────────────

def test_imports_cleanly(cve):
    from mcp.server.fastmcp import FastMCP
    assert isinstance(cve.mcp, FastMCP)


def test_tools_present(cve):
    for name in ["cve_status", "search_cve", "get_cve", "stack_audit", "web_attack_surface", "sync"]:
        assert hasattr(cve, name) and callable(getattr(cve, name))


# ── Dispatch (local DB, no network) ───────────────────────────────────────────

def test_cve_status_returns_json(cve, seeded_db):
    result = json.loads(cve.cve_status())
    assert "total_cached" in result
    assert result["total_cached"] >= 3


def test_search_cve_finds_nextjs(cve, seeded_db):
    result = json.loads(cve.search_cve("nextjs", min_cvss=7.0))
    assert result["count"] >= 1
    assert any("CVE-2024-00001" == r["cve_id"] for r in result["results"])


def test_search_cve_network_filter(cve, seeded_db):
    result = json.loads(cve.search_cve("redis", min_cvss=5.0, attack_vector="NETWORK"))
    # CVE-2023-00003 is LOCAL — should be excluded
    assert all(r["attack_vector"] == "NETWORK" for r in result["results"])


def test_get_cve_cached(cve, seeded_db):
    result = json.loads(cve.get_cve("CVE-2024-00001"))
    assert result["cve_id"] == "CVE-2024-00001"
    assert result["cvss_score"] == 9.8
    assert "CWE-89" in result["cwe"]
    assert result["has_poc"] is True


def test_web_attack_surface_filters(cve, seeded_db):
    result = json.loads(cve.web_attack_surface(min_cvss=7.0, year_from=2024))
    # CVE-2024-00001: NETWORK/LOW/NONE/NONE — should appear
    # CVE-2023-00003: LOCAL — should not appear
    ids = [r["cve_id"] for r in result["results"]]
    assert "CVE-2024-00001" in ids
    assert "CVE-2023-00003" not in ids


def test_stack_audit_local(cve, seeded_db):
    result = json.loads(cve.stack_audit(["nextjs", "prisma"], min_cvss=5.0, only_network=True))
    assert "by_technology" in result
    assert "summary" in result
    assert result["summary"]["total_critical"] >= 1
