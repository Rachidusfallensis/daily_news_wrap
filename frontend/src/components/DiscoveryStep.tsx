import { useEffect, useState, useCallback, useRef } from 'react'
import { Loader2 } from 'lucide-react'
import type { DiscoveryPack, DiscoveredItem } from '../types'
import { ProviderBadge } from './ProviderBadge'

interface DiscoveryStepProps {
  runId: number | null
  thesisText: string
  onApply: (accepted: AcceptedItems) => Promise<void>
  onSkip: () => void
  onEvent?: (event: { type: string; [key: string]: unknown }) => void
}

export interface AcceptedItems {
  sources: DiscoveredItem[]
  venues: DiscoveredItem[]
  authors: DiscoveredItem[]
}

type Stage = 'expanding' | 'resolving' | 'verifying' | 'ranking' | 'done' | 'error'

const STAGE_ORDER: Stage[] = ['expanding', 'resolving', 'verifying', 'ranking', 'done']
const STAGE_LABELS: Record<Stage, string> = {
  expanding: 'Analysing your thesis…',
  resolving: 'Searching academic providers…',
  verifying: 'Verifying sources…',
  ranking: 'Ranking results…',
  done: 'Done',
  error: 'Unavailable',
}

interface RunStatus {
  run_id: number
  status: string
  pack: DiscoveryPack | null
}

const POLL_INTERVAL_MS = 2000
const TIMEOUT_MS = 30_000

