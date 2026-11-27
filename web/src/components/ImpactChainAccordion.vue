<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type {
  AffectedApi,
  CallPath,
  CodeDiffLine,
  FullstackImpact,
  JobGraph,
  SuspectFunction,
} from '@/api/types'
import { fetchJobCodeDiff } from '@/api/client'
import { buildImpactSummary } from '@/utils/callGraphPrepare'
import { buildImpactAccordionItems, type ImpactAccordionStep } from '@/utils/impactAccordionBuild'
import '@/components/call-graph-panel.css'

export interface AccordionDiffPick {
  title: string
  file: string
  startLine: number
  endLine: number
  nodeType?: 'api' | 'changed' | 'frontend' | 'symbol'
}

const props = withDefaults(
  defineProps<{
    jobId: string
    callPaths?: CallPath[]
    apis?: AffectedApi[]
    graph?: JobGraph | null
    fullstack?: FullstackImpact
    suspects?: SuspectFunction[]
    changedIds?: string[]
    panelTitle?: string
    emptyTitle?: string
    emptyDesc?: string
    processing?: boolean
    /** 已完成且无调用链：折叠为大块空态，改为轻量横条提示 */
    compactEmpty?: boolean
    compactEmptyText?: string
  }>(),
  {
    callPaths: () => [],
    apis: () => [],
    graph: null,
    fullstack: undefined,
    suspects: () => [],
    changedIds: () => [],
    panelTitle: '变更影响拓扑',
    emptyTitle: '暂无影响链路',
    emptyDesc: '任务完成后按受影响接口展示逆向追溯',
    processing: false,
    compactEmpty: false,
    compactEmptyText: '本次变更无涉及调用链，暂无拓扑图。',
  },
)

const emit = defineEmits<{ viewDiff: [AccordionDiffPick] }>()

const showGraphMode = ref(false)
const expanded = ref<string[]>([])
const inlineDiff = ref<Record<string, CodeDiffLine[]>>({})
const inlineLoading = ref<Record<string, boolean>>({})

const items = computed(() =>
  buildImpactAccordionItems(
    props.callPaths,
    props.apis,
    props.graph,
    props.fullstack,
    props.suspects,
  ),
)

const hasItems = computed(() => items.value.length > 0)
const showCompactEmpty = computed(
  () => !hasItems.value && props.compactEmpty && !props.processing,
)
const impactSummary = computed(() => buildImpactSummary(props.graph, props.changedIds))

function summaryText(item: (typeof items.value)[number]) {
  const parts: string[] = []
  if (item.fileCount > 0) parts.push(`${item.fileCount} 个变更文件`)
  if (item.frontendCount > 0) parts.push(`${item.frontendCount} 个前端组件`)

  const hasChangeStep = item.steps.some((s) => s.kind === 'change')
  const treeDepth = item.steps.length
  const layers = item.layers ?? 0
  const midHops = layers > 1 ? layers - 1 : Math.max(0, item.symbolCount - 1)

  if (midHops > 0) {
    parts.push(`${midHops} 层中间调用`)
  } else if (hasChangeStep && treeDepth > 1) {
    parts.push('路由 → 变更符号')
  } else if (item.symbolCount > 0) {
    parts.push(`${item.symbolCount} 处上游符号`)
  } else if (treeDepth > 1) {
    parts.push(`${treeDepth - 1} 步逆向链路`)
  }

  return parts.length ? parts.join(' · ') : '已命中接口'
}

function stepIcon(kind: ImpactAccordionStep['kind']) {
  if (kind === 'frontend') return 'mdi-xml'
  if (kind === 'api') return 'mdi-cloud-outline'
  return 'mdi-file-code-outline'
}

const copyToast = ref<string | null>(null)
let copyTimer: number | undefined

async function copyInlineDiff(key: string) {
  const lines = inlineDiff.value[key] ?? []
  const text = lines.map((l) => l.text).join('\n')
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    copyToast.value = '片段已复制'
    if (copyTimer) window.clearTimeout(copyTimer)
    copyTimer = window.setTimeout(() => {
      copyToast.value = null
    }, 1800)
  } catch {
    copyToast.value = '复制失败'
  }
}

