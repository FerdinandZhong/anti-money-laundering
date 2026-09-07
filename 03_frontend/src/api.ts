import axios from 'axios'

export const api = axios.create({ baseURL: '/api' })

export interface Alert {
  alert_id: string
  case_id?: string
  customer_id: string
  risk_score: number
  risk_band: string
  status: string
  created_at: string
}

export interface AlertsResponse {
  alerts: Alert[]
  total: number
  open_count: number
}

export interface CaseDetail {
  case_id: string
  alert_id: string
  customer_id: string
  customer_name: string
  customer_kyc_rating: string
  risk_score: number
  risk_band: string
  triggered_rules: string[]
  reason_codes?: string[]
  top_features?: Record<string, number>
  model_version?: string
  account_age_days: number
  expected_monthly_turnover: number
  transactions: Transaction[]
  analysis?: string | null
  analyzed_at?: string | null
  disposition?: string | null
}

export interface Transaction {
  transaction_id?: string
  event_time: string
  direction: string
  amount: number
  channel: string
  counterparty_name: string
  counterparty_country: string
  typology?: string
  is_suspicious: number
  score: number | null
  label?: number | null   // analyst per-tx label: 1 suspicious, 0 clean, null unset
}

export interface Stats {
  total_alerts: number
  open_alerts: number
  critical_alerts: number
  total_cases: number
  total_annotations: number
  total_labelled: number
  suspicious_labelled: number
  human_labelled: number
}

export interface ModelRun {
  run_id: string
  model_version: string
  status: string
  metrics?: string        // JSON string: { pr_auc, recall_top2pct, ... }
  pr_auc?: number         // present only in DEMO fallback rows
  recall_top2pct?: number
  created_at: string
}

export interface Deployment {
  deployment_id: string
  model_version: string
  status: string          // CHAMPION | CANARY | SHADOW | RETIRED
  traffic_pct?: number
  deployed_at?: string
}

export interface DriftResult {
  features: { feature: string; psi: number }[]
  computed_at: string
}

export interface EnvironmentHealth {
  source_backend: 'impala' | 'csv'
  source_ok: boolean
  active_model: { alias: string; reachable: boolean; message: string }
  champion_artifact_present: boolean
}

export type AlertSort = 'risk_score' | 'newest' | 'oldest'

export const getEnvironmentHealth = () =>
  api.get<EnvironmentHealth>('/health/environment').then(r => r.data)

export const getAlerts = (status = 'OPEN', limit = 50, sort: AlertSort = 'risk_score') =>
  api.get<AlertsResponse>('/alerts', { params: { status, limit, sort } }).then(r => r.data)

export const getAlertDetail = (alertId: string) =>
  api.get<CaseDetail>(`/alerts/${alertId}/detail`).then(r => r.data)

export const getStats = () =>
  api.get<Stats>('/stats').then(r => r.data)

export const investigateCase = (caseId: string) =>
  fetch(`/api/cases/${caseId}/investigate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ stream: true }),
  })

export const disposeCase = (caseId: string, body: { disposition: string; notes: string; adjudicator: string }) =>
  api.post(`/cases/${caseId}/dispose`, body).then(r => r.data)

export const setTransactionLabels = (
  caseId: string,
  labels: { transaction_id: string; label: number | null }[],
  labeledBy = '',
) => api.post(`/cases/${caseId}/transaction-labels`, { labels, labeled_by: labeledBy }).then(r => r.data)

export const getModelRuns = () =>
  api.get<{ runs: ModelRun[] }>('/model/runs').then(r => r.data.runs)

export const getDeployments = () =>
  api.get<{ deployments: Deployment[] }>('/model/deployments').then(r => r.data.deployments)

export const getDrift = () =>
  api.get<DriftResult>('/model/drift').then(r => r.data)

export interface ScoreBin { bucket: string; count: number }
export interface AlertBand { band: string; count: number }

export const getScoreHistogram = () =>
  api.get<{ bins: ScoreBin[] }>('/model/score-histogram').then(r => r.data.bins)

export const getAlertBands = () =>
  api.get<{ bands: AlertBand[] }>('/model/alert-bands').then(r => r.data.bands)

export const triggerRetrain = () =>
  api.post('/model/retrain').then(r => r.data)

// Retraining pipeline as an SSE stream (create-job → run → canary → promote).
export const retrainStream = () =>
  fetch('/api/model/retrain/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  })

/** Read a `data: {json}\n\n` SSE response and invoke onEvent per parsed event.
 *  Buffers across chunk boundaries so split lines don't drop events. */
export async function streamSSE(
  res: Response,
  onEvent: (e: Record<string, unknown>) => void,
) {
  if (!res.body) return
  const reader = res.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    const lines = buf.split('\n')
    buf = lines.pop() ?? ''          // keep the trailing partial line
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const raw = line.slice(6).trim()
      if (!raw || raw === '[DONE]') continue
      try { onEvent(JSON.parse(raw)) } catch { /* ignore malformed frame */ }
    }
  }
}

export interface CaiiEndpoint {
  name: string
  base_url: string
  model: string
}

export const getCaiiEndpoints = () =>
  api.get<{ endpoints: CaiiEndpoint[] }>('/config/llm/caii-endpoints').then(r => r.data.endpoints)

export const setLlmProvider = (body: { provider: string; base_url?: string; model?: string }) =>
  api.post('/config/llm', body).then(r => r.data)

export interface LlmModel {
  id: number
  alias: string
  provider: string
  model_identifier: string
  api_base: string | null
  api_key: string        // masked from the server
  is_active: number
}

export interface RegisterModelBody {
  alias: string
  provider: string
  model_identifier: string
  api_base?: string
  api_key?: string
}

export const getLlmModels = () =>
  api.get<{ models: LlmModel[] }>('/config/llm/models').then(r => r.data.models)

export const registerLlmModel = (body: RegisterModelBody) =>
  api.post('/config/llm/models', body).then(r => r.data)

export const activateLlmModel = (id: number) =>
  api.post(`/config/llm/models/${id}/activate`).then(r => r.data)

export const updateLlmModel = (id: number, body: RegisterModelBody) =>
  api.put(`/config/llm/models/${id}`, body).then(r => r.data)

export const testLlmModel = (id: number) =>
  api.post<{ ok: boolean; message: string }>(`/config/llm/models/${id}/test`).then(r => r.data)
