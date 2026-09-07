import { useCallback, useEffect, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { FlaskConical, RefreshCw, TrendingUp, Cpu, Database, Activity, Loader2 } from 'lucide-react'
import type { AlertBand, Deployment, DriftResult, ModelRun, ScoreBin, Stats } from '../api'
import {
  getAlertBands, getDrift, getDeployments, getModelRuns, getScoreHistogram, getStats,
  retrainStream, streamSSE,
} from '../api'
import { PipelineStream, type PipelineItem } from './PipelineStream'
import type { WorkflowNode } from './WorkflowGraph'

// Token-mirrored chart colors (Recharts takes literal hex, not CSS classes).
const C = { accent: '#e35b1f', grid: '#e3e6ea', axis: '#6b7280', ink: '#1a1a2e', danger: '#dc2626' }

const BAND_COLOR: Record<string, string> = {
  CRITICAL: '#dc2626', HIGH: '#ea580c', MEDIUM: '#d97706', LOW: '#059669',
}

const RT_PHASES = ['PREPARE', 'TRAIN', 'CANARY', 'PROMOTE', 'NARRATE']

// Mirrors the step names yielded by 02_backend/agents/retraining.py, grouped by phase.
const RT_STEP_PHASE: Record<string, string> = {
  dataset: 'PREPARE',
  create_job: 'TRAIN', run_job: 'TRAIN', train_workbench: 'TRAIN', train_local: 'TRAIN',
  canary_deploy: 'CANARY', canary_record: 'CANARY',
  promote: 'PROMOTE',
}

const STATUS_CFG: Record<string, { textCls: string; dotCls: string }> = {
  COMPLETE:  { textCls: 'text-aml-green', dotCls: 'bg-aml-green' },
  COMPLETED: { textCls: 'text-aml-green', dotCls: 'bg-aml-green' },
  RUNNING:   { textCls: 'text-aml-amber', dotCls: 'bg-aml-amber animate-pulse' },
  FAILED:    { textCls: 'text-aml-red',   dotCls: 'bg-aml-red' },
}

/** Pull pr_auc / recall from a run — live rows carry a metrics JSON string,
 *  demo rows carry the numbers directly. */
function runMetrics(r: ModelRun): { pr_auc?: number; recall?: number } {
  if (r.metrics) {
    try { const m = JSON.parse(r.metrics); return { pr_auc: m.pr_auc, recall: m.recall_top2pct } } catch { /* noop */ }
  }
  return { pr_auc: r.pr_auc, recall: r.recall_top2pct }
}

export const ModelDashboard: React.FC = () => {
  const [runs, setRuns]   = useState<ModelRun[]>([])
  const [drift, setDrift] = useState<DriftResult | null>(null)
  const [dep, setDep]     = useState<Deployment | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(false)
  const [bands, setBands] = useState<AlertBand[] | null>(null)
  const [hist, setHist] = useState<ScoreBin[] | null>(null)

  // Retraining pipeline stream state
  const [rtPhase, setRtPhase]     = useState<string | null>(null)
  const [rtItems, setRtItems]     = useState<PipelineItem[]>([])
  const [rtNarrative, setRtNarr]  = useState('')
  const [rtRunning, setRtRunning] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    Promise.allSettled([
      getModelRuns().then(setRuns).catch(() => setRuns([])),
      getDrift().then(setDrift).catch(() => setDrift(null)),
      getDeployments().then(ds => setDep(ds.find(d => d.status === 'CHAMPION') ?? ds[0] ?? null))
                      .catch(() => setDep(null)),
      getStats().then(setStats).catch(() => setStats(null)),
      getAlertBands().then(setBands).catch(() => setBands(null)),
      getScoreHistogram().then(setHist).catch(() => setHist(null)),
    ]).finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const champion = dep?.model_version ?? '—'
  // PR-AUC card must reflect the active CHAMPION's own run, not just the most
  // recently dated completed run — those diverge after a rollback, or when
  // /model/runs (limited to 10) no longer includes the champion's run.
  const championRun = dep ? runs.find(r => r.model_version === dep.model_version) : undefined
  const latestRun = championRun ?? runs.filter(r => r.status.startsWith('COMPLET')).at(-1)
  const prAuc     = latestRun ? (runMetrics(latestRun).pr_auc?.toFixed(3) ?? '—') : '—'
  const amountPsi   = drift?.features?.find(f => f.feature === 'amount_log')?.psi ?? 0

  const handleRetrainEvent = (e: Record<string, unknown>) => {
    switch (e.type) {
      case 'phase':
        setRtPhase(String(e.phase))
        break
      case 'step': {
        const key = String(e.step)
        const raw = String(e.status)
        const status: PipelineItem['status'] =
          raw === 'ok' ? 'ok' : raw === 'skip' ? 'skip' : raw === 'error' ? 'error' : 'running'
        const item: PipelineItem = {
          key, status, mono: true,
          label: key.replace(/_/g, ' '),
          detail: String(e.detail ?? ''),
        }
        setRtItems(prev => {
          const i = prev.findIndex(x => x.key === key)
          if (i < 0) return [...prev, item]
          const next = [...prev]; next[i] = item; return next
        })
        break
      }
      case 'token':
        setRtNarr(prev => prev + String(e.text ?? ''))
        break
      case 'done':
        load()   // refresh runs + champion once promotion lands
        break
    }
  }

  const runRetrain = async () => {
    setRtPhase(null); setRtItems([]); setRtNarr(''); setRtRunning(true)
    try {
      const res = await retrainStream()
      await streamSSE(res, handleRetrainEvent)
    } catch {
      setRtItems([{ key: 'error', label: 'pipeline', status: 'error', detail: 'Backend not reachable.' }])
    }
    setRtRunning(false)
  }

  // Live DAG for the retrain pipeline: one node per RT_PHASES entry, status
  // rolled up from its steps (see RT_STEP_PHASE) — NARRATE has no steps, just tokens.
  const rtPhaseIdx = rtPhase ? RT_PHASES.indexOf(rtPhase) : -1
  const rtGraphNodes: WorkflowNode[] = (rtRunning || rtItems.length > 0 || rtPhaseIdx >= 0)
    ? RT_PHASES.map((phase, i) => {
        if (phase === 'NARRATE') {
          const status: WorkflowNode['status'] = rtNarrative
            ? (rtRunning ? 'running' : 'completed')
            : rtPhaseIdx === i ? 'running' : rtPhaseIdx > i ? 'completed' : 'pending'
          return { id: phase, label: phase, status, llmCalls: 1 }
        }
        const steps = rtItems.filter(it => RT_STEP_PHASE[it.key] === phase)
        let status: WorkflowNode['status']
        if (steps.some(s => s.status === 'error')) status = 'error'
        else if (steps.length === 0) status = rtPhaseIdx > i ? 'completed' : rtPhaseIdx === i ? 'running' : 'pending'
        else if (steps.every(s => s.status === 'skip')) status = 'skip'
        else if (steps.some(s => s.status === 'ok')) status = 'completed'
        else status = 'running'
        return { id: phase, label: phase, status }
      })
    : []

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-8">

      {/* Model performance section */}
      <div>
        <div className="w-8 h-0.5 bg-accent mb-3" />
        <h2 className="text-lg font-bold text-ink tracking-tight">Model performance</h2>
        <p className="text-sm text-ink-muted mt-1">
          Test-set metrics from the latest training run — compare across versions below.
        </p>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-4 gap-4">
        <StatCard icon={<Cpu className="w-4 h-4 text-accent" />} label="Champion Model" value={champion} />
        <StatCard icon={<TrendingUp className="w-4 h-4 text-aml-green" />} label="PR-AUC" value={prAuc} valueClass="text-aml-green-dim" />
        <StatCard
          icon={<Database className="w-4 h-4 text-aml-amber" />}
          label="Labelled transactions"
          value={stats ? stats.total_labelled.toLocaleString() : '—'}
          sub={
            <p className="text-2xs text-ink-muted mt-1.5">
              {stats ? `${stats.suspicious_labelled} suspicious · ${stats.human_labelled} analyst-tagged` : '—'}
            </p>
          }
        />
        <StatCard
          icon={<Activity className={`w-4 h-4 ${amountPsi >= 0.2 ? 'text-aml-red' : 'text-aml-green'}`} />}
          label="Feature Drift (PSI)"
          value={amountPsi.toFixed(3)}
          valueClass={amountPsi >= 0.2 ? 'text-aml-red-dim' : 'text-aml-green-dim'}
          sub={
            <span className={`text-2xs font-semibold mt-1 block ${amountPsi >= 0.2 ? 'text-aml-red-dim' : 'text-aml-green-dim'}`}>
              {amountPsi >= 0.2 ? '⚠ DRIFT DETECTED' : '✓ STABLE'}
            </span>
          }
        />
      </div>

      {/* ModelOps console section header */}
      <div>
        <div className="w-8 h-0.5 bg-accent mb-3" />
        <h2 className="text-lg font-bold text-ink tracking-tight">ModelOps console</h2>
        <p className="text-sm text-ink-muted mt-1">
          Monitor drift, review run history, and run the retraining pipeline.
        </p>
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-2 gap-5">
        {/* Drift monitor */}
        <div className="bg-surface-1 rounded-lg p-5 shadow-soft">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-sm font-semibold text-ink">Drift Monitor</h3>
              <p className="text-xs text-ink-muted mt-0.5">Population Stability Index per feature</p>
            </div>
            <button
              onClick={load}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-ink-muted
                         bg-surface-2 rounded-lg hover:bg-surface-3 transition-colors"
            >
              <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
              Compute
            </button>
          </div>
          {drift && (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={drift.features} margin={{ top: 4, right: 10, left: -10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.grid} />
                <XAxis dataKey="feature" tick={{ fill: C.axis, fontSize: 11 }} />
                <YAxis tick={{ fill: C.axis, fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ background: '#fff', border: `1px solid ${C.grid}`, borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: C.ink }}
                  itemStyle={{ color: C.accent }}
                  cursor={{ fill: 'rgba(227,91,31,0.06)' }}
                />
                <ReferenceLine
                  y={0.2} stroke={C.danger} strokeDasharray="4 2"
                  label={{ value: '0.2', fill: C.danger, fontSize: 10 }}
                />
                <Bar dataKey="psi" fill={C.accent} radius={[4, 4, 0, 0]} maxBarSize={40} />
              </BarChart>
            </ResponsiveContainer>
          )}
          <p className="text-2xs text-ink-faint mt-2">
            Computed: {drift ? new Date(drift.computed_at).toLocaleString() : '—'}
          </p>
        </div>

        {/* Model runs */}
        <div className="bg-surface-1 rounded-lg p-5 shadow-soft">
          <div className="mb-4">
            <h3 className="text-sm font-semibold text-ink">Model Runs History</h3>
            <p className="text-xs text-ink-muted mt-0.5">Training runs and performance metrics</p>
          </div>

          <div className="rounded-lg border border-surface-3 overflow-hidden">
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr className="border-b border-surface-3 bg-surface-2">
                  {['Run', 'Version', 'Status', 'PR-AUC', 'Recall@2%', 'Date'].map(h => (
                    <th key={h} className="px-3 py-2.5 text-left text-ink-muted font-semibold">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {runs.map(r => {
                  const cfg = STATUS_CFG[r.status] ?? STATUS_CFG.FAILED
                  const m = runMetrics(r)
                  return (
                    <tr key={r.run_id} className="border-b border-surface-3 last:border-0 hover:bg-surface-2">
                      <td className="px-3 py-2.5 text-ink-faint font-mono">{r.run_id.slice(-6)}</td>
                      <td className="px-3 py-2.5 text-ink-muted font-mono">{r.model_version}</td>
                      <td className="px-3 py-2.5">
                        <span className={`flex items-center gap-1.5 font-semibold ${cfg.textCls}`}>
                          <span className={`w-1.5 h-1.5 rounded-full ${cfg.dotCls}`} />
                          {r.status}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-ink-muted tabular-nums">{m.pr_auc ? m.pr_auc.toFixed(3) : '—'}</td>
                      <td className="px-3 py-2.5 text-ink-muted tabular-nums">{m.recall ? (m.recall * 100).toFixed(1) + '%' : '—'}</td>
                      <td className="px-3 py-2.5 text-ink-muted">{new Date(r.created_at).toLocaleDateString()}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Analytics row: alert bands, score distribution, PR-AUC trend */}
      <div className="grid grid-cols-3 gap-5">
        {/* Alert band breakdown */}
        <div className="bg-surface-1 rounded-lg p-5 shadow-soft">
          <h3 className="text-sm font-semibold text-ink">Alert Band Breakdown</h3>
          <p className="text-xs text-ink-muted mt-0.5 mb-2">Open alerts by risk band</p>
          {bands && bands.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie data={bands} dataKey="count" nameKey="band" innerRadius={50} outerRadius={80} paddingAngle={2}>
                  {bands.map(b => (
                    <Cell key={b.band} fill={BAND_COLOR[b.band] ?? C.accent} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: '#fff', border: `1px solid ${C.grid}`, borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: C.ink }}
                />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-2xs text-ink-faint py-16 text-center">
              {loading ? 'Loading…' : 'No alert band data'}
            </p>
          )}
        </div>

        {/* Risk-score distribution */}
        <div className="bg-surface-1 rounded-lg p-5 shadow-soft">
          <h3 className="text-sm font-semibold text-ink">Risk-Score Distribution</h3>
          <p className="text-xs text-ink-muted mt-0.5 mb-2">Score histogram across scored transactions (log scale — most transactions score low)</p>
          {hist && hist.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={hist} margin={{ top: 4, right: 10, left: -10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.grid} />
                <XAxis dataKey="bucket" tick={{ fill: C.axis, fontSize: 10 }} />
                <YAxis scale="log" domain={[0.9, 'auto']} allowDataOverflow tick={{ fill: C.axis, fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ background: '#fff', border: `1px solid ${C.grid}`, borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: C.ink }}
                  itemStyle={{ color: C.accent }}
                  cursor={{ fill: 'rgba(227,91,31,0.06)' }}
                />
                <Bar dataKey="count" fill={C.accent} radius={[4, 4, 0, 0]} maxBarSize={30} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-2xs text-ink-faint py-16 text-center">
              {loading ? 'Loading…' : 'No score data'}
            </p>
          )}
        </div>

        {/* PR-AUC across versions */}
        <div className="bg-surface-1 rounded-lg p-5 shadow-soft">
          <h3 className="text-sm font-semibold text-ink">PR-AUC Across Versions</h3>
          <p className="text-xs text-ink-muted mt-0.5 mb-2">Trend across completed training runs</p>
          {runs.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <LineChart
                data={runs.map(r => ({ version: r.model_version.slice(-8), pr_auc: runMetrics(r).pr_auc ?? null }))}
                margin={{ top: 4, right: 10, left: -10, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke={C.grid} />
                <XAxis dataKey="version" tick={{ fill: C.axis, fontSize: 10 }} />
                <YAxis tick={{ fill: C.axis, fontSize: 11 }} domain={[0, 1]} />
                <Tooltip
                  contentStyle={{ background: '#fff', border: `1px solid ${C.grid}`, borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: C.ink }}
                  itemStyle={{ color: C.accent }}
                />
                <Line type="monotone" dataKey="pr_auc" stroke={C.accent} strokeWidth={2} dot={{ r: 3, fill: C.accent }} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-2xs text-ink-faint py-16 text-center">
              {loading ? 'Loading…' : 'No run history'}
            </p>
          )}
        </div>
      </div>

      {/* Retraining pipeline (streamed agent workflow) */}
      <div className="bg-surface-1 rounded-lg p-5 shadow-soft">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-semibold text-ink">Retraining pipeline</h3>
            <p className="text-xs text-ink-muted mt-0.5">
              Agent workflow: create job → run → canary deploy → promote to CHAMPION
            </p>
          </div>
          <button
            onClick={runRetrain}
            disabled={rtRunning}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-lg transition-colors
              ${rtRunning ? 'bg-surface-3 text-ink-faint cursor-not-allowed' : 'bg-accent text-white hover:bg-accent-dim'}`}
          >
            {rtRunning
              ? <><Loader2 className="w-3.5 h-3.5 animate-spin" />Retraining…</>
              : <><FlaskConical className="w-3.5 h-3.5" />Run retraining</>}
          </button>
        </div>

        <PipelineStream
          phases={RT_PHASES}
          activePhase={rtPhase}
          items={rtItems}
          narrative={rtNarrative}
          narrativeTitle="Summary"
          running={rtRunning}
          idle={'// Run retraining to stream the pipeline…'}
          graphNodes={rtGraphNodes}
        />
      </div>
    </div>
  )
}

const StatCard: React.FC<{
  icon: React.ReactNode; label: string; value: string; valueClass?: string; sub?: React.ReactNode
}> = ({ icon, label, value, valueClass, sub }) => (
  <div className="bg-surface-1 rounded-lg p-5 shadow-soft">
    <div className="flex items-center gap-2 mb-3">
      <div className="p-1.5 bg-surface-2 rounded-lg">{icon}</div>
      <p className="text-xs text-ink-muted font-medium">{label}</p>
    </div>
    <div className={`text-2xl font-bold tabular-nums ${valueClass ?? 'text-ink'}`}>{value}</div>
    {sub}
  </div>
)
