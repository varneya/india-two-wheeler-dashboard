#!/usr/bin/env bash
# Deploy to an Oracle Always Free (or other Debian/Ubuntu) VM after merging
# deployment changes into the remote default branch. Run as root with:
#   TWB_DUCKDNS_DOMAIN=my-bikes TWB_DUCKDNS_TOKEN=<DuckDNS UUID> bash scripts/setup_oracle_vm.sh
# Open inbound TCP 80/443 and point DuckDNS at the VM first.
#
# Groq is the preferred hosted LLM: provision GROQ_API_KEY in the root-owned
# /etc/twowheeler/env. To schedule theme batches, also configure
# THEMES_LLM_BACKEND=groq:<model-id> there. Existing provider credentials and
# ADMIN_TOKEN are preserved; a missing/empty admin token is securely generated.
# Never source this file as shell code. Tokens are never displayed by this script.
# Local models are optional: TWB_INSTALL_OLLAMA=true (default: false).
# TWB_USER defaults to a dedicated system account, twowheeler; TWB_REPO defaults
# to /opt/twowheeler. Dirty checkouts and unmerged local commits require manual
# resolution; deployment never stashes, resets, or discards server edits.

# Disable tracing before accessing secrets, including when invoked with bash -x.
set +x
set -euo pipefail

info() { printf '[info] %s\n' "$*"; }
die() { printf '[error] %s\n' "$*" >&2; exit 1; }

