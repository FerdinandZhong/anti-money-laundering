import { useCallback, useEffect, useState } from 'react'
import { Wrench, Plus, Check, Loader2, Plug, Pencil, X } from 'lucide-react'
import type { ToolConfig, ToolTestResult } from '../api'
import { getTools, registerTool, updateTool, testTool } from '../api'

const emptyForm = { name: '', url: '', api_key: '', enabled: true }

export const ToolsView: React.FC = () => {
  const [tools, setTools] = useState<ToolConfig[]>([])
  const [form, setForm] = useState({ ...emptyForm })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [testing, setTesting] = useState<number | null>(null)
  const [testResults, setTestResults] = useState<Record<number, ToolTestResult>>({})
  const [editingId, setEditingId] = useState<number | null>(null)

  const load = useCallback(() => { getTools().then(setTools).catch(() => setTools([])) }, [])
  useEffect(() => { load() }, [load])

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
      load()
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
      <div>
        <div className="w-8 h-0.5 bg-accent mb-3" />
        <h2 className="text-lg font-bold text-ink tracking-tight flex items-center gap-2">
          <Wrench className="w-5 h-5 text-accent" /> MCP Tool Servers
        </h2>
        <p className="text-sm text-ink-muted mt-1">
          Connect a remote (streamable-HTTP) MCP server — e.g. sanctions, registry, or adverse-media tools.
          The verification agent uses these to confirm or refute the investigation's findings.
          Unconfigured, investigations run exactly as before.
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
