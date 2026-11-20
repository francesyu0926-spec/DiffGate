export function parseFullNameFromCloneUrl(url: string): string | null {
  const trimmed = url.trim()
  if (!trimmed) return null
  try {
    if (trimmed.startsWith('git@')) {
      const match = trimmed.match(/^git@[^:]+:(.+?)(?:\.git)?$/i)
      return match?.[1] ?? null
    }
    const u = new URL(trimmed)
    const path = u.pathname.replace(/^\//, '').replace(/\.git$/i, '')
    return path || null
  } catch {
    return null
  }
}