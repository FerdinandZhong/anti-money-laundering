import { useEffect, useState } from 'react'
import { Activity, Boxes, FlaskConical, Inbox, LayoutGrid, Wrench } from 'lucide-react'
import type { Alert, EnvironmentHealth } from './api'
import { getAlerts, getEnvironmentHealth } from './api'
import { AlertQueue } from './components/AlertQueue'
import { CaseWorkbench } from './components/CaseWorkbench'
import { ModelDashboard } from './components/ModelDashboard'
import { ModelsView } from './components/ModelsView'
import { ToolsView } from './components/ToolsView'
import './App.css'

type Tab = 'investigation' | 'model' | 'models' | 'tools'

const pages: { key: Tab; label: string; icon: React.ReactNode }[] = [
  { key: 'investigation', label: 'Investigation', icon: <Activity /> },
  { key: 'model', label: 'ModelOps', icon: <FlaskConical /> },
  { key: 'models', label: 'Models', icon: <Boxes /> },
  { key: 'tools', label: 'Tools', icon: <Wrench /> },
]

export default function App() {
  const [tab, setTab] = useState<Tab>('investigation')
  const [selected, setSelected] = useState<Alert | null>(null)
  const [hasLoaded, setHasLoaded] = useState(false)
  const [queueError, setQueueError] = useState(false)
  const [env, setEnv] = useState<EnvironmentHealth | null>(null)
  const [envLoaded, setEnvLoaded] = useState(false)
  const [queueReload, setQueueReload] = useState(0)

  useEffect(() => {
    getAlerts().then(r => setSelected(r.alerts[0] ?? null)).catch(() => { setSelected(null); setQueueError(true) }).finally(() => setHasLoaded(true))
    getEnvironmentHealth().then(setEnv).catch(() => setEnv(null)).finally(() => setEnvLoaded(true))
  }, [])

  return <div className="app-shell font-sans">
    <aside className="app-sidebar">
      <div className="app-brand" aria-label="Cloudera AML Investigation">CLOUDERA<span>AML INVESTIGATION</span></div>
      <div className="app-workspace-card"><span className="app-workspace-icon"><LayoutGrid size={17} /></span><div><strong>Investigation workspace</strong><small>Account review</small></div></div>
      <div className="app-nav-heading">WORKSPACE</div>
      <nav className="app-nav" aria-label="Main navigation">
        {pages.map(page => <button key={page.key} type="button" aria-current={tab === page.key ? 'page' : undefined} onClick={() => setTab(page.key)}>{page.icon}{page.label}</button>)}
      </nav>
      <div className="app-sidebar-bottom"><strong>Connected data</strong><p>{env ? `${env.source_backend.toUpperCase()} source · ${env.active_model.reachable ? 'model available' : 'model unavailable'}` : envLoaded ? 'Environment status unavailable' : 'Checking backend and source status…'}</p></div>
      <div className="app-sidebar-persona"><span>AML</span><div>Analyst workspace<small>Customer review</small></div></div>
    </aside>

    <div className="app-main">
      <header className="app-topbar">
        <div className="app-breadcrumb">Cloudera AI <span>/</span> AML <span>/</span> <strong>{pages.find(page => page.key === tab)?.label}</strong></div>
        <div className="app-statuses" aria-label="Environment status">
          <Status label="Backend" ok={hasLoaded && !queueError} />
          <Status label="Model" ok={env?.active_model.reachable ?? false} title={env?.active_model.message} />
          <Status label={env ? `Source (${env.source_backend})` : 'Source'} ok={env?.source_ok ?? false} />
        </div>
      </header>
      <main className="app-main-content" id="main-content">
        {tab === 'investigation' ? hasLoaded && !selected ? <div className="app-empty"><div><Inbox /><p>{queueError ? 'Could not load alerts' : 'No open alerts'}</p></div></div>
          : <div className="investigation-workspace"><AlertQueue selectedAlertId={selected?.alert_id ?? null} onSelect={setSelected} reloadKey={queueReload} />
            <CaseWorkbench alertId={selected?.alert_id ?? null} onDisposed={() => setQueueReload(key => key + 1)} /></div>
          : <div className="app-scroll-page">{tab === 'model' ? <ModelDashboard /> : tab === 'models' ? <ModelsView /> : <ToolsView />}</div>}
      </main>
    </div>
  </div>
}

function Status({ label, ok, title }: { label: string; ok: boolean; title?: string }) {
  return <div className="app-status" title={title || `${label}: ${ok ? 'available' : 'unavailable'}`}>
    <span className={`app-status-dot ${ok ? 'is-ok' : ''}`} />
    <span>{label}</span>
  </div>
}
