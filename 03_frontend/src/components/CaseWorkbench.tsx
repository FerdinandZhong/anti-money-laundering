import React, { useEffect, useState } from 'react'
import {
  AlertTriangle, ArrowDownLeft, ArrowUpRight, Check, ChevronDown, ChevronRight,
  Clock3, FileSearch, LayoutDashboard, List, Network, Save, Sparkles,
} from 'lucide-react'
import type { CaseDetail, Transaction } from '../api'
import { getAlertDetail, setTransactionLabels } from '../api'
import { Badge, RiskBadge } from './Badge'
import { AgentPanel } from './AgentPanel'
import { NetworkGraph } from './NetworkGraph'

interface Props {
  alertId: string | null
  onDisposed?: () => void
}

type WorkspaceTab = 'overview' | 'transactions' | 'network' | 'findings'
type SaveState = 'idle' | 'saving' | 'saved' | 'error'

const fmt = (n: number) =>
  new Intl.NumberFormat('en-SG', { style: 'currency', currency: 'SGD', maximumFractionDigits: 0 }).format(n)

const fmtDate = (s?: string | null) => s
  ? new Date(s).toLocaleString('en-SG', { dateStyle: 'medium', timeStyle: 'short' })
  : 'Not available'

const RISK_SCORE_COLOR = (s: number) =>
  s >= 0.8 ? 'text-red-600' : s >= 0.6 ? 'text-orange-500' : s >= 0.4 ? 'text-amber-500' : 'text-green-600'

const TABS: { key: WorkspaceTab; label: string; icon: React.ReactNode }[] = [
  { key: 'overview', label: 'Overview', icon: <LayoutDashboard className="w-3.5 h-3.5" /> },
  { key: 'transactions', label: 'Transactions', icon: <List className="w-3.5 h-3.5" /> },
  { key: 'network', label: 'Network', icon: <Network className="w-3.5 h-3.5" /> },
  { key: 'findings', label: 'AI Findings', icon: <Sparkles className="w-3.5 h-3.5" /> },
]

