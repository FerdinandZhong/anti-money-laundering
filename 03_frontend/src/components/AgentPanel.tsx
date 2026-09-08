import React, { useEffect, useState } from 'react'
import { Play, Loader2, CheckCircle2, Settings } from 'lucide-react'
import { disposeCase, investigateCase, streamSSE, api, getCaiiEndpoints, setLlmProvider } from '../api'
import type { CaiiEndpoint } from '../api'
import { PipelineStream, Md, type PipelineItem, type Verdict } from './PipelineStream'
import type { WorkflowNode } from './WorkflowGraph'

interface Props {
  caseId: string
  savedAnalysis?: { text: string; at: string }
  onDisposed?: () => void
  closed?: boolean
}

const DISPOSITIONS = [
  { value: 'SUSPICIOUS',      label: 'Suspicious — File STR',   desc: 'Escalate for SAR/STR filing.' },
  { value: 'FALSE_POSITIVE',  label: 'False Positive — Close',  desc: 'Alert is not indicative of money laundering.' },
  { value: 'NEEDS_MORE_INFO', label: 'Needs More Info',          desc: 'Request additional documents or review.' },
]

// Fixed worker order for the pipeline (matches supervisor dispatch).
const WORKER_ORDER = ['profile', 'pattern', 'network', 'screening']
// VERIFYING is only entered when an MCP server is configured (fail-soft otherwise).
const PHASES = ['COLLECTING', 'VERIFYING', 'ANALYZING', 'REVIEWED']

// Mirrors WORKER_TOOLS in 02_backend/agents/workers.py — tool chips per worker node.
const WORKER_TOOLS: Record<string, string[]> = {
  profile:   ['get_alert_detail', 'get_customer_profile'],
  pattern:   ['get_transaction_history', 'get_model_explanation'],
  network:   ['get_network_graph', 'get_device_overlap'],
  screening: ['get_customer_profile'],
}

interface LlmCfg { provider: string; model: string; available_providers: Record<string, { model: string }> }

