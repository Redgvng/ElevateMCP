---
name: mcp-development
description: "Patterns and conventions for building new MCP servers in CommandCode (Python FastMCP, stdio transport, ~/.commandcode/mcp-servers/). Covers boilerplate, tool design, schema parsing, garde-fous (denylist/dryRun/audit), handshake testing, registration in mcp.json, and the central rule: do NOT MCP-ify mature CLI tools (NIH trap). Use when the user asks to create a new MCP, refactor an existing one, or evaluate whether a feature should be MCP/skill/script."
---

# MCP development for CommandCode

Conventions pour développer un nouveau MCP server qui s'intègre proprement dans la flotte CommandCode.

## La règle de coupe (LIRE EN PREMIER)

> Si un outil CLI mature existe (>1k★ >2 ans), **interdiction de MCP-ifier** sauf si tu ajoutes un agrégat ou un état impossible en bash. Sinon = skill markdown qui pipe vers le CLI.

**Corollaire** : un MCP ne se justifie QUE si son output structuré est consommé par un agent dans une boucle (ex: scan → autofix → re-scan).

Anti-patterns à refuser même si l'utilisateur insiste :
- `bench-diff` → utilise `hyperfine` + `git notes`
- `dep-audit` → `npm audit` + `npm-check-updates` + `depcheck`
- `http-craft` → Bruno (open source, fichiers `.bru` versionnés)
- `todo-radar` → `rg "TODO|FIXME" --json | jq` + skill
- Wrapper d'outil cloud existant qui marche bien

## Convention de structure

```
~/.commandcode/mcp-servers/<name>/
├── server.py        # FastMCP server, stdio transport
└── (data/)          # cache disque optionnel (~/.commandcode/data/<name>/)
```

Pas de `__init__.py`, pas de package. Un fichier `server.py` autonome.

## Boilerplate minimal

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

## Stack & dépendances

- **Python 3.12** dans `~/.commandcode/venv/` (déjà présent)
- **mcp 1.27** (FastMCP) — déjà installé
- **Préférer stdlib pure** quand possible (json, re, pathlib, urllib, subprocess)
- Si lib externe nécessaire : ajouter au `pip install` de `~/.commandcode/venv/` et documenter dans la note basic-memory du catalogue
- Outils CLI externes : détecter via `shutil.which()` et fail-graceful, jamais crash

## Garde-fous critiques (à intégrer SYSTÉMATIQUEMENT)

### Pour les MCP qui mutent
- **Denylist hard** : `.env`, `.ssh`, `.aws`, `/etc/`, secrets refusés côté MCP, pas côté prompt
- **dryRun=True par défaut**, mutation effective requiert flag explicite
- **Audit log** : chaque mutation logguée (path, action, before/after)

### Pour les MCP avec scope tenant (Astrée)
- **cabinetId REQUIS** sur tools tenant-scoped, le MCP refuse sans
- **Refus si cabinetId vide ou whitespace**

### Pour les MCP qui appellent des APIs externes
- **Timeout explicite** (10s par défaut)
- **Fail-fast graceful** : retour JSON `{"error": "..."}`, jamais crash le serveur
- **Pas de retry agressif** — le client MCP gère

## Validation pré-enregistrement

3 checks obligatoires avant d'ajouter à `mcp.json` :

```bash
# 1. Syntax check
~/path/to/venv/bin/python -m py_compile ~/.commandcode/mcp-servers/<name>/server.py

# 2. Handshake MCP (initialize → tools/list)
# Voir /tmp pattern :
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

# 3. Smoke test : 1 tool/call représentatif
# (similaire au handshake mais avec method='tools/call')
```

## Enregistrement dans le gateway

Ajouter le serveur dans `mcp-servers/gateway/_registry.py` :

```python
TOOLS["mon-outil"] = ["outil_a", "outil_b"]
# Si un nom entre en conflit avec un outil existant :
RENAMES["mon-outil"] = {"outil_a": "mon_outil_a"}
```

Le gateway (`ElevateMCP`) recharge automatiquement les modules au démarrage — redémarrer l'agent suffit.

> **Note:** Ne plus ajouter d'entrée individuelle dans `mcp.json`. Depuis ElevateMCP, une seule entrée `ElevateMCP` gère tous les serveurs.

## Skill associée (recommandé)

Pour chaque MCP non trivial, créer une skill `~/.commandcode/skills/<name>/SKILL.md` qui :
- Décrit QUAND invoquer (use cases)
- Décrit QUAND ne PAS invoquer
- Liste les tools avec garde-fous
- Donne 1-3 workflows typiques
- Liste les anti-patterns
- Chiffre le ROI

C'est cette skill que l'agent consultera, pas le code Python du server. Sans skill, le MCP est sous-utilisé.

## Documentation mémoire

Après ajout d'un MCP :
1. Update `~/.ccs/.../memory/commandcode_setup.md` (compteurs servers + tools)
2. Update basic-memory `main/projects/commandcode/command-code-catalogue-mcp-built-ideas` (cocher l'idée si elle y était, ou ajouter)
3. Si stratégique, créer une note dédiée

## Erreurs à éviter

❌ Coder le MCP avant d'avoir vérifié qu'aucun outil CLI mature ne fait déjà le job
❌ Ajouter 7 tools alors que 2 suffiraient pour le ROI réel (scope creep)
❌ Faire un MCP qui réimplémente un autre déjà installé (doublon)
❌ Output non structuré (texte brut) → impossible à consommer par l'agent en boucle
❌ Pas de garde-fous → fuite secrets ou mutation prod accidentelle
❌ Pas de skill associée → MCP sous-utilisé, devient mort-né en 60 jours
