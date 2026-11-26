<script setup lang="ts">
import * as d3 from 'd3'
import { linkHorizontal } from 'd3-shape'
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  shallowRef,
  watch,
} from 'vue'
import type { GraphNode, GraphNodeType, JobGraph } from '@/api/types'
import {
  buildAdj,
  buildImpactSummary,
  fileKey,
  graphLayerIndex,
  highlightNeighborhood,
  LAYER_LABELS,
  prepareCallGraphDisplay,
} from '@/utils/callGraphPrepare'

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

const wrapRef = ref<HTMLDivElement | null>(null)
const svgRef = ref<SVGSVGElement | null>(null)
const canvasHeight = ref(280)
const hoverId = shallowRef<string | null>(null)
let ro: ResizeObserver | undefined
let zoomBehavior: d3.ZoomBehavior<SVGSVGElement, unknown> | undefined

const NODE_W = 272
const NODE_H = 74
const GAP_Y = 10
const PAD = 20
const COL_GAP_MIN = 36

type PlacedNode = GraphNode & { x: number; y: number; layer: number }
type LinkPoint = { x: number; y: number }
type FlowLink = {
  id: string
  sourceId: string
  targetId: string
  source: LinkPoint
  target: LinkPoint
  dim: boolean
  hot: boolean
}

const hasNodes = computed(() => Boolean(props.data?.nodes?.length))

const displayData = computed(() =>
  prepareCallGraphDisplay(props.data, {
    filterApiOnly: filterApiOnly.value,
    compactLayers: compactLayers.value,
    aggregateByFile: aggregateByFile.value,
    expandedFiles: expandedFiles.value,
    changedIds: props.changedIds,
  }),
)

const graphHasRenderable = computed(() => Boolean(displayData.value?.nodes?.length))
const impactSummary = computed(() => buildImpactSummary(props.data, props.changedIds))

const TYPE_FILL: Record<GraphNodeType | 'cluster', string> = {
  frontend: 'rgba(129, 201, 149, 0.14)',
  changed: 'rgba(253, 214, 99, 0.12)',
  symbol: 'rgba(138, 180, 248, 0.12)',
  api: 'rgba(242, 139, 130, 0.14)',
  cluster: 'rgba(253, 214, 99, 0.16)',
}

const TYPE_STROKE: Record<GraphNodeType | 'cluster', string> = {
  frontend: 'rgba(168, 218, 181, 0.85)',
  changed: 'rgba(255, 224, 130, 0.78)',
  symbol: 'rgba(174, 203, 250, 0.75)',
  api: 'rgba(255, 158, 148, 0.82)',
  cluster: 'rgba(255, 224, 130, 0.78)',
}

const TYPE_TITLE: Record<GraphNodeType | 'cluster', string> = {
  frontend: '#b8f0c8',
  changed: '#ffe8a8',
  symbol: '#d4e4ff',
  api: '#ffc9c4',
  cluster: '#ffe8a8',
}

const TYPE_DOT: Record<GraphNodeType | 'cluster', string> = {
  frontend: '#81c995',
  changed: '#fdd663',
  symbol: '#8ab4f8',
  api: '#f28b82',
  cluster: '#fdd663',
}

function shortGraphLabel(n: GraphNode) {
  if (n.id.startsWith('file:')) return n.label
  if (n.type === 'api') {
    return `${(n.method || 'GET').toUpperCase()} ${n.route || '/'}`
  }
  const raw = (n.label || n.id).replace(/\\/g, '.')
  const parts = raw.split('.').filter(Boolean)
  if (parts.length < 2) {
    const leaf = parts[0] ?? raw
    return leaf.includes('(') ? leaf : `${leaf}()`
  }
  const method = parts[parts.length - 1]!
  const prev = parts[parts.length - 2]!
  const withCall = method.includes('(') ? method : `${method}()`
  if (/^[A-Z][_a-zA-Z0-9]*/.test(prev)) return `${prev}.${withCall}`
  return withCall
}

function nodeTitle(n: GraphNode) {
  return shortGraphLabel(n)
}

function nodeTitleFull(n: GraphNode) {
  if (n.id.startsWith('file:')) return n.label
  if (n.type === 'api') return shortGraphLabel(n)
  const label = n.label ?? n.id
  return label.includes('(') ? label : `${label}()`
}

function nodeSubtitle(n: GraphNode) {
  if (n.id.startsWith('file:')) return '点击展开文件内函数'
  if (!n.file) return ''
  if (n.line && n.end_line) return `${n.file} : L${n.line}-L${n.end_line}`
  if (n.line) return `${n.file} : L${n.line}`
  return n.file
}

