<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Graph } from '@antv/g6'
import type { JobGraph } from '@/api/types'

const props = defineProps<{
  data: JobGraph | null
}>()

const containerRef = ref<HTMLDivElement | null>(null)
let graph: Graph | null = null

const TYPE_COLORS: Record<string, string> = {
  api: '#dc2626',
  changed: '#f59e0b',
  symbol: '#2563eb',
}

function renderGraph() {
  if (!containerRef.value || !props.data?.nodes?.length) return

  graph?.destroy()
  graph = new Graph({
    container: containerRef.value,
    autoFit: 'view',
    data: {
      nodes: props.data.nodes.map((n) => ({
        id: n.id,
        data: {
          label: n.label,
          type: n.type,
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
      rankdir: 'BT',
      nodesep: 36,
      ranksep: 48,
    },
    node: {
      style: {
        size: 30,
        labelText: (d: { data?: { label?: string } }) => d.data?.label ?? '',
        labelFontSize: 11,
        fill: (d: { data?: { type?: string } }) => TYPE_COLORS[d.data?.type ?? 'symbol'],
        stroke: '#e5e7eb',
        lineWidth: 1,
      },
    },
    edge: {
      style: {
        stroke: '#94a3b8',
        endArrow: true,
      },
    },
    behaviors: ['drag-canvas', 'zoom-canvas', 'drag-element'],
  })

  graph.render()
}

watch(
  () => props.data,
  () => renderGraph(),
  { deep: true },
)

onMounted(renderGraph)
onBeforeUnmount(() => {
  graph?.destroy()
  graph = null
})
</script>

<template>
  <div class="graph-wrap">
    <div v-if="!data?.nodes?.length" class="empty">暂无调用链子图（任务完成后生成）</div>
    <div v-show="data?.nodes?.length" ref="containerRef" class="graph" />
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
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  min-height: 420px;
}
.graph {
  width: 100%;
  height: 420px;
}
.empty {
  display: grid;
  place-items: center;
  height: 420px;
  color: #6b7280;
}
.legend {
  display: flex;
  gap: 16px;
  padding: 10px 14px;
  border-top: 1px solid #e5e7eb;
  font-size: 12px;
  color: #4b5563;
}
.dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-right: 6px;
}
.dot.changed {
  background: #f59e0b;
}
.dot.symbol {
  background: #2563eb;
}
.dot.api {
  background: #dc2626;
}
</style>