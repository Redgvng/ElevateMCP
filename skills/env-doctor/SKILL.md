---
name: env-doctor
description: "Audit env vars for a project — detects missing variables before `npm run dev`/`python ./run.py` crashes 30s later. Cross-checks .env vs .env.example vs code references (process.env.X, import.meta.env.X, os.getenv, os.environ). Tracks unused declarations and undocumented vars. Generates .env.example template from code. Use when starting work on a fresh clone, before deployment, or when a 'X is not defined' runtime error appears. Calls the env-doctor MCP."
---

# env-doctor — env vars sanity checker

Prevents the `npm run dev` that crashes 30 seconds later with `DATABASE_URL is undefined`.

## When to invoke

- First `git clone` or feature branch switch → verify all required env vars are set
- Before deployment → ensure no env vars are in code but missing from `.env`
- Runtime error "X is not defined" on an env var → confirm if it's the root cause
- PR review adding a new env var → ensure it's in `.env.example`
- Cleanup: find declared but never used env vars (legacy)

DO NOT invoke when:
- No `.env` or code touching env vars (pure static lib)
- Env is managed by an external orchestrator (Kubernetes secrets, AWS Parameter Store) that doesn't write to `.env`

## Available tools

| Tool | Usage | Output |
|---|---|---|
| `env_check(project)` | Full audit: missing/unused/undocumented + severity | Detailed JSON |
| `env_diff(project)` | Diff `.env` vs `.env.example` (which is in which) | Short JSON |
| `required(project)` | List env vars referenced in code, file:line | JSON |
| `template_gen(project)` | Generates a `.env.example` to paste into the repo | Dotenv text |

## Detected patterns

JS/TS:
- `process.env.FOO`
- `process.env["FOO"]`
- `import.meta.env.FOO` (Vite/Astro)

Python:
- `os.getenv("FOO")` / `os.getenv("FOO", default)`
- `os.environ["FOO"]`
- `os.environ.get("FOO")`

Skip dirs: `node_modules`, `.next`, `dist`, `build`, `.git`, `coverage`, `__pycache__`, `.venv`, `venv`.

## Typical workflow: fresh clone

```
1. cd <project>
2. mcp__env-doctor__env_diff(project=".")
   → lists vars only_in_example (ask a teammate for the real values)
3. cp .env.example .env
4. Fill in real values (from 1Password, Bitwarden, etc.)
5. mcp__env-doctor__env_check(project=".")
   → if missing > 0: complete them, otherwise "ok"
6. npm run dev / python ./run.py — should boot cleanly
```

## Typical workflow: pre-deployment

```
1. mcp__env-doctor__required(project="/path/to/project")
   → exhaustive list of all referenced vars (often 30-50+ on real apps)
2. Compare against the list of secrets configured on the host
3. For each missing-in-env (at target runtime) → add via secret manager
4. mcp__env-doctor__env_check(project=".") → confirm "ok" before build
```

## Typical workflow: debt cleanup

```
1. mcp__env-doctor__env_check(project=".")
   → unused_in_env: ["LEGACY_API_URL", "OLD_FEATURE_FLAG"]
2. Check git log to understand when each var became obsolete
3. Remove from `.env`, `.env.example`, and docs
4. Document in commit "chore: drop unused env vars X, Y"
```

## Anti-patterns

❌ Never blindly trust `unused_in_env` — some vars are used by external tools (PM2, Docker Compose, shell scripts) that aren't scanned
❌ Don't commit `template_gen` output without cleaning — some vars are truly optional and shouldn't be in `.env.example` (e.g. `OPENAI_API_KEY` if you're on Mistral)
❌ Don't use on a monorepo without specifying the sub-project — risks scanning unrelated folders and skewing the diff
❌ Don't ignore `severity: warning` (undocumented) — that's what bites a new dev on clone

## Typical case: complex Next.js app

A real Next.js app (auth + DB + payment + storage + LLM) easily has 30-50+ env vars (`DATABASE_URL`, `NEXTAUTH_*`, `STRIPE_*`, `S3_*`, etc.). `check(/path/to/project)` should run after every `git pull` and before every `npm run dev`. If `missing > 0`, the worker may crash silently.

## ROI

~5-10 min/incident × 1-2/day for a polyglot solo dev. Weekly regular use: ~10 min/week. Low daily cost but avoids frustrating debug sessions.
