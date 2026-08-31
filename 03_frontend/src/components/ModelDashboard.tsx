import { useCallback, useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { Deployment, DriftResult, ModelRun } from '../api'
import { getDrift, getDeployments, getModelRuns, triggerRetrain } from '../api'

const DEMO_RUNS: ModelRun[] = [
  { run_id: 'run-001', model_version: 'v1.2.0', status: 'COMPLETED', pr_auc: 0.847, recall_top2pct: 0.72, created_at: '2024-01-10T08:00:00Z' },
  { run_id: 'run-002', model_version: 'v1.3.0', status: 'COMPLETED', pr_auc: 0.863, recall_top2pct: 0.75, created_at: '2024-01-20T09:00:00Z' },
  { run_id: 'run-003', model_version: 'v1.4.0', status: 'RUNNING', pr_auc: 0, recall_top2pct: 0, created_at: '2024-01-31T10:00:00Z' },
]

const DEMO_DRIFT: DriftResult = {
  features: [
    { feature: 'amount_log', psi: 0.24 },
    { feature: 'hour_of_day', psi: 0.08 },
    { feature: 'is_cross_border', psi: 0.11 },
  ],
  computed_at: new Date().toISOString(),
}

const DEMO_DEP: Deployment[] = [
  { deployment_id: 'dep-001', model_version: 'v1.3.0', champion: true, deployed_at: '2024-01-21T00:00:00Z' },
]

export const ModelDashboard: React.FC = () => {
  const [runs, setRuns] = useState<ModelRun[]>([])
  const [drift, setDrift] = useState<DriftResult | null>(null)
  const [dep, setDep] = useState<Deployment | null>(null)
  const [retrainMsg, setRetrainMsg] = useState('')

  const load = useCallback(() => {
    getModelRuns().then(setRuns).catch(() => setRuns(DEMO_RUNS))
    getDrift().then(setDrift).catch(() => setDrift(DEMO_DRIFT))
    getDeployments().then(ds => setDep(ds.find(d => d.champion) ?? ds[0] ?? null))
      .catch(() => setDep(DEMO_DEP[0]))
  }, [])

  useEffect(() => { load() }, [load])

  const champion = dep?.model_version ?? '—'
  const latestRun = runs.filter(r => r.status === 'COMPLETED').at(-1)
  const prAuc = latestRun ? latestRun.pr_auc.toFixed(3) : '—'
  const annotations = 499 // demo fixed value per spec
  const threshold = 500
  const amountPsi = drift?.features.find(f => f.feature === 'amount_log')?.psi ?? 0

  const handleRetrain = async () => {
    try {
      await triggerRetrain()
      setRetrainMsg('Retrain triggered successfully.')
    } catch {
      setRetrainMsg('Retrain triggered (demo mode).')
    }
    load()
  }

  return (
    <div style={{ padding: 24 }}>
      {/* Stat cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
        <StatCard label="Model Version" value={champion} />
        <StatCard label="PR-AUC" value={prAuc} />
        <StatCard
          label="Annotations"
          value={`${annotations} / ${threshold}`}
          sub={
            <div style={{ marginTop: 8 }}>
              <div style={{ background: '#2a2d3a', borderRadius: 3, height: 6 }}>
                <div style={{
                  width: `${(annotations / threshold) * 100}%`,
                  height: '100%',
                  borderRadius: 3,
                  background: annotations >= 490 ? '#f44336' : '#00c853',
                }} />
              </div>
            </div>
          }
        />
        <StatCard
          label="Drift Status (amount_log)"
          value={amountPsi.toFixed(3)}
          valueColor={amountPsi >= 0.2 ? '#f44336' : '#00c853'}
          sub={<div style={{ color: amountPsi >= 0.2 ? '#f44336' : '#00c853', fontSize: 11, marginTop: 4 }}>
            {amountPsi >= 0.2 ? 'DRIFT DETECTED' : 'STABLE'}
          </div>}
        />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
        {/* Drift Monitor */}
        <div style={S.card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3 style={S.cardTitle}>Drift Monitor (PSI)</h3>
            <button onClick={load} style={S.btn}>Compute Drift</button>
          </div>
          {drift && (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={drift.features} margin={{ top: 4, right: 10, left: -10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2a2d3a" />
                <XAxis dataKey="feature" tick={{ fill: '#888', fontSize: 11 }} />
                <YAxis tick={{ fill: '#888', fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ background: '#1a1d27', border: '1px solid #2a2d3a', borderRadius: 6 }}
                  labelStyle={{ color: '#fff' }}
                  itemStyle={{ color: '#ff9800' }}
                />
                <ReferenceLine y={0.2} stroke="#f44336" strokeDasharray="4 2" label={{ value: '0.2', fill: '#f44336', fontSize: 11 }} />
                <Bar dataKey="psi" fill="#ff6d00" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
          <div style={{ color: '#555', fontSize: 11, marginTop: 8 }}>
            Computed: {drift ? new Date(drift.computed_at).toLocaleString() : '—'}
          </div>
        </div>

        {/* Model Runs History */}
        <div style={S.card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3 style={S.cardTitle}>Model Runs History</h3>
            <button onClick={handleRetrain} style={S.btn}>Trigger Retrain</button>
          </div>
          {retrainMsg && <div style={{ color: '#00c853', fontSize: 12, marginBottom: 10 }}>{retrainMsg}</div>}
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr>
                {['Run ID', 'Version', 'Status', 'PR-AUC', 'Recall@2%', 'Date'].map(h => (
                  <th key={h} style={{ color: '#888', fontWeight: 600, padding: '6px 8px', textAlign: 'left', borderBottom: '1px solid #2a2d3a' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {runs.map(r => (
                <tr key={r.run_id}>
                  <td style={S.td}>{r.run_id.slice(-6)}</td>
                  <td style={S.td}>{r.model_version}</td>
                  <td style={S.td}>
                    <span style={{
                      color: r.status === 'COMPLETED' ? '#00c853' : r.status === 'RUNNING' ? '#ff9800' : '#888',
                      fontWeight: 600,
                    }}>
                      {r.status}
                    </span>
                  </td>
                  <td style={S.td}>{r.pr_auc ? r.pr_auc.toFixed(3) : '—'}</td>
                  <td style={S.td}>{r.recall_top2pct ? (r.recall_top2pct * 100).toFixed(1) + '%' : '—'}</td>
                  <td style={S.td}>{new Date(r.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

const StatCard: React.FC<{
  label: string
  value: string
  valueColor?: string
  sub?: React.ReactNode
}> = ({ label, value, valueColor, sub }) => (
  <div style={S.card}>
    <div style={{ color: '#888', fontSize: 12, marginBottom: 8 }}>{label}</div>
    <div style={{ color: valueColor ?? '#fff', fontSize: 28, fontWeight: 700 }}>{value}</div>
    {sub}
  </div>
)

const S = {
  card: {
    background: '#1a1d27',
    borderRadius: 8,
    padding: 20,
  },
  cardTitle: {
    color: '#fff',
    fontSize: 14,
    margin: 0,
    fontWeight: 600,
  },
  btn: {
    background: '#ff6d00',
    color: '#fff',
    border: 'none',
    borderRadius: 5,
    padding: '6px 14px',
    cursor: 'pointer',
    fontWeight: 600,
    fontSize: 12,
  },
  td: {
    color: '#ccc',
    padding: '8px 8px',
    borderBottom: '1px solid #1e2130',
  },
}
