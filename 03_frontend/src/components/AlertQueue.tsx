import React, { useEffect, useState } from 'react'
import { Bell, RefreshCw } from 'lucide-react'
import type { Alert, AlertSort, AlertStatus } from '../api'
import { getAlerts, getAlertCounts } from '../api'
import { RiskBadge } from './Badge'

const RISK_COLOR: Record<string, string> = {
  CRITICAL: '#dc2626', HIGH: '#ea580c', MEDIUM: '#d97706', LOW: '#16a34a',
}

const BUCKETS: { status: AlertStatus; label: string }[] = [
  { status: 'OPEN', label: 'Open' },
  { status: 'PROPOSED', label: 'Proposed' },
  { status: 'PENDING', label: 'Pending' },
  { status: 'CLOSED', label: 'Archived' },
]

interface Props {
  selectedAlertId: string | null
  onSelect: (alert: Alert) => void
  reloadKey?: number   // bump to force a reload after a disposition
}

export const AlertQueue: React.FC<Props> = ({ selectedAlertId, onSelect, reloadKey }) => {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [counts, setCounts] = useState<Record<AlertStatus, number>>({ OPEN: 0, PROPOSED: 0, PENDING: 0, CLOSED: 0 })
  const [status, setStatus] = useState<AlertStatus>('OPEN')
  const [loading, setLoading] = useState(true)
  const [sort, setSort] = useState<AlertSort>('risk_score')
  const [error, setError] = useState(false)

  const load = (nextStatus: AlertStatus = status, nextSort: AlertSort = sort) => {
    setLoading(true); setError(false)
    getAlerts(nextStatus, 50, nextSort)
      .then(r => setAlerts(r.alerts))
      .catch(() => { setAlerts([]); setError(true) })
      .finally(() => setLoading(false))
    getAlertCounts().then(setCounts).catch(() => {})
  }

  useEffect(() => { load() }, [reloadKey])   // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="w-[28%] shrink-0 flex flex-col bg-surface-1 rounded-lg overflow-hidden shadow-soft min-h-0">
      {/* Header */}
      <div className="flex items-center gap-2.5 px-4 py-3 border-b border-surface-3 shrink-0 bg-surface-2">
        <Bell className="w-3.5 h-3.5 text-accent" />
        <h2 className="text-sm font-semibold text-ink flex-1">Alert Queue</h2>
        <span className="px-2 py-0.5 text-xs font-bold rounded-full bg-accent/10 text-accent border border-accent/20">
          {counts[status]}
        </span>
        <select
          value={sort}
          onChange={e => { const next = e.target.value as AlertSort; setSort(next); load(status, next) }}
          className="text-2xs text-ink-muted border border-surface-3 rounded-lg px-1.5 py-0.5 bg-surface-1"
          title="Sort alerts"
        >
          <option value="risk_score">Risk score</option>
          <option value="newest">Newest</option>
          <option value="oldest">Oldest</option>
        </select>
        <button
          onClick={() => load()}
          className="p-1 text-ink-faint hover:text-ink-muted rounded-lg hover:bg-surface-3 transition-colors"
          title="Refresh"
        >
          <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Bucket bar */}
      <div className="flex gap-1 px-3 py-2 border-b border-surface-3 bg-surface-1">
        {BUCKETS.map(b => (
          <button
            key={b.status}
            onClick={() => { setStatus(b.status); load(b.status) }}
            className={`text-2xs font-semibold px-2 py-1 rounded-lg transition-colors
              ${status === b.status ? 'bg-accent text-white' : 'text-ink-muted bg-surface-2 hover:bg-surface-3'}`}
          >
            {b.label} <span className="opacity-70">{counts[b.status]}</span>
          </button>
        ))}
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto divide-y divide-surface-3">
        {alerts.map(a => {
          const isSelected = a.alert_id === selectedAlertId
          return (
            <div
              key={a.alert_id}
              onClick={() => onSelect(a)}
              className={`px-4 py-3 cursor-pointer transition-colors border-l-2 animate-fade-in
                ${isSelected
                  ? 'bg-accent/5 border-l-accent'
                  : 'border-l-transparent hover:bg-surface-2'
                }`}
            >
              <div className="flex items-center justify-between mb-1.5">
                <RiskBadge band={a.risk_band} small />
                <span className="text-2xs text-ink-faint font-mono">{a.alert_id.slice(-12)}</span>
              </div>
              <div className="text-xs text-ink-muted mb-2 truncate">{a.customer_id}</div>
              <div className="flex items-center gap-2">
                <div className="flex-1 h-1.5 rounded-full bg-surface-3">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${a.risk_score * 100}%`,
                      background: RISK_COLOR[a.risk_band] ?? '#9ca3af',
                    }}
                  />
                </div>
                <span className="text-2xs text-ink-muted tabular-nums w-7 text-right">
                  {(a.risk_score * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          )
        })}

        {alerts.length === 0 && !loading && (
          <div className="flex items-center justify-center h-32 text-sm text-ink-faint">
            {error ? "Couldn't load alerts" : `No ${status.toLowerCase()} alerts`}
          </div>
        )}
      </div>
    </div>
  )
}
