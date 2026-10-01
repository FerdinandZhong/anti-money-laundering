import { useEffect, useState } from 'react'
import { getKnowledgeLibrary, getSemanticGraph } from '../api'
import type { CaseDetail, KnowledgeLibrary, SemanticGraph as GraphModel } from '../api'
import './SemanticGraph.css'

type GraphNode = GraphModel['nodes'][number]

const NODE_WIDTH = 176
const NODE_HEIGHT = 76
const positions: Record<string, [number, number]> = {
  customer: [22, 120], account: [246, 120], transaction: [470, 12],
  alert: [470, 120], case: [694, 120], evidence: [694, 228], lance_kyc: [470, 228],
}
const keyFields: Record<string, string[]> = {
  customer: ['customer_id', 'risk_rating', 'expected_monthly_turnover', 'beneficial_owner'],
  account: ['account_id', 'customer_id', 'status'],
  transaction: ['transaction_id', 'from_account_id', 'to_account_id', 'amount', 'event_time'],
  alert: ['alert_id', 'account_id', 'risk_score', 'data_cutoff_at'],
  case: ['case_id', 'alert_id', 'state'],
  evidence: ['evidence_id', 'case_id', 'data_version'],
}
const keyFunctions: Record<string, string> = {
  customer: 'Provides the KYC profile and declared activity baseline.',
  account: 'Sets the account scope for monitoring and investigation.',
  transaction: 'Records monetary movement used to calculate observed activity.',
  alert: 'Ranks an account for review at a recorded data cutoff.',
  case: 'Tracks the investigation opened from an alert.',
  evidence: 'Retains references to retrieval or verification results.',
}

function edgePath(from: GraphNode, to: GraphNode) {
  const [fromX, fromY] = positions[from.id]
  const [toX, toY] = positions[to.id]
  const horizontal = Math.abs(toX - fromX) >= Math.abs(toY - fromY)
  if (horizontal) {
    const forward = toX > fromX
    const x1 = fromX + (forward ? NODE_WIDTH : 0)
    const x2 = toX + (forward ? 0 : NODE_WIDTH)
    const y1 = fromY + NODE_HEIGHT / 2
    const y2 = toY + NODE_HEIGHT / 2
    const bend = Math.max(32, Math.abs(x2 - x1) / 2)
    const direction = Math.sign(x2 - x1)
    return `M ${x1} ${y1} C ${x1 + direction * bend} ${y1}, ${x2 - direction * bend} ${y2}, ${x2} ${y2}`
  }
  const down = toY > fromY
  const x1 = fromX + NODE_WIDTH / 2
  const x2 = toX + NODE_WIDTH / 2
  const y1 = fromY + (down ? NODE_HEIGHT : 0)
  const y2 = toY + (down ? 0 : NODE_HEIGHT)
  const bend = Math.max(32, Math.abs(y2 - y1) / 2)
  const direction = Math.sign(y2 - y1)
  return `M ${x1} ${y1} C ${x1} ${y1 + direction * bend}, ${x2} ${y2 - direction * bend}, ${x2} ${y2}`
}

function accountValue(id: string, detail: CaseDetail) {
  switch (id) {
    case 'customer': return `${detail.customer_name} · ${detail.customer_id}`
    case 'account': return detail.account_id || 'No account ID recorded'
    case 'transaction': return detail.observed_outflow_30d == null
      ? 'No 30-day outflow available in this case view'
      : `30-day recorded outflow: ${detail.observed_outflow_30d.toLocaleString('en-SG')}`
    case 'alert': return `Review priority: ${(detail.risk_score * 100).toFixed(1)}%`
    case 'case': return detail.case_id
    case 'evidence': return 'See the KYC Documents and AI Findings tabs'
    default: return 'No account value shown in this view'
  }
}

