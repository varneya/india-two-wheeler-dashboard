#!/usr/bin/env bash
# =============================================================================
# setup_oracle_vm.sh — single-shot deploy of the dashboard backend onto a
# fresh Oracle Cloud (or any Debian/Ubuntu) Linux VM with a public IP.
#
# What it does, in order:
#   1. Validates inputs (DuckDNS subdomain + token, optional Anthropic key)
#   2. Updates apt + installs Python 3.12, git, curl, caddy
#   3. Clones (or pulls) the repo at /opt/twowheeler
#   4. Runs scripts/install_backend.sh (Python venv + pip install)
#   5. Installs Ollama via the official one-liner; pulls
#      nomic-embed-text + qwen3:8b
#   6. Writes the systemd units from deploy/ with TWB_* placeholders
#      substituted; enables + starts them
#   7. Writes /etc/caddy/Caddyfile with the DuckDNS subdomain + reverse_proxy
#      to localhost:8000; reloads Caddy so it picks up the cert via HTTP-01
#   8. Registers the daily refresh-all systemd timer + the every-5-min
#      DuckDNS A-record updater
#   9. Prints final URLs and curl probes you can run to verify
#
# Idempotent: safe to re-run when you change the domain / token / anthropic
# key. Existing units are reloaded; pulled Ollama models are skipped.
#
# Usage (as root or with sudo):
#   sudo \
#     TWB_DUCKDNS_DOMAIN=varneya-bikes \
#     TWB_DUCKDNS_TOKEN=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \
#     TWB_ANTHROPIC_KEY=sk-ant-... \
#     TWB_EMBEDDING_BACKEND=ollama \
#     bash scripts/setup_oracle_vm.sh
#
# After provisioning the Oracle VM, BEFORE running this:
#   - Open ports 22, 80, 443 in the VCN security list AND
#     `sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT`
#     `sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT`
#     (Oracle Linux ships with a strict default iptables; Ubuntu does not.)
#   - Sign up at duckdns.org, create a subdomain, and copy the token.
#   - Set the subdomain's A record to this VM's public IP via the
#     DuckDNS dashboard — the every-5-min updater keeps it current after that.
# =============================================================================

set -euo pipefail

# ---- Colour helpers (parallel to install_backend.sh) ------------------------
BOLD="\033[1m"; GREEN="\033[32m"; YELLOW="\033[33m"
CYAN="\033[36m"; RED="\033[31m"; RESET="\033[0m"
info()    { echo -e "${CYAN}[info]${RESET}  $*"; }
ok()      { echo -e "${GREEN}[ok]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[warn]${RESET}  $*"; }
err()     { echo -e "${RED}[error]${RESET} $*"; }
step()    { echo -e "\n${BOLD}$*${RESET}"; }

# ---- Inputs / defaults ------------------------------------------------------
TWB_DUCKDNS_DOMAIN="${TWB_DUCKDNS_DOMAIN:-}"
TWB_DUCKDNS_TOKEN="${TWB_DUCKDNS_TOKEN:-}"
TWB_ANTHROPIC_KEY="${TWB_ANTHROPIC_KEY:-}"
TWB_EMBEDDING_BACKEND="${TWB_EMBEDDING_BACKEND:-ollama}"
TWB_USER="${TWB_USER:-${SUDO_USER:-$USER}}"
TWB_REPO="${TWB_REPO:-/opt/twowheeler}"
TWB_REPO_URL="${TWB_REPO_URL:-https://github.com/varneya/india-two-wheeler-dashboard.git}"
TWB_OLLAMA_MODELS="${TWB_OLLAMA_MODELS:-nomic-embed-text qwen3:8b}"

if [[ -z "$TWB_DUCKDNS_DOMAIN" || -z "$TWB_DUCKDNS_TOKEN" ]]; then
  err "TWB_DUCKDNS_DOMAIN and TWB_DUCKDNS_TOKEN are required."
  err "See the comment header in this script for the full env-var list."
  exit 1
