import { useRef, useState } from 'react'
import { presentationText } from './semanticPresentation'
import { getSemanticContracts } from '../api'
import type { SemanticContractSource } from '../api'

export function SemanticContracts() {
  const [contracts, setContracts] = useState<SemanticContractSource[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)
  const pending = useRef(false)

  async function load() {
    if (pending.current) return
    pending.current = true
    setLoading(true); setError(false)
    try { setContracts(await getSemanticContracts()) }
    catch { setError(true) }
    finally { pending.current = false; setLoading(false) }
  }

  return <details className="rounded-lg border border-surface-3 bg-white p-4" onToggle={event => {
    if (event.currentTarget.open && !contracts && !error) void load()
  }}>
    <summary className="cursor-pointer font-bold">Browse Ossie-style model and AML extensions (YAML)</summary>
    <p className="mt-3 text-ink-muted leading-5">Inspect the original YAML for the Ossie-style semantic model and AML extensions.</p>
    <div aria-live="polite">{loading && <p className="mt-3">Loading source contracts…</p>}
      {error && <p className="mt-3 text-amber-700">Source contracts unavailable. <button className="underline" onClick={() => void load()}>Retry</button></p>}
    </div>
    {contracts?.map(contract => <details key={contract.filename} className="mt-3 rounded-md border border-surface-3 p-3">
      <summary className="cursor-pointer font-semibold">{contract.title}</summary>
      <p className="mt-2 text-ink-muted">{presentationText(contract.description)}</p>
      <p className="mt-2 font-mono text-2xs break-all">semantic/{contract.filename}</p>
      <pre className="mt-3 max-h-[32rem] overflow-auto rounded-md bg-surface-2 p-4 text-2xs leading-5" tabIndex={0} aria-label={contract.title + ' YAML'}><code>{contract.content}</code></pre>
    </details>)}
  </details>
}
