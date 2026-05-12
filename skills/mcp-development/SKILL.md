---
name: mcp-development
description: "Patterns and conventions for building new MCP servers in CommandCode (Python FastMCP, stdio transport, ~/.commandcode/mcp-servers/). Covers boilerplate, tool design, schema parsing, guardrails (denylist/dryRun/audit), handshake testing, registration in mcp.json, and the central rule: do NOT MCP-ify mature CLI tools (NIH trap). Use when the user asks to create a new MCP, refactor an existing one, or evaluate whether a feature should be MCP/skill/script."
---

# MCP development for CommandCode

Conventions for building a new MCP server that integrates cleanly into the CommandCode fleet.

## The cutoff rule (READ FIRST)

> If a mature CLI tool exists (>1k★ >2 years), **do not MCP-ify it** unless you add aggregation or state impossible in bash. Otherwise = markdown skill that pipes to the CLI.

**Corollary**: an MCP is only justified if its structured output is consumed by an agent in a loop (e.g. scan → autofix → re-scan).

Anti-patterns to refuse even if the user insists:
- `bench-diff` → use `hyperfine` + `git notes`
- `dep-audit` → `npm audit` + `npm-check-updates` + `depcheck`
- `http-craft` → Bruno (open source, `.bru` files versioned)
- `todo-radar` → `rg "TODO|FIXME" --json | jq` + skill
- Wrapper for an existing cloud tool that already works well

## Structure convention

```
~/.commandcode/mcp-servers/<name>/
├── server.py        # FastMCP server, stdio transport
└── (data/)          # optional disk cache (~/.commandcode/data/<name>/)
```

No `__init__.py`, no package. A single standalone `server.py` file.

## Minimal boilerplate

```python
#!/usr/bin/env python3
"""MCP server: <name> — <one-line purpose>."""
from __future__ import annotations
import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("<name>")

@mcp.tool()
def tool_name(arg1: str, arg2: int = 10) -> str:
    """One-line description visible to the agent.

    Args:
        arg1: ...
        arg2: ... (default 10)

    Returns:
        JSON string or plain text. Always structured for agent consumption.
    """
    # ... implementation ...
    return json.dumps({"result": "..."}, indent=2)

if __name__ == "__main__":
    mcp.run()
```

## Stack & dependencies

- **Python 3.12** in `~/.commandcode/venv/` (already present)
- **mcp 1.27** (FastMCP) — already installed
- **Prefer pure stdlib** when possible (json, re, pathlib, urllib, subprocess)
- If an external lib is needed: add to `pip install` in `~/.commandcode/venv/` and document in the catalog memory note
- External CLI tools: detect via `shutil.which()` and fail-graceful, never crash

## Critical guardrails (ALWAYS integrate)

### For mutating MCPs
- **Hard denylist**: `.env`, `.ssh`, `.aws`, `/etc/`, secrets rejected MCP-side, not prompt-side
- **dryRun=True by default**, actual mutation requires an explicit flag
- **Audit log**: every mutation logged (path, action, before/after)

### For tenant-scoped MCPs
- **projectId REQUIRED** on tenant-scoped tools, the MCP refuses without it
- **Refuse if projectId is empty or whitespace**

### For MCPs calling external APIs
- **Explicit timeout** (10s default)
- **Fail-fast graceful**: return JSON `{"error": "..."}`, never crash the server
- **No aggressive retry** — the MCP client handles that

## Pre-registration validation

3 mandatory checks before adding to `mcp.json`:

```bash
# 1. Syntax check
~/path/to/venv/bin/python -m py_compile ~/.commandcode/mcp-servers/<name>/server.py

# 2. MCP Handshake (initialize → tools/list)
# See /tmp pattern:
~/path/to/venv/bin/python <<'EOF'
import json, subprocess
PY = os.path.expanduser('~/.commandcode/venv/bin/python')  # adjust to your install
SRV = os.path.expanduser('~/.commandcode/mcp-servers/<name>/server.py')
payload = (json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'t','version':'1'}}})+'\n'
  + json.dumps({'jsonrpc':'2.0','method':'notifications/initialized'})+'\n'
  + json.dumps({'jsonrpc':'2.0','id':2,'method':'tools/list'})+'\n')
p = subprocess.Popen([PY, SRV], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
out, err = p.communicate(input=payload, timeout=20)
for line in out.splitlines():
    if not line.strip(): continue
    msg = json.loads(line) if line.strip().startswith('{') else None
    if msg and msg.get('id') == 2 and 'result' in msg:
        print('OK', len(msg['result']['tools']), 'tools:', [t['name'] for t in msg['result']['tools']])
EOF

# 3. Smoke test: 1 representative tool/call
# (similar to handshake but with method='tools/call')
```

## Registering in the gateway

Add the server in `mcp-servers/gateway/_registry.py`:

```python
TOOLS["my-tool"] = ["tool_a", "tool_b"]
# If a name conflicts with an existing tool:
RENAMES["my-tool"] = {"tool_a": "my_tool_a"}
```

The gateway (`ElevateMCP`) auto-reloads modules on startup — restarting the agent is enough.

> **Note:** No longer add individual entries in `mcp.json`. Since ElevateMCP, a single `ElevateMCP` entry manages all servers.

## Associated skill (recommended)

For every non-trivial MCP, create a skill `~/.commandcode/skills/<name>/SKILL.md` that:
- Describes WHEN to invoke (use cases)
- Describes when NOT to invoke
- Lists the tools with guardrails
- Gives 1-3 typical workflows
- Lists anti-patterns
- Quantifies ROI

It's this skill that the agent will consult, not the Python server code. Without a skill, the MCP is underused.

## Memory documentation

After adding an MCP:
1. Update the server and tool counters in your memory notes
2. Update the MCP catalog (check the idea if it was listed, or add it)
3. If strategic, create a dedicated note

## Mistakes to avoid

❌ Coding the MCP before checking that no mature CLI tool already does the job
❌ Adding 7 tools when 2 would suffice for the real ROI (scope creep)
❌ Building an MCP that duplicates another already installed (double-dip)
❌ Unstructured output (raw text) → impossible for the agent to consume in a loop
❌ No guardrails → secret leak or accidental production mutation
❌ No associated skill → MCP underused, dead in 60 days
