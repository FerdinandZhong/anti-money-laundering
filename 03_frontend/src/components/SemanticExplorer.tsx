import { useEffect, useRef, useState } from 'react'
import { getKnowledgeLibrary, getCaseSemanticContext, getSemanticIntents, querySemanticFacts } from '../api'
import type { CaseDetail, ControlAssessment, KnowledgeLibrary, SemanticContext, SemanticIntent } from '../api'
import { presentationText } from './semanticPresentation'
import { SemanticMeaning } from './SemanticMeaning'
import { SemanticContracts } from './SemanticContracts'
import { KycControls } from './KycControls'
import { ContextLineage, LiveContext, RegulationContext } from './SemanticSections'

const label = (value: string) => value.replaceAll('_', ' ')
const presets = [
  { title: 'Compare KYC with activity', intent: 'kyc_review', terms: 'expected turnover, observed outflow' },
  { title: 'Explain the priority score', intent: 'score_explanation', terms: 'risk score, model signal, sustained pattern' },
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

export function SemanticExplorer({ customerId, alertId, detail }: { customerId: string; alertId: string; detail: CaseDetail }) {
  const [library, setLibrary] = useState<KnowledgeLibrary | null>(null)
  const [assessment, setAssessment] = useState<ControlAssessment | null>(null)
  const [intents, setIntents] = useState<Record<string, SemanticIntent>>({})
  const [intent, setIntent] = useState('kyc_review')
  const [terms, setTerms] = useState(presets[0].terms)
  const [context, setContext] = useState<SemanticContext | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [discoveryError, setDiscoveryError] = useState(false)
  const request = useRef(0)

  useEffect(() => {
    let cancelled = false
    getSemanticIntents().then(available => {
      if (!cancelled) setIntents(available)
    }).catch(() => { if (!cancelled) setDiscoveryError(true) })
    return () => { cancelled = true; request.current += 1 }
  }, [])

  useEffect(() => {
    let active = true
    setLibrary(null)
    getKnowledgeLibrary(alertId).then(value => { if (active) setLibrary(value) })
      .catch(() => { if (active) setLibrary({available: false, release_id: null, documents: []}) })
    return () => { active = false }
  }, [alertId])

  const documentStatus = !library ? 'Checking supporting documents…'
    : !library.available ? 'Supporting documents: availability could not be checked.'
    : !library.documents.length ? 'Supporting documents: unavailable for this account.'
    : `Document library: ${library.documents.length} versions linked to this account. Profile values below are not document-verified.`

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
    <nav aria-label="Semantic sections" className="flex flex-wrap gap-2 rounded-lg border border-surface-3 bg-white p-3">{['Context','Lineage','Query','Original Ossie files'].map((name,index) => <a key={name} href={`#semantic-section-${index+1}`} className="rounded-md px-4 py-2 font-semibold text-ink hover:bg-surface-2"><span className="mr-2 text-accent">0{index+1}</span>{name}</a>)}</nav>
    <section id="semantic-section-1" className="space-y-4 scroll-mt-4">
      <div className="border-b border-surface-3 pb-3"><p className="font-semibold text-accent">01 / CONTEXT</p><h2 className="mt-1 text-xl font-bold">Evidence, obligations & account activity</h2><p className="mt-2 text-ink-muted">Understand the documents, regulations and activity linked to this account.</p></div>
      <SemanticMeaning detail={detail} />
      <p className="text-ink-muted">{documentStatus}</p>
      <div id="semantic-kyc"><KycControls alertId={alertId} onAssessment={setAssessment} /></div>
      <RegulationContext />
      <LiveContext detail={detail} assessment={assessment} />
    </section>
    <section id="semantic-section-2" className="space-y-4 rounded-lg border border-surface-3 bg-white p-5 scroll-mt-4">
      <div><p className="font-semibold text-accent">02 / LINEAGE</p><h2 className="mt-1 text-xl font-bold">How the sections connect</h2><p className="mt-2 text-ink-muted">Trace source fields through shared concepts to clause references and control outcomes.</p></div>
      <ContextLineage assessment={assessment} detail={detail} />
    </section>
    <section id="semantic-section-3" className="space-y-4 scroll-mt-4">
    <div className="border-b border-surface-3 pb-3"><p className="font-semibold text-accent">03 / QUERY</p><h2 className="mt-1 text-xl font-bold">Explore the semantic model</h2></div>
    <section className="rounded-lg border border-surface-3 bg-white p-5 shadow-soft">
      <h3 className="text-base font-bold">Look up account data</h3>
      <p className="text-ink-muted mt-2 leading-5">Choose a topic and enter business terms to find related account facts. Values come from stored customer, transaction and alert records.</p>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mt-4">
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
      {intents[intent] && <p className="text-ink-muted mt-3">{presentationText(intents[intent].description)}</p>}
      {discoveryError && <p role="alert" className="mt-3 text-amber-700">Contract discovery is unavailable. Preset queries can still be tried.</p>}
    </section>

    <div aria-live="polite">{busy ? 'Retrieving scoped facts…' : error || (!context ? 'Choose a query above to inspect its result.' : '')}</div>
    {context && <>
      <section className="rounded-lg border border-surface-3 bg-white p-4">
        <div className="flex flex-wrap justify-between gap-2"><h4 className="font-bold">Resolved context · {label(context.intent)}</h4></div>
        <p className="mt-2 text-ink-muted">{documentStatus}</p>
        <p className="mt-2">Selected alert account: {context.scope.selected_account_id ?? 'Not available'}</p>
        <p className="mt-1">Accounts included in observed flow: {context.scope.account_ids?.join(', ') || 'Not available'}</p>
        <p className="mt-1">Flow window (UTC): {context.scope.window_start_at ?? 'Unknown'} to {context.scope.data_cutoff_at ?? 'Unknown'}</p>
        {context.requested_concepts && <p className="mt-2 text-ink-muted">Resolved terms → {context.requested_concepts.join(', ') || 'None'}</p>}
        {!!context.unavailable_concepts?.length && <p className="mt-3 border-l-2 border-accent pl-3">Not returned: <strong>{context.unavailable_concepts.join(', ')}</strong>. These terms are unknown, outside this intent, or have no available fact. A priority score is deliberately outside KYC review.</p>}
      </section>
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        {context.facts.map(fact => <section key={fact.id} className="rounded-lg border border-surface-3 bg-white p-4 shadow-soft">
          <h4 className="font-bold">{fact.label || label(fact.concept)}</h4>
          <p className="text-ink-muted leading-5 mt-1">{presentationText(fact.definition || 'Definition not supplied by this backend version.')}</p>
          <div className="mt-3"><FactValue value={fact.value} concept={fact.concept} /></div>
          <p className="mt-3 pt-2 border-t border-surface-3 text-2xs text-ink-muted break-all">Source: {fact.source_ref}</p>
        </section>)}
      </div>
      <details className="rounded-lg border border-surface-3 p-4">
        <summary className="cursor-pointer font-semibold">How to interpret these results</summary>
        {context.allowed_conclusions?.map(item => <p key={item} className="mt-2">{presentationText(item)}</p>)}
        {context.claim_limitations.map(item => <p key={item} className="mt-2 text-ink-muted">{presentationText(item)}</p>)}
      </details>
    </>}
    </section>
    <section id="semantic-section-4" className="space-y-4 scroll-mt-4"><div className="border-b border-surface-3 pb-3"><p className="font-semibold text-accent">04 / ORIGINAL OSSIE FILES</p><h2 className="mt-1 text-xl font-bold">Source model & contracts</h2></div><SemanticContracts /></section>
  </div>
}
