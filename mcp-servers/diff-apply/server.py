#!/usr/bin/env python3
"""MCP server: apply unified diffs (LLM-generated patches) to a working tree.

Pure Python, no `patch` binary needed. Supports dry_run and conflict detection.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("diff-apply")

# Same denylist as the global write-guard for defense in depth
SENSITIVE_PATTERNS = ["/.ssh/", "/.aws/", "/.gnupg/", "/etc/", "/.commandcode/auth.json", "/.npmrc", "/.pypirc"]
SENSITIVE_FILENAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519"}


def _check_path(path: str) -> str | None:
    import os
    abspath = os.path.abspath(os.path.expanduser(path))
    base = os.path.basename(abspath)
    if base in SENSITIVE_FILENAMES:
        return f"refused: '{base}' is in the sensitive-filenames denylist"
    for pat in SENSITIVE_PATTERNS:
        if pat in abspath:
            return f"refused: path matches sensitive pattern '{pat}'"
    return None


HUNK_HEADER = re.compile(r"^@@ -(?P<a_start>\d+)(?:,(?P<a_len>\d+))? \+(?P<b_start>\d+)(?:,(?P<b_len>\d+))? @@")


def _parse_diff(diff: str) -> list[dict[str, Any]]:
    """Parse a unified diff into a list of file patches.

    Each patch: {old_file, new_file, hunks: [{a_start, b_start, lines: [(' '|'+'|'-', text)]}]}
    """
    patches: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    cur_hunk: dict[str, Any] | None = None
    lines = diff.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("diff --git "):
            if cur:
                if cur_hunk:
                    cur["hunks"].append(cur_hunk)
                    cur_hunk = None
                patches.append(cur)
            cur = {"old_file": None, "new_file": None, "hunks": []}
        elif ln.startswith("--- "):
            if cur is None:
                cur = {"old_file": None, "new_file": None, "hunks": []}
            cur["old_file"] = ln[4:].lstrip("a/").strip()
            if cur["old_file"] == "/dev/null":
                cur["old_file"] = None
        elif ln.startswith("+++ "):
            if cur is None:
                cur = {"old_file": None, "new_file": None, "hunks": []}
            cur["new_file"] = ln[4:].lstrip("b/").strip()
            if cur["new_file"] == "/dev/null":
                cur["new_file"] = None
        elif ln.startswith("@@"):
            m = HUNK_HEADER.match(ln)
            if not m:
                i += 1
                continue
            if cur is None:
                cur = {"old_file": None, "new_file": None, "hunks": []}
            if cur_hunk:
                cur["hunks"].append(cur_hunk)
            cur_hunk = {
                "a_start": int(m.group("a_start")),
                "a_len": int(m.group("a_len") or 1),
                "b_start": int(m.group("b_start")),
                "b_len": int(m.group("b_len") or 1),
                "lines": [],
            }
        elif cur_hunk is not None and ln and ln[0] in (" ", "+", "-"):
            cur_hunk["lines"].append((ln[0], ln[1:]))
        elif cur_hunk is not None and ln.startswith("\\"):
            # "\ No newline at end of file" — ignore
            pass
        i += 1
    if cur_hunk and cur is not None:
        cur["hunks"].append(cur_hunk)
    if cur:
        patches.append(cur)
    return patches


def _apply_hunk(file_lines: list[str], hunk: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Apply one hunk. Returns (new_file_lines, conflicts).

    The expected old context is matched against current file at a_start. If mismatch,
    we try to relocate within +/- 5 lines via simple search of the context block.
    """
    a_start = hunk["a_start"]
    expected_old: list[str] = [t for kind, t in hunk["lines"] if kind in (" ", "-")]
    new_lines: list[str] = [t for kind, t in hunk["lines"] if kind in (" ", "+")]

    # locate
    def matches_at(idx: int) -> bool:
        if idx < 0 or idx + len(expected_old) > len(file_lines):
            return False
        for j, want in enumerate(expected_old):
            if file_lines[idx + j] != want:
                return False
        return True

    base = a_start - 1  # convert to 0-based
    located = base if matches_at(base) else None
    if located is None:
        for delta in range(1, 50):
            for cand in (base - delta, base + delta):
                if matches_at(cand):
                    located = cand
                    break
            if located is not None:
                break
    if located is None:
        return file_lines, [f"hunk @@ -{a_start} not found within ±50 lines"]

    new_file = file_lines[:located] + new_lines + file_lines[located + len(expected_old):]
    return new_file, []