export const AgentPanel: React.FC<Props> = ({ caseId, savedAnalysis, onDisposed, closed }) => {
  const [phase, setPhase] = useState<string | null>(null)
  const [workers, setWorkers] = useState<Record<string, PipelineItem>>({})
  const [narrative, setNarrative] = useState('')
  const [running, setRunning] = useState(false)
  const [err, setErr] = useState('')
  const [verdicts, setVerdicts] = useState<Verdict[]>([])
  const [vtools, setVtools] = useState<string[]>([])   // MCP tool names called by verification

  const [disposition, setDisposition] = useState('SUSPICIOUS')
  const [notes, setNotes] = useState('')
  const [adjudicator, setAdjudicator] = useState('')
  const [disposeMsg, setDisposeMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [llmCfg, setLlmCfg] = useState<LlmCfg | null>(null)
  const [showLlm, setShowLlm] = useState(false)
  const [caiiEndpoints, setCaiiEndpoints] = useState<CaiiEndpoint[]>([])
  const [picked, setPicked] = useState<{ name: string; model: string } | null>(null)

  useEffect(() => {
    api.get<LlmCfg>('/config/llm').then(r => setLlmCfg(r.data)).catch(() => null)
  }, [])

  useEffect(() => {
    if (showLlm && caiiEndpoints.length === 0) {
      getCaiiEndpoints().then(setCaiiEndpoints).catch(() => null)
    }
  }, [showLlm, caiiEndpoints.length])

  const switchProvider = async (provider: string) => {
    await setLlmProvider({ provider })
    setPicked(null)
    const r = await api.get<LlmCfg>('/config/llm')
    setLlmCfg(r.data)
    setShowLlm(false)
  }

  const pickEndpoint = async (ep: CaiiEndpoint) => {
    await setLlmProvider({ provider: 'caii', base_url: ep.base_url, model: ep.model })
    setPicked({ name: ep.name, model: ep.model })
    setShowLlm(false)
  }

  const handleEvent = (e: Record<string, unknown>) => {
    switch (e.type) {
      case 'phase':
        setPhase(String(e.phase))
        break
      case 'worker_start': {
        const w = String(e.worker)
        setWorkers(prev => ({ ...prev, [w]: { key: w, label: w, status: 'running', mono: true } }))
        break
      }
      case 'worker_done': {
        const w = String(e.worker)
        setWorkers(prev => ({
          ...prev,
          [w]: {
            key: w, label: w, status: 'ok', mono: true,
            detail: String(e.findings ?? ''),
            chips: (e.evidence_ids as string[]) ?? [],
          },
        }))
        break
      }
      case 'tool_call':
        setVtools(prev => [...prev, String(e.query ?? '')])
        break
      case 'verdict':
        setVerdicts(prev => [...prev, {
          claim: String(e.claim ?? ''),
          verdict: String(e.verdict ?? 'unverified'),
          sources: (e.sources as string[]) ?? [],
        }])
        break
      case 'token':
        setNarrative(prev => prev + String(e.text ?? ''))
        break
    }
  }

  const runInvestigation = async () => {
    setPhase(null); setWorkers({}); setNarrative(''); setErr('')
    setVerdicts([]); setVtools([])
    setRunning(true)
    try {
      const res = await investigateCase(caseId)
      await streamSSE(res, handleEvent)
    } catch {
      setErr('Backend not reachable — start the API server and try again.')
    }
    setRunning(false)
  }

  const handleDispose = async () => {
    try {
      await disposeCase(caseId, { disposition, notes, adjudicator })
      setDisposeMsg({ ok: true, text: `Decision recorded: ${disposition}. Case closed.` })
      onDisposed?.()
    } catch {
      setDisposeMsg({ ok: false, text: 'Submit failed — check that the backend is running.' })
    }
  }

  // Verification only appears once configured (worker_start(verification) arrived).
  const hasVerification = !!workers['verification']
  const itemOrder = [...WORKER_ORDER, ...(hasVerification ? ['verification'] : [])]
  const items = itemOrder.filter(w => workers[w]).map(w => workers[w])

  // Live DAG: 4 collectors → (verification, if configured) → narrate.
  const graphNodeOrder = [...WORKER_ORDER, ...(hasVerification ? ['verification'] : []), 'narrate']
  const graphNodes: WorkflowNode[] = running || items.length > 0 || narrative
    ? graphNodeOrder.map(id => {
        if (id === 'narrate') {
          const status: WorkflowNode['status'] =
            narrative ? (running ? 'running' : 'completed') : running && items.length === itemOrder.length ? 'running' : 'pending'
          return { id, label: 'narrate', status, llmCalls: 1 }
        }
        const w = workers[id]
        const status: WorkflowNode['status'] = !w
          ? 'pending'
          : w.status === 'running'
          ? 'running'
          : (w.detail ?? '').startsWith('Error:')
          ? 'error'
          : 'completed'
        const tools = id === 'verification'
          ? vtools.slice(0, 6).map(name => ({ name }))
          : (WORKER_TOOLS[id] ?? []).map(name => ({ name }))
        return { id, label: id, status, llmCalls: 1, tools }
      })
    : []

  return (
    <div className="space-y-5">
      {/* Section header + LLM badge */}
      <div className="flex items-start justify-between">
        <div>
          <div className="w-8 h-0.5 bg-accent mb-2" />
          <h3 className="text-sm font-bold text-ink tracking-tight">AI Investigation</h3>
          <p className="text-xs text-ink-muted mt-0.5">
            4 specialist workers investigate in parallel, then compose a narrative
          </p>
        </div>
        {llmCfg && (
          <div className="relative">
            <button
              onClick={() => setShowLlm(v => !v)}
              className="flex items-center gap-1 text-2xs text-ink-muted bg-surface-2
                         px-2 py-1 rounded-lg hover:text-accent transition-colors"
            >
              <Settings className="w-3 h-3" />
              {picked ? `caii · ${picked.name}` : `${llmCfg.provider} · ${llmCfg.model}`}
            </button>
            {showLlm && (
              <div className="absolute right-0 top-7 z-10 bg-surface-1 rounded-lg shadow-soft p-2 min-w-[180px]">
                <p className="text-2xs text-ink-faint uppercase tracking-wider px-2 pb-1">Switch provider</p>
                {Object.entries(llmCfg.available_providers).map(([p, info]) => (
                  <button
                    key={p}
                    onClick={() => switchProvider(p)}
                    className={`w-full text-left px-2 py-1.5 rounded-lg text-xs transition-colors
                      ${p === llmCfg.provider && !picked ? 'bg-accent/10 text-accent font-semibold' : 'hover:bg-surface-2 text-ink-muted'}`}
                  >
                    {p} <span className="text-ink-faint">· {info.model}</span>
                  </button>
                ))}
                {caiiEndpoints.length > 0 && (
                  <>
                    <p className="text-2xs text-ink-faint uppercase tracking-wider px-2 pt-2 pb-1 mt-1">
                      Live CAII endpoints
                    </p>
                    {caiiEndpoints.map(ep => (
                      <button
                        key={ep.name}
                        onClick={() => pickEndpoint(ep)}
                        className={`w-full text-left px-2 py-1.5 rounded-lg text-xs transition-colors
                          ${picked?.name === ep.name ? 'bg-accent/10 text-accent font-semibold' : 'hover:bg-surface-2 text-ink-muted'}`}
                      >
                        {ep.name} <span className="text-ink-faint">· {ep.model || 'model?'}</span>
                      </button>
                    ))}
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Run button */}
      <button
        onClick={runInvestigation}
        disabled={running}
        className={`flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold transition-colors w-full justify-center
          ${running
            ? 'bg-surface-3 text-ink-faint cursor-not-allowed'
            : 'bg-accent text-white hover:bg-accent-dim'
          }`}
      >
        {running
          ? <><Loader2 className="w-4 h-4 animate-spin" />Investigating…</>
          : <><Play className="w-4 h-4" />Run inference</>
        }
      </button>

      {/* Structured stream — saved analysis takes the idle slot until a fresh run starts */}
      {!running && !narrative && savedAnalysis ? (
        <div className="border-l-2 border-accent/60 pl-4">
          <div className="bg-surface-1 rounded-lg shadow-soft p-4">
            <p className="text-2xs uppercase tracking-wider text-ink-faint mb-1.5">
              Saved analysis{savedAnalysis.at ? ` · ${new Date(savedAnalysis.at).toLocaleString()}` : ''}
            </p>
            <Md text={savedAnalysis.text} />
          </div>
        </div>
      ) : (
        <PipelineStream
          phases={PHASES}
          activePhase={phase}
          items={items}
          narrative={narrative}
          narrativeTitle="Analyst narrative"
          running={running}
          idle={'// Run inference to stream the agent analysis…'}
          graphNodes={graphNodes}
          verdicts={verdicts}
        />
      )}
      {err && (
        <p className="text-xs text-aml-red bg-aml-red/5 px-3 py-2 rounded-lg">{err}</p>
      )}

      {/* Dispose form */}
      <div className="rounded-lg p-5 bg-surface-2">
        <div className="mb-3">
          <div className="w-8 h-0.5 bg-accent mb-2" />
          <h4 className="text-sm font-bold text-ink tracking-tight">Record Decision</h4>
          <p className="text-xs text-ink-muted mt-0.5">
            After reviewing the agent report, select an outcome and submit to close the case.
          </p>
        </div>

        {/* Disposition picker — radio-style cards */}
        <div className="space-y-1.5 mb-3">
          {DISPOSITIONS.map(d => (
            <label
              key={d.value}
              className={`flex items-start gap-2.5 p-2.5 rounded-lg border cursor-pointer transition-colors
                ${disposition === d.value
                  ? 'border-accent bg-accent/5'
                  : 'border-surface-3 bg-surface-1 hover:border-surface-4'}`}
            >
              <input
                type="radio"
                name="disposition"
                value={d.value}
                checked={disposition === d.value}
                onChange={() => setDisposition(d.value)}
                className="mt-0.5 accent-accent"
              />
              <div>
                <p className="text-xs font-semibold text-ink">{d.label}</p>
                <p className="text-2xs text-ink-muted">{d.desc}</p>
              </div>
            </label>
          ))}
        </div>

        <div className="flex gap-2 mb-3">
          <div className="space-y-1 flex-1">
            <label className="text-2xs text-ink-muted uppercase tracking-wider">Analyst ID</label>
            <input
              value={adjudicator}
              onChange={e => setAdjudicator(e.target.value)}
              placeholder="e.g. jsmith"
              className="w-full bg-surface-1 border border-surface-3 rounded-lg text-xs text-ink
                         px-3 py-2 outline-none focus:border-accent placeholder-ink-faint"
            />
          </div>
          <div className="space-y-1 flex-[2]">
            <label className="text-2xs text-ink-muted uppercase tracking-wider">Notes</label>
            <input
              value={notes}
              onChange={e => setNotes(e.target.value)}
              placeholder="Brief rationale for this decision…"
              className="w-full bg-surface-1 border border-surface-3 rounded-lg text-xs text-ink
                         px-3 py-2 outline-none focus:border-accent placeholder-ink-faint"
            />
          </div>
        </div>

        <button
          onClick={handleDispose}
          disabled={!!closed}
          className={`flex items-center gap-1.5 px-4 py-2 text-white
                     text-xs font-semibold rounded-lg transition-colors w-full justify-center
                     ${closed ? 'bg-accent/40 cursor-not-allowed' : 'bg-accent hover:bg-accent-dim'}`}
        >
          <CheckCircle2 className="w-3.5 h-3.5" />
          Submit Decision
        </button>

        {(closed || disposeMsg) && (
          <p className={`mt-3 text-xs px-3 py-2 rounded-lg ${
            !disposeMsg || disposeMsg.ok
              ? 'text-aml-green-dim bg-aml-green/10'
              : 'text-aml-red-dim bg-aml-red/10'
          }`}>
            {disposeMsg ? disposeMsg.text : 'Decision recorded. Case closed.'}
          </p>
        )}
      </div>
    </div>
  )
}
