# Setup & Dependencies

This guide walks you through installing everything needed to run the India Two-Wheeler Dashboard — from the lightest setup (sales charts only) to the full stack (all five theming methods, including local LLM via Ollama).

> **Tip:** if you only want to browse the data and don't care about LLM/ML theme analysis, you can skip Sections 5 and 6 entirely.

---

## Quickstart with the hosted UI

If you don't want to clone & build the frontend yourself, the hosted bundle at
**<https://varneya.github.io/india-two-wheeler-dashboard/>** does it for you.
The UI runs in your browser; the data scrapers, SQLite store, and ML/LLM
inference run on **your** machine by default. Cloud LLM backends send the sampled
review text to the configured provider.

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
so dashboard requests go to your local backend. Claude is selectable in the UI;
Groq and generic OpenAI-compatible inference are currently selected through
the analysis API (Section 6). Ollama is optional for browsing and keyword analysis.

---

## What do you actually need?

Pick the row that matches what you want and install only those sections.

| You want to... | Sections needed |
|---|---|
| Browse sales charts, reviews, influencer videos | 1, 2, 3, 4 |
| Run keyword theming | 1, 2, 3, 4 |
| Run TF-IDF theming / Prophet forecasting | 1, 2, 3 (+ **3c**), 4 |
| Run semantic / BERTopic theming (local embeddings) | 1, 2, 3 (+ **3c**), 4, **5** |
| Run LLM theming on your machine | 1, 2, 3, 4, **5** |
| Run LLM theming via a cloud API (Claude / Groq / OpenAI-compatible) | 1, 2, 3, 4, **6** |
| **The full experience (all 5 methods)** | **1–6** |

---

## 1. System prerequisites

| Tool | Minimum version | Check |
|---|---|---|
| **Python** | 3.12+ (required by pinned NumPy) | `python3 --version` |
| **Node.js** | 20.19+ or 22.12+ (Vite 8) | `node --version` |
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

> **Recommended: bundled bootstrap scripts.** They check Python version, offer to install Python 3.12 if missing (Homebrew on macOS, apt on Debian/Ubuntu, winget on Windows), create the venv, upgrade pip, and `pip install -r requirements.txt` (the core set) in one shot. Idempotent — safe to re-run. Add the ML extras afterwards if you need them (Section 3c).
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

Install the pinned core dependencies from the activated backend environment:

```bash
python -m pip install -r requirements.txt
```

Core supports scraping, sales history/imputation, keyword themes, and LLM
API calls. It does not install Prophet or the clustering/embedding stack.

### 3c. Optional ML dependencies

```bash
python -m pip install -r requirements-ml.txt
```

This adds TF-IDF, semantic clustering, BERTopic, Prophet, and in-process
sentence-transformers embeddings. Without these extras, those methods report
an installation message; the rest of the API still starts normally.

**Package roles:**

| Package | Used by | Purpose |
|---|---|---|
| `fastapi` | `main.py` | HTTP API framework |
| `uvicorn[standard]` | `main.py` | ASGI server |
| `requests` | scrapers, themes_embeddings | HTTP client (RushLane, BikeWale, BikeDekho, ZigWheels, Reddit, Ollama) |
| `beautifulsoup4` | `scraper.py`, `reviews_scraper.py` | HTML parsing |
| `anthropic` | `themes_llm.py` | Claude API client |
| `pydantic-settings`, `python-dotenv` | `config.py` | Load `backend/.env`; process environment values take precedence |
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

## 6. Optional — cloud or self-hosted LLM APIs

Copy `backend/.env.example` to `backend/.env` if the latter does not already
exist, then edit it. Keep existing keys when changing settings. Restart the
backend after changing configuration.

- **Claude:** set `ANTHROPIC_API_KEY`; optionally override `CLAUDE_MODEL`.
  Select Claude in Owner Insights → LLM.
- **Groq:** set `GROQ_API_KEY`. The analysis API accepts
  `config.backend = "groq:<model-id>"`; choose a model available to your account.
- **Other OpenAI-compatible servers:** set `OPENAI_COMPAT_BASE_URL` including
  its `/v1` path and, if required, `OPENAI_COMPAT_API_KEY`. Use
  `config.backend = "openai:<model-id>"`. Keyless local endpoints are supported.
- **Ollama:** use `config.backend = "ollama:<model>"`; its address is configured
  with `OLLAMA_BASE_URL` (default `http://localhost:11434`).

