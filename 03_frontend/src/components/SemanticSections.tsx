import { useEffect, useState } from 'react'
import { getRegulatoryMeanings } from '../api'
import type { RegulatoryMeaning } from '../api'
import type { CaseDetail, ControlAssessment } from '../api'
import { businessLabel, contextDate, presentationText } from './semanticPresentation'

export function RegulationContext() {
  const [requirements, setRequirements] = useState<RegulatoryMeaning[]>([])
  const [region, setRegion] = useState('ALL')
  const [failed, setFailed] = useState(false)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    let active = true
    getRegulatoryMeanings().then(data => { if (active) setRequirements(data.requirements) })
      .catch(() => { if (active) setFailed(true) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])
  return <section id="semantic-regulation" className="rounded-lg border border-surface-3 bg-white p-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="text-base font-bold">Regulation</h3><p className="mt-2 text-ink-muted">Understand the terms, requirements and their connection to business data.</p></div>
      <label className="text-ink-muted">Browse jurisdiction<select aria-label="Regulation jurisdiction" value={region} onChange={event => setRegion(event.target.value)} className="ml-2 rounded border border-surface-3 bg-white p-2 text-ink"><option value="ALL">All</option><option value="SG">Singapore</option><option value="HK">Hong Kong</option></select></label>
    </div>
    <p className="mt-3 text-ink-muted">Applicability depends on booking jurisdiction, institution type and the conditions below. Document availability does not determine which requirements apply.</p>
    {loading && <p className="mt-3">Loading regulatory meanings…</p>}
    {failed && <p role="status" className="mt-3">Regulatory meanings are unavailable. Reload to try again.</p>}
    <div className="mt-4 grid gap-4 lg:grid-cols-2">{requirements.filter(item => region === 'ALL' || item.jurisdiction === region).map(item => <article key={item.id} className="rounded-lg border border-surface-3 bg-surface-2 p-4">
      <div className="flex items-center justify-between gap-3"><h4 className="text-sm font-bold">{item.term}</h4><span className="rounded border border-surface-3 bg-white px-2 py-1">{item.jurisdiction}</span></div>
      <p className="mt-2 leading-5">{item.meaning}</p>
      <dl className="mt-4 space-y-3"><div><dt className="font-semibold">What is required</dt><dd className="mt-1 leading-5 text-ink-muted">{item.requirement}</dd></div><div><dt className="font-semibold">When it applies</dt><dd className="mt-1 leading-5 text-ink-muted">{item.applicability}</dd></div></dl>
      <div className="mt-4 border-t border-surface-3 pt-3"><p className="font-semibold">Related business concepts</p><div className="mt-2 flex flex-wrap gap-2">{item.business_concepts.map(concept => <span key={concept} className="rounded bg-white px-2 py-1">{businessLabel(concept)}</span>)}</div></div>
      <details className="mt-3"><summary className="cursor-pointer text-accent">Fields and evidence types</summary><p className="mt-2 break-words">{item.fields.join(' · ')}</p><p className="mt-2 text-ink-muted">Evidence types: {item.evidence_types.join(', ')}</p><p className="mt-2 text-ink-muted">{item.distinction}</p><p className="mt-2 text-ink-muted">Mapping: related concepts, not automatic legal equivalence.</p></details>
      <a href={item.source_url} target="_blank" rel="noreferrer" className="mt-4 inline-block text-accent underline">{item.source_id} §{item.clause} ↗</a><p className="mt-1 text-ink-muted">{item.edition}</p>
    </article>)}</div>
  </section>
}

