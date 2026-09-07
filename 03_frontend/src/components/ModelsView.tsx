import { useCallback, useEffect, useState } from 'react'
import { Boxes, Plus, Check, Loader2, FlaskConical, Pencil, X } from 'lucide-react'
import type { LlmModel } from '../api'
import { getLlmModels, registerLlmModel, updateLlmModel, activateLlmModel, testLlmModel } from '../api'

const PROVIDERS = [
  { value: 'openai',            label: 'OpenAI' },
  { value: 'openai_compatible', label: 'OpenAI Compatible' },
  { value: 'caii',              label: 'Cloudera AI Inference (CAII)' },
  { value: 'vllm',              label: 'vLLM' },
  { value: 'ollama',            label: 'Ollama' },
]

const emptyForm = { alias: '', provider: 'openai', model_identifier: '', api_base: '', api_key: '' }

export const ModelsView: React.FC = () => {
  const [models, setModels] = useState<LlmModel[]>([])
  const [form, setForm] = useState({ ...emptyForm })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [testing, setTesting] = useState<number | null>(null)
  const [testResults, setTestResults] = useState<Record<number, { ok: boolean; message: string }>>({})
  const [editingId, setEditingId] = useState<number | null>(null)

  const load = useCallback(() => { getLlmModels().then(setModels).catch(() => setModels([])) }, [])
  useEffect(() => { load() }, [load])

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm(f => ({ ...f, [k]: e.target.value }))

  const startEdit = (m: LlmModel) => {
    setEditingId(m.id)
    setForm({ alias: m.alias, provider: m.provider, model_identifier: m.model_identifier,
              api_base: m.api_base ?? '', api_key: '' })  // key blank = keep existing
    setMsg(null)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const cancelEdit = () => { setEditingId(null); setForm({ ...emptyForm }); setMsg(null) }

  const submit = async () => {
    if (!form.alias.trim() || !form.model_identifier.trim()) {
      setMsg({ ok: false, text: 'Alias and model identifier are required.' }); return
    }
    setBusy(true); setMsg(null)
    try {
      if (editingId != null) {
        await updateLlmModel(editingId, {
          alias: form.alias.trim(),
          provider: form.provider,
          model_identifier: form.model_identifier.trim(),
          api_base: form.api_base.trim(),        // empty string clears it (OpenAI default)
          api_key: form.api_key.trim() || undefined,  // blank = keep existing
        })
        setMsg({ ok: true, text: `Updated "${form.alias}".` })
      } else {
        await registerLlmModel({
          alias: form.alias.trim(),
          provider: form.provider,
          model_identifier: form.model_identifier.trim(),
          api_base: form.api_base.trim() || undefined,
          api_key: form.api_key.trim() || undefined,
        })
        setMsg({ ok: true, text: `Registered "${form.alias}" — now active. The agents will use it.` })
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

  const use = async (id: number) => { await activateLlmModel(id).catch(() => {}); load() }

  const test = async (id: number) => {
    setTesting(id)
    try {
      const result = await testLlmModel(id)
      setTestResults(prev => ({ ...prev, [id]: result }))
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setTestResults(prev => ({ ...prev, [id]: { ok: false, message: detail || 'Test failed — check the backend is running.' } }))
    }
    setTesting(null)
  }

  const needsBase = form.provider !== 'openai'

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-8">
      <div>
        <div className="w-8 h-0.5 bg-accent mb-3" />
        <h2 className="text-lg font-bold text-ink tracking-tight flex items-center gap-2">
          <Boxes className="w-5 h-5 text-accent" /> Language Models
        </h2>
        <p className="text-sm text-ink-muted mt-1">
          Register a model to power the investigation agents. The newest registration becomes active.
        </p>
      </div>

      {/* Register form */}
      <div className="bg-surface-1 rounded-lg p-5 shadow-soft space-y-4">
        <h3 className="text-sm font-semibold text-ink">{editingId != null ? 'Edit model' : 'Register model'}</h3>

        <div className="grid grid-cols-2 gap-4">
          <Field label="Model Provider">
            <select value={form.provider} onChange={set('provider')}
              className="w-full bg-surface-1 border border-surface-3 rounded-lg text-sm text-ink px-3 py-2 outline-none focus:border-accent">
              {PROVIDERS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
          </Field>
          <Field label="Model Alias">
            <Input value={form.alias} onChange={set('alias')} placeholder="e.g. gpt-5.1-prod" />
          </Field>
          <Field label="Model Identifier">
            <Input value={form.model_identifier} onChange={set('model_identifier')} placeholder="e.g. gpt-5.1, meta-llama/Llama-3.1-8B-Instruct" />
          </Field>
          <Field label={needsBase ? 'API Base' : 'API Base (optional for OpenAI)'}>
            <Input value={form.api_base} onChange={set('api_base')} placeholder="https://host/v1" />
          </Field>
          <Field label="API Key">
            <Input value={form.api_key} onChange={set('api_key')}
              placeholder={editingId != null ? 'leave blank to keep current key' : 'Enter API key'} type="password" />
          </Field>
        </div>

        <div className="flex items-center gap-3">
          <button onClick={submit} disabled={busy}
            className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-semibold transition-colors
              ${busy ? 'bg-surface-3 text-ink-faint cursor-not-allowed' : 'bg-accent text-white hover:bg-accent-dim'}`}>
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : editingId != null ? <Check className="w-4 h-4" /> : <Plus className="w-4 h-4" />}
            {editingId != null ? 'Save changes' : 'Register'}
          </button>
          {editingId != null && (
            <button onClick={cancelEdit}
              className="flex items-center gap-1 px-3 py-2 rounded-lg text-sm text-ink-muted bg-surface-2 hover:bg-surface-3 transition-colors">
              <X className="w-4 h-4" /> Cancel
            </button>
          )}
          {msg && (
            <span className={`text-xs ${msg.ok ? 'text-aml-green-dim' : 'text-aml-red-dim'}`}>{msg.text}</span>
          )}
        </div>
      </div>

      {/* Registered models */}
      <div className="bg-surface-1 rounded-lg p-5 shadow-soft">
        <h3 className="text-sm font-semibold text-ink mb-4">Registered models</h3>
        {models.length === 0 ? (
          <p className="text-xs text-ink-faint">No models registered yet — the app falls back to the configured provider.</p>
        ) : (
          <div className="rounded-lg border border-surface-3 overflow-hidden">
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr className="border-b border-surface-3 bg-surface-2">
                  {['Alias', 'Identifier', 'Provider', 'API base', 'Status', '', ''].map(h => (
                    <th key={h} className="px-3 py-2.5 text-left text-ink-muted font-semibold">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {models.map(m => {
                  const result = testResults[m.id]
                  return (
                    <tr key={m.id} className="border-b border-surface-3 last:border-0 hover:bg-surface-2">
                      <td className="px-3 py-2.5 text-ink font-semibold">{m.alias}</td>
                      <td className="px-3 py-2.5 text-ink-muted font-mono">{m.model_identifier}</td>
                      <td className="px-3 py-2.5 text-ink-muted">{m.provider}</td>
                      <td className="px-3 py-2.5 text-ink-faint font-mono">{m.api_base || '—'}</td>
                      <td className="px-3 py-2.5">
                        {m.is_active
                          ? <span className="inline-flex items-center gap-1 text-aml-green-dim font-semibold"><Check className="w-3.5 h-3.5" />Active</span>
                          : <span className="text-ink-faint">idle</span>}
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-2">
                          <button onClick={() => test(m.id)} disabled={testing === m.id}
                            className="flex items-center gap-1 text-2xs font-semibold px-2 py-1 rounded-lg text-ink-muted
                                       bg-surface-2 hover:bg-surface-3 transition-colors disabled:opacity-60">
                            {testing === m.id
                              ? <Loader2 className="w-3 h-3 animate-spin" />
                              : <FlaskConical className="w-3 h-3" />}
                            Test
                          </button>
                          <button onClick={() => startEdit(m)}
                            className="flex items-center gap-1 text-2xs font-semibold px-2 py-1 rounded-lg text-ink-muted
                                       bg-surface-2 hover:bg-surface-3 transition-colors">
                            <Pencil className="w-3 h-3" />
                            Edit
                          </button>
                          {result && (
                            <span className={`text-2xs ${result.ok ? 'text-aml-green-dim' : 'text-aml-red-dim'}`}>
                              {result.message}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        {!m.is_active && (
                          <button onClick={() => use(m.id)}
                            className="text-2xs font-semibold px-2 py-1 rounded-lg text-accent hover:bg-accent/10 transition-colors">
                            Use
                          </button>
                        )}
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
