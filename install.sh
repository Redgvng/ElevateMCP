#!/usr/bin/env bash
# mcp-toolkit installer
# Installs 11 MCP servers + 3 skills into CommandCode / any
# MCP-compatible CLI agent.
#
# Default targets (auto-detected, fall through):
#   1. ~/.commandcode/    (CommandCode CLI)
#   2. ~/.config/mcp-toolkit/  (standalone, register manually)
#
# Override target:
#   INSTALL_DIR=~/my-mcp ./install.sh
#
# Override Python venv path:
#   VENV=/path/to/venv ./install.sh
#
# Skip optional CLI binaries (gitleaks, tesseract):
#   SKIP_OPTIONAL=1 ./install.sh

set -euo pipefail

readonly RED=$'\033[1;31m'
readonly GREEN=$'\033[1;32m'
readonly YELLOW=$'\033[1;33m'
readonly BLUE=$'\033[1;34m'
readonly RESET=$'\033[0m'

log()   { printf "${BLUE}[install]${RESET} %s\n" "$*"; }
ok()    { printf "${GREEN}[ ok   ]${RESET} %s\n" "$*"; }
warn()  { printf "${YELLOW}[ warn ]${RESET} %s\n" "$*"; }
fatal() { printf "${RED}[fatal]${RESET} %s\n" "$*" >&2; exit 1; }

readonly REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_SERVERS="${REPO_DIR}/mcp-servers"
readonly REPO_SKILLS="${REPO_DIR}/skills"

# ─── 1. Detect target ────────────────────────────────────────────────────────
detect_target() {
  if [[ -n "${INSTALL_DIR:-}" ]]; then
    echo "$INSTALL_DIR"
    return
  fi
  if [[ -d "$HOME/.commandcode" ]]; then
    echo "$HOME/.commandcode"
    return
  fi
  echo "$HOME/.config/mcp-toolkit"
}

INSTALL_DIR="$(detect_target)"
log "Target install dir: $INSTALL_DIR"

mkdir -p "$INSTALL_DIR/mcp-servers" "$INSTALL_DIR/skills"

# ─── 2. Detect / create Python venv ──────────────────────────────────────────
VENV="${VENV:-$INSTALL_DIR/venv}"

create_venv() {
  log "Creating Python venv at $VENV"
  if command -v python3.12 >/dev/null 2>&1; then
    PYTHON=python3.12
  elif command -v python3.11 >/dev/null 2>&1; then
    PYTHON=python3.11
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
  else
    fatal "No python3 found. Install Python 3.10+ first."
  fi

  if "$PYTHON" -m venv "$VENV" 2>/dev/null; then
    ok "Venv created with stdlib"
  else
    warn "python3-venv missing. Bootstrapping with get-pip.py"
    mkdir -p "$VENV/bin"
    "$PYTHON" -c "import os, sys; os.makedirs('$VENV/bin', exist_ok=True); \
                  os.symlink(sys.executable, '$VENV/bin/python')"
    curl -sSL https://bootstrap.pypa.io/get-pip.py | "$VENV/bin/python" - --target "$VENV/lib/python_pkgs"
    cat > "$VENV/bin/pip" <<EOF
#!/usr/bin/env bash
PYTHONPATH="$VENV/lib/python_pkgs" "$VENV/bin/python" "$VENV/lib/python_pkgs/pip" "\$@"
EOF
    chmod +x "$VENV/bin/pip"
  fi
}

if [[ ! -x "$VENV/bin/python" ]]; then
  create_venv
else
  ok "Venv already at $VENV"
fi

readonly VENV_PY="$VENV/bin/python"
readonly VENV_PIP="$VENV/bin/pip"

# ─── 3. Install Python dependencies ──────────────────────────────────────────
log "Installing required Python packages (mcp, requests, httpx)"
"$VENV_PIP" install -q --upgrade pip wheel || true
"$VENV_PIP" install -q -r "$REPO_DIR/requirements.txt" \
  || fatal "pip install failed. Check $VENV_PIP install -r requirements.txt manually."
ok "Python deps installed"

# Optional deps: prompt user
read_yn() {
  local prompt="$1"
  local default="${2:-n}"
  if [[ "${ASSUME_YES:-0}" == "1" ]]; then echo "y"; return; fi
  if [[ "${ASSUME_NO:-0}" == "1" ]]; then echo "n"; return; fi
  read -r -p "$prompt [y/N] " ans
  echo "${ans:-$default}"
}

if [[ "$(read_yn 'Install optional Python deps for sql/browser-inspect (psycopg, pymysql, playwright + Chromium ~150MB)?')" =~ ^[yY] ]]; then
  "$VENV_PIP" install -q "psycopg[binary]" pymysql playwright \
    && "$VENV_PY" -m playwright install chromium 2>&1 | tail -3 \
    && ok "Optional Python deps installed (sql + browser-inspect ready)"
fi

if [[ "$(read_yn 'Install fastembed for semantic-search (BGE-small ONNX, ~50MB on first query)?')" =~ ^[yY] ]]; then
  "$VENV_PIP" install -q fastembed numpy \
    && ok "fastembed installed (semantic-search ready)"
