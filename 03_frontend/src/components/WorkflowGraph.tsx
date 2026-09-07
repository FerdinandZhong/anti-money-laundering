import { GitBranch } from 'lucide-react'

export interface WorkflowNode {
  id: string
  label: string
  status: 'pending' | 'running' | 'completed' | 'skip' | 'error'
  llmCalls?: number
  tools?: { name: string; error?: boolean }[]
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
const NODE_H = 50
const H_GAP  = 34
const ARROW  = 8
const SVG_H  = 120

/** Presentational live DAG for an agent pipeline — ported from the Agent Studio
 *  WorkflowGraph reference, recolored to the app's light theme. */
export const WorkflowGraph: React.FC<Props> = ({ nodes, running }) => {
  if (nodes.length === 0) return null

  const idxById: Record<string, number> = {}
  nodes.forEach((n, i) => { idxById[n.id] = i })

  const totalW = nodes.length * NODE_W + (nodes.length - 1) * H_GAP
  const svgW   = totalW + 40
  const cx = (i: number) => 20 + i * (NODE_W + H_GAP) + NODE_W / 2
  const cy = SVG_H / 2 - 8

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
          {/* Edges */}
          {nodes.slice(0, -1).map((n, i) => {
            const x1 = cx(i) + NODE_W / 2
            const x2 = cx(i + 1) - NODE_W / 2
            return (
              <g key={`${n.id}-edge`}>
                <line x1={x1} y1={cy} x2={x2 - ARROW} y2={cy} stroke="#d5d9e0" strokeWidth={1.5} />
                <polygon points={`${x2},${cy} ${x2 - ARROW},${cy - 4} ${x2 - ARROW},${cy + 4}`} fill="#d5d9e0" />
              </g>
            )
          })}

          {/* Nodes */}
          {nodes.map((n, i) => {
            const col = STATUS_COLORS[n.status]
            const x = cx(i) - NODE_W / 2
            const y = cy - NODE_H / 2
            const isAnim = n.status === 'running'
            const shownTools = (n.tools ?? []).slice(0, 2)
            const extraTools = (n.tools?.length ?? 0) - shownTools.length

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
                  x={cx(i)} y={y + 20} textAnchor="middle" fontSize={9.5}
                  fill={col.text} fontFamily="Inter,system-ui,sans-serif" fontWeight="600"
                >
                  {n.label.length > 20 ? n.label.slice(0, 20) + '…' : n.label}
                </text>

                {/* LLM call count */}
                {!!n.llmCalls && n.llmCalls > 0 && (
                  <text
                    x={cx(i)} y={y + 34} textAnchor="middle" fontSize={8}
                    fill={col.text} opacity={0.7} fontFamily="Inter,system-ui,sans-serif"
                  >
                    {n.llmCalls} LLM call{n.llmCalls > 1 ? 's' : ''}
                  </text>
                )}

                {/* Status dot */}
                {n.status !== 'pending' && (
                  <circle cx={x + NODE_W - 10} cy={y + 10} r={4} fill={col.stroke} />
                )}

                {/* Tool chips */}
                {shownTools.map((t, ti) => {
                  const chipColor = t.error ? '#dc2626' : '#9aa1ac'
                  return (
                    <text
                      key={t.name}
                      x={cx(i)} y={y + NODE_H + 12 + ti * 11}
                      textAnchor="middle" fontSize={7.5}
                      fill={chipColor} fontFamily="Inter,system-ui,sans-serif" fontWeight="600"
                    >
                      {t.error ? '⚠ ' : ''}{t.name}
                    </text>
                  )
                })}
                {extraTools > 0 && (
                  <text
                    x={cx(i)} y={y + NODE_H + 12 + shownTools.length * 11}
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
