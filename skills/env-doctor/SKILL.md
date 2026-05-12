---
name: env-doctor
description: "Audit env vars for a project — detects missing variables before `npm run dev`/`python ./run.py` crashes 30s later. Cross-checks .env vs .env.example vs code references (process.env.X, import.meta.env.X, os.getenv, os.environ). Tracks unused declarations and undocumented vars. Generates .env.example template from code. Use when starting work on a fresh clone, before deployment, or when a 'X is not defined' runtime error appears. Calls the env-doctor MCP."
---

# env-doctor — env vars sanity checker

Évite le `npm run dev` qui plante 30 secondes plus tard sur `DATABASE_URL is undefined`.

## Quand invoquer

- Premier `git clone` ou switch de branche feature → vérifier qu'on a toutes les env vars requises
- Avant un déploiement → vérifier qu'aucune env n'est dans le code mais pas dans `.env`
- Erreur runtime "X is not defined" sur une env var → confirmer si c'est en cause
- PR review qui ajoute une nouvelle env var → s'assurer qu'elle est dans `.env.example`
- Nettoyage : trouver les env vars déclarées mais jamais utilisées (legacy)

NE PAS invoquer si :
- Pas de `.env` ni de code touchant aux env vars (pure lib statique)
- L'env est gérée par un orchestrateur externe (Kubernetes secrets, AWS Parameter Store) qui n'écrit pas dans `.env`

## Tools disponibles

| Tool | Usage | Output |
|---|---|---|
| `env_check(project)` | Audit complet : missing/unused/undocumented + severity | JSON détaillé |
| `env_diff(project)` | Diff `.env` vs `.env.example` (which is in which) | JSON court |
| `required(project)` | Liste des env vars référencées dans le code, file:line | JSON |
| `template_gen(project)` | Génère un `.env.example` à coller dans le repo | Texte dotenv |

## Patterns détectés

JS/TS :
- `process.env.FOO`
- `process.env["FOO"]`
- `import.meta.env.FOO` (Vite/Astro)

Python :
- `os.getenv("FOO")` / `os.getenv("FOO", default)`
- `os.environ["FOO"]`
- `os.environ.get("FOO")`

Skip dirs : `node_modules`, `.next`, `dist`, `build`, `.git`, `coverage`, `__pycache__`, `.venv`, `venv`.

## Workflow typique : nouveau clone

```
1. cd <project>
2. mcp__env-doctor__env_diff(project=".")
   → liste vars only_in_example (à demander à un collègue)
3. cp .env.example .env
4. Remplir les vraies valeurs (depuis 1Password, Bitwarden, etc.)
5. mcp__env-doctor__env_check(project=".")
   → si missing > 0 : compléter, sinon "ok"
6. npm run dev / python ./run.py — devrait booter
```

## Workflow typique : avant deploy Astrée

```
1. mcp__env-doctor__required(project="/path/to/project")
   → liste exhaustive des vars utilisées (souvent 30-50+ sur app réel)
2. Comparer avec la liste des secrets configurés sur l'hébergeur
3. Pour chaque var missing in env (au runtime cible) → ajouter via secret manager
4. mcp__env-doctor__env_check(project=".") → confirmer "ok" avant build
```

## Workflow typique : nettoyage debt

```
1. mcp__env-doctor__env_check(project=".")
   → unused_in_env: ["LEGACY_API_URL", "OLD_FEATURE_FLAG"]
2. Vérifier git log pour comprendre quand chaque var est devenue obsolète
3. Retirer du `.env`, `.env.example`, et docs
4. Documenter en commit "chore: drop unused env vars X, Y"
```

## Anti-patterns

❌ Ne jamais faire confiance aveuglément à `unused_in_env` — certaines vars sont utilisées par des tools externes (PM2, Docker Compose, scripts shell) qui ne sont pas scannés
❌ Ne pas committer le `template_gen` output sans le nettoyer — certaines vars sont vraiment optionnelles et n'ont pas leur place dans `.env.example` (ex: `OPENAI_API_KEY` si on est sur Mistral)
❌ Ne pas utiliser sur un repo monorepo sans préciser le sous-projet — risque de scanner des dossiers non liés et fausser le diff
❌ Ne pas ignorer les `severity: warning` (undocumented) — c'est ce qui pique un nouveau dev qui clone

## Cas typique : Next.js complexe

Une app Next.js réelle (auth + DB + payment + storage + LLM) compte facilement 30-50+ env vars (`DATABASE_URL`, `NEXTAUTH_*`, `STRIPE_*`, `S3_*`, etc.). `check(/path/to/project)` doit être lancé après chaque `git pull` et avant chaque `npm run dev`. Si `missing > 0`, le worker peut crash silencieusement.

## ROI

~5-10 min/incident × 1-2/jour pour un dev solo polyglotte. Ramené à un usage hebdo régulier : ~10 min/semaine. Faible quotidien mais évite des debug frustrants.
