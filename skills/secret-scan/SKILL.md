---
name: secret-scan
description: "Detect leaked secrets in git diffs, history, or single files. Hybrid mode: wraps gitleaks if installed (battle-tested rules), falls back to 16 builtin regex patterns covering AWS/GitHub/Stripe/OpenAI/Anthropic/JWT/PEM keys/nvapi/Mistral. Use BEFORE every commit, when reviewing a PR, or when auditing a repo for past leaks. Output is masked (last 4 chars only) — never prints the full secret. Calls the secret-scan MCP."
---

# Secret scanner (gitleaks-backed or builtin patterns)

Prevents secret leaks in git diffs, staged content, or commit history. Defense-in-depth for multi-project working trees.

## When to invoke

- Before every `git commit` or push (ideally as a pre-commit hook)
- During PR review (scan diff vs main)
- Auditing a retrieved repo (scan N commits of history)
- When pasting suspicious code or a .env file
- Adding a new external dependency (verify it doesn't bundle embedded secrets)

DO NOT invoke when:
- The scanned content is publicly known (e.g. open-source lib, read-only)
- Debugging a known secret (use vault CLI directly instead)

## Available tools

| Tool | Usage | Guardrail |
|---|---|---|
| `scan_status` | Active mode (gitleaks/builtin), version, pattern count | none |
| `scan_staged(repo)` | Scan git staged content (pre-commit style) | repo path validated |
| `scan_diff(target_ref, repo)` | Diff between HEAD and a ref | refs validated |
| `scan_history(depth, repo)` | Last N commits, capped at 1000 | depth bounded |
| `scan_file(path)` | Single file scan | absolute or cwd-relative |
| `add_pattern(name, regex)` | Custom regex in RAM (lost on restart) | regex validated via re.compile |

## Gitleaks mode (preferred)

If `gitleaks` is on PATH (binary installed in `~/.local/bin/gitleaks`), the MCP uses `gitleaks detect`/`protect` with battle-tested rules (~150 patterns). Native gitleaks JSON output, ready to parse.

## Builtin mode (fallback)

16 essential patterns:
- AWS: AKIA*
- GitHub: ghp_, gho_, ghs_
- Stripe: sk_live_, sk_test_, pk_live_
- OpenAI, Anthropic, Google, Slack
- JWT (3-part base64url)
- nvapi-, mistral_key (with context)
- PEM private keys
- Generic api_key / secret_key (strict regex ≥24 chars)

Builtin = basic defense. Gitleaks = full defense.

## Typical workflow: pre-commit audit

```
1. mcp__secret-scan__scan_status()                           → check mode (should be gitleaks)
2. mcp__secret-scan__scan_staged(repo="/path/to/project")    → pre-commit
3. mcp__secret-scan__scan_diff(target_ref="origin/main")     → branch diff
4. If findings: triage by rule (filter false positives: test fixtures, dummy keys)
5. For real leaks:
   - Not yet committed: `git restore --staged <file>` + replace value
   - Already committed: `git filter-repo` + ROTATE the real secret
```

## Typical workflow: post-incident history audit

```
1. mcp__secret-scan__scan_history(depth=200, repo="/path/to/project")
2. List findings per commit
3. For each rule found → IMMEDIATE secret rotation (Stripe, OpenAI, AWS, etc.)
4. Do NOT rebase public history without coordination
5. Document the incident (compliance log)
```

## Anti-patterns

❌ Never print/log the full secret value — the MCP already masks (last 4 chars), keep it masked
❌ Don't rely on builtin if gitleaks is available — always install gitleaks in `~/.local/bin/`
❌ Don't commit a custom `add_pattern` into code — it's in RAM, add to server.py if stable
❌ Don't use for DEV secrets (placeholders, dummy values) — false positive noise
❌ Don't replace with raw `grep` — patterns are contextual (e.g. Mistral key requires mistral/scaleway context)

## Installing gitleaks (if missing)

```bash
curl -sL "https://github.com/gitleaks/gitleaks/releases/latest/download/gitleaks_*_linux_x64.tar.gz" -o /tmp/gl.tgz
mkdir -p ~/.local/bin
tar -xzf /tmp/gl.tgz -C ~/.local/bin/ gitleaks
rm /tmp/gl.tgz
gitleaks version
```

## ROI

- 1 leak avoided = no rotation needed = no monitoring network alert, no reputational risk.
- Ongoing: ~2 min/commit for the scan reflex, ~3 min/day saved by eliminating paranoia.
- Pre-commit hook recommended after stabilization.