export function SemanticGraph({ detail }: { detail: CaseDetail }) {
  const [model, setModel] = useState<GraphModel | null>(null)
  const [failed, setFailed] = useState(false)
  const [selected, setSelected] = useState('account')
  const [library, setLibrary] = useState<KnowledgeLibrary | null>(null)

  useEffect(() => {
    let active = true
    getSemanticGraph().then(value => { if (active) setModel(value) })
      .catch(() => { if (active) setFailed(true) })
    return () => { active = false }
  }, [])
  useEffect(() => {
    let active = true
    getKnowledgeLibrary(detail.alert_id).then(value => { if (active) setLibrary(value) })
      .catch(() => { if (active) setLibrary({ available: false, release_id: null, documents: [] }) })
    return () => { active = false }
  }, [detail.alert_id])

  if (failed) return <p role="status">The model graph is unavailable. Account data remains above.</p>
  if (!model) return <p role="status">Loading the model graph…</p>

  const isLance = selected === 'lance_kyc'
  const node = model.nodes.find(item => item.id === selected) || model.nodes[0]
  const concept = model.ontology.concepts.find(item => item.id === node.id)
  const links = model.edges.filter(edge => edge.source === node.id || edge.target === node.id)
  const nodes = new Map(model.nodes.map(item => [item.id, item]))
  const cutoff = detail.data_cutoff_at ? new Date(detail.data_cutoff_at).getTime() : null
  const eligibleDocuments = library?.documents.filter(item => cutoff == null || new Date(item.received_at).getTime() <= cutoff).length || 0

  return <div className="semantic-map">
    <p className="semantic-map-caption">Select a node for its key fields and function. Solid arrows are Ossie-declared joins; the dashed arrow is the KYC evidence retrieval path.</p>
    <div className="semantic-graph-scroll" aria-label="Ossie model and data lineage graph">
      <div className="semantic-graph-stage">
        <svg className="semantic-graph-lines" viewBox="0 0 900 320" aria-hidden="true">
          <defs><marker id="semantic-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M 0 0 L 8 4 L 0 8 Z" fill="context-stroke" /></marker></defs>
          {model.edges.map(edge => {
            const from = nodes.get(edge.source), to = nodes.get(edge.target)
            if (!from || !to || !positions[from.id] || !positions[to.id]) return null
            return <path key={edge.id} d={edgePath(from, to)} fill="none"
              strokeWidth={edge.source === selected || edge.target === selected ? 2.5 : 1.5}
              stroke={edge.source === selected || edge.target === selected ? 'var(--color-accent)' : '#b9b3c9'}
              markerEnd="url(#semantic-arrow)" />
          })}
          <path d="M 646 266 C 666 266, 674 266, 694 266" fill="none"
            stroke="var(--color-accent)" strokeWidth="2" strokeDasharray="5 5" markerEnd="url(#semantic-arrow)" />
        </svg>
        {model.nodes.map(item => {
          const [x, y] = positions[item.id] || [22, 38]
          return <button key={item.id} type="button" style={{ left: x, top: y, width: NODE_WIDTH, height: NODE_HEIGHT }}
            className={`semantic-graph-node ${selected === item.id ? 'is-selected' : ''}`}
            aria-pressed={selected === item.id} onClick={() => setSelected(item.id)}>
            <span className="semantic-graph-kind">{item.source}</span><strong>{item.label}</strong>
          </button>
        })}
        <button type="button" style={{ left: 470, top: 228, width: NODE_WIDTH, height: NODE_HEIGHT }}
          className={`semantic-graph-node is-index ${isLance ? 'is-selected' : ''}`}
          aria-pressed={isLance} onClick={() => setSelected('lance_kyc')}>
          <span className="semantic-graph-kind">LanceDB · PDF / OCR</span><strong>KYC page index</strong>
        </button>
      </div>
    </div>
    <div className="semantic-map-detail" aria-live="polite">
      {isLance ? <>
        <div>
          <span className="semantic-map-eyebrow">KYC evidence index</span>
          <h3>PDF, image and text → searchable pages</h3>
          <p>Native PDF text or OCR from scanned pages is split into cited chunks. Original files stay in the same versioned release.</p>
          <p className="semantic-map-current">{!library ? 'Checking indexed documents…' : !library.available
            ? 'KYC index unavailable' : cutoff == null
              ? `${library.documents.length} document versions linked to this customer/account`
              : `${library.documents.length} document versions linked to this customer/account; ${eligibleDocuments} received by the alert cutoff`}</p>
        </div>
        <div>
          <span className="semantic-map-eyebrow">LanceDB structure and function</span>
          <p><strong>documents:</strong> version, scope, receipt time and asset hash.</p>
          <p><strong>chunks:</strong> page, extracted text, OCR evidence and chunk ID.</p>
          <p><strong>Search:</strong> bilingual full-text; vector search when an embedding model is configured.</p>
          <p><strong>Scope:</strong> customer, account and receipt cutoff for alert search.</p>
        </div>
      </> : <>
        <div>
          <span className="semantic-map-eyebrow">Business meaning and function</span>
          <h3>{node.label}</h3>
          <p>{concept?.definition || node.description || 'No definition supplied in this model.'}</p>
          <p><strong>Key function:</strong> {keyFunctions[node.id] || node.description}</p>
          <p className="semantic-map-current">This account: {accountValue(node.id, detail)}</p>
        </div>
        <div>
          <span className="semantic-map-eyebrow">Essential attributes and lineage</span>
          <div className="semantic-map-attributes">{(keyFields[node.id] || node.primary_key).filter(field => node.fields.some(item => item.name === field)).map(field => <span key={field}>{field}</span>)}</div>
          <p>Source: <strong>{node.source}</strong></p>
          <ul>{links.map(edge => <li key={edge.id}>{edge.description || `${edge.source} connects to ${edge.target}`}</li>)}</ul>
        </div>
      </>}
    </div>
  </div>
}
