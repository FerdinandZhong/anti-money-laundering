import { useEffect, useState } from 'react'
import { controlSourceUrl, getControlAssessment } from '../api'
import type { ControlAssessment } from '../api'
import { businessLabel, contextDate, presentationText } from './semanticPresentation'

export function KycControls({ alertId, onAssessment }: { alertId: string; onAssessment?: (value: ControlAssessment) => void }) {
  const [assessment, setAssessment] = useState<ControlAssessment | null>(null)
  useEffect(() => { if (assessment) onAssessment?.(assessment) }, [assessment, onAssessment])
  useEffect(() => {
    let active = true
    setAssessment(null)
    getControlAssessment(alertId).then(value => { if (active) setAssessment(value) })
      .catch(() => { if (active) setAssessment({ available: false, reason: 'KYC information unavailable' }) })
    return () => { active = false }
  }, [alertId])
  if (!assessment) return <p className="text-xs text-ink-muted">Loading KYC information…</p>
  if (!assessment.available) return <p className="text-xs text-ink-muted">{presentationText(assessment.reason || 'KYC information unavailable')}</p>
  return <section className="space-y-3 rounded border border-surface-3 bg-white p-4 text-xs">
    <h3 className="text-base font-bold">KYC</h3>
    <p className="text-ink-muted">{assessment.booking_context?.booking_jurisdiction} · {businessLabel(assessment.booking_context?.product || '')} · {assessment.account_id} · {contextDate(assessment.as_of)}</p>
    {assessment.controls?.filter(control => !control.calculation).map(control => <article key={control.control_id} className="rounded border border-surface-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><strong>{businessLabel(control.concept)}</strong><span className={`rounded px-2 py-1 font-semibold ${control.outcome === 'SATISFIED' ? 'bg-green-50 text-green-800' : 'bg-amber-50 text-amber-800'}`}>{control.outcome.replaceAll('_', ' ')}</span></div>
      <p className="mt-2 text-ink-muted">{presentationText(control.reason)}</p>
      {!!control.missing_sources?.length && <p className="mt-2 text-amber-800">Missing required sources: {control.missing_sources.join(', ')}</p>}
      {control.missing_evidence?.map(item => <p key={item.assertion_id} className="mt-1 text-amber-800">{item.assertion_id}: {item.reason}</p>)}
      <div className="mt-3 grid gap-3 lg:grid-cols-2">{control.evidence.map(item => <div key={item.assertion_id} className="rounded bg-surface-2 p-3">
        <p className="text-ink-muted">{businessLabel(item.source)} · {item.field}</p><p className="mt-1 text-sm font-semibold">{item.value}</p>
        <a className="mt-2 inline-block text-accent underline" href={controlSourceUrl(alertId,item.assertion_id,assessment.release_id!,item.page)} target="_blank" rel="noreferrer">Open document · page {item.page}</a>
        <p className="mt-1 text-ink-muted">Received {contextDate(item.received_at)}</p>

      </div>)}</div>
    </article>)}
  </section>
}
