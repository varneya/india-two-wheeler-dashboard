# Architecture

Four views of the system, scoped to the concerns they cover. All Mermaid blocks render directly on GitHub.

1. **Data engineering** — scrapers, catalogue, orchestrator, SQLite store
2. **Dashboarding** — React frontend, FastAPI surface, env-driven API base
3. **LLM / ML** — five theming engines, embeddings, hardware detection
4. **Deployment topology** — GitHub Pages frontend + visitor-local backend + Ollama

---

## 1. Data Engineering

Seven independent scrapers feed a single SQLite store. The `/api/refresh-all` endpoint orchestrates them as a 5-stage pipeline (RushLane discovery → BikeWale reviews → BikeDekho/ZigWheels/Reddit reviews → AutoPunditz prose + brand totals → YouTube transcripts), with per-stage progress polled by the frontend. AutoPunditz is the canonical brand-level wholesale source; RushLane is the model-level fallback.

```mermaid
flowchart LR
    subgraph Sources["External Sources"]
        RL[(RushLane<br/>sales-breakup articles)]
        AP[(AutoPunditz<br/>per-brand + aggregate posts)]
        BW[(BikeWale<br/>owner reviews)]
        BD[(BikeDekho<br/>user reviews + ratings)]
        ZW[(ZigWheels<br/>user reviews)]
        RD[(Reddit /r/IndianBikes<br/>JSON API)]
        YT[(YouTube<br/>13 review channels)]
    end

    subgraph Catalogue["Catalogue / Whitelist"]
        BC[bike_catalogue.py<br/>~110 bikes / 15 brands]
        BR[bike_registry.py<br/>slug → id mapping]
    end

    subgraph Scrapers["Scrapers (backend/)"]
        SC[scraper.py<br/>article discovery]
        EX[extractor.py<br/>per-bike unit regex]
        APS[autopunditz_scraper.py<br/>prose + sitemap]
        RS[reviews_scraper.py<br/>BikeWale]
        BDS[bikedekho_scraper.py<br/>30 reviews/page + ratings]
        ZWS[zigwheels_scraper.py<br/>numeric review IDs]
        RDS[reddit_scraper.py<br/>top comments per post]
        YTS[youtube_scraper.py<br/>yt-dlp + transcript-api]
    end

    subgraph Orchestrator["Orchestrator"]
        RA["POST /api/refresh-all<br/>(FastAPI background task)"]
        ST["GET /api/refresh-all/status<br/>stage / progress / logs"]
    end

    subgraph Store["SQLite — backend/sales.db"]
        T1[(bikes)]
        T2[(sales_data<br/>per-bike wholesale<br/>autopunditz + rushlane)]
        T3[("reviews<br/>source ∈ {bikewale,<br/>bikedekho, zigwheels, reddit}")]
        T4[(wholesale_brand_sales<br/>autopunditz brand totals)]
        T5[(video_transcripts<br/>+ video_bike_match)]
        T6[(scrape_log /<br/>reviews_log)]
    end

    RA -->|stage 1| SC --> EX
    RA -->|stage 2| RS
    RA -->|stage 3| BDS & ZWS & RDS
    RA -->|stage 4| APS
    RA -->|stage 5| YTS

    RL --> SC
    RL --> EX
    AP --> APS
    BW --> RS
    BD --> BDS
    ZW --> ZWS
    RD --> RDS
    YT --> YTS

    BC -.validates.- EX
    BC -.iterates.- RS
    BC -.iterates.- BDS
    BC -.iterates.- ZWS
    BC -.iterates.- RDS
    BC -.matches.- YTS
    BC -.matches.- APS
    BR -.lookup.- EX

    EX --> T1
    EX --> T2
    EX --> T6
    APS --> T2
    APS --> T4
    RS --> T3
    BDS --> T3
    ZWS --> T3
    RDS --> T3
    RS --> T6
    YTS --> T5

    RA --> ST
    T5 -.reads.- ST
```

---

## 2. Dashboarding

React 19 + Vite + TS frontend talks to a FastAPI backend through a shared `API_BASE` (in `api/client.ts`) that defaults to `/api` for local dev (proxied by Vite to `localhost:8000`) and is overridden at build time via `VITE_API_BASE` for the GitHub Pages deploy. State is managed by TanStack Query (server) and a `SelectedBike` React Context (global). Charts are Recharts; UI is shadcn/Radix on Tailwind v4.

