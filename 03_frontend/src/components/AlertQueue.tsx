import React, { useEffect, useState } from 'react'
import type { Alert } from '../api'
import { getAlerts } from '../api'
import { RiskBadge } from './Badge'

const S = {
  panel: {
    width: '30%',
    background: '#1a1d27',
    borderRadius: 8,
    display: 'flex',
    flexDirection: 'column' as const,
    overflow: 'hidden',
  },
  header: {
    padding: '16px 20px',
    borderBottom: '1px solid #2a2d3a',
    display: 'flex',
    alignItems: 'center',
    gap: 10,
  },
  title: { color: '#fff', fontWeight: 700, fontSize: 16, margin: 0 },
  countBadge: {
    background: '#ff6d00',
    color: '#fff',
    borderRadius: 12,
    padding: '1px 8px',
    fontSize: 12,
    fontWeight: 700,
  },
  list: { overflowY: 'auto' as const, flex: 1 },
  card: (selected: boolean) => ({
    padding: '12px 16px',
    borderBottom: '1px solid #2a2d3a',
    cursor: 'pointer',
    background: selected ? '#252838' : 'transparent',
    borderLeft: selected ? '3px solid #ff6d00' : '3px solid transparent',
    transition: 'background 0.15s',
  }),
  row: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 },
  alertId: { color: '#aaa', fontSize: 11, fontFamily: 'monospace' },
  customerId: { color: '#ccc', fontSize: 12, marginTop: 2 },
  barBg: { background: '#2a2d3a', borderRadius: 3, height: 4, marginTop: 8 },
  barFill: (pct: number, color: string) => ({
    width: `${pct}%`,
    height: '100%',
    background: color,
    borderRadius: 3,
  }),
}

const scoreColor = (score: number) => {
  if (score >= 0.8) return '#f44336'
  if (score >= 0.6) return '#ff6d00'
  if (score >= 0.4) return '#ff9800'
  return '#00c853'
}

interface Props {
  selectedAlertId: string | null
  onSelect: (alert: Alert) => void
}

export const AlertQueue: React.FC<Props> = ({ selectedAlertId, onSelect }) => {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [openCount, setOpenCount] = useState(0)

  useEffect(() => {
    getAlerts('OPEN', 50).then(r => {
      setAlerts(r.alerts)
      setOpenCount(r.open_count ?? r.total)
    }).catch(() => {
      // backend not running — show placeholder
      setAlerts([{
        alert_id: 'ALERT-NIGHTFALL-001',
        case_id: 'CASE-NIGHTFALL-001',
        customer_id: 'CUST-NIGHTFALL-001',
        risk_score: 0.91,
        risk_band: 'CRITICAL',
        status: 'OPEN',
        created_at: new Date().toISOString(),
      }])
      setOpenCount(148)
    })
  }, [])

  return (
    <div style={S.panel}>
      <div style={S.header}>
        <h2 style={S.title}>Alert Queue</h2>
        <span style={S.countBadge}>{openCount}</span>
      </div>
      <div style={S.list}>
        {alerts.map(a => (
          <div
            key={a.alert_id}
            style={S.card(a.alert_id === selectedAlertId)}
            onClick={() => onSelect(a)}
          >
            <div style={S.row}>
              <RiskBadge band={a.risk_band} small />
              <span style={S.alertId}>{a.alert_id.slice(-12)}</span>
            </div>
            <div style={S.customerId}>{a.customer_id}</div>
            <div style={S.barBg}>
              <div style={S.barFill(a.risk_score * 100, scoreColor(a.risk_score))} />
            </div>
            <div style={{ color: '#888', fontSize: 10, marginTop: 3 }}>
              {(a.risk_score * 100).toFixed(0)}% risk
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