def _apply_patch(patch: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    target_rel = patch["new_file"] or patch["old_file"]
    if not target_rel:
        return {"file": None, "status": "skipped", "reason": "no target file"}
    target = base_dir / target_rel
    err = _check_path(str(target))
    if err:
        return {"file": target_rel, "status": "refused", "reason": err}

    # creation
    if patch["old_file"] is None and patch["new_file"]:
        if target.exists():
            return {"file": target_rel, "status": "conflict", "reason": "file exists, expected creation"}
        body_lines: list[str] = []
        for h in patch["hunks"]:
            body_lines += [t for kind, t in h["lines"] if kind in (" ", "+")]
        return {"file": target_rel, "status": "create", "new_content": "\n".join(body_lines) + "\n"}

    # deletion
    if patch["new_file"] is None and patch["old_file"]:
        if not target.exists():
            return {"file": target_rel, "status": "skipped", "reason": "already absent"}
        return {"file": target_rel, "status": "delete"}

    # modification
    if not target.exists():
        return {"file": target_rel, "status": "conflict", "reason": "target file missing"}
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"file": target_rel, "status": "conflict", "reason": "not utf-8"}

    file_lines = content.splitlines()
    conflicts: list[str] = []
    for h in patch["hunks"]:
        file_lines, hc = _apply_hunk(file_lines, h)
        conflicts += hc
    new_content = "\n".join(file_lines)
    if content.endswith("\n"):
        new_content += "\n"
    if conflicts:
        return {"file": target_rel, "status": "conflict", "reason": "; ".join(conflicts)}
    return {"file": target_rel, "status": "modify", "new_content": new_content}


@mcp.tool()
def parse(diff: str) -> str:
    """Parse a unified diff and report what files/hunks it touches (no apply).

    Args:
        diff: Unified diff text.

    Returns:
        JSON: [{file, hunks: int, lines_added, lines_removed, op}] where op is create/delete/modify.
    """
    try:
        patches = _parse_diff(diff)
    except Exception as e:
        return json.dumps({"error": str(e)})
    out = []
    for p in patches:
        added = sum(1 for h in p["hunks"] for k, _ in h["lines"] if k == "+")
        removed = sum(1 for h in p["hunks"] for k, _ in h["lines"] if k == "-")
        if p["old_file"] is None:
            op = "create"
        elif p["new_file"] is None:
            op = "delete"
        else:
            op = "modify"
        out.append({
            "file": p["new_file"] or p["old_file"],
            "op": op,
            "hunks": len(p["hunks"]),
            "lines_added": added,
            "lines_removed": removed,
        })
    return json.dumps(out, ensure_ascii=False, indent=2)


@mcp.tool()
def dry_run(diff: str, base_dir: str) -> str:
    """Try applying a diff without writing. Returns per-file status (would-apply, conflict, refused).

    Args:
        diff: Unified diff text.
        base_dir: Repository root the diff is rooted at.

    Returns:
        JSON: [{file, status, reason?}]
    """
    base = Path(base_dir).expanduser().resolve()
    if not base.is_dir():
        return json.dumps({"error": f"not a directory: {base_dir}"})
    try:
        patches = _parse_diff(diff)
    except Exception as e:
        return json.dumps({"error": str(e)})
    results = []
    for p in patches:
        r = _apply_patch(p, base)
        # strip new_content for dry_run brevity
        r.pop("new_content", None)
        results.append(r)
    return json.dumps(results, ensure_ascii=False, indent=2)


@mcp.tool()
def apply(diff: str, base_dir: str, allow_conflicts: bool = False) -> str:
    """Apply a diff to a working tree. Atomic per-file; aborts globally on conflict
    unless allow_conflicts=True (in which case conflicting files are skipped).

    Args:
        diff: Unified diff text.
        base_dir: Repository root.
        allow_conflicts: If True, skip conflicting files instead of aborting.

    Returns:
        JSON: [{file, status, reason?}]
    """
    base = Path(base_dir).expanduser().resolve()
    if not base.is_dir():
        return json.dumps({"error": f"not a directory: {base_dir}"})
    try:
        patches = _parse_diff(diff)
    except Exception as e:
        return json.dumps({"error": str(e)})

    plans = [_apply_patch(p, base) for p in patches]

    # Pre-flight conflict check
    conflicting = [r for r in plans if r["status"] in ("conflict", "refused")]
    if conflicting and not allow_conflicts:
        # Strip new_content for brevity
        for r in plans:
            r.pop("new_content", None)
        return json.dumps({
            "aborted": True,
            "reason": "conflicts or refusals detected; pass allow_conflicts=true to proceed",
            "plan": plans,
        }, ensure_ascii=False, indent=2)

    applied = []
    for r in plans:
        if r["status"] == "modify" and "new_content" in r:
            (base / r["file"]).write_text(r.pop("new_content"), encoding="utf-8")
            applied.append({"file": r["file"], "status": "modified"})
        elif r["status"] == "create" and "new_content" in r:
            target = base / r["file"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(r.pop("new_content"), encoding="utf-8")
            applied.append({"file": r["file"], "status": "created"})
        elif r["status"] == "delete":
            try:
                (base / r["file"]).unlink()
                applied.append({"file": r["file"], "status": "deleted"})
            except OSError as e:
                applied.append({"file": r["file"], "status": "delete-failed", "reason": str(e)})
        else:
            r.pop("new_content", None)
            applied.append(r)
    return json.dumps({"aborted": False, "applied": applied}, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run()