function layoutNodes(
  nodes: GraphNode[],
  containerWidth: number,
): { placed: PlacedNode[]; width: number; height: number; colW: number; layers: number[] } {
  const layers = [...new Set(nodes.map((n) => graphLayerIndex(n)))].sort((a, b) => a - b)
  const nCols = Math.max(1, layers.length)
  const colW =
    nCols <= 1
      ? NODE_W + COL_GAP_MIN
      : Math.max(
          NODE_W + COL_GAP_MIN,
          (Math.max(containerWidth, 520) - PAD * 2 - NODE_W) / (nCols - 1),
        )
  const placed: PlacedNode[] = []
  const headerH = 18
  let maxBottom = PAD + headerH

  for (const layer of layers) {
    const colIndex = layers.indexOf(layer)
    const colNodes = nodes
      .filter((n) => graphLayerIndex(n) === layer)
      .sort((a, b) => nodeTitle(a).localeCompare(nodeTitle(b)))
    colNodes.forEach((n, row) => {
      const y = PAD + headerH + row * (NODE_H + GAP_Y)
      const x = PAD + colIndex * colW
      placed.push({ ...n, x, y, layer })
      maxBottom = Math.max(maxBottom, y + NODE_H)
    })
  }

  const width = PAD * 2 + (nCols - 1) * colW + NODE_W
  const height = maxBottom + PAD
  return { placed, width, height, colW, layers }
}

function resolvePickNode(id: string): GraphNode | null {
  if (id.startsWith('file:')) {
    const fk = id.slice(5)
    const raw = props.data?.nodes ?? []
    return (
      raw.find((n) => n.file && fileKey(n.file) === fk && n.type === 'changed') ??
      raw.find((n) => n.file && fileKey(n.file) === fk) ??
      null
    )
  }
  return displayData.value?.nodes.find((n) => n.id === id) ?? null
}

function onNodeClick(n: GraphNode, event?: Event) {
  event?.stopPropagation()
  event?.preventDefault()
  if (n.id.startsWith('file:')) {
    const fk = n.id.slice(5)
    const next = new Set(expandedFiles.value)
    if (next.has(fk)) next.delete(fk)
    else next.add(fk)
    expandedFiles.value = next
    return
  }
  const src = displayData.value
  if (!src) return
  const node = resolvePickNode(n.id) ?? n
  const { fwd } = buildAdj(src.edges)
  emit('nodePick', {
    id: node.id,
    label: node.label,
    type: node.type,
    file: node.file,
    line: node.line,
    end_line: node.end_line ?? node.line,
    method: node.method,
    route: node.route,
    calleeHints: [...(fwd.get(node.id) ?? [])],
  })
}

function zoomFilter(event: Event) {
  const target = event.target as Element | null
  if (target?.closest?.('.d3-node')) return false
  if (event.type === 'wheel') return true
  if (event.type === 'dblclick') return false
  return event.type === 'mousedown' || event.type === 'touchstart'
}

function applyZoomTransform(transform: d3.ZoomTransform) {
  const svgEl = svgRef.value
  if (!svgEl) return
  d3.select(svgEl).select<SVGGElement>('.d3-zoom-root').attr('transform', transform.toString())
}

function ensureZoomBehavior(svg: d3.Selection<SVGSVGElement, unknown, null, undefined>) {
  if (!zoomBehavior) {
    zoomBehavior = d3
      .zoom<SVGSVGElement, unknown>()
      .filter(zoomFilter)
      .scaleExtent([0.45, 1.8])
      .on('zoom', (event) => {
        applyZoomTransform(event.transform)
      })
  }
  svg.call(zoomBehavior)
}

