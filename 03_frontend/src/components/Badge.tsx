import React from 'react'

// Text colors mirror the aml-* status tokens (single source); bg/border are tints.
const BAND_CFG: Record<string, { bg: string; text: string; border: string }> = {
  CRITICAL: { bg: '#fef2f2', text: '#dc2626', border: '#fecaca' },  // aml-red
  HIGH:     { bg: '#fff7ed', text: '#ea580c', border: '#fed7aa' },
  MEDIUM:   { bg: '#fffbeb', text: '#d97706', border: '#fde68a' },  // aml-amber
  LOW:      { bg: '#f0fdf4', text: '#059669', border: '#bbf7d0' },  // aml-green
}

interface BadgeProps {
  label: string
  color?: string
  small?: boolean
  neutral?: boolean
}

export const Badge: React.FC<BadgeProps> = ({ label, small, neutral }) => {
  const cfg = neutral ? undefined : BAND_CFG[label]
  const style: React.CSSProperties = cfg
    ? { background: cfg.bg, color: cfg.text, borderColor: cfg.border }
    : { background: '#f3f4f6', color: '#6b7280', borderColor: '#e5e7eb' }

  return (
    <span
      className={`inline-flex items-center font-semibold rounded-full border tracking-wide whitespace-nowrap
        ${small ? 'text-2xs px-1.5 py-0.5' : 'text-xs px-2 py-0.5'}`}
      style={style}
    >
      {label}
    </span>
  )
}

export const RiskBadge: React.FC<{ band: string; small?: boolean }> = ({ band, small }) => (
  <Badge label={band} small={small} />
)
