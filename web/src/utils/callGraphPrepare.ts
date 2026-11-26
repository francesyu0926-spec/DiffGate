import type { GraphEdge, GraphNode, JobGraph } from '@/api/types'
import { cleanRepoRelativePath } from '@/utils/repoPath'

export function fileKey(file: string) {
  return cleanRepoRelativePath(file)
}

export function fileBasename(file: string) {
  const parts = fileKey(file).split('/')
  return parts[parts.length - 1] || file
}

export function buildAdj(edges: GraphEdge[]) {
  const fwd = new Map<string, Set<string>>()
  const back = new Map<string, Set<string>>()
  for (const e of edges) {
    if (!fwd.has(e.source)) fwd.set(e.source, new Set())
    if (!back.has(e.target)) back.set(e.target, new Set())
    fwd.get(e.source)!.add(e.target)
    back.get(e.target)!.add(e.source)
  }
  return { fwd, back }
}

export function nodesOnPathsToApi(
  nodes: GraphNode[],
  edges: GraphEdge[],
  changedSet: Set<string>,
) {
  const ids = new Set(nodes.map((n) => n.id))
  const apiIds = new Set(nodes.filter((n) => n.type === 'api').map((n) => n.id))
  if (!apiIds.size) return ids

  const { fwd } = buildAdj(edges)
  const canReachApi = new Map<string, boolean>()

  function dfsApi(node: string, visiting: Set<string>): boolean {
    if (canReachApi.has(node)) return canReachApi.get(node)!
    if (apiIds.has(node)) {
      canReachApi.set(node, true)
      return true
    }
    if (visiting.has(node)) return false
    visiting.add(node)
    let ok = false
    for (const nxt of fwd.get(node) ?? []) {
      if (ids.has(nxt) && dfsApi(nxt, visiting)) ok = true
    }
    visiting.delete(node)
    canReachApi.set(node, ok)
    return ok
  }

  for (const id of ids) dfsApi(id, new Set())

  const reachableFromChanged = new Set<string>()
  const seeds = [...changedSet].filter((id) => ids.has(id))
  if (!seeds.length) seeds.push(...nodes.filter((n) => n.type === 'changed').map((n) => n.id))

  for (const seed of seeds) {
    const q = [seed]
    const seen = new Set<string>()
    while (q.length) {
      const cur = q.pop()!
      if (seen.has(cur)) continue
      seen.add(cur)
      reachableFromChanged.add(cur)
      for (const nxt of fwd.get(cur) ?? []) {
        if (ids.has(nxt)) q.push(nxt)
      }
    }
  }

  const keep = new Set<string>()
  for (const id of ids) {
    if (canReachApi.get(id) && (reachableFromChanged.has(id) || apiIds.has(id))) {
      keep.add(id)
    }
  }
  for (const n of nodes) {
    if (n.type !== 'frontend') continue
    for (const e of edges) {
      if (e.source === n.id && keep.has(e.target)) keep.add(n.id)
    }
  }
  if (!keep.size) return ids
  return keep
}

export function compactGraphPayload(nodes: GraphNode[], edges: GraphEdge[]) {
  const deg = new Map<string, number>()
  for (const e of edges) {
    deg.set(e.source, (deg.get(e.source) ?? 0) + 1)
    deg.set(e.target, (deg.get(e.target) ?? 0) + 1)
  }
  const apiIds = new Set(nodes.filter((n) => n.type === 'api').map((n) => n.id))
  const keep = new Set<string>(apiIds)
  for (const n of nodes) {
    if (n.type === 'changed') keep.add(n.id)
    if ((deg.get(n.id) ?? 0) <= 2) keep.add(n.id)
  }
  const bridge = new Set<string>()
  for (const e of edges) {
    if (keep.has(e.source) && keep.has(e.target)) continue
    if (keep.has(e.source) || keep.has(e.target)) {
      bridge.add(e.source)
      bridge.add(e.target)
    }
  }
  for (const id of bridge) keep.add(id)
  const fNodes = nodes.filter((n) => keep.has(n.id))
  const fIds = new Set(fNodes.map((n) => n.id))
  const fEdges = edges.filter((e) => fIds.has(e.source) && fIds.has(e.target))
  return { nodes: fNodes, edges: fEdges }
}

export function aggregateGraphByFile(
  nodes: GraphNode[],
  edges: GraphEdge[],
  expanded: Set<string>,
  enabled: boolean,
) {
  if (!enabled) return { nodes, edges }

  const byFile = new Map<string, GraphNode[]>()
  for (const n of nodes) {
    if (n.type === 'api' || !n.file) continue
    const fk = fileKey(n.file)
    if (!byFile.has(fk)) byFile.set(fk, [])
    byFile.get(fk)!.push(n)
  }

  const idToCluster = new Map<string, string>()
  const keepIndividual = new Set<string>()
  const clusterNodes: GraphNode[] = []

  for (const n of nodes) {
    if (n.type === 'api' || !n.file) {
      keepIndividual.add(n.id)
      continue
    }
    const fk = fileKey(n.file)
    const group = byFile.get(fk) ?? []
    if (group.length <= 1 || expanded.has(fk)) {
      keepIndividual.add(n.id)
    } else {
      idToCluster.set(n.id, `file:${fk}`)
    }
  }

  for (const [fk, group] of byFile) {
    if (group.length <= 1 || expanded.has(fk)) continue
    const clusterId = `file:${fk}`
    if (clusterNodes.some((c) => c.id === clusterId)) continue
    const changedN = group.filter((g) => g.type === 'changed').length
    const suffix = changedN > 0 ? `${changedN} 处变更` : `${group.length} 个函数`
    clusterNodes.push({
      id: clusterId,
      label: `${fileBasename(fk)} · ${suffix}`,
      type: 'changed',
      file: fk,
      line: Math.min(...group.map((g) => g.line ?? 1)),
    })
  }

  const outNodes = [...nodes.filter((n) => keepIndividual.has(n.id)), ...clusterNodes]
  const remap = (id: string) => idToCluster.get(id) ?? id
  const edgeKey = new Set<string>()
  const outEdges: GraphEdge[] = []
  for (const e of edges) {
    const s = remap(e.source)
    const t = remap(e.target)
    if (s === t) continue
    const key = `${s}\0${t}`
    if (edgeKey.has(key)) continue
    edgeKey.add(key)
    outEdges.push({ source: s, target: t })
  }
  return { nodes: outNodes, edges: outEdges }
}

