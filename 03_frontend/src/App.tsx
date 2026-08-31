import { useEffect, useState } from 'react'
import type { Alert } from './api'
import { AlertQueue } from './components/AlertQueue'
import { CaseWorkbench } from './components/CaseWorkbench'
import { ModelDashboard } from './components/ModelDashboard'

const DEFAULT_ALERT: Alert = {
  alert_id: 'ALERT-NIGHTFALL-001',
  case_id: 'CASE-NIGHTFALL-001',
  customer_id: 'CUST-NIGHTFALL-001',
  risk_score: 0.91,
  risk_band: 'CRITICAL',
  status: 'OPEN',
  created_at: new Date().toISOString(),
}

export default function App() {
  const [tab, setTab] = useState<'investigation' | 'model'>('investigation')
  const [selected, setSelected] = useState<Alert>(DEFAULT_ALERT)

  useEffect(() => { setSelected(DEFAULT_ALERT) }, [])

  return (
    <div style={{
      minHeight: '100vh',
      background: '#0f1117',
      fontFamily: "'Inter', 'Segoe UI', sans-serif",
      color: '#ccc',
    }}>
      {/* Top nav */}
      <div style={{
        background: '#1a1d27',
        borderBottom: '1px solid #2a2d3a',
        padding: '0 24px',
        display: 'flex',
        alignItems: 'center',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginRight: 32, padding: '14px 0' }}>
          <div style={{
            width: 28, height: 28, borderRadius: 6,
            background: '#ff6d00',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontWeight: 900, color: '#fff', fontSize: 14,
          }}>C</div>
          <span style={{ color: '#fff', fontWeight: 700, fontSize: 15 }}>AML Intelligence Platform</span>
        </div>

        {[
          { key: 'investigation', label: 'Dashboard A: Investigation' },
          { key: 'model', label: 'Dashboard B: Model Health' },
        ].map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key as typeof tab)}
            style={{
              background: 'none',
              border: 'none',
              borderBottom: tab === t.key ? '2px solid #ff6d00' : '2px solid transparent',
              color: tab === t.key ? '#fff' : '#888',
              padding: '16px 20px',
              cursor: 'pointer',
              fontWeight: tab === t.key ? 600 : 400,
              fontSize: 13,
              transition: 'color 0.15s',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'investigation' ? (
        <div style={{
          display: 'flex',
          gap: 16,
          padding: 16,
          height: 'calc(100vh - 57px)',
          boxSizing: 'border-box',
        }}>
          <AlertQueue selectedAlertId={selected.alert_id} onSelect={setSelected} />
          <CaseWorkbench caseId={selected.case_id} alertId={selected.alert_id} />
        </div>
      ) : (
        <ModelDashboard />
      )}
    </div>
  )
}