export default function DiscoveryStep({ runId, thesisText, onApply, onSkip, onEvent }: DiscoveryStepProps) {
  const [stage, setStage] = useState<Stage>('expanding')
  const [degraded, setDegraded] = useState(false)
  const [pack, setPack] = useState<DiscoveryPack | null>(null)
  const [accepted, setAccepted] = useState<Set<string>>(new Set())
  const [applying, setApplying] = useState(false)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const doneRef = useRef(false)

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
      timeoutRef.current = null
    }
  }, [])

  const setDone = useCallback((discoveryPack: DiscoveryPack) => {
    doneRef.current = true
    stopPolling()
    setPack(discoveryPack)
    setStage('done')
    setAccepted(new Set([
      ...discoveryPack.sources.map(s => `${s.name}|${s.provider}`),
      ...discoveryPack.venues.map(v => `${v.name}|${v.provider}`),
      ...discoveryPack.authors.map(a => `${a.name}|${a.provider}`),
    ]))
  }, [stopPolling])

  const fetchStatus = useCallback(async () => {
    if (!runId || doneRef.current) return
    try {
      const res = await fetch(`/api/discovery/run/${runId}`, { credentials: 'include' })
      if (!res.ok) return
      const data: RunStatus = await res.json()
      const s = data.status as Stage
      if (s === 'done' && data.pack) {
        setDone(data.pack)
      } else if (s === 'error') {
        doneRef.current = true
        stopPolling()
        setStage('error')
      } else if (STAGE_ORDER.includes(s)) {
        setStage(s)
      }
    } catch {
      // keep polling on transient errors
    }
  }, [runId, stopPolling, setDone])

  useEffect(() => {
    if (!runId) {
      setStage('error')
      return
    }
    doneRef.current = false
    setDegraded(false)
    setStage('expanding')
    fetchStatus()
    pollingRef.current = setInterval(fetchStatus, POLL_INTERVAL_MS)

    // 30s hard timeout → degraded fallback (NFR-DA9)
    timeoutRef.current = setTimeout(() => {
      if (!doneRef.current) {
        doneRef.current = true
        stopPolling()
        setDegraded(true)
        setStage('error')
      }
    }, TIMEOUT_MS)

    return stopPolling
  }, [runId, fetchStatus, stopPolling])

  // React to SSE events pushed from the server
  useEffect(() => {
    if (!onEvent || !runId) return
    const event = onEvent as unknown as { type: string; run_id?: number }
    if (!event.type) return
    const type = event.type
    if (event.run_id !== runId) return
    if (doneRef.current) return
    if (type === 'discovery:expanding') setStage('expanding')
    else if (type === 'discovery:resolving') setStage('resolving')
    else if (type === 'discovery:verifying') setStage('verifying')
    else if (type === 'discovery:ranking') setStage('ranking')
    else if (type === 'discovery:done') fetchStatus()
    else if (type === 'discovery:error') {
      doneRef.current = true
      stopPolling()
      setStage('error')
    }
  }, [onEvent, runId, fetchStatus, stopPolling])

  const toggleItem = useCallback((item: DiscoveredItem) => {
    const key = `${item.name}|${item.provider}`
    setAccepted(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  const handleApply = useCallback(async () => {
    if (!pack) return
    setApplying(true)
    try {
      const acceptedItems: AcceptedItems = {
        sources: pack.sources.filter(s => accepted.has(`${s.name}|${s.provider}`)),
        venues: pack.venues.filter(v => accepted.has(`${v.name}|${v.provider}`)),
        authors: pack.authors.filter(a => accepted.has(`${a.name}|${a.provider}`)),
      }
      await onApply(acceptedItems)
    } finally {
      setApplying(false)
    }
  }, [pack, accepted, onApply])

  function renderItem(item: DiscoveredItem) {
    const key = `${item.name}|${item.provider}`
    const isAccepted = accepted.has(key)
    return (
      <div key={key} className="flex items-center justify-between py-2 px-3 rounded-lg border border-border-subtle bg-bg-surface">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm text-text-primary truncate">{item.name}</span>
          <ProviderBadge provider={item.provider} />
          {item.verified && (
            <span className="text-[10px] text-green-600 font-medium shrink-0">verified</span>
          )}
          {item.unverifiable && (
            <span className="text-[10px] text-yellow-600 font-medium shrink-0">unverifiable</span>
          )}
        </div>
        <button
          onClick={() => toggleItem(item)}
          className={`shrink-0 ml-2 px-3 py-1 rounded-md text-xs font-medium transition-colors ${isAccepted ? 'bg-accent text-white hover:bg-accent/90' : 'border border-border-default text-text-muted hover:border-border-hover'}`}
        >
          {isAccepted ? 'Include' : 'Exclude'}
        </button>
      </div>
    )
  }

  function renderSection(title: string, items: DiscoveredItem[], emptyMsg: string) {
    return (
      <div className="mb-6">
        <h3 className="text-sm font-semibold text-text-primary mb-2">{title}</h3>
        {items.length === 0 ? (
          <p className="text-xs text-text-muted italic">{emptyMsg}</p>
        ) : (
          <div className="space-y-1.5">{items.map(renderItem)}</div>
        )}
      </div>
    )
  }

  if (stage === 'error') {
    return (
      <div>
        <div className="rounded-md bg-yellow-50 border border-yellow-200 p-4 text-sm text-yellow-800 mb-6">
          {degraded
            ? 'Source discovery timed out. You can skip this step and configure sources later in Settings → Sources.'
            : 'Source discovery is currently unavailable. You can skip this step and configure sources later.'}
        </div>
        <div className="flex items-center justify-between mt-6">
          <button onClick={onSkip} className="px-4 py-2 rounded-lg text-sm text-text-secondary hover:text-text-primary transition-colors">
            Skip
          </button>
          <button onClick={onSkip} className="px-5 py-2 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent/90 transition-colors">
            Continue →
          </button>
        </div>
      </div>
    )
  }

  if (stage !== 'done') {
    const stageIdx = STAGE_ORDER.indexOf(stage)
    const progressPct = stageIdx >= 0 ? Math.round((stageIdx / (STAGE_ORDER.length - 1)) * 100) : 0
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <Loader2 className="w-8 h-8 animate-spin text-accent mb-4" />
        <p className="text-sm text-text-muted mb-4">{STAGE_LABELS[stage]}</p>
        <div className="w-64 bg-bg-elevated rounded-full h-1.5 overflow-hidden">
          <div
            className="h-full bg-accent rounded-full transition-all duration-500"
            style={{ width: `${progressPct}%` }}
          />
        </div>
        <div className="flex gap-3 mt-3">
          {STAGE_ORDER.filter(s => s !== 'done').map((s, i) => (
            <span
              key={s}
              className={`text-[10px] transition-colors ${
                i <= stageIdx ? 'text-accent font-medium' : 'text-text-muted/50'
              }`}
            >
              {s}
            </span>
          ))}
        </div>
        <p className="text-xs text-text-muted/60 mt-4">{thesisText.slice(0, 80)}{thesisText.length > 80 ? '…' : ''}</p>
      </div>
    )
  }

  const allEmpty = pack && pack.sources.length === 0 && pack.venues.length === 0 && pack.authors.length === 0
  return (
    <div>
      <h2 className="text-lg font-semibold text-text-primary mb-1">Discovered sources</h2>
      <p className="text-sm text-text-muted mb-7 leading-relaxed">
        Baṣīra found the following sources matching your thesis. Toggle any you want to exclude, then click Apply.{' '}
        <span className="text-[11px] font-mono text-text-muted">FR-MT-59 · Step 3</span>
      </p>

      {allEmpty && (
        <div className="rounded-md bg-yellow-50 border border-yellow-200 p-4 text-sm text-yellow-800 mb-6">
          No sources were found. You can skip this step and configure sources manually later.
        </div>
      )}

      {pack && (
        <>
          {renderSection('Sources', pack.sources, 'No source venues found')}
          {renderSection('Venues', pack.venues, 'No venues found')}
          {renderSection('Authors', pack.authors, 'No authors found')}
        </>
      )}

      <div className="flex items-center justify-between mt-6">
        <button onClick={onSkip} disabled={applying} className="px-4 py-2 rounded-lg text-sm text-text-secondary hover:text-text-primary transition-colors disabled:opacity-50">
          Skip
        </button>
        <button onClick={handleApply} disabled={applying} className="px-5 py-2 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent/90 disabled:opacity-50 transition-colors">
          {applying ? 'Applying…' : 'Apply & Continue →'}
        </button>
      </div>
    </div>
  )
}
