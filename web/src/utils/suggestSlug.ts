/** 由显示名生成用例集 slug（可再手工微调）。 */
export function suggestSlugFromName(name: string): string {
  const raw = name.trim()
  if (!raw) return ''

  const words = raw.match(/[a-zA-Z][a-zA-Z0-9]*/g)
  if (words && words.length > 0) {
    const base = words.map((w) => w.toLowerCase()).join('-')
    const withSuffix = base.endsWith('-cases') || base.endsWith('cases') ? base : `${base}-cases`
    return withSuffix.replace(/-+/g, '-').slice(0, 128)
  }

  const latin = raw
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/\s+/g, '-')
    .replace(/[^a-z0-9._-]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^[-._]+|[-._]+$/g, '')

  if (latin.length >= 2) {
    return (latin.endsWith('-cases') ? latin : `${latin}-cases`).slice(0, 128)
  }

  const hash = [...raw].reduce((acc, ch) => (acc * 31 + ch.charCodeAt(0)) >>> 0, 0)
  return `suite-${hash.toString(36)}-cases`
}