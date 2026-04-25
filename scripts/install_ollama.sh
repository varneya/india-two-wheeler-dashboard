#!/usr/bin/env bash
# =============================================================================
# install_ollama.sh — Sets up Ollama for local LLM theme analysis
#
# Usage:
#   chmod +x scripts/install_ollama.sh
#   ./scripts/install_ollama.sh [model]
#
# If no model is specified, defaults to llama3.2:3b (fast, works on 8 GB RAM).
# Recommended models by RAM:
#   4  GB  → phi3:mini    (2.2 GB)
#   8  GB  → llama3.2:3b  (2.0 GB) or mistral:7b (4.1 GB)
#   16 GB  → llama3.2:8b  (4.7 GB) — best balance of speed & quality
#   32 GB+ → mixtral:8x7b (26 GB)  — excellent quality
# =============================================================================

set -euo pipefail

MODEL="${1:-llama3.2:3b}"

BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
CYAN="\033[36m"
RED="\033[31m"
RESET="\033[0m"

info()    { echo -e "${CYAN}[info]${RESET}  $*"; }
success() { echo -e "${GREEN}[ok]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[warn]${RESET}  $*"; }
error()   { echo -e "${RED}[error]${RESET} $*"; }
step()    { echo -e "\n${BOLD}$*${RESET}"; }

# -------------------------------------------------------------------
# 1. Detect OS
# -------------------------------------------------------------------
step "Step 1 — Checking operating system"
OS="$(uname -s)"
if [[ "$OS" != "Darwin" ]]; then
  error "This script is designed for macOS. On Linux run: curl -fsSL https://ollama.com/install.sh | sh"
  exit 1
fi
success "macOS detected"

# -------------------------------------------------------------------
# 2. Install Ollama (via Homebrew or direct download)
# -------------------------------------------------------------------
step "Step 2 — Installing Ollama"

if command -v ollama &>/dev/null; then
  CURRENT_VERSION="$(ollama --version 2>/dev/null || echo 'unknown')"
  success "Ollama already installed ($CURRENT_VERSION)"
else
  if command -v brew &>/dev/null; then
    info "Installing via Homebrew…"
    brew install ollama
    success "Ollama installed via Homebrew"
  else
    info "Homebrew not found — downloading Ollama.app directly…"
    TMPDIR="$(mktemp -d)"
    DMG="$TMPDIR/ollama.dmg"
    info "Downloading from https://ollama.com/download/Ollama-darwin.zip …"
    curl -fsSL -o "$TMPDIR/ollama.zip" "https://ollama.com/download/Ollama-darwin.zip"
    info "Extracting…"
    unzip -q "$TMPDIR/ollama.zip" -d "$TMPDIR"
    info "Moving Ollama.app to /Applications…"
    mv "$TMPDIR/Ollama.app" /Applications/ 2>/dev/null || {
      warn "Could not move to /Applications (permission?). Moving to ~/Applications instead."
      mkdir -p ~/Applications
      mv "$TMPDIR/Ollama.app" ~/Applications/
    }
    rm -rf "$TMPDIR"
    # Symlink the CLI binary
    OLLAMA_BIN="/Applications/Ollama.app/Contents/MacOS/ollama"
    if [[ ! -f "$OLLAMA_BIN" ]]; then
      OLLAMA_BIN="$HOME/Applications/Ollama.app/Contents/MacOS/ollama"
    fi
    if [[ -f "$OLLAMA_BIN" ]] && [[ ! -L /usr/local/bin/ollama ]]; then
      sudo ln -sf "$OLLAMA_BIN" /usr/local/bin/ollama 2>/dev/null || \
        warn "Could not create /usr/local/bin/ollama symlink. Add $OLLAMA_BIN to your PATH."
    fi
    success "Ollama.app installed"
  fi
fi

# -------------------------------------------------------------------
# 3. Start Ollama server (if not already running)
# -------------------------------------------------------------------
step "Step 3 — Starting Ollama server"

if curl -sf http://localhost:11434/api/tags &>/dev/null; then
  success "Ollama server is already running"
else
  info "Starting Ollama server in the background…"
  ollama serve &>/tmp/ollama_serve.log &
  OLLAMA_PID=$!
  info "Waiting for server to become ready (pid $OLLAMA_PID)…"
  for i in $(seq 1 20); do
    if curl -sf http://localhost:11434/api/tags &>/dev/null; then
      success "Ollama server is up"
      break
    fi
    sleep 1
    if [[ $i -eq 20 ]]; then
      error "Ollama server did not start in time. Check /tmp/ollama_serve.log"
      exit 1
    fi
  done
fi

# -------------------------------------------------------------------
# 4. Pull the requested model
# -------------------------------------------------------------------
step "Step 4 — Pulling model: $MODEL"

# Check if already pulled
PULLED="$(ollama list 2>/dev/null | awk 'NR>1 {print $1}' || echo '')"
if echo "$PULLED" | grep -qF "$MODEL"; then
  success "Model $MODEL is already pulled"
else
  info "Pulling $MODEL — this may take a few minutes depending on your connection…"
  ollama pull "$MODEL"
  success "Model $MODEL pulled successfully"
fi

# -------------------------------------------------------------------
# 5. Quick smoke test
# -------------------------------------------------------------------
step "Step 5 — Smoke test"
info "Sending a quick prompt to $MODEL…"
RESPONSE="$(ollama run "$MODEL" 'Reply with only the word: ready' --nowordwrap 2>/dev/null | head -1 || echo '')"
if [[ -n "$RESPONSE" ]]; then
  success "Model responded: \"$RESPONSE\""
else
  warn "No response from smoke test — model may still work, check manually."
fi

# -------------------------------------------------------------------
# Done
# -------------------------------------------------------------------
echo ""
echo -e "${BOLD}${GREEN}✓ Ollama is ready!${RESET}"
echo ""
echo -e "  Model pulled : ${BOLD}$MODEL${RESET}"
echo -e "  API base URL : ${BOLD}http://localhost:11434${RESET}"
echo ""
echo -e "  In the dashboard, select ${BOLD}LLM Analysis${RESET} → choose ${BOLD}Local (Ollama)${RESET}"
echo -e "  and pick ${BOLD}$MODEL${RESET} from the model list."
echo ""
echo -e "To pull a different model later:"
echo -e "  ${CYAN}ollama pull mistral:7b${RESET}"
echo ""
echo -e "To keep the server running across reboots (macOS):"
echo -e "  ${CYAN}brew services start ollama${RESET}  (if installed via Homebrew)"
