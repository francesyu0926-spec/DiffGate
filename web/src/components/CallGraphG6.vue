<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Graph } from '@antv/g6'
import type { JobGraph } from '@/api/types'

const props = withDefaults(
  defineProps<{
    data: JobGraph | null
    emptyHint?: string
    emptyTitle?: string
    emptyDesc?: string
  }>(),
  {
    emptyHint: '暂无调用链子图（任务完成后生成）',
    emptyTitle: '暂无调用链子图',
    emptyDesc: '任务完成后生成变更影响拓扑',
  },
)

const hasNodes = computed(() => Boolean(props.data?.nodes?.length))

const containerRef = ref<HTMLDivElement | null>(null)
let graph: Graph | null = null

const TYPE_COLORS: Record<string, string> = {
  api: 'rgba(242, 139, 130, 0.22)',
  changed: 'rgba(253, 214, 99, 0.2)',
  symbol: 'rgba(138, 180, 248, 0.2)',
}

const TYPE_STROKES: Record<string, string> = {
  api: '#f28b82',
  changed: '#fdd663',
  symbol: '#8ab4f8',
}

const NODE_SIZE: [number, number] = [210, 42]
const FIT_PADDING = 32
let fitTimer: number | undefined

function shortLabel(label: string, max = 30) {
  if (label.length <= max) return label
  return `${label.slice(0, max - 1)}…`
}

function nodeLabelText(d: { data?: { label?: string } }) {
  return shortLabel(d.data?.label ?? '')
}

function scheduleFitView() {
  if (fitTimer) window.clearTimeout(fitTimer)
  fitTimer = window.setTimeout(() => {
    void graph?.fitView()
  }, 100)
}

function renderGraph() {
  if (!containerRef.value || !props.data?.nodes?.length) return

  graph?.destroy()
  graph = new Graph({
    container: containerRef.value,
    padding: FIT_PADDING,
    data: {
      nodes: props.data.nodes.map((n) => ({
        id: n.id,
        data: {
          label: n.label,
          kind: n.type,
          file: n.file,
          line: n.line,
          route: n.route,
          method: n.method,
        },
      })),
      edges: props.data.edges.map((e, idx) => ({
        id: `e-${idx}`,
        source: e.source,
        target: e.target,
      })),
    },
    layout: {
      type: 'dagre',
      rankdir: 'LR',
      nodesep: 24,
      ranksep: 70,
    },
    node: {
      type: 'rect',
      style: {
        size: NODE_SIZE,
        radius: 8,
        labelText: (d: { data?: { label?: string } }) => nodeLabelText(d),
        labelFontSize: 12,
        labelLineHeight: 16,
        labelFill: '#e8eaed',
        labelPlacement: 'center',
        labelWordWrap: true,
        labelMaxWidth: 186,
        fill: (d: { data?: { kind?: string } }) => TYPE_COLORS[d.data?.kind ?? 'symbol'],
        stroke: (d: { data?: { kind?: string } }) => TYPE_STROKES[d.data?.kind ?? 'symbol'],
        lineWidth: 1.5,
      },
    },
    edge: {
      style: {
        stroke: '#5f6368',
        endArrow: true,
      },
    },
    behaviors: ['drag-canvas', 'zoom-canvas', 'drag-element'],
  })

  graph.render()
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
  () => props.data,
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
      <div class="graph-toolbar" aria-label="画布工具">
        <button type="button" class="graph-tool-btn" title="适应画布" @click="fitView">适应画布</button>
        <button type="button" class="graph-tool-btn" title="重置缩放" @click="resetZoom">重置缩放</button>
      </div>
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
  min-height: 460px;
}
.graph-stage {
  position: relative;
}
.graph {
  width: 100%;
  height: 460px;
}
.graph-toolbar {
  position: absolute;
  top: 10px;
  right: 10px;
  z-index: 2;
  display: flex;
  gap: 8px;
  pointer-events: none;
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