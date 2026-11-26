<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import hljs from 'highlight.js/lib/core'
import python from 'highlight.js/lib/languages/python'
import typescript from 'highlight.js/lib/languages/typescript'
import javascript from 'highlight.js/lib/languages/javascript'
import { fetchJobCodeDiff } from '@/api/client'
import type { CodeDiffLine, CodeDiffView, GraphNodeType } from '@/api/types'
import 'highlight.js/styles/atom-one-dark.css'

hljs.registerLanguage('python', python)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('javascript', javascript)

const props = withDefaults(
  defineProps<{
    jobId: string
    open: boolean
    title?: string
    file?: string
    startLine?: number
    endLine?: number
    nodeType?: GraphNodeType
    highlight?: string
    impactPath?: string
    repo?: string
    headSha?: string
    showBack?: boolean
    backLabel?: string
  }>(),
  {
    showBack: false,
    backLabel: '返回未解析列表',
  },
)

const roleBadge = computed(() => {
  const t = props.nodeType
  if (t === 'api') return { label: '受影响接口', class: 'cdd-role--api' }
  if (t === 'changed') return { label: '直接变更函数', class: 'cdd-role--changed' }
  if (t === 'frontend') return { label: '前端调用方', class: 'cdd-role--frontend' }
  return { label: '上游方法', class: 'cdd-role--symbol' }
})

const headFileName = computed(() => {
  if (props.title?.trim()) return props.title.trim()
  const f = props.file?.replace(/\\/g, '/') ?? ''
  const parts = f.split('/')
  return parts[parts.length - 1] || '代码详情'
})

const emit = defineEmits<{ 'update:open': [boolean]; back: [] }>()

const loading = ref(false)
const view = ref<CodeDiffView | null>(null)
const error = ref('')

const emptyMessage = computed(() => {
  const reason = view.value?.empty_reason
  if (reason === 'workspace_missing') {
    return '本地分析工作区不存在（可能被新一轮分析清理）。请对该仓库再跑一次分析后重试。'
  }
  if (reason === 'file_not_found') {
    return `找不到文件 ${view.value?.file || props.file}。请确认图节点路径与仓库 scan_root 一致。`
  }
  if (reason === 'range_empty') {
    return '该文件已找到，但当前行号区间内没有可展示内容。'
  }
  return '该范围内暂无可用代码片段。若分析已完成仍为空，请重启 API（run_api.ps1）并重新打开抽屉。'
})

const pathRangeLine = computed(() => {
  const file = view.value?.file || props.file
  if (!file) return ''
  const s = view.value?.start_line ?? props.startLine
  const e = view.value?.end_line ?? props.endLine
  const range = s && e ? ` · L${s}-L${e}` : ''
  return `${file}${range}`
})

const githubCompareUrl = computed(() => {
  if (!props.repo || !props.headSha) return ''
  const [owner, name] = props.repo.split('/')
  if (!owner || !name) return ''
  return `https://github.com/${owner}/${name}/commit/${props.headSha}`
})

function close() {
  emit('update:open', false)
}

function goBack() {
  emit('back')
}

async function load() {
  if (!props.open || !props.file?.trim() || !props.startLine || !props.endLine) return
  loading.value = true
  error.value = ''
  view.value = null
  try {
    view.value = await fetchJobCodeDiff(props.jobId, {
      file: props.file,
      start_line: props.startLine,
      end_line: props.endLine,
      node_type: props.nodeType ?? 'symbol',
      highlight: props.highlight,
    })
  } catch (e: unknown) {
    view.value = null
    const ax = e as { response?: { status?: number; data?: { detail?: string } }; message?: string }
    const detail = ax.response?.data?.detail
    if (detail) {
      error.value = detail
    } else if (ax.response?.status === 404) {
      error.value = '接口不可用（请重启后端 API 后重试）'
    } else {
      error.value = ax.message ?? '加载失败'
    }
  } finally {
    loading.value = false
  }
}

function copyAll() {
  const text = (view.value?.lines ?? []).map((l) => l.text).join('\n')
  if (text) void navigator.clipboard.writeText(text)
}

function isRiskLine(line: CodeDiffLine) {
  if (!line.line_no || !view.value?.highlight_lines?.length) return false
  return view.value.highlight_lines.includes(line.line_no)
}

function isFocusLine(line: CodeDiffLine) {
  const ln = line.line_no
  if (!ln || !props.startLine) return false
  return props.nodeType === 'frontend' && ln === props.startLine
}

