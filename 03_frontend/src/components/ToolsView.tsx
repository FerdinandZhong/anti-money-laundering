import { useCallback, useEffect, useState } from 'react'
import { Wrench, Plus, Check, Loader2, Plug, Pencil, X } from 'lucide-react'
import type { ToolConfig, ToolTestResult, EmbeddedServer } from '../api'
import { getTools, registerTool, updateTool, testTool, getEmbedded, updateEmbedded, testEmbedded } from '../api'

// ── Embedded server metadata (frontend-only, mirrors backend field lists) ──

const EMBEDDED_META: Record<string, {
  title: string; blurb: string; fallback: string
  labels: Record<string, string>; secrets: string[]
}> = {
  'iceberg-mcp': {
    title: 'Iceberg MCP Server',
    blurb: 'Read-only Iceberg/Impala access for the investigation agents (execute_query, get_schema).',
    fallback: 'Unconfigured — investigation reads the local CSV dataset.',
    labels: {
      impala_host: 'Impala host', impala_port: 'Port', impala_user: 'Workload user',
      impala_password: 'Workload password', impala_database: 'Database',
    },
    secrets: ['impala_password'],
  },
  'workbench-mcp': {
    title: 'CAI Workbench MCP Server',
    blurb: 'Drives training jobs + canary model deployments on Cloudera AI Workbench for the retraining workflow.',
    fallback: 'Unconfigured — retraining trains locally, no Workbench job is created.',
    labels: { host: 'Workbench host', api_key: 'API key', project_id: 'Project ID' },
    secrets: ['api_key'],
  },
}

// ── EmbeddedCard ───────────────────────────────────────────────────────────