Groq and generic OpenAI-compatible providers are supported by the backend;
there is currently no dedicated provider selector for them in the UI. For
example, from a shell with `ADMIN_TOKEN` set when the server requires it:

```bash
curl --fail-with-body -X POST http://localhost:8000/api/bikes/tvs-jupiter/themes/analyze \
  -H 'Content-Type: application/json' \
  -H "X-Admin-Token: ${ADMIN_TOKEN}" \
  -d '{"method":"llm","config":{"backend":"groq:YOUR_MODEL_ID"},"pool_scope":"bike"}'
```

Poll `/api/bikes/tvs-jupiter/themes/status`, then read
`/api/bikes/tvs-jupiter/themes`. Provider credentials stay in the backend.
Cloud LLM requests send sampled review text to the chosen provider; usage is
subject to that provider's pricing and limits.

### Shared backend authentication

For local use, leaving `ADMIN_TOKEN` empty preserves the local workflow.
Before exposing a shared backend, set a long random token (`openssl rand -hex 32`)
on the server. Refresh, cleanup, analysis, model downloads, and hardware probes
then require `X-Admin-Token`; reads of saved sales/reviews/themes stay public.
Forecast reads can still start CPU work, so this guard is not a complete
public traffic or resource-limit policy.

For an owner browser, set `localStorage.setItem('twd_admin_token', 'YOUR_TOKEN')`
in that site's developer console and reload. Remove it with
`localStorage.removeItem('twd_admin_token')` and reload to return to public access.
**Never put `VITE_ADMIN_TOKEN` or provider keys in a public frontend build**:
build-time Vite variables are included in downloadable JavaScript.

On the VM, both backend and nightly refresh units read `/etc/twowheeler/env`.
Create it with mode `600` and put `ADMIN_TOKEN=...` there before starting services.
This shared environment file overrides the backend `.env` token so the timer
and backend use the same credential. Provider keys may also be placed there.

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

First-time launch will show no data — click the **Data Refresh** tab and run a refresh to populate sales (RushLane + AutoPunditz), reviews, and YouTube transcripts (~5–15 min).

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
Install the ML extras from Section 3c: `python -m pip install -r requirements-ml.txt`.

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
the bundled bootstrap targets an Ubuntu VM, including Oracle ARM instances.
Confirm current pricing, free-tier eligibility, and available capacity with
your provider before provisioning. The script installs the core backend and
Ollama; install ML extras separately if you need clustering or forecasting.

### One-time prerequisites you do yourself (~30 min)

1. **Provision an Oracle Cloud Always-Free ARM VM**
   (`VM.Standard.A1.Flex`, 2 OCPU + 12 GB RAM, Ubuntu 24.04). Allocate a
   public IP. In the VCN security list, open inbound TCP 22, 80, 443.
   On Oracle Linux you also need `sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT`
   and the same for 443 (Ubuntu's default iptables is permissive — skip this step there).

2. **Sign up at <https://www.duckdns.org/>** (GitHub OAuth, ~2 min). Create
   a subdomain (e.g. `varneya-bikes`), copy your DuckDNS token, and set the
   subdomain's A record to your VM's public IP.

3. **SSH into the VM** as a sudo-capable user. Before running the bootstrap,
   create `/etc/twowheeler/env` with mode `600` and an `ADMIN_TOKEN` as described
   in Section 6. The script preserves this file and both services read it.

### Run the bootstrap (~10–20 min, mostly model downloads)

```bash
sudo \
  TWB_DUCKDNS_DOMAIN=varneya-bikes \
  TWB_DUCKDNS_TOKEN=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \
  bash <(curl -fsSL https://raw.githubusercontent.com/varneya/india-two-wheeler-dashboard/main/scripts/setup_oracle_vm.sh)
```

The script:

1. `apt install`s Python 3.12, git, Caddy, Ollama
2. Clones the repo to `/opt/twowheeler` and runs `scripts/install_backend.sh` (venv + pip)
3. Pulls `nomic-embed-text` + `qwen3:8b` by default
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

- **Provider policy and capacity:** consult your provider's current terms for
  idle-instance reclamation and provisioning limits. Keep backups of
  `backend/sales.db` and any PDFs you need.
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

## Development checks

From the repository root:

```bash
backend/venv/bin/python -m pip install -r backend/requirements-dev.txt
backend/venv/bin/python -m pytest backend/tests
cd frontend
npm run build
```

The backend tests use temporary databases and network stubs. They do not
scrape external sites or call paid inference services. A production build
checks TypeScript and bundles the frontend; it does not verify live providers.