export type PrepareCallGraphOptions = {
  filterApiOnly: boolean
  compactLayers: boolean
  aggregateByFile: boolean
  expandedFiles: Set<string>
  changedIds: string[]
}

export function prepareCallGraphDisplay(
  raw: JobGraph | null,
  opts: PrepareCallGraphOptions,
): { nodes: GraphNode[]; edges: GraphEdge[] } | null {
  if (!raw?.nodes?.length) return null
  let nodes = raw.nodes.map((n) => (n.file ? { ...n, file: fileKey(n.file) } : n))
  let edges = raw.edges
  const changedSet = new Set(opts.changedIds)
  if (opts.filterApiOnly) {
    const keep = nodesOnPathsToApi(nodes, edges, changedSet)
    nodes = nodes.filter((n) => keep.has(n.id))
    const ids = new Set(nodes.map((n) => n.id))
    edges = edges.filter((e) => ids.has(e.source) && ids.has(e.target))
  }
  if (opts.compactLayers) {
    const compact = compactGraphPayload(nodes, edges)
    nodes = compact.nodes
    edges = compact.edges
  }
  const aggregated = aggregateGraphByFile(nodes, edges, opts.expandedFiles, opts.aggregateByFile)
  return pruneOrphanSymbols(aggregated.nodes, aggregated.edges)
}

/** 去掉在子图中无边相连的上游 symbol，避免拓扑里出现“飘着的长文本” */
export function pruneOrphanSymbols(nodes: GraphNode[], edges: GraphEdge[]) {
  if (!nodes.length) return { nodes, edges }
  const degree = new Map<string, number>()
  for (const e of edges) {
    degree.set(e.source, (degree.get(e.source) ?? 0) + 1)
    degree.set(e.target, (degree.get(e.target) ?? 0) + 1)
  }
  const keep = new Set(
    nodes
      .filter((n) => {
        if (n.type !== 'symbol') return true
        if (n.id.startsWith('file:')) return true
        return (degree.get(n.id) ?? 0) > 0
      })
      .map((n) => n.id),
  )
  return {
    nodes: nodes.filter((n) => keep.has(n.id)),
    edges: edges.filter((e) => keep.has(e.source) && keep.has(e.target)),
  }
}

export function buildImpactSummary(raw: JobGraph | null, changedIds: string[]) {
  if (!raw?.nodes?.length) return null
  const fileCounts = new Map<string, number>()
  for (const n of raw.nodes) {
    if (n.type === 'api' || !n.file) continue
    const fk = fileKey(n.file)
    fileCounts.set(fk, (fileCounts.get(fk) ?? 0) + 1)
  }
  const fileNames = [...fileCounts.keys()].map(fileBasename)
  const sampleFiles = fileNames.slice(0, 3).join('、')
  const totalSymbols = changedIds.length || raw.nodes.filter((n) => n.type === 'changed').length
  const apis = raw.nodes.filter((n) => n.type === 'api')
  const apiList = apis.map((a) => ({
    method: (a.method || 'GET').toUpperCase(),
    route: a.route || a.label || '/',
    key: a.id,
  }))
  const fe = raw.nodes.filter((n) => n.type === 'frontend')
  return {
    fileCount: fileCounts.size || 0,
    sampleFiles,
    fileCountLabel: fileCounts.size > 0 ? `${fileCounts.size} 个文件` : '若干文件',
    totalSymbols,
    apiCount: apis.length,
    apiList,
    feCount: fe.length,
    hasApis: apis.length > 0,
  }
}

export function graphLayerIndex(n: GraphNode): number {
  if (n.id.startsWith('file:')) return 1
  if (n.type === 'frontend') return 0
  if (n.type === 'changed') return 1
  if (n.type === 'symbol') return 2
  return 3
}

export const LAYER_LABELS = ['前端调用方', '变更符号', '上游方法', '受影响 API']

export function highlightNeighborhood(
  seed: string,
  edges: GraphEdge[],
  nodeIds: Set<string>,
): Set<string> {
  const { fwd, back } = buildAdj(edges)
  const out = new Set<string>([seed])
  const up = [seed]
  while (up.length) {
    const cur = up.pop()!
    for (const p of back.get(cur) ?? []) {
      if (!nodeIds.has(p) || out.has(p)) continue
      out.add(p)
      up.push(p)
    }
  }
  const down = [seed]
  while (down.length) {
    const cur = down.pop()!
    for (const nxt of fwd.get(cur) ?? []) {
      if (!nodeIds.has(nxt) || out.has(nxt)) continue
      out.add(nxt)
      down.push(nxt)
    }
  }
  return out
}