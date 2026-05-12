#!/usr/bin/env python3
"""MCP server: structured git operations.

Wraps git CLI calls and returns structured output (not raw text)
so the agent doesn't waste tokens parsing.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("git")


def _run(args: list[str], cwd: str, timeout: int = 30) -> tuple[int, str, str]:
    p = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout
    )
    return p.returncode, p.stdout, p.stderr


def _resolve_repo(repo: str) -> str:
    p = Path(repo).expanduser().resolve()
    if not p.is_dir():
        raise ValueError(f"not a directory: {repo}")
    rc, _, _ = subprocess.run(
        ["git", "rev-parse", "--git-dir"], cwd=str(p), capture_output=True, text=True
    ).returncode, "", ""
    return str(p)


@mcp.tool()
def log(repo: str, ref: str = "HEAD", limit: int = 20, path: str | None = None) -> str:
    """Get structured commit log.

    Args:
        repo: Repository path.
        ref: Branch/tag/commit to start from. Default HEAD.
        limit: Max number of commits. Default 20.
        path: Optional file path to filter commits that touched it.

    Returns:
        JSON list: [{sha, short, author, email, date, subject, body, files_changed}]
    """
    repo = _resolve_repo(repo)
    fmt = "%H%x1f%h%x1f%an%x1f%ae%x1f%aI%x1f%s%x1f%b%x1e"
    args = ["log", f"--format={fmt}", "--name-only", f"-n{limit}", ref]
    if path:
        args += ["--", path]
    rc, out, err = _run(args, repo)
    if rc != 0:
        return json.dumps({"error": err.strip()})
    commits = []
    for block in out.split("\x1e"):
        block = block.strip("\n")
        if not block:
            continue
        parts = block.split("\n", 1)
        head = parts[0]
        files = parts[1].strip().split("\n") if len(parts) > 1 and parts[1].strip() else []
        files = [f for f in files if f]
        h = head.split("\x1f")
        if len(h) < 7:
            continue
        commits.append({
            "sha": h[0],
            "short": h[1],
            "author": h[2],
            "email": h[3],
            "date": h[4],
            "subject": h[5],
            "body": h[6].strip(),
            "files_changed": files,
        })
    return json.dumps(commits, ensure_ascii=False, indent=2)


@mcp.tool()
def diff(repo: str, from_ref: str, to_ref: str = "HEAD", files: list[str] | None = None, stat: bool = False) -> str:
    """Get diff between two refs.

    Args:
        repo: Repository path.
        from_ref: Base ref.
        to_ref: Compared ref. Default HEAD.
        files: Optional list of paths to limit the diff.
        stat: If True, return summary stats (files + insertions/deletions) instead of full diff.

    Returns:
        Unified diff or stat summary.
    """
    repo = _resolve_repo(repo)
    args = ["diff"]
    if stat:
        args.append("--stat")
    args += [f"{from_ref}..{to_ref}"]
    if files:
        args += ["--", *files]
    rc, out, err = _run(args, repo, timeout=60)
    if rc != 0:
        return f"error: {err.strip()}"
    if len(out) > 50000:
        return out[:50000] + f"\n... ({len(out) - 50000} more chars truncated; pass `stat=True` for summary)"
    return out or "(no differences)"


@mcp.tool()
def blame(repo: str, file: str, line: int | None = None) -> str:
    """Show blame info for a file (or a single line).

    Args:
        repo: Repository path.
        file: File path (relative to repo root).
        line: Optional 1-based line number to blame just one line.

    Returns:
        JSON: list of {line, sha, author, date, content} or single object if line given.
    """
    repo = _resolve_repo(repo)
    args = ["blame", "--line-porcelain"]
    if line:
        args += ["-L", f"{line},{line}"]
    args += [file]
    rc, out, err = _run(args, repo, timeout=30)
    if rc != 0:
        return json.dumps({"error": err.strip()})
    entries = []
    cur: dict[str, Any] = {}
    n = 0
    for raw in out.splitlines():
        if raw.startswith("\t"):
            cur["content"] = raw[1:]
            entries.append(cur)
            cur = {}
            n += 1
            continue
        if not cur and len(raw.split()) >= 3 and len(raw.split()[0]) == 40:
            parts = raw.split()
            cur["sha"] = parts[0]
            cur["line"] = int(parts[2])
        elif raw.startswith("author "):
            cur["author"] = raw[7:]
        elif raw.startswith("author-time "):
            cur["timestamp"] = int(raw[12:])
    if line and entries:
        return json.dumps(entries[0], ensure_ascii=False, indent=2)
    return json.dumps(entries[:200], ensure_ascii=False, indent=2)


@mcp.tool()
def find_commits_touching(repo: str, symbol: str, limit: int = 30) -> str:
    """Find commits that added/removed a string (uses git log -S).

    Args:
        repo: Repository path.
        symbol: Exact string to search in patches (function name, variable, magic value...).
        limit: Max commits.

    Returns:
        JSON: [{sha, short, date, author, subject}]
    """
    repo = _resolve_repo(repo)
    fmt = "%H%x1f%h%x1f%aI%x1f%an%x1f%s"
    rc, out, err = _run(["log", f"--format={fmt}", f"-S{symbol}", f"-n{limit}"], repo, timeout=60)
    if rc != 0:
        return json.dumps({"error": err.strip()})
    commits = []
    for line in out.splitlines():
        h = line.split("\x1f")
        if len(h) < 5:
            continue
        commits.append({
            "sha": h[0], "short": h[1], "date": h[2], "author": h[3], "subject": h[4],
        })
    return json.dumps(commits, ensure_ascii=False, indent=2)


@mcp.tool()
def branches(repo: str, include_remote: bool = False) -> str:
    """List branches with current marker.

    Args:
        repo: Repository path.
        include_remote: Include remote-tracking branches.

    Returns:
        JSON: {current: str, local: [...], remote: [...]}
    """
    repo = _resolve_repo(repo)
    rc, out, _ = _run(["branch", "--format=%(refname:short)"], repo)
    local = [b.strip() for b in out.splitlines() if b.strip()]
    rc2, out2, _ = _run(["rev-parse", "--abbrev-ref", "HEAD"], repo)
    current = out2.strip() if rc2 == 0 else None
    remote = []
    if include_remote:
        rc3, out3, _ = _run(["branch", "-r", "--format=%(refname:short)"], repo)
        if rc3 == 0:
            remote = [b.strip() for b in out3.splitlines() if b.strip()]
    return json.dumps({"current": current, "local": local, "remote": remote}, indent=2)


@mcp.tool()
def status(repo: str) -> str:
    """Show working-tree status (parsed porcelain).

    Args:
        repo: Repository path.

    Returns:
        JSON: {branch, ahead, behind, staged: [...], unstaged: [...], untracked: [...]}
    """
    repo = _resolve_repo(repo)
    rc, out, err = _run(["status", "--porcelain=v2", "--branch"], repo)
    if rc != 0:
        return json.dumps({"error": err.strip()})
    info: dict[str, Any] = {"branch": None, "ahead": 0, "behind": 0,
                            "staged": [], "unstaged": [], "untracked": []}
    for raw in out.splitlines():
        if raw.startswith("# branch.head"):
            info["branch"] = raw.split()[-1]
        elif raw.startswith("# branch.ab"):
            parts = raw.split()
            info["ahead"] = int(parts[2].lstrip("+"))
            info["behind"] = int(parts[3].lstrip("-"))
        elif raw.startswith("?"):
            info["untracked"].append(raw.split(maxsplit=1)[1])
        elif raw.startswith("1 ") or raw.startswith("2 "):
            parts = raw.split()
            xy = parts[1]
            path = raw.split(maxsplit=8)[-1]
            if xy[0] != ".":
                info["staged"].append({"status": xy[0], "path": path})
            if xy[1] != ".":
                info["unstaged"].append({"status": xy[1], "path": path})
    return json.dumps(info, ensure_ascii=False, indent=2)


@mcp.tool()
def show(repo: str, ref: str) -> str:
    """Show full info + diff for a commit.

    Args:
        repo: Repository path.
        ref: Commit SHA, tag, or branch.

    Returns:
        Commit message + author + diff. Truncated at 50 KB.
    """
    repo = _resolve_repo(repo)
    rc, out, err = _run(["show", "--stat", "--patch", ref], repo, timeout=60)
    if rc != 0:
        return f"error: {err.strip()}"
    if len(out) > 50000:
        out = out[:50000] + f"\n... ({len(out) - 50000} more chars truncated)"
    return out


if __name__ == "__main__":
    mcp.run()
