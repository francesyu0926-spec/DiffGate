import type {
  AffectedApi,
  CallPath,
  FullstackImpact,
  GraphNode,
  JobGraph,
  SuspectFunction,
} from '@/api/types'
import { cleanRepoRelativePath } from '@/utils/repoPath'

export type ImpactAccordionStepKind = 'frontend' | 'api' | 'change'

export interface ImpactAccordionStep {
  kind: ImpactAccordionStepKind
  /** @deprecated 展示用 primary + meta */
  title: string
  detail: string
  primary: string
  meta?: string
  relation?: string
  file?: string
  startLine?: number
  endLine?: number
  suspect?: SuspectFunction
}

export interface ImpactAccordionItem {
  key: string
  method: string
  path: string
  fileCount: number
  frontendCount: number
  symbolCount: number
  chainLabels: string[]
  steps: ImpactAccordionStep[]
  apiFile?: string
  apiLine?: number
}

function apiKey(method: string, path: string) {
  return `${(method || 'GET').toUpperCase()} ${path}`
}

function isApiLabel(label: string) {
  return /^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+\//i.test(label)
}

function pathMatch(a: string, b: string) {
  const na = a.replace(/\/+$/, '') || '/'
  const nb = b.replace(/\/+$/, '') || '/'
  return na === nb
}

function shortSymbol(name: string) {
  const parts = name.split('.')
  return parts[parts.length - 1] || name
}

function labelsForRow(row: CallPath) {
  return row.chain_labels?.length ? row.chain_labels : row.chain ?? []
}

function findApiMeta(
  row: CallPath,
  apis: AffectedApi[],
  graph: JobGraph | null,
): { file?: string; line?: number } {
  const hit = apis.find((a) => a.path === row.path && a.method === row.method)
  if (hit?.file && hit.line > 0) {
    return { file: cleanRepoRelativePath(hit.file), line: hit.line }
  }
  const method = (row.method || 'GET').toUpperCase()
  const node = graph?.nodes?.find(
    (n: GraphNode) =>
      n.type === 'api' &&
      n.route === row.path &&
      (n.method || 'GET').toUpperCase() === method,
  )
  if (node?.file && node.line) {
    return { file: cleanRepoRelativePath(node.file), line: node.line }
  }
  return {}
}

