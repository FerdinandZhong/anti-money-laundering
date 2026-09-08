import React from 'react'
import { Loader2, CheckCircle2, MinusCircle, AlertTriangle } from 'lucide-react'
import { WorkflowGraph, type WorkflowNode } from './WorkflowGraph'

/** One row in a streamed pipeline — a worker (investigation) or a step (retrain). */
export interface PipelineItem {
  key: string
  label: string
  status: 'running' | 'ok' | 'skip' | 'error'
  detail?: string        // worker findings (bullet lines) or step detail
  chips?: string[]       // evidence ids
  mono?: boolean         // render label mono (console character)
}

/** One verification verdict for a factual claim (from the MCP verification worker). */
export interface Verdict {
  claim: string
  verdict: 'confirmed' | 'refuted' | 'unverified' | string
  sources: string[]
}

interface Props {
  phases: string[]              // ordered phase names for the stepper
  activePhase: string | null
  items: PipelineItem[]
  narrative?: string
  narrativeTitle?: string
  running?: boolean
  idle?: React.ReactNode        // shown before the first run
  graphNodes?: WorkflowNode[]   // optional live DAG rendered above the phase stepper
  verdicts?: Verdict[]          // verification verdicts, rendered as a card before the narrative
}

/** Minimal markdown renderer: **bold**, numbered section headers, bullet lines. No deps. */
export const Md: React.FC<{ text: string; running?: boolean }> = ({ text, running }) => {
  const bold = (s: string): React.ReactNode[] =>
    s.split(/\*\*(.+?)\*\*/g).map((p, i) => i % 2 === 1 ? <strong key={i}>{p}</strong> : p as React.ReactNode)

  return (
    <div className="text-xs text-ink leading-relaxed space-y-0.5">
      {text.split('\n').map((line, i, arr) => {
        const cursor = running && i === arr.length - 1
          ? <span className="inline-block w-1.5 h-3.5 ml-0.5 bg-accent/70 align-middle animate-pulse" />
          : null
        if (line === '') return <div key={i} className="h-1" />
        if (/^\d+\.\s/.test(line))
          return <p key={i} className="font-semibold text-ink mt-2 first:mt-0">{bold(line)}{cursor}</p>
        if (line.startsWith('- '))
          return <p key={i} className="pl-3">{bold(line.slice(2))}{cursor}</p>
        return <p key={i}>{bold(line)}{cursor}</p>
      })}
    </div>
  )
}

const VERDICT_STYLE: Record<string, string> = {
  confirmed:  'text-aml-green bg-aml-green/10',
  refuted:    'text-aml-red bg-aml-red/10',
  unverified: 'text-amber-600 bg-amber-500/10',
}

const STATUS: Record<PipelineItem['status'], { cls: string; icon: React.ReactNode }> = {
  running: { cls: 'text-accent',    icon: <Loader2 className="w-3.5 h-3.5 animate-spin" /> },
  ok:      { cls: 'text-aml-green', icon: <CheckCircle2 className="w-3.5 h-3.5" /> },
  skip:    { cls: 'text-ink-faint', icon: <MinusCircle className="w-3.5 h-3.5" /> },
  error:   { cls: 'text-aml-red',   icon: <AlertTriangle className="w-3.5 h-3.5" /> },
}

/** Presentational renderer for an SSE pipeline: a phase stepper, per-item status
 *  cards with evidence chips, and a streamed narrative. Callers reduce their own
 *  events (worker_* or step) into `items` — this component stays vocabulary-free. */
export const PipelineStream: React.FC<Props> = ({
  phases, activePhase, items, narrative, narrativeTitle = 'Narrative', running, idle, graphNodes, verdicts,
}) => {
  const activeIdx = activePhase ? phases.indexOf(activePhase) : -1
  const started = items.length > 0 || activeIdx >= 0 || running

  if (!started && idle) {
    return <div className="border-l-2 border-surface-3 pl-4 py-3 text-2xs text-ink-faint font-mono">{idle}</div>
  }

  return (
    <div className="border-l-2 border-accent/60 pl-4 space-y-3">
      {/* Live DAG */}
      {graphNodes && graphNodes.length > 0 && (
        <WorkflowGraph nodes={graphNodes} running={running} />
      )}

      {/* Phase stepper */}
      {phases.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {phases.map((p, i) => {
            const done = activeIdx > i
            const active = activeIdx === i
            return (
              <span
                key={p}
                className={`text-2xs font-semibold px-2 py-0.5 rounded-full tracking-wide transition-colors
                  ${active ? 'bg-accent text-white'
                    : done ? 'bg-accent/10 text-accent'
                    : 'bg-surface-2 text-ink-faint'}`}
              >
                {p}
              </span>
            )
          })}
        </div>
      )}

      {/* Item cards */}
      <div className="space-y-2">
        {items.map(it => {
          const s = STATUS[it.status]
          return (
            <div key={it.key} className="bg-surface-1 rounded-lg shadow-soft p-3 animate-fade-in">
              <div className={`flex items-center gap-2 ${s.cls}`}>
                {s.icon}
                <span className={`text-xs font-semibold text-ink ${it.mono ? 'font-mono' : ''}`}>
                  {it.label}
                </span>
              </div>
              {it.detail && (
                <p className="text-2xs text-ink-muted mt-1.5 whitespace-pre-wrap leading-relaxed">
                  {it.detail}
                </p>
              )}
              {it.chips && it.chips.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2">
                  {it.chips.map(c => (
                    <span key={c} className="text-2xs font-mono text-ink-faint bg-surface-2 rounded-lg px-1.5 py-0.5">
                      {c}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Verification verdicts */}
      {verdicts && verdicts.length > 0 && (
        <div className="bg-surface-1 rounded-lg shadow-soft p-4 animate-fade-in">
          <p className="text-2xs uppercase tracking-wider text-ink-faint mb-2">Verification verdicts</p>
          <div className="space-y-2">
            {verdicts.map((v, i) => (
              <div key={i} className="text-xs">
                <div className="flex items-start gap-2">
                  <span className={`text-2xs font-semibold px-1.5 py-0.5 rounded-full uppercase tracking-wide shrink-0
                    ${VERDICT_STYLE[v.verdict] ?? 'text-ink-faint bg-surface-2'}`}>
                    {v.verdict}
                  </span>
                  <span className="text-ink leading-snug">{v.claim}</span>
                </div>
                {v.sources.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1 ml-1">
                    {v.sources.map((s, j) => {
                      const isUrl = /^https?:\/\//.test(s)
                      return isUrl ? (
                        <a key={j} href={s} target="_blank" rel="noreferrer"
                           className="text-2xs text-accent hover:underline break-all">{s}</a>
                      ) : (
                        <span key={j} className="text-2xs text-ink-faint bg-surface-2 rounded px-1.5 py-0.5 break-all">{s}</span>
                      )
                    })}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Streamed narrative */}
      {narrative && (
        <div className="bg-surface-1 rounded-lg shadow-soft p-4">
          <p className="text-2xs uppercase tracking-wider text-ink-faint mb-1.5">{narrativeTitle}</p>
          <Md text={narrative} running={running} />
        </div>
      )}
    </div>
  )
}