export const CaseWorkbench: React.FC<Props> = ({ alertId, onDisposed }) => {
  const [detail, setDetail] = useState<CaseDetail | null>(null)
  const [error, setError] = useState(false)
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('overview')
  const [labels, setLabels] = useState<Record<string, number | null>>({})
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const [openRow, setOpenRow] = useState<number | null>(null)

  useEffect(() => {
    if (!alertId) return
    setDetail(null)
    setError(false)
    setActiveTab('overview')
    setSaveState('idle')
    getAlertDetail(alertId)
      .then(d => { if (d?.case_id) setDetail(d); else setError(true) })
      .catch(() => setError(true))
  }, [alertId])

  useEffect(() => {
    if (!detail) return
    const seed: Record<string, number | null> = {}
    for (const tx of detail.transactions ?? []) {
      if (tx.transaction_id) seed[tx.transaction_id] = tx.label ?? null
    }
    setLabels(seed)
  }, [detail])

  const persistLabels = async (
    updates: { transaction_id: string; label: number | null }[],
    previous: Record<string, number | null>,
  ) => {
    if (!detail) return
    setSaveState('saving')
    try {
      await setTransactionLabels(detail.case_id, updates)
      setSaveState('saved')
    } catch {
      setLabels(previous)
      setSaveState('error')
    }
  }

  const saveLabel = (txId: string, next: number | null) => {
    const previous = { ...labels }
    setLabels(prev => ({ ...prev, [txId]: next }))
    void persistLabels([{ transaction_id: txId, label: next }], previous)
  }

  const bulkLabel = (val: number) => {
    if (!detail) return
    const shown = (detail.transactions ?? []).filter(t => t.transaction_id) as { transaction_id: string }[]
    const previous = { ...labels }
    setLabels(prev => {
      const next = { ...prev }
      shown.forEach(t => { next[t.transaction_id] = val })
      return next
    })
    void persistLabels(shown.map(t => ({ transaction_id: t.transaction_id, label: val })), previous)
  }

  if (!alertId) return <EmptyState message="Select an alert to open the case workbench" />
  if (error) return <EmptyState message="Couldn't load case detail" />
  if (!detail) return <EmptyState message="Loading case…" loading />

  return (
    <div className="flex-1 flex flex-col bg-surface-1 rounded-lg overflow-hidden shadow-soft min-w-0 min-h-0">
      <div className="flex items-start justify-between px-6 py-4 border-b border-surface-3 shrink-0 bg-surface-2">
        <div className="min-w-0">
          <div className="w-8 h-0.5 bg-accent mb-2.5" />
          <div className="flex items-center gap-2.5 mb-1">
            <h2 className="text-base font-bold text-ink truncate">{detail.customer_name}</h2>
            <RiskBadge band={detail.risk_band} />
          </div>
          <p className="text-xs text-ink-muted font-mono">
            {detail.customer_id} · {detail.account_id} · {detail.case_id}
          </p>
        </div>
        <div className="text-right shrink-0 ml-4">
          <div className={`text-4xl font-black tabular-nums ${RISK_SCORE_COLOR(detail.risk_score)}`}>
            {(detail.risk_score * 100).toFixed(0)}<span className="text-lg font-semibold">%</span>
          </div>
          <div className="text-xs text-ink-muted mt-0.5">Account Priority Score</div>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-4 px-6 py-3 border-b border-surface-3 shrink-0 bg-surface-1">
        <MetaItem label="KYC Risk Rating"><Badge label={detail.customer_kyc_rating} small neutral /></MetaItem>
        <MetaItem label="Account Age">{detail.account_age_days} days</MetaItem>
        <MetaItem label="Expected Monthly Turnover">{fmt(detail.expected_monthly_turnover)}</MetaItem>
        <MetaItem label="Observed Outflow · 30 days">{fmt(detail.observed_outflow_30d ?? 0)}</MetaItem>
      </div>

      <div className="flex items-center gap-1 px-6 border-b border-surface-3 bg-surface-1 shrink-0" role="tablist">
        {TABS.map(tab => (
          <button
            key={tab.key}
            role="tab"
            aria-selected={activeTab === tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`flex items-center gap-1.5 px-3 py-3 text-xs font-semibold border-b-2 transition-colors ${
              activeTab === tab.key
                ? 'border-accent text-accent'
                : 'border-transparent text-ink-muted hover:text-ink'
            }`}
          >
            {tab.icon}{tab.label}
          </button>
        ))}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto px-6 py-5">
        {activeTab === 'overview' && <Overview detail={detail} onOpenTransactions={() => setActiveTab('transactions')} />}
        {activeTab === 'transactions' && (
          <Transactions
            detail={detail}
            labels={labels}
            saveState={saveState}
            openRow={openRow}
            onOpenRow={setOpenRow}
            onLabel={saveLabel}
            onBulk={bulkLabel}
          />
        )}
        {activeTab === 'network' && (
          detail.network && detail.network.nodes.length > 1
            ? <NetworkGraph graph={detail.network} expanded />
            : <PanelEmpty icon={<Network className="w-8 h-8" />} message="No material account links were found." />
        )}
        {activeTab === 'findings' && (
          <AgentPanel
            caseId={detail.case_id}
            savedAnalysis={detail.analysis ? { text: detail.analysis, at: detail.analyzed_at ?? '' } : undefined}
            onDisposed={onDisposed}
            closed={!!detail.disposition}
          />
        )}
      </div>
    </div>
  )
}

