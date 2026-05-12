# mcp-toolkit

**12 production-ready MCP servers + 3 skills for CommandCode and any MCP-compatible CLI agent.**

A curated toolkit that covers what an agent actually can't do in bash alone:
semantic search, multi-file edits, structured git output, secret scanning,
env-var auditing, SQL, diff application, browser inspection, and test running.
All stdio-transport, all stdlib-first, all under 250 lines each.

```
       12 servers · 47 tools · 3 skills · 1 gateway (ElevateMCP) · MIT
```

## Why

Most MCP packs are either toy demos or a single-purpose wrapper.
**mcp-toolkit** is what one developer actually uses every day across multiple projects:

- **No NIH (Not-Invented-Here) bias.** Wraps mature CLI tools (`gitleaks`, `tesseract`, `ripgrep`)
  with a tight typed interface — never reinvents what already exists.
- **Stdlib-first.** 9 of 12 servers run on Python stdlib + `mcp`.
  Optional deps (Playwright, fastembed, psycopg) are gated behind prompts.
- **Failure-graceful.** Missing CLI binary? The server boots and returns
  `available: false` with hints — never crashes your agent.
- **One-shot install.** `./install.sh` detects CommandCode,
  creates a venv, copies servers, generates `mcp.json`. Done in 60 seconds.

## Install

```bash
git clone https://github.com/Redgvng/ElevateMCP.git
cd mcp-toolkit
./install.sh
```

The installer:
1. Auto-detects target (`~/.commandcode` or `~/.config/mcp-toolkit`)
2. Creates a Python 3.10+ venv if absent
3. Installs core deps (`mcp`, `httpx`, `requests`, `croniter`, `jsonpath-ng`)
4. **Prompts** for optional Python deps (sql/browser-inspect/semantic-search)
5. **Prompts** for optional system binaries (`gitleaks`, `tesseract`, `ripgrep`, `jq`)
6. Generates a fully-formed `mcp.json` ready for your agent

### Override defaults

```bash
INSTALL_DIR=~/my-mcp ./install.sh   # custom location
VENV=~/.virtualenvs/mcp ./install.sh # reuse existing venv
ASSUME_YES=1 ./install.sh           # non-interactive (installs all optional deps)
SKIP_OPTIONAL=1 ./install.sh        # skip system binary prompts
```

### Uninstall

```bash
./uninstall.sh
```

## The 12 servers

### Code intelligence

| Server | Tools | Purpose |
|---|---|---|
| **multiedit** | `multi_edit`, `multi_file_edit` | N atomic edits per file + cross-file refactor |
| **semantic-search** | `index`, `ss_query`, `list_indexes` | Intent search via fastembed BGE-small (offline) |
| **git** | `log`, `git_diff`, `blame`, `find_commits_touching`, `branches`, `git_status`, `show` | Structured JSON git output |

### Development workflow

| Server | Tools | Purpose |
|---|---|---|
| **test-runner** | `run`, `list_tests` | vitest / jest / bun / pytest with JUnit XML parse |
| **sql** | `sql_query`, `tables`, `describe`, `explain` | Postgres / SQLite / MySQL — read-only by default, refuses `DROP DATABASE` even with `unsafe=True` |
| **diff-apply** | `parse`, `dry_run`, `apply` | Apply LLM-generated diffs with conflict detection + denylist |
| **browser-inspect** | `screenshot`, `dom`, `console`, `network`, `eval_js`, `click_and_capture` | Playwright Chromium headless — verify your UI |

### Safety & sanity

| Server | Tools | Purpose |
|---|---|---|
| **secret-scan** | `scan_status`, `scan_staged`, `scan_diff`, `scan_history`, `scan_file`, `add_pattern` | Hybrid mode: gitleaks if installed (preferred) → 16 builtin patterns fallback |
| **env-doctor** | `env_check`, `env_diff`, `required`, `template_gen` | Cross-checks `.env` vs `.env.example` vs code refs (`process.env.X`, `os.getenv`) |
| **llm-guard** | `scan_prompt`, `list_attacks`, `redact_pii`, `batch_scan` | Prompt injection & jailbreak detection, PII redaction — stdlib-only, no deps |

## The 3 skills

