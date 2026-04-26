import { useEffect, useState } from 'react'
import { CheckCircle2, XCircle, RefreshCw, ExternalLink } from 'lucide-react'
import { Card } from './ui/card'
import { Badge } from './ui/badge'
import { Button } from './ui/button'
import { API_BASE, OLLAMA_BASE } from '../api/client'

type Probe = 'unknown' | 'ok' | 'down'

interface OllamaStatus {
  state: Probe
  models: string[]
}

const REQUIRED_MODELS = ['nomic-embed-text', 'mistral:7b']

// Ollama auto-appends `:latest` when a model is pulled without an explicit
// tag, so `nomic-embed-text` shows up as `nomic-embed-text:latest` in
// /api/tags. Treat the bare name and `:latest` as equivalent.
function hasModel(required: string, pulled: string[]): boolean {
  if (pulled.includes(required)) return true
  if (!required.includes(':')) return pulled.includes(`${required}:latest`)
  return false
}

type Platform = 'mac' | 'windows' | 'linux'

function detectPlatform(): Platform {
  if (typeof navigator === 'undefined') return 'mac'
  const ua = navigator.userAgent.toLowerCase()
  if (ua.includes('win')) return 'windows'
  if (ua.includes('mac')) return 'mac'
  if (ua.includes('linux')) return 'linux'
  return 'mac'
}

interface PlatformCommands {
  prereqs: string
  backend: string
  ollama: string
  models: string
  notes?: string
}

const INSTALL_COMMANDS: Record<Platform, PlatformCommands> = {
  mac: {
    prereqs: `# One-time: install Python 3.10+, Node 20+, Git
brew install python@3.12 node git`,
    backend: `git clone https://github.com/varneya/india-two-wheeler-dashboard.git
cd india-two-wheeler-dashboard

# Easiest: bundled bootstrap script (Python check, venv, pip install)
chmod +x scripts/install_backend.sh
./scripts/install_backend.sh

# Then start the server
cd backend && source venv/bin/activate
uvicorn main:app --port 8000`,
    ollama: `# Install
brew install ollama

# Start with this origin allowlisted (so the hosted page can reach it)
OLLAMA_ORIGINS="https://varneya.github.io" ollama serve`,
    models: `ollama pull nomic-embed-text
ollama pull mistral:7b      # or llama3.2:3b for 8 GB RAM, phi3:mini for 4 GB`,
    notes: `Tip: to keep OLLAMA_ORIGINS set across reboots, run
launchctl setenv OLLAMA_ORIGINS "https://varneya.github.io"
once and restart the Ollama.app from /Applications.`,
  },
  windows: {
    prereqs: `# One-time, in PowerShell as Admin: install Node 20+ and Git
# (the backend bootstrap script will install Python 3.12 if missing)
winget install OpenJS.NodeJS Git.Git`,
    backend: `git clone https://github.com/varneya/india-two-wheeler-dashboard.git
cd india-two-wheeler-dashboard

# Easiest: bundled bootstrap script (installs Python 3.12 via winget if
# needed, creates venv, pip install -r requirements.txt). The .cmd
# wrapper sidesteps the default ExecutionPolicy that blocks .ps1 files.
scripts\\install_backend.cmd

# Then start the server
cd backend
.\\venv\\Scripts\\activate
uvicorn main:app --port 8000`,
    ollama: `# Easiest: bundled installer (sets OLLAMA_ORIGINS persistently,
# pulls a default model, smoke-tests it). The .cmd wrapper handles
# Windows' default ExecutionPolicy for you.
scripts\\install_ollama.cmd

# Manual alternative — download installer from
# https://ollama.com/download/windows, then in PowerShell:
$env:OLLAMA_ORIGINS = "https://varneya.github.io"
ollama serve`,
    models: `ollama pull nomic-embed-text
ollama pull mistral:7b      # or llama3.2:3b for 8 GB RAM, phi3:mini for 4 GB`,
    notes: `Tip: the bundled installer persists OLLAMA_ORIGINS via
[Environment]::SetEnvironmentVariable(...) so it survives reboots.
If you went the manual route, set it once via System Properties →
Environment Variables and restart Ollama.`,
  },
  linux: {
    prereqs: `# One-time (Debian/Ubuntu): install Python 3.10+, Node 20+, Git
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nodejs npm git`,
    backend: `git clone https://github.com/varneya/india-two-wheeler-dashboard.git
cd india-two-wheeler-dashboard

# Easiest: bundled bootstrap script (Python check, venv, pip install)
chmod +x scripts/install_backend.sh
./scripts/install_backend.sh

# Then start the server
cd backend && source venv/bin/activate
uvicorn main:app --port 8000`,
    ollama: `# Install
curl -fsSL https://ollama.com/install.sh | sh

# Start with this origin allowlisted
OLLAMA_ORIGINS="https://varneya.github.io" ollama serve`,
    models: `ollama pull nomic-embed-text
ollama pull mistral:7b      # or llama3.2:3b for 8 GB RAM, phi3:mini for 4 GB`,
    notes: `Tip: if running Ollama as a systemd service,
sudo systemctl edit ollama.service
and add Environment="OLLAMA_ORIGINS=https://varneya.github.io" under [Service].`,
  },
}

