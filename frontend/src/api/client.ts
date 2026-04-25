// Shared API base URL for all frontend → backend calls.
//
// - In local dev: defaults to '/api', which Vite's proxy forwards to
//   http://localhost:8000 (see vite.config.ts).
// - In a production build: set VITE_API_BASE at build time to point at the
//   user's locally-running backend, e.g. http://localhost:8000/api.
export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? '/api'

// Optional Ollama base URL for browser-side probing in the Setup tab.
export const OLLAMA_BASE: string =
  (import.meta.env.VITE_OLLAMA_BASE as string | undefined) ??
  'http://localhost:11434'
