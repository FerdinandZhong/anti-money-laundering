import { useState } from 'react'
import { api } from '../api'
import { businessLabel, contextDate, presentationText } from './semanticPresentation'

export interface InvestigationFinding {
  id: string
  concept: string
  observation: string
  status: string
  next_action?: string
  interpretation?: string
  meaning?: string
  distinction?: string
  applicability?: string
  clause?: string
  source_url?: string
  evidence_url: string
  scope: { account_id: string; cutoff: string | null }
  evidence_links?: { label: string; page?: number; excerpt: string; url: string }[]
}

function Finding({ item }: { item: InvestigationFinding }) {
  const [evidence, setEvidence] = useState<unknown>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const load = async () => {
    if (evidence) { setEvidence(null); return }
    setLoading(true); setError('')
    try {
      const response = await api.get(item.evidence_url.replace(/^\/api/, ''))
      setEvidence(response.data)
    } catch { setError('Retained evidence could not be loaded.') }
    finally { setLoading(false) }
  }
  return <article className="rounded-lg border border-surface-3 bg-surface-2 p-4 space-y-2 text-xs">
    <div className="flex justify-between gap-3"><strong>{businessLabel(item.concept)}</strong><span className="text-ink-muted">{businessLabel(item.status)}</span></div>
    <p>{presentationText(item.observation)}</p>
    {item.interpretation && <p><span className="font-semibold">AI interpretation: </span>{presentationText(item.interpretation)}</p>}
    {item.next_action && <p><span className="font-semibold">Next step: </span>{presentationText(item.next_action)}</p>}
    {(item.meaning || item.evidence_links?.length) ? <details className="pt-1">
      <summary className="cursor-pointer text-accent">Meaning and source evidence</summary>
      {item.meaning && <p className="mt-2">{item.meaning} {item.distinction}</p>}
      {item.source_url && /^https:\/\//.test(item.source_url) && <p className="mt-2"><a href={item.source_url} target="_blank" rel="noreferrer" className="text-accent underline">Source clause {item.clause}</a> · Applicability requires the stated conditions.</p>}
      {item.evidence_links?.map((link, i) => <div className="mt-2 border-l-2 border-surface-3 pl-3" key={i}>
        <p className="text-ink-muted whitespace-pre-wrap">{link.excerpt.slice(0, 700)}</p>
        <a href={link.url} target="_blank" rel="noreferrer" className="text-accent underline">{presentationText(link.label)} · page {link.page ?? 1}</a>
      </div>)}
    </details> : null}
    <p className="text-ink-faint">{item.scope.account_id} · {contextDate(item.scope.cutoff)}</p>
    <button type="button" className="text-accent underline" disabled={loading} onClick={load}>{loading ? 'Loading…' : evidence ? 'Hide retained inputs' : 'Inspect retained inputs'}</button>
    {error && <p role="alert">{error}</p>}
    {evidence != null && <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all text-2xs">{JSON.stringify(evidence, null, 2)}</pre>}
  </article>
}

export function InvestigationFindings({ findings }: { findings: InvestigationFinding[] }) {
  return <div className="space-y-3 mt-3">{findings.map(item => <Finding item={item} key={item.id} />)}</div>
}