function langForFile(file?: string) {
  const f = (file || '').toLowerCase()
  if (f.endsWith('.py')) return 'python'
  if (f.endsWith('.ts') || f.endsWith('.tsx')) return 'typescript'
  if (f.endsWith('.js') || f.endsWith('.jsx') || f.endsWith('.vue')) return 'javascript'
  return 'python'
}

function highlightedCode(text: string) {
  const raw = text || ' '
  const lang = langForFile(view.value?.file || props.file)
  try {
    return hljs.highlight(raw, { language: lang }).value
  } catch {
    return raw
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
  }
}

function gutterMark(line: CodeDiffLine) {
  if (line.kind === 'add') return '+'
  if (line.kind === 'del') return '−'
  return ''
}

watch(
  () => [props.open, props.file, props.startLine, props.endLine, props.nodeType, props.highlight],
  () => {
    if (props.open) void load()
  },
  { immediate: true },
)
</script>

<template>
  <el-drawer
    :model-value="open"
    direction="rtl"
    size="min(94vw, 600px)"
    class="code-diff-drawer"
    modal-class="code-diff-drawer-overlay"
    :with-header="false"
    :modal="true"
    :lock-scroll="true"
    append-to-body
    @update:model-value="emit('update:open', $event)"
  >
    <div class="cdd-shell">
      <div class="cdd-top">
      <header class="cdd-head">
        <div class="cdd-head__nav">
          <button v-if="showBack" type="button" class="cdd-back-text" @click="goBack">
            <span class="mdi mdi-chevron-left" aria-hidden="true" />
            {{ backLabel }}
          </button>
          <span v-else class="cdd-head__nav-spacer" />
          <div class="cdd-head__icon-actions">
            <button type="button" class="cdd-icon-btn" title="复制代码" aria-label="复制代码" @click="copyAll">
              <span class="mdi mdi-content-copy" aria-hidden="true" />
            </button>
            <a
              v-if="githubCompareUrl"
              class="cdd-icon-btn"
              :href="githubCompareUrl"
              target="_blank"
              rel="noopener noreferrer"
              title="在 GitHub 查看"
              aria-label="在 GitHub 查看"
            >
              <span class="mdi mdi-github" aria-hidden="true" />
            </a>
            <button type="button" class="cdd-icon-btn" title="关闭" aria-label="关闭" @click="close">
              <span class="mdi mdi-close" aria-hidden="true" />
            </button>
          </div>
        </div>
        <div class="cdd-head__title-row">
          <h2 class="cdd-head__title">{{ headFileName }}</h2>
          <span class="cdd-role-badge" :class="roleBadge.class">{{ roleBadge.label }}</span>
          <span v-if="view?.source_label" class="cdd-source-badge">{{ view.source_label }}</span>
        </div>
        <p v-if="impactPath" class="cdd-impact-path">{{ impactPath }}</p>
        <p v-if="pathRangeLine" class="cdd-head__sub mono">{{ pathRangeLine }}</p>
      </header>
      <p v-if="view?.hint" class="cdd-hint">{{ view.hint }}</p>
      </div>

      <div v-loading="loading" class="cdd-body">
        <p v-if="error" class="cdd-error">{{ error }}</p>
        <div v-else-if="view?.lines?.length" class="cdd-code-panel">
          <pre class="cdd-pre"><code
            v-for="(line, idx) in view.lines"
            :key="idx"
            class="cdd-line"
            :class="{
              'cdd-line--add': line.kind === 'add',
              'cdd-line--del': line.kind === 'del',
              'cdd-line--focus': isFocusLine(line),
              'cdd-line--risk': isRiskLine(line) && !isFocusLine(line),
            }"
          >
            <span class="cdd-gutter">{{ gutterMark(line) }}</span>
            <span class="cdd-ln" :class="{ 'cdd-ln--focus': isFocusLine(line) }">
              {{ line.line_no ?? ' ' }}
            </span>
            <span class="cdd-code hljs" v-html="highlightedCode(line.text)" />
            <span v-if="isFocusLine(line)" class="cdd-focus-tag">← 接口调用行</span>
            <span v-else-if="isRiskLine(line)" class="cdd-risk-tag">← 风险调用点</span>
          </code></pre>
        </div>
        <div v-else-if="!loading" class="cdd-empty-wrap">
          <p class="cdd-empty">{{ emptyMessage }}</p>
          <button type="button" class="cdd-action cdd-empty-retry" @click="load">重新加载</button>
        </div>
      </div>
    </div>
  </el-drawer>
