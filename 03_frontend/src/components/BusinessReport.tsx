import { contextDate } from './semanticPresentation'

interface ReportParagraph { text: string; finding_ids: string[] }
export interface BusinessReportData {
  version: string
  mode: 'narrated' | 'source_summary'
  recommendation: string
  evidence_completeness?: { status: string; label: string }
  customer_name?: string | null
  as_of?: string | null
  sections: { key: string; title: string; paragraphs: ReportParagraph[] }[]
  open_questions: ReportParagraph[]
}

export function BusinessReport({ report, onShowEvidence }: { report: BusinessReportData; onShowEvidence: (ids: string[]) => void }) {
  return <article aria-label="Investigation report" className="rounded-xl border border-surface-3 bg-white p-6 space-y-5">
    <div>
      <p className="text-xs font-semibold text-ink-muted mb-2">INVESTIGATION REPORT</p>
      <h3 className="text-xl font-bold text-ink">{report.recommendation}</h3>
      {report.evidence_completeness && <p className="text-sm text-ink mt-2">Supporting information: {report.evidence_completeness.label}</p>}
      <p className="text-xs text-ink-muted mt-2">{report.customer_name ? `${report.customer_name} · ` : ''}Information reviewed as of {contextDate(report.as_of)}</p>
    </div>
    {report.sections.map(section => <section key={section.key} className="space-y-2">
      <h4 className="text-sm font-semibold text-ink">{section.title}</h4>
      {section.paragraphs.map((paragraph, i) => <div key={i}>
        <p className="text-sm text-ink leading-7">{paragraph.text}</p>
        {paragraph.finding_ids.length > 0 && <button onClick={() => onShowEvidence(paragraph.finding_ids)} className="text-xs text-accent hover:underline mt-1">View supporting findings</button>}
      </div>)}
    </section>)}
    {report.open_questions.length > 0 && <section className="rounded-lg bg-surface-2 p-4 space-y-2">
      <h4 className="text-sm font-semibold">Still to resolve</h4>
      <ul className="space-y-2 list-disc pl-4 text-sm text-ink-muted leading-6">{report.open_questions.map((item, i) => <li key={i}>{item.text}</li>)}</ul>
    </section>}
    <p className="text-xs text-ink-muted">{report.mode === 'narrated' ? 'Prepared with AI assistance for analyst review.' : 'Summary of the available findings for analyst review.'}</p>
  </article>
}
