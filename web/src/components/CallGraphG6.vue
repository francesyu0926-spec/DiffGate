<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Graph, type IElementEvent } from '@antv/g6'
import type { GraphNode, GraphNodeType, JobGraph } from '@/api/types'
import { cleanRepoRelativePath } from '@/utils/repoPath'

export interface GraphNodePick {
  id: string
  label: string
  type: GraphNodeType
  file?: string
  line?: number
  end_line?: number
  method?: string | null
  route?: string | null
  calleeHints?: string[]
}

const props = withDefaults(
  defineProps<{
    data: JobGraph | null
    changedIds?: string[]
    emptyHint?: string
    emptyTitle?: string
    emptyDesc?: string
    panelTitle?: string
    /** 任务分析中：空态显示加载而非静态占位 */
    processing?: boolean
  }>(),
  {
    changedIds: () => [],
    emptyHint: '暂无调用链子图（任务完成后生成）',
    emptyTitle: '暂无调用链子图',
    emptyDesc: '任务完成后生成变更影响拓扑',
    panelTitle: '变更影响拓扑',
    processing: false,
  },
)

const emit = defineEmits<{ nodePick: [GraphNodePick] }>()

const filterApiOnly = ref(true)
const compactLayers = ref(false)
const aggregateByFile = ref(true)
const expandedFiles = ref<Set<string>>(new Set())
const selectedId = ref<string | null>(null)

const hasNodes = computed(() => Boolean(props.data?.nodes?.length))

const containerRef = ref<HTMLDivElement | null>(null)
let graph: Graph | null = null

const TYPE_COLORS: Record<string, string> = {
  api: 'rgba(242, 139, 130, 0.22)',
  changed: 'rgba(253, 214, 99, 0.2)',
  symbol: 'rgba(138, 180, 248, 0.16)',
  frontend: 'rgba(129, 201, 149, 0.2)',
}

const TYPE_STROKES: Record<string, string> = {
  api: 'rgba(255, 158, 148, 0.75)',
  changed: 'rgba(255, 224, 130, 0.7)',
  symbol: 'rgba(174, 203, 250, 0.65)',
  frontend: 'rgba(168, 218, 181, 0.7)',
}

const TYPE_LABEL_COLORS: Record<string, string> = {
  api: '#ffc9c4',
  changed: '#ffe9a8',
  symbol: '#c5d9ff',
  frontend: '#b8e6c8',
}

const NODE_SIZE: [number, number] = [272, 68]
const API_NODE_SIZE: [number, number] = [308, 66]
const FILE_CLUSTER_SIZE: [number, number] = [312, 68]

const EDGE_DIM = 'rgba(148, 163, 184, 0.34)'
const EDGE_ACTIVE = 'rgba(174, 203, 250, 0.78)'

function fileKey(file: string) {
  return cleanRepoRelativePath(file)
}

function fileBasename(file: string) {
  const parts = fileKey(file).split('/')
  return parts[parts.length - 1] || file
}
const FIT_PADDING = 12
const MAX_FIT_ZOOM = 1.35
const MIN_FIT_ZOOM = 0.35
let fitTimer: number | undefined

function pickLayout(nodes: GraphNode[], _edges: { source: string; target: string }[], _apiFilter: boolean) {
  const n = nodes.length
  const ranksep = Math.min(140, 72 + Math.floor(n * 2.2))
  const nodesep = Math.min(56, 32 + Math.floor(n * 0.45))
  return {
    type: 'dagre',
    rankdir: 'LR',
    nodesep,
    ranksep,
    preventOverlap: true,
    align: 'UL',
  }
}

function nodeSize(d: { data?: { kind?: string } }): [number, number] {
  const kind = d.data?.kind
  if (kind === 'api') return API_NODE_SIZE
  if (kind === 'file-cluster') return FILE_CLUSTER_SIZE
  return NODE_SIZE
}

