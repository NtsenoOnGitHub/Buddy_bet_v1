/** Format an ISO 8601 datetime string for display. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Intl.DateTimeFormat('en-ZA', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZoneName: 'short',
  }).format(new Date(iso))
}

/** Relative time: "2 hours ago", "in 3 days", etc. */
export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return '—'
  const diff = new Date(iso).getTime() - Date.now()
  const abs = Math.abs(diff)
  const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

  if (abs < 60_000)    return rtf.format(Math.round(diff / 1_000), 'second')
  if (abs < 3_600_000) return rtf.format(Math.round(diff / 60_000), 'minute')
  if (abs < 86_400_000) return rtf.format(Math.round(diff / 3_600_000), 'hour')
  return rtf.format(Math.round(diff / 86_400_000), 'day')
}

/**
 * How long a bet has been stuck pending: "2h 34m", "3d 1h", "45m".
 * Returns an empty string if the timestamp is missing or in the future.
 */
export function formatPendingAge(iso: string | null | undefined): string {
  if (!iso) return ''
  const ms = Date.now() - new Date(iso).getTime()
  if (ms <= 0) return ''
  const totalMins  = Math.floor(ms / 60_000)
  const totalHours = Math.floor(totalMins / 60)
  const totalDays  = Math.floor(totalHours / 24)
  if (totalDays > 0)  return `${totalDays}d ${totalHours % 24}h`
  if (totalHours > 0) return `${totalHours}h ${totalMins % 60}m`
  return `${totalMins}m`
}