function updateHoverStyles() {
  const data = displayData.value
  const svgEl = svgRef.value
  if (!data?.nodes.length || !svgEl) return

  const idSet = new Set(data.nodes.map((n) => n.id))
  const active =
    hoverId.value && idSet.has(hoverId.value)
      ? highlightNeighborhood(hoverId.value, data.edges, idSet)
      : null

  const svg = d3.select(svgEl)
  svg
    .selectAll<SVGGElement, PlacedNode>('.d3-node')
    .attr('opacity', (d) => (active && !active.has(d.id) ? 0.2 : 1))
  svg
    .selectAll<SVGRectElement, PlacedNode>('.d3-node rect')
    .attr('stroke-width', (d) => (hoverId.value === d.id ? 2 : 1.25))
  svg
    .selectAll<SVGPathElement, FlowLink>('.d3-links path')
    .attr('stroke', (d) => {
      const highlighted = active ? active.has(d.sourceId) && active.has(d.targetId) : true
      const hot = active
        ? highlighted && (d.sourceId === hoverId.value || d.targetId === hoverId.value)
        : false
      if (hot) return 'rgba(147, 197, 253, 0.92)'
      if (active && !highlighted) return 'rgba(148,163,184,0.12)'
      return 'url(#d3-link-grad)'
    })
    .attr('stroke-width', (d) => {
      const highlighted = active ? active.has(d.sourceId) && active.has(d.targetId) : true
      const hot = active
        ? highlighted && (d.sourceId === hoverId.value || d.targetId === hoverId.value)
        : false
      if (hot) return 2.5
      if (active && !highlighted) return 1
      return 2
    })
}

function drawGraph() {
  const data = displayData.value
  const svgEl = svgRef.value
  const wrap = wrapRef.value
  if (!data?.nodes.length || !svgEl || !wrap) return

  const containerW = Math.max(wrap.clientWidth, 520)
  const { placed, width, height, colW, layers } = layoutNodes(data.nodes, containerW)
  canvasHeight.value = Math.min(560, Math.max(240, height + 12))

  const pos = new Map(placed.map((p) => [p.id, p]))
  const idSet = new Set(placed.map((p) => p.id))
  const active =
    hoverId.value && idSet.has(hoverId.value)
      ? highlightNeighborhood(hoverId.value, data.edges, idSet)
      : null

  const svg = d3.select(svgEl)
  const savedTransform = d3.zoomTransform(svgEl)
  svg.selectAll('*').remove()
  svg.attr('viewBox', `0 0 ${width} ${height}`).attr('width', '100%').attr('height', canvasHeight.value)

  const root = svg
    .append('g')
    .attr('class', 'd3-zoom-root')
    .attr('transform', savedTransform.toString())

  const defs = svg.append('defs')
  const grad = defs
    .append('linearGradient')
    .attr('id', 'd3-link-grad')
    .attr('gradientUnits', 'userSpaceOnUse')
    .attr('x1', 0)
    .attr('x2', width)
    .attr('y1', 0)
    .attr('y2', 0)
  grad.append('stop').attr('offset', '0%').attr('stop-color', 'rgba(148,163,184,0.18)')
  grad.append('stop').attr('offset', '100%').attr('stop-color', 'rgba(138,180,248,0.62)')

  const linkGen = linkHorizontal<FlowLink, LinkPoint>()
    .source((d) => d.source)
    .target((d) => d.target)

  const linkData: FlowLink[] = data.edges
    .map((e) => {
      const s = pos.get(e.source)
      const t = pos.get(e.target)
      if (!s || !t || s.layer >= t.layer) return null
      const highlighted = active ? active.has(e.source) && active.has(e.target) : true
      return {
        id: `${e.source}->${e.target}`,
        sourceId: e.source,
        targetId: e.target,
        source: { x: s.x + NODE_W, y: s.y + NODE_H / 2 },
        target: { x: t.x, y: t.y + NODE_H / 2 },
        dim: active ? !highlighted : false,
        hot: active ? highlighted && (e.source === hoverId.value || e.target === hoverId.value) : false,
      }
    })
    .filter((d): d is FlowLink => d !== null)

  root
    .append('g')
    .attr('class', 'd3-links')
    .selectAll('path')
    .data(linkData)
    .join('path')
    .attr('d', (d) => linkGen(d) || '')
    .attr('fill', 'none')
    .attr('stroke', (d) =>
      d.hot ? 'rgba(147, 197, 253, 0.92)' : d.dim ? 'rgba(148,163,184,0.12)' : 'url(#d3-link-grad)',
    )
    .attr('stroke-width', (d) => (d.hot ? 2.5 : d.dim ? 1 : 2))
    .attr('stroke-opacity', (d) => (d.dim ? 0.35 : 0.92))
    .attr('marker-end', 'url(#d3-arrow)')

  defs
    .append('marker')
    .attr('id', 'd3-arrow')
    .attr('viewBox', '0 -4 8 8')
    .attr('refX', 6)
    .attr('refY', 0)
    .attr('markerWidth', 7)
    .attr('markerHeight', 7)
    .attr('orient', 'auto')
    .append('path')
    .attr('d', 'M0,-4 L8,0 L0,4 Z')
    .attr('fill', 'rgba(138,180,248,0.75)')

  const headerG = root.append('g').attr('class', 'd3-layer-headers')
  for (const layer of layers) {
    const colIndex = layers.indexOf(layer)
    headerG
      .append('text')
      .attr('x', PAD + colIndex * colW + NODE_W / 2)
      .attr('y', PAD + 4)
      .attr('text-anchor', 'middle')
      .attr('fill', 'rgba(255,255,255,0.38)')
      .attr('font-size', 10)
      .attr('font-weight', 500)
      .text(LAYER_LABELS[layer] ?? '')
  }

  const nodeG = root
    .append('g')
    .attr('class', 'd3-nodes')
    .selectAll('g')
    .data(placed)
    .join('g')
    .attr('class', 'd3-node')
    .attr('transform', (d) => `translate(${d.x},${d.y})`)
    .style('cursor', 'pointer')
    .on('mouseenter', (event, d) => {
      event.stopPropagation()
      hoverId.value = d.id
      updateHoverStyles()
    })
    .on('mouseleave', (event) => {
      event.stopPropagation()
      hoverId.value = null
      updateHoverStyles()
    })
    .on('click', (event, d) => onNodeClick(d, event))

  nodeG
    .attr('opacity', (d) => (active && !active.has(d.id) ? 0.2 : 1))
    .attr('title', (d) => nodeTitleFull(d))

  nodeG
    .append('rect')
    .attr('width', NODE_W)
    .attr('height', NODE_H)
    .attr('rx', 12)
    .attr('fill', (d) => {
      const k = d.id.startsWith('file:') ? 'cluster' : d.type
      return TYPE_FILL[k]
    })
    .attr('stroke', (d) => {
      const k = d.id.startsWith('file:') ? 'cluster' : d.type
      return TYPE_STROKE[k]
    })
    .attr('stroke-width', (d) => (hoverId.value === d.id ? 2 : 1.25))

  nodeG
    .append('circle')
    .attr('cx', 16)
    .attr('cy', 22)
    .attr('r', 5)
    .attr('fill', (d) => {
      const k = d.id.startsWith('file:') ? 'cluster' : d.type
      return TYPE_DOT[k]
    })

  nodeG
    .append('text')
    .attr('x', 28)
    .attr('y', 26)
    .attr('fill', (d) => {
      const k = d.id.startsWith('file:') ? 'cluster' : d.type
      return TYPE_TITLE[k]
    })
    .attr('font-size', 12)
    .attr('font-weight', 700)
    .text((d) => {
      const t = nodeTitle(d)
      return t.length > 36 ? `${t.slice(0, 34)}…` : t
    })

  nodeG
    .append('text')
    .attr('x', 12)
    .attr('y', 58)
    .attr('fill', 'rgba(255,255,255,0.52)')
    .attr('font-size', 10)
    .attr('font-family', 'ui-monospace, Consolas, monospace')
    .text((d) => {
      const full = nodeTitleFull(d)
      const short = nodeTitle(d)
      const sub =
        full !== short && !d.id.startsWith('file:')
          ? full
          : nodeSubtitle(d)
      return sub.length > 44 ? `…${sub.slice(-42)}` : sub
    })

  ensureZoomBehavior(svg)
  applyZoomTransform(savedTransform)
}