function highlightLine(text: string, kind: CodeDiffLine['kind']) {
  const esc = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  if (kind === 'add' || kind === 'del') return esc
  return esc
    .replace(/('([^'\\]|\\.)*'|"([^"\\]|\\.)*")/g, '<span class="tok-str">$1</span>')
    .replace(
      /\b(def|class|import|from|if|elif|else|try|except|return|async|await|with|raise)\b/g,
      '<span class="tok-kw">$1</span>',
    )
}

function panelExpanded(key: string) {
  return expanded.value.includes(key)
}

function openDiff(step: ImpactAccordionStep, itemTitle: string) {
  if (!step.file || !step.startLine) return
  const start = step.startLine
  const end = step.endLine && step.endLine >= start ? step.endLine : start + 20
  emit('viewDiff', {
    title: step.title || itemTitle,
    file: step.file,
    startLine: start,
    endLine: end,
    nodeType: step.kind === 'frontend' ? 'frontend' : step.kind === 'api' ? 'api' : 'changed',
  })
}

function openApiDiff(item: (typeof items.value)[number]) {
  if (!item.apiFile || !item.apiLine) {
    const apiStep = item.steps.find((s) => s.kind === 'api')
    if (apiStep?.file && apiStep.startLine) {
      openDiff(apiStep, `${item.method} ${item.path}`)
    }
    return
  }
  emit('viewDiff', {
    title: `${item.method} ${item.path}`,
    file: item.apiFile,
    startLine: item.apiLine,
    endLine: item.apiLine + 24,
    nodeType: 'api',
  })
}

async function loadInlineDiff(key: string, step: ImpactAccordionStep) {
  if (!props.jobId || !step.file || !step.startLine || step.kind !== 'change') return
  if (inlineDiff.value[key]?.length) return
  inlineLoading.value = { ...inlineLoading.value, [key]: true }
  try {
    const start = step.startLine
    const end = step.endLine && step.endLine >= start ? step.endLine : start + 16
    const view = await fetchJobCodeDiff(props.jobId, {
      file: step.file,
      start_line: start,
      end_line: end,
      node_type: 'changed',
    })
    inlineDiff.value = { ...inlineDiff.value, [key]: view.lines?.slice(0, 24) ?? [] }
  } catch {
    inlineDiff.value = { ...inlineDiff.value, [key]: [] }
  } finally {
    inlineLoading.value = { ...inlineLoading.value, [key]: false }
  }
}

watch(expanded, (keys) => {
  for (const k of keys) {
    const item = items.value.find((i) => i.key === k)
    const root = item?.steps.find((s) => s.kind === 'change' && s.file && s.startLine)
    if (root) void loadInlineDiff(`${k}:root`, root)
  }
})
</script>

