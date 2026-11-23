<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import CallGraphG6 from '@/components/CallGraphG6.vue'
import { fetchJob, fetchJobGraph } from '@/api/client'
import type { JobDetail, JobGraph, JobStatus } from '@/api/types'

const props = defineProps<{ id: string }>()
const router = useRouter()

const job = ref<JobDetail | null>(null)
const graph = ref<JobGraph | null>(null)
const loading = ref(false)
let timer: number | undefined
let pollTicks = 0
const POLL_MS = 2500
const MAX_POLL_TICKS = 48

function graphReady(g: JobGraph | null) {
  return Boolean(g?.nodes?.length)
}

function jobHasImpact(j: JobDetail) {
  return (
    (j.changed_symbols?.symbols?.length ?? 0) > 0 ||
    (j.changed_symbols?.suspects?.length ?? 0) > 0 ||
    (j.affected_apis?.apis?.length ?? 0) > 0 ||
    (j.affected_apis?.call_paths?.length ?? 0) > 0
  )
}

async function tryLoadGraph() {
  try {
    const g = await fetchJobGraph(props.id)
    if (graphReady(g)) {
      graph.value = g
      return true
    }
  } catch {
    /* 图数据可能尚未写入，下一轮轮询再试 */
  }
  return false
}

function shouldPoll(): boolean {
  const j = job.value
  if (!j) return pollTicks < MAX_POLL_TICKS
  if (j.status === 'pending' || j.status === 'running') return true
  if (j.status === 'failed') return false
  if (j.status === 'completed') {
    if (graphReady(graph.value)) return false
    if (jobHasImpact(j)) return pollTicks < MAX_POLL_TICKS
    return pollTicks < 8
  }
  return false
}

function reconcilePoll() {
  clearPoll()
  if (!shouldPoll()) return
  timer = window.setInterval(() => {
    pollTicks += 1
    if (pollTicks > MAX_POLL_TICKS) {
      clearPoll()
      return
    }
    void load(true)
  }, POLL_MS)
}

const apis = computed(() => job.value?.affected_apis?.apis ?? [])
const callPaths = computed(
  () => job.value?.affected_apis?.call_paths ?? [],
)
const suspects = computed(() => job.value?.changed_symbols?.suspects ?? [])
const symbols = computed(() => job.value?.changed_symbols?.symbols ?? [])

const STATUS_LABEL: Record<JobStatus, string> = {
  pending: '排队中',
  running: '分析中',
  completed: '已完成',
  failed: '失败',
}

const statusLabel = computed(() => {
  const s = job.value?.status
  if (!s) return '—'
  return STATUS_LABEL[s] ?? s
})

function shortSha(sha: string) {
  return sha?.slice(0, 8) ?? '—'
}

const commitRange = computed(() => {
  const j = job.value
  if (!j?.base_sha || !j?.head_sha) return '—'
  return `${shortSha(j.base_sha)} → ${shortSha(j.head_sha)}`
})

const isEmptyImpact = computed(() => {
  const j = job.value
  return Boolean(j && j.status === 'completed' && !jobHasImpact(j))
})

const emptyImpactNotice = computed(() => {
  const j = job.value
  if (!isEmptyImpact.value || !j) return null
  const ds = j.changed_symbols?.diff_summary
  const range = commitRange.value
  if (ds && ds.python_files === 0 && ds.other_files > 0) {
    return `分析已完成（${range}）。本次 diff 无 .py 变更，仅有 ${ds.other_files} 个非 Python 文件，无法生成 AST 影响面。`
  }
  if (ds && ds.python_files === 0 && ds.other_files === 0) {
    return `分析已完成（${range}）。对比范围内无文件差异。`
  }
  return `分析已完成（${range}），但未检测到可映射的 Python 变更行。`
})

const graphEmptyTitle = computed(() =>
  isEmptyImpact.value ? '本次无可展示的调用链拓扑' : '暂无调用链子图',
)

const graphEmptyDesc = computed(() => {
  if (!isEmptyImpact.value) return '任务完成后生成变更影响拓扑'
  const ds = job.value?.changed_symbols?.diff_summary
  if (ds && ds.python_files === 0) {
    return '本次提交仅涉及非 Python 文件或无函数级逻辑变更，系统已自动判定为零接口风险。'
  }
  return '未在变更行中定位到可分析的 Python 符号。'
})

const showZeroRiskAutoPass = computed(() => isEmptyImpact.value)

function goRegression() {
  void router.push({ name: 'regression', query: { job: props.id } })
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    job.value = await fetchJob(props.id)
    if (job.value.status === 'completed') {
      await tryLoadGraph()
    }
    if (job.value.status === 'failed') {
      clearPoll()
      return
    }
    reconcilePoll()
  } finally {
    if (!silent) loading.value = false
  }
}

