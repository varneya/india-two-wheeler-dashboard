#!/usr/bin/env bash
# =============================================================================
# install_backend.sh - Bootstraps the FastAPI backend on macOS or Linux
#
# Idempotent: safe to re-run. Each step skips itself if already done.
#
# Usage (from the repo root):
#   chmod +x scripts/install_backend.sh
#   ./scripts/install_backend.sh
#
# What it does:
#   1. Checks for Python 3.10+. If missing, offers to install 3.12 via brew (mac)
#      or apt (Debian/Ubuntu).
#   2. Creates backend/venv if it doesn't exist.
#   3. Upgrades pip and installs everything in backend/requirements.txt.
#   4. Prints the command to actually run the server.
# =============================================================================

set -euo pipefail

BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
CYAN="\033[36m"
RED="\033[31m"
RESET="\033[0m"

info()    { echo -e "${CYAN}[info]${RESET}  $*"; }
ok()      { echo -e "${GREEN}[ok]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[warn]${RESET}  $*"; }
err()     { echo -e "${RED}[error]${RESET} $*"; }
step()    { echo -e "\n${BOLD}$*${RESET}"; }

# Resolve repo root from script location so the user can run this from anywhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
VENV_DIR="$BACKEND_DIR/venv"
REQ_FILE="$BACKEND_DIR/requirements.txt"

if [[ ! -f "$REQ_FILE" ]]; then
  err "Could not find $REQ_FILE - is this script being run from the repo?"
  exit 1
fi

# -------------------------------------------------------------------
# 1. Python presence + version check
# -------------------------------------------------------------------
step "Step 1 - Checking Python"

find_python() {
  for c in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$c" &>/dev/null; then
      echo "$c"
      return 0
    fi
  done
  return 1
}

python_version_ok() {
  local exe="$1"
  local raw
  raw="$("$exe" --version 2>&1 || true)"
  if [[ "$raw" =~ Python\ ([0-9]+)\.([0-9]+) ]]; then
    local major="${BASH_REMATCH[1]}"
    local minor="${BASH_REMATCH[2]}"
    if [[ "$major" -eq 3 ]] && [[ "$minor" -ge 10 ]]; then
      return 0
    fi
  fi
  return 1
}

PY_EXE="$(find_python || true)"
if [[ -n "$PY_EXE" ]] && python_version_ok "$PY_EXE"; then
  ok "Using $($PY_EXE --version) at $(command -v "$PY_EXE")"
else
  if [[ -n "$PY_EXE" ]]; then
    warn "Found $($PY_EXE --version 2>&1) but need 3.10+."
  else
    warn "Python 3 not found on PATH."
  fi

  OS="$(uname -s)"
  if [[ "$OS" == "Darwin" ]]; then
    if ! command -v brew &>/dev/null; then
      err "Homebrew not found. Install it from https://brew.sh, then re-run this script."
      exit 1
    fi
    read -r -p "Install Python 3.12 via Homebrew now? (y/N) " resp
    [[ "$resp" =~ ^[Yy]$ ]] || { err "Aborting."; exit 1; }
    info "Running 'brew install python@3.12'..."
    brew install python@3.12
    PY_EXE="python3.12"
  else
    # Linux: best-effort apt; fall through with an error otherwise.
    if ! command -v apt-get &>/dev/null; then
      err "Auto-install supports apt only. Install Python 3.10+ manually for your distro and re-run."
      exit 1
    fi
    read -r -p "Install Python 3.12 via apt now? (y/N) " resp
    [[ "$resp" =~ ^[Yy]$ ]] || { err "Aborting."; exit 1; }
    info "Running 'sudo apt update && sudo apt install -y python3.12 python3.12-venv'..."
    sudo apt update
    sudo apt install -y python3.12 python3.12-venv python3-pip
    PY_EXE="python3.12"
  fi

  if ! python_version_ok "$PY_EXE"; then
    err "Python install didn't take effect. Open a new shell and re-run this script."
    exit 1
  fi
  ok "Installed $($PY_EXE --version)"
fi

# -------------------------------------------------------------------
# 2. Create the virtualenv (backend/venv)
# -------------------------------------------------------------------
step "Step 2 - Creating virtualenv at backend/venv"

if [[ -x "$VENV_DIR/bin/python" ]]; then
  ok "venv already exists - reusing"
else
  info "Running '$PY_EXE -m venv $VENV_DIR'..."
  "$PY_EXE" -m venv "$VENV_DIR"
  ok "venv created"
fi

VENV_PY="$VENV_DIR/bin/python"

# -------------------------------------------------------------------
# 3. Upgrade pip + install requirements.txt
# -------------------------------------------------------------------
step "Step 3 - Installing backend dependencies"

info "Upgrading pip inside the venv..."
"$VENV_PY" -m pip install --upgrade pip

info "Installing requirements.txt (5-10 min the first time - Prophet,"
info "  hdbscan, umap-learn, scikit-learn all need wheels or compile)..."
"$VENV_PY" -m pip install -r "$REQ_FILE"
ok "All dependencies installed"

info "Smoke-testing imports..."
"$VENV_PY" -c "import fastapi, sklearn, hdbscan, umap, prophet, psutil; print('imports OK')"

# -------------------------------------------------------------------
# Done
# -------------------------------------------------------------------
echo ""
echo -e "${BOLD}${GREEN}Backend is ready!${RESET}"
echo ""
echo -e "  venv   : ${BOLD}$VENV_DIR${RESET}"
echo -e "  Python : ${BOLD}$($VENV_PY --version)${RESET}"
echo ""
echo "To start the FastAPI server:"
echo "  cd $BACKEND_DIR"
echo "  source venv/bin/activate"
echo "  uvicorn main:app --port 8000"
echo ""
echo "Or in one line (no activation needed):"
echo "  $VENV_PY -m uvicorn main:app --app-dir $BACKEND_DIR --port 8000"
echo ""
echo "Then run scripts/install_ollama.sh to set up the LLM side."
