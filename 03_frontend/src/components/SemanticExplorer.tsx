import { useEffect, useRef, useState } from 'react'
import { getCaseSemanticContext, getSemanticIntents, getSemanticPaths, querySemanticFacts } from '../api'
import type { SemanticContext, SemanticIntent } from '../api'
import { SemanticContracts } from './SemanticContracts'

const label = (value: string) => value.replaceAll('_', ' ')
const presets = [
  { title: 'Compare KYC with activity', intent: 'kyc_review', terms: 'expected turnover, observed outflow' },
  { title: 'Explain the priority score', intent: 'score_explanation', terms: 'risk score, model signal, sustained pattern' },
  { title: 'Test the intent boundary', intent: 'kyc_review', terms: 'expected turnover, risk score' },
]

function FactValue({ value, concept }: { value: unknown; concept: string }) {
  if (value == null) return <span>Not available</span>
  if (typeof value === 'number') return <span className="text-lg font-bold tabular-nums">{
    concept === 'account_priority_score' ? `${(value * 100).toFixed(1)}% priority (not probability)` : value.toLocaleString('en-SG')
  }</span>
  if (typeof value !== 'object') return <span>{String(value)}</span>
  return <dl className="space-y-1">
    {Object.entries(value).map(([key, item]) => <div key={key} className="flex flex-wrap gap-x-2">
      <dt className="text-ink-muted capitalize">{label(key)}:</dt>
      <dd className="min-w-0 break-words">{item == null ? 'Not available' : typeof item === 'object'
        ? <details><summary className="cursor-pointer text-accent">View structured detail</summary><pre className="whitespace-pre-wrap break-all text-2xs">{JSON.stringify(item, null, 2)}</pre></details>
        : String(item)}</dd>
    </div>)}
  </dl>
}