</template>

<style scoped>
.code-diff-drawer :deep(.el-drawer) {
  background: #000000 !important;
  color: #e8eaed;
  border-left: 1px solid #1f1f1f;
  box-shadow: -12px 0 32px rgba(0, 0, 0, 0.35);
  height: 100vh;
  max-height: 100vh;
}
.code-diff-drawer :deep(.el-overlay) {
  background-color: rgba(0, 0, 0, 0.45);
}
.code-diff-drawer :deep(.el-drawer__body) {
  display: flex;
  flex-direction: column;
  height: 100%;
  max-height: 100vh;
  min-height: 0;
  padding: 0 !important;
  margin: 0;
  background: #000000 !important;
  color: #e8eaed;
  overflow: hidden !important;
}
.code-diff-drawer :deep(.el-loading-mask) {
  background-color: rgba(0, 0, 0, 0.65);
}
.cdd-shell {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
  height: 100%;
  max-height: 100%;
  overflow: hidden;
  background: #000000;
}
.cdd-top {
  flex: 0 0 auto;
  flex-shrink: 0;
  z-index: 2;
  background: #000000;
}
.cdd-head {
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex-shrink: 0;
  padding: 14px 16px 12px;
  border-bottom: 1px solid #1f1f1f;
  background: #000000;
}
.cdd-head__nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 32px;
}
.cdd-head__nav-spacer {
  flex: 1;
}
.cdd-back-text {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  margin: 0;
  padding: 4px 6px 4px 2px;
  border: none;
  background: transparent;
  color: #fdba74;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
}
.cdd-back-text:hover {
  color: #fed7aa;
}
.cdd-back-text .mdi {
  font-size: 20px;
  line-height: 1;
}
.cdd-head__icon-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.cdd-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid #3c4043;
  border-radius: 8px;
  background: #252930;
  color: #c4c7c5;
  text-decoration: none;
  cursor: pointer;
}
.cdd-icon-btn:hover {
  border-color: #5f6368;
  color: #f1f3f5;
}
.cdd-icon-btn .mdi {
  font-size: 18px;
  line-height: 1;
}
.cdd-head__title-row {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.cdd-head__title {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  color: #f1f3f5;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 1;
  min-width: 0;
}
.cdd-role-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
  white-space: nowrap;
  flex-shrink: 0;
}
.cdd-role--api {
  color: #f87171;
  background: rgba(248, 113, 113, 0.12);
  border: 1px solid rgba(248, 113, 113, 0.35);
  box-shadow: 0 0 12px rgba(248, 113, 113, 0.15);
}
.cdd-role--changed {
  color: #fbbf24;
  background: rgba(251, 191, 36, 0.12);
  border: 1px solid rgba(251, 191, 36, 0.35);
  box-shadow: 0 0 10px rgba(251, 191, 36, 0.12);
}
.cdd-role--symbol {
  color: #8ab4f8;
  background: rgba(138, 180, 248, 0.12);
  border: 1px solid rgba(138, 180, 248, 0.32);
}
.cdd-role--frontend {
  color: #81c995;
  background: rgba(129, 201, 149, 0.12);
  border: 1px solid rgba(129, 201, 149, 0.35);
}
.cdd-impact-path {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.45;
  color: rgba(253, 214, 99, 0.88);
}
.cdd-source-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.72);
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.12);
  white-space: nowrap;
  flex-shrink: 0;
}
.cdd-head__sub {
  margin: 6px 0 0;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.52);
}
.cdd-action {
  border: 1px solid #3c4043;
  background: #252930;
  color: #c4c7c5;
  font-size: 12px;
  padding: 6px 10px;
  border-radius: 8px;
  text-decoration: none;
  cursor: pointer;
}
.cdd-action:hover {
  border-color: #5f6368;
  color: #f1f3f5;
}
.cdd-hint {
  margin: 0;
  flex-shrink: 0;
  padding: 10px 18px;
  font-size: 12px;
  color: rgba(253, 214, 99, 0.88);
  background: rgba(253, 214, 99, 0.06);
  border-bottom: 1px solid rgba(253, 214, 99, 0.12);
}
.cdd-body {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 12px 0 0;
  background: #000000;
  overflow: hidden;
}
.cdd-body :deep(.el-loading-mask) {
  border-radius: 10px;
  margin: 0 14px 16px;
}
.cdd-code-panel {
  flex: 1 1 auto;
  margin: 0 14px 16px;
  border: 1px solid #1a1a1a;
  border-radius: 10px;
  background: #000000;
  overflow-x: auto;
  overflow-y: auto;
  min-height: 0;
  max-height: 100%;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 255, 255, 0.16) transparent;
}
.cdd-pre {
  margin: 0;
  padding: 4px 0 8px;
  font-family: 'Roboto Mono', ui-monospace, 'Cascadia Code', Consolas, monospace;
  font-size: 12px;
  line-height: 20px;
  color: #e8eaed;
  width: max-content;
  min-width: 100%;
  box-sizing: border-box;
}
.cdd-line {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 2px 12px;
  white-space: nowrap;
  min-height: 20px;
  line-height: 20px;
}
.cdd-gutter {
  flex: 0 0 1.1em;
  text-align: center;
  color: rgba(255, 255, 255, 0.28);
  user-select: none;
  font-weight: 700;
  font-size: 11px;
}
.cdd-line--add .cdd-gutter {
  color: #3fb950;
}
.cdd-line--del .cdd-gutter {
  color: #f85149;
}
.cdd-ln {
  flex: 0 0 3.4em;
  padding: 0 10px 0 4px;
  text-align: right;
  color: rgba(255, 255, 255, 0.28);
  user-select: none;
  border-right: 1px solid rgba(255, 255, 255, 0.06);
  margin-right: 10px;
  background: rgba(0, 0, 0, 0.22);
}
.cdd-code {
  flex: 0 1 auto;
  min-width: 0;
  white-space: pre;
  overflow-x: visible;
  word-break: normal;
  background: transparent !important;
  padding: 0;
}
.cdd-code :deep(.hljs) {
  background: transparent;
  padding: 0;
}
.cdd-line--add {
  background: rgba(46, 160, 67, 0.18);
}
.cdd-line--add .cdd-ln {
  background: rgba(46, 160, 67, 0.1);
}
.cdd-line--del {
  background: rgba(248, 81, 73, 0.18);
}
.cdd-line--del .cdd-ln {
  background: rgba(248, 81, 73, 0.1);
}
.cdd-line--risk {
  background: rgba(210, 153, 34, 0.16);
  box-shadow: inset 3px 0 0 #d29922;
}
.cdd-line--risk .cdd-ln {
  background: rgba(210, 153, 34, 0.1);
}
.cdd-line--focus {
  background: rgba(251, 191, 36, 0.14);
  box-shadow: inset 3px 0 0 #fbbf24;
}
.cdd-ln--focus {
  position: relative;
  font-weight: 600;
  color: #fde68a;
  background: rgba(251, 191, 36, 0.12) !important;
}
.cdd-ln--focus::before {
  content: '';
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-right: 6px;
  border-radius: 50%;
  background: #fbbf24;
  vertical-align: middle;
  box-shadow: 0 0 6px rgba(251, 191, 36, 0.65);
}
.cdd-focus-tag,
.cdd-risk-tag {
  flex: 0 0 auto;
  margin-left: 12px;
  padding: 1px 8px;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 600;
  white-space: nowrap;
}
.cdd-focus-tag {
  color: #fde68a;
  background: rgba(251, 191, 36, 0.12);
  border: 1px solid rgba(251, 191, 36, 0.28);
}
.cdd-risk-tag {
  color: #e3b341;
  background: rgba(210, 153, 34, 0.12);
  border: 1px solid rgba(210, 153, 34, 0.28);
}
.cdd-empty-wrap {
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 12px;
}
.cdd-error,
.cdd-empty {
  margin: 0;
  font-size: 13px;
  line-height: 1.55;
  color: rgba(255, 255, 255, 0.58);
}
.cdd-empty-retry {
  margin: 0;
}
</style>

<style>
.code-diff-drawer-overlay {
  background-color: rgba(0, 0, 0, 0.52) !important;
  backdrop-filter: blur(2px);
}
.el-drawer.code-diff-drawer {
  position: fixed !important;
  top: 0;
  right: 0;
  display: flex !important;
  flex-direction: column !important;
  height: 100vh !important;
  max-height: 100vh !important;
  z-index: 3000;
  background: #000000 !important;
  box-shadow: -16px 0 40px rgba(0, 0, 0, 0.55);
  overflow: hidden !important;
}
.el-drawer.code-diff-drawer .el-drawer__body {
  display: flex !important;
  flex-direction: column !important;
  flex: 1 1 auto !important;
  min-height: 0 !important;
  max-height: 100% !important;
  height: auto !important;
  overflow: hidden !important;
  padding: 0 !important;
}
</style>