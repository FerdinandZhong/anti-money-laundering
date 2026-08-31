import React from 'react'

const BAND_COLORS: Record<string, string> = {
  CRITICAL: '#f44336',
  HIGH: '#ff6d00',
  MEDIUM: '#ff9800',
  LOW: '#00c853',
}

interface BadgeProps {
  label: string
  color?: string
  small?: boolean
}

export const Badge: React.FC<BadgeProps> = ({ label, color, small }) => {
  const bg = color ?? BAND_COLORS[label] ?? '#555'
  return (
    <span style={{
      background: bg,
      color: '#fff',
      borderRadius: 4,
      padding: small ? '1px 6px' : '2px 10px',
      fontSize: small ? 10 : 12,
      fontWeight: 700,
      letterSpacing: 0.5,
      whiteSpace: 'nowrap',
    }}>
      {label}
    </span>
  )
}

export const RiskBadge: React.FC<{ band: string; small?: boolean }> = ({ band, small }) => (
  <Badge label={band} color={BAND_COLORS[band]} small={small} />
)
