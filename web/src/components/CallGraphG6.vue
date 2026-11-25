<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Graph } from '@antv/g6'
import type { GraphNode, GraphNodeType, JobGraph } from '@/api/types'

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
  }>(),
  {
    changedIds: () => [],
    emptyHint: '暂无调用链子图（任务完成后生成）',
    emptyTitle: '暂无调用链子图',
    emptyDesc: '任务完成后生成变更影响拓扑',
    panelTitle: '变更影响拓扑',
  },
)

const emit = defineEmits<{ nodePick: [GraphNodePick] }>()

const filterApiOnly = ref(true)
const compactLayers = ref(false)
const selectedId = ref<string | null>(null)

const hasNodes = computed(() => Boolean(props.data?.nodes?.length))

const containerRef = ref<HTMLDivElement | null>(null)
let graph: Graph | null = null

const TYPE_COLORS: Record<string, string> = {
  api: 'rgba(242, 139, 130, 0.32)',
  changed: 'rgba(253, 214, 99, 0.2)',
  symbol: 'rgba(138, 180, 248, 0.2)',
}

const TYPE_STROKES: Record<string, string> = {
  api: '#f28b82',
  changed: '#fdd663',
  symbol: '#8ab4f8',
}

const NODE_SIZE: [number, number] = [230, 54]
const API_NODE_SIZE: [number, number] = [268, 50]
const FIT_PADDING = 32
const MAX_FIT_ZOOM = 1
const MIN_FIT_ZOOM = 0.65
let fitTimer: number | undefined

function pickLayout(nodes: GraphNode[], edges: { source: string; target: string }[], apiFilter: boolean) {
  const n = nodes.length
  const e = edges.length
  if (apiFilter && e > 0 && n <= 12) {
    return { type: 'dagre', rankdir: 'LR', nodesep: 32, ranksep: 84 }
  }
  const sparse = e < n * 0.45
  if (n >= 8 && sparse) {
    const cols = Math.min(6, Math.max(3, Math.ceil(Math.sqrt(n))))
    return {
      type: 'grid',
      cols,
      rows: Math.ceil(n / cols),
      nodeSize: 248,
      preventOverlap: true,
      sortBy: 'id',
    }
  }
  return { type: 'dagre', rankdir: 'LR', nodesep: 36, ranksep: 88 }
}

function nodeSize(d: { data?: { kind?: string } }): [number, number] {
  return d.data?.kind === 'api' ? API_NODE_SIZE : NODE_SIZE
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
  let nodes = raw.nodes
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
  return { nodes, edges }
})

function nodeTitle(d: {
  data?: {
    label?: string
    kind?: string
    route?: string | null
    method?: string | null
  }
}) {
  const kind = d.data?.kind
  if (kind === 'api') {
    const method = (d.data?.method || 'GET').toUpperCase()
    return `${method} ${d.data?.route || '/'}`
  }
  const label = d.data?.label ?? ''
  return label.includes('(') ? label : `${label}()`
}

function nodeSubtitle(d: {
  data?: { file?: string; line?: number; end_line?: number }
}) {
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
  return `${nodeTitle(d)}\n${nodeSubtitle(d)}`
}

async function safeFitView() {
  if (!graph) return
  const nodeCount = displayData.value?.nodes.length ?? 0
  if (nodeCount <= 1) {
    await graph.zoomTo(1)
    return
  }
  await graph.fitView()
  const zoom = typeof graph.getZoom === 'function' ? graph.getZoom() : 1
  if (zoom > MAX_FIT_ZOOM) {
    await graph.zoomTo(MAX_FIT_ZOOM)
  } else if (zoom < MIN_FIT_ZOOM && nodeCount > 3) {
    await graph.zoomTo(MIN_FIT_ZOOM)
  }
}

function scheduleFitView() {
  if (fitTimer) window.clearTimeout(fitTimer)
  fitTimer = window.setTimeout(() => {
    void safeFitView()
  }, 100)
}

function pickNode(id: string) {
  const src = displayData.value
  if (!src) return
  const node = src.nodes.find((n) => n.id === id)
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
  const target = (event as { target?: { id?: string } })?.target
  return target?.id ? String(target.id) : null
}

function bindGraphEvents() {
  if (!graph) return
  graph.on('node:click', (event) => {
    const id = nodeIdFromEvent(event)
    if (!id) return
    selectedId.value = id
    const ids = displayData.value?.nodes.map((n) => n.id) ?? []
    const state: Record<string, string | string[]> = {}
    for (const nodeId of ids) {
      state[nodeId] = nodeId === id ? 'selected' : []
    }
    void graph?.setElementState(state)
    pickNode(id)
  })
}

