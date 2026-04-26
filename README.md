# India Two-Wheeler Sales Dashboard

A self-hosted dashboard that scrapes monthly motorcycle & scooter sales data
from public Indian sources, owner reviews from **BikeWale, BikeDekho,
ZigWheels, and r/IndianBikes**, and turns the reviews into themes via five
different theming methods — keyword rules, TF-IDF clustering, semantic
embedding clustering, BERTopic, or an LLM (Claude or local Ollama).

Covers ~110 bikes across 15 manufacturers (Yamaha, Honda, Hero, Bajaj, TVS,
Royal Enfield, Suzuki, KTM, Aprilia, Kawasaki, BMW, Triumph, Ducati, Husqvarna,
Harley-Davidson).

## Live dashboard

**Hosted UI:** <https://varneya.github.io/india-two-wheeler-dashboard/>

The hosted page is the React frontend only — it expects a backend and (for
LLM/embedding methods) Ollama running on **your own machine**. No data is sent
to any third-party server (the optional Anthropic Claude API call is the one
exception, only if you pick the "LLM → Claude" theme method).

On first load the page lands on the **Setup** tab, probes for `localhost:8000`
(backend) and `localhost:11434` (Ollama), and shows live status pills + the
exact commands you need to copy-paste. Once both are running, the rest of the
tabs come alive.

For full install instructions see **[SETUP.md](SETUP.md)**.

For the system architecture (data engineering, dashboarding, ML/LLM, and the
hosted-frontend + local-backend deployment topology) see
**[ARCHITECTURE.md](ARCHITECTURE.md)**.

## Features

- **Per-bike sales view** — monthly chart, peak / latest / total cards,
  staleness warnings, MoM deltas. Imputed months are visibly marked
  (lighter dashed bars) and historical anomalies surface as amber dots.
- **Predictive layer** — same chart toggles in a Prophet forecast (3–24
  months out) with a 95% confidence band, plus a "Next month" tile in
  the metrics row. Imputation fills gaps using priority `seasonal_naive
  → linear → ffill → median` so a few missed scrape months don't break
  the forecast.
- **Cross-source comparison** — RushLane (manufacturer-reported) vs FADA
  (dealer registrations from Vahan) for each brand
- **Compare tab** — overlay 2–4 bikes' monthly sales on one chart
- **Owner Insights** — reviews from BikeWale, BikeDekho, ZigWheels, and
  Reddit r/IndianBikes (~50–70 reviews per popular bike vs. BikeWale alone's
  ~10), with AI-derived themes from the merged corpus
- **Five theming methods** —
  - **Keyword Rules** — fast, deterministic, with a UI for editing keyword
    buckets per session (persists to `localStorage`)
  - **TF-IDF + KMeans** — classical ML baseline
  - **Semantic Clustering** — Ollama `nomic-embed-text` + HDBSCAN + c-TF-IDF
  - **BERTopic Pipeline** — embeddings → UMAP → HDBSCAN → c-TF-IDF, with
    optional Mistral 7B name refinement
  - **LLM Analysis** — Claude (API) or any local Ollama model
- **One-click data refresh** — four-stage pipeline (RushLane discovery →
  BikeWale reviews → BikeDekho/ZigWheels/Reddit reviews → FADA retail PDFs)
  with live progress
- **`⌘K` command palette** to search bikes
- **Light & dark mode**
- **Setup tab** — live status pills for backend / Ollama / required models,
  with copy-paste install commands. Auto-shown when the hosted page can't
  reach a local backend.

## Architecture

See **[ARCHITECTURE.md](ARCHITECTURE.md)** for full Mermaid diagrams covering
data engineering, dashboarding, the LLM/ML stack, and the deployment
topology (hosted frontend + local-first backend).

```
backend/                    FastAPI + SQLite (no ORM)
  scraper.py                RushLane URL discovery + fetch
  extractor.py              Per-bike regex extractor (sales)
  bike_registry.py          URL-slug → catalogue lookup
  bike_catalogue.py         Curated whitelist of ~110 Indian bikes
  reviews_scraper.py        BikeWale review scraper
  bikedekho_scraper.py      BikeDekho user reviews (~30/page, with ratings)
  zigwheels_scraper.py      ZigWheels user reviews (numeric review IDs)
  reddit_scraper.py         r/IndianBikes search + comment-thread JSON
  fada_scraper.py           FADA monthly retail PDF parser (pdfplumber)
  themes_keyword.py         Method 1 — keyword bucket matching
  themes_tfidf.py           Method 2 — TF-IDF + KMeans
  themes_semantic.py        Method 3 — embeddings + HDBSCAN
  themes_bertopic.py        Method 4 — embeddings + UMAP + HDBSCAN + LLM
  themes_llm.py             Method 5 — Claude or Ollama
  hardware_detector.py      Mac chip detection + Ollama status
  database.py               SQLite schema + migrations
  main.py                   FastAPI routes (CORS allowlists localhost:5173
                            and varneya.github.io for the hosted UI)

frontend/                   Vite + React 19 + TypeScript
  src/components/ui/        shadcn/ui primitives
  src/components/           App-specific components (incl. SetupTab.tsx)
  src/api/client.ts         Shared API_BASE / OLLAMA_BASE (env-driven)
  src/api/                  Axios + fetch helpers
  src/hooks/                React Query hooks + theme toggle

.github/workflows/
  deploy.yml                Builds frontend and publishes to GitHub Pages on
                            every push touching frontend/. Bakes
                            VITE_API_BASE=http://localhost:8000/api into the
                            production build so the hosted UI calls the
                            visitor's own machine.
```

