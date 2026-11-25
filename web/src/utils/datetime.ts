/** API/SQLite timestamps are UTC; append Z when timezone is omitted. */
export function parseApiInstant(iso: string | null | undefined): Date | null {
  if (!iso) return null
  const raw = iso.trim()
  if (!raw) return null
  if (/[zZ]$|[+-]\d{2}:?\d{2}$/.test(raw)) {
    const d = new Date(raw)
    return Number.isNaN(d.getTime()) ? null : d
  }
  const normalized = raw.includes('T') ? raw : raw.replace(' ', 'T')
  const d = new Date(`${normalized}Z`)
  return Number.isNaN(d.getTime()) ? null : d
}

export function formatLocalDateTime(iso: string | null | undefined): string {
  const d = parseApiInstant(iso)
  if (!d) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function formatRelativeTime(iso: string | null | undefined): string {
  const d = parseApiInstant(iso)
  if (!d) return '—'
  const diffMin = Math.max(0, Math.floor((Date.now() - d.getTime()) / 60000))
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin} 分钟前`

  const hours = Math.floor(diffMin / 60)
  if (hours < 24) return `${hours} 小时前`

  const days = Math.floor(hours / 24)
  if (days < 7) return `${days} 天前`

  if (days < 28) return `${Math.max(1, Math.floor(days / 7))} 周前`

  if (days < 365) return `${Math.max(1, Math.floor(days / 30))} 个月前`

  return `${Math.max(1, Math.floor(days / 365))} 年前`
}