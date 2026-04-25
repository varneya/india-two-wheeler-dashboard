# Frontend — India Two-Wheeler Dashboard

Vite + React 19 + TypeScript SPA. Hosted at <https://varneya.github.io/india-two-wheeler-dashboard/>; also runs locally with `npm run dev` against a backend on `localhost:8000`.

For project-wide setup see the [root README](../README.md) and [SETUP.md](../SETUP.md). For architecture see [ARCHITECTURE.md](../ARCHITECTURE.md).

## Quick commands

```bash
npm install
npm run dev          # http://localhost:5173 — Vite proxies /api → localhost:8000
npm run build        # static bundle in dist/
npm run lint
```

## API base URL

All API clients read from `src/api/client.ts`, which exports:

- `API_BASE` — defaults to `/api`. Override at build time with `VITE_API_BASE` (the GitHub Pages workflow sets this to `http://localhost:8000/api`).
- `OLLAMA_BASE` — defaults to `http://localhost:11434`. Override with `VITE_OLLAMA_BASE`.

This means the same source builds work for local dev (Vite proxy) and for the hosted bundle (calls visitor's localhost directly).

## Notable components

| File | Purpose |
|---|---|
| `src/App.tsx` | Tab router; auto-jumps to Setup if backend is unreachable on first load |
| `src/components/SetupTab.tsx` | Status pills + install commands; polls every ~8 s |
| `src/components/InsightsTab.tsx` | Owner reviews + theme analysis (5 methods) |
| `src/components/CompareTab.tsx` | Multi-bike sales overlay |
| `src/components/RefreshTab.tsx` | One-click 3-stage data pipeline |
| `src/api/client.ts` | Shared API_BASE / OLLAMA_BASE |
| `vite.config.ts` | Sets `base: '/india-two-wheeler-dashboard/'` for production builds |

## Deploy

Pushing to `main` with changes under `frontend/**` triggers `.github/workflows/deploy.yml`, which builds and publishes to GitHub Pages. No manual step needed.
