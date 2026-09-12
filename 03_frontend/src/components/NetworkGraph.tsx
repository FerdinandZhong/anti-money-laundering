import React, { useState } from 'react'
import { Share2, ChevronDown, ChevronRight, Info } from 'lucide-react'
import type { NetworkGraph as Graph, NetworkNode } from '../api'

const NODE_STYLE: Record<string, { fill: string; stroke: string; text: string }> = {
  source:      { fill: '#f7f8fa', stroke: '#9aa1ac', text: '#4b5563' },
  collector:   { fill: '#fff4ee', stroke: '#e35b1f', text: '#e35b1f' },
  beneficiary: { fill: '#fef2f2', stroke: '#dc2626', text: '#dc2626' },
  account:     { fill: '#f7f8fa', stroke: '#d5d9e0', text: '#9aa1ac' },
}

const short = (id: string, max = 18) => (id.length > max ? id.slice(0, max - 1) + '…' : id)
const money = (n?: number) => (n == null ? '' : n >= 1000 ? `$${(n / 1000).toFixed(0)}k` : `$${n}`)

export const NetworkGraph: React.FC<{ graph: Graph; expanded?: boolean }> = ({ graph, expanded = false }) => {
  const [open, setOpen] = useState(true)
  if (!graph || graph.nodes.length === 0) return null

  const nodeW = expanded ? 190 : 132
  const nodeH = expanded ? 58 : 40
  const svgW = expanded ? 1200 : 640
  const colX: Record<string, number> = expanded
    ? { source: 130, collector: 505, beneficiary: 880, account: 505 }
    : { source: 90, collector: 300, beneficiary: 510, account: 300 }

  // group nodes into columns, assign y by index within the column
  const cols: Record<string, NetworkNode[]> = { source: [], collector: [], beneficiary: [], account: [] }
  graph.nodes.forEach(n => { (cols[n.type] ?? cols.account).push(n) })

  const pos: Record<string, { x: number; y: number }> = {}
  const rowGap = nodeH + (expanded ? 42 : 16)
  Object.entries(cols).forEach(([type, ns]) => {
    const x = colX[type] ?? colX.account
    const top = expanded
      ? 70 + Math.max(0, (Math.max(...Object.values(cols).map(c => c.length)) - ns.length)) * rowGap / 2
      : 20 + Math.max(0, (Math.max(...Object.values(cols).map(c => c.length)) - ns.length)) * rowGap / 2
    ns.forEach((n, i) => { pos[n.id] = { x, y: top + i * rowGap } })
  })

  const maxCount = Math.max(1, ...Object.values(cols).map(c => c.length))
  const svgH = expanded ? Math.max(540, 140 + maxCount * rowGap) : 40 + maxCount * rowGap

  const cx = (id: string) => (pos[id]?.x ?? 300) + nodeW / 2
  const cy = (id: string) => (pos[id]?.y ?? 20) + nodeH / 2

  return (
    <div className={`bg-surface-1 rounded-lg shadow-soft overflow-hidden ${expanded ? 'border border-surface-3' : ''}`}>
      <button
        onClick={() => { if (!expanded) setOpen(v => !v) }}
        className={`w-full flex items-center gap-2 border-b border-surface-3 px-4 py-2 transition-colors ${expanded ? 'cursor-default' : 'hover:bg-surface-2'}`}
      >
        <Share2 className="w-3 h-3 text-accent" />
        <span className="text-2xs font-semibold tracking-wider uppercase text-ink-muted">Network Graph</span>
        <span className="ml-auto text-2xs text-ink-faint mr-2">
          {graph.nodes.length} nodes · {graph.edges.length} links
        </span>
        {!expanded && (open ? <ChevronDown className="w-3 h-3 text-ink-faint" /> : <ChevronRight className="w-3 h-3 text-ink-faint" />)}
      </button>
      {open && <>
        {expanded && <div className="flex items-center gap-2 px-5 py-3 bg-surface-2 text-2xs text-ink-muted border-b border-surface-3">
          <Info className="w-3.5 h-3.5 text-accent shrink-0" />
          Solid orange arrows show funds movement; dashed violet links show a shared device or channel relationship. The orange-bordered node is the selected account.{graph.hidden_flow_count ? ` The ${graph.hidden_flow_count} smaller flow${graph.hidden_flow_count === 1 ? '' : 's'} remain available in Transactions.` : ''}
        </div>}
        <div className={`overflow-auto ${expanded ? 'p-5 min-h-[620px]' : 'px-2 py-2'}`} style={expanded ? undefined : { maxHeight: 320 }}>
        <svg viewBox={`0 0 ${svgW} ${svgH}`} width="100%" height={expanded ? 600 : undefined}
             preserveAspectRatio="xMidYMid meet" style={{ minWidth: expanded ? 920 : svgW }}>
          <defs>
            <marker id="ng-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
              <polygon points="0,0 8,4 0,8" fill="#e35b1f" />
            </marker>
          </defs>

          {graph.edges.map((e, i) => {
            const x1 = cx(e.source), y1 = cy(e.source), x2 = cx(e.target), y2 = cy(e.target)
            const isFlow = e.relation === 'fund_flow'
            return (
              <g key={i}>
                <line
                  x1={x1} y1={y1} x2={x2} y2={y2}
                  stroke={isFlow ? '#e35b1f' : '#c4b5fd'}
                  strokeWidth={isFlow ? 1.6 : 1.2}
                  strokeDasharray={isFlow ? undefined : '4 3'}
                  markerEnd={isFlow ? 'url(#ng-arrow)' : undefined}
                  opacity={0.8}
                />
                {isFlow && e.amount != null && (
                  <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 3} textAnchor="middle"
                        fontSize={8} fill="#e35b1f" fontFamily="Inter,system-ui,sans-serif">
                    {money(e.amount)}
                  </text>
                )}
              </g>
            )
          })}

          {graph.nodes.map(n => {
            const p = pos[n.id]; if (!p) return null
            const s = NODE_STYLE[n.type] ?? NODE_STYLE.account
            return (
              <g key={n.id}>
                <rect x={p.x} y={p.y} width={nodeW} height={nodeH} rx={expanded ? 10 : 7}
                      fill={s.fill} stroke={s.stroke} strokeWidth={n.is_root ? (expanded ? 3 : 2) : 1} />
                <text x={p.x + nodeW / 2} y={p.y + (expanded ? 25 : 17)} textAnchor="middle" fontSize={expanded ? 15 : 9}
                      fill={s.text} fontWeight="600" fontFamily="Inter,system-ui,sans-serif">
                  {short(n.label ?? n.id)}
                </text>
                <text x={p.x + nodeW / 2} y={p.y + (expanded ? 44 : 30)} textAnchor="middle" fontSize={expanded ? 11 : 7.5}
                      fill={s.text} opacity={0.7} fontFamily="Inter,system-ui,sans-serif">
                  {n.label && n.label !== n.id ? short(n.id, 16) : n.type}{n.country ? ` · ${n.country}` : ''}
                </text>
              </g>
            )
          })}
        </svg>
        </div>
      </>}
    </div>
  )
}
