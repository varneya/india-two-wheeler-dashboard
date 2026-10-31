import { Cpu } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { fetchPullProgress, pullOllamaModel, type PullProgress } from '../../api/themesApi'
import type { HardwareReport, OllamaModel } from '../../types/themes'
import { Button } from '../ui/button'
import { Card, CardContent } from '../ui/card'

function formatBytes(n: number): string {
  if (!n) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = n
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(v >= 100 ? 0 : 1)} ${units[i]}`
}

function HardwareCard({
  hw,
  onPull,
}: {
  hw: HardwareReport
  onPull: (model: string) => void
}) {
  const { hardware, ollama, recommended_models } = hw
  const [progress, setProgress] = useState<Record<string, PullProgress>>({})
  const pollersRef = useRef<Record<string, ReturnType<typeof setInterval>>>({})

  // If Ollama is running and at least one model is pulled, collapse by default —
  // the user has already done the one-time setup and doesn't need to see this
  // every time. They can click the row to expand if they want to pull another.
  const hasReadyModel = ollama.running && (ollama.pulled_models?.length ?? 0) > 0
  const [expanded, setExpanded] = useState(!hasReadyModel)

  function stopPolling(name: string) {
    const t = pollersRef.current[name]
    if (t) {
      clearInterval(t)
      delete pollersRef.current[name]
    }
  }

  // Cleanup intervals on unmount
  useEffect(() => () => {
    Object.values(pollersRef.current).forEach(clearInterval)
    pollersRef.current = {}
  }, [])

  async function handlePull(name: string) {
    if (pollersRef.current[name]) return // already polling
    setProgress(p => ({
      ...p,
      [name]: { status: 'starting', completed: 0, total: 0, percent: 0, error: null, finished: false },
    }))
    try {
      await pullOllamaModel(name)
    } catch (e) {
      setProgress(p => ({
        ...p,
        [name]: { ...p[name], status: 'error', error: String(e), finished: true },
      }))
      return
    }

    pollersRef.current[name] = setInterval(async () => {
      try {
        const pr = await fetchPullProgress(name)
        setProgress(p => ({ ...p, [name]: pr }))
        if (pr.finished) {
          stopPolling(name)
          // Refresh hardware so the model shows as ready
          setTimeout(() => onPull(name), 500)
        }
      } catch {
        stopPolling(name)
      }
    }, 600)
  }

  // ---- Collapsed state: tiny one-liner ----
  if (!expanded) {
    const readyModel = ollama.pulled_models?.[0] ?? '—'
    return (
      <button
        onClick={() => setExpanded(true)}
        className="w-full flex items-center justify-between bg-card hover:bg-accent/50 border border-border rounded-xl px-4 py-2.5 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-emerald-400" />
          <span className="text-sm text-muted-foreground">
            Local LLM ready · <span className="font-mono text-foreground">{readyModel}</span>
          </span>
          <span className="text-xs text-muted-foreground/70 hidden sm:inline">
            on {hardware.chip} · {hardware.ram_gb} GB
          </span>
        </div>
        <span className="text-xs text-muted-foreground hover:text-foreground">Change ▾</span>
      </button>
    )
  }

  // ---- Expanded state: full card ----
  return (
    <Card>
      <CardContent className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-primary/15 border border-primary/30 flex items-center justify-center text-primary">
          <Cpu className="w-4 h-4" />
        </div>
        <div>
          <p className="font-semibold text-foreground text-sm">{hardware.chip}</p>
          <p className="text-muted-foreground text-xs">{hardware.ram_gb} GB unified memory</p>
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          <div
            className={`w-2 h-2 rounded-full ${
              ollama.running ? 'bg-emerald-400' : ollama.installed ? 'bg-amber-400' : 'bg-red-400'
            }`}
          />
          <span className="text-xs text-muted-foreground">
            {ollama.running ? 'Ollama running' : ollama.installed ? 'Ollama installed (not running)' : 'Ollama not installed'}
          </span>
          {hasReadyModel && (
            <button
              onClick={() => setExpanded(false)}
              className="ml-2 text-xs text-muted-foreground hover:text-foreground"
              title="Collapse"
            >
              ▴
            </button>
          )}
        </div>
      </div>

      {!ollama.installed && (
        <div className="bg-slate-700/50 border border-slate-600 rounded-lg px-4 py-3 text-sm text-slate-300 space-y-1">
          <p className="font-medium text-white">Install Ollama to use local models:</p>
          <code className="block text-xs bg-slate-900 rounded px-2 py-1 text-emerald-300 mt-1">
            chmod +x scripts/install_ollama.sh && ./scripts/install_ollama.sh
          </code>
        </div>
      )}

      {!ollama.running && ollama.installed && (
        <div className="bg-amber-900/20 border border-amber-700/40 rounded-lg px-4 py-3 text-sm text-amber-300">
          Ollama is installed but not running.{' '}
          <code className="bg-amber-900/40 px-1 rounded text-xs">ollama serve</code>
        </div>
      )}

      {ollama.running && recommended_models.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-slate-400 uppercase tracking-wide">
            Recommended models for your Mac
          </p>
          <div className="space-y-1.5">
            {recommended_models.map((m: OllamaModel) => {
              const pr = progress[m.name]
              const isPulling = pr && !pr.finished
              const justFinished = pr && pr.finished && !pr.error
              const failed = pr && pr.error

              return (
                <div
                  key={m.name}
                  className="bg-slate-700/40 rounded-lg px-3 py-2 space-y-1.5"
                >
                  <div className="flex items-center gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-sm text-white font-mono">{m.name}</p>
                        {m.recommended && (
                          <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded-full bg-violet-500/15 text-violet-300 border border-violet-500/30 font-medium">
                            Recommended
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-slate-400 truncate">
                        {m.size_label} · {m.quality} · {m.description}
                      </p>
                    </div>
                    {m.pulled || justFinished ? (
                      <span className="text-xs text-emerald-400 font-medium shrink-0">✓ ready</span>
                    ) : isPulling ? (
                      <span className="text-xs text-amber-400 font-mono shrink-0 tabular-nums">
                        {pr.percent.toFixed(1)}%
                      </span>
                    ) : (
                      <Button
                        size="sm"
                        onClick={() => handlePull(m.name)}
                        className="shrink-0"
                      >
                        Pull
                      </Button>
                    )}
                  </div>

                  {/* Progress bar */}
                  {isPulling && (
                    <div className="space-y-1">
                      <div className="h-1.5 w-full bg-slate-900/60 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-gradient-to-r from-blue-500 to-cyan-400 transition-all duration-300 ease-out"
                          style={{ width: `${Math.max(pr.percent, 2)}%` }}
                        />
                      </div>
                      <div className="flex items-center justify-between text-[10px] text-slate-400 font-mono tabular-nums">
                        <span className="capitalize">{pr.status}</span>
                        <span>
                          {pr.total > 0
                            ? `${formatBytes(pr.completed)} / ${formatBytes(pr.total)}`
                            : '...'}
                        </span>
                      </div>
                    </div>
                  )}
                  {failed && (
                    <p className="text-[10px] text-destructive">Error: {pr.error}</p>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
      </CardContent>
    </Card>
  )
}

export function HardwarePanel({
  hw,
  hwLoading,
  hwError,
  onPull,
}: {
  hw: HardwareReport | null
  hwLoading: boolean
  hwError: string | null
  onPull: (model: string) => void
}) {
  return (
    <div>
      <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
        Your Hardware
      </h2>
      {hwLoading ? (
        <Card className="h-24 animate-pulse" />
      ) : hw && !hwError ? (
        <HardwareCard hw={hw} onPull={onPull} />
      ) : (
        <Card className="py-3">
          <CardContent className="text-sm text-muted-foreground">
            {hwError ?? 'Could not detect hardware. Is the backend running?'}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
