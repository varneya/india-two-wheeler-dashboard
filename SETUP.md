# Setup & Dependencies

This guide walks you through installing everything needed to run the India Two-Wheeler Dashboard — from the lightest setup (sales charts only) to the full stack (all five theming methods, including local LLM via Ollama).

> **Tip:** if you only want to browse the data and don't care about LLM/ML theme analysis, you can skip Sections 5 and 6 entirely.

---

## Quickstart with the hosted UI

If you don't want to clone & build the frontend yourself, the hosted bundle at
**<https://varneya.github.io/india-two-wheeler-dashboard/>** does it for you.
The UI runs in your browser; the data scrapers, SQLite store, and ML/LLM
inference all run on **your** machine.

1. Open the URL above. It auto-lands on the **Setup** tab and shows live
   status pills (Backend / Ollama / Models).
2. Run the backend locally (Sections 2 + 3 below).
3. Start Ollama with the hosted origin allowlisted so the browser can reach it:

   ```bash
   OLLAMA_ORIGINS="https://varneya.github.io" ollama serve
   ```

4. The Setup tab polls every ~8 s — pills go green and the rest of the
   tabs come alive.

The hosted frontend bundles a build-time `VITE_API_BASE=http://localhost:8000/api`,
so it always calls *your* machine — never a third-party server. (The optional
Anthropic Claude API call, only triggered by the "LLM → Claude" theme method,
is the one exception.)

---

## What do you actually need?

Pick the row that matches what you want and install only those sections.

| You want to... | Sections needed |
|---|---|
| Browse sales charts, reviews, FADA data | 1, 2, 3, 4 |
| Run keyword / TF-IDF theming | 1, 2, 3, 4 |
| Run semantic / BERTopic theming (local embeddings) | 1, 2, 3, 4, **5** |
| Run LLM theming on your machine | 1, 2, 3, 4, **5** |
| Run LLM theming via Anthropic Claude | 1, 2, 3, 4, **6** |
| **The full experience (all 5 methods)** | **1–6** |

---

## 1. System prerequisites

| Tool | Minimum version | Check |
|---|---|---|
| **Python** | 3.10+ | `python3 --version` |
| **Node.js** | 20+ | `node --version` |
| **npm** | 10+ (ships with Node) | `npm --version` |
| **Git** | any recent | `git --version` |

### Install if missing

