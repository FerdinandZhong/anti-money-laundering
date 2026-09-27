import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { getKnowledgeLibrary, searchKnowledge, knowledgeAssetUrl } from '../api'
import type { KycDocument, KnowledgeDocument, KnowledgeLibrary, KnowledgeSearch } from '../api'

export function KycKnowledge({ alertId, legacy }: { alertId: string; legacy: KycDocument[] }) {
  const [library, setLibrary] = useState<KnowledgeLibrary | null>(null)
  const [result, setResult] = useState<KnowledgeSearch | null>(null)
  const [selected, setSelected] = useState<KnowledgeDocument | null>(null)
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const sequence = useRef(0)
  useEffect(() => {
    let active = true
    getKnowledgeLibrary(alertId).then(data => {
      if (active) { setLibrary(data); setSelected(data.documents[0] ?? null) }
    }).catch(() => { if (active) setError('Document library unavailable. Existing onboarding records are shown below.') })
    return () => { active = false; sequence.current++ }
  }, [alertId])

  async function search(event: FormEvent) {
    event.preventDefault()
    if (!library?.release_id || !query.trim()) return
    const request = ++sequence.current
    setBusy(true); setError('')
    try {
      const data = await searchKnowledge(alertId, library.release_id, query.trim())
      if (request === sequence.current) { setResult(data); setSelected(data.hits[0] ?? null) }
    } catch {
      if (request === sequence.current) setError('Search unavailable. You can still browse the document library.')
    } finally { if (request === sequence.current) setBusy(false) }
  }

  const showPlainRecords = !!library && (!library.available || library.documents.length === 0) || (!library && !!error)
  const documents = result ? result.hits : library?.documents ?? []
  return <div className="space-y-4">
    {!showPlainRecords && <div className="rounded-lg border border-surface-3 bg-white p-4">
      <h3 className="text-sm font-bold text-ink">KYC evidence library</h3>
      <p className="mt-1 text-xs text-ink-muted">Search English or Chinese document text and inspect the original page. OCR and declarations require verification.</p>
      <form className="mt-3 flex gap-2" onSubmit={search}>
        <input aria-label="Search KYC evidence" value={query} maxLength={1000} onChange={e => setQuery(e.target.value)}
          placeholder="Beneficial owner / 受益所有人 / registration ID" className="min-w-0 flex-1 rounded border border-surface-3 px-3 py-2 text-sm" />
        <button disabled={busy || !library?.available || !query.trim()} className="rounded bg-accent px-4 py-2 text-sm text-white disabled:opacity-40">{busy ? 'Searching…' : 'Search'}</button>
        {result && <button type="button" onClick={() => { sequence.current++; setBusy(false); setResult(null); setSelected(library?.documents[0] ?? null) }} className="px-2 text-xs text-ink-muted">Browse all</button>}
      </form>
      <p className="mt-2 text-xs text-ink-muted">{result ? `${result.mode ?? 'Unavailable'} search · as of ${result.as_of ?? 'unknown cutoff'}` : library?.note ?? 'Loading documents…'}</p>
      {result?.note && <p className="mt-1 text-xs text-ink-muted">{result.note}</p>}
      {error && <p role="alert" className="mt-2 text-xs text-red-700">{error}</p>}
    </div>}
    {!showPlainRecords && library?.available && <div className="grid gap-4 xl:grid-cols-3">
      <div className="space-y-2 max-h-[700px] overflow-y-auto">
        {documents.length === 0 && <p className="p-4 text-sm text-ink-muted">No matching documents in this alert’s scope and time window.</p>}
        {documents.map((doc, index) => <button key={doc.chunk_id ?? doc.version_id + index} onClick={() => setSelected(doc)}
          className={`w-full rounded-lg border p-3 text-left ${selected === doc ? 'border-accent bg-orange-50' : 'border-surface-3 bg-white'}`}>
          <p className="text-sm font-semibold text-ink">{doc.title}</p>
          <p className="mt-1 text-xs text-ink-muted">{doc.language} · {doc.page ? `Page ${doc.page}` : `${doc.page_count} page(s)`}</p>
          {doc.illustrative && <p className="mt-1 text-xs font-semibold text-amber-800">Illustrative fixture — not customer verification</p>}
          {doc.text && <p className="mt-2 line-clamp-4 whitespace-pre-line text-xs text-ink-muted">{doc.text}</p>}
        </button>)}
      </div>
      <div className="xl:col-span-2 rounded-lg border border-surface-3 bg-white p-4">
        {selected && library.release_id ? <>
          <h4 className="text-sm font-bold">{selected.title}</h4>
          <p className="mt-1 text-xs text-ink-muted">{selected.provenance}</p>
          <p className="mt-2 break-all text-xs text-ink-muted">Version: {selected.version_id} · Received: {selected.received_at}</p>
          <a className="my-3 inline-block text-xs font-semibold text-accent" target="_blank" rel="noreferrer"
            href={knowledgeAssetUrl(alertId, library.release_id, selected.version_id, selected.page)}>Open original document ↗</a>
          <iframe title={`KYC document: ${selected.title}`} className="h-[560px] w-full rounded border border-surface-3"
            src={knowledgeAssetUrl(alertId, library.release_id, selected.version_id, selected.page)} />
        </> : <p className="text-sm text-ink-muted">Select a document to inspect its evidence.</p>}
      </div>
    </div>}
    {showPlainRecords && legacy.length === 0 && <p className="text-sm text-ink-muted">No onboarding records available for this account.</p>}
    {showPlainRecords && legacy.map(doc => <section key={doc.name} className="rounded-lg border border-surface-3 bg-white p-5">
      <h3 className="text-sm font-bold">{doc.name}</h3><p className="text-xs text-ink-muted">{doc.source}</p>
      <p className="mt-3 whitespace-pre-line text-xs leading-5 text-ink-muted">{doc.content}</p>
    </section>)}
  </div>
}