function renderGraph() {
  if (!containerRef.value || !displayData.value?.nodes?.length) return

  graph?.destroy()
  graph = new Graph({
    container: containerRef.value,
    padding: FIT_PADDING,
    data: {
      nodes: displayData.value.nodes.map((n) => ({
        id: n.id,
        data: {
          label: n.label,
          kind: n.type,
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
        radius: 8,
        labelText: (d: { data?: { label?: string; kind?: string } }) => nodeLabelText(d),
        labelFontSize: 13,
        labelLineHeight: 17,
        labelFill: '#e8eaed',
        labelPlacement: 'center',
        labelWordWrap: true,
        labelMaxWidth: (d: { data?: { kind?: string } }) =>
          d.data?.kind === 'api' ? 248 : 210,
        labelMaxLines: 2,
        fill: (d: { data?: { kind?: string } }) => TYPE_COLORS[d.data?.kind ?? 'symbol'],
        stroke: (d: { data?: { kind?: string } }) => {
          const kind = d.data?.kind ?? 'symbol'
          return kind === 'api' ? '#f6aea8' : TYPE_STROKES[kind]
        },
        lineWidth: (d: { data?: { kind?: string } }) => (d.data?.kind === 'api' ? 2.5 : 1.5),
        shadowBlur: (d: { data?: { kind?: string } }) => (d.data?.kind === 'api' ? 12 : 0),
        shadowColor: (d: { data?: { kind?: string } }) =>
          d.data?.kind === 'api' ? 'rgba(242, 139, 130, 0.35)' : 'transparent',
        opacity: 1,
      },
      state: {
        active: { opacity: 1 },
        inactive: { opacity: 0.26, fill: 'rgba(26, 29, 33, 0.45)' },
        selected: {
          stroke: '#ffffff',
          lineWidth: 2.5,
          opacity: 1,
        },
      },
    },
    edge: {
      style: {
        stroke: '#5f6368',
        endArrow: true,
        opacity: 0.85,
      },
      state: {
        active: { stroke: '#9aa0a6', opacity: 1 },
        inactive: { opacity: 0.2 },
      },
    },
    behaviors: [
      'drag-canvas',
      { type: 'zoom-canvas', maxZoom: MAX_FIT_ZOOM, minZoom: MIN_FIT_ZOOM },
      'drag-element',
      {
        type: 'hover-activate',
        degree: 1,
        direction: 'both',
        state: 'active',
        inactiveState: 'inactive',
      },
    ],
  })

  graph.render()
  bindGraphEvents()
  scheduleFitView()
}

function fitView() {
  scheduleFitView()
}

function resetZoom() {
  void graph?.zoomTo(1)
  scheduleFitView()
}

watch(
  () => [displayData.value, filterApiOnly.value, compactLayers.value],
  () => renderGraph(),
  { deep: true },
)

onMounted(renderGraph)
onBeforeUnmount(() => {
  if (fitTimer) window.clearTimeout(fitTimer)
  graph?.destroy()
  graph = null
})
</script>

<template>
  <div class="graph-wrap" :class="hasNodes ? 'graph-wrap--filled' : 'graph-wrap--empty'">
    <div v-if="!hasNodes" class="empty">
      <div class="empty-icon" aria-hidden="true">
        <span class="mdi mdi-source-branch empty-icon__glyph" />
      </div>
      <p class="empty-title">{{ emptyTitle }}</p>
      <p class="empty-desc">{{ emptyDesc || emptyHint }}</p>
    </div>
    <div v-show="hasNodes" class="graph-stage">
      <header class="graph-headbar">
        <h3 class="graph-headbar__title">{{ panelTitle }}</h3>
        <div class="graph-toolbar" aria-label="画布工具">
        <label class="graph-toggle">
          <input v-model="filterApiOnly" type="checkbox" />
          仅看命中 API 的有效链路
        </label>
        <label class="graph-toggle">
          <input v-model="compactLayers" type="checkbox" />
          折叠冗长层级
        </label>
        <button type="button" class="graph-tool-btn" title="适应画布" @click="fitView">适应画布</button>
        <button type="button" class="graph-tool-btn" title="重置缩放" @click="resetZoom">重置缩放</button>
        </div>
      </header>
      <div ref="containerRef" class="graph" />
    </div>
    <div class="legend">
      <span><i class="dot changed" />变更符号</span>
      <span><i class="dot symbol" />上游方法</span>
      <span><i class="dot api" />受影响 API</span>
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
  min-height: 640px;
}
.graph-stage {
  position: relative;
}
.graph-headbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px 16px;
  padding: 14px 16px 10px;
  border-bottom: 1px solid rgba(42, 46, 53, 0.65);
}
.graph-headbar__title {
  margin: 0;
  font-size: 1.0625rem;
  font-weight: 600;
  color: #e8eaed;
  letter-spacing: 0.01em;
}
.graph {
  width: 100%;
  height: 560px;
}
.graph-toolbar {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  flex: 1 1 auto;
  min-width: min(100%, 18rem);
}
.graph-toggle {
  pointer-events: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(37, 41, 48, 0.88);
  color: rgba(255, 255, 255, 0.78);
  font-size: 11px;
  padding: 7px 10px;
  border-radius: 999px;
  cursor: pointer;
  backdrop-filter: blur(6px);
}
.graph-tool-btn {
  pointer-events: auto;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(37, 41, 48, 0.88);
  color: rgba(255, 255, 255, 0.82);
  font-size: 12px;
  line-height: 1;
  padding: 8px 10px;
  border-radius: 999px;
  cursor: pointer;
  backdrop-filter: blur(6px);
  transition: background 0.15s ease, border-color 0.15s ease;
}
.graph-tool-btn:hover {
  background: rgba(50, 54, 62, 0.95);
  border-color: rgba(255, 255, 255, 0.22);
  color: #f1f3f5;
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
</style>