async function probeBackend(): Promise<Probe> {
  try {
    const res = await fetch(`${API_BASE}/health`, { cache: 'no-store' })
    return res.ok ? 'ok' : 'down'
  } catch {
    return 'down'
  }
}

async function probeOllama(): Promise<OllamaStatus> {
  try {
    const res = await fetch(`${OLLAMA_BASE}/api/tags`, { cache: 'no-store' })
    if (!res.ok) return { state: 'down', models: [] }
    const json = (await res.json()) as { models?: { name: string }[] }
    const models = (json.models ?? []).map(m => m.name)
    return { state: 'ok', models }
  } catch {
    return { state: 'down', models: [] }
  }
}

function StatusPill({ state, label }: { state: Probe; label: string }) {
  if (state === 'unknown') return <Badge variant="secondary">checking…</Badge>
  if (state === 'ok')
    return (
      <Badge variant="success" className="gap-1">
        <CheckCircle2 /> {label}
      </Badge>
    )
  return (
    <Badge variant="destructive" className="gap-1">
      <XCircle /> {label}
    </Badge>
  )
}

function CodeBlock({ children }: { children: string }) {
  return (
    <pre className="bg-muted/50 border rounded-md p-3 text-xs overflow-x-auto font-mono">
      <code>{children}</code>
    </pre>
  )
}

