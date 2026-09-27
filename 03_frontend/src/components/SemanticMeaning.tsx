import { useEffect, useState } from 'react'
import { getCaseSemanticContext } from '../api'
import type { CaseDetail, SemanticContext } from '../api'
import { businessLabel, contextDate } from './semanticPresentation'

const concepts = [
  { id: 'customer', title: 'Customer', kind: 'Entity', question: 'Who holds the accounts?', tone: 'border-surface-3 bg-surface-2 text-ink' },
  { id: 'kyc_declaration', title: 'Expected turnover', kind: 'Declared value', question: 'What activity was expected?', tone: 'border-surface-3 bg-surface-2 text-ink' },
  { id: 'observed_outbound_flow_30d', title: 'Observed outflow', kind: 'Calculated metric', question: 'What activity was recorded?', tone: 'border-surface-3 bg-surface-2 text-ink' },
  { id: 'account_priority_score', title: 'Review priority', kind: 'Model output', question: 'Which account needs attention?', tone: 'border-surface-3 bg-surface-2 text-ink' },
]

export function SemanticMeaning({ detail }: { detail: CaseDetail }) {
  const [context, setContext] = useState<SemanticContext | null>(null)
  const [selected, setSelected] = useState('kyc_declaration')
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let active = true
    setContext(null); setFailed(false)
    getCaseSemanticContext(detail.customer_id, 'score_explanation', detail.alert_id)
      .then(value => { if (active) setContext(value) })
      .catch(() => { if (active) setFailed(true) })
    return () => { active = false }
  }, [detail.customer_id, detail.alert_id])
  const fact = context?.facts.find(item => item.concept === selected)
  const concept = concepts.find(item => item.id === selected)!
  function valueFor(id: string) {
    const value = context?.facts.find(item => item.concept === id)?.value
    if (value == null) return context ? 'Not available' : '…'
    if (id === 'customer' && typeof value === 'object') return String((value as {name?: string}).name || detail.customer_id)
    if (typeof value === 'number') return id === 'account_priority_score' ? `${(value * 100).toFixed(1)}%` : value.toLocaleString('en-SG', {maximumFractionDigits: 2})
    return String(value)
  }
  return <div className="rounded-xl border border-surface-3 bg-white p-5" aria-label="Business meaning explorer">
    <div className="mb-4 flex flex-wrap items-end justify-between gap-2"><div><h3 className="text-base font-bold">What the data means</h3><p className="mt-1 text-ink-muted">Select a concept to see its meaning, value and source.</p></div><span className="text-ink-muted">{detail.account_id}</span></div>
    {failed ? <p role="status" className="text-ink-muted">Business definitions are unavailable. Account records remain below.</p> : <>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">{concepts.map(item => <button key={item.id} type="button" aria-pressed={selected === item.id} onClick={() => setSelected(item.id)} className={`rounded-lg border p-4 text-left transition-shadow focus-visible:outline-accent ${item.tone} ${selected === item.id ? 'ring-2 ring-accent ring-offset-2' : 'hover:shadow-md'}`}>
        <span className="text-[10px] font-bold uppercase tracking-wider">{item.kind}</span>
        <h4 className="mt-2 font-semibold">{item.title}</h4><p className="mt-2 break-words text-lg font-bold tabular-nums">{valueFor(item.id)}</p><p className="mt-2 text-xs">{item.question}</p>
      </button>)}</div>
      <div className="mt-5 grid gap-5 rounded-lg bg-surface-2 p-4 lg:grid-cols-2" aria-live="polite">
        <div><p className="text-[10px] font-bold uppercase tracking-wider text-ink-muted">Meaning</p><h4 className="mt-1 text-sm font-bold">{fact?.label || concept.title}</h4><p className="mt-2 leading-5">{fact?.definition || 'Loading the semantic definition…'}</p>
          {selected === 'kyc_declaration' && <p className="mt-2 text-ink-muted">A recorded expectation, separate from observed transactions and document verification.</p>}
          {selected === 'observed_outbound_flow_30d' && <div className="mt-3 rounded border border-teal-200 bg-white p-3 font-medium">Outbound transaction amounts → sum over 30 days</div>}
          {selected === 'customer' && <p className="mt-2 text-ink-muted">The customer owns accounts; each alert identifies one monitored account.</p>}
        </div>
        <dl className="space-y-3"><div><dt className="text-ink-muted">Source</dt><dd className="mt-1 break-words font-medium">{fact?.source_ref || 'Not available'}</dd></div><div><dt className="text-ink-muted">Applies to</dt><dd className="mt-1">{selected === 'account_priority_score' ? context?.scope.selected_account_id : selected === 'observed_outbound_flow_30d' ? context?.scope.account_ids?.join(', ') : detail.customer_id}</dd></div>
          {selected === 'observed_outbound_flow_30d' && <div><dt className="text-ink-muted">Time window</dt><dd className="mt-1">{contextDate(context?.scope.window_start_at)} → {contextDate(context?.scope.data_cutoff_at)}</dd></div>}
          {selected === 'customer' && fact?.value && typeof fact.value === 'object' ? <div className="flex flex-wrap gap-2">{Object.entries(fact.value).filter(([key]) => ['industry', 'risk_rating'].includes(key)).map(([key,value]) => <span key={key} className="rounded bg-white px-2 py-1">{businessLabel(key)}: {String(value ?? 'Not recorded')}</span>)}</div> : null}
        </dl>
      </div>
    </>}
  </div>
}
