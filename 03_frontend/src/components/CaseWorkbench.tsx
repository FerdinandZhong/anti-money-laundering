import React, { useEffect, useState } from 'react'
import { FileSearch, ArrowUpRight, ArrowDownLeft } from 'lucide-react'
import type { CaseDetail } from '../api'
import { getAlertDetail, setTransactionLabels } from '../api'
import { Badge, RiskBadge } from './Badge'
import { AgentPanel } from './AgentPanel'

interface Props {
  alertId: string | null
  onDisposed?: () => void
}

const fmt = (n: number) =>
  new Intl.NumberFormat('en-SG', { style: 'currency', currency: 'SGD', maximumFractionDigits: 0 }).format(n)

const fmtDate = (s: string) =>
  new Date(s).toLocaleString('en-SG', { dateStyle: 'short', timeStyle: 'short' })

const RISK_SCORE_COLOR = (s: number) =>
  s >= 0.8 ? 'text-red-600' : s >= 0.6 ? 'text-orange-500' : s >= 0.4 ? 'text-amber-500' : 'text-green-600'

export const CaseWorkbench: React.FC<Props> = ({ alertId, onDisposed }) => {
  const [detail, setDetail] = useState<CaseDetail | null>(null)
  const [error, setError] = useState(false)
  // analyst per-tx labels, keyed by transaction_id: 1 suspicious, 0 clean, null unset
  const [labels, setLabels] = useState<Record<string, number | null>>({})

  useEffect(() => {
    if (!alertId) return
    setDetail(null)
    setError(false)
    getAlertDetail(alertId)
      .then(d => { if (d?.case_id) setDetail(d); else setError(true) })
      .catch(() => setError(true))
  }, [alertId])

  // seed local label state from the loaded detail
  useEffect(() => {
    if (!detail) return
    const seed: Record<string, number | null> = {}
    for (const tx of detail.transactions ?? []) {
      if (tx.transaction_id) seed[tx.transaction_id] = tx.label ?? null
    }
    setLabels(seed)
  }, [detail])

  // auto-save a single row change (optimistic; ignore transient network errors)
  const saveLabel = (txId: string, next: number | null) => {
    setLabels(prev => ({ ...prev, [txId]: next }))
    if (detail) setTransactionLabels(detail.case_id, [{ transaction_id: txId, label: next }]).catch(() => {})
  }

  const bulkLabel = (val: number) => {
    if (!detail) return
    const shown = (detail.transactions ?? []).filter(t => t.transaction_id) as { transaction_id: string }[]
    setLabels(prev => {
      const next = { ...prev }
      shown.forEach(t => { next[t.transaction_id] = val })
      return next
    })
    setTransactionLabels(detail.case_id, shown.map(t => ({ transaction_id: t.transaction_id, label: val }))).catch(() => {})
  }

  if (!alertId) return (
    <EmptyState message="Select an alert to open the case workbench" />
  )
  if (error) return (
    <EmptyState message="Couldn't load case detail" />
  )
  if (!detail) return (
    <EmptyState message="Loading case…" loading />
  )

  return (
    <div className="flex-1 flex flex-col bg-surface-1 rounded-lg overflow-hidden shadow-soft min-w-0 min-h-0">
      {/* Customer header */}
      <div className="flex items-start justify-between px-6 py-4 border-b border-surface-3 shrink-0 bg-surface-2">
        <div>
          {/* Orange accent line — matches reference */}
          <div className="w-8 h-0.5 bg-accent mb-2.5" />
          <div className="flex items-center gap-2.5 mb-1">
            <h2 className="text-base font-bold text-ink">{detail.customer_name}</h2>
            <RiskBadge band={detail.risk_band} />
          </div>
          <p className="text-xs text-ink-muted font-mono">{detail.customer_id} · {detail.case_id}</p>
        </div>
        <div className="text-right shrink-0">
          <div className={`text-4xl font-black tabular-nums ${RISK_SCORE_COLOR(detail.risk_score)}`}>
            {(detail.risk_score * 100).toFixed(0)}
            <span className="text-lg font-semibold">%</span>
          </div>
          <div className="text-xs text-ink-muted mt-0.5">Account Risk Score</div>
        </div>
      </div>

      {/* Meta row */}
      <div className="grid grid-cols-5 gap-4 px-6 py-3 border-b border-surface-3 shrink-0 bg-surface-1">
        <MetaItem label="KYC Risk Rating">
          <Badge label={detail.customer_kyc_rating} small neutral />
        </MetaItem>
        <MetaItem label="Account Age">{detail.account_age_days} days</MetaItem>
        <MetaItem label="Monthly Turnover">{fmt(detail.expected_monthly_turnover)}</MetaItem>
        <div className="col-span-2">
          <p className="text-2xs text-ink-muted uppercase tracking-wider mb-1.5">Triggered Rules</p>
          <div className="flex gap-1.5 flex-wrap">
            {(detail.triggered_rules ?? []).map(r => (
              <Badge key={r} label={r} color="#f3f4f6" small />
            ))}
          </div>
        </div>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 min-h-0 overflow-y-auto px-6 py-5">
        {/* Section header */}
        <div className="mb-4 flex items-end justify-between">
          <div>
            <div className="w-8 h-0.5 bg-accent mb-2" />
            <h3 className="text-sm font-bold text-ink">Transaction Timeline</h3>
            <p className="text-xs text-ink-muted mt-0.5">
              Key transactions flagged for this alert — label suspicious rows to train the next model
            </p>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            <button
              onClick={() => bulkLabel(1)}
              className="text-2xs font-semibold px-2 py-1 rounded-lg border border-red-200 text-red-600 bg-red-50 hover:bg-red-100 transition-colors"
            >
              Mark all suspicious
            </button>
            <button
              onClick={() => bulkLabel(0)}
              className="text-2xs font-semibold px-2 py-1 rounded-lg border border-green-200 text-green-600 bg-green-50 hover:bg-green-100 transition-colors"
            >
              Mark all clean
            </button>
          </div>
        </div>

        <div className="rounded-lg border border-surface-3 overflow-hidden mb-6 shadow-soft">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="border-b border-surface-3 bg-surface-2">
                {['Time', 'Dir', 'Amount (SGD)', 'Channel', 'Counterparty', 'Country', 'Typology', 'Score', 'Label'].map(h => (
                  <th key={h} className="px-3 py-2.5 text-left text-ink-muted font-semibold whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[...(detail.transactions ?? [])].sort((a, b) => (b.is_suspicious ? 1 : 0) - (a.is_suspicious ? 1 : 0)).map((tx, i) => (
                <tr
                  key={i}
                  className={`border-b border-surface-3 last:border-0 transition-colors
                    ${tx.is_suspicious ? 'bg-red-50 hover:bg-red-100/50' : 'hover:bg-surface-2'}`}
                >
                  <td className="px-3 py-2.5 text-ink-muted font-mono">{fmtDate(tx.event_time)}</td>
                  <td className="px-3 py-2.5">
                    {tx.direction === 'OUT'
                      ? <ArrowUpRight className="w-4 h-4 text-red-500" />
                      : <ArrowDownLeft className="w-4 h-4 text-green-500" />}
                  </td>
                  <td className="px-3 py-2.5 text-ink font-semibold tabular-nums">{fmt(tx.amount)}</td>
                  <td className="px-3 py-2.5 text-ink-muted">{tx.channel}</td>
                  <td className="px-3 py-2.5 text-ink-muted">{tx.counterparty_name}</td>
                  <td className="px-3 py-2.5">
                    <span className="px-1.5 py-0.5 rounded-lg bg-surface-3 text-ink-muted font-mono text-2xs">
                      {tx.counterparty_country}
                    </span>
                  </td>
                  <td className="px-3 py-2.5">
                    {tx.typology
                      ? <Badge label={tx.typology} color="#fff7ed" small />
                      : <span className="text-ink-faint">—</span>}
                  </td>
                  <td className="px-3 py-2.5 tabular-nums font-semibold">
                    {tx.score != null
                      ? <span className={RISK_SCORE_COLOR(tx.score)}>{(tx.score * 100).toFixed(0)}%</span>
                      : <span className="text-ink-faint">—</span>}
                  </td>
                  <td className="px-3 py-2.5">
                    {tx.transaction_id
                      ? <LabelControl
                          value={labels[tx.transaction_id] ?? null}
                          onChange={next => saveLabel(tx.transaction_id!, next)}
                        />
                      : <span className="text-ink-faint">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <AgentPanel
          caseId={detail.case_id}
          savedAnalysis={detail.analysis ? { text: detail.analysis, at: detail.analyzed_at ?? '' } : undefined}
          onDisposed={onDisposed}
          closed={!!detail.disposition}
        />
      </div>
    </div>
  )
}

/** 3-state analyst label: Suspicious (1) / Clean (0) / unset. Clicking the
 *  active state toggles it back to unset. */
const LabelControl: React.FC<{ value: number | null; onChange: (next: number | null) => void }> = ({ value, onChange }) => {
  const set = (v: number) => onChange(value === v ? null : v)
  return (
    <div className="flex items-center gap-1">
      <button
        onClick={() => set(1)}
        title="Mark suspicious"
        className={`px-1.5 py-0.5 rounded-lg text-2xs font-bold border transition-colors ${
          value === 1
            ? 'bg-red-600 text-white border-red-600'
            : 'bg-white text-red-500 border-red-200 hover:bg-red-50'}`}
      >
        S
      </button>
      <button
        onClick={() => set(0)}
        title="Mark clean"
        className={`px-1.5 py-0.5 rounded-lg text-2xs font-bold border transition-colors ${
          value === 0
            ? 'bg-green-600 text-white border-green-600'
            : 'bg-white text-green-600 border-green-200 hover:bg-green-50'}`}
      >
        C
      </button>
    </div>
  )
}

const MetaItem: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div>
    <p className="text-2xs text-ink-muted uppercase tracking-wider mb-1.5">{label}</p>
    <div className="text-sm text-ink-muted">{children}</div>
  </div>
)

const EmptyState: React.FC<{ message: string; loading?: boolean }> = ({ message, loading }) => (
  <div className="flex-1 flex items-center justify-center bg-surface-1 rounded-lg shadow-soft">
    <div className="text-center">
      <FileSearch className={`w-10 h-10 mx-auto mb-3 ${loading ? 'text-accent/40 animate-pulse' : 'text-ink-faint'}`} />
      <p className="text-sm text-ink-muted">{message}</p>
    </div>
  </div>
)
