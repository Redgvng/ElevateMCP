#!/usr/bin/env python3
"""MCP server: env-doctor — detect missing env vars before `npm run dev` crashes.

Compares:
- `.env` (local)
- `.env.example` (template, optional)
- Code references: `process.env.X`, `import.meta.env.X` (TS/JS), `os.getenv("X")` / `os.environ["X"]` (Py)

Tools:
- check(project) — full diff: missing in .env, unused in .env, undocumented in .env.example
- diff(project) — short diff .env vs .env.example
- required(project) — list of all env vars referenced in code
- template_gen(project) — generate a .env.example from code references

All read-only. Never prints values.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("env-doctor")

CODE_EXTS = {".ts", ".tsx", ".js", ".mjs", ".cjs", ".jsx", ".py"}
SKIP_DIRS = {"node_modules", ".next", "dist", "build", ".git", "coverage", "__pycache__", ".venv", "venv"}

# Patterns to detect env var usage in code
PATTERNS = [
    # process.env.FOO  /  process.env["FOO"]
    re.compile(r"process\.env\.([A-Z_][A-Z0-9_]*)"),
    re.compile(r"process\.env\[['\"]([A-Z_][A-Z0-9_]*)['\"]"),
    # import.meta.env.FOO (Vite / Astro)
    re.compile(r"import\.meta\.env\.([A-Z_][A-Z0-9_]*)"),
    # Python: os.getenv("FOO") / os.environ["FOO"] / os.environ.get("FOO")
    re.compile(r"os\.getenv\s*\(\s*['\"]([A-Z_][A-Z0-9_]*)['\"]"),
    re.compile(r"os\.environ\s*\[\s*['\"]([A-Z_][A-Z0-9_]*)['\"]"),
    re.compile(r"os\.environ\.get\s*\(\s*['\"]([A-Z_][A-Z0-9_]*)['\"]"),
]


def _parse_env_file(path: Path) -> set[str]:
    """Return set of var names declared (KEY=...) in a dotenv file."""
    out: set[str] = set()
    if not path.exists():
        return out
    try:
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
            if m:
                out.add(m.group(1))
    except Exception:
        pass
    return out


def _scan_code(root: Path) -> dict[str, list[tuple[str, int]]]:
    """Walk root and return {VAR_NAME: [(file_rel, line_no), ...]}."""
    refs: dict[str, list[tuple[str, int]]] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in CODE_EXTS:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            for pat in PATTERNS:
                for m in pat.finditer(line):
                    var = m.group(1)
                    refs.setdefault(var, []).append((str(path.relative_to(root)), line_no))
    return refs


@mcp.tool()
def check(project: str = "") -> str:
    """Full env audit for a project.

    Args:
        project: Path to project root (default: cwd).

    Returns:
        JSON: {project, env_count, example_count, used_count, missing_in_env: [...], unused_in_env: [...], undocumented: [...], summary}
    """
    root = Path(project) if project else Path(os.getcwd())
    if not root.exists():
        return json.dumps({"error": f"project not found: {root}"})

    env_vars = _parse_env_file(root / ".env")
    example_vars = _parse_env_file(root / ".env.example")
    used = _scan_code(root)
    used_names = set(used.keys())

    # Missing in .env: code references a var that's not in .env (and we have a .env file)
    missing_in_env = sorted(used_names - env_vars) if env_vars else sorted(used_names - example_vars)

    # Unused in .env: declared in .env but never referenced in code
    unused_in_env = sorted((env_vars or example_vars) - used_names)

    # Undocumented: in .env but not in .env.example
    undocumented = sorted(env_vars - example_vars) if env_vars and example_vars else []

    return json.dumps({
        "project": str(root),
        "env_count": len(env_vars),
        "example_count": len(example_vars),
        "used_count": len(used_names),
        "missing_in_env": missing_in_env[:50],
        "unused_in_env": unused_in_env[:50],
        "undocumented_in_example": undocumented[:50],
        "summary": {
            "missing": len(missing_in_env),
            "unused": len(unused_in_env),
            "undocumented": len(undocumented),
            "severity": "critical" if missing_in_env else ("warning" if undocumented or unused_in_env else "ok"),
        },
    }, indent=2)


@mcp.tool()
def diff(project: str = "") -> str:
    """Short diff: .env vs .env.example.

    Args:
        project: Path to project root.

    Returns:
        JSON: {only_in_env: [...], only_in_example: [...], common_count}
    """
    root = Path(project) if project else Path(os.getcwd())
    env_vars = _parse_env_file(root / ".env")
    example_vars = _parse_env_file(root / ".env.example")
    return json.dumps({
        "project": str(root),
        "only_in_env": sorted(env_vars - example_vars),
        "only_in_example": sorted(example_vars - env_vars),
        "common_count": len(env_vars & example_vars),
    }, indent=2)


@mcp.tool()
def required(project: str = "") -> str:
    """List all env vars referenced in code, with file:line of first occurrence.

    Args:
        project: Path to project root.

    Returns:
        JSON: {project, vars: [{name, count, first_seen: 'file:line'}], total}
    """
    root = Path(project) if project else Path(os.getcwd())
    used = _scan_code(root)
    out = []
    for name in sorted(used.keys()):
        refs = used[name]
        f, l = refs[0]
        out.append({"name": name, "count": len(refs), "first_seen": f"{f}:{l}"})
    return json.dumps({"project": str(root), "total": len(out), "vars": out}, indent=2)


@mcp.tool()
def template_gen(project: str = "") -> str:
    """Generate a .env.example template from code references.

    Args:
        project: Path to project root.

    Returns:
        Text: dotenv-style template with each referenced var as `VAR_NAME=`, sorted.
    """
    root = Path(project) if project else Path(os.getcwd())
    used = _scan_code(root)
    if not used:
        return "# No env var references found in code"
    lines = [f"# Generated by env-doctor — {len(used)} variables", ""]
    for name in sorted(used.keys()):
        refs = used[name]
        first = refs[0]
        lines.append(f"# Used in {first[0]}:{first[1]} ({len(refs)} reference{'s' if len(refs) > 1 else ''})")
        lines.append(f"{name}=")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