<template>
  <div
    class="graph-wrap impact-accordion-wrap"
    :class="[
      hasItems ? 'graph-wrap--filled' : 'graph-wrap--empty',
      processing && !hasItems && 'graph-wrap--processing',
      showCompactEmpty && 'graph-wrap--compact-empty',
    ]"
  >
    <div v-if="showCompactEmpty" class="topology-compact-hint" role="status">
      <span class="mdi mdi-source-branch topology-compact-hint__icon" aria-hidden="true" />
      <p class="topology-compact-hint__text">{{ compactEmptyText }}</p>
    </div>
    <div v-else-if="!hasItems" class="empty">
      <div class="empty-icon" :class="{ 'empty-icon--spin': processing }" aria-hidden="true">
        <span class="mdi empty-icon__glyph" :class="processing ? 'mdi-loading' : 'mdi-source-branch'" />
      </div>
      <p class="empty-title">{{ emptyTitle }}</p>
      <p class="empty-desc">{{ emptyDesc }}</p>
    </div>

    <div v-show="hasItems" class="graph-stage">
      <header class="graph-headbar">
        <h3 class="graph-headbar__title">{{ panelTitle }}</h3>
        <div class="graph-toolbar impact-accordion-toolbar" aria-label="视图切换">
          <span class="impact-accordion-mode-label">影响链路手风琴</span>
          <label class="graph-toggle">
            <input v-model="showGraphMode" type="checkbox" />
            同时显示 D3 拓扑（实验）
          </label>
        </div>
      </header>

      <div v-if="impactSummary" class="impact-tip-bar" role="status">
        <v-icon icon="mdi-lightbulb-on-outline" size="18" class="impact-tip-bar__icon" />
        <p class="impact-tip-bar__text">
          <template v-if="!impactSummary.hasApis">
            本次变更涉及 {{ impactSummary.fileCountLabel }}，约 {{ impactSummary.totalSymbols }} 处符号。
          </template>
          <template v-else>
            默认收起 {{ items.length }} 条受影响接口；展开后沿 前端 → API → 根因 查看逆向链路。
          </template>
        </p>
      </div>

      <v-expansion-panels v-model="expanded" multiple class="impact-accordion-panels" variant="accordion">
        <v-expansion-panel
          v-for="item in items"
          :key="item.key"
          :value="item.key"
          elevation="0"
          class="impact-accordion-panel"
          :class="{ 'impact-accordion-panel--open': panelExpanded(item.key) }"
        >
          <v-expansion-panel-title
            class="impact-accordion-head"
            expand-icon="mdi-chevron-down"
            collapse-icon="mdi-chevron-up"
          >
            <div class="impact-accordion-head__row">
              <div class="impact-accordion-head__main">
                <span
                  class="http-pill impact-accordion-method"
                  :class="`http-pill--${item.method.toLowerCase()}`"
                >
                  {{ item.method }}
                </span>
                <span class="impact-accordion-path mono">{{ item.path }}</span>
              </div>
              <div class="impact-accordion-head__meta">
                <span class="impact-accordion-summary">{{ summaryText(item) }}</span>
                <v-btn
                  class="impact-accordion-diff-btn text-none"
                  variant="text"
                  size="small"
                  density="comfortable"
                  @click.stop="openApiDiff(item)"
                >
                  查看 Code Diff
                </v-btn>
              </div>
            </div>
          </v-expansion-panel-title>

          <v-expansion-panel-text class="impact-accordion-body">
            <div class="impact-tree">
              <div
                v-for="(step, idx) in item.steps"
                :key="idx"
                class="impact-tree__node"
                :class="[
                  `impact-tree__node--${step.kind}`,
                  idx < item.steps.length - 1 && 'impact-tree__node--has-child',
                ]"
              >
                <div class="impact-tree__connector" aria-hidden="true">
                  <span class="impact-tree__branch-h" />
                  <span class="impact-tree__dot" />
                  <span v-if="idx < item.steps.length - 1" class="impact-tree__branch-v" />
                </div>
                <div class="impact-tree__body">
                  <div class="impact-tree__row">
                    <div class="impact-tree__labels">
                      <div class="impact-tree__primary">
                        <v-icon :icon="stepIcon(step.kind)" size="16" class="impact-tree__type-icon" />
                        <span class="impact-tree__name">{{ step.primary }}</span>
                        <span v-if="step.meta" class="impact-tree__meta mono">{{ step.meta }}</span>
                      </div>
                      <p v-if="step.relation" class="impact-tree__relation">{{ step.relation }}</p>
                    </div>
                    <button
                      v-if="step.file && step.startLine"
                      type="button"
                      class="impact-tree__code-ghost"
                      @click="openDiff(step, item.key)"
                    >
                      查看代码
                    </button>
                  </div>
                  <div
                    v-if="step.kind === 'change' && step.file && step.startLine"
                    class="impact-code-card"
                  >
                    <div class="impact-code-card__toolbar">
                      <span class="impact-code-card__fname mono">{{ step.file }}</span>
                      <button
                        v-if="(inlineDiff[`${item.key}:root`] ?? []).length"
                        type="button"
                        class="impact-code-card__copy"
                        @click="copyInlineDiff(`${item.key}:root`)"
                      >
                        复制
                      </button>
                    </div>
                    <div v-if="inlineLoading[`${item.key}:root`]" class="impact-code-card__loading">
                      加载 Diff 预览…
                    </div>
                    <pre
                      v-else-if="(inlineDiff[`${item.key}:root`] ?? []).length"
                      class="impact-code-card__pre mono"
                    ><code
                      v-for="(ln, li) in inlineDiff[`${item.key}:root`]"
                      :key="li"
                      class="impact-code-card__line"
                      :class="`impact-code-card__line--${ln.kind}`"
                    ><span v-if="ln.line_no != null" class="impact-code-card__gutter">{{ ln.line_no }}</span><span class="impact-code-card__code" v-html="highlightLine(ln.text, ln.kind)" /></code></pre>
                  </div>
                </div>
              </div>
            </div>
          </v-expansion-panel-text>
        </v-expansion-panel>
      </v-expansion-panels>

      <slot v-if="showGraphMode" name="graph" />
    </div>
    <v-snackbar :model-value="!!copyToast" location="bottom" color="surface" :timeout="1800" variant="elevated">
      {{ copyToast }}
    </v-snackbar>
  </div>
