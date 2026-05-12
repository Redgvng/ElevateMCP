---
name: secret-scan
description: "Detect leaked secrets in git diffs, history, or single files. Hybrid mode: wraps gitleaks if installed (battle-tested rules), falls back to 16 builtin regex patterns covering AWS/GitHub/Stripe/OpenAI/Anthropic/JWT/PEM keys/nvapi/Mistral. Use BEFORE every commit, when reviewing a PR, or when auditing a repo for past leaks. Output is masked (last 4 chars only) — never prints the full secret. Calls the secret-scan MCP."
---

# Secret scanner (gitleaks-backed or builtin patterns)

Empêche les fuites de secrets en git diff, staged content, ou history. Critère de défense en profondeur sur un working tree de 21 entrées Astrée.

## Quand invoquer

- Avant chaque `git commit` ou push (idéalement en pre-commit hook)
- Lors d'une revue de PR (scan de la diff vs main)
- Audit d'un repo récupéré (scan history sur N commits)
- Quand l'utilisateur copie-colle du code suspect ou un .env
- Ajout d'une nouvelle dépendance externe (vérifier qu'elle ne demande pas un secret embarqué)

NE PAS invoquer si :
- Le contenu scanné est notoirement public (ex: lib open source en lecture)
- Pour debug d'un secret connu (utiliser `op` CLI ou vault directement)

## Tools disponibles

| Tool | Usage | Garde-fou |
|---|---|---|
| `scan_status` | Mode actif (gitleaks/builtin), version, count patterns | aucun |
| `scan_staged(repo)` | Scan git staged content (pre-commit-style) | repo path validé |
| `scan_diff(target_ref, repo)` | Diff entre HEAD et un ref | refs validées |
| `scan_history(depth, repo)` | Last N commits, capped à 1000 | depth borné |
| `scan_file(path)` | Single file scan | absolute or cwd-relative |
| `add_pattern(name, regex)` | Custom regex en RAM (perdu au restart) | regex validé via re.compile |

## Mode gitleaks (préféré)

Si `gitleaks` est dans le PATH (binaire installé dans `~/.local/bin/gitleaks`), le MCP utilise `gitleaks detect`/`protect` avec leurs rules battle-tested (~150 patterns). Output JSON natif gitleaks, prêt à parser.

## Mode builtin (fallback)

16 patterns essentiels :
- AWS: AKIA*
- GitHub: ghp_, gho_, ghs_
- Stripe: sk_live_, sk_test_, pk_live_
- OpenAI, Anthropic, Google, Slack
- JWT (3-part base64url)
- nvapi-, mistral_key (avec contexte)
- PEM private keys
- Generic api_key / secret_key (regex strict ≥24 chars)

Builtin = défense de base. Gitleaks = défense complète.

## Workflow typique : audit Astrée working tree

```
1. mcp__secret-scan__scan_status()                              → check mode (devrait être gitleaks)
2. mcp__secret-scan__scan_staged(repo="/path/to/project")  → pre-commit
3. mcp__secret-scan__scan_diff(target_ref="origin/main")   → diff branche
4. Si findings : trier par rule (filtrer faux positifs : test fixtures, dummy keys)
5. Pour vrais leaks :
   - Si pas encore commité : `git restore --staged <file>` + remplacer la valeur
   - Si déjà commité : `git filter-repo` + ROTATION du secret réel
```

## Workflow audit history (post-incident)

```
1. mcp__secret-scan__scan_history(depth=200, repo="/path/to/project")
2. Lister les findings par commit
3. Pour chaque rule trouvée → ROTATION immédiate du secret (Stripe, OpenAI, AWS, etc.)
4. NE PAS rebase l'history publique sans coordination
5. Documenter l'incident (compliance log)
```

## Anti-patterns

❌ Ne jamais print/log la valeur complète d'un secret — le MCP masque déjà (last 4 chars), garder le masque
❌ Ne pas se contenter du builtin si gitleaks est dispo — toujours installer gitleaks dans `~/.local/bin/`
❌ Ne pas commiter un `add_pattern` custom dans le code — c'est en RAM, ajouter au server.py si pattern stable
❌ Ne pas utiliser pour des secrets de DEV (placeholders, dummy values) — false positives noise
❌ Ne pas remplacer par `grep` simple — les patterns sont contextuels (ex: Mistral key requiert contexte mistral/scaleway)

## Installation gitleaks (si absent)

```bash
curl -sL "https://github.com/gitleaks/gitleaks/releases/latest/download/gitleaks_*_linux_x64.tar.gz" -o /tmp/gl.tgz
mkdir -p ~/.local/bin
tar -xzf /tmp/gl.tgz -C ~/.local/bin/ gitleaks
rm /tmp/gl.tgz
gitleaks version
```

## ROI

- 1 leak évité = rotation pas faite = pas de réseau monitoring CRA, pas de risque réputationnel.
- En continu : ~2 min/commit pour le réflexe scan, ~3 min/jour économisés en paranoïa éliminée.
- Hook pre-commit recommandé après stabilisation.