```mermaid
flowchart TB
    subgraph Browser["Browser — Vite :5173 (or hosted GitHub Pages)"]
        APP[App.tsx<br/>tab router]
        subgraph Tabs["Tabs"]
            T_SALES[Sales]
            T_INS[Owner Insights]
            T_CMP[Compare]
            T_REF[Data Refresh]
            T_SET[Setup<br/>auto-default if<br/>backend unreachable]
        end
        subgraph Components["Components"]
            BP[BikePicker /<br/>BikeCommandPalette ⌘K]
            SC[SalesChart<br/>unified: history +<br/>imputed bars +<br/>forecast line + CI band]
            SCTRL[SalesChartControls<br/>toggle · horizon · Re-fit]
            AL[AnomaliesList]
            IML[ImputedMonthsList]
            RC[ReviewCard]
            CT[CompareTab]
            TT[ThemesTab]
            RT[RefreshTab]
            ST[SetupTab<br/>status pills +<br/>install commands]
            MC[MetricsCards<br/>+ Next-month tile<br/>when forecast loaded]
            SCC[SourceComparisonCard<br/>wholesale vs retail]
        end
        subgraph Data["Data layer"]
            QC[TanStack Query<br/>cache + polling]
            CTX[SelectedBike Context]
            AX[Axios — API_BASE]
            CL["api/client.ts<br/>API_BASE / OLLAMA_BASE<br/>(env-driven)"]
        end
        APIS["api/<br/>bikesApi · salesApi ·<br/>reviewsApi · themesApi"]
    end

    subgraph Backend["FastAPI — :8000 (backend/main.py)"]
        E_BR["/api/brands<br/>/api/brands/{id}/models<br/>/api/brands/{id}/wholesale-vs-retail<br/>/api/brands/{id}/sales/series<br/>/api/brands/{id}/metrics<br/>/api/brands/{id}/forecast (lazy)<br/>/api/brands/{id}/forecast/refresh<br/>/api/brands/{id}/forecast/status"]
        E_BK["/api/bikes · /api/bikes/{id}<br/>/api/bikes/{id}/sales<br/>/api/bikes/{id}/sales/series<br/>/api/bikes/{id}/metrics<br/>/api/bikes/{id}/forecast (lazy)<br/>/api/bikes/{id}/forecast/refresh<br/>/api/bikes/{id}/forecast/status<br/>/api/bikes/{id}/anomalies<br/>/compare?ids=..."]
        E_RV["/api/bikes/{id}/reviews<br/>/api/bikes/{id}/reviews/summary"]
        E_REF["/api/refresh-all<br/>/api/refresh-all/status"]
        E_SYS["/api/health<br/>/api/hardware"]
        CORS["CORS allowlist:<br/>localhost:5173 +<br/>varneya.github.io"]
    end

    OL[("Ollama @ :11434")]
    DB[(SQLite<br/>sales.db)]

    APP --> T_SALES & T_INS & T_CMP & T_REF & T_SET
    T_SALES --> BP & MC & SCTRL & SC & AL & IML & SCC
    T_INS --> TT & RC
    T_CMP --> CT
    T_REF --> RT
    T_SET --> ST

    BP --> CTX
    CTX --> QC
    Components --> APIS
    APIS --> CL
    CL --> AX
    AX -->|HTTP API_BASE| Backend

    ST -.probe /health.-> Backend
    ST -.probe /api/tags.-> OL

    QC -.polls status.- E_REF

    E_BR & E_BK & E_RV & E_SYS --> DB
    E_REF --> DB
    Backend --- CORS
```

---

## 3. LLM / Machine Learning

Theme extraction over reviews has five interchangeable engines, all dispatched through `themes_runner`. Embeddings are produced locally by Ollama (`nomic-embed-text`); the LLM stage can run against Anthropic Claude (cloud) or Ollama Mistral (local). `hardware_detector` decides which local models the host can realistically run.

```mermaid
flowchart TB
    subgraph FE["Frontend — ThemesTab"]
        UI[method picker +<br/>config form]
        UI -->|POST| EP1["/api/bikes/{id}/themes/analyze"]
        UI -->|poll| EP2["/api/bikes/{id}/themes/status"]
        UI -->|setup| EP3["/api/hardware<br/>/api/ollama/pull/{model}"]
    end

    subgraph Runner["Dispatcher"]
        TR[themes_runner.py<br/>run_analysis method, config, bike_id]
    end

    subgraph Methods["Five Engines (backend/themes_*.py)"]
        M1[themes_keyword<br/>rule lists]
        M2[themes_tfidf<br/>TF-IDF + KMeans]
        M3[themes_semantic<br/>HDBSCAN + c-TF-IDF]
        M4[themes_bertopic<br/>UMAP + HDBSCAN<br/>+ optional LLM naming]
        M5[themes_llm<br/>Claude OR Ollama chat]
    end

    subgraph Shared["Shared ML Layer"]
        EMB[themes_embeddings.py<br/>Ollama HTTP client<br/>c-TF-IDF · sentiment]
        HW[hardware_detector.py<br/>chip / RAM / Ollama status<br/>recommended_models]
    end

    subgraph LLMs["Inference Backends"]
        OL["Ollama @ :11434<br/>nomic-embed-text 768d<br/>mistral:7b · phi3 · llama3"]
        CL["Anthropic API<br/>claude-sonnet-4-6<br/>prompt caching"]
    end

    DB[(SQLite<br/>reviews · themes_analysis)]

    EP1 --> TR
    TR --> M1 & M2 & M3 & M4 & M5

    DB -.reviews.-> TR

    M3 --> EMB
    M4 --> EMB
    M5 --> EMB
    M4 -->|optional naming| OL
    M5 -->|backend=ollama| OL
    M5 -->|backend=claude| CL
    EMB -->|embeddings| OL

    EP3 --> HW
    HW --> OL

    M1 & M2 & M3 & M4 & M5 -->|themes JSON| DB
    DB -.reads.-> EP2
```

