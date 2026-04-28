#!/usr/bin/env bash
# =============================================================================
# install_ollama.sh — Sets up Ollama for local LLM theme analysis
#
# Usage:
#   chmod +x scripts/install_ollama.sh
#   ./scripts/install_ollama.sh [model]
#
# If no model is specified, defaults to qwen3:4b (fast, works on 4 GB RAM,
# beats llama3.2:3b on instruction-following + JSON discipline at a similar
# footprint). Recommended models by RAM (current as of April 2026):
#   4  GB  → qwen3:4b      (2.5 GB) — default; gemma3:4b for multilingual
#   8  GB  → qwen3:8b      (5.2 GB) — top open 8B; granite3.3:8b for tight JSON
#   16 GB  → qwen3:14b     (9.3 GB) — best dense 14B; phi4:14b alternative
#   32 GB  → qwen3:32b     (20 GB)  — best dense 32B; deepseek-r1:32b for reasoning
#   48 GB+ → llama3.3:70b  (43 GB)  — Meta's best dense; deepseek-r1:70b reasoner
# =============================================================================

set -euo pipefail

MODEL="${1:-qwen3:4b}"

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
echo -e "  ${CYAN}ollama pull qwen3:8b${RESET}    # 8 GB RAM, top open 8B"
echo -e "  ${CYAN}ollama pull qwen3:14b${RESET}   # 16 GB RAM"
echo -e "  ${CYAN}ollama pull qwen3:32b${RESET}   # 32 GB RAM"
echo ""
echo -e "To keep the server running across reboots (macOS):"
echo -e "  ${CYAN}brew services start ollama${RESET}  (if installed via Homebrew)"
