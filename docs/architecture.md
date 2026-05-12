# Architecture

## Overview

mcp-toolkit is a collection of standalone MCP servers, each living in a single
`server.py` file under `mcp-servers/<name>/`. No shared package, no `__init__.py`,
no daemon — each server is spawned on-demand by the agent client via stdio transport.

```
mcp-toolkit/
├── mcp-servers/
│   ├── time/server.py          ← one file, one server
│   ├── env-doctor/server.py
│   └── ...                     (19 total)
├── skills/
│   ├── secret-scan/SKILL.md    ← when + workflow for the agent
│   ├── env-doctor/SKILL.md
│   └── mcp-development/SKILL.md
├── install.sh                  ← copies servers + generates mcp.json
└── requirements.txt
```

## Transport

All servers use **stdio transport** (MCP default). The agent spawns each server as a
subprocess and exchanges JSON-RPC 2.0 messages over stdin/stdout. No port binding,
no HTTP daemon, no global state between invocations.

## Server anatomy

Every server follows the same pattern:

```python
#!/usr/bin/env python3
"""One-paragraph docstring: what this server does."""
from __future__ import annotations

# stdlib imports
# optional dep imports (only what the server needs)
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("server-name")

# ── helpers ──────────────────────────────────────────────────────────────────

def _internal_helper(...): ...

# ── tools ────────────────────────────────────────────────────────────────────

@mcp.tool()
def tool_name(arg: str, flag: bool = False) -> str:
    """One-line description.

    Args:
        arg: What this arg does.
        flag: What this flag does.

    Returns:
        JSON string or plain text.
    """
    ...

if __name__ == "__main__":
    mcp.run()
```

Rules enforced consistently across all 19 servers:

- **One file.** No sub-packages, no imports from sibling servers.
- **Returns JSON or plain text.** Agents consume structured output — raw blobs waste tokens.
- **Read-only by default.** Mutations require an explicit `dryRun=False` or `unsafe=True` argument.
- **Garde-fous.** Sensitive path denylist (`.ssh`, `.aws`, `.env`, `/etc/`) checked before any write.
- **Failure-graceful.** Missing optional binary → `{"available": false, "hint": "apt install ..."}`. Never crash.
- **Stdlib-first.** Optional deps (playwright, fastembed, psycopg) are gated behind install prompts and imported only inside the functions that need them — not at module level.

## Tiers

| Tier | Purpose | Servers |
|------|---------|---------|
| 1 — Code intelligence | Core dev loop: edits, search, git, types, lint, JSON | `multiedit`, `semantic-search`, `git`, `typecheck`, `lint`, `json-query`, `time` |
| 2 — Dev workflow | Test, database, patch, browser | `test-runner`, `sql`, `diff-apply`, `browser-inspect` |
| 3 — Niceties | Clipboard, process mgmt, docs, pkg info, OCR, screenshots | `clipboard`, `process`, `devdocs`, `package-info`, `ocr`, `screenshot` |
| 4 — Safety & sanity | Secret detection, env-var auditing | `secret-scan`, `env-doctor` |

The tiered naming is install-time guidance only — any server can be selectively
disabled by removing its entry from `mcp.json`.

## Optional dependencies

Some servers call optional external tools or Python packages:

| Dep | Unlocks | How to install |
|-----|---------|----------------|
| `gitleaks` binary | `secret-scan` gitleaks mode | `install.sh` prompts, or release tarball |
| `playwright` + Chromium | `browser-inspect` | `pip install playwright && playwright install chromium` |
| `fastembed`, `numpy` | `semantic-search` embedding backend | `pip install fastembed numpy` |
| `psycopg[binary]`, `pymysql` | `sql` Postgres/MySQL drivers | `pip install psycopg[binary] pymysql` |
| `tesseract` | `ocr` | `apt install tesseract-ocr` |
| `xclip`/`wl-copy` | `clipboard` | `apt install xclip` |
| `scrot`/`grim` | `screenshot` | `apt install scrot` |

Servers that depend on optional packages import them **inside the tool function**,
not at module level, so the server boots cleanly even without them.

Exception: `browser-inspect` imports `playwright.async_api` at module level because
all its tools are async. It returns a startup error if playwright is absent.

## The NIH rule

> If a mature CLI tool exists (>1 000 GitHub stars, >2 years old), do not MCP-ify it
> unless the MCP adds aggregation or stateful output that is impossible in bash.

This rule exists because MCP-ifying a mature CLI is maintenance overhead with no
benefit — the CLI already has docs, releases, and community support. The skill
`skills/mcp-development/SKILL.md` explains the anti-patterns to watch for.

## Skills

Skills (`skills/<name>/SKILL.md`) are markdown documents that tell the agent **when**
to invoke a specific MCP and **what workflow to follow**. They are not code — they are
prompt fragments loaded into the agent's context.

`install.sh` copies them alongside the servers so the agent finds them automatically.
