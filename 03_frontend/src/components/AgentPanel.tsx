import React, { useRef, useState } from 'react'
import { disposeCase, investigateCase } from '../api'

interface Props {
  caseId: string
}

export const AgentPanel: React.FC<Props> = ({ caseId }) => {
  const [output, setOutput] = useState('')
  const [running, setRunning] = useState(false)
  const [disposition, setDisposition] = useState('SUSPICIOUS')
  const [notes, setNotes] = useState('')
  const [adjudicator, setAdjudicator] = useState('')
  const [disposeMsg, setDisposeMsg] = useState('')
  const termRef = useRef<HTMLDivElement>(null)

  const runInvestigation = async () => {
    setOutput('')
    setRunning(true)
    try {
      const res = await investigateCase(caseId)
      if (!res.body) { setRunning(false); return }
      const reader = res.body.getReader()
      const dec = new TextDecoder()
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = dec.decode(value, { stream: true })
        // handle SSE "data: ..." lines or raw text
        const lines = chunk.split('\n')
        for (const line of lines) {
          const text = line.startsWith('data: ') ? line.slice(6) : line
          if (text && text !== '[DONE]') {
            setOutput(prev => prev + text + (line.startsWith('data: ') ? '\n' : ''))
          }
        }
        if (termRef.current) termRef.current.scrollTop = termRef.current.scrollHeight
      }
    } catch {
      setOutput('[Error: backend not reachable. Start the API server on port 8000.]')
    }
    setRunning(false)
  }

  const handleDispose = async () => {
    try {
      await disposeCase(caseId, { disposition, notes, adjudicator })
      setDisposeMsg(`Case disposed as ${disposition}. Annotation recorded.`)
    } catch {
      setDisposeMsg('[Error: dispose failed — check backend]')
    }
  }

  return (
    <div style={{ marginTop: 20 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
        <h3 style={{ color: '#fff', margin: 0, fontSize: 15 }}>Agent Investigation</h3>
        <button
          onClick={runInvestigation}
          disabled={running}
          style={{
            background: running ? '#444' : '#ff6d00',
            color: '#fff',
            border: 'none',
            borderRadius: 5,
            padding: '6px 16px',
            cursor: running ? 'not-allowed' : 'pointer',
            fontWeight: 600,
            fontSize: 13,
          }}
        >
          {running ? 'Investigating…' : 'Run AI Investigation'}
        </button>
      </div>

      <div
        ref={termRef}
        style={{
          background: '#0a0c14',
          border: '1px solid #2a2d3a',
          borderRadius: 6,
          padding: 16,
          minHeight: 140,
          maxHeight: 320,
          overflowY: 'auto',
          fontFamily: 'monospace',
          fontSize: 13,
          color: '#00e676',
          whiteSpace: 'pre-wrap',
          lineHeight: 1.6,
        }}
      >
        {output || <span style={{ color: '#555' }}>// Click "Run AI Investigation" to start streaming analysis…</span>}
      </div>

      {/* Dispose form */}
      <div style={{ marginTop: 20, background: '#1a1d27', borderRadius: 6, padding: 16 }}>
        <h4 style={{ color: '#fff', margin: '0 0 12px', fontSize: 14 }}>Dispose Case</h4>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' as const, alignItems: 'flex-end' }}>
          <div>
            <label style={labelStyle}>Disposition</label>
            <select
              value={disposition}
              onChange={e => setDisposition(e.target.value)}
              style={inputStyle}
            >
              <option value="SUSPICIOUS">SUSPICIOUS</option>
              <option value="FALSE_POSITIVE">FALSE_POSITIVE</option>
              <option value="NEEDS_MORE_INFO">NEEDS_MORE_INFO</option>
            </select>
          </div>
          <div style={{ flex: 1, minWidth: 160 }}>
            <label style={labelStyle}>Notes</label>
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              rows={2}
              style={{ ...inputStyle, resize: 'vertical' as const, width: '100%' }}
              placeholder="Investigation notes…"
            />
          </div>
          <div>
            <label style={labelStyle}>Adjudicator</label>
            <input
              value={adjudicator}
              onChange={e => setAdjudicator(e.target.value)}
              style={inputStyle}
              placeholder="analyst_id"
            />
          </div>
          <button
            onClick={handleDispose}
            style={{
              background: '#00c853',
              color: '#fff',
              border: 'none',
              borderRadius: 5,
              padding: '8px 18px',
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: 13,
              height: 36,
            }}
          >
            Submit
          </button>
        </div>
        {disposeMsg && (
          <div style={{ marginTop: 10, color: '#00c853', fontSize: 13 }}>{disposeMsg}</div>
        )}
      </div>
    </div>
  )
}

const labelStyle: React.CSSProperties = {
  display: 'block',
  color: '#888',
  fontSize: 11,
  marginBottom: 4,
}

const inputStyle: React.CSSProperties = {
  background: '#0f1117',
  border: '1px solid #2a2d3a',
  borderRadius: 4,
  color: '#fff',
  padding: '6px 10px',
  fontSize: 13,
}
