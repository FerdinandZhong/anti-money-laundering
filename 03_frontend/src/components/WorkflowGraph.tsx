import { GitBranch } from 'lucide-react'

export interface WorkflowNode {
  id: string
  label: string
  status: 'pending' | 'running' | 'completed' | 'skip' | 'error'
  llmCalls?: number
  tools?: { name: string; error?: boolean }[]
  parallel?: boolean   // consecutive parallel nodes render as one concurrent lane
}

interface Props {
  nodes: WorkflowNode[]
  running?: boolean
}

// Light-theme colors (SVG fill/stroke need literal hex, not CSS classes).
const STATUS_COLORS: Record<WorkflowNode['status'], { fill: string; stroke: string; text: string }> = {
  pending:   { fill: '#f7f8fa', stroke: '#d5d9e0', text: '#9aa1ac' },
  running:   { fill: '#fff4ee', stroke: '#e35b1f', text: '#e35b1f' },
  completed: { fill: '#ecfdf3', stroke: '#059669', text: '#059669' },
  skip:      { fill: '#f7f8fa', stroke: '#9aa1ac', text: '#9aa1ac' },
  error:     { fill: '#fef2f2', stroke: '#dc2626', text: '#dc2626' },
}

const NODE_W = 130
const NODE_H = 46
const H_GAP  = 44
const V_GAP  = 14
const ARROW  = 8

/** Presentational live DAG for an agent pipeline. Consecutive nodes flagged
 *  `parallel` are drawn stacked in one column (a concurrent lane) with fan-out /
 *  fan-in edges — so the graph matches the real execution (the investigation runs
 *  its 4 collector workers in parallel; retraining stays a sequential chain). */
export const WorkflowGraph: React.FC<Props> = ({ nodes, running }) => {
  if (nodes.length === 0) return null

  // Group consecutive parallel nodes into a single column (lane).
  const columns: number[][] = []
  nodes.forEach((n, i) => {
    const prev = columns[columns.length - 1]
    if (n.parallel && prev && nodes[prev[0]].parallel) prev.push(i)
    else columns.push([i])
  })

  const groupH = (k: number) => k * NODE_H + (k - 1) * V_GAP
  const maxK = Math.max(...columns.map(c => c.length))
  const contentH = groupH(maxK)
  const SVG_H = contentH + 56           // padding for labels + tool chips
  const midY = 24 + contentH / 2
  const colX = (c: number) => 20 + c * (NODE_W + H_GAP) + NODE_W / 2
  const totalW = columns.length * NODE_W + (columns.length - 1) * H_GAP
  const svgW = totalW + 40

  // Position + column-length per node index.
  const pos: Record<number, { x: number; y: number; cxv: number; cyv: number; solo: boolean }> = {}
  columns.forEach((col, c) => {
    const top = midY - groupH(col.length) / 2
    col.forEach((ni, j) => {
      const y = top + j * (NODE_H + V_GAP)
      pos[ni] = { x: colX(c) - NODE_W / 2, y, cxv: colX(c), cyv: y + NODE_H / 2, solo: col.length === 1 }
    })
  })

  const doneCount = nodes.filter(n => n.status === 'completed').length

  return (
    <div className="bg-surface-1 rounded-lg shadow-soft overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-surface-3 px-4 py-2">
        <GitBranch className={`w-3 h-3 ${running ? 'text-accent animate-pulse' : 'text-ink-faint'}`} />
        <span className="text-2xs font-semibold tracking-wider uppercase text-ink-muted">
          Workflow Graph
        </span>
        <span className="ml-auto text-2xs text-ink-faint">{doneCount}/{nodes.length} done</span>
      </div>

      {/* SVG DAG */}
      <div className="overflow-x-auto px-2 py-2">
        <svg viewBox={`0 0 ${svgW} ${SVG_H}`} width="100%" style={{ maxHeight: SVG_H, minWidth: totalW + 40 }}>
          {/* Edges: fan out to / fan in from each column's nodes */}
          {columns.slice(0, -1).map((col, c) =>
            col.flatMap(a => columns[c + 1].map(b => {
              const x1 = pos[a].cxv + NODE_W / 2, y1 = pos[a].cyv
              const x2 = pos[b].cxv - NODE_W / 2, y2 = pos[b].cyv
              return (
                <g key={`${a}-${b}-edge`}>
                  <line x1={x1} y1={y1} x2={x2 - ARROW} y2={y2} stroke="#d5d9e0" strokeWidth={1.5} />
                  <polygon points={`${x2},${y2} ${x2 - ARROW},${y2 - 4} ${x2 - ARROW},${y2 + 4}`} fill="#d5d9e0" />
                </g>
              )
            }))
          )}

          {/* Nodes */}
          {nodes.map((n, i) => {
            const col = STATUS_COLORS[n.status]
            const { x, y, cxv, solo } = pos[i]
            const isAnim = n.status === 'running'
            const shownTools = solo ? (n.tools ?? []).slice(0, 2) : []   // tools only in single lanes (no collision)
            const extraTools = solo ? (n.tools?.length ?? 0) - shownTools.length : 0

            return (
              <g key={n.id}>
                {isAnim && (
                  <rect
                    x={x - 3} y={y - 3} width={NODE_W + 6} height={NODE_H + 6}
                    rx={9} fill="none" stroke={col.stroke} strokeWidth={2} opacity={0.35}
                  >
                    <animate attributeName="opacity" values="0.35;0.7;0.35" dur="1.2s" repeatCount="indefinite" />
                  </rect>
                )}

                <rect
                  x={x} y={y} width={NODE_W} height={NODE_H} rx={7}
                  fill={col.fill} stroke={col.stroke} strokeWidth={isAnim ? 1.5 : 1}
                />

                {/* Label */}
                <text
                  x={cxv} y={y + 19} textAnchor="middle" fontSize={9.5}
                  fill={col.text} fontFamily="Inter,system-ui,sans-serif" fontWeight="600"
                >
                  {n.label.length > 20 ? n.label.slice(0, 20) + '…' : n.label}
                </text>

                {/* LLM call count */}
                {!!n.llmCalls && n.llmCalls > 0 && (
                  <text
                    x={cxv} y={y + 32} textAnchor="middle" fontSize={8}
                    fill={col.text} opacity={0.7} fontFamily="Inter,system-ui,sans-serif"
                  >
                    {n.llmCalls} LLM call{n.llmCalls > 1 ? 's' : ''}
                  </text>
                )}

                {/* Status dot */}
                {n.status !== 'pending' && (
                  <circle cx={x + NODE_W - 10} cy={y + 10} r={4} fill={col.stroke} />
                )}

                {/* Tool chips (single lanes only) */}
                {shownTools.map((t, ti) => {
                  const chipColor = t.error ? '#dc2626' : '#9aa1ac'
                  return (
                    <text
                      key={t.name}
                      x={cxv} y={y + NODE_H + 12 + ti * 11}
                      textAnchor="middle" fontSize={7.5}
                      fill={chipColor} fontFamily="Inter,system-ui,sans-serif" fontWeight="600"
                    >
                      {t.error ? '⚠ ' : ''}{t.name}
                    </text>
                  )
                })}
                {extraTools > 0 && (
                  <text
                    x={cxv} y={y + NODE_H + 12 + shownTools.length * 11}
                    textAnchor="middle" fontSize={7} fill="#9aa1ac" fontFamily="Inter,system-ui,sans-serif"
                  >
                    +{extraTools} more
                  </text>
                )}
              </g>
            )
          })}
        </svg>
      </div>
    </div>
  )
}
