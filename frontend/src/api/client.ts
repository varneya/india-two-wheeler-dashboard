// Shared HTTP client for all frontend → backend calls: one axios instance
// (`api`) configured with the base URL + admin header, plus an ApiError
// normalization layer so every caller sees the same error shape.
import axios from 'axios'

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

// Optional admin token for a SHARED/PUBLIC backend. When the backend has
// ADMIN_TOKEN set, its write/expensive endpoints require this header; with
// no token set server-side (the local-first default) the header is ignored.
// Sources, in priority order:
//   1. localStorage 'twd_admin_token' — lets the owner authorize the hosted
//      page at runtime (set it in devtools, then reload)
//   2. VITE_ADMIN_TOKEN baked in at build time (for a private owner build —
//      do NOT set this in a build served to the public)
// try/catch, not a typeof guard: with storage access denied (Block All
// Cookies, some webviews) even reading window.localStorage throws, and a
// module-load throw here would blank-page the whole app.
let storedToken: string | null = null
try {
  storedToken = localStorage.getItem('twd_admin_token')
} catch {
  /* storage blocked — fall through to the build-time token */
}

const ADMIN_TOKEN: string | null =
  storedToken ||
  (import.meta.env.VITE_ADMIN_TOKEN as string | undefined) ||
  null

export const adminHeaders: Record<string, string> = ADMIN_TOKEN
  ? { 'X-Admin-Token': ADMIN_TOKEN }
  : {}

// ---------------------------------------------------------------------------
// Normalized errors
// ---------------------------------------------------------------------------

// Every failed request through the shared `api` instance rejects with an
// ApiError:
//   kind 'unreachable' — no HTTP response at all (backend down, network cut)
//   kind 'http'        — the backend answered with an error status; `message`
//                        prefers FastAPI's JSON `detail` body over the bare
//                        statusText, so callers can surface it directly.
export class ApiError extends Error {
  kind: 'unreachable' | 'http'
  status?: number
  detail?: string

  constructor(
    kind: 'unreachable' | 'http',
    message: string,
    status?: number,
    detail?: string,
  ) {
    super(message)
    this.name = 'ApiError'
    this.kind = kind
    this.status = status
    this.detail = detail
  }
}

// ---------------------------------------------------------------------------
// Shared axios instance
// ---------------------------------------------------------------------------

export const api = axios.create({ baseURL: API_BASE, headers: adminHeaders })

api.interceptors.response.use(
  response => response,
  (error: unknown) => {
    if (axios.isAxiosError(error)) {
      const response = error.response
      if (response) {
        // FastAPI error bodies are {"detail": "..."}; detail can also be a
        // validation-error array (422), which we don't flatten — statusText
        // is the fallback then.
        const data = response.data as { detail?: unknown } | undefined
        const detail =
          typeof data?.detail === 'string' ? data.detail : undefined
        const message =
          detail || response.statusText || `Request failed (${response.status})`
        return Promise.reject(
          new ApiError('http', message, response.status, detail),
        )
      }
      return Promise.reject(
        new ApiError('unreachable', 'Backend unreachable — is it running?'),
      )
    }
    return Promise.reject(error)
  },
)