validate_inputs() {
  TWB_DUCKDNS_DOMAIN="${TWB_DUCKDNS_DOMAIN:-}"
  TWB_DUCKDNS_TOKEN="${TWB_DUCKDNS_TOKEN:-}"
  TWB_USER="${TWB_USER:-twowheeler}"
  TWB_REPO="${TWB_REPO:-/opt/twowheeler}"
  TWB_REPO_URL="${TWB_REPO_URL:-https://github.com/varneya/india-two-wheeler-dashboard.git}"
  TWB_INSTALL_OLLAMA="${TWB_INSTALL_OLLAMA:-false}"
  # Embeddings remain an optional feature; Groq theme batches need neither
  # an embedding model nor the optional ML dependencies.
  TWB_EMBEDDING_BACKEND="${TWB_EMBEDDING_BACKEND:-ollama}"
  TWB_OLLAMA_MODELS="${TWB_OLLAMA_MODELS:-nomic-embed-text qwen3:8b}"
  [[ ${#TWB_DUCKDNS_DOMAIN} -le 63 && "$TWB_DUCKDNS_DOMAIN" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] \
    || die 'TWB_DUCKDNS_DOMAIN must be one lowercase DNS label (1-63 characters).'
  [[ "$TWB_DUCKDNS_TOKEN" =~ ^[[:xdigit:]]{8}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{12}$ ]] \
    || die 'TWB_DUCKDNS_TOKEN must be a DuckDNS UUID token.'
  [[ "$TWB_USER" != root && "$TWB_USER" =~ ^[a-z_][a-z0-9_-]*$ ]] \
    || die 'TWB_USER must be a non-root service account name.'
  # These values enter systemd/Caddy templates, so reject syntax and specifiers.
  [[ "$TWB_REPO" =~ ^/[a-zA-Z0-9_./-]+$ && "$TWB_REPO" != / ]] \
    || die 'TWB_REPO must be an absolute path without whitespace or template syntax.'
  [[ "$TWB_INSTALL_OLLAMA" == true || "$TWB_INSTALL_OLLAMA" == false ]] \
    || die 'TWB_INSTALL_OLLAMA must be true or false.'
  [[ "$TWB_EMBEDDING_BACKEND" == ollama || "$TWB_EMBEDDING_BACKEND" == sentence_transformers ]] \
    || die 'Unsupported embedding backend.'
  TWB_DOMAIN="${TWB_DUCKDNS_DOMAIN}.duckdns.org"
  TWB_ORIGIN_HTTPS="https://${TWB_DOMAIN}"
  export TWB_USER TWB_REPO TWB_DOMAIN TWB_ORIGIN_HTTPS TWB_EMBEDDING_BACKEND
}

require_root() { [[ "$EUID" -eq 0 ]] || die 'Run as root (sudo).'; }

# Output only a boolean scheduler flag, never values from the env file.
# Managed keys use an intentionally conservative single-line subset of systemd
# EnvironmentFile syntax; other lines (including provider credentials) survive
# byte for byte. Ambiguous managed values fail closed without printing them.
prepare_env() {
  python3 - "$1" <<'PY'
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile

path = Path(sys.argv[1])
try:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError()
    raw = path.read_bytes() if path.exists() else b''
    text = raw.decode('utf-8')
    values = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(('#', ';')):
            continue
        # Reject multiline/continued assignments anywhere: otherwise a token
        # assignment could become part of a preceding provider's quoted value.
        assignment = re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*\s*=(.*)', stripped)
        if not assignment or stripped.endswith('\\'):
            raise ValueError()
        raw_value = assignment.group(1).strip()
        if raw_value.startswith(("'", '"')):
            if (len(raw_value) < 2 or raw_value[-1] != raw_value[0]
                    or raw_value[0] in raw_value[1:-1] or '\\' in raw_value):
                raise ValueError()
        match = re.match(r'^\s*(ADMIN_TOKEN|THEMES_LLM_BACKEND)\s*=(.*)$', line)
        if match:
            value = match.group(2).strip()
            if value.startswith(("'", '"')):
                quote = value[0]
                if len(value) < 2 or value[-1] != quote or quote in value[1:-1]:
                    raise ValueError()
                value = value[1:-1]
            elif re.search(r'''[\s'"\\]''', value):
                raise ValueError()
            if '\\' in value or any(ord(c) < 32 for c in value):
                raise ValueError()
            values[match.group(1)] = value
    if not values.get('ADMIN_TOKEN', '').strip():
        # Appending overrides earlier empty entries, preserving every existing
        # credential line.
        raw += (b'\n' if raw and not raw.endswith(b'\n') else b'')
        raw += ('ADMIN_TOKEN=' + secrets.token_urlsafe(48) + '\n').encode()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.env-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print('true' if values.get('THEMES_LLM_BACKEND', '').strip() else 'false')
except (OSError, ValueError, UnicodeError):
    sys.exit('Cannot safely prepare deployment env file; check permissions and single-line managed assignments.')
PY
}

install_packages() {
  command -v apt-get >/dev/null || die 'This script requires Debian/Ubuntu.'
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl gnupg git build-essential sqlite3 \
    python3 python3-venv python3-pip gettext-base sudo
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' \
    || die 'Python 3.12+ is required; use Ubuntu 24.04+ or install it before retrying.'
  if ! command -v caddy >/dev/null; then
    curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
      | gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
      > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq
    apt-get install -y -qq caddy
  fi
}

ensure_service_user() {
  if ! id -u "$TWB_USER" >/dev/null 2>&1; then
    useradd --system --user-group --create-home --home-dir /var/lib/twowheeler \
      --shell /usr/sbin/nologin "$TWB_USER"
  fi
  [[ "$(id -u "$TWB_USER")" != 0 ]] || die 'Service account must not have UID 0.'
  TWB_GROUP="$(id -gn "$TWB_USER")"
  [[ "$TWB_GROUP" =~ ^[a-z_][a-z0-9_-]*$ ]] || die 'Unsupported service account group name.'
  export TWB_GROUP
}

repo_git() { sudo -u "$TWB_USER" git -C "$TWB_REPO" "$@"; }
update_repo() {
  local status remote_ref branch
  if [[ ! -e "$TWB_REPO" ]]; then
    install -d -o "$TWB_USER" -g "$TWB_GROUP" "$TWB_REPO"
    sudo -u "$TWB_USER" git clone -- "$TWB_REPO_URL" "$TWB_REPO"
  fi
  [[ -d "$TWB_REPO/.git" ]] || die 'TWB_REPO must be a repository checkout.'
  chown -R "$TWB_USER:$TWB_GROUP" "$TWB_REPO"
  status="$(repo_git status --porcelain --untracked-files=all)"
  [[ -z "$status" ]] \
    || die 'Server checkout has local edits; resolve them before deployment.'
  repo_git fetch origin
  repo_git remote set-head origin --auto >/dev/null
  remote_ref="$(repo_git symbolic-ref refs/remotes/origin/HEAD)"
  [[ "$remote_ref" == refs/remotes/origin/* ]] || die 'Cannot identify remote default branch.'
  branch="${remote_ref#refs/remotes/origin/}"
  repo_git merge-base --is-ancestor HEAD "$remote_ref" \
    || die 'Server checkout has commits absent from the remote default; merge them before deployment.'
  if repo_git show-ref --verify --quiet "refs/heads/$branch"; then
    repo_git merge-base --is-ancestor "refs/heads/$branch" "$remote_ref" \
      || die 'Local default branch has unmerged commits; resolve them before deployment.'
  fi
  repo_git checkout "$branch"
  repo_git merge --ff-only "$remote_ref"
}

install_backend() { sudo -u "$TWB_USER" bash "$TWB_REPO/scripts/install_backend.sh"; }

wait_for_health() {
  local url="$1" attempt
  for attempt in {1..30}; do
    if curl --fail --silent --show-error --connect-timeout 5 --max-time 10 \
      --output /dev/null "$url" 2>/dev/null; then
      return 0
    fi
    sleep 2
  done
  die 'Health check failed; inspect the backend and Caddy service logs.'
}

install_ollama() {
  [[ "$TWB_INSTALL_OLLAMA" == true ]] || return 0
  if ! command -v ollama >/dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh
  fi
  systemctl enable --now ollama.service
  wait_for_health http://127.0.0.1:11434/api/tags
  local model
  local -a models
  read -r -a models <<< "$TWB_OLLAMA_MODELS"
  for model in "${models[@]}"; do
    [[ "$model" =~ ^[a-zA-Z0-9][a-zA-Z0-9_./:-]*$ ]] || die 'Invalid Ollama model name.'
    ollama pull "$model"
  done
}

render_service() {
  envsubst '$TWB_USER $TWB_GROUP $TWB_REPO $TWB_ORIGIN_HTTPS $TWB_EMBEDDING_BACKEND' \
    < "$1" | sed "s/^Group=${TWB_USER}$/Group=${TWB_GROUP}/" > "$2"
}

install_units() {
  local unit_dir="$1" config_dir="$2"
  install -d -m 755 "$unit_dir"
  render_service "$TWB_REPO/deploy/twowheeler-backend.service" "$unit_dir/twowheeler-backend.service"
  cp "$TWB_REPO/deploy/refresh-all.service" "$unit_dir/refresh-all.service"
  cp "$TWB_REPO/deploy/refresh-all.timer" "$unit_dir/refresh-all.timer"
  # umask 077 is set before creating either credential file.
  printf 'TWB_DUCKDNS_DOMAIN=%s\nTWB_DUCKDNS_TOKEN=%s\n' \
    "$TWB_DUCKDNS_DOMAIN" "$TWB_DUCKDNS_TOKEN" > "$config_dir/duckdns.env"
  chmod 600 "$config_dir/duckdns.env"
  cp "$TWB_REPO/deploy/duckdns-update.service" "$unit_dir/duckdns-update.service"
  cp "$TWB_REPO/deploy/duckdns-update.timer" "$unit_dir/duckdns-update.timer"
  if [[ "$THEMES_CONFIGURED" == true ]]; then
    render_service "$TWB_REPO/deploy/themes-batch.service" "$unit_dir/themes-batch.service"
    cp "$TWB_REPO/deploy/themes-batch.timer" "$unit_dir/themes-batch.timer"
  elif [[ -e "$unit_dir/themes-batch.timer" ]]; then
    # A re-run after removing the backend setting must stop future batch jobs.
    systemctl disable --now themes-batch.timer
  fi
  systemctl daemon-reload
  systemctl enable twowheeler-backend.service
  systemctl restart twowheeler-backend.service
  wait_for_health http://127.0.0.1:8000/api/health
  systemctl enable --now refresh-all.timer
  systemctl enable --now duckdns-update.timer
  if [[ "$THEMES_CONFIGURED" == true ]]; then
    systemctl enable --now themes-batch.timer
  fi
  systemctl start duckdns-update.service
}

configure_caddy() {
  local config_dir="$1" candidate
  install -d -m 755 "$config_dir" /var/log/caddy
  chown caddy:caddy /var/log/caddy
  candidate="$(mktemp "$config_dir/.Caddyfile.XXXXXX")"
  envsubst '$TWB_DOMAIN' < "$TWB_REPO/deploy/Caddyfile" > "$candidate"
  if ! caddy validate --config "$candidate" --adapter caddyfile; then
    rm -f "$candidate"
    die 'Caddy configuration validation failed; existing config was preserved.'
  fi
  install -m 644 "$candidate" "$config_dir/Caddyfile"
  rm -f "$candidate"
  systemctl enable caddy
  systemctl reload caddy || systemctl restart caddy
}

main() {
  validate_inputs
  require_root
  umask 077
  # Prepare auth before package installation can start Caddy, or any service
  # is restarted. Python 3 is supplied by supported Ubuntu/Debian VM images.
  install -d -m 700 -o root -g root /etc/twowheeler
  THEMES_CONFIGURED="$(prepare_env /etc/twowheeler/env)"
  install_packages
  ensure_service_user
  update_repo
  install_backend
  install_ollama
  install_units /etc/systemd/system /etc/twowheeler
  configure_caddy /etc/caddy
  wait_for_health "${TWB_ORIGIN_HTTPS}/api/health"
  info "Setup complete: ${TWB_ORIGIN_HTTPS}/api/health"
  info 'Admin token and provider credentials: /etc/twowheeler/env (root-only).'
  info 'Groq theme batches require GROQ_API_KEY and THEMES_LLM_BACKEND in that file.'
  info 'Logs: journalctl -u twowheeler-backend -f'
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