</template>

<style scoped>
.topology-compact-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  min-height: 88px;
  max-height: 100px;
  padding: 14px 20px;
  box-sizing: border-box;
}
.topology-compact-hint__icon {
  font-size: 22px;
  line-height: 1;
  color: rgba(255, 255, 255, 0.42);
  flex-shrink: 0;
}
.topology-compact-hint__text {
  margin: 0;
  font-size: 13px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.62);
  line-height: 1.45;
  text-align: left;
}
.impact-accordion-toolbar {
  gap: 12px;
}
.impact-accordion-mode-label {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.45);
}
.impact-tip-bar {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin: 0 16px 8px;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid #2a2a2a;
}
.impact-tip-bar__icon {
  color: rgba(255, 255, 255, 0.38);
  margin-top: 1px;
  flex-shrink: 0;
}
.impact-tip-bar__text {
  margin: 0;
  font-size: 12px;
  line-height: 1.55;
  color: #777;
}
.impact-accordion-panels {
  background: transparent;
  margin: 0;
}
.impact-accordion-panels :deep(.v-expansion-panel) {
  background: #1e2126;
  border: 1px solid #2a2e35;
  border-left: 3px solid transparent;
  border-radius: 12px !important;
  margin: 0 16px 10px;
  overflow: hidden;
  transition: border-color 0.18s ease, background 0.18s ease;
}
.impact-accordion-panel--open {
  border-left-color: #8ab4f8 !important;
  background: #1f2329 !important;
}
.impact-accordion-panels :deep(.v-expansion-panel:first-child) {
  margin-top: 8px;
}
.impact-accordion-panels :deep(.v-expansion-panel-title) {
  padding: 12px 14px;
  min-height: 52px;
  background: #1a1d22;
}
.impact-accordion-panel--open :deep(.v-expansion-panel-title) {
  background: #171a1f;
}
.impact-accordion-panels :deep(.v-expansion-panel-title__icon) {
  color: rgba(255, 255, 255, 0.55);
  background: rgba(255, 255, 255, 0.06);
  border-radius: 50%;
  width: 28px;
  height: 28px;
}
.impact-accordion-panels :deep(.v-expansion-panel-text__wrapper) {
  padding: 0 14px 14px;
}
.impact-accordion-head__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  min-width: 0;
}
.impact-accordion-head__main {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1 1 auto;
}
.impact-accordion-method {
  flex-shrink: 0;
  font-size: 11px;
  border: none !important;
  box-shadow: none !important;
  background: rgba(129, 201, 149, 0.14) !important;
  color: #81c995 !important;
  font-weight: 600;
}
.impact-accordion-method.http-pill--post {
  background: rgba(253, 214, 99, 0.14) !important;
  color: #fdd663 !important;
}
.impact-accordion-method.http-pill--delete {
  background: rgba(242, 139, 130, 0.14) !important;
  color: #f28b82 !important;
}
.impact-accordion-path {
  font-size: 15px;
  font-weight: 700;
  color: #fff;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.impact-accordion-head__meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
  margin-left: 12px;
}
.impact-accordion-summary {
  font-size: 11px;
  color: #777;
  max-width: 200px;
  text-align: right;
  line-height: 1.35;
}
.impact-accordion-diff-btn {
  color: #8ab4f8 !important;
  letter-spacing: 0;
  font-size: 12px;
  font-weight: 600;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.impact-tree {
  padding: 6px 0 2px 4px;
  border-left: 1px solid #333;
  margin-left: 10px;
}
.impact-tree__node {
  display: flex;
  align-items: stretch;
  gap: 0;
  padding-left: 0;
  margin-bottom: 4px;
}
.impact-tree__node--has-child {
  padding-bottom: 6px;
}
.impact-tree__connector {
  position: relative;
  width: 28px;
  flex-shrink: 0;
}
.impact-tree__branch-h {
  position: absolute;
  left: 0;
  top: 14px;
  width: 18px;
  height: 1px;
  background: #333;
}
.impact-tree__dot {
  position: absolute;
  left: 16px;
  top: 10px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  z-index: 1;
}
.impact-tree__node--frontend .impact-tree__dot {
  background: #81c995;
}
.impact-tree__node--api .impact-tree__dot {
  background: #8ab4f8;
}
.impact-tree__node--change .impact-tree__dot {
  background: #fdd663;
}
.impact-tree__branch-v {
  position: absolute;
  left: 16px;
  top: 18px;
  bottom: -8px;
  width: 1px;
  background: #333;
}
.impact-tree__body {
  flex: 1;
  min-width: 0;
  padding-left: 40px;
  padding-bottom: 12px;
}
.impact-tree__row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  column-gap: 12px;
}
.impact-tree__type-icon {
  opacity: 0.7;
  flex-shrink: 0;
}
.impact-tree__node--frontend .impact-tree__type-icon {
  color: #81c995;
}
.impact-tree__node--api .impact-tree__type-icon {
  color: #8ab4f8;
}
.impact-tree__node--change .impact-tree__type-icon {
  color: #fdd663;
}
.impact-tree__labels {
  flex: 1;
  min-width: 0;
}
.impact-tree__primary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.impact-tree__name {
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  line-height: 1.35;
}
.impact-tree__meta {
  font-size: 11px;
  color: #6b7280;
}
.impact-tree__relation {
  margin: 4px 0 0;
  padding-left: 24px;
  font-size: 12px;
  line-height: 1.45;
  color: #5c6370;
}
.impact-tree__code-ghost {
  flex-shrink: 0;
  height: 28px;
  padding: 0 10px;
  border: 1px solid #3a3f47;
  border-radius: 999px;
  background: transparent;
  color: #8ab4f8;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
  cursor: pointer;
  white-space: nowrap;
  transition:
    background 0.15s ease,
    border-color 0.15s ease;
}
.impact-tree__code-ghost:hover {
  background: rgba(138, 180, 248, 0.1);
  border-color: rgba(138, 180, 248, 0.45);
}
.impact-code-card {
  margin-top: 10px;
  border: 1px solid #333;
  border-radius: 6px;
  background: #0d0d0d;
  overflow: hidden;
  max-height: 240px;
}
.impact-code-card__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 10px;
  border-bottom: 1px solid #2a2a2a;
  background: #161616;
}
.impact-code-card__fname {
  font-size: 11px;
  color: #777;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.impact-code-card__copy {
  border: none;
  background: none;
  font-size: 11px;
  color: #8ab4f8;
  cursor: pointer;
  flex-shrink: 0;
}
.impact-code-card__copy:hover {
  text-decoration: underline;
}
.impact-code-card__loading {
  padding: 12px;
  font-size: 12px;
  color: #777;
}
.impact-code-card__pre {
  margin: 0;
  padding: 0;
  overflow: auto;
  max-height: 200px;
  font-size: 12px;
  line-height: 1.5;
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, 'Cascadia Code', Consolas, monospace;
}
.impact-code-card__line {
  display: flex;
  min-height: 1.5em;
}
.impact-code-card__gutter {
  flex: 0 0 3rem;
  padding: 0 8px 0 6px;
  margin-right: 8px;
  text-align: right;
  color: #4b5263;
  user-select: none;
  border-right: 1px solid #333;
  background: #0d0d0d;
}
.impact-code-card__code {
  flex: 1;
  padding: 0 10px 0 0;
  color: #e6e8eb;
  white-space: pre-wrap;
  word-break: break-word;
}
.impact-code-card__line--add .impact-code-card__code {
  background: rgba(152, 195, 121, 0.1);
  color: #98c379;
}
.impact-code-card__line--del .impact-code-card__code {
  background: rgba(224, 108, 117, 0.1);
  color: #e06c75;
}
.impact-code-card__code :deep(.tok-kw) {
  color: #c678dd;
}
.impact-code-card__code :deep(.tok-str) {
  color: #98c379;
}
</style>