fi
TWB_DOMAIN="${TWB_DUCKDNS_DOMAIN}.duckdns.org"
TWB_ORIGIN_HTTPS="https://${TWB_DOMAIN}"
export TWB_DUCKDNS_DOMAIN TWB_DUCKDNS_TOKEN TWB_DOMAIN TWB_ORIGIN_HTTPS \
       TWB_USER TWB_REPO TWB_EMBEDDING_BACKEND

if [[ "$EUID" -ne 0 ]]; then
  err "Run as root (sudo)."
  exit 1
fi
if [[ "$TWB_USER" == "root" ]]; then
  warn "TWB_USER is root — backend will run as root. Consider creating a 'twowheeler' user."
fi

# -------------------------------------------------------------------
# 1. apt deps + Caddy
# -------------------------------------------------------------------
step "Step 1 — apt deps + Caddy"

if ! command -v apt-get &>/dev/null; then
  err "This script targets Debian/Ubuntu. For other distros, install python3, git, curl, caddy manually and re-run."
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq software-properties-common ca-certificates curl gnupg \
    git build-essential sqlite3

# Python 3.12 — usually present on Ubuntu 24.04+; install python3.12-venv
# explicitly because the slim base image doesn't always include it.
apt-get install -y -qq python3 python3-venv python3-pip

# Caddy via the official apt repo (ships v2 with auto Let's Encrypt)
if ! command -v caddy &>/dev/null; then
  info "installing Caddy from the official repo..."
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
    | tee /etc/apt/sources.list.d/caddy-stable.list > /dev/null
  apt-get update -qq
  apt-get install -y -qq caddy
  ok "Caddy installed"
else
  ok "Caddy already installed"
fi

# envsubst for templating the systemd units
apt-get install -y -qq gettext-base

# -------------------------------------------------------------------
# 2. Clone / pull the repo
# -------------------------------------------------------------------
step "Step 2 — repo at $TWB_REPO"

if [[ -d "$TWB_REPO/.git" ]]; then
  info "pulling latest..."
  git -C "$TWB_REPO" pull --rebase --autostash
else
  info "cloning $TWB_REPO_URL ..."
  mkdir -p "$(dirname "$TWB_REPO")"
  git clone "$TWB_REPO_URL" "$TWB_REPO"
fi
chown -R "$TWB_USER:$TWB_USER" "$TWB_REPO"

# -------------------------------------------------------------------
# 3. Backend Python deps via the existing install_backend.sh
# -------------------------------------------------------------------
step "Step 3 — backend venv + deps"

sudo -u "$TWB_USER" bash "$TWB_REPO/scripts/install_backend.sh"

# Optional Anthropic key
if [[ -n "$TWB_ANTHROPIC_KEY" ]]; then
  ENV_FILE="$TWB_REPO/backend/.env"
  if grep -q "^ANTHROPIC_API_KEY=" "$ENV_FILE" 2>/dev/null; then
    sed -i "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=$TWB_ANTHROPIC_KEY|" "$ENV_FILE"
  else
    echo "ANTHROPIC_API_KEY=$TWB_ANTHROPIC_KEY" >> "$ENV_FILE"
  fi
  chown "$TWB_USER:$TWB_USER" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  ok "ANTHROPIC_API_KEY written to backend/.env (mode 600)"
fi

# -------------------------------------------------------------------
# 4. Ollama install + model pulls
# -------------------------------------------------------------------
step "Step 4 — Ollama + models"

if ! command -v ollama &>/dev/null; then
  info "installing Ollama (official one-liner)..."
  curl -fsSL https://ollama.com/install.sh | sh
  ok "Ollama installed"
else
  ok "Ollama already installed"
fi

# Wait briefly for Ollama's own systemd service to come up
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -sf http://localhost:11434/api/tags -o /dev/null; then break; fi
  sleep 1
  if [[ $i -eq 10 ]]; then warn "Ollama API not responding after 10s — model pulls will retry"; fi
done

for model in $TWB_OLLAMA_MODELS; do
  if ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qF "$model"; then
    ok "model $model already pulled"
  else
    info "pulling $model (may take several minutes)..."
    ollama pull "$model"
    ok "model $model pulled"
  fi