`skills/` ships markdown skills that explain **when** to invoke each MCP and what
workflow to follow. Drop them in `~/.commandcode/skills/` (auto by `install.sh`).

| Skill | When to invoke |
|---|---|
| **secret-scan** | Before commit, PR review, repo audit. Triage by rule, mask secrets, rotate before rebase. |
| **env-doctor** | Fresh clone, before deploy, "X undefined" runtime error, env-var cleanup. |
| **mcp-development** | Adding a new MCP server. Boilerplate, garde-fous, NIH-avoidance rule. |

## Compatibility

| Agent | Status |
|---|---|
| **CommandCode CLI** | First-class. `install.sh` auto-detects `~/.commandcode/`. |
| **Cursor / Cline / Continue / Aider** | Compatible — they all consume `mcp.json`. Copy the entries from `examples/mcp.json.example`. |
| **Custom agents** | Compatible with any MCP-1.x stdio client. |

## Optional system binaries

The toolkit works without them, but installs unlock features:

| Binary | Unlocks | Install |
|---|---|---|
| `gitleaks` | `secret-scan` mode `gitleaks` (~150 rules vs 16 builtin) | `./install.sh` prompts, or download from [github.com/gitleaks/gitleaks/releases](https://github.com/gitleaks/gitleaks/releases) |
| `ripgrep` | Used internally by some skills | `apt install ripgrep` |

## Architecture principles

1. **stdio transport, FastMCP framework.** No HTTP daemons, no global state.
2. **One file, one server.** `mcp-servers/<name>/server.py`. No package, no `__init__.py`.
3. **Stdlib first.** External libs only when essential (httpx, fastembed, playwright).
4. **Read-only by default.** Mutations require explicit `dryRun=False` flag.
5. **Garde-fous.** Denylists for `.env`, `.ssh`, `/etc/`. cabinetId/projectId enforcement on multi-tenant tools.
6. **Failure-graceful.** Missing CLI? Return `{"error": "..."}` JSON, never crash.
7. **Output structured.** Every tool returns JSON ready for agent consumption in autofix loops.

## Per-server quick reference

Each MCP has a self-contained `server.py` with docstring per tool. Read them directly:

```bash
# Show all tools and their docstrings for a given server
~/.commandcode/venv/bin/python -c "
import inspect
import sys; sys.path.insert(0, '$HOME/.commandcode/mcp-servers/secret-scan')
import server
print(server.__doc__)
for name, fn in inspect.getmembers(server, inspect.isfunction):
    if hasattr(fn, '_tool_meta') or 'tool' in str(getattr(fn, '_tool_handler', '')):
        print(f'\n## {name}'); print(inspect.getdoc(fn))
"
```

Or open the `server.py` files directly — every tool has a Google-style docstring.

## Adding your own MCP

See `skills/mcp-development/SKILL.md` for the full pattern. Short version:

```bash
mkdir -p ~/.commandcode/mcp-servers/my-tool
cat > ~/.commandcode/mcp-servers/my-tool/server.py <<'EOF'
#!/usr/bin/env python3
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("my-tool")

@mcp.tool()
def hello(name: str) -> str:
    """Say hello.

    Args:
        name: Who to greet.
    Returns:
        Greeting string.
    """
    return f"Hello, {name}!"

if __name__ == "__main__":
    mcp.run()
EOF

# Add to ~/.commandcode/mcp.json
# Restart your agent
```

## Contributing

PRs welcome — especially:
- New stdio MCP servers under 300 lines, stdlib-first
- Skills (`.md`) explaining workflows for existing servers
- Cross-platform support (Windows tested? macOS tested?)
- Tests (handshake + smoke per MCP)

## License

MIT — see [LICENSE](./LICENSE).

## Credits

Born out of one solo dev's daily workflow on multiple Next.js / Python / Go projects.
The "Not-Invented-Here" rule that shaped this toolkit:

> If a mature CLI tool exists (>1k★, >2 years), don't MCP-ify it unless you add
> aggregation or state that's impossible in bash. Otherwise it's a markdown
> skill that pipes to the CLI.

The 5 MCPs that did meet that bar: `multiedit`, `semantic-search`, `secret-scan`,
`env-doctor`, and `cabinet-isolation`.
The rest wrap battle-tested CLIs / SDKs with structured output.
