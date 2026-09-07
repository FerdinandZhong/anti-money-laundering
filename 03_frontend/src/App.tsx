import { useEffect, useState } from 'react'
import { Activity, FlaskConical, Circle, Boxes, Inbox } from 'lucide-react'
import type { Alert, EnvironmentHealth } from './api'
import { getAlerts, getEnvironmentHealth } from './api'
import { AlertQueue } from './components/AlertQueue'
import { CaseWorkbench } from './components/CaseWorkbench'
import { ModelDashboard } from './components/ModelDashboard'
import { ModelsView } from './components/ModelsView'

type Tab = 'investigation' | 'model' | 'models'

export default function App() {
  const [tab, setTab] = useState<Tab>('investigation')
  const [selected, setSelected] = useState<Alert | null>(null)
  const [hasLoaded, setHasLoaded] = useState(false)
  const [env, setEnv] = useState<EnvironmentHealth | null>(null)

  useEffect(() => {
    getAlerts().then(r => setSelected(r.alerts[0] ?? null)).finally(() => setHasLoaded(true))
    getEnvironmentHealth().then(setEnv).catch(() => setEnv(null))
  }, [])

  return (
    <div className="h-screen overflow-hidden flex flex-col bg-surface-0 font-sans">

      {/* ── Cloudera header ── */}
      <header className="bg-header border-b-[3px] border-accent flex items-center px-6 py-0 shrink-0 h-14">
        {/* Logo */}
        <div className="flex items-center gap-3 pr-8 border-r border-white/10">
          <span className="text-white font-black text-lg tracking-[0.06em] leading-none select-none">
            CLOUDERA
          </span>
        </div>

        {/* App name */}
        <div className="px-6">
          <p className="text-white font-semibold text-sm leading-tight">AML Investigation Platform</p>
          <p className="text-white/40 text-2xs leading-tight">
            Intelligent AML investigation · Cloudera AI Applied ML Prototype
          </p>
        </div>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Status indicators — reflect GET /api/health/environment, not hardcoded */}
        <div className="flex items-center gap-5 mr-5">
          <StatusDot label="Backend" ok={env !== null} />
          <StatusDot label="Model" ok={env?.active_model.reachable ?? false} title={env?.active_model.message} />
          <StatusDot
            label={env ? `Source (${env.source_backend})` : 'Source'}
            ok={env?.source_ok ?? false}
          />
        </div>

        {/* Tab buttons */}
        <div className="flex items-center gap-2">
          <TabBtn
            active={tab === 'investigation'}
            icon={<Activity className="w-3.5 h-3.5" />}
            label="Investigation"
            onClick={() => setTab('investigation')}
          />
          <TabBtn
            active={tab === 'model'}
            icon={<FlaskConical className="w-3.5 h-3.5" />}
            label="ModelOps"
            onClick={() => setTab('model')}
            primary
          />
          <TabBtn
            active={tab === 'models'}
            icon={<Boxes className="w-3.5 h-3.5" />}
            label="Models"
            onClick={() => setTab('models')}
            primary
          />
        </div>
      </header>

      {/* ── Body ── */}
      {tab === 'investigation' ? (
        hasLoaded && !selected ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <Inbox className="w-10 h-10 mx-auto mb-3 text-ink-faint" />
              <p className="text-sm text-ink-muted">No open alerts</p>
            </div>
          </div>
        ) : (
          <div className="flex flex-1 min-h-0 gap-4 p-5">
            <AlertQueue selectedAlertId={selected?.alert_id ?? null} onSelect={setSelected} />
            <CaseWorkbench alertId={selected?.alert_id ?? null} />
          </div>
        )
      ) : tab === 'model' ? (
        <div className="flex-1 min-h-0 overflow-y-auto">
          <ModelDashboard />
        </div>
      ) : (
        <div className="flex-1 min-h-0 overflow-y-auto">
          <ModelsView />
        </div>
      )}
    </div>
  )
}

function StatusDot({ label, ok, title }: { label: string; ok?: boolean; title?: string }) {
  return (
    <div className="flex items-center gap-1.5" title={title}>
      <Circle
        className={`w-2 h-2 fill-current ${ok ? 'text-aml-green' : 'text-ink-muted'}`}
      />
      <span className="text-white/50 text-xs">{label}</span>
    </div>
  )
}

function TabBtn({
  active, icon, label, onClick, primary,
}: {
  active: boolean; icon: React.ReactNode; label: string;
  onClick: () => void; primary?: boolean;
}) {
  if (primary) {
    return (
      <button
        onClick={onClick}
        className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-colors
          ${active
            ? 'bg-accent text-white'
            : 'bg-white/10 text-white/70 hover:bg-white/20 hover:text-white'
          }`}
      >
        {icon}{label}
      </button>
    )
  }
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-colors
        border
        ${active
          ? 'border-white/30 bg-white/15 text-white'
          : 'border-white/10 text-white/50 hover:border-white/20 hover:text-white/80'
        }`}
    >
      {icon}{label}
    </button>
  )
}