fi

# ─── 4. Copy MCP servers ─────────────────────────────────────────────────────
log "Copying 11 MCP servers + ElevateMCP gateway to $INSTALL_DIR/mcp-servers/"
cp -r "$REPO_SERVERS"/* "$INSTALL_DIR/mcp-servers/"
ok "MCP servers copied"

# ─── 5. Copy skills ──────────────────────────────────────────────────────────
log "Copying 3 skills to $INSTALL_DIR/skills/"
cp -r "$REPO_SKILLS"/* "$INSTALL_DIR/skills/"
ok "Skills copied: secret-scan, env-doctor, mcp-development"

# ─── 6. Generate / merge mcp.json ────────────────────────────────────────────
MCP_JSON="$INSTALL_DIR/mcp.json"
log "Generating $MCP_JSON"

generate_entries() {
  local gw_py="$INSTALL_DIR/mcp-servers/gateway/server.py"
  printf '    "ElevateMCP": {\n'
  printf '      "transport": "stdio",\n'
  printf '      "enabled": true,\n'
  printf '      "command": "%s",\n' "$VENV_PY"
  printf '      "args": ["%s"]\n' "$gw_py"
  printf '    }'
}

if [[ -f "$MCP_JSON" ]]; then
  warn "$MCP_JSON exists — backing up to ${MCP_JSON}.bak.$(date +%s)"
  cp "$MCP_JSON" "${MCP_JSON}.bak.$(date +%s)"
fi

cat > "$MCP_JSON" <<EOF
{
  "mcpServers": {
$(generate_entries)
  }
}
EOF
ok "mcp.json written ($MCP_JSON)"

# ─── 7. Optional system binaries ─────────────────────────────────────────────
if [[ "${SKIP_OPTIONAL:-0}" != "1" ]]; then
  log "Optional system binaries (recommended for full feature set)"
  echo
  echo "  • gitleaks  — enables secret-scan in 'gitleaks' mode (vs builtin patterns)"
  echo "  • tesseract — enables ocr MCP (with eng/fra languages)"
  echo "  • ripgrep   — useful for fast scans (used by skills)"
  echo "  • jq        — JSON inspection in terminals"
  echo

  if [[ "$(read_yn 'Install gitleaks 8.30+ to ~/.local/bin (no sudo needed)?')" =~ ^[yY] ]]; then
    mkdir -p "$HOME/.local/bin"
    GL_VERSION="$(curl -sL https://api.github.com/repos/gitleaks/gitleaks/releases/latest | grep '"tag_name"' | head -1 | cut -d'"' -f4 | sed 's/^v//')"
    GL_ARCH="$(uname -m)"
    [[ "$GL_ARCH" == "x86_64" ]] && GL_ARCH="x64"
    [[ "$GL_ARCH" == "aarch64" ]] && GL_ARCH="arm64"
    GL_OS="$(uname | tr '[:upper:]' '[:lower:]')"
    GL_URL="https://github.com/gitleaks/gitleaks/releases/download/v${GL_VERSION}/gitleaks_${GL_VERSION}_${GL_OS}_${GL_ARCH}.tar.gz"
    log "Downloading gitleaks ${GL_VERSION} (${GL_OS}/${GL_ARCH})"
    curl -sL "$GL_URL" | tar -xz -C "$HOME/.local/bin" gitleaks \
      && chmod +x "$HOME/.local/bin/gitleaks" \
      && ok "gitleaks installed: $($HOME/.local/bin/gitleaks version)" \
      || warn "gitleaks install failed. Manual: $GL_URL"
  fi

  if command -v apt-get >/dev/null 2>&1; then
    if [[ "$(read_yn 'Install tesseract+fra/eng + ripgrep + jq via apt (sudo)?')" =~ ^[yY] ]]; then
      sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        tesseract-ocr tesseract-ocr-fra tesseract-ocr-eng ripgrep jq \
        && ok "System packages installed"
    fi
  elif command -v brew >/dev/null 2>&1; then
    if [[ "$(read_yn 'Install tesseract + ripgrep + jq via brew?')" =~ ^[yY] ]]; then
      brew install tesseract tesseract-lang ripgrep jq \
        && ok "Homebrew packages installed"
    fi
  fi
fi

# ─── 8. Summary ──────────────────────────────────────────────────────────────
echo
ok "Installation complete."
echo
echo "  Servers installed:  $(ls "$INSTALL_DIR/mcp-servers" | wc -l)"
echo "  Skills installed:   $(ls "$INSTALL_DIR/skills" | wc -l)"
echo "  Config:             $MCP_JSON"
echo "  Venv:               $VENV"
echo
echo "Next steps:"
case "$INSTALL_DIR" in
  *commandcode*) echo "  • Restart CommandCode CLI; run /mcp to verify 'ElevateMCP' loaded (~43 tools)" ;;
  *)             echo "  • Reference $MCP_JSON in your agent's config"
                 echo "  • Or copy individual entries to your existing mcp.json" ;;
esac
echo "  • See README.md for per-MCP usage and troubleshooting"