export function SetupTab() {
  const [backend, setBackend] = useState<Probe>('unknown')
  const [ollama, setOllama] = useState<OllamaStatus>({ state: 'unknown', models: [] })
  const [checking, setChecking] = useState(false)

  async function recheck() {
    setChecking(true)
    const [b, o] = await Promise.all([probeBackend(), probeOllama()])
    setBackend(b)
    setOllama(o)
    setChecking(false)
  }

  useEffect(() => {
    void recheck()
    const id = setInterval(recheck, 8000)
    return () => clearInterval(id)
  }, [])

  const missingModels = REQUIRED_MODELS.filter(m => !hasModel(m, ollama.models))
  const modelsState: Probe =
    ollama.state !== 'ok' ? 'unknown' : missingModels.length === 0 ? 'ok' : 'down'

  const allGreen = backend === 'ok' && ollama.state === 'ok' && modelsState === 'ok'
  const [platform, setPlatform] = useState<Platform>(detectPlatform)
  const cmds = INSTALL_COMMANDS[platform]

  return (
    <div className="flex flex-col gap-6">
      {/* Status panel */}
      <Card className="p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Local environment status</h2>
          <Button variant="outline" size="sm" onClick={recheck} disabled={checking}>
            <RefreshCw className={checking ? 'animate-spin' : ''} /> Re-check
          </Button>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="border rounded-md p-4 flex flex-col gap-2">
            <div className="text-sm text-muted-foreground">Backend</div>
            <StatusPill state={backend} label={backend === 'ok' ? 'reachable' : 'not reachable'} />
            <div className="text-xs text-muted-foreground break-all">{API_BASE}</div>
            <div className="text-xs text-muted-foreground mt-1">
              Required for sales charts, reviews, FADA data, all theming methods.
            </div>
          </div>

          <div className="border rounded-md p-4 flex flex-col gap-2">
            <div className="text-sm text-muted-foreground">Ollama</div>
            <StatusPill state={ollama.state} label={ollama.state === 'ok' ? `running (${ollama.models.length} models)` : 'not reachable'} />
            <div className="text-xs text-muted-foreground break-all">{OLLAMA_BASE}</div>
            <div className="text-xs text-muted-foreground mt-1">
              Required for semantic / BERTopic / local-LLM theming.
            </div>
          </div>

          <div className="border rounded-md p-4 flex flex-col gap-2">
            <div className="text-sm text-muted-foreground">Models</div>
            <StatusPill
              state={modelsState}
              label={
                ollama.state !== 'ok'
                  ? 'awaiting Ollama'
                  : missingModels.length === 0
                  ? 'all pulled'
                  : `missing ${missingModels.length}`
              }
            />
            <div className="text-xs text-muted-foreground">
              {REQUIRED_MODELS.map(m => (
                <div key={m} className="flex items-center gap-1">
                  {hasModel(m, ollama.models) ? '✓' : '·'} {m}
                </div>
              ))}
            </div>
          </div>
        </div>

        {allGreen && (
          <div className="mt-4 text-sm text-emerald-400">
            ✓ All set — head to the Sales Data or Owner Insights tab.
          </div>
        )}
      </Card>

      {/* Install instructions — always shown so users can come back later. */}
      <Card className="p-6 flex flex-col gap-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h2 className="text-lg font-semibold mb-1">
              {allGreen ? 'How this works (for reference)' : 'Set up your local environment'}
            </h2>
            <p className="text-sm text-muted-foreground max-w-prose">
              The dashboard runs in your browser, but the data scrapers and ML models run on your
              machine — nothing is sent to a third-party server (except optional Anthropic API
              calls, if you use them).
            </p>
          </div>

          {/* Platform selector */}
          <div className="inline-flex rounded-md bg-muted/40 p-1 text-xs font-medium">
            {(['mac', 'windows', 'linux'] as Platform[]).map(p => (
              <button
                key={p}
                type="button"
                onClick={() => setPlatform(p)}
                className={`px-3 py-1 rounded ${
                  platform === p
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                {p === 'mac' ? 'macOS' : p === 'windows' ? 'Windows' : 'Linux'}
              </button>
            ))}
          </div>
        </div>

        {/* Step 0: prerequisites */}
        <section className="flex flex-col gap-2">
          <h3 className="font-medium">Prerequisites</h3>
          <p className="text-sm text-muted-foreground">
            Python 3.10+, Node.js 20+, and Git. Skip if you already have them.
          </p>
          <CodeBlock>{cmds.prereqs}</CodeBlock>
        </section>

        {/* Step 1: backend */}
        <section className="flex flex-col gap-2">
          <h3 className="font-medium">1. Run the backend locally</h3>
          <p className="text-sm text-muted-foreground">
            Clone the repo and start FastAPI on port 8000. First-time install pulls in pandas +
            scikit-learn + hdbscan + Prophet, which can take a few minutes.
          </p>
          <CodeBlock>{cmds.backend}</CodeBlock>
        </section>

        {/* Step 2: ollama */}
        <section className="flex flex-col gap-2">
          <h3 className="font-medium">2. Install &amp; start Ollama</h3>
          <p className="text-sm text-muted-foreground">
            <code>OLLAMA_ORIGINS</code> lets the browser at <code>varneya.github.io</code> talk
            to Ollama on <code>localhost</code> — without it, requests get blocked by CORS.
          </p>
          <CodeBlock>{cmds.ollama}</CodeBlock>
          {cmds.notes && (
            <p className="text-xs text-muted-foreground whitespace-pre-line">{cmds.notes}</p>
          )}
        </section>

        {/* Step 3: models */}
        <section className="flex flex-col gap-2">
          <h3 className="font-medium">3. Pull the models</h3>
          <p className="text-sm text-muted-foreground">
            <code>nomic-embed-text</code> (~274 MB) is the embedding model.{' '}
            <code>mistral:7b</code> (~4.4 GB) handles BERTopic naming and the LLM-themes method.
          </p>
          <CodeBlock>{cmds.models}</CodeBlock>
        </section>

        <div className="text-sm">
          Full guide with troubleshooting:{' '}
          <a
            href="https://github.com/varneya/india-two-wheeler-dashboard/blob/main/SETUP.md"
            target="_blank"
            rel="noreferrer"
            className="text-primary hover:underline inline-flex items-center gap-1"
          >
            SETUP.md on GitHub <ExternalLink className="size-3" />
          </a>
        </div>
      </Card>
    </div>
  )
}