### Engine cheat-sheet

| Method | Local cost | Network | Best for |
|---|---|---|---|
| `keyword` | trivial | none | sanity baseline, offline |
| `tfidf` | low | none | quick clustering when reviews are plentiful |
| `semantic` | medium (embeddings) | Ollama only | denser topics on small corpora |
| `bertopic` | medium-high | Ollama (+optional LLM naming) | interpretable topics with auto-named clusters |
| `llm` | low local | Anthropic **or** Ollama | best narrative themes, sentiment, exemplar quotes |

---

## 4. Deployment topology

The hosted UI lives on GitHub Pages but is deliberately *empty* of data — it's a static React bundle whose API base is hard-coded at build time to `http://localhost:8000/api`. Visitors run the FastAPI backend (and optionally Ollama) on their own machine; the browser ferries data between the hosted page and the visitor's localhost. Nothing the visitor scrapes or reviews ever leaves their laptop, except the optional Anthropic Claude API call.

```mermaid
flowchart LR
    subgraph Repo["GitHub repo · varneya/india-two-wheeler-dashboard"]
        SRC[main branch<br/>frontend/ + backend/]
        WF[".github/workflows/deploy.yml<br/>triggers on push to frontend/**"]
    end

    subgraph CI["GitHub Actions runner"]
        BUILD["npm ci + npm run build<br/><br/>env:<br/>VITE_API_BASE=<br/>http://localhost:8000/api<br/>VITE_OLLAMA_BASE=<br/>http://localhost:11434"]
        ART[upload-pages-artifact<br/>→ frontend/dist]
    end

    GH_PAGES[("GitHub Pages CDN<br/>varneya.github.io/<br/>india-two-wheeler-dashboard/")]

    subgraph Visitor["Visitor's machine"]
        BROWSER["Browser<br/>loads the hosted bundle"]
        FAPI["FastAPI :8000<br/>uvicorn main:app<br/><br/>CORS allows<br/>varneya.github.io"]
        OLL["Ollama :11434<br/>OLLAMA_ORIGINS=<br/>https://varneya.github.io"]
        SQL[(sales.db)]
    end

    SRC --> WF --> BUILD --> ART --> GH_PAGES
    GH_PAGES -->|HTML/JS/CSS| BROWSER
    BROWSER -->|XHR localhost:8000/api/*| FAPI
    BROWSER -->|fetch localhost:11434<br/>embeddings + chat| OLL
    FAPI <--> SQL

    classDef cloud fill:#1e3a5f,stroke:#3b82f6,color:#fff
    classDef local fill:#0d2818,stroke:#10b981,color:#fff
    class Repo,CI,GH_PAGES cloud
    class Visitor local
```

**Why this works:**

- Browsers exempt `localhost` from mixed-content blocking, so an HTTPS page can fetch `http://localhost:8000` and `http://localhost:11434`.
- The backend explicitly allowlists `https://varneya.github.io` in CORS (`backend/main.py`).
- Ollama needs `OLLAMA_ORIGINS=https://varneya.github.io` set when started, so its CORS preflight permits the browser request.
- The `SetupTab` component polls both endpoints every ~8 s and surfaces the install commands when either is unreachable, so a fresh visitor lands on a useful page even before they've installed anything.

**Why this is free:** GitHub Pages hosts the static bundle at zero cost, GitHub Actions provides 2000 free CI minutes/month, and all heavy compute (scraping, embeddings, clustering, LLM inference) runs on the visitor's machine. The only paid path is the optional Anthropic Claude API, billed per-call to whoever owns the API key.

**Local-only mode:** `npm run dev` and `uvicorn main:app` work exactly as before — `command !== 'build'` keeps `base: '/'` and the API client's default `/api` is proxied to `localhost:8000` by Vite. The hosted-mode plumbing is purely additive.