const EmbeddedCard: React.FC<{ server: EmbeddedServer; onSaved: () => void }> = ({ server, onSaved }) => {
  const meta = EMBEDDED_META[server.name]
  if (!meta) return null
  const [form, setForm] = useState<Record<string, string>>(
    Object.fromEntries(
      server.fields.map(f => [f, meta.secrets.includes(f) ? '' : (server.params[f] ?? '')])
    )
  )
  const [enabled, setEnabled] = useState(server.enabled)
  const [busy, setBusy] = useState(false)
  const [testing, setTesting] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const save = async () => {
    setBusy(true); setMsg(null)
    try {
      await updateEmbedded(server.name, { params: form, enabled })
      setMsg({ ok: true, text: 'Saved.' }); onSaved()
    } catch { setMsg({ ok: false, text: 'Save failed — check the backend.' }) }
    setBusy(false)
  }

  const test = async () => {
    setTesting(true); setMsg(null)
    try {
      const r = await testEmbedded(server.name, form)
      setMsg(r.ok
        ? { ok: true, text: `${r.count} tool(s): ${(r.tools ?? []).join(', ')}` }
        : { ok: false, text: r.message ?? 'Connection failed' })
    } catch { setMsg({ ok: false, text: 'Test failed — check the backend.' }) }
    setTesting(false)
  }

  return (
    <div className="bg-surface-1 rounded-lg p-5 shadow-soft space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-sm font-semibold text-ink">{meta.title}</h3>
          <p className="text-xs text-ink-muted mt-0.5 max-w-xl">{meta.blurb}</p>
        </div>
        <span className={`text-2xs font-semibold px-2 py-1 rounded-full shrink-0
          ${server.configured ? 'bg-aml-green/10 text-aml-green-dim' : 'bg-surface-2 text-ink-faint'}`}>
          {server.configured ? 'Active' : 'Local fallback'}
        </span>
      </div>
      {!server.configured && <p className="text-2xs text-ink-faint">{meta.fallback}</p>}
      <div className="grid grid-cols-2 gap-4">
        {server.fields.map(f => (
          <Field key={f} label={meta.labels[f] ?? f}>
            <Input
              value={form[f] ?? ''}
              type={meta.secrets.includes(f) ? 'password' : 'text'}
              placeholder={meta.secrets.includes(f) && server.params[f] ? 'leave blank to keep current' : ''}
              onChange={e => setForm(prev => ({ ...prev, [f]: e.target.value }))}
            />
          </Field>
        ))}
      </div>
      <div className="flex items-center gap-3">
        <button onClick={save} disabled={busy}
          className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-semibold transition-colors
            ${busy ? 'bg-surface-3 text-ink-faint cursor-not-allowed' : 'bg-accent text-white hover:bg-accent-dim'}`}>
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />} Save
        </button>
        <button onClick={test} disabled={testing}
          className="flex items-center gap-1 px-3 py-2 rounded-lg text-sm text-ink-muted bg-surface-2 hover:bg-surface-3 transition-colors">
          {testing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plug className="w-4 h-4" />} Test connection
        </button>
        <label className="flex items-center gap-2 text-sm text-ink-muted">
          <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)}
            className="accent-accent w-4 h-4" /> Enabled
        </label>
        {msg && <span className={`text-xs ${msg.ok ? 'text-aml-green-dim' : 'text-aml-red-dim'}`}>{msg.text}</span>}
      </div>
    </div>
  )
}

// ── ToolsView ──────────────────────────────────────────────────────────────

const emptyForm = { name: '', url: '', api_key: '', enabled: true }

export const ToolsView: React.FC = () => {
  const [servers, setServers] = useState<EmbeddedServer[]>([])
  const [tools, setTools] = useState<ToolConfig[]>([])
  const [form, setForm] = useState({ ...emptyForm })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [testing, setTesting] = useState<number | null>(null)
  const [testResults, setTestResults] = useState<Record<number, ToolTestResult>>({})
  const [editingId, setEditingId] = useState<number | null>(null)

  const loadEmbedded = useCallback(() => { getEmbedded().then(setServers).catch(() => setServers([])) }, [])
  const loadTools = useCallback(() => { getTools().then(setTools).catch(() => setTools([])) }, [])

  useEffect(() => { loadEmbedded(); loadTools() }, [loadEmbedded, loadTools])

  const set = (k: 'name' | 'url' | 'api_key') => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm(f => ({ ...f, [k]: e.target.value }))

  const startEdit = (t: ToolConfig) => {
    setEditingId(t.id)
    setForm({ name: t.name, url: t.url, api_key: '', enabled: !!t.enabled })  // key blank = keep existing
    setMsg(null)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const cancelEdit = () => { setEditingId(null); setForm({ ...emptyForm }); setMsg(null) }

  const submit = async () => {
    if (!form.name.trim() || !form.url.trim()) {
      setMsg({ ok: false, text: 'Name and URL are required.' }); return
    }
    setBusy(true); setMsg(null)
    try {
      const body = {
        name: form.name.trim(),
        url: form.url.trim(),
        api_key: form.api_key.trim() || undefined,   // blank = keep existing on edit
        enabled: form.enabled,
      }
      if (editingId != null) {
        await updateTool(editingId, body)
        setMsg({ ok: true, text: `Updated "${form.name}".` })
      } else {
        await registerTool(body)
        setMsg({ ok: true, text: `Registered "${form.name}". Configure a tool-calling model to enable verification.` })
      }
      setEditingId(null)
      setForm({ ...emptyForm })
      loadTools()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setMsg({ ok: false, text: detail || 'Save failed — check the backend is running.' })
    }
    setBusy(false)
  }

  const test = async (id: number) => {
    setTesting(id)
    try {
      const result = await testTool(id)
      setTestResults(prev => ({ ...prev, [id]: result }))
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setTestResults(prev => ({ ...prev, [id]: { ok: false, message: detail || 'Test failed — check the backend is running.' } }))
    }
    setTesting(null)
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-8">

      {/* ── Section 1: Embedded Cloudera MCP Servers ── */}
      <div>
        <div className="w-8 h-0.5 bg-accent mb-3" />
        <h2 className="text-lg font-bold text-ink tracking-tight flex items-center gap-2">
          <Wrench className="w-5 h-5 text-accent" /> Embedded Cloudera MCP Servers
        </h2>
        <p className="text-sm text-ink-muted mt-1">
          Built-in MCP servers for Cloudera infrastructure. Configure credentials to activate live data access;
          leave unconfigured to use local CSV fallbacks.
        </p>
      </div>

      {servers.length === 0 ? (
        <p className="text-xs text-ink-faint">Loading embedded servers…</p>
      ) : (
        <div className="space-y-4">
          {servers.map(s => <EmbeddedCard key={s.name} server={s} onSaved={loadEmbedded} />)}
        </div>
      )}

      {/* ── Section 2: Custom verification servers ── */}
      <div>
        <div className="w-8 h-0.5 bg-accent mb-3" />
        <h2 className="text-lg font-bold text-ink tracking-tight flex items-center gap-2">
          <Wrench className="w-5 h-5 text-accent" /> Custom Verification Servers
        </h2>
        <p className="text-sm text-ink-muted mt-1">
          Remote streamable-HTTP MCP servers used by the verification agent (sanctions, registry, adverse media…).
        </p>
      </div>

      {/* Register form */}
      <div className="bg-surface-1 rounded-lg p-5 shadow-soft space-y-4">
        <h3 className="text-sm font-semibold text-ink">{editingId != null ? 'Edit MCP server' : 'Add MCP server'}</h3>

        <div className="grid grid-cols-2 gap-4">
          <Field label="Name">
            <Input value={form.name} onChange={set('name')} placeholder="e.g. sanctions-mcp" />
          </Field>
          <Field label="Server URL (streamable-HTTP)">
            <Input value={form.url} onChange={set('url')} placeholder="https://host/mcp" />
          </Field>
          <Field label="API Key (optional — sent as Bearer)">
            <Input value={form.api_key} onChange={set('api_key')} type="password"
              placeholder={editingId != null ? 'leave blank to keep current key' : 'Enter API key'} />
          </Field>
          <Field label="Enabled">
            <label className="flex items-center gap-2 h-[38px] text-sm text-ink-muted">
              <input type="checkbox" checked={form.enabled}
                onChange={e => setForm(f => ({ ...f, enabled: e.target.checked }))}
                className="accent-accent w-4 h-4" />
              Available to the verification agent
            </label>
          </Field>
        </div>

        <div className="flex items-center gap-3">
          <button onClick={submit} disabled={busy}
            className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-semibold transition-colors
              ${busy ? 'bg-surface-3 text-ink-faint cursor-not-allowed' : 'bg-accent text-white hover:bg-accent-dim'}`}>
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : editingId != null ? <Check className="w-4 h-4" /> : <Plus className="w-4 h-4" />}
            {editingId != null ? 'Save changes' : 'Add server'}
          </button>
          {editingId != null && (
            <button onClick={cancelEdit}
              className="flex items-center gap-1 px-3 py-2 rounded-lg text-sm text-ink-muted bg-surface-2 hover:bg-surface-3 transition-colors">
              <X className="w-4 h-4" /> Cancel
            </button>
          )}
          {msg && <span className={`text-xs ${msg.ok ? 'text-aml-green-dim' : 'text-aml-red-dim'}`}>{msg.text}</span>}
        </div>
      </div>

      {/* Registered servers */}
      <div className="bg-surface-1 rounded-lg p-5 shadow-soft">
        <h3 className="text-sm font-semibold text-ink mb-4">Registered servers</h3>
        {tools.length === 0 ? (
          <p className="text-xs text-ink-faint">No MCP servers yet — investigations run without the verification step.</p>
        ) : (
          <div className="rounded-lg border border-surface-3 overflow-hidden">
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr className="border-b border-surface-3 bg-surface-2">
                  {['Name', 'URL', 'Status', '', ''].map((h, i) => (
                    <th key={i} className="px-3 py-2.5 text-left text-ink-muted font-semibold">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tools.map(t => {
                  const result = testResults[t.id]
                  return (
                    <tr key={t.id} className="border-b border-surface-3 last:border-0 hover:bg-surface-2 align-top">
                      <td className="px-3 py-2.5 text-ink font-semibold">{t.name}</td>
                      <td className="px-3 py-2.5 text-ink-muted font-mono break-all max-w-[16rem]">{t.url}</td>
                      <td className="px-3 py-2.5">
                        {t.enabled
                          ? <span className="inline-flex items-center gap-1 text-aml-green-dim font-semibold"><Check className="w-3.5 h-3.5" />Enabled</span>
                          : <span className="text-ink-faint">disabled</span>}
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-2 flex-wrap">
                          <button onClick={() => test(t.id)} disabled={testing === t.id}
                            className="flex items-center gap-1 text-2xs font-semibold px-2 py-1 rounded-lg text-ink-muted
                                       bg-surface-2 hover:bg-surface-3 transition-colors disabled:opacity-60">
                            {testing === t.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plug className="w-3 h-3" />}
                            Test connection
                          </button>
                          <button onClick={() => startEdit(t)}
                            className="flex items-center gap-1 text-2xs font-semibold px-2 py-1 rounded-lg text-ink-muted
                                       bg-surface-2 hover:bg-surface-3 transition-colors">
                            <Pencil className="w-3 h-3" /> Edit
                          </button>
                          {result && (
                            <span className={`text-2xs ${result.ok ? 'text-aml-green-dim' : 'text-aml-red-dim'}`}>
                              {result.ok
                                ? `${result.count} tool(s): ${(result.tools ?? []).join(', ') || '—'}`
                                : result.message}
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

const Field: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div className="space-y-1">
    <label className="text-2xs text-ink-muted uppercase tracking-wider">{label}</label>
    {children}
  </div>
)

const Input: React.FC<React.InputHTMLAttributes<HTMLInputElement>> = (props) => (
  <input {...props}
    className="w-full bg-surface-1 border border-surface-3 rounded-lg text-sm text-ink px-3 py-2 outline-none focus:border-accent placeholder-ink-faint" />
)
