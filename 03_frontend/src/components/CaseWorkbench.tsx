import React, { useEffect, useState } from 'react'
import type { CaseDetail } from '../api'
import { getCase } from '../api'
import { Badge, RiskBadge } from './Badge'
import { AgentPanel } from './AgentPanel'

interface Props {
  caseId: string | null
  alertId: string | null
}

const fmt = (n: number) =>
  new Intl.NumberFormat('en-SG', { style: 'currency', currency: 'SGD', maximumFractionDigits: 0 }).format(n)

const fmtDate = (s: string) => new Date(s).toLocaleString('en-SG', { dateStyle: 'short', timeStyle: 'short' })

export const CaseWorkbench: React.FC<Props> = ({ caseId, alertId }) => {
  const [detail, setDetail] = useState<CaseDetail | null>(null)
  useEffect(() => {
    if (!caseId) return
    setDetail(null)
    getCase(caseId).catch(() => {
      // fallback demo data
      setDetail({
        case_id: caseId,
        alert_id: alertId ?? '',
        customer_id: 'CUST-NIGHTFALL-001',
        customer_name: 'Nightfall Holdings Pte Ltd',
        risk_rating: 'HIGH',
        risk_score: 0.91,
        risk_band: 'CRITICAL',
        triggered_rules: ['RAPID_LAYERING', 'CROSS_BORDER_STRUCTURING', 'UNUSUAL_VOLUME'],
        account_age_days: 412,
        expected_monthly_turnover: 50000,
        transactions: [
          {
            event_time: '2024-01-15T09:23:00Z',
            direction: 'OUT',
            amount: 48500,
            channel: 'WIRE',
            counterparty_name: 'Shell Co BVI',
            counterparty_country: 'VG',
            typology: 'LAYERING',
            is_suspicious: 1,
          },
          {
            event_time: '2024-01-15T11:47:00Z',
            direction: 'IN',
            amount: 47800,
            channel: 'SWIFT',
            counterparty_name: 'Cayman Entity Ltd',
            counterparty_country: 'KY',
            typology: undefined,
            is_suspicious: 0,
          },
          {
            event_time: '2024-01-16T14:02:00Z',
            direction: 'OUT',
            amount: 47200,
            channel: 'WIRE',
            counterparty_name: 'Panama Holdings',
            counterparty_country: 'PA',
            typology: 'STRUCTURING',
            is_suspicious: 1,
          },
        ],
      })
    }).then(d => { if (d) setDetail(d) })
  }, [caseId])

  if (!caseId) return (
    <div style={{ ...S.panel, alignItems: 'center', justifyContent: 'center' }}>
      <p style={{ color: '#555' }}>Select an alert to open the case workbench</p>
    </div>
  )

  if (!detail) return (
    <div style={{ ...S.panel, alignItems: 'center', justifyContent: 'center' }}>
      <p style={{ color: '#888' }}>Loading case…</p>
    </div>
  )

  return (
    <div style={S.panel}>
      {/* Customer header */}
      <div style={S.header}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
            <span style={S.customerName}>{detail.customer_name}</span>
            <RiskBadge band={detail.risk_band} />
          </div>
          <div style={{ color: '#888', fontSize: 12 }}>
            {detail.customer_id} · {detail.case_id}
          </div>
        </div>
        <div style={{ textAlign: 'right' as const }}>
          <div style={{ fontSize: 36, fontWeight: 800, color: riskColor(detail.risk_score) }}>
            {(detail.risk_score * 100).toFixed(0)}%
          </div>
          <div style={{ color: '#888', fontSize: 11 }}>Risk Score</div>
        </div>
      </div>

      {/* Meta row */}
      <div style={S.metaRow}>
        <MetaItem label="Risk Rating" value={<RiskBadge band={detail.risk_rating} small />} />
        <MetaItem label="Account Age" value={`${detail.account_age_days} days`} />
        <MetaItem label="Exp. Monthly Turnover" value={fmt(detail.expected_monthly_turnover)} />
        <div style={{ gridColumn: 'span 2' }}>
          <div style={{ color: '#888', fontSize: 11, marginBottom: 4 }}>Triggered Rules</div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' as const }}>
            {detail.triggered_rules.map(r => (
              <Badge key={r} label={r} color="#2a2d3a" />
            ))}
          </div>
        </div>
      </div>

      {/* Transaction timeline */}
      <div style={{ padding: '0 20px', flex: 1, overflowY: 'auto' as const }}>
        <h3 style={{ color: '#fff', fontSize: 14, marginBottom: 10 }}>Transaction Timeline</h3>
        <table style={S.table}>
          <thead>
            <tr>
              {['Time', 'Dir', 'Amount (SGD)', 'Channel', 'Counterparty', 'Country', 'Typology'].map(h => (
                <th key={h} style={S.th}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {detail.transactions.map((tx, i) => (
              <tr key={i} style={{ background: tx.is_suspicious ? 'rgba(244,67,54,0.12)' : 'transparent' }}>
                <td style={S.td}>{fmtDate(tx.event_time)}</td>
                <td style={{ ...S.td, fontSize: 18, color: tx.direction === 'OUT' ? '#f44336' : '#00c853' }}>
                  {tx.direction === 'OUT' ? '↑' : '↓'}
                </td>
                <td style={{ ...S.td, fontWeight: 600, color: '#fff' }}>{fmt(tx.amount)}</td>
                <td style={S.td}>{tx.channel}</td>
                <td style={S.td}>{tx.counterparty_name}</td>
                <td style={S.td}>{tx.counterparty_country}</td>
                <td style={S.td}>
                  {tx.typology ? <Badge label={tx.typology} color="#ff6d00" small /> : <span style={{ color: '#555' }}>—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <AgentPanel caseId={detail.case_id} />
      </div>
    </div>
  )
}

const MetaItem: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div>
    <div style={{ color: '#888', fontSize: 11, marginBottom: 3 }}>{label}</div>
    <div style={{ color: '#ccc', fontSize: 13 }}>{value}</div>
  </div>
)

const riskColor = (score: number) => {
  if (score >= 0.8) return '#f44336'
  if (score >= 0.6) return '#ff6d00'
  if (score >= 0.4) return '#ff9800'
  return '#00c853'
}

const S = {
  panel: {
    width: '70%',
    background: '#1a1d27',
    borderRadius: 8,
    display: 'flex',
    flexDirection: 'column' as const,
    overflow: 'hidden',
  },
  header: {
    padding: '20px 24px',
    borderBottom: '1px solid #2a2d3a',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
  },
  customerName: {
    color: '#fff',
    fontWeight: 700,
    fontSize: 18,
  },
  metaRow: {
    display: 'grid',
    gridTemplateColumns: 'repeat(5, 1fr)',
    gap: 16,
    padding: '16px 24px',
    borderBottom: '1px solid #2a2d3a',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse' as const,
    fontSize: 12,
  },
  th: {
    color: '#888',
    fontWeight: 600,
    padding: '8px 10px',
    textAlign: 'left' as const,
    borderBottom: '1px solid #2a2d3a',
    whiteSpace: 'nowrap' as const,
  },
  td: {
    color: '#ccc',
    padding: '9px 10px',
    borderBottom: '1px solid #1e2130',
  },
}
