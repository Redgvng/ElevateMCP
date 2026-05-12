#!/usr/bin/env bash
# mcp-toolkit uninstaller. Removes the 11 MCP servers + 3 skills installed by install.sh.
# Does NOT delete the venv (you may share it with other tools).
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-}"
if [[ -z "$INSTALL_DIR" ]]; then
  if [[ -d "$HOME/.commandcode/mcp-servers" ]]; then
    INSTALL_DIR="$HOME/.commandcode"
  else
    echo "Cannot detect install dir. Set INSTALL_DIR=... ./uninstall.sh" >&2
    exit 1
  fi
fi

echo "Uninstalling mcp-toolkit from: $INSTALL_DIR"
SERVERS=(multiedit semantic-search git test-runner sql diff-apply browser-inspect cve-search llm-guard secret-scan env-doctor gateway)
SKILLS=(secret-scan env-doctor mcp-development)

for s in "${SERVERS[@]}"; do
  if [[ -d "$INSTALL_DIR/mcp-servers/$s" ]]; then
    rm -rf "$INSTALL_DIR/mcp-servers/$s"
    echo "  removed mcp-servers/$s"
  fi
done

for s in "${SKILLS[@]}"; do
  if [[ -d "$INSTALL_DIR/skills/$s" ]]; then
    rm -rf "$INSTALL_DIR/skills/$s"
    echo "  removed skills/$s"
  fi
done

# Backup mcp.json if it still references our servers
if [[ -f "$INSTALL_DIR/mcp.json" ]]; then
  echo
  echo "Note: $INSTALL_DIR/mcp.json was not auto-edited (might contain other servers)."
  echo "Edit it manually to remove the entries for the uninstalled servers."
fi

echo "Done."