function fitView() {
  const svgEl = svgRef.value
  const wrap = wrapRef.value
  const data = displayData.value
  if (!svgEl || !wrap || !data?.nodes.length) return
  const svg = d3.select(svgEl)
  ensureZoomBehavior(svg)
  if (!zoomBehavior) return
  const { width, height } = layoutNodes(data.nodes, wrap.clientWidth || 900)
  const pad = 8
  const k = Math.min(
    1.5,
    (wrap.clientWidth - pad * 2) / width,
    (canvasHeight.value - pad * 2) / height,
  )
  const tx = (wrap.clientWidth - width * k) / 2
  const ty = Math.max(pad, (canvasHeight.value - height * k) / 2)
  const next = d3.zoomIdentity.translate(tx, ty).scale(k)
  svg.interrupt().transition().duration(280).call(zoomBehavior.transform, next)
  applyZoomTransform(next)
}

function applyZoom(factor: number) {
  const svgEl = svgRef.value
  if (!svgEl || !zoomBehavior) return
  const t = d3.zoomTransform(svgEl)
  const wrap = wrapRef.value
  const cx = wrap ? wrap.clientWidth / 2 : 0
  const cy = wrap ? canvasHeight.value / 2 : 0
  const nextK = Math.min(1.8, Math.max(0.45, t.k * factor))
  const next = d3.zoomIdentity
    .translate(cx - (cx - t.x) * (nextK / t.k), cy - (cy - t.y) * (nextK / t.k))
    .scale(nextK)
  d3.select(svgEl).transition().duration(180).call(zoomBehavior.transform, next)
}