**Data sources:**

- **RushLane** — monthly "sales-breakup" articles. Manufacturer-reported
  numbers (mostly wholesale dispatches; some brands report Vahan retail —
  see the *Sales by source* card for the cross-check)
- **BikeWale** — owner reviews per model (~10 per bike, deduped by review ID)
- **BikeDekho** — user reviews with explicit 1–5 star ratings (~30 per bike on
  page 1; deduped by hash of author + date + title)
- **ZigWheels** — user reviews with stable site-issued numeric IDs
- **Reddit r/IndianBikes** — top-level comments on posts matching the bike's
  display name, filtered by length and upvote score
- **FADA** — monthly Vehicle Retail Data PDFs. Brand-level only; comes from
  Vahan dealer registrations

## Setup

Full step-by-step guide (with per-OS commands, troubleshooting, and a
"method → dependencies" cheat-sheet) is in **[SETUP.md](SETUP.md)**.

### TL;DR — local-only

```bash
# Backend
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend (in a second terminal)
cd frontend
npm install && npm run dev          # → http://localhost:5173

# Optional: Ollama for local LLM / embeddings
brew install ollama && ollama serve &
ollama pull nomic-embed-text mistral:7b
```

### TL;DR — use the hosted UI with your local backend

Visit <https://varneya.github.io/india-two-wheeler-dashboard/>, then on your
machine:

```bash
# Terminal 1 — backend
cd backend && source venv/bin/activate && uvicorn main:app --port 8000

# Terminal 2 — Ollama, allowlisting the hosted origin
OLLAMA_ORIGINS="https://varneya.github.io" ollama serve
```

The Setup tab on the hosted page polls every ~8s and lights up green once both
are reachable.

## First run

1. Open the dashboard. The catalogue is pre-seeded but no scraped data exists yet.
2. Go to the **Data Refresh** tab and click **Refresh Everything**.
3. ~5–10 minutes later you have monthly sales, BikeWale reviews, and FADA
   retail data for ~50 bikes.
4. Pick a bike from the brand → model dropdowns (or `⌘K` for search).
5. Try the *Owner Insights* tab and run different theming methods to compare.

## Tech stack

**Backend:** FastAPI, SQLite, BeautifulSoup, requests, scikit-learn,
hdbscan, umap-learn, pdfplumber, anthropic, ollama (HTTP), python-dotenv

**Frontend:** React 19, TypeScript, Vite, Tailwind CSS v4, shadcn/ui (Radix),
Recharts, TanStack Query, Lucide, Sonner, cmdk

**Local AI:** Ollama with `nomic-embed-text` (embeddings) and `mistral:7b`
(generation). No data leaves the machine for these methods.

## Honest scope notes

- **Scraping is best-effort.** The RushLane parser is pattern-matched against
  observed article styles; sites can change layouts at any time. Per-bike
  unit floors in `bike_catalogue.py` reject obvious misparses (e.g. *"125cc"*
  read as a sales count).
- **RushLane wholesale vs FADA retail isn't a clean split.** FADA always =
  retail (Vahan registrations). RushLane is mostly manufacturer dispatches
  but varies by brand. The "Sales by source" card surfaces both rather than
  asserting which is "correct".
- **Reviews per source are capped at what each site shows on page 1**
  (BikeWale ~10, BikeDekho ~30, ZigWheels ~4, Reddit ~6 posts × top comments).
  Pagination is generally JS-driven or server-side disabled on these sites.
- **Themes quality scales with review count.** With 10 reviews, expect 2–4
  themes. With 100+, the embedding methods produce much sharper clusters.

## Disclaimer

This project scrapes publicly accessible web pages for personal analysis. It
respects `robots.txt` for the sites it touches and rate-limits aggressively.
If you're a publisher and want your site removed, open an issue or pull request.

Not affiliated with Yamaha, Honda, Hero, Bajaj, TVS, RushLane, BikeWale,
BikeDekho, ZigWheels, Reddit, FADA, or any other entity mentioned.

## License

MIT — see [LICENSE](LICENSE).