export function LiveContext({ detail, assessment }: { detail: CaseDetail; assessment: ControlAssessment | null }) {
  const screening = detail.analysis?.match(/\[SCREENING\]\s*([\s\S]*?)(?=\n\[[A-Z_]+\]|\n\n|$)/)?.[1]?.trim()
  const values = [
    ['Expected monthly turnover', detail.expected_monthly_turnover?.toLocaleString('en-SG')],
    ['Observed outflow · 30 days', detail.observed_outflow_30d?.toLocaleString('en-SG')],
    ['Account priority', `${(detail.risk_score * 100).toFixed(1)}%`],
    ['KYC risk rating', detail.customer_kyc_rating],
  ]
  return <section id="semantic-live" className="rounded-lg border border-surface-3 bg-white p-5">
    <h3 className="text-base font-bold">Live data & screening</h3>
    <p className="mt-2 text-ink-muted">Account {detail.account_id} · data cutoff {contextDate(detail.data_cutoff_at)}</p>
    <div className="mt-4 grid grid-cols-2 gap-3 xl:grid-cols-4">{values.map(([name,value]) => <div key={name} className="rounded-lg bg-surface-2 p-4"><p className="text-ink-muted">{name}</p><p className="mt-2 text-lg font-bold">{value ?? 'Not available'}</p></div>)}</div>
    <div className="mt-4 grid gap-4 lg:grid-cols-2">
      <article className="rounded-lg border border-surface-3 p-4"><h4 className="font-semibold">Recorded alert signals</h4><div className="mt-3 flex flex-wrap gap-2">{(detail.reason_codes || detail.triggered_rules || []).map(reason => <span key={reason} className="rounded bg-surface-2 px-2 py-1">{businessLabel(reason)}</span>)}</div></article>
      <article className="rounded-lg border border-surface-3 p-4"><h4 className="font-semibold">Screening findings</h4><p className="mt-2 whitespace-pre-wrap leading-5 text-ink-muted">{screening ? presentationText(screening) : 'No recorded screening findings for this case. Run the investigation to populate this section.'}</p>{screening && <p className="mt-2 text-ink-muted">Profile-based investigation findings · {contextDate(detail.analyzed_at || undefined)}</p>}</article>
    </div>
    <div className="mt-4 grid gap-3 lg:grid-cols-2">{assessment?.controls?.filter(control => control.calculation).map(control => <article key={control.control_id} className="rounded-lg border border-surface-3 p-4">
      <div className="flex flex-wrap justify-between gap-2"><h4 className="font-semibold">{businessLabel(control.concept)}</h4><span className={`rounded px-2 py-1 ${control.outcome === 'SATISFIED' ? 'bg-green-50 text-green-800' : 'bg-amber-50 text-amber-800'}`}>{businessLabel(control.outcome)}</span></div>
      <p className="mt-2 text-ink-muted">Source: account control ledger</p><p className="mt-2 text-ink-muted">{presentationText(control.reason)}</p>
    </article>)}</div>
  </section>
}

export function ContextLineage({ assessment, detail }: { assessment: ControlAssessment | null; detail: CaseDetail }) {
  return <div className="space-y-4">
    <div className="rounded-xl border border-surface-3 bg-surface-2 p-5">
      <h3 className="font-bold">The account in context</h3>
      <div className="mt-4 grid items-center gap-3 md:grid-cols-5">
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-4"><p className="text-blue-900 font-semibold">Customer</p><p className="mt-2 break-words">{detail.customer_name}</p></div>
        <p className="text-center text-ink-muted">owns →</p>
        <div className="rounded-lg border border-violet-200 bg-violet-50 p-4"><p className="text-violet-900 font-semibold">Account</p><p className="mt-2 break-words">{detail.account_id}</p></div>
        <p className="text-center text-ink-muted">monitored by →</p>
        <div className="rounded-lg border border-orange-200 bg-orange-50 p-4"><p className="text-orange-900 font-semibold">Alert</p><p className="mt-2">{(detail.risk_score * 100).toFixed(1)}% review priority</p></div>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <p className="rounded-lg bg-white p-3"><strong>Profile</strong><br /><span className="text-ink-muted">Describes the customer and expected activity.</span></p>
        <p className="rounded-lg bg-white p-3"><strong>Transactions</strong><br /><span className="text-ink-muted">Record activity used to calculate observed flow.</span></p>
        <p className="rounded-lg bg-white p-3"><strong>Priority score</strong><br /><span className="text-ink-muted">Ranks this account for investigation.</span></p>
      </div>
    </div>
    <div className="grid gap-3 md:grid-cols-3">{[
      ['KYC evidence', 'Document fields → business concepts', '#semantic-kyc'],
      ['Regulation', 'Clause references → related concepts', '#semantic-regulation'],
      ['Live data & screening', 'Account records → metrics and findings', '#semantic-live'],
    ].map(([title,description,href]) => <a key={title} href={href} className="rounded-lg border border-surface-3 bg-surface-2 p-4 hover:border-accent"><strong>{title}</strong><p className="mt-2 text-ink-muted">{description}</p></a>)}</div>
    <div className="rounded-lg bg-surface-2 p-4 text-center"><strong>Connected by account, date and business concept</strong></div>
    {!!assessment?.controls?.length && <div className="overflow-x-auto"><table className="w-full text-left"><thead className="border-b border-surface-3 text-ink-muted"><tr>{['Source','Business concept','Related clause','Control result'].map(title => <th key={title} className="p-3 font-medium">{title}</th>)}</tr></thead><tbody>{assessment?.controls?.map(control => <tr key={control.control_id} className="border-b border-surface-3 align-top"><td className="p-3">{control.evidence.length ? control.evidence.map(item => `${businessLabel(item.source)} · ${item.field}`).join(' / ') : control.source_tables?.map(businessLabel).join(', ') || 'Evidence pending'}</td><td className="p-3 font-medium">{businessLabel(control.concept)}</td><td className="p-3">{assessment.regulatory_linkage?.candidates?.filter(link => link.concepts.includes(control.concept)).map(link => <a key={link.clause} href={link.source_url} target="_blank" rel="noreferrer" className="block text-accent underline">{link.source_id} §{link.clause}</a>)}</td><td className="p-3">{businessLabel(control.outcome)}</td></tr>)}</tbody></table></div>}
  </div>
}
