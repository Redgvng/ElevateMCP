#!/usr/bin/env python3
"""MCP server exposing multi-edit tools for CommandCode.

Tools:
- multi_edit: apply N edits to a single file atomically (all or nothing)
- multi_file_edit: apply edits across multiple files in one call

Both honor the same sensitive-path denylist as the PreToolUse hook so
that bypassing the native edit_file tool through MCP can't write to
secrets.
"""
from __future__ import annotations

import difflib
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("multiedit")

# Same denylist as ~/.commandcode/hooks/guard-write.py — defense in depth.
SENSITIVE_PATTERNS = [
    "/.ssh/", "/.aws/", "/.gnupg/", "/etc/",
    "/.commandcode/auth.json", "/.npmrc", "/.pypirc",
]
SENSITIVE_FILENAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519"}


def _check_path(path: str) -> str | None:
    """Return an error message if the path is sensitive, else None."""
    abspath = os.path.abspath(os.path.expanduser(path))
    base = os.path.basename(abspath)
    if base in SENSITIVE_FILENAMES:
        return f"refused: '{base}' is in the sensitive-filenames denylist"
    for pat in SENSITIVE_PATTERNS:
        if pat in abspath:
            return f"refused: path matches sensitive pattern '{pat}'"
    return None


def _apply_edits(text: str, edits: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """Apply edits sequentially. Returns (new_text, per_edit_report).

    Raises ValueError on the first failure (atomic semantics).
    """
    out = text
    report: list[str] = []
    for i, e in enumerate(edits, 1):
        old = e.get("old_string", e.get("oldString"))
        new = e.get("new_string", e.get("newString"))
        replace_all = bool(e.get("replace_all", e.get("replaceAll", False)))
        if not isinstance(old, str) or not isinstance(new, str):
            raise ValueError(f"edit #{i}: 'old_string' and 'new_string' must be strings")
        if old == new:
            raise ValueError(f"edit #{i}: 'old_string' equals 'new_string' (no-op)")
        if old == "":
            raise ValueError(f"edit #{i}: 'old_string' is empty (use write_file for creation)")

        count = out.count(old)
        if count == 0:
            raise ValueError(f"edit #{i}: 'old_string' not found in file")
        if count > 1 and not replace_all:
            raise ValueError(
                f"edit #{i}: 'old_string' matches {count} locations; "
                f"set replace_all=true or add more context to disambiguate"
            )
        if replace_all:
            out = out.replace(old, new)
            report.append(f"edit #{i}: replaced {count} occurrence(s)")
        else:
            out = out.replace(old, new, 1)
            report.append(f"edit #{i}: replaced 1 occurrence")
    return out, report


def _diff(before: str, after: str, path: str) -> str:
    diff = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=2,
    )
    out = "".join(diff)
    if len(out) > 4000:
        out = out[:4000] + f"\n... ({len(out) - 4000} more chars truncated)"
    return out


@mcp.tool()
def multi_edit(file_path: str, edits: list[dict[str, Any]]) -> str:
    """Apply multiple edits to a single file atomically.

    Each edit is {old_string, new_string, replace_all?}. Edits are applied in
    order; later edits operate on the result of earlier ones. If any edit
    fails (string not found, ambiguous match without replace_all, no-op), the
    whole operation aborts and the file is not modified.

    Use this instead of calling edit_file N times when you have multiple
    related changes to the same file — saves N-1 round-trips and guarantees
    atomicity.

    Args:
        file_path: Absolute path to the file to edit.
        edits: List of edits. Each item: {old_string: str, new_string: str, replace_all?: bool}.

    Returns:
        Per-edit report + unified diff of the cumulative change.
    """
    if not edits:
        return "error: edits list is empty"
    if not isinstance(edits, list):
        return f"error: 'edits' must be a list, got {type(edits).__name__}"

    err = _check_path(file_path)
    if err:
        return f"error: {err}"

    p = Path(file_path)
    if not p.is_absolute():
        return f"error: file_path must be absolute, got '{file_path}'"
    if not p.exists():
        return f"error: file does not exist: {file_path}"
    if not p.is_file():
        return f"error: not a regular file: {file_path}"

    try:
        before = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"error: file is not valid UTF-8: {file_path}"

    try:
        after, report = _apply_edits(before, edits)
    except ValueError as e:
        return f"error (atomic abort, file unchanged): {e}"

    if after == before:
        return "no-op: edits produced no net change"

    p.write_text(after, encoding="utf-8")
    diff = _diff(before, after, str(p))
    return f"OK — {len(edits)} edit(s) applied to {file_path}\n\n" + "\n".join(report) + "\n\n--- diff ---\n" + diff


@mcp.tool()
def multi_file_edit(operations: list[dict[str, Any]]) -> str:
    """Apply edits across multiple files in one call (atomic per-file, sequential across files).

    Each operation is {file_path: str, edits: [{old_string, new_string, replace_all?}]}.
    For each operation, the same atomic semantics as multi_edit apply. If a later
    file fails, earlier files have already been written (NOT cross-file atomic).

    Use this for cross-file refactors (rename a symbol across N files, etc).

    Args:
        operations: List of {file_path, edits} objects.

    Returns:
        Per-file report.
    """
    if not isinstance(operations, list) or not operations:
        return "error: 'operations' must be a non-empty list"

    results = []
    for i, op in enumerate(operations, 1):
        fp = op.get("file_path") or op.get("filePath")
        edits = op.get("edits", [])
        if not isinstance(fp, str) or not edits:
            results.append(f"op #{i}: skipped (missing file_path or edits)")
            continue
        outcome = multi_edit(fp, edits)
        results.append(f"op #{i} ({fp}):\n{outcome}")
        if outcome.startswith("error"):
            results.append(f"\nABORTED at op #{i}; remaining {len(operations) - i} operations not attempted")
            break
    return "\n\n".join(results)


if __name__ == "__main__":
    mcp.run()
