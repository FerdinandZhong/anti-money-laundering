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

interface Props {
  phases: string[]              // ordered phase names for the stepper
  activePhase: string | null
  items: PipelineItem[]
  narrative?: string
  narrativeTitle?: string
  running?: boolean
  idle?: React.ReactNode        // shown before the first run
  graphNodes?: WorkflowNode[]   // optional live DAG rendered above the phase stepper
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
  phases, activePhase, items, narrative, narrativeTitle = 'Narrative', running, idle, graphNodes,
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

      {/* Streamed narrative */}
      {narrative && (
        <div className="bg-surface-1 rounded-lg shadow-soft p-4">
          <p className="text-2xs uppercase tracking-wider text-ink-faint mb-1.5">{narrativeTitle}</p>
          <p className="text-xs text-ink leading-relaxed whitespace-pre-wrap">
            {narrative}
            {running && <span className="inline-block w-1.5 h-3.5 ml-0.5 bg-accent/70 align-middle animate-pulse" />}
          </p>
        </div>
      )}
    </div>
  )
}
