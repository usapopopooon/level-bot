export function formatNumber(n: number): string {
  return n.toLocaleString()
}

export function formatSeconds(total: number): string {
  if (total < 0) total = 0
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  if (hours > 0) return `${hours}h ${minutes}m`
  if (minutes > 0) return `${minutes}m ${seconds}s`
  return `${seconds}s`
}

export function formatHoursDecimal(total: number): number {
  return Math.round((total / 3600) * 100) / 100
}

export function formatDateShort(iso: string): string {
  const d = new Date(iso)
  return `${d.getMonth() + 1}/${d.getDate()}`
}