export function SemanticExplorer({ customerId, alertId }: { customerId: string; alertId: string }) {
  const [intents, setIntents] = useState<Record<string, SemanticIntent>>({})
  const [paths, setPaths] = useState<Awaited<ReturnType<typeof getSemanticPaths>>>([])
  const [intent, setIntent] = useState('kyc_review')
  const [terms, setTerms] = useState(presets[0].terms)
  const [context, setContext] = useState<SemanticContext | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [discoveryError, setDiscoveryError] = useState(false)
  const request = useRef(0)

  useEffect(() => {
    let cancelled = false
    Promise.all([getSemanticIntents(), getSemanticPaths()]).then(([available, relationships]) => {
      if (!cancelled) { setIntents(available); setPaths(relationships) }
    }).catch(() => { if (!cancelled) setDiscoveryError(true) })
    return () => { cancelled = true; request.current += 1 }
  }, [])

  async function run(nextIntent = intent, nextTerms = terms, full = false) {
    const id = ++request.current
    setBusy(true); setError(''); setContext(null)
    try {
      const result = full
        ? await getCaseSemanticContext(customerId, nextIntent, alertId)
        : await querySemanticFacts(customerId, alertId, nextIntent, nextTerms.split(',').map(t => t.trim()).filter(Boolean))
      if (id === request.current) setContext(result)
    } catch {
      if (id === request.current) setError('Could not retrieve semantic context. Check backend availability and try again.')
    } finally {
      if (id === request.current) setBusy(false)
    }
  }

  function clearResult() { request.current += 1; setContext(null); setBusy(false); setError('') }

  return <div className="space-y-4 text-xs text-ink">
    <section className="rounded-lg border border-surface-3 bg-white p-5 shadow-soft">
      <h3 className="text-base font-bold">From business question to governed context</h3>
      <p className="text-ink-muted mt-2 leading-5">Choose an investigation purpose, resolve business terms, then inspect the facts an agent can retrieve. These are live API queries, not generated answers or historical worker inputs. No investigation or scoring is triggered.</p>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 mt-4">
        {presets.map((preset, index) => <button key={preset.title} onClick={() => {
          setIntent(preset.intent); setTerms(preset.terms); void run(preset.intent, preset.terms)
        }} className="text-left rounded-lg border border-surface-3 p-3 hover:border-accent focus-visible:outline-accent">
          <span className="text-accent font-bold">0{index + 1}</span>
          <p className="font-semibold mt-1">{preset.title}</p>
          <p className="text-ink-muted mt-1">{preset.terms}</p>
        </button>)}
      </div>
      <div className="flex flex-col lg:flex-row gap-3 mt-5 items-end">
        <label className="w-full lg:w-56">Investigation purpose
          <select value={intent} onChange={e => { setIntent(e.target.value); clearResult() }} className="block mt-1 w-full border border-surface-3 rounded-md p-2 bg-white">
            {Object.keys(intents).length ? Object.keys(intents).map(key => <option key={key} value={key}>{label(key)}</option>) : <option value={intent}>{label(intent)}</option>}
          </select>
        </label>
        <label className="flex-1 w-full">Business terms (comma-separated)
          <input value={terms} onChange={e => { setTerms(e.target.value); clearResult() }} className="block mt-1 w-full border border-surface-3 rounded-md p-2" />
        </label>
        <button disabled={busy || !terms.trim()} onClick={() => void run()} className="rounded-md bg-accent text-white px-4 py-2 disabled:opacity-50">Query facts</button>
        <button disabled={busy} onClick={() => void run(intent, terms, true)} className="rounded-md border border-surface-3 px-4 py-2 disabled:opacity-50">Full intent context</button>
      </div>
      {intents[intent] && <p className="text-ink-muted mt-3">{intents[intent].description}</p>}
      {discoveryError && <p role="alert" className="mt-3 text-amber-700">Contract discovery is unavailable. Preset queries can still be tried.</p>}
    </section>

    <section className="rounded-lg border border-surface-3 bg-surface-2 p-4">
      <h4 className="font-bold">Declared business relationships</h4>
      {paths.map((path, i) => <p key={i} className="mt-2 font-mono">{path[0]?.from}{path.map(step => ` → ${step.id} → ${step.to}`).join('')}</p>)}
      <p className="text-ink-muted mt-2">The contract describes how concepts relate. This is not a detected fund-flow network; use the Network tab for account links.</p>
    </section>

    <SemanticContracts />
    <div aria-live="polite">{busy ? 'Retrieving scoped facts…' : error || (!context ? 'Choose a demo query above to inspect its result.' : '')}</div>
    {context && <>
      <section className="rounded-lg border border-surface-3 bg-white p-4">
        <div className="flex flex-wrap justify-between gap-2"><h4 className="font-bold">Resolved context · {label(context.intent)}</h4><span className="text-ink-muted">Model {context.semantic_model_version} · Ontology {context.ontology_version}</span></div>
        <p className="mt-2">Selected alert account: {context.scope.selected_account_id ?? 'Not available'}</p>
        <p className="mt-1">Accounts included in observed flow: {context.scope.account_ids?.join(', ') || 'Not available'}</p>
        <p className="mt-1">Flow window (UTC): {context.scope.window_start_at ?? 'Unknown'} to {context.scope.data_cutoff_at ?? 'Unknown'}</p>
        {context.requested_concepts && <p className="mt-2 text-ink-muted">Resolved terms → {context.requested_concepts.join(', ') || 'None'}</p>}
        {!!context.unavailable_concepts?.length && <p className="mt-3 border-l-2 border-accent pl-3">Not returned: <strong>{context.unavailable_concepts.join(', ')}</strong>. These terms are unknown, outside this intent, or have no available fact. A priority score is deliberately outside KYC review.</p>}
      </section>
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        {context.facts.map(fact => <section key={fact.id} className="rounded-lg border border-surface-3 bg-white p-4 shadow-soft">
          <h4 className="font-bold">{fact.label || label(fact.concept)}</h4>
          <p className="text-ink-muted leading-5 mt-1">{fact.definition || 'Definition not supplied by this backend version.'}</p>
          <div className="mt-3"><FactValue value={fact.value} concept={fact.concept} /></div>
          <p className="mt-3 pt-2 border-t border-surface-3 text-2xs text-ink-muted break-all">Source: {fact.source_ref}</p>
        </section>)}
      </div>
      <section className="grid grid-cols-1 lg:grid-cols-2 gap-4 rounded-lg border border-surface-3 bg-white p-5">
        <div><h4 className="font-bold">Permitted interpretation</h4>{context.allowed_conclusions?.map(item => <p key={item} className="mt-2 leading-5">{item}</p>)}</div>
        <div><h4 className="font-bold">What the agent must not overclaim</h4>{context.claim_limitations.map(item => <p key={item} className="mt-2 border-l-2 border-accent pl-3 text-ink-muted leading-5">{item}</p>)}</div>
        <p className="lg:col-span-2 text-ink-muted">Fact selection is enforced by the resolver. Interpretation guidance is supplied to the agent, not a guarantee that every generated answer complies.</p>
      </section>
      <details className="rounded-lg border border-surface-3 bg-surface-2 p-4">
        <summary className="cursor-pointer font-semibold">Coverage and agent handoff ({context.evidence_refs.length} evidence references)</summary>
        {context.retrieval_notes?.map(note => <p key={note} className="mt-2 text-ink-muted leading-5">{note}</p>)}
        <p className="mt-2">Declared concepts without facts in this bundle: {context.unavailable_fact_concepts?.join(', ') || 'None reported'}</p>
        <p className="mt-2">The investigation workers and MCP tools use this resolver. Profile and screening request KYC review; pattern and network workers request their respective intents and also retrieve task-specific evidence.</p>
        <details className="mt-3"><summary className="cursor-pointer">Inspect returned JSON</summary><pre className="mt-2 whitespace-pre-wrap break-all text-2xs">{JSON.stringify(context, null, 2)}</pre></details>
      </details>
    </>}
  </div>
}