done

# -------------------------------------------------------------------
# 5. systemd units (backend + refresh timer + DuckDNS updater)
# -------------------------------------------------------------------
step "Step 5 — systemd units"

# Backend unit
envsubst '$TWB_USER $TWB_REPO $TWB_ORIGIN_HTTPS $TWB_EMBEDDING_BACKEND' \
  < "$TWB_REPO/deploy/twowheeler-backend.service" \
  > /etc/systemd/system/twowheeler-backend.service

# Refresh timer + service (no substitution needed)
cp "$TWB_REPO/deploy/refresh-all.service" /etc/systemd/system/refresh-all.service
cp "$TWB_REPO/deploy/refresh-all.timer"   /etc/systemd/system/refresh-all.timer

# DuckDNS updater — needs a small env file with the token
mkdir -p /etc/twowheeler
cat > /etc/twowheeler/duckdns.env <<EOF
TWB_DUCKDNS_DOMAIN=$TWB_DUCKDNS_DOMAIN
TWB_DUCKDNS_TOKEN=$TWB_DUCKDNS_TOKEN
EOF
chmod 600 /etc/twowheeler/duckdns.env

cp "$TWB_REPO/deploy/duckdns-update.service" /etc/systemd/system/duckdns-update.service
cp "$TWB_REPO/deploy/duckdns-update.timer"   /etc/systemd/system/duckdns-update.timer

systemctl daemon-reload
systemctl enable --now twowheeler-backend.service
systemctl enable --now refresh-all.timer
systemctl enable --now duckdns-update.timer

# Trigger the DuckDNS update once immediately so the A record is correct
# before Caddy tries to fetch a cert via HTTP-01.
systemctl start duckdns-update.service || true

# -------------------------------------------------------------------
# 6. Caddyfile + reload
# -------------------------------------------------------------------
step "Step 6 — Caddy (TLS via Let's Encrypt)"

mkdir -p /var/log/caddy
chown caddy:caddy /var/log/caddy 2>/dev/null || true

envsubst '$TWB_DOMAIN' \
  < "$TWB_REPO/deploy/Caddyfile" \
  > /etc/caddy/Caddyfile

systemctl reload caddy || systemctl restart caddy

# -------------------------------------------------------------------
# 7. Verify
# -------------------------------------------------------------------
step "Step 7 — verify"

sleep 5  # Caddy fetches cert + hands off backend
PUBLIC_IP="$(curl -fsS https://api.ipify.org || echo 'unknown')"

echo
echo -e "  Backend (local) : $(curl -sf http://127.0.0.1:8000/api/health || echo 'not yet ready, check journalctl -u twowheeler-backend -f')"
echo -e "  Backend (https) : (Caddy is fetching cert; first request can take 30-60s)"
echo
echo -e "${BOLD}${GREEN}Setup complete.${RESET}"
echo
echo -e "  Public IP            : ${BOLD}$PUBLIC_IP${RESET}"
echo -e "  DuckDNS subdomain    : ${BOLD}$TWB_DOMAIN${RESET}  (must point at $PUBLIC_IP)"
echo -e "  Backend (HTTPS)      : ${BOLD}https://$TWB_DOMAIN/api/health${RESET}"
echo -e "  systemd units        : twowheeler-backend, refresh-all.timer, duckdns-update.timer, ollama"
echo -e "  Logs                 : journalctl -u twowheeler-backend -f"
echo
echo -e "${BOLD}Next:${RESET}"
echo -e "  1. Verify TLS:        curl -fsS https://$TWB_DOMAIN/api/health"
echo -e "  2. Trigger a refresh: curl -X POST https://$TWB_DOMAIN/api/refresh-all"
echo -e "  3. Update the GitHub Pages workflow's VITE_API_BASE to point here:"
echo -e "       VITE_API_BASE=https://$TWB_DOMAIN/api"
echo -e "     Then push to main; the Pages workflow rebuilds + deploys."
echo
