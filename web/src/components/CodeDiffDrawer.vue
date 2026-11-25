<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { fetchJobCodeDiff } from '@/api/client'
import type { CodeDiffView, GraphNodeType } from '@/api/types'

const props = defineProps<{
  jobId: string
  open: boolean
  title?: string
  file?: string
  startLine?: number
  endLine?: number
  nodeType?: GraphNodeType
  highlight?: string
  repo?: string
  headSha?: string
}>()

const emit = defineEmits<{ 'update:open': [boolean] }>()

const loading = ref(false)
const view = ref<CodeDiffView | null>(null)
const error = ref('')

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

async function load() {
  if (!props.open || !props.file || !props.startLine || !props.endLine) return
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

watch(
  () => [props.open, props.file, props.startLine, props.endLine, props.nodeType, props.highlight],
  () => {
    if (props.open) void load()
  },
)
</script>

<template>
  <el-drawer
    :model-value="open"
    direction="rtl"
    size="620px"
    class="code-diff-drawer"
    :with-header="false"
    @update:model-value="emit('update:open', $event)"
  >
    <header class="cdd-head">
      <div class="cdd-head__main">
        <p class="cdd-head__title">{{ title || pathRangeLine || '代码详情' }}</p>
        <p v-if="pathRangeLine" class="cdd-head__sub mono">{{ pathRangeLine }}</p>
      </div>
      <div class="cdd-head__actions">
        <button type="button" class="cdd-action" @click="copyAll">复制代码</button>
        <a
          v-if="githubCompareUrl"
          class="cdd-action"
          :href="githubCompareUrl"
          target="_blank"
          rel="noopener noreferrer"
        >
          在 GitHub 查看
        </a>
        <button
          type="button"
          class="cdd-close"
          aria-label="关闭"
          title="关闭"
          @click="close"
        >
          <span class="mdi mdi-close" aria-hidden="true" />
        </button>
      </div>
    </header>

    <p v-if="view?.hint" class="cdd-hint">{{ view.hint }}</p>

    <div v-loading="loading" class="cdd-body">
      <p v-if="error" class="cdd-error">{{ error }}</p>
      <pre v-else-if="view?.lines?.length" class="cdd-pre mono"><code
        v-for="(line, idx) in view.lines"
        :key="idx"
        class="cdd-line"
        :class="{
          'cdd-line--add': line.kind === 'add',
          'cdd-line--del': line.kind === 'del',
          'cdd-line--hi':
            line.line_no && (view.highlight_lines || []).includes(line.line_no),
        }"
      ><span class="cdd-ln">{{ line.line_no ?? ' ' }}</span>{{ line.text }}
</code></pre>
      <p v-else-if="!loading" class="cdd-empty">该范围内暂无可用代码片段，请确认分析任务已完成且仓库已拉取。</p>
    </div>
  </el-drawer>
</template>

<style scoped>
.code-diff-drawer :deep(.el-drawer) {
  background: #14171a;
  color: #e8eaed;
  border-left: 1px solid #2a2e35;
  box-shadow: -12px 0 32px rgba(0, 0, 0, 0.35);
}
.code-diff-drawer :deep(.el-drawer__body) {
  padding: 0;
  background: #14171a;
  color: #e8eaed;
}
.code-diff-drawer :deep(.el-loading-mask) {
  background-color: rgba(20, 23, 26, 0.72);
}
.cdd-head {
  display: flex;
  gap: 12px;
  justify-content: space-between;
  align-items: flex-start;
  padding: 16px 18px;
  border-bottom: 1px solid #2a2e35;
  background: #14171a;
}
.cdd-head__title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: #f1f3f5;
}
.cdd-head__sub {
  margin: 6px 0 0;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.52);
}
.cdd-head__actions {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 8px;
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
.cdd-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1px solid #3c4043;
  border-radius: 50%;
  background: #252930;
  color: #e8eaed;
  cursor: pointer;
  flex-shrink: 0;
}
.cdd-close:hover {
  border-color: #8ab4f8;
  color: #fff;
}
.cdd-close .mdi {
  font-size: 18px;
  line-height: 1;
}
.cdd-hint {
  margin: 0;
  padding: 10px 18px;
  font-size: 12px;
  color: rgba(253, 214, 99, 0.88);
  background: rgba(253, 214, 99, 0.06);
  border-bottom: 1px solid rgba(253, 214, 99, 0.12);
}
.cdd-body {
  min-height: 240px;
  padding: 12px 0;
  background: #14171a;
}
.cdd-pre {
  margin: 0;
  font-size: 12px;
  line-height: 1.55;
  color: #e8eaed;
  overflow: auto;
  max-height: calc(100vh - 160px);
}
.cdd-line {
  display: block;
  padding: 0 16px;
  white-space: pre-wrap;
  word-break: break-word;
}
.cdd-ln {
  display: inline-block;
  width: 3.2em;
  margin-right: 12px;
  text-align: right;
  color: rgba(255, 255, 255, 0.35);
  user-select: none;
}
.cdd-line--add {
  background: rgba(52, 168, 83, 0.16);
}
.cdd-line--del {
  background: rgba(234, 67, 53, 0.16);
}
.cdd-line--hi {
  background: rgba(253, 214, 99, 0.12);
  box-shadow: inset 3px 0 0 #fdd663;
}
.cdd-error,
.cdd-empty {
  margin: 0;
  padding: 16px 18px;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.58);
}
</style>