export const businessLabel = (value: string) => value.replace(/^DEMO-(CORPUS-)?/i, '').replace(/[_-]/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
export const presentationText = (value: string) => value.replace(/\bsynthetic\s+/gi, '').replace(/\bdemo\s+/gi, '').replace(/\bdemo-/gi, '').trim()
export const contextDate = (value?: string | null) => {
  if (!value) return 'Not available'
  // Backend timestamps without an offset represent UTC, not browser local time.
  const timestamp = /[T ]\d{2}:\d{2}/.test(value) && !/(Z|[+-]\d{2}:?\d{2})$/i.test(value) ? `${value.replace(' ', 'T')}Z` : value
  return new Date(timestamp).toLocaleString('en-GB', {timeZone: 'UTC', year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit'}) + ' UTC'
}
