#!/usr/bin/env python3
"""MCP server: structured test runner across vitest/pytest/jest/bun test."""
from __future__ import annotations

import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("test-runner")


def _detect(directory: Path) -> str | None:
    pkg = directory / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text())
        except Exception:
            data = {}
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        if "vitest" in deps:
            return "vitest"
        if "jest" in deps or "@jest/core" in deps:
            return "jest"
        # bun test : peu de signal en deps, on regarde plutôt si bun.lock présent + pas de vitest/jest
        if (directory / "bun.lock").exists() or (directory / "bun.lockb").exists():
            return "bun"
    if (directory / "pyproject.toml").exists() or list(directory.glob("test_*.py")) or list(directory.glob("*_test.py")) or (directory / "pytest.ini").exists() or (directory / "tests").is_dir():
        return "pytest"
    return None


def _run(cmd: list[str], cwd: str, timeout: int = 600) -> tuple[int, str, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def _parse_junit(xml_text: str) -> list[dict[str, Any]]:
    """Parse a JUnit XML report into a list of test results."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out = []
    for tc in root.iter("testcase"):
        entry: dict[str, Any] = {
            "suite": tc.get("classname", ""),
            "name": tc.get("name", ""),
            "time": float(tc.get("time", 0) or 0),
            "status": "passed",
        }
        for child in tc:
            tag = child.tag.lower()
            if tag in ("failure", "error"):
                entry["status"] = "failed"
                entry["message"] = (child.get("message") or "").strip()
                entry["stack"] = (child.text or "").strip()[:2000]
            elif tag == "skipped":
                entry["status"] = "skipped"
                entry["message"] = (child.get("message") or "").strip()
        out.append(entry)
    return out


def _summary(results: list[dict[str, Any]]) -> dict[str, int]:
    s = {"total": len(results), "passed": 0, "failed": 0, "skipped": 0}
    for r in results:
        s[r.get("status", "passed")] = s.get(r.get("status", "passed"), 0) + 1
    return s


def _vitest(directory: Path, file: str | None, grep: str | None) -> tuple[list, str]:
    junit = directory / ".test-output.junit.xml"
    args = ["npx", "--no-install", "vitest", "run", "--reporter=junit", f"--outputFile={junit.name}"]
    if file:
        args.append(file)
    if grep:
        args += ["-t", grep]
    rc, out, err = _run(args, str(directory))
    results = []
    if junit.exists():
        results = _parse_junit(junit.read_text())
        try:
            junit.unlink()
        except OSError:
            pass
    return results, (err or out)[-2000:]


def _jest(directory: Path, file: str | None, grep: str | None) -> tuple[list, str]:
    args = ["npx", "--no-install", "jest", "--reporters=jest-junit", "--silent"]
    env_extra = "JEST_JUNIT_OUTPUT_FILE=.jest-junit.xml "
    if file:
        args.append(file)
    if grep:
        args += ["-t", grep]
    cmd = ["bash", "-c", env_extra + " ".join(args)]
    rc, out, err = _run(cmd, str(directory))
    junit = directory / ".jest-junit.xml"
    results = []
    if junit.exists():
        results = _parse_junit(junit.read_text())
        try:
            junit.unlink()
        except OSError:
            pass
    return results, (err or out)[-2000:]


def _bun(directory: Path, file: str | None, grep: str | None) -> tuple[list, str]:
    args = ["bun", "test"]
    if file:
        args.append(file)
    if grep:
        args += ["-t", grep]
    rc, out, err = _run(args, str(directory))
    # bun test n'émet pas JUnit nativement — on parse stderr
    results = []
    pat = re.compile(r"^(✓|✗|~)\s+(.+?)\s+\[?\s*(\d+\.?\d*)\s*ms\]?\s*$")
    for raw in (err + "\n" + out).splitlines():
        m = pat.match(raw.strip())
        if m:
            sym, name, ms = m.groups()
            status = {"✓": "passed", "✗": "failed", "~": "skipped"}.get(sym, "passed")
            results.append({"suite": "", "name": name, "time": float(ms) / 1000, "status": status})
    return results, (err or out)[-2000:]


def _pytest(directory: Path, file: str | None, grep: str | None) -> tuple[list, str]:
    junit = directory / ".pytest-junit.xml"
    args = ["pytest", "--junitxml=" + str(junit), "-q", "--no-header", "--tb=short"]
    if grep:
        args += ["-k", grep]
    if file:
        args.append(file)
    rc, out, err = _run(args, str(directory))
    results = []
    if junit.exists():
        results = _parse_junit(junit.read_text())
        try:
            junit.unlink()
        except OSError:
            pass
    return results, (err or out)[-2000:]


@mcp.tool()
def run(directory: str, file: str | None = None, grep: str | None = None, framework: str | None = None) -> str:
    """Run tests and return structured results.

    Auto-detects vitest/jest/bun test (Node) or pytest (Python).

    Args:
        directory: Project root.
        file: Optional path to a single test file.
        grep: Optional pattern to filter test names.
        framework: Override auto-detection. One of 'vitest', 'jest', 'bun', 'pytest'.

    Returns:
        JSON: {framework, summary: {total, passed, failed, skipped}, failures: [...], stderr_tail}
    """
    d = Path(directory).expanduser().resolve()
    if not d.is_dir():
        return json.dumps({"error": f"not a directory: {directory}"})
    fw = (framework or _detect(d) or "").lower()
    runners = {"vitest": _vitest, "jest": _jest, "bun": _bun, "pytest": _pytest}
    if fw not in runners:
        return json.dumps({"error": f"undetected framework, pass framework=... Got '{fw}'"})
    try:
        results, stderr_tail = runners[fw](d, file, grep)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"test run timed out (10 min)"})
    except Exception as e:
        return json.dumps({"error": f"runner failed: {e}"})
    failures = [r for r in results if r.get("status") == "failed"]
    return json.dumps({
        "framework": fw,
        "summary": _summary(results),
        "failures": failures[:50],
        "stderr_tail": stderr_tail,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def list_tests(directory: str, framework: str | None = None) -> str:
    """List test files in a project (no execution).

    Args:
        directory: Project root.
        framework: Optional override.

    Returns:
        JSON list of file paths.
    """
    d = Path(directory).expanduser().resolve()
    fw = (framework or _detect(d) or "").lower()
    patterns = {
        "vitest": ["**/*.test.ts", "**/*.test.tsx", "**/*.test.js", "**/*.spec.ts", "**/*.spec.tsx", "**/*.spec.js"],
        "jest": ["**/*.test.ts", "**/*.test.tsx", "**/*.test.js", "**/__tests__/**/*.ts", "**/__tests__/**/*.js"],
        "bun": ["**/*.test.ts", "**/*.test.tsx", "**/*.test.js"],
        "pytest": ["**/test_*.py", "**/*_test.py", "tests/**/*.py"],
    }.get(fw)
    if not patterns:
        return json.dumps({"error": f"undetected framework"})
    skip_dirs = {"node_modules", ".git", "dist", "build", ".next", "coverage", "__pycache__", ".venv", "venv"}
    files: list[str] = []
    import os as _os
    for dirpath, dirnames, filenames in _os.walk(d):
        dirnames[:] = [x for x in dirnames if x not in skip_dirs and not x.startswith(".")]
        for fn in filenames:
            p = Path(dirpath) / fn
            rel = p.relative_to(d)
            for pat in patterns:
                if rel.match(pat):
                    files.append(str(rel))
                    break
    return json.dumps({"framework": fw, "files": sorted(set(files))[:500]}, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run()