function clearPoll() {
  if (timer) window.clearInterval(timer)
  timer = undefined
}

function resetForJob() {
  clearPoll()
  pollTicks = 0
  job.value = null
  graph.value = null
}

watch(
  () => props.id,
  () => {
    resetForJob()
    void load()
  },
)

onMounted(() => {
  void load()
})

onUnmounted(clearPoll)
</script>

<template>
  <div v-loading="loading" class="page job-detail-page">
    <div class="job-page-head">
      <el-page-header class="job-page-header" @back="$router.push('/analysis')">
        <template #content>
          <span class="mono job-page-title">{{ job?.repo ?? props.id }}</span>
        </template>
      </el-page-header>
      <button
        v-if="job?.status === 'completed'"
        type="button"
        class="job-regression-cta text-none"
        @click="goRegression"
      >
        查看精准回归
        <span class="job-regression-cta__arrow" aria-hidden="true">→</span>
      </button>
    </div>

    <div class="job-meta-card">
      <div class="job-meta-grid">
        <div class="job-meta-item">
          <span class="job-meta-item__label">状态</span>
          <span
            class="job-status-badge"
            :class="job?.status ? `job-status-badge--${job.status}` : 'job-status-badge--pending'"
          >
            {{ statusLabel }}
          </span>
        </div>
        <div class="job-meta-item">
          <span class="job-meta-item__label">影响 API</span>
          <span class="job-meta-item__value">{{ apis.length }}</span>
        </div>
        <div class="job-meta-item">
          <span class="job-meta-item__label">变更符号</span>
          <span class="job-meta-item__value">{{ symbols.length }}</span>
        </div>
        <div class="job-meta-item job-meta-item--branch">
          <span class="job-meta-item__label">分支 & 对比范围</span>
          <span class="job-meta-item__value">{{ job?.ref ?? '—' }}</span>
          <span class="job-meta-item__range mono">{{ commitRange }}</span>
        </div>
      </div>
    </div>

    <el-alert
      v-if="job?.error_message"
      type="error"
      :title="job.error_message"
      show-icon
      :closable="false"
      class="mb"
    />
    <div v-else-if="emptyImpactNotice" class="job-tonal-alert mb" role="status">
      <span class="job-tonal-alert__icon mdi mdi-information-outline" aria-hidden="true" />
      <p class="job-tonal-alert__text">{{ emptyImpactNotice }}</p>
      <aside v-if="showZeroRiskAutoPass" class="job-tonal-alert__aside">
        <span class="job-pass-badge">质量门禁自动放行 (PASS)</span>
        <span class="job-pass-sub">非业务代码变更，已跳过冗余回归</span>
      </aside>
    </div>

    <section class="job-detail-block">
      <h3 class="job-section__title">变更影响拓扑</h3>
      <CallGraphG6
        :data="graph"
        :empty-title="graphEmptyTitle"
        :empty-desc="graphEmptyDesc"
      />
    </section>

    <el-row :gutter="16" class="lists job-detail-tables">
      <el-col :span="12">
        <h3 class="job-section__title">受影响顶层接口</h3>
        <div class="job-panel job-panel--table">
          <el-table :data="callPaths" size="small" stripe empty-text="暂无受影响 API，或未生成追溯链路">
            <el-table-column prop="method" label="方法" width="80" />
            <el-table-column prop="path" label="接口" min-width="140" show-overflow-tooltip />
            <el-table-column label="调用链" min-width="200">
              <template #default="{ row }">
                <span class="chain">{{ row.chain_labels.join(' → ') }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="layers" label="层数" width="64" />
          </el-table>
        </div>
      </el-col>
      <el-col :span="12">
        <h3 class="job-section__title">初始变更函数明细</h3>
        <div class="job-panel job-panel--table">
          <el-table
            :data="suspects"
            size="small"
            stripe
            max-height="280"
            empty-text="无 Git 命中时展示变更符号列表"
          >
            <el-table-column prop="qualified_name" label="函数" show-overflow-tooltip />
            <el-table-column label="行号" width="108">
              <template #default="{ row }">{{ row.start_line }}-{{ row.end_line }}</template>
            </el-table-column>
          </el-table>
          <el-scrollbar v-if="!suspects.length && symbols.length" height="120px" class="job-sym-scroll">
            <ul class="sym-list">
              <li v-for="s in symbols" :key="s">{{ s }}</li>
            </ul>
          </el-scrollbar>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.job-page-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px 16px;
}
.job-page-header {
  flex: 1 1 auto;
  min-width: 0;
}
.job-page-title {
  font-size: 1.05rem;
  font-weight: 600;
}
.job-regression-cta {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 40px;
  padding: 0 18px;
  border: none;
  border-radius: 999px;
  background: #f1f3f5;
  color: #111315;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.28);
  transition: background 0.15s ease;
}
.job-regression-cta:hover {
  background: #e8eaed;
}
.job-regression-cta__arrow {
  font-weight: 600;
  opacity: 0.85;
}
.job-meta-card {
  margin-top: 4px;
  padding: 16px 20px;
  background: #1a1d21;
  border: 1px solid #2a2e35;
  border-radius: 16px;
  box-sizing: border-box;
}
.job-meta-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px 20px;
}
.job-meta-item__label {
  display: block;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.55);
  margin-bottom: 6px;
}
.job-meta-item__value {
  font-size: 1.375rem;
  font-weight: 600;
  color: #f1f3f5;
  font-variant-numeric: tabular-nums;
}
.job-meta-item--branch .job-meta-item__value {
  font-size: 1.125rem;
}
.job-meta-item__range {
  display: block;
  margin-top: 6px;
  font-size: 12px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.48);
  letter-spacing: 0.02em;
}
.job-tonal-alert {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 12px 16px;
  padding: 12px 16px;
  border-radius: 12px;
  background: rgba(138, 180, 248, 0.08);
  border: 1px solid rgba(138, 180, 248, 0.25);
}
.job-tonal-alert__text {
  flex: 1 1 12rem;
}
.job-tonal-alert__aside {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  margin-left: auto;
  text-align: right;
  flex: 0 1 auto;
}
.job-pass-badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  color: #81c995;
  background: rgba(129, 201, 149, 0.14);
  border: 1px solid rgba(129, 201, 149, 0.35);
  white-space: nowrap;
}
.job-pass-sub {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.48);
  max-width: 14rem;
  line-height: 1.4;
}
.job-tonal-alert__icon {
  flex-shrink: 0;
  font-size: 20px;
  line-height: 1.4;
  color: #8ab4f8;
}
.job-tonal-alert__text {
  margin: 0;
  font-size: 13px;
  line-height: 1.55;
  color: #c4c7c5;
}
.job-status-badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.2;
}
.job-status-badge--completed {
  background: rgba(129, 201, 149, 0.18);
  color: #81c995;
  border: 1px solid rgba(129, 201, 149, 0.35);
}
.job-status-badge--running {
  background: rgba(138, 180, 248, 0.15);
  color: #8ab4f8;
  border: 1px solid rgba(138, 180, 248, 0.3);
}
.job-status-badge--pending {
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.72);
  border: 1px solid #2a2e35;
}
.job-status-badge--failed {
  background: rgba(242, 139, 130, 0.15);
  color: #f28b82;
  border: 1px solid rgba(242, 139, 130, 0.35);
}
.job-detail-block,
.job-detail-tables {
  width: 100%;
}
.job-detail-tables {
  margin-bottom: 8px;
}
@media (max-width: 768px) {
  .job-meta-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
.job-section__title {
  margin: 4px 0 10px;
  font-size: 1.0625rem;
  font-weight: 600;
  color: #e8eaed;
  letter-spacing: 0.01em;
}
.job-panel {
  background: #1a1d21;
  border: 1px solid #2a2e35;
  border-radius: 16px;
  overflow: hidden;
}
.job-panel--table {
  padding: 0;
}
.chain {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.82);
}
.sym-list {
  margin: 0;
  padding: 12px 18px 14px;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.78);
}
.job-sym-scroll :deep(.el-scrollbar__view) {
  background: #1a1d21;
}
.mb {
  margin-bottom: 4px;
}
.job-detail-page :deep(.el-page-header__content),
.job-detail-page :deep(.el-page-header__title) {
  color: #e8eaed;
}
.job-detail-page :deep(.el-table) {
  --el-table-bg-color: #1a1d21;
  --el-table-tr-bg-color: #1a1d21;
  --el-table-expanded-cell-bg-color: #1a1d21;
  --el-table-header-bg-color: #252930;
  --el-table-row-hover-bg-color: #2a2e35;
  --el-table-border-color: #2a2e35;
  --el-table-text-color: #e8eaed;
  --el-table-header-text-color: rgba(255, 255, 255, 0.72);
  --el-fill-color-lighter: #22262c;
}
.job-detail-page :deep(.el-table__empty-text) {
  color: rgba(255, 255, 255, 0.5);
}
.job-detail-page :deep(.el-table--striped .el-table__body tr.el-table__row--striped td.el-table__cell) {
  background: #1f2329;
}
.job-detail-page :deep(.el-loading-mask) {
  background-color: rgba(11, 12, 14, 0.72);
}
</style>