**macOS** (recommended: [Homebrew](https://brew.sh))
```bash
brew install python@3.12 node git
```

**Ubuntu / Debian**
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nodejs npm git
```

**Windows** — install via [winget](https://learn.microsoft.com/en-us/windows/package-manager/winget/):
```powershell
winget install Python.Python.3.12 OpenJS.NodeJS Git.Git
```

---

## 2. Clone the repository

```bash
git clone https://github.com/varneya/india-two-wheeler-dashboard.git
cd india-two-wheeler-dashboard
```

---

## 3. Backend (FastAPI + Python)

> **Recommended: bundled bootstrap scripts.** They check Python version, offer to install Python 3.12 if missing (Homebrew on macOS, apt on Debian/Ubuntu, winget on Windows), create the venv, upgrade pip, and `pip install -r requirements.txt` in one shot. Idempotent — safe to re-run.
>
> **macOS / Linux:**
> ```bash
> chmod +x scripts/install_backend.sh
> ./scripts/install_backend.sh
> ```
> **Windows:**
> ```powershell
> scripts\install_backend.cmd
> ```
> (The `.cmd` wrapper invokes PowerShell with `-ExecutionPolicy Bypass` so the
> bundled `.ps1` runs even on a fresh Windows machine where the default policy
> blocks unsigned scripts. You can also double-click it from Explorer.)
>
> If you'd rather do it by hand, the manual steps follow.

### 3a. Create and activate a virtual environment

```bash
cd backend
python3 -m venv venv
source venv/bin/activate          # macOS / Linux
# venv\Scripts\activate           # Windows PowerShell
```

### 3b. Install Python packages

The bundled `requirements.txt` covers core deps. The full list (including ML deps used by `themes_semantic` and `themes_bertopic`) is:

```bash
pip install \
  fastapi \
  "uvicorn[standard]" \
  requests \
  beautifulsoup4 \
  anthropic \
  python-dotenv \
  pdfplumber \
  numpy \
  pandas \
  scikit-learn \
  hdbscan \
  umap-learn \
  prophet
```

**Package roles:**

| Package | Used by | Purpose |
|---|---|---|
| `fastapi` | `main.py` | HTTP API framework |
| `uvicorn[standard]` | `main.py` | ASGI server |
| `requests` | scrapers, themes_embeddings | HTTP client (RushLane, BikeWale, BikeDekho, ZigWheels, Reddit, Ollama) |
| `beautifulsoup4` | `scraper.py`, `reviews_scraper.py` | HTML parsing |
| `anthropic` | `themes_llm.py` | Claude API client |
| `python-dotenv` | `main.py` | Load `.env` |
| `pdfplumber` | `fada_scraper.py` | Parse FADA monthly PDFs |
| `numpy` | embeddings, clustering, forecast | Numerical arrays |
| `pandas` | `forecast.py` | Period-indexed monthly series |
| `scikit-learn` | `themes_tfidf.py`, fallback in semantic | TF-IDF, KMeans, silhouette |
| `hdbscan` | `themes_semantic.py`, `themes_bertopic.py` | Density-based clustering |
| `umap-learn` | `themes_bertopic.py` | Dimensionality reduction |
| `prophet` | `forecast.py` | Sales forecasting (yearly seasonality) |

> **Heads-up:** `hdbscan` and `umap-learn` compile native code on install. On macOS you may need Xcode CLI tools (`xcode-select --install`); on Ubuntu, `sudo apt install build-essential python3-dev`. On Windows, install the Microsoft C++ Build Tools.

> **Prophet footprint:** `prophet` pulls in `cmdstanpy` + `matplotlib` and adds ~200 MB to the venv. The first `import prophet` in a fresh install can take 30–60s while it bootstraps the STAN backend; subsequent imports are fast. If install fails on macOS, see <https://facebook.github.io/prophet/docs/installation.html>.

---

## 4. Frontend (React + Vite)

```bash
cd ../frontend
npm install
```

This pulls in everything from `package.json`:

**Runtime dependencies:**
- `react` 19, `react-dom` 19
- `@tanstack/react-query` — server-state caching
- `axios` — HTTP client
- `recharts` — charts
- `@radix-ui/*` (accordion, collapsible, dialog, tabs, slot) — accessible UI primitives
- `cmdk` — ⌘K command palette
- `lucide-react` — icons
- `sonner` — toast notifications

**Dev dependencies:**
- `vite` 8, `@vitejs/plugin-react`
- `typescript` 6
- `tailwindcss` 4, `@tailwindcss/vite`, `tw-animate-css`
- `class-variance-authority`, `clsx`, `tailwind-merge` — Tailwind utilities
- `eslint` 9, `eslint-plugin-react-hooks`, `eslint-plugin-react-refresh`, `typescript-eslint`
- `@types/node`, `@types/react`, `@types/react-dom`

---

## 5. Optional — Local LLM via Ollama

Required for: **semantic theming**, **BERTopic theming**, and the **LLM (Ollama backend)** option of the LLM theme method.

### 5a. Install Ollama

**macOS — easiest:** use the bundled installer script (auto-installs + pulls a default model + runs a smoke test):

```bash
chmod +x scripts/install_ollama.sh
./scripts/install_ollama.sh                  # default: llama3.2:3b
./scripts/install_ollama.sh mistral:7b       # or pick a model
```

**macOS — manual:**
```bash
brew install ollama
```

**Linux:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**Windows — easiest:** use the bundled installer (auto-installs Ollama, sets `OLLAMA_ORIGINS` persistently, pulls a default model + smoke-tests it):

```powershell
scripts\install_ollama.cmd                  # default: llama3.2:3b
scripts\install_ollama.cmd mistral:7b       # or pick a model
```

The `.cmd` wrapper invokes PowerShell with `-ExecutionPolicy Bypass` so it works on a fresh Windows machine without you having to flip any policy.

**Windows — manual:** download the installer from <https://ollama.com/download>, then in PowerShell:

```powershell
$env:OLLAMA_ORIGINS = "https://varneya.github.io"
ollama serve
```

### 5b. Start the server

```bash
ollama serve                                  # foreground
# OR (macOS Homebrew install)
brew services start ollama                    # background, persists across reboots
```

Verify: `curl http://localhost:11434/api/tags` should return JSON.

### 5c. Pull the models the dashboard uses

```bash
ollama pull nomic-embed-text                  # embeddings — required for semantic & BERTopic (default backend)
ollama pull mistral:7b                        # LLM — used by themes_llm + BERTopic naming
```

> **Don't want to install Ollama for embeddings?** Set
> `EMBEDDING_BACKEND=sentence_transformers` and the backend uses an
> in-process Hugging Face model (`all-MiniLM-L6-v2`, 90 MB) instead of
> Ollama. Adds ~1 GB of `torch` to the venv but skips the Ollama install
> entirely. Useful for cloud deploys where Ollama isn't available, and for
> users who only want one local process. The cache (`review_embeddings`)
> tracks both backends side-by-side keyed by model name, so switching
> doesn't break anything — it just triggers a re-embed in the new model's
> namespace. See `backend/themes_embeddings.py` for the full backend
> contract.

**Pick a chat model that fits your RAM:**

| RAM | Recommended chat model | Size |
|---|---|---|
| 4 GB | `phi3:mini` | 2.2 GB |
| 8 GB | `llama3.2:3b` or `mistral:7b` | 2–4 GB |
| 16 GB | `llama3.1:8b` | 4.7 GB |
| 32 GB+ | `mixtral:8x7b` | 26 GB |

The dashboard's `/api/hardware` endpoint inspects your machine and recommends models automatically — visit the **Data Refresh** tab to see suggestions.

### 5d. (Only if connecting to a hosted dashboard) Allow CORS

If you're loading the dashboard from a public URL (e.g. `https://dashboard.example.com`) but want it to talk to the Ollama running on your laptop, start Ollama with the dashboard's origin allowlisted:

```bash
OLLAMA_ORIGINS="https://dashboard.example.com" ollama serve
```

Local-only setups don't need this — `localhost:5173` and `localhost:8000` are already allowed.

---

## 6. Optional — Anthropic Claude API

Required only for: **LLM theming → backend = Claude**.

1. Get an API key from <https://console.anthropic.com/settings/keys>
2. Create `backend/.env`:

```bash
echo 'ANTHROPIC_API_KEY=sk-ant-...' > backend/.env
```

The backend uses the `claude-sonnet-4-6` model with prompt caching enabled. Cost is typically a few cents per analysis run.

---

## 7. Run the app

Open two terminals:

**Terminal 1 — backend (port 8000):**
```bash
cd backend
source venv/bin/activate
uvicorn main:app --reload --port 8000
```

**Terminal 2 — frontend (port 5173):**
```bash
cd frontend
npm run dev
```

Then open <http://localhost:5173>.

---

## 8. Verify everything works

The fastest check is the **Setup** tab in the dashboard itself — it polls the
backend and Ollama every ~8 s and shows green/red pills for each. If you'd
rather curl manually:

| Check | Command / URL | Expected |
|---|---|---|
| Backend up | `curl http://localhost:8000/api/health` | `{"status":"ok"}` |
| Hardware probe | `curl http://localhost:8000/api/hardware` | JSON with `chip`, `ram_gb`, `ollama.running` |
| Ollama up | `curl http://localhost:11434/api/tags` | JSON list of pulled models |
| Frontend up (local) | <http://localhost:5173> | Dashboard loads with bike picker |
| Frontend up (hosted) | <https://varneya.github.io/india-two-wheeler-dashboard/> | Same, served from GitHub Pages |
| Embeddings | dashboard → Owner Insights → method = "Semantic" → run | Themes appear within ~30s |
| LLM (Claude) | dashboard → Owner Insights → method = "LLM" → backend = Claude → run | Themes with sentiment + quotes |
| LLM (Ollama) | dashboard → Owner Insights → method = "LLM" → backend = Ollama → run | Same, locally |

First-time launch will show no data — click the **Data Refresh** tab and run a refresh to populate sales, reviews, and FADA data (~5–15 min).

---

## Method → dependency cheat-sheet

| Method | Python deps beyond core | Local services |
|---|---|---|
| Keyword Rules | — | — |
| TF-IDF + KMeans | `scikit-learn`, `numpy` | — |
| Semantic Clustering | `scikit-learn`, `numpy`, `hdbscan` | Ollama + `nomic-embed-text` |
| BERTopic | `scikit-learn`, `numpy`, `hdbscan`, `umap-learn` | Ollama + `nomic-embed-text` (+ a chat model for naming) |
| LLM Analysis | `anthropic` (for Claude) | Ollama + a chat model (for local backend) |

---

## Troubleshooting

**`ImportError: hdbscan` / `umap` not found**
You skipped them in Section 3b. Re-run the full `pip install` block.

**`hdbscan` install fails on macOS**
Run `xcode-select --install`, then retry. If still failing, try `pip install hdbscan --no-build-isolation`.

**Ollama returns `connection refused`**
The server isn't running. Start it with `ollama serve` or `brew services start ollama`.

**Browser blocks Ollama from a hosted dashboard**
You forgot `OLLAMA_ORIGINS`. See Section 5d.

**`ANTHROPIC_API_KEY` not picked up**
Confirm `backend/.env` is in the `backend/` folder (not repo root) and that you restarted `uvicorn` after creating it.

**Port already in use (`8000` or `5173`)**
Find the offender: `lsof -ti :8000 | xargs kill` (macOS / Linux) or use `netstat -ano | findstr :8000` then `taskkill /PID <pid> /F` (Windows).

---

## Hosting the backend on Oracle Cloud (Always Free)

If you want the backend reachable 24/7 from any device — not just your laptop —
the cheapest path is an **Oracle Cloud Always-Free ARM Ampere VM** (2 OCPU /
12 GB RAM, no monthly charge ever). The bundled bootstrap script does
everything that can be automated end-to-end on the VM in one shot.

### One-time prerequisites you do yourself (~30 min)

1. **Provision an Oracle Cloud Always-Free ARM VM**
   (`VM.Standard.A1.Flex`, 2 OCPU + 12 GB RAM, Ubuntu 24.04). Allocate a
   public IP. In the VCN security list, open inbound TCP 22, 80, 443.
   On Oracle Linux you also need `sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT`
   and the same for 443 (Ubuntu's default iptables is permissive — skip this step there).

2. **Sign up at <https://www.duckdns.org/>** (GitHub OAuth, ~2 min). Create
   a subdomain (e.g. `varneya-bikes`), copy your DuckDNS token, and set the
   subdomain's A record to your VM's public IP.

3. **SSH into the VM** as a sudo-capable user.

### Run the bootstrap (~10–20 min, mostly model downloads)

```bash
sudo \
  TWB_DUCKDNS_DOMAIN=varneya-bikes \
  TWB_DUCKDNS_TOKEN=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \
  TWB_ANTHROPIC_KEY=sk-ant-...  \    # optional — only needed for the Claude theme method
  bash <(curl -fsSL https://raw.githubusercontent.com/varneya/india-two-wheeler-dashboard/main/scripts/setup_oracle_vm.sh)
```

The script:

1. `apt install`s Python 3.12, git, Caddy, Ollama
2. Clones the repo to `/opt/twowheeler` and runs `scripts/install_backend.sh` (venv + pip)
3. Pulls `nomic-embed-text` + `mistral:7b` (~4.7 GB)
4. Writes systemd units for the backend, the daily scrape refresh, and the
   DuckDNS A-record updater; enables them all
5. Drops a Caddyfile that terminates TLS (Let's Encrypt via HTTP-01) for
   `${TWB_DUCKDNS_DOMAIN}.duckdns.org` and reverse-proxies to `:8000`
6. Prints the verification curls

### Point the GitHub Pages frontend at the new backend

In `.github/workflows/deploy.yml`, change `VITE_API_BASE` from
`http://localhost:8000/api` to `https://varneya-bikes.duckdns.org/api`,
push to `main`, and the deploy workflow rebuilds + publishes. Visitors no
longer need a local backend running — your Oracle VM serves everyone.

### Operational caveats

- **Oracle reclaims Always-Free instances from accounts that never spend
  a cent.** Spin up a $0.01-paid resource for an hour every couple of
  months, or just have a billing event of any size, to avoid this.
- **Capacity wall**: ARM Ampere stock is scarce in popular regions. If
  provisioning fails with "Out of capacity", retry every few hours or pick
  a quieter region (Mumbai, Hyderabad, Singapore, Seoul tend to have stock).
- **Ops**: the script is idempotent — re-run it any time you change the
  DuckDNS domain, Anthropic key, or want to upgrade after `git pull`.
- **Logs**: `journalctl -u twowheeler-backend -f` for the API,
  `journalctl -u caddy -f` for TLS issues.

---

## Total install footprint (rough)

| Component | Disk |
|---|---|
| Python venv + all backend packages | ~600 MB |
| `node_modules/` | ~350 MB |
| Ollama runtime | ~150 MB |
| `nomic-embed-text` | 274 MB |
| `mistral:7b` | 4.4 GB |
| **Full stack** | **~6 GB** |
