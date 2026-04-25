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

  const missingModels = REQUIRED_MODELS.filter(m => !ollama.models.includes(m))
  const modelsState: Probe =
    ollama.state !== 'ok' ? 'unknown' : missingModels.length === 0 ? 'ok' : 'down'

  const allGreen = backend === 'ok' && ollama.state === 'ok' && modelsState === 'ok'

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
                  {ollama.models.includes(m) ? '✓' : '·'} {m}
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

      {/* Install instructions */}
      {!allGreen && (
        <Card className="p-6 flex flex-col gap-6">
          <div>
            <h2 className="text-lg font-semibold mb-1">Set up your local environment</h2>
            <p className="text-sm text-muted-foreground">
              The dashboard runs in your browser, but the data scrapers and ML models run on your
              machine — nothing is sent to a third-party server (except optional Anthropic API
              calls, if you use them).
            </p>
          </div>

          {/* Step 1: backend */}
          <section className="flex flex-col gap-2">
            <h3 className="font-medium">1. Run the backend locally</h3>
            <p className="text-sm text-muted-foreground">
              Clone the repo and start FastAPI. Python 3.10+ required.
            </p>
            <CodeBlock>{`git clone https://github.com/varneya/india-two-wheeler-dashboard.git
cd india-two-wheeler-dashboard/backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --port 8000`}</CodeBlock>
            <p className="text-xs text-muted-foreground">
              Windows: replace <code>source venv/bin/activate</code> with{' '}
              <code>venv\Scripts\activate</code>.
            </p>
          </section>

          {/* Step 2: ollama */}
          <section className="flex flex-col gap-2">
            <h3 className="font-medium">2. Install &amp; start Ollama</h3>
            <p className="text-sm text-muted-foreground">
              The <code>OLLAMA_ORIGINS</code> env var lets your browser at{' '}
              <code>varneya.github.io</code> talk to Ollama on <code>localhost</code>.
            </p>
            <CodeBlock>{`# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh

# Windows: download installer from https://ollama.com/download

# Start the server with this origin allowlisted
OLLAMA_ORIGINS="https://varneya.github.io" ollama serve`}</CodeBlock>
          </section>

          {/* Step 3: models */}
          <section className="flex flex-col gap-2">
            <h3 className="font-medium">3. Pull the models</h3>
            <p className="text-sm text-muted-foreground">
              <code>nomic-embed-text</code> for embeddings, <code>mistral:7b</code> for LLM theming
              and BERTopic auto-naming. Pick a smaller chat model if you have ≤8 GB RAM.
            </p>
            <CodeBlock>{`ollama pull nomic-embed-text
ollama pull mistral:7b      # or llama3.2:3b for 8 GB RAM, phi3:mini for 4 GB`}</CodeBlock>
          </section>

          <div className="text-sm">
            Full guide:{' '}
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
      )}
    </div>
  )
}