function frontendHits(path: string, method: string, fs?: FullstackImpact) {
  if (!fs) return [] as { file: string; line: number }[]
  const m = (method || 'GET').toUpperCase()
  const out: { file: string; line: number }[] = []
  const seen = new Set<string>()
  for (const c of fs.frontend_api_calls ?? []) {
    if (!pathMatch(c.backend_path ?? c.path, path)) continue
    const cm = (c.backend_method || c.method || 'GET').toUpperCase()
    if (cm !== m && c.method?.toUpperCase() !== m) continue
    const key = `${c.file}:${c.line}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push({ file: cleanRepoRelativePath(c.file), line: c.line })
  }
  for (const agg of fs.frontend_api_calls_aggregated ?? []) {
    const idx = (agg.backend_paths ?? []).findIndex((p) => pathMatch(p, path))
    if (idx < 0) continue
    const cm = (agg.backend_methods?.[idx] || 'GET').toUpperCase()
    if (cm !== m) continue
    for (const ln of agg.lines ?? []) {
      const key = `${agg.file}:${ln}`
      if (seen.has(key)) continue
      seen.add(key)
      out.push({ file: cleanRepoRelativePath(agg.file), line: ln })
    }
  }
  for (const c of fs.matched_api_calls ?? []) {
    if (!pathMatch(c.endpoint, path)) continue
    if ((c.method || 'GET').toUpperCase() !== m) continue
    for (const ln of c.lines ?? (c.first_line ? [c.first_line] : [])) {
      const key = `${c.file}:${ln}`
      if (seen.has(key)) continue
      seen.add(key)
      out.push({ file: cleanRepoRelativePath(c.file), line: ln })
    }
  }
  return out
}

function symbolsFromLabels(labels: string[]) {
  const syms: string[] = []
  for (const l of labels) {
    if (!l || isApiLabel(l)) continue
    syms.push(l)
  }
  return syms
}

function pickRootSuspect(labels: string[], suspects: SuspectFunction[]) {
  const syms = symbolsFromLabels(labels)
  for (let i = syms.length - 1; i >= 0; i--) {
    const token = syms[i]!
    const short = shortSymbol(token)
    const hit = suspects.find(
      (s) => s.qualified_name === token || shortSymbol(s.qualified_name) === short,
    )
    if (hit?.file && hit.file !== '—') return hit
  }
  return suspects.find((s) => s.file && s.file !== '—') ?? null
}

function fileCountFromChain(labels: string[], suspects: SuspectFunction[]) {
  const files = new Set<string>()
  for (const s of suspects) {
    if (symbolsFromLabels(labels).some((t) => t === s.qualified_name || shortSymbol(t) === shortSymbol(s.qualified_name))) {
      files.add(cleanRepoRelativePath(s.file))
    }
  }
  return files.size || Math.min(1, symbolsFromLabels(labels).length)
}

function buildSteps(
  row: CallPath,
  meta: { file?: string; line?: number },
  fs: FullstackImpact | undefined,
  suspects: SuspectFunction[],
): ImpactAccordionStep[] {
  const labels = labelsForRow(row)
  const steps: ImpactAccordionStep[] = []
  const fe = frontendHits(row.path, row.method, fs)
  const feShow = fe.slice(0, 3)
  const method = (row.method || 'GET').toUpperCase()
  for (const f of feShow) {
    const base = f.file.split('/').pop() || f.file
    steps.push({
      kind: 'frontend',
      title: `${base} (L${f.line})`,
      primary: base,
      meta: `L${f.line}`,
      relation: `↳ 调用 ${method} ${row.path}`,
      detail: `前端消费方调用 ${method} ${row.path}`,
      file: f.file,
      startLine: f.line,
      endLine: f.line + 8,
    })
  }
  steps.push({
    kind: 'api',
    title: `${method} ${row.path}`,
    primary: `${method} ${row.path}`,
    meta: meta.file && meta.line ? `${meta.file}:L${meta.line}` : undefined,
    relation: '↳ 后端路由入口',
    detail: meta.file && meta.line ? `${meta.file}:L${meta.line}` : '后端路由处理该请求',
    file: meta.file,
    startLine: meta.line,
    endLine: meta.line ? meta.line + 24 : undefined,
  })
  const root = pickRootSuspect(labels, suspects)
  if (root) {
    const filePath = cleanRepoRelativePath(root.file)
    const base = filePath.split('/').pop() || root.file
    const sym = shortSymbol(root.qualified_name)
    steps.push({
      kind: 'change',
      title: `${base} · ${sym}`,
      primary: `${base} · ${sym}`,
      meta:
        root.changed_lines?.length > 0
          ? `变更行 ${root.changed_lines.slice(0, 4).join(', ')}${root.changed_lines.length > 4 ? '…' : ''}`
          : `L${root.start_line}–L${root.end_line}`,
      relation: '↳ 根因符号',
      detail:
        root.changed_lines?.length > 0
          ? `变更行 ${root.changed_lines.slice(0, 6).join(', ')}${root.changed_lines.length > 6 ? '…' : ''}`
          : `L${root.start_line}–L${root.end_line}`,
      file: filePath,
      startLine: root.start_line || root.changed_lines?.[0],
      endLine: root.end_line || root.changed_lines?.[root.changed_lines.length - 1],
      suspect: root,
    })
  } else {
    const tail = symbolsFromLabels(labels).pop()
    if (tail) {
      const sym = shortSymbol(tail)
      steps.push({
        kind: 'change',
        title: sym,
        primary: sym,
        relation: '↳ 变更符号',
        detail: '变更符号位于调用链上游',
      })
    }
  }
  return steps
}

export function buildImpactAccordionItems(
  callPaths: CallPath[],
  apis: AffectedApi[],
  graph: JobGraph | null,
  fullstack: FullstackImpact | undefined,
  suspects: SuspectFunction[],
): ImpactAccordionItem[] {
  const byKey = new Map<string, CallPath & { chain_labels?: string[] }>()
  for (const row of callPaths) {
    const key = apiKey(row.method, row.path)
    const labels = labelsForRow(row)
    const prev = byKey.get(key)
    if (!prev || labels.length > labelsForRow(prev).length) {
      byKey.set(key, { ...row, chain_labels: labels })
    }
  }
  if (!byKey.size && graph?.nodes?.length) {
    for (const n of graph.nodes) {
      if (n.type !== 'api' || !n.route) continue
      const key = apiKey(n.method || 'GET', n.route)
      if (byKey.has(key)) continue
      byKey.set(key, {
        method: (n.method || 'GET').toUpperCase(),
        path: n.route,
        chain: [],
        chain_labels: [],
        layers: 0,
      })
    }
  }
  const items: ImpactAccordionItem[] = []
  for (const row of byKey.values()) {
    const labels = labelsForRow(row)
    const key = apiKey(row.method, row.path)
    const meta = findApiMeta(row, apis, graph)
    const fe = frontendHits(row.path, row.method, fullstack)
    items.push({
      key,
      method: (row.method || 'GET').toUpperCase(),
      path: row.path,
      fileCount: fileCountFromChain(labels, suspects),
      frontendCount: fe.length,
      symbolCount: symbolsFromLabels(labels).length,
      chainLabels: labels,
      steps: buildSteps(row, meta, fullstack, suspects),
      apiFile: meta.file,
      apiLine: meta.line,
    })
  }
  items.sort((a, b) => a.path.localeCompare(b.path) || a.method.localeCompare(b.method))
  return items
}