# Architecture

Three views of the system, scoped to the concerns they cover. All Mermaid blocks render directly on GitHub.

---

## 1. Data Engineering

Three independent scrapers feed a single SQLite store. The `/api/refresh-all` endpoint orchestrates them as a 3-stage pipeline (RushLane discovery → BikeWale reviews → FADA PDF parse), with per-stage progress polled by the frontend.

```mermaid
flowchart LR
    subgraph Sources["External Sources"]
        RL[(RushLane<br/>sales-breakup articles)]
        BW[(BikeWale<br/>owner reviews)]
        FADA[(FADA<br/>monthly PDFs)]
    end

    subgraph Catalogue["Catalogue / Whitelist"]
        BC[bike_catalogue.py<br/>~110 bikes / 15 brands]
        BR[bike_registry.py<br/>slug → id mapping]
    end

    subgraph Scrapers["Scrapers (backend/)"]
        SC[scraper.py<br/>article discovery]
        EX[extractor.py<br/>per-bike unit regex]
        RS[reviews_scraper.py<br/>dedupe by post_id]
        FS[fada_scraper.py<br/>pdfplumber]
    end

    subgraph Orchestrator["Orchestrator"]
        RA["POST /api/refresh-all<br/>(FastAPI background task)"]
        ST["GET /api/refresh-all/status<br/>stage / progress / logs"]
    end

    subgraph Store["SQLite — backend/sales.db"]
        T1[(bikes)]
        T2[(sales_data<br/>wholesale)]
        T3[(reviews)]
        T4[(retail_brand_sales<br/>FADA)]
        T5[(scrape_log /<br/>reviews_log)]
    end

    RA -->|stage 1| SC --> EX
    RA -->|stage 2| RS
    RA -->|stage 3| FS

    RL --> SC
    RL --> EX
    BW --> RS
    FADA --> FS

    BC -.validates.- EX
    BC -.iterates.- RS
    BR -.lookup.- EX

    EX --> T1
    EX --> T2
    EX --> T5
    RS --> T3
    RS --> T5
    FS --> T4

    RA --> ST
    T5 -.reads.- ST
```

---

## 2. Dashboarding

React 19 + Vite + TS frontend talks to a FastAPI backend over `/api/*`. State is managed by TanStack Query (server) and a `SelectedBike` React Context (global). Charts are Recharts; UI is shadcn/Radix on Tailwind v4.

```mermaid
flowchart TB
    subgraph Browser["Browser — Vite :5173"]
        APP[App.tsx<br/>tab router]
        subgraph Tabs["Tabs"]
            T_SALES[Sales]
            T_INS[Owner Insights]
            T_CMP[Compare]
            T_REF[Data Refresh]
        end
        subgraph Components["Components"]
            BP[BikePicker /<br/>BikeCommandPalette ⌘K]
            SC[SalesChart<br/>Recharts]
            RC[ReviewCard]
            CT[CompareTab]
            TT[ThemesTab]
            RT[RefreshTab]
            MC[MetricsCards /<br/>SalesTable]
            SCC[SourceComparisonCard<br/>wholesale vs retail]
        end
        subgraph Data["Data layer"]
            QC[TanStack Query<br/>cache + polling]
            CTX[SelectedBike Context]
            AX[Axios — /api]
        end
        APIS["api/<br/>bikesApi · salesApi ·<br/>reviewsApi · themesApi"]
    end

    subgraph Backend["FastAPI — :8000 (backend/main.py)"]
        E_BR["/api/brands<br/>/api/brands/{id}/models<br/>/api/brands/{id}/wholesale-vs-retail"]
        E_BK["/api/bikes · /api/bikes/{id}<br/>/api/bikes/{id}/sales<br/>/api/bikes/{id}/metrics<br/>/compare?ids=..."]
        E_RV["/api/bikes/{id}/reviews<br/>/api/bikes/{id}/reviews/summary"]
        E_REF["/api/refresh-all<br/>/api/refresh-all/status"]
        E_SYS["/api/health<br/>/api/hardware"]
    end

    DB[(SQLite<br/>sales.db)]

    APP --> T_SALES & T_INS & T_CMP & T_REF
    T_SALES --> BP & SC & MC & SCC
    T_INS --> TT & RC
    T_CMP --> CT
    T_REF --> RT

    BP --> CTX
    CTX --> QC
    Components --> APIS
    APIS --> AX
    AX -->|HTTP /api| Backend

    QC -.polls status.- E_REF

    E_BR & E_BK & E_RV & E_SYS --> DB
    E_REF --> DB
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
