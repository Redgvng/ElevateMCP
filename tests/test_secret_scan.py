"""Unit tests for the secret-scan MCP server (builtin patterns, no gitleaks required)."""
from __future__ import annotations

import json

import pytest

from helpers import load_server

# NB: scan_file always uses _scan_text (builtin), even when gitleaks is present.
# Tests here are therefore deterministic regardless of env.


@pytest.fixture(scope="module")
def ss():
    return load_server("secret-scan")


# ── status ────────────────────────────────────────────────────────────────────

def test_status_returns_mode(ss):
    data = json.loads(ss.status())
    assert data["mode"] in ("gitleaks", "builtin")


def test_status_has_builtin_count(ss):
    data = json.loads(ss.status())
    assert data["builtin_patterns_count"] >= 14


# ── scan_file — clean ─────────────────────────────────────────────────────────

def test_scan_clean_file(ss, tmp_path):
    f = tmp_path / "clean.py"
    f.write_text("x = 1\nprint('hello world')\n")
    data = json.loads(ss.scan_file(str(f)))
    assert data["summary"]["total"] == 0
    assert data["findings"] == []


def test_scan_nonexistent_file(ss):
    data = json.loads(ss.scan_file("/nonexistent/path/file.py"))
    assert "error" in data


# ── scan_file — AWS key ───────────────────────────────────────────────────────

def test_scan_detects_aws_access_key(ss, tmp_path):
    f = tmp_path / "creds.py"
    # Standard AKIAIOSFODNN7EXAMPLE format: AKIA + 16 uppercase alnum
    f.write_text('AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n')
    data = json.loads(ss.scan_file(str(f)))
    assert data["summary"]["total"] >= 1
    rules = {finding["rule"] for finding in data["findings"]}
    assert "aws_access_key" in rules


def test_aws_key_is_masked(ss, tmp_path):
    f = tmp_path / "creds.py"
    raw = "AKIAIOSFODNN7EXAMPLE"
    f.write_text(f'KEY = "{raw}"\n')
    data = json.loads(ss.scan_file(str(f)))
    for finding in data["findings"]:
        assert raw not in finding.get("secret_masked", "")
        assert finding["secret_masked"].endswith(raw[-4:])


# ── scan_file — GitHub PAT ────────────────────────────────────────────────────

def test_scan_detects_github_pat(ss, tmp_path):
    f = tmp_path / "config.py"
    pat = "ghp_" + "A" * 36
    f.write_text(f'GITHUB_TOKEN = "{pat}"\n')
    data = json.loads(ss.scan_file(str(f)))
    assert data["summary"]["total"] >= 1
    rules = {finding["rule"] for finding in data["findings"]}
    assert "github_pat" in rules


# ── scan_file — PEM private key ───────────────────────────────────────────────

def test_scan_detects_pem_key(ss, tmp_path):
    f = tmp_path / "key.pem"
    f.write_text(
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA...\n"
        "-----END RSA PRIVATE KEY-----\n"
    )
    data = json.loads(ss.scan_file(str(f)))
    assert data["summary"]["total"] >= 1
    rules = {finding["rule"] for finding in data["findings"]}
    assert "private_key_pem" in rules


# ── scan_file — Stripe key ────────────────────────────────────────────────────

def test_scan_detects_stripe_live_key(ss, tmp_path):
    f = tmp_path / "payment.js"
    f.write_text('const stripe = Stripe("sk_live_AAAAAAAAAAAAAAAAAAAAAA");\n')
    data = json.loads(ss.scan_file(str(f)))
    assert data["summary"]["total"] >= 1


# ── scan_file — anthropic key ────────────────────────────────────────────────

def test_scan_detects_anthropic_key(ss, tmp_path):
    f = tmp_path / "client.py"
    key = "sk-ant-" + "A" * 45
    f.write_text(f'client = anthropic.Anthropic(api_key="{key}")\n')
    data = json.loads(ss.scan_file(str(f)))
    assert data["summary"]["total"] >= 1
    rules = {finding["rule"] for finding in data["findings"]}
    assert "anthropic_key" in rules


# ── scan_file — JWT ───────────────────────────────────────────────────────────

def test_scan_detects_jwt(ss, tmp_path):
    f = tmp_path / "auth.py"
    # Minimal valid JWT shape: eyJ... .eyJ... .<sig>
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyIjoiYWxpY2UifQ.SomeSignatureHereXXXXXX"
    f.write_text(f'TOKEN = "{jwt}"\n')
    data = json.loads(ss.scan_file(str(f)))
    assert data["summary"]["total"] >= 1
    rules = {finding["rule"] for finding in data["findings"]}
    assert "jwt" in rules


# ── add_pattern ───────────────────────────────────────────────────────────────

def test_add_pattern_ok(ss):
    data = json.loads(ss.add_pattern("test-token", r"\bTEST-[A-Z]{8}\b"))
    assert data["status"] == "ok"
    assert data["total_custom_patterns"] >= 1


def test_add_pattern_invalid_regex(ss):
    data = json.loads(ss.add_pattern("bad", r"[unclosed"))
    assert "error" in data


def test_custom_pattern_fires(ss, tmp_path):
    ss.add_pattern("internal-key", r"\bINTERNAL-[A-Z0-9]{8}\b")
    f = tmp_path / "internal.py"
    f.write_text('KEY = "INTERNAL-AAAAAAAA"\n')
    data = json.loads(ss.scan_file(str(f)))
    rules = {finding["rule"] for finding in data["findings"]}
    assert "internal-key" in rules