function aggregateGraphByFile(
  nodes: GraphNode[],
  edges: { source: string; target: string }[],
  expanded: Set<string>,
) {
  if (!aggregateByFile.value) return { nodes, edges }

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
  const outEdges: { source: string; target: string }[] = []
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

function buildAdj(edges: { source: string; target: string }[]) {
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

function nodesOnPathsToApi(
  nodes: GraphNode[],
  edges: { source: string; target: string }[],
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

function compactGraphPayload(
  nodes: GraphNode[],
  edges: { source: string; target: string }[],
) {
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

const displayData = computed(() => {
  const raw = props.data
  if (!raw?.nodes?.length) return null
  let nodes = raw.nodes.map((n) => (n.file ? { ...n, file: fileKey(n.file) } : n))
  let edges = raw.edges
  const changedSet = new Set(props.changedIds)
  if (filterApiOnly.value) {
    const keep = nodesOnPathsToApi(nodes, edges, changedSet)
    nodes = nodes.filter((n) => keep.has(n.id))
    const ids = new Set(nodes.map((n) => n.id))
    edges = edges.filter((e) => ids.has(e.source) && ids.has(e.target))
  }
  if (compactLayers.value) {
    const compact = compactGraphPayload(nodes, edges)
    nodes = compact.nodes
    edges = compact.edges
  }
  const aggregated = aggregateGraphByFile(nodes, edges, expandedFiles.value)
  return { nodes: aggregated.nodes, edges: aggregated.edges }
})

const graphHasRenderable = computed(() => Boolean(displayData.value?.nodes?.length))

/** 画布高度随节点规模收缩，避免「结论区下方一大块空画布」 */
const graphCanvasHeight = computed(() => {
  const n = displayData.value?.nodes.length ?? 0
  if (n <= 2) return 220
  if (n <= 4) return 260
  if (n <= 8) return 300
  if (n <= 14) return 360
  if (n <= 22) return 420
  return 480
})

const impactSummary = computed(() => {
  const raw = props.data
  if (!raw?.nodes?.length) return null
  const fileCounts = new Map<string, number>()
  for (const n of raw.nodes) {
    if (n.type === 'api' || !n.file) continue
    const fk = fileKey(n.file)
    fileCounts.set(fk, (fileCounts.get(fk) ?? 0) + 1)
  }
  const fileNames = [...fileCounts.keys()].map(fileBasename)
  const sampleFiles = fileNames.slice(0, 3).join('、')
  const totalSymbols =
    props.changedIds.length || raw.nodes.filter((n) => n.type === 'changed').length
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
})

function nodeKindGlyph(kind?: string) {
  if (kind === 'frontend') return '⬡'
  if (kind === 'api') return '◈'
  if (kind === 'changed' || kind === 'file-cluster') return '◎'
  return '○'
}

function nodeTitle(d: {
  data?: {
    label?: string
    kind?: string
    route?: string | null
    method?: string | null
  }
}) {
  const kind = d.data?.kind
  if (kind === 'file-cluster') {
    return d.data?.label ?? '模块'
  }
  if (kind === 'api') {
    const method = (d.data?.method || 'GET').toUpperCase()
    return `${method} ${d.data?.route || '/'}`
  }
  const label = d.data?.label ?? ''
  return label.includes('(') ? label : `${label}()`
}

function nodeSubtitle(d: {
  data?: { kind?: string; file?: string; line?: number; end_line?: number }
}) {
  const kind = d.data?.kind
  if (kind === 'file-cluster') {
    return '点击展开文件内函数'
  }
  const file = d.data?.file
  if (!file) return ''
  const start = d.data?.line
  const end = d.data?.end_line
  if (start && end) return `${file} : L${start}-L${end}`
  if (start) return `${file} : L${start}`
  return file
}

function nodeLabelText(d: {
  data?: {
    label?: string
    kind?: string
    route?: string | null
    method?: string | null
    file?: string
    line?: number
    end_line?: number
  }
}) {
  const kind = d.data?.kind
  const title = nodeTitle(d)
  const sub = nodeSubtitle(d)
  const glyph = nodeKindGlyph(kind)
  return sub ? `${glyph} ${title}\n${sub}` : `${glyph} ${title}`
}

function resizeGraphCanvas() {
  if (!graph || !containerRef.value) return
  const w = containerRef.value.clientWidth
  const h = containerRef.value.clientHeight
  if (w > 0 && h > 0 && typeof graph.resize === 'function') {
    graph.resize(w, h)
  }
}

async function focusGraphContent() {
  if (!graph) return
  resizeGraphCanvas()
  const nodeCount = displayData.value?.nodes.length ?? 0
  if (nodeCount <= 1) {
    await graph.zoomTo(1)
    return
  }
  try {
    await graph.fitView()
  } catch {
    /* ignore */
  }
  let zoom = typeof graph.getZoom === 'function' ? graph.getZoom() : 1
  if (zoom > MAX_FIT_ZOOM) {
    await graph.zoomTo(MAX_FIT_ZOOM)
    zoom = MAX_FIT_ZOOM
  }
  if (nodeCount <= 12 && zoom < 0.72) {
    await graph.zoomTo(Math.min(MAX_FIT_ZOOM, 0.88))
  }
  try {
    await graph.fitCenter()
  } catch {
    /* ignore */
  }
}

function scheduleFitView() {
  if (fitTimer) window.clearTimeout(fitTimer)
  fitTimer = window.setTimeout(() => {
    void focusGraphContent()
  }, 320)
}

function resolvePickNode(id: string): GraphNode | null {
  if (id.startsWith('file:')) {
    const fk = id.slice(5)
    const raw = props.data?.nodes ?? []
    const member =
      raw.find((n) => n.file && fileKey(n.file) === fk && n.type === 'changed') ??
      raw.find((n) => n.file && fileKey(n.file) === fk)
    return member ?? null
  }
  return displayData.value?.nodes.find((n) => n.id === id) ?? null
}

function pickNode(id: string) {
  const src = displayData.value
  if (!src) return
  const node = resolvePickNode(id)
  if (!node) return
  const fwd = buildAdj(src.edges).fwd
  const calleeHints = [...(fwd.get(id) ?? [])]
  emit('nodePick', {
    id: node.id,
    label: node.label,
    type: node.type,
    file: node.file,
    line: node.line,
    end_line: node.end_line,
    method: node.method,
    route: node.route,
    calleeHints,
  })
}

function nodeIdFromEvent(event: unknown): string | null {
  if (!graph) return null
  const evt = event as IElementEvent
  const nodeIds = new Set(displayData.value?.nodes.map((n) => n.id) ?? [])
  const known = (id?: string) => {
    if (!id) return null
    if (nodeIds.has(id)) return id
    try {
      graph!.getNodeData(id)
      return id
    } catch {
      return null
    }
  }
  if (evt.targetType === 'node') {
    const hit = known(evt.target?.id)
    if (hit) return hit
  }
  let cur = evt.originalTarget as { id?: string; parent?: { id?: string; parent?: unknown } } | undefined
  for (let depth = 0; depth < 14 && cur; depth += 1) {
    const hit = known(cur.id)
    if (hit) return hit
    cur = cur.parent as typeof cur
  }
  return null
}

function bindGraphEvents() {
  if (!graph) return
  graph.on('node:click', (event) => {
    const id = nodeIdFromEvent(event)
    if (!id) return
    if (id.startsWith('file:')) {
      const fk = id.slice(5)
      const next = new Set(expandedFiles.value)
      if (next.has(fk)) next.delete(fk)
      else next.add(fk)
      expandedFiles.value = next
      selectedId.value = null
      renderGraph()
      return
    }
    pickNode(id)
    selectedId.value = id
    const ids = displayData.value?.nodes.map((n) => n.id) ?? []
    const state: Record<string, string | string[]> = {}
    for (const nodeId of ids) {
      state[nodeId] = nodeId === id ? 'selected' : []
    }
    void graph?.setElementState(state).catch(() => undefined)
  })
}

function renderGraph() {
  if (!containerRef.value) return
  if (!displayData.value?.nodes?.length) {
    graph?.destroy()
    graph = null
    return
  }

  graph?.destroy()
  graph = new Graph({
    container: containerRef.value,
    padding: FIT_PADDING,
    data: {
      nodes: displayData.value.nodes.map((n) => ({
        id: n.id,
        data: {
          label: n.label,
          kind: n.id.startsWith('file:') ? 'file-cluster' : n.type,
          file: n.file,
          line: n.line,
          end_line: n.end_line,
          route: n.route,
          method: n.method,
        },
      })),
      edges: displayData.value.edges.map((e, idx) => ({
        id: `e-${idx}`,
        source: e.source,
        target: e.target,
      })),
    },
    layout: pickLayout(displayData.value.nodes, displayData.value.edges, filterApiOnly.value),
    node: {
      type: 'rect',
      style: {
        size: (d: { data?: { kind?: string } }) => nodeSize(d),
        radius: 10,
        port: true,
        ports: [{ placement: 'left' }, { placement: 'right' }],
        labelText: (d: { data?: { label?: string; kind?: string } }) => nodeLabelText(d),
        labelFontSize: 12,
        labelLineHeight: 17,
        labelFontFamily: 'ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif',
        labelFill: (d: { data?: { kind?: string } }) =>
          TYPE_LABEL_COLORS[d.data?.kind ?? 'symbol'] ?? '#e8eaed',
        labelPlacement: 'center',
        labelWordWrap: true,
        labelMaxWidth: (d: { data?: { kind?: string } }) => {
          const kind = d.data?.kind
          if (kind === 'api') return 278
          if (kind === 'file-cluster') return 286
          return 238
        },
        labelMaxLines: 3,
        fill: (d: { data?: { kind?: string } }) => {
          const kind = d.data?.kind ?? 'symbol'
          if (kind === 'file-cluster') return 'rgba(253, 214, 99, 0.24)'
          return TYPE_COLORS[kind] ?? TYPE_COLORS.symbol
        },
        stroke: (d: { data?: { kind?: string } }) => {
          const kind = d.data?.kind ?? 'symbol'
          if (kind === 'file-cluster') return TYPE_STROKES.changed
          return TYPE_STROKES[kind] ?? TYPE_STROKES.symbol
        },
        lineWidth: (d: { data?: { kind?: string } }) => {
          const kind = d.data?.kind
          if (kind === 'api') return 1.5
          if (kind === 'file-cluster') return 1.5
          return 1.25
        },
        shadowBlur: 0,
        shadowColor: 'transparent',
        opacity: 1,
      },
      state: {
        active: {
          opacity: 1,
          shadowBlur: 14,
          shadowColor: 'rgba(138, 180, 248, 0.38)',
          lineWidth: 2,
        },
        inactive: { opacity: 0.28, fill: 'rgba(26, 29, 33, 0.45)' },
        selected: {
          stroke: '#ffffff',
          lineWidth: 2.5,
          opacity: 1,
          shadowBlur: 18,
          shadowColor: 'rgba(255, 255, 255, 0.22)',
        },
      },
    },
    edge: {
      type: 'cubic-horizontal',
      style: {
        stroke: EDGE_DIM,
        lineWidth: 1.35,
        endArrow: true,
        endArrowSize: 7,
        curveOffset: 22,
        curvePosition: 0.5,
        opacity: 0.88,
      },
      state: {
        active: { stroke: EDGE_ACTIVE, lineWidth: 1.85, opacity: 0.95 },
        inactive: { stroke: EDGE_DIM, opacity: 0.1, lineWidth: 1 },
      },
    },
    behaviors: [
      'drag-canvas',
      { type: 'zoom-canvas', maxZoom: MAX_FIT_ZOOM, minZoom: MIN_FIT_ZOOM },
      {
        type: 'hover-activate',
        degree: 6,
        direction: 'both',
        state: 'active',
        inactiveState: 'inactive',
      },
    ],
  })

  graph.render()
  bindGraphEvents()
  graph.on?.('afterlayout', () => {
    scheduleFitView()
  })
  void nextTick(() => {
    resizeGraphCanvas()
    scheduleFitView()
  })
}

function fitView() {
  scheduleFitView()
}

function resetZoom() {
  void graph?.zoomTo(1)
  scheduleFitView()
}

watch(
  () => [
    displayData.value,
    filterApiOnly.value,
    compactLayers.value,
    aggregateByFile.value,
    expandedFiles.value,
  ],
  () => renderGraph(),
  { deep: true },
)

watch(aggregateByFile, (on) => {
  if (on) expandedFiles.value = new Set()
})

watch(graphCanvasHeight, () => {
  void nextTick(() => {
    resizeGraphCanvas()
    scheduleFitView()
  })
})

onMounted(renderGraph)
onBeforeUnmount(() => {
  if (fitTimer) window.clearTimeout(fitTimer)
  graph?.destroy()
  graph = null
})
</script>

<template>
  <div
    class="graph-wrap"
    :class="[
      hasNodes ? 'graph-wrap--filled' : 'graph-wrap--empty',
      processing && !hasNodes && 'graph-wrap--processing',
    ]"
  >
    <div v-if="!hasNodes" class="empty">
      <div class="empty-icon" :class="{ 'empty-icon--spin': processing }" aria-hidden="true">
        <span
          class="mdi empty-icon__glyph"
          :class="processing ? 'mdi-loading' : 'mdi-source-branch'"
        />
      </div>
      <p class="empty-title">{{ emptyTitle }}</p>
      <p class="empty-desc">{{ emptyDesc || emptyHint }}</p>
    </div>
    <div v-show="hasNodes" class="graph-stage">
      <header class="graph-headbar">
        <h3 class="graph-headbar__title">{{ panelTitle }}</h3>
        <div class="graph-toolbar" aria-label="画布工具">
          <div class="graph-toolbar-group">
            <label class="graph-toggle">
              <input v-model="filterApiOnly" type="checkbox" />
              仅看命中 API 的有效链路
            </label>
            <label class="graph-toggle">
              <input v-model="aggregateByFile" type="checkbox" />
              按文件聚合
            </label>
            <label class="graph-toggle">
              <input v-model="compactLayers" type="checkbox" />
              折叠冗长层级
            </label>
          </div>
          <span class="graph-toolbar-divider" aria-hidden="true" />
          <div class="graph-toolbar-group graph-toolbar-group--view">
            <button
              type="button"
              class="graph-tool-btn graph-tool-btn--icon"
              title="适应画布"
              aria-label="适应画布"
              @click="fitView"
            >
              <span class="mdi mdi-fit-to-screen-outline" aria-hidden="true" />
            </button>
            <button
              type="button"
              class="graph-tool-btn graph-tool-btn--icon"
              title="重置缩放"
              aria-label="重置缩放"
              @click="resetZoom"
            >
              <span class="mdi mdi-refresh" aria-hidden="true" />
            </button>
          </div>
        </div>
      </header>
      <div v-if="impactSummary" class="graph-summary-banner graph-summary-banner--alert graph-summary-banner--compact" role="status">
        <span class="graph-summary-banner__label">影响评估结论</span>
        <div class="graph-summary-banner__body">
          <p v-if="!impactSummary.hasApis" class="graph-summary-banner__text">
            本次变更涉及
            <strong>{{ impactSummary.fileCountLabel }}</strong>
            <template v-if="impactSummary.sampleFiles">
              （含 <strong>{{ impactSummary.sampleFiles }}</strong
              ><template v-if="impactSummary.fileCount > 3"> 等</template>）
            </template>
            ，约 <strong class="graph-summary-num">{{ impactSummary.totalSymbols }}</strong> 处变更符号。经调用链追踪，未发现对外部接口的传播影响。
          </p>
          <p v-else class="graph-summary-banner__text">
            本次变更涉及
            <strong>{{ impactSummary.fileCountLabel }}</strong>
            <template v-if="impactSummary.sampleFiles">
              （含 <strong>{{ impactSummary.sampleFiles }}</strong
              ><template v-if="impactSummary.fileCount > 3"> 等</template>）
            </template>
            ，约 <strong class="graph-summary-num">{{ impactSummary.totalSymbols }}</strong> 处变更符号；共
            <strong class="graph-summary-num">{{ impactSummary.apiCount }}</strong> 个外部接口受影响
            <template v-if="impactSummary.feCount">
              ；同仓前端 <strong class="graph-summary-num">{{ impactSummary.feCount }}</strong> 处调用需关注
            </template>
            。
          </p>
          <div v-if="impactSummary.apiList?.length" class="graph-summary-apis">
            <p class="graph-summary-apis__title">
              受影响的内部接口（共 <strong>{{ impactSummary.apiCount }}</strong> 个）
            </p>
            <div class="graph-summary-chips" aria-label="受影响 API">
              <span
                v-for="api in impactSummary.apiList"
                :key="api.key"
                class="graph-summary-chip"
                :class="`graph-summary-chip--${api.method === 'POST' ? 'post' : api.method === 'DELETE' ? 'delete' : 'get'}`"
              >
                <span class="graph-summary-chip__method">{{ api.method }}</span>
                <span class="graph-summary-chip__path">{{ api.route }}</span>
              </span>
            </div>
          </div>
        </div>
      </div>
      <div v-if="!graphHasRenderable" class="graph-filter-empty" role="status">
        当前筛选条件下没有可展示的节点；可关闭「仅看命中 API」或开启「按文件聚合」。
      </div>
      <div
        v-show="graphHasRenderable"
        ref="containerRef"
        class="graph"
        :style="{ height: `${graphCanvasHeight}px` }"
      />
    </div>
    <div class="legend">
      <span><i class="dot changed" />变更符号 / 文件聚合</span>
      <span><i class="dot symbol" />上游方法</span>
      <span><i class="dot api" />受影响 API</span>
      <span><i class="dot frontend" />前端消费方</span>
    </div>
  </div>
</template>

<style scoped>
.graph-wrap {
  position: relative;
  background: #1a1d21;
  border: 1px solid #2a2e35;
  border-radius: 16px;
  box-shadow: none;
}
.graph-wrap--empty {
  min-height: 0;
}
.graph-wrap--filled {
  min-height: 0;
}
.graph-stage {
  position: relative;
  display: flex;
  flex-direction: column;
}
.graph-headbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px 16px;
  min-height: 52px;
  box-sizing: border-box;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(42, 46, 53, 0.65);
}
.graph-headbar__title {
  margin: 0;
  font-size: 1.0625rem;
  font-weight: 600;
  line-height: 1.35;
  color: #e8eaed;
  letter-spacing: 0.01em;
  flex-shrink: 0;
}
.graph-summary-banner {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 8px 12px;
  margin: 0;
  padding: 10px 14px;
  background: rgba(255, 255, 255, 0.02);
  border-bottom: 1px solid rgba(42, 46, 53, 0.55);
}
.graph-summary-banner--compact {
  align-items: flex-start;
  padding-bottom: 8px;
}
.graph-summary-banner--alert {
  border-left: 3px solid rgba(138, 180, 248, 0.65);
  background: linear-gradient(
    90deg,
    rgba(138, 180, 248, 0.1) 0%,
    rgba(138, 180, 248, 0.04) 38%,
    rgba(255, 255, 255, 0.02) 100%
  );
}
.graph-summary-banner__body {
  flex: 1 1 auto;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
}
.graph-summary-apis {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  flex: 0 0 auto;
}
.graph-summary-apis__title {
  margin: 0;
  font-size: 11px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.48);
}
.graph-summary-apis__title strong {
  color: #8ab4f8;
  font-weight: 600;
}
.graph-summary-chips {
  display: flex;
  flex-wrap: wrap;
  align-content: flex-start;
  gap: 8px;
  max-width: 100%;
}
.graph-summary-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: 0 1 auto;
  max-width: 100%;
  padding: 4px 9px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 500;
  line-height: 1.35;
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.24);
  white-space: nowrap;
}
.graph-summary-chip__method {
  font-weight: 700;
  font-size: 10px;
  letter-spacing: 0.03em;
}
.graph-summary-chip__path {
  font-family: ui-monospace, 'Cascadia Code', 'SF Mono', Consolas, monospace;
  font-size: 11px;
}
.graph-summary-chip--get {
  color: #6ee7b7;
}
.graph-summary-chip--get .graph-summary-chip__method {
  color: #34d399;
}
.graph-summary-chip--post {
  color: #fdba74;
  background: rgba(251, 146, 60, 0.12);
  border-color: rgba(251, 146, 60, 0.28);
}
.graph-summary-chip--post .graph-summary-chip__method {
  color: #fb923c;
}
.graph-summary-chip--delete {
  color: #fca5a5;
  background: rgba(248, 113, 113, 0.1);
  border-color: rgba(248, 113, 113, 0.24);
}
.graph-summary-num {
  color: #8ab4f8 !important;
  font-variant-numeric: tabular-nums;
  font-weight: 700 !important;
}
.graph-summary-banner__label {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: rgba(174, 203, 250, 0.95);
  padding: 3px 8px;
  border-radius: 6px;
  background: rgba(138, 180, 248, 0.12);
}
.graph-summary-banner__text {
  margin: 0;
  flex: 0 0 auto;
  font-size: 13px;
  line-height: 1.55;
  color: rgba(232, 234, 237, 0.82);
  word-break: break-word;
}
.graph-summary-banner__text strong {
  color: #e8eaed;
  font-weight: 600;
}
.graph-filter-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 120px;
  padding: 24px;
  font-size: 13px;
  line-height: 1.55;
  color: rgba(255, 255, 255, 0.55);
  text-align: center;
}
.graph {
  width: 100%;
  min-height: 200px;
  max-height: 500px;
  flex-shrink: 0;
  overflow: hidden;
  background-color: #16181c;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.035) 1px, transparent 1px);
  background-size: 24px 24px;
}
.graph-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 12px 14px;
  flex: 1 1 auto;
  min-width: min(100%, 18rem);
}
.graph-toolbar-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.graph-toolbar-divider {
  width: 1px;
  align-self: stretch;
  min-height: 32px;
  margin: 0 2px;
  background: rgba(255, 255, 255, 0.14);
  flex-shrink: 0;
}
.graph-toggle {
  pointer-events: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  min-height: 32px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(37, 41, 48, 0.88);
  color: rgba(255, 255, 255, 0.78);
  font-size: 11px;
  padding: 0 10px;
  border-radius: 8px;
  cursor: pointer;
  backdrop-filter: blur(6px);
}
.graph-tool-btn {
  pointer-events: auto;
  min-height: 32px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(37, 41, 48, 0.88);
  color: rgba(255, 255, 255, 0.82);
  font-size: 12px;
  line-height: 1;
  padding: 0 12px;
  border-radius: 8px;
  cursor: pointer;
  backdrop-filter: blur(6px);
  transition: background 0.15s ease, border-color 0.15s ease;
}
.graph-tool-btn:hover {
  background: rgba(50, 54, 62, 0.95);
  border-color: rgba(255, 255, 255, 0.22);
  color: #f1f3f5;
}
.graph-tool-btn--icon {
  width: 32px;
  min-width: 32px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.graph-tool-btn--icon .mdi {
  font-size: 18px;
  line-height: 1;
}
.graph-toolbar-group--view {
  gap: 6px;
}
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  box-sizing: border-box;
  height: 220px;
  padding: 20px 24px;
  text-align: center;
}
.empty-icon {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: #24282e;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 2px;
}
.empty-icon__glyph {
  font-size: 26px;
  color: rgba(255, 255, 255, 0.55);
}
.empty-icon--spin .empty-icon__glyph {
  color: #8ab4f8;
  animation: graph-empty-spin 0.95s linear infinite;
}
.graph-wrap--processing {
  border-color: rgba(138, 180, 248, 0.22);
  box-shadow: 0 0 0 1px rgba(138, 180, 248, 0.06) inset;
}
@keyframes graph-empty-spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
.empty-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.78);
}
.empty-desc {
  margin: 0;
  max-width: 28rem;
  font-size: 12px;
  line-height: 1.55;
  color: rgba(255, 255, 255, 0.5);
}
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  padding: 10px 16px;
  border-top: 1px solid #2a2e35;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.72);
}
.dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-right: 6px;
}
.dot.changed {
  background: #fdd663;
}
.dot.symbol {
  background: #8ab4f8;
}
.dot.api {
  background: #f28b82;
}
.dot.frontend {
  background: #81c995;
}
</style>

<style>
/* 若 G6 内置 tooltip 仍出现，强制深色样式并避免挡住节点 */
.g6-tooltip,
.g6-component-tooltip,
[class*='g6-tooltip'] {
  max-width: min(380px, 92vw) !important;
  padding: 8px 12px !important;
  font-size: 12px !important;
  line-height: 1.45 !important;
  color: rgba(255, 255, 255, 0.9) !important;
  background: #2c2c2c !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  border-radius: 8px !important;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45) !important;
  pointer-events: none !important;
  font-family: ui-monospace, 'Cascadia Code', 'SF Mono', Consolas, monospace !important;
  word-break: break-all;
}
</style>