function resetZoom() {
  scheduleDraw()
  void nextTick(() => fitView())
}

function scheduleDraw() {
  void nextTick(() => drawGraph())
}

watch(
  () => [
    displayData.value,
    filterApiOnly.value,
    compactLayers.value,
    aggregateByFile.value,
    expandedFiles.value,
  ],
  () => {
    scheduleDraw()
    void nextTick(() => fitView())
  },
  { deep: true },
)

watch(aggregateByFile, (on) => {
  if (on) expandedFiles.value = new Set()
})

onMounted(() => {
  scheduleDraw()
  if (wrapRef.value) {
    ro = new ResizeObserver(() => {
      scheduleDraw()
      void nextTick(() => fitView())
    })
    ro.observe(wrapRef.value)
  }
  void nextTick(() => fitView())
})

onBeforeUnmount(() => {
  ro?.disconnect()
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
        <span class="mdi empty-icon__glyph" :class="processing ? 'mdi-loading' : 'mdi-source-branch'" />
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
            本次变更涉及 <strong>{{ impactSummary.fileCountLabel }}</strong>
            <template v-if="impactSummary.sampleFiles">（含 <strong>{{ impactSummary.sampleFiles }}</strong> 等）</template>
            ，约 <strong class="graph-summary-num">{{ impactSummary.totalSymbols }}</strong> 处变更符号。
          </p>
          <p v-else class="graph-summary-banner__text">
            本次变更涉及 <strong>{{ impactSummary.fileCountLabel }}</strong>
            <template v-if="impactSummary.sampleFiles">（含 <strong>{{ impactSummary.sampleFiles }}</strong> 等）</template>
            ，约 <strong class="graph-summary-num">{{ impactSummary.totalSymbols }}</strong> 处变更符号；共
            <strong class="graph-summary-num">{{ impactSummary.apiCount }}</strong> 个外部接口受影响；
            同仓前端 <strong class="graph-summary-num">{{ impactSummary.feCount }}</strong> 处调用需关注。
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
      <div v-show="graphHasRenderable" ref="wrapRef" class="d3-graph-canvas" :style="{ height: `${canvasHeight}px` }">
        <svg ref="svgRef" class="d3-graph-svg" role="img" aria-label="变更影响拓扑图" />
        <div class="d3-floating-tools" aria-label="画布缩放">
          <button type="button" class="d3-float-btn" title="放大" aria-label="放大" @click="applyZoom(1.12)">
            <span class="mdi mdi-plus" aria-hidden="true" />
          </button>
          <button type="button" class="d3-float-btn" title="缩小" aria-label="缩小" @click="applyZoom(1 / 1.12)">
            <span class="mdi mdi-minus" aria-hidden="true" />
          </button>
          <button type="button" class="d3-float-btn" title="适应画布" aria-label="适应画布" @click="fitView">
            <span class="mdi mdi-fit-to-screen-outline" aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>

    <div class="legend">
      <span><i class="dot changed" />变更符号 / 文件聚合</span>
      <span><i class="dot symbol" />上游方法</span>
      <span><i class="dot api" />受影响 API</span>
      <span><i class="dot frontend" />前端消费方</span>
    </div>
  </div>
</template>

<style scoped src="./call-graph-panel.css"></style>
<style scoped>
.d3-graph-canvas {
  position: relative;
  width: 100%;
  overflow: hidden;
  background-color: #16181c;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.035) 1px, transparent 1px);
  background-size: 24px 24px;
  border-top: 1px solid rgba(42, 46, 53, 0.55);
}
.d3-graph-svg {
  display: block;
  user-select: none;
}
.d3-floating-tools {
  position: absolute;
  right: 12px;
  bottom: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  z-index: 2;
  padding: 6px;
  border-radius: 12px;
  background: rgba(26, 29, 33, 0.92);
  border: 1px solid rgba(255, 255, 255, 0.12);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
}
.d3-float-btn {
  width: 36px;
  height: 36px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 10px;
  background: rgba(42, 46, 53, 0.95);
  color: rgba(255, 255, 255, 0.88);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.d3-float-btn:hover {
  background: rgba(55, 60, 68, 0.98);
  border-color: rgba(138, 180, 248, 0.45);
  color: #e8eaed;
}
.d3-float-btn .mdi {
  font-size: 18px;
  line-height: 1;
}
</style>