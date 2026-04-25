# India Two-Wheeler Sales Dashboard

A self-hosted dashboard that scrapes monthly motorcycle & scooter sales data
from public Indian sources, owner reviews from BikeWale, and turns the reviews
into themes via five different theming methods — keyword rules, TF-IDF
clustering, semantic embedding clustering, BERTopic, or an LLM (Claude or
local Ollama).

Covers ~110 bikes across 15 manufacturers (Yamaha, Honda, Hero, Bajaj, TVS,
Royal Enfield, Suzuki, KTM, Aprilia, Kawasaki, BMW, Triumph, Ducati, Husqvarna,
Harley-Davidson).

## Features

- **Per-bike sales view** — monthly chart, peak / latest / total cards,
  staleness warnings, MoM deltas
- **Cross-source comparison** — RushLane (manufacturer-reported) vs FADA
  (dealer registrations from Vahan) for each brand
- **Compare tab** — overlay 2–4 bikes' monthly sales on one chart
- **Owner Insights** — BikeWale reviews with real reviewer names and star
  ratings, plus AI-derived themes from those reviews
- **Five theming methods** —
  - **Keyword Rules** — fast, deterministic, with a UI for editing keyword
    buckets per session (persists to `localStorage`)
  - **TF-IDF + KMeans** — classical ML baseline
  - **Semantic Clustering** — Ollama `nomic-embed-text` + HDBSCAN + c-TF-IDF
  - **BERTopic Pipeline** — embeddings → UMAP → HDBSCAN → c-TF-IDF, with
    optional Mistral 7B name refinement
  - **LLM Analysis** — Claude (API) or any local Ollama model
- **One-click data refresh** — three-stage pipeline (RushLane → BikeWale →
  FADA retail PDFs) with live progress
- **`⌘K` command palette** to search bikes
- **Light & dark mode**

## Architecture

```
backend/                    FastAPI + SQLite (no ORM)
  scraper.py                RushLane URL discovery + fetch
  extractor.py              Per-bike regex extractor (sales)
  bike_registry.py          URL-slug → catalogue lookup
  bike_catalogue.py         Curated whitelist of ~110 Indian bikes
  reviews_scraper.py        BikeWale review scraper
  fada_scraper.py           FADA monthly retail PDF parser (pdfplumber)
  themes_keyword.py         Method 1 — keyword bucket matching
  themes_tfidf.py           Method 2 — TF-IDF + KMeans
  themes_semantic.py        Method 3 — embeddings + HDBSCAN
  themes_bertopic.py        Method 4 — embeddings + UMAP + HDBSCAN + LLM
  themes_llm.py             Method 5 — Claude or Ollama
  hardware_detector.py      Mac chip detection + Ollama status
  database.py               SQLite schema + migrations
  main.py                   FastAPI routes

frontend/                   Vite + React 19 + TypeScript
  src/components/ui/        shadcn/ui primitives
  src/components/           App-specific components
  src/api/                  Axios + fetch helpers
  src/hooks/                React Query hooks + theme toggle
```

**Data sources:**

- **RushLane** — monthly "sales-breakup" articles. Manufacturer-reported
  numbers (mostly wholesale dispatches; some brands report Vahan retail —
  see the *Sales by source* card for the cross-check)
- **BikeWale** — owner reviews per model (~10 per bike, dedupe'd by review ID)
- **FADA** — monthly Vehicle Retail Data PDFs. Brand-level only; comes from
  Vahan dealer registrations

## Setup

### Prerequisites

- Python 3.10+
- Node 18+ (for the frontend)
- (Optional) [Ollama](https://ollama.com) for the local-LLM theme methods

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # add ANTHROPIC_API_KEY if you want the Claude LLM method
uvicorn main:app --reload --port 8000
```

The first startup runs migrations and seeds the bike catalogue. Visit
[http://localhost:8000/api/health](http://localhost:8000/api/health).

### Frontend

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173
```

### (Optional) Ollama for local LLM / embedding methods

```bash
# Easy path — runs the bundled installer
chmod +x scripts/install_ollama.sh
./scripts/install_ollama.sh

# Or manually:
brew install ollama
ollama serve &
ollama pull nomic-embed-text   # 274 MB — required for Semantic / BERTopic methods
ollama pull mistral:7b         # 4.4 GB  — used by BERTopic's LLM-naming step + LLM Analysis method
```

The dashboard's *Theme Analysis* tab auto-detects whether Ollama is running
and surfaces install hints if it isn't.

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
- **Reviews are capped at what BikeWale shows on page 1** (~10 per bike).
  BikeWale's `?page=N` query param is a no-op on their server.
- **Themes quality scales with review count.** With 10 reviews, expect 2–4
  themes. With 100+, the embedding methods produce much sharper clusters.

## Disclaimer

This project scrapes publicly accessible web pages for personal analysis. It
respects `robots.txt` for the sites it touches and rate-limits aggressively.
If you're a publisher and want your site removed, open an issue or pull request.

Not affiliated with Yamaha, Honda, Hero, Bajaj, TVS, RushLane, BikeWale, FADA,
or any other entity mentioned.

## License

MIT — see [LICENSE](LICENSE).
