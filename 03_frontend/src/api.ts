import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export interface Alert {
  alert_id: string
  case_id: string
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
  risk_rating: string
  risk_score: number
  risk_band: string
  triggered_rules: string[]
  account_age_days: number
  expected_monthly_turnover: number
  transactions: Transaction[]
}

export interface Transaction {
  event_time: string
  direction: string
  amount: number
  channel: string
  counterparty_name: string
  counterparty_country: string
  typology?: string
  is_suspicious: number
}

export interface Stats {
  open_alerts: number
  critical_alerts: number
  annotations_total: number
  annotations_threshold: number
}

export interface ModelRun {
  run_id: string
  model_version: string
  status: string
  pr_auc: number
  recall_top2pct: number
  created_at: string
}

export interface Deployment {
  deployment_id: string
  model_version: string
  champion: boolean
  deployed_at: string
}

export interface DriftResult {
  features: { feature: string; psi: number }[]
  computed_at: string
}

export const getAlerts = (status = 'OPEN', limit = 50) =>
  api.get<AlertsResponse>('/alerts', { params: { status, limit } }).then(r => r.data)

export const getCase = (caseId: string) =>
  api.get<CaseDetail>(`/cases/${caseId}`).then(r => r.data)

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

export const getModelRuns = () =>
  api.get<ModelRun[]>('/model/runs').then(r => r.data)

export const getDeployments = () =>
  api.get<Deployment[]>('/model/deployments').then(r => r.data)

export const getDrift = () =>
  api.get<DriftResult>('/model/drift').then(r => r.data)

export const triggerRetrain = () =>
  api.post('/model/retrain').then(r => r.data)