const Overview: React.FC<{ detail: CaseDetail; onOpenTransactions: () => void }> = ({ detail, onOpenTransactions }) => {
  const ratio = detail.observed_vs_expected_pct ?? 0
  const timeline = [
    { label: 'Monitoring window opened', value: detail.window_start_at, muted: true },
    { label: 'First contributing transaction in pattern', value: detail.pattern_start_at },
    { label: 'Latest contributing transaction', value: detail.latest_contributing_at },
    { label: 'Nightly scoring run created alert', value: detail.scoring_run_at },
  ]

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-4">
        <section className="rounded-lg border border-surface-3 p-4 shadow-soft bg-white">
          <div className="flex items-center gap-2 mb-3">
            <AlertTriangle className="w-4 h-4 text-accent" />
            <h3 className="text-sm font-bold text-ink">Why this alert?</h3>
          </div>
          <p className="text-xs leading-5 text-ink-muted mb-3">
            The account moved into the daily review queue because its transaction pattern ranked among the highest-priority accounts in the latest monitored batch.
          </p>
          <p className="text-2xs leading-4 text-ink-muted border-l-2 border-accent pl-2 mb-3">
            The {(detail.risk_score * 100).toFixed(0)}% score prioritises analyst review; it is not a probability that the customer committed a crime.
          </p>
          <div className="flex gap-1.5 flex-wrap">
            {(detail.triggered_rules ?? []).map(r => <Badge key={r} label={r} color="#fff7ed" small />)}
          </div>
          <button onClick={onOpenTransactions} className="mt-4 text-xs font-semibold text-accent hover:text-accent-dim">
            Review supporting transactions →
          </button>
        </section>

        <section className="rounded-lg border border-surface-3 p-4 shadow-soft bg-white">
          <div className="flex items-center gap-2 mb-3">
            <Clock3 className="w-4 h-4 text-accent" />
            <h3 className="text-sm font-bold text-ink">Why now?</h3>
          </div>
          <p className="text-xs leading-5 text-ink-muted">
            The alert was created by the nightly scoring run after the recent pattern crossed the account-level prioritisation threshold. Earlier activity remains visible as context; it had not yet formed the sustained pattern shown here.
          </p>
          <div className="mt-3 rounded-lg bg-surface-2 px-3 py-2 text-2xs text-ink-muted">
            Data included through <span className="font-semibold text-ink">{fmtDate(detail.data_cutoff_at)}</span>
          </div>
        </section>
      </div>

      <div className="grid grid-cols-[1.2fr_1fr] gap-4">
        <section className="rounded-lg border border-surface-3 p-4 bg-white">
          <h3 className="text-sm font-bold text-ink mb-4">Detection timeline</h3>
          <div className="relative pl-4">
            <div className="absolute left-[5px] top-1 bottom-1 w-px bg-surface-3" />
            {timeline.map((event, i) => (
              <div key={event.label} className="relative flex items-start gap-3 pb-4 last:pb-0">
                <span className={`absolute -left-4 top-1 w-2.5 h-2.5 rounded-full border-2 border-white ${i === timeline.length - 1 ? 'bg-accent' : 'bg-ink-faint'}`} />
                <div>
                  <p className={`text-xs font-semibold ${event.muted ? 'text-ink-muted' : 'text-ink'}`}>{event.label}</p>
                  <p className="text-2xs text-ink-muted mt-0.5">{fmtDate(event.value)}</p>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-lg border border-surface-3 p-4 bg-white">
          <h3 className="text-sm font-bold text-ink mb-1">Expected vs observed</h3>
          <p className="text-2xs text-ink-muted mb-4">30-day outbound flow compared with KYC expectation</p>
          <div className="flex items-end justify-between mb-2">
            <div>
              <p className="text-2xs uppercase tracking-wider text-ink-faint">Observed</p>
              <p className="text-xl font-bold text-ink">{fmt(detail.observed_outflow_30d ?? 0)}</p>
            </div>
            <p className={`text-sm font-bold ${ratio > 100 ? 'text-red-600' : 'text-ink-muted'}`}>{ratio.toFixed(0)}%</p>
          </div>
          <div className="h-2.5 rounded-full bg-surface-3 overflow-hidden">
            <div className="h-full rounded-full bg-accent" style={{ width: `${Math.min(ratio, 100)}%` }} />
          </div>
          <div className="flex justify-between mt-2 text-2xs text-ink-muted">
            <span>Expected {fmt(detail.expected_monthly_turnover)}</span>
            <span>30-day window</span>
          </div>
          <div className="mt-4 pt-4 border-t border-surface-3 grid grid-cols-2 gap-3">
            <Detail label="Industry" value={detail.customer_industry} />
            <Detail label="KYC updated" value={detail.kyc_last_updated} />
            <Detail label="Beneficial owner" value={detail.beneficial_owner} />
            <Detail label="Model version" value={detail.model_version} />
          </div>
        </section>
      </div>

      <ScoreCalculation detail={detail} />
    </div>
  )
}

const ScoreCalculation: React.FC<{ detail: CaseDetail }> = ({ detail }) => {
  const breakdown = detail.score_breakdown
  return (
    <section className="rounded-lg border border-surface-3 p-4 bg-white">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h3 className="text-sm font-bold text-ink">How the account priority score is computed</h3>
          <p className="text-2xs text-ink-muted mt-1">
            The current demo first combines account evidence, then maps the account’s rank in the daily eligible queue to a review priority. It is not a calibrated crime probability.
          </p>
        </div>
        <div className={`text-2xl font-black tabular-nums shrink-0 ${RISK_SCORE_COLOR(detail.risk_score)}`}>{(detail.risk_score * 100).toFixed(0)}%</div>
      </div>
      {breakdown ? (
        <>
          <div className="grid grid-cols-3 gap-3 mb-4">
            <ScoreStep label="1 · Weighted account evidence" value={`${(breakdown.account_evidence_score * 100).toFixed(1)} / 100`} />
            <ScoreStep label="2 · Daily queue position" value={`${(breakdown.daily_queue_percentile * 100).toFixed(0)}th percentile`} />
            <ScoreStep label="3 · Review priority" value={`${(breakdown.display_priority_score * 100).toFixed(0)}%`} accent />
          </div>
          <div className="grid grid-cols-2 xl:grid-cols-3 gap-2">
            {breakdown.signals.map(signal => (
              <div key={signal.key} className="rounded-lg bg-surface-2 px-3 py-2.5">
                <div className="flex justify-between gap-2 text-2xs text-ink-muted">
                  <span className="truncate" title={signal.label}>{signal.label}</span>
                  <span className="shrink-0">{(signal.weight * 100).toFixed(0)}% wt.</span>
                </div>
                <div className="flex items-end justify-between gap-2 mt-1">
                  <span className="text-sm font-bold text-ink tabular-nums">{(signal.value * 100).toFixed(0)}%</span>
                  <span className="text-2xs font-semibold text-accent tabular-nums">+{(signal.contribution * 100).toFixed(1)} pts</span>
                </div>
              </div>
            ))}
          </div>
        </>
      ) : (
        <div className="rounded-lg bg-surface-2 px-3 py-3 text-xs text-ink-muted">
          This is a legacy alert created before the reproducible score breakdown was persisted. Its rule evidence is visible above; run a refreshed scoring batch to display the weighted inputs and queue position.
        </div>
      )}
    </section>
  )
}

const ScoreStep: React.FC<{ label: string; value: string; accent?: boolean }> = ({ label, value, accent }) => (
  <div className={`rounded-lg border px-3 py-2.5 ${accent ? 'border-accent/30 bg-accent/5' : 'border-surface-3'}`}>
    <p className="text-2xs text-ink-muted">{label}</p>
    <p className={`text-sm font-bold tabular-nums mt-1 ${accent ? 'text-accent' : 'text-ink'}`}>{value}</p>
  </div>
)

interface TransactionsProps {
  detail: CaseDetail
  labels: Record<string, number | null>
  saveState: SaveState
  openRow: number | null
  onOpenRow: (row: number | null) => void
  onLabel: (txId: string, next: number | null) => void
  onBulk: (value: number) => void
}

const Transactions: React.FC<TransactionsProps> = ({ detail, labels, saveState, openRow, onOpenRow, onLabel, onBulk }) => (
  <div>
    <div className="mb-4 flex items-end justify-between gap-4">
      <div>
        <h3 className="text-sm font-bold text-ink">Supporting transactions</h3>
        <p className="text-xs text-ink-muted mt-0.5">Highest-scoring evidence selected for analyst review; labels become governed training feedback.</p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <SaveIndicator state={saveState} />
        <button onClick={() => onBulk(1)} className="text-2xs font-semibold px-2.5 py-1.5 rounded-lg border border-red-200 text-red-600 bg-red-50 hover:bg-red-100">Mark all suspicious</button>
        <button onClick={() => onBulk(0)} className="text-2xs font-semibold px-2.5 py-1.5 rounded-lg border border-green-200 text-green-700 bg-green-50 hover:bg-green-100">Mark all clean</button>
      </div>
    </div>

    <div className="rounded-lg border border-surface-3 overflow-x-auto shadow-soft">
      <table className="w-full text-xs border-collapse min-w-[940px]">
        <thead><tr className="border-b border-surface-3 bg-surface-2">
          {['Time', 'Direction', 'Amount', 'Channel', 'Counterparty', 'Country', 'Signals', 'Model score', 'Analyst label'].map(h => (
            <th key={h} className="px-3 py-2.5 text-left text-ink-muted font-semibold whitespace-nowrap">{h}</th>
          ))}
        </tr></thead>
        <tbody>
          {(detail.transactions ?? []).map((tx, i) => <TransactionRow
            key={tx.transaction_id ?? i}
            tx={tx}
            open={openRow === i}
            label={tx.transaction_id ? labels[tx.transaction_id] ?? null : null}
            onOpen={() => onOpenRow(openRow === i ? null : i)}
            onLabel={next => tx.transaction_id && onLabel(tx.transaction_id, next)}
          />)}
        </tbody>
      </table>
    </div>
  </div>
)

const TransactionRow: React.FC<{
  tx: Transaction; open: boolean; label: number | null; onOpen: () => void; onLabel: (next: number | null) => void
}> = ({ tx, open, label, onOpen, onLabel }) => (
  <>
    <tr onClick={onOpen} className={`border-b border-surface-3 last:border-0 cursor-pointer transition-colors ${tx.score != null && tx.score >= 0.5 ? 'bg-orange-50/50 hover:bg-orange-50' : 'hover:bg-surface-2'}`}>
      <td className="px-3 py-2.5 text-ink-muted font-mono whitespace-nowrap"><span className="inline-flex items-center gap-1">{open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}{fmtDate(tx.event_time)}</span></td>
      <td className="px-3 py-2.5"><span className="inline-flex items-center gap-1 text-ink-muted">{tx.direction === 'OUTBOUND' ? <ArrowUpRight className="w-4 h-4 text-red-500" /> : <ArrowDownLeft className="w-4 h-4 text-green-500" />}{tx.direction === 'OUTBOUND' ? 'Out' : 'In'}</span></td>
      <td className="px-3 py-2.5 text-ink font-semibold tabular-nums whitespace-nowrap">{fmt(tx.amount)}</td>
      <td className="px-3 py-2.5 text-ink-muted">{tx.channel}</td>
      <td className="px-3 py-2.5 text-ink-muted max-w-[180px] truncate">{tx.counterparty_name}</td>
      <td className="px-3 py-2.5"><span className="px-1.5 py-0.5 rounded-lg bg-surface-3 text-ink-muted font-mono text-2xs">{tx.counterparty_country}</span></td>
      <td className="px-3 py-2.5"><span className="text-2xs text-ink-muted">{(tx.flags ?? []).length ? `${tx.flags!.length} signal${tx.flags!.length === 1 ? '' : 's'}` : '—'}</span></td>
      <td className="px-3 py-2.5 tabular-nums font-semibold">{tx.score != null ? <span className={RISK_SCORE_COLOR(tx.score)}>{(tx.score * 100).toFixed(0)}%</span> : '—'}</td>
      <td className="px-3 py-2.5" onClick={e => e.stopPropagation()}>{tx.transaction_id ? <LabelControl value={label} onChange={onLabel} /> : '—'}</td>
    </tr>
    {open && <tr className="bg-surface-2/60"><td colSpan={9} className="px-6 py-3">
      <div className="flex flex-wrap gap-1.5 mb-3">{(tx.flags ?? []).length === 0 ? <span className="text-2xs text-ink-faint">No derived transaction signals.</span> : (tx.flags ?? []).map(f => <span key={f.key} title={f.why} className="text-2xs font-semibold px-2 py-0.5 rounded-lg bg-amber-50 text-amber-700 border border-amber-200">{f.label}</span>)}</div>
      <div className="grid grid-cols-2 gap-x-8 gap-y-2"><Detail label="Transaction ID" value={tx.transaction_id} /><Detail label="From → To" value={`${tx.from_account_id ?? '—'} → ${tx.to_account_id ?? '—'}`} /><Detail label="Currency" value={tx.currency} /><Detail label="MCC" value={tx.mcc} /><Detail label="Reference" value={tx.reference} /></div>
    </td></tr>}
  </>
)

const SaveIndicator: React.FC<{ state: SaveState }> = ({ state }) => {
  if (state === 'idle') return null
  const style = state === 'error' ? 'text-red-600' : state === 'saved' ? 'text-green-700' : 'text-ink-muted'
  return <span className={`inline-flex items-center gap-1 text-2xs ${style}`}>{state === 'saved' ? <Check className="w-3 h-3" /> : <Save className={`w-3 h-3 ${state === 'saving' ? 'animate-pulse' : ''}`} />}{state === 'saving' ? 'Saving…' : state === 'saved' ? 'Saved' : 'Save failed — reverted'}</span>
}

const LabelControl: React.FC<{ value: number | null; onChange: (next: number | null) => void }> = ({ value, onChange }) => {
  const set = (v: number) => onChange(value === v ? null : v)
  return <div className="flex items-center gap-1">
    <button onClick={() => set(1)} aria-pressed={value === 1} className={`px-2 py-1 rounded-lg text-2xs font-semibold border ${value === 1 ? 'bg-red-600 text-white border-red-600' : 'bg-white text-red-600 border-red-200 hover:bg-red-50'}`}>Suspicious</button>
    <button onClick={() => set(0)} aria-pressed={value === 0} className={`px-2 py-1 rounded-lg text-2xs font-semibold border ${value === 0 ? 'bg-green-600 text-white border-green-600' : 'bg-white text-green-700 border-green-200 hover:bg-green-50'}`}>Clean</button>
  </div>
}

const Detail: React.FC<{ label: string; value?: string | null }> = ({ label, value }) => <div><p className="text-2xs text-ink-faint uppercase tracking-wider">{label}</p><p className="text-xs text-ink-muted break-all mt-0.5">{value || '—'}</p></div>
const MetaItem: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => <div><p className="text-2xs text-ink-muted uppercase tracking-wider mb-1.5">{label}</p><div className="text-sm text-ink-muted">{children}</div></div>
const PanelEmpty: React.FC<{ icon: React.ReactNode; message: string }> = ({ icon, message }) => <div className="h-64 flex flex-col items-center justify-center text-ink-faint gap-3">{icon}<p className="text-sm">{message}</p></div>
const EmptyState: React.FC<{ message: string; loading?: boolean }> = ({ message, loading }) => <div className="flex-1 flex items-center justify-center bg-surface-1 rounded-lg shadow-soft"><div className="text-center"><FileSearch className={`w-10 h-10 mx-auto mb-3 ${loading ? 'text-accent/40 animate-pulse' : 'text-ink-faint'}`} /><p className="text-sm text-ink-muted">{message}</p></div></div>
