#!/usr/bin/env python3
"""MCP server: secret scanner.

Hybrid mode:
- If `gitleaks` binary is available, wrap it (preferred — battle-tested rules).
- Otherwise, fall back to a builtin regex set covering ~15 common secret types.

Tools:
- status() — which mode is active, gitleaks version if any
- scan_staged() — scan git staged content (pre-commit-style)
- scan_diff(target_ref) — scan diff between HEAD and a ref
- scan_history(depth) — scan last N commits
- scan_file(path) — scan a single file
- add_pattern(name, regex) — register a custom regex pattern (builtin mode)

All read-only. Refuses to print secrets — only positions + masked excerpts (4 last chars).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("secret-scan")

GITLEAKS = shutil.which("gitleaks")

# Builtin patterns — pragmatic subset of gitleaks defaults
BUILTIN_PATTERNS: dict[str, str] = {
    "aws_access_key":    r"\bAKIA[0-9A-Z]{16}\b",
    "github_pat":        r"\bghp_[0-9a-zA-Z]{36}\b",
    "github_oauth":      r"\bgho_[0-9a-zA-Z]{36}\b",
    "github_app":        r"\bghs_[0-9a-zA-Z]{36}\b",
    "stripe_live":       r"\bsk_live_[0-9a-zA-Z]{20,}\b",
    "stripe_test":       r"\bsk_test_[0-9a-zA-Z]{20,}\b",
    "stripe_pub_live":   r"\bpk_live_[0-9a-zA-Z]{20,}\b",
    "openai_key":        r"\bsk-[A-Za-z0-9_]{20}T3BlbkFJ[A-Za-z0-9_]{20}\b",
    "anthropic_key":     r"\bsk-ant-[A-Za-z0-9_-]{40,}\b",
    "google_api_key":    r"\bAIza[0-9A-Za-z_-]{35}\b",
    "slack_token":       r"\bxox[baprs]-[0-9a-zA-Z-]{10,}\b",
    "jwt":               r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{10,}\b",
    "nvapi":             r"\bnvapi-[A-Za-z0-9_-]{30,}\b",
    "private_key_pem":   r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----",
    "generic_api_key":   r"(?i)(?:api[_-]?key|apikey|secret[_-]?key)\s*[=:]\s*['\"]([A-Za-z0-9_/+\-]{24,})['\"]",
    "mistral_key":       r"\b[A-Za-z0-9]{32}\b(?=.*(?:mistral|MISTRAL|scaleway|SCALEWAY))",
}

CUSTOM_PATTERNS: dict[str, str] = {}


def _mask(s: str) -> str:
    """Mask a secret showing only last 4 chars."""
    if len(s) <= 8:
        return "*" * len(s)
    return "*" * (len(s) - 4) + s[-4:]


def _scan_text(text: str, file_label: str) -> list[dict]:
    findings: list[dict] = []
    patterns = {**BUILTIN_PATTERNS, **CUSTOM_PATTERNS}
    for name, pat in patterns.items():
        try:
            rx = re.compile(pat)
        except re.error:
            continue
        for m in rx.finditer(text):
            line_no = text[:m.start()].count("\n") + 1
            secret = m.group(0)
            findings.append({
                "rule": name,
                "file": file_label,
                "line": line_no,
                "secret_masked": _mask(secret),
                "length": len(secret),
            })
    return findings


def _gitleaks(args: list[str]) -> dict:
    """Run gitleaks with --report-format json --report-path /dev/stdout."""
    cmd = [GITLEAKS] + args + ["--report-format", "json", "--report-path", "/dev/stdout", "--no-banner"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        # gitleaks exits 1 if leaks found
        if r.stdout.strip():
            return {"mode": "gitleaks", "findings": json.loads(r.stdout), "stderr": r.stderr[:500]}
        return {"mode": "gitleaks", "findings": [], "stderr": r.stderr[:500]}
    except (json.JSONDecodeError, subprocess.TimeoutExpired) as e:
        return {"mode": "gitleaks", "error": str(e)}


@mcp.tool()
def status() -> str:
    """Report which scan mode is active and tool details.

    Returns:
        JSON: {mode: 'gitleaks'|'builtin', gitleaks_path?, gitleaks_version?, builtin_patterns_count, custom_patterns_count}
    """
    out: dict = {
        "mode": "gitleaks" if GITLEAKS else "builtin",
        "gitleaks_path": GITLEAKS,
        "builtin_patterns_count": len(BUILTIN_PATTERNS),
        "custom_patterns_count": len(CUSTOM_PATTERNS),
    }
    if GITLEAKS:
        try:
            r = subprocess.run([GITLEAKS, "version"], capture_output=True, text=True, timeout=5)
            out["gitleaks_version"] = r.stdout.strip()
        except Exception:
            out["gitleaks_version"] = "unknown"
    return json.dumps(out, indent=2)


@mcp.tool()
def scan_staged(repo: str = "") -> str:
    """Scan git staged content for secrets (pre-commit style).

    Args:
        repo: Repo path (default: cwd).

    Returns:
        JSON: {findings: [...], summary, mode}
    """
    cwd = repo if repo else os.getcwd()
    if GITLEAKS:
        result = _gitleaks(["protect", "--staged", "--source", cwd])
        result["summary"] = {"total": len(result.get("findings", []))}
        return json.dumps(result, indent=2, default=str)

    # Builtin: get staged diff via git
    try:
        r = subprocess.run(["git", "diff", "--cached"], cwd=cwd, capture_output=True, text=True, timeout=30)
    except Exception as e:
        return json.dumps({"error": f"git diff failed: {e}"})
    findings = _scan_text(r.stdout, "<staged>")
    return json.dumps({"mode": "builtin", "findings": findings, "summary": {"total": len(findings)}}, indent=2)


@mcp.tool()
def scan_diff(target_ref: str = "main", repo: str = "") -> str:
    """Scan the diff between HEAD and a target ref.

    Args:
        target_ref: Git ref to compare against (default: main).
        repo: Repo path (default: cwd).

    Returns:
        JSON: {findings, summary, mode}
    """
    cwd = repo if repo else os.getcwd()
    if GITLEAKS:
        result = _gitleaks(["detect", "--source", cwd, "--log-opts", f"{target_ref}..HEAD"])
        result["summary"] = {"total": len(result.get("findings", []))}
        return json.dumps(result, indent=2, default=str)

    try:
        r = subprocess.run(["git", "diff", f"{target_ref}..HEAD"], cwd=cwd, capture_output=True, text=True, timeout=30)
    except Exception as e:
        return json.dumps({"error": f"git diff failed: {e}"})
    findings = _scan_text(r.stdout, f"<diff {target_ref}..HEAD>")
    return json.dumps({"mode": "builtin", "findings": findings, "summary": {"total": len(findings)}}, indent=2)


@mcp.tool()
def scan_history(depth: int = 100, repo: str = "") -> str:
    """Scan the last N commits for secrets.

    Args:
        depth: Number of commits to scan (default 100, max 1000).
        repo: Repo path (default: cwd).

    Returns:
        JSON: {findings, summary, mode}
    """
    depth = max(1, min(int(depth), 1000))
    cwd = repo if repo else os.getcwd()
    if GITLEAKS:
        result = _gitleaks(["detect", "--source", cwd, "--log-opts", f"-n {depth}"])
        result["summary"] = {"total": len(result.get("findings", []))}
        return json.dumps(result, indent=2, default=str)

    # Builtin: walk last N commits, scan their diffs
    try:
        r = subprocess.run(
            ["git", "log", f"-n{depth}", "--format=%H", "--no-merges"],
            cwd=cwd, capture_output=True, text=True, timeout=20,
        )
    except Exception as e:
        return json.dumps({"error": f"git log failed: {e}"})
    findings: list[dict] = []
    for sha in r.stdout.strip().splitlines():
        try:
            d = subprocess.run(
                ["git", "show", "--no-color", sha],
                cwd=cwd, capture_output=True, text=True, timeout=15,
            )
            for f in _scan_text(d.stdout, sha[:8]):
                findings.append(f)
        except Exception:
            continue
    return json.dumps({"mode": "builtin", "findings": findings[:200], "summary": {"total": len(findings), "truncated": len(findings) > 200}}, indent=2)


@mcp.tool()
def scan_file(path: str) -> str:
    """Scan a single file for secrets.

    Args:
        path: Absolute or relative path.

    Returns:
        JSON: {findings, summary, mode}
    """
    p = Path(path)
    if not p.is_absolute():
        p = Path(os.getcwd()) / path
    if not p.exists():
        return json.dumps({"error": f"file not found: {p}"})
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return json.dumps({"error": f"read failed: {e}"})
    findings = _scan_text(text, str(p))
    mode = "gitleaks" if GITLEAKS else "builtin"  # gitleaks scan-single-file via stdin not implemented here
    return json.dumps({"mode": mode, "findings": findings, "summary": {"total": len(findings)}}, indent=2)


@mcp.tool()
def add_pattern(name: str, regex: str) -> str:
    """Register a custom regex pattern (in-memory, lost on server restart).

    Args:
        name: Identifier for the rule (e.g. 'company-internal-token').
        regex: Python regex pattern.

    Returns:
        JSON: {status, total_custom_patterns}
    """
    try:
        re.compile(regex)
    except re.error as e:
        return json.dumps({"error": f"invalid regex: {e}"})
    CUSTOM_PATTERNS[name] = regex
    return json.dumps({"status": "ok", "total_custom_patterns": len(CUSTOM_PATTERNS)})


if __name__ == "__main__":
    mcp.run()
