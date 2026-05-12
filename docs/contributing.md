# Contributing

## Quick start

```bash
git clone <repo>
cd mcp-toolkit
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/ -v
```

All tests should pass before you open a PR. CI runs on Python 3.10, 3.11, 3.12.

## What belongs here

- New MCP servers (under 300 lines, stdlib-first, stdio transport).
- Skills (`.md` documents explaining agent workflows for existing servers).
- Cross-platform fixes (Windows clipboard, macOS screencapture, etc.).
- Tests for existing servers.

What does **not** belong:

- MCP wrappers for mature CLI tools that already have good JSON output (see NIH rule below).
- Servers over 300 lines without a strong justification.
- Global state between tool calls (each call must be stateless).

## Adding a new server

Read `skills/mcp-development/SKILL.md` first — it covers the full pattern.

Short checklist:

1. **Check the NIH rule.** If a CLI tool like `ripgrep`, `jq`, or `fd` already does what you need and outputs JSON, write a skill instead. A new MCP is justified when the agent needs structured output that is impossible in one bash invocation (e.g. aggregating multiple calls, maintaining a cache, detecting tool presence with graceful fallback).

2. **Create the directory and file.**

   ```bash
   mkdir mcp-servers/my-tool
   touch mcp-servers/my-tool/server.py
   ```

3. **Follow the boilerplate** (see `docs/architecture.md`). Key constraints:
   - `mcp = FastMCP("my-tool")` — name must match directory name.
   - Return JSON or plain text; never raise unhandled exceptions.
   - Optional deps: import inside the function, not at module level (except playwright).
   - Sensitive-path denylist: replicate the guard from `multiedit/server.py` for any write operation.

4. **Write tests.** Add `tests/test_my_tool.py`. At minimum:
   - An import test (already covered by `test_import.py` once you add the name to `ALL_SERVERS`).
   - A smoke test that calls each tool with valid input and checks the output parses.
   - An error-path test (bad path, missing binary, etc.).

5. **Update `test_import.py`** — add `"my-tool"` to `ALL_SERVERS` and `EXPECTED_TOOLS`.

6. **Update `uninstall.sh`** — add the server name to the `SERVERS` array.

7. **Update `examples/mcp.json.example`** — add the entry.

8. **Update the README** — add a row to the relevant tier table.

## Running tests

```bash
# Full suite
pytest tests/ -v

# One file
pytest tests/test_time.py -v

# Fast: only stdlib-safe tests (skip if optional deps missing)
pytest tests/ -v -k "not browser"
```

## Code style

- Python 3.10+ syntax (`X | Y` unions, `match`, etc.).
- `from __future__ import annotations` at the top of every file.
- Type hints on all public functions.
- Google-style docstrings on tool functions (Args / Returns sections).
- No line longer than 100 characters.
- Format with `ruff format` or `black` before submitting.

## PR checklist

- [ ] `pytest tests/ -v` passes locally.
- [ ] New server: boilerplate followed, tests added, README updated, uninstall.sh updated.
- [ ] No secrets committed (run `secret-scan` MCP or `gitleaks detect` if installed).
- [ ] One logical change per PR.
