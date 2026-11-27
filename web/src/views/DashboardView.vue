<script setup lang="ts">
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { fetchDashboardOverview, fetchJobAnalysisStats, fetchJobs } from '@/api/client'
import type { JobAnalysisStats, JobListItem, JobStatus } from '@/api/types'
import RepoAutocompleteFilter, { type RepoGateStat } from '@/components/RepoAutocompleteFilter.vue'
import Md3LoadState from '@/components/Md3LoadState.vue'
import { formatLocalDateTime } from '@/utils/datetime'

const router = useRouter()
const openNewAnalysis = inject<() => void>('openNewAnalysis', () => {})
const loading = ref(false)
const jobs = ref<JobListItem[]>([])
const stats = ref<JobAnalysisStats | null>(null)
const repoFilter = ref<string | null>(null)
const statusFilter = ref<'all' | JobStatus>('all')
const repoGateStats = ref<RepoGateStat[]>([])
const jobPage = ref(1)
const jobPageSize = ref(10)
const jobTotal = ref(0)
const jobPerPageOptions = [10, 25, 50]

const jobPageCount = computed(() => Math.max(1, Math.ceil(jobTotal.value / jobPageSize.value)))
const jobRangeStart = computed(() =>
  jobTotal.value === 0 ? 0 : (jobPage.value - 1) * jobPageSize.value + 1,
)
const jobRangeEnd = computed(() => Math.min(jobPage.value * jobPageSize.value, jobTotal.value))
const canGoJobPrev = computed(() => jobPage.value > 1)
const canGoJobNext = computed(() => jobPage.value < jobPageCount.value)

const jobPaginationNavButtons = computed(() => [
  {
    id: 'first',
    label: '第一页',
    icon: 'mdi-chevron-double-left',
    disabled: !canGoJobPrev.value,
    onClick: () => {
      jobPage.value = 1
    },
  },
  {
    id: 'prev',
    label: '上一页',
    icon: 'mdi-chevron-left',
    disabled: !canGoJobPrev.value,
    onClick: () => {
      jobPage.value = Math.max(1, jobPage.value - 1)
    },
  },
  {
    id: 'next',
    label: '下一页',
    icon: 'mdi-chevron-right',
    disabled: !canGoJobNext.value,
    onClick: () => {
      jobPage.value = Math.min(jobPageCount.value, jobPage.value + 1)
    },
  },
  {
    id: 'last',
    label: '最后一页',
    icon: 'mdi-chevron-double-right',
    disabled: !canGoJobNext.value,
    onClick: () => {
      jobPage.value = jobPageCount.value
    },
  },
])

const statusItems = [
  { title: '全部', value: 'all' as const },
  { title: '已完成', value: 'completed' as const },
  { title: '分析中', value: 'running' as const },
  { title: '排队', value: 'pending' as const },
  { title: '失败', value: 'failed' as const },
]

function formatDuration(seconds: number) {
  const sec = Math.max(0, Math.round(seconds))
  if (sec < 60) return `${sec}s`
  const m = Math.floor(sec / 60)
  const r = sec % 60
  return `${m}m ${r}s`
}

const overviewCards = computed(() => {
  const s = stats.value
  const convergenceSub =
    s && !s.ever_hit_api && s.total > 0
      ? '暂无命中 HTTP 接口的变更记录'
      : `平均从 ${s?.avg_baseline_apis ?? 0} 个接口收敛至 ${s?.avg_impacted_apis ?? 0} 个精准接口`
  const convergencePct = s?.api_convergence_pct ?? 0
  const convergenceWarn = convergencePct > 0 && convergencePct < 15
  return [
    {
      title: '累计 Diff 分析任务',
      value: `${s?.total ?? 0} 次`,
      badge: s?.avg_seconds ? formatDuration(s.avg_seconds) : undefined,
      sub: s?.avg_seconds ? `平均图谱追溯耗时 ${formatDuration(s.avg_seconds)}` : '暂无耗时样本',
      accent: '#8AB4F8',
      icon: 'mdi-chart-bar',
      iconBg: 'rgba(138, 180, 248, 0.15)',
      iconColor: '#8AB4F8',
      valueColor: '#E8EAED',
    },
    {
      title: '平均每次影响 API 收敛率',
      value: `${convergencePct}%`,
      sub: convergenceSub,
      accent: convergenceWarn ? '#FDD663' : '#8AB4F8',
      icon: 'mdi-target',
      iconBg: convergenceWarn ? 'rgba(253, 214, 99, 0.15)' : 'rgba(138, 180, 248, 0.15)',
      iconColor: convergenceWarn ? '#FDD663' : '#8AB4F8',
      valueColor: convergenceWarn ? '#FB923C' : '#60A5FA',
    },
    {
      title: '关联精准回归触发率',
      value: `${s?.regression_trigger_pct ?? 0}%`,
      sub: '自动推送受影响 API 列表至测试套件',
      accent: '#81C995',
      icon: 'mdi-rocket-launch-outline',
      iconBg: 'rgba(52, 168, 83, 0.15)',
      iconColor: '#81C995',
      valueColor: '#81C995',
    },
  ]
})

function statusLabel(status: JobStatus) {
  const map: Record<JobStatus, string> = {
    completed: '已完成',
    running: '分析中',
    pending: '排队中',
    failed: '失败',
    debouncing: '合并推送',
    superseded: '已取代',
  }
  return map[status] ?? status
}

function statusChipClass(status: JobStatus) {
  if (status === 'completed') return 'status-chip--done'
  if (status === 'failed') return 'status-chip--fail'
  if (status === 'running') return 'status-chip--run'
  if (status === 'superseded') return 'status-chip--muted'
  if (status === 'debouncing') return 'status-chip--debounce'
  return 'status-chip--wait'
}

function formatTime(iso: string | null) {
  return formatLocalDateTime(iso)
}

function jobCommitTitle(job: JobListItem) {
  const parts = [job.head_sha, formatTime(job.created_at)]
  if (job.commit_message) parts.push(job.commit_message)
  return parts.join(' · ')
}

async function load() {
  loading.value = true
  try {
    const statusParam = statusFilter.value === 'all' ? undefined : statusFilter.value
    const offset = (jobPage.value - 1) * jobPageSize.value
    const [listPage, overview, dash] = await Promise.all([
      fetchJobs(jobPageSize.value, offset, {
        repo: repoFilter.value || undefined,
        status: statusParam,
      }),
      fetchJobAnalysisStats(),
      fetchDashboardOverview(7),
    ])
    const maxPage = Math.max(1, Math.ceil(listPage.total / jobPageSize.value))
    if (listPage.total > 0 && jobPage.value > maxPage) {
      jobPage.value = maxPage
      loading.value = false
      await load()
      return
    }
    jobs.value = listPage.items
    jobTotal.value =
      listPage.total > 0 ? listPage.total : offset + listPage.items.length
    stats.value = overview
    repoGateStats.value = dash.repo_gate_stats ?? []
  } finally {
    loading.value = false
  }
}

function openJob(job: JobListItem) {
  router.push(`/jobs/${job.id}`)
}

function openCreate() {
  openNewAnalysis()
}

watch([repoFilter, statusFilter], () => {
  jobPage.value = 1
})
watch(jobPageSize, () => {
  jobPage.value = 1
})
watch([repoFilter, statusFilter, jobPage, jobPageSize], load)

onMounted(load)
</script>

<template>
  <div class="analysis-page">
    <div class="analysis-grid">
    <div class="analysis-hero d-flex flex-wrap align-start justify-space-between gap-4 mb-4">
      <div>
        <h2 class="analysis-page-title mb-1">变更影响分析</h2>
        <p class="mb-0 analysis-sub">
          基于 Git Diff 与 AST 静态调用链图谱，精确追溯代码改动影响的顶层 API 接口。
        </p>
      </div>
      <div class="analysis-toolbar">
        <div class="analysis-toolbar__filters">
          <RepoAutocompleteFilter
            v-model="repoFilter"
            field-class="analysis-filter-select"
            :gate-stats="repoGateStats"
          />
          <v-select
            v-model="statusFilter"
            class="analysis-filter-status"
            :items="statusItems"
            item-title="title"
            item-value="value"
            variant="solo"
            flat
            density="comfortable"
            hide-details
            rounded="lg"
            menu-icon="mdi-menu-down"
          />
        </div>
        <v-btn
          class="analysis-refresh"
          :class="{ 'analysis-refresh--spin': loading }"
          variant="text"
          rounded="lg"
          :loading="loading"
          icon="mdi-refresh"
          aria-label="刷新列表"
          title="刷新列表"
          @click="load"
        />
      </div>
    </div>

    <div class="analysis-kpi-grid mb-4">
      <v-card
        v-for="card in overviewCards"
        :key="card.title"
        class="h-100 kpi-card m3-surface-card m3-elevated"
        rounded="xl"
        :border="false"
      >
        <span class="kpi-accent" :style="{ backgroundColor: card.accent }" aria-hidden="true" />
        <v-card-text class="kpi-card-inner">
          <div class="d-flex align-start justify-space-between gap-2 mb-3">
            <div class="text-body-2 text-medium-emphasis kpi-title">{{ card.title }}</div>
            <v-avatar size="40" rounded="lg" :style="{ backgroundColor: card.iconBg }">
              <v-icon :icon="card.icon" :color="card.iconColor" size="22" />
            </v-avatar>
          </div>
          <div class="kpi-metric-row">
            <div class="kpi-metric" :style="{ color: card.valueColor }">{{ card.value }}</div>
            <span v-if="card.badge" class="kpi-inline-badge mono">{{ card.badge }}</span>
          </div>
          <p class="text-caption text-medium-emphasis mt-3 mb-0">{{ card.sub }}</p>
        </v-card-text>
      </v-card>
    </div>

    <div v-if="loading && jobs.length === 0" class="mb-3">
      <Md3LoadState mode="overlay" label="加载分析记录…" min-height="220px" />
    </div>

    <div v-if="!loading && jobs.length === 0" class="empty-panel analysis-panel">
      <div class="empty-icon-wrap mb-4" aria-hidden="true">
        <v-icon icon="mdi-history" size="32" />
      </div>
      <div class="text-h6 font-weight-medium">暂无变更影响分析记录</div>
      <p class="text-body-2 text-medium-emphasis mt-2 empty-tip">
        使用右上角「新建分析」发起 Diff，或向 Git 仓库推送代码由 Webhook 自动触发 AST 逆向追溯。
      </p>
      <v-btn
        class="empty-cta-link text-none mt-3"
        variant="text"
        color="primary"
        append-icon="mdi-chevron-right"
        @click="openCreate"
      >
        前往新建分析
      </v-btn>
    </div>

    <div v-else class="job-list analysis-panel d-flex flex-column">
      <article
        v-for="job in jobs"
        :key="job.id"
        class="job-row"
        role="button"
        tabindex="0"
        @click="openJob(job)"
        @keyup.enter="openJob(job)"
      >
        <div class="job-col-repo min-width-0">
          <div class="d-flex align-center flex-wrap ga-2 mb-1">
            <span class="repo-name text-body-2">{{ job.repo }}</span>
            <v-chip size="x-small" variant="outlined" rounded="lg" class="branch-chip">{{ job.ref_branch }}</v-chip>
          </div>
          <div class="job-commit-meta text-caption text-truncate" :title="jobCommitTitle(job)">
            <span class="job-commit-label">Commit</span>
            <span class="job-commit-sha mono">{{ job.head_sha }}</span>
            <span class="job-commit-sep" aria-hidden="true">·</span>
            <span class="job-commit-time">{{ formatTime(job.created_at) }}</span>
            <template v-if="job.commit_message">
              <span class="job-commit-sep" aria-hidden="true">·</span>
              <span class="job-commit-msg text-truncate">{{ job.commit_message }}</span>
            </template>
          </div>
        </div>

        <div class="job-col-trigger d-none d-md-flex">
          <v-chip size="x-small" variant="outlined" rounded="lg" class="trigger-chip">{{ job.trigger_label }}</v-chip>
        </div>

        <div class="job-col-impact">
          <div class="impact-chain">
            <v-chip size="small" variant="outlined" rounded="lg" class="impact-chip">
              改 <span class="impact-num">{{ job.changed_files }}</span> 文件
            </v-chip>
            <span class="impact-arrow" aria-hidden="true">›</span>
            <v-chip size="small" variant="outlined" rounded="lg" class="impact-chip">
              命中 <span class="impact-num">{{ job.method_count }}</span> 方法
            </v-chip>
            <span class="impact-arrow" aria-hidden="true">›</span>
            <v-chip
              size="small"
              variant="outlined"
              rounded="lg"
              class="impact-chip"
              :class="job.api_count > 0 ? 'impact-chip--accent' : 'impact-chip--zero'"
            >
              影响 <span class="impact-num">{{ job.api_count }}</span> API
            </v-chip>
          </div>
        </div>

        <div class="job-col-actions d-flex align-center justify-end ga-2" @click.stop>
          <v-chip
            size="x-small"
            variant="flat"
            rounded="lg"
            class="status-chip"
            :class="statusChipClass(job.status)"
          >
            {{ statusLabel(job.status) }}
          </v-chip>
          <v-btn size="small" variant="text" rounded="lg" class="cta-graph text-none" @click="openJob(job)">
            查看调用链图谱
          </v-btn>
        </div>
      </article>

      <div v-if="jobs.length > 0" class="job-pagination-wrapper">
        <div class="job-pagination-left">
          <span class="job-pagination-label">每页</span>
          <v-select
            v-model="jobPageSize"
            :items="jobPerPageOptions"
            density="compact"
            hide-details
            variant="solo"
            flat
            class="job-page-size-select"
            menu-icon="mdi-menu-down"
          />
        </div>
        <div class="job-pagination-right">
          <span class="job-page-text">
            {{ jobRangeStart }}-{{ jobRangeEnd }} 共 {{ jobTotal }}
          </span>
          <span class="job-page-index">第 {{ jobPage }} / {{ jobPageCount }} 页</span>
          <div class="job-page-buttons" role="navigation" aria-label="任务列表分页">
            <v-btn
              v-for="btn in jobPaginationNavButtons"
              :key="btn.id"
              class="job-page-btn"
              icon
              variant="text"
              density="comfortable"
              :disabled="btn.disabled"
              :aria-label="btn.label"
              @click="btn.onClick"
            >
              <v-icon :icon="btn.icon" size="20" />
            </v-btn>
          </div>
        </div>
      </div>
    </div>
    </div>
  </div>
</template>

<style scoped>
.analysis-page {
  width: 100%;
  color: rgba(255, 255, 255, 0.87);
}
.analysis-page-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: #ffffff;
  letter-spacing: 0.01em;
}
.analysis-hero .analysis-sub {
  font-size: 12px;
  line-height: 1.55;
  color: #888888 !important;
}
.analysis-grid {
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
}
.analysis-kpi-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  width: 100%;
  box-sizing: border-box;
}
@media (max-width: 959px) {
  .analysis-kpi-grid {
    grid-template-columns: 1fr;
  }
}
.analysis-hero {
  width: 100%;
  align-items: flex-start;
  box-sizing: border-box;
}
.analysis-sub {
  max-width: 560px;
  line-height: 1.5;
}
.analysis-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 16px;
  margin-inline-start: auto;
  flex: 0 1 auto;
  max-width: 100%;
}
.analysis-toolbar__filters {
  display: flex;
  align-items: center;
  gap: 12px;
}
.analysis-toolbar__filters :deep(.repo-autocomplete.analysis-filter-select) {
  width: 280px !important;
  min-width: 280px !important;
  max-width: 280px !important;
  flex-shrink: 0;
}
.analysis-filter-status {
  width: 124px;
  min-width: 124px;
  flex-shrink: 0;
}
.analysis-filter-select :deep(.v-field),
.analysis-filter-status :deep(.v-field) {
  min-height: 40px;
  height: 40px;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  background-color: #1f1f1f !important;
  box-shadow: none;
}
.analysis-filter-select :deep(.v-field__append-inner),
.analysis-filter-status :deep(.v-field__append-inner) {
  opacity: 0.82;
}
.analysis-filter-select :deep(.v-select__menu-icon),
.analysis-filter-status :deep(.v-select__menu-icon) {
  color: rgba(255, 255, 255, 0.72);
  opacity: 1;
  margin-inline-end: 2px;
}
.analysis-filter-select :deep(.v-field__outline),
.analysis-filter-status :deep(.v-field__outline),
.analysis-filter-select :deep(.v-field__overlay),
.analysis-filter-status :deep(.v-field__overlay) {
  opacity: 0 !important;
}
.analysis-refresh {
  width: 40px !important;
  height: 40px !important;
  min-width: 40px !important;
  flex-shrink: 0;
  padding: 8px !important;
  border: none;
  background: transparent !important;
  color: rgba(255, 255, 255, 0.72) !important;
  border-radius: 8px !important;
  transition: background 0.2s ease, transform 0.45s ease;
}
.analysis-refresh:hover {
  background: rgba(255, 255, 255, 0.06) !important;
  color: #ffffff !important;
}
.analysis-refresh--spin :deep(.v-icon) {
  animation: analysis-refresh-spin 0.65s linear infinite;
}
@keyframes analysis-refresh-spin {
  to {
    transform: rotate(360deg);
  }
}
.cta-graph {
  font-weight: 500;
  font-size: 13px;
  letter-spacing: 0;
  color: rgba(255, 255, 255, 0.62) !important;
  min-width: 0;
  padding-inline: 10px !important;
  border: 1px solid transparent !important;
  background: transparent !important;
  box-shadow: none !important;
}
.cta-graph:hover {
  color: rgba(255, 255, 255, 0.9) !important;
  background: rgba(255, 255, 255, 0.06) !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
}
.cta-graph :deep(.v-btn__overlay) {
  opacity: 0 !important;
}
.job-commit-meta {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 0 6px;
  max-width: 100%;
  line-height: 1.45;
  color: rgba(255, 255, 255, 0.42);
}
.job-commit-label {
  color: rgba(255, 255, 255, 0.38);
  font-size: 11px;
  letter-spacing: 0.02em;
}
.job-commit-sha {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.55);
  font-weight: 500;
}
.job-commit-time {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.42);
}
.job-commit-sep {
  color: rgba(255, 255, 255, 0.22);
  user-select: none;
}
.job-commit-msg {
  flex: 1 1 120px;
  min-width: 0;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.6);
}
.impact-chip :deep(.v-chip__content) {
  gap: 4px;
  letter-spacing: 0.02em;
}
.analysis-panel {
  width: 100%;
  box-sizing: border-box;
}
.job-list {
  gap: 12px;
  padding-block: 2px;
}
.empty-panel {
  text-align: center;
  padding: 36px 24px 40px;
  border: 1px solid #2a2e35;
  border-radius: 16px;
  background: rgb(var(--v-theme-surface));
}
.empty-icon-wrap {
  width: 64px;
  height: 64px;
  margin-inline: auto;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(138, 180, 248, 0.14);
  color: #8ab4f8;
}
.empty-cta-link {
  font-weight: 500;
  letter-spacing: 0;
}
.empty-tip {
  max-width: 420px;
  margin-inline: auto;
}
.job-row {
  display: grid;
  grid-template-columns:
    minmax(0, 1.35fr)
    minmax(96px, 108px)
    minmax(0, 1fr)
    minmax(236px, 236px);
  gap: 10px 16px;
  align-items: center;
  padding: 14px 16px;
  box-sizing: border-box;
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 12px;
  background: #1c1f24;
  cursor: pointer;
  transition:
    background-color 0.18s ease,
    border-color 0.18s ease;
}
.job-row:hover {
  background: #22262c;
  border-color: rgba(255, 255, 255, 0.08);
}
.repo-name {
  color: rgba(255, 255, 255, 0.95);
  font-weight: 500;
  letter-spacing: -0.01em;
}
.impact-chain {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 10px;
}
.impact-num {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: rgba(255, 255, 255, 0.72);
}
.branch-chip,
.trigger-chip {
  background: transparent !important;
  color: rgba(255, 255, 255, 0.45) !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  font-size: 11px;
  font-weight: 500;
  height: 22px !important;
  padding-inline: 8px !important;
}
.trigger-chip {
  color: rgba(255, 255, 255, 0.38) !important;
  border-color: rgba(255, 255, 255, 0.07) !important;
}
.impact-chip {
  background: rgba(255, 255, 255, 0.03) !important;
  color: rgba(255, 255, 255, 0.52) !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  font-size: 12px;
  font-weight: 400;
  height: 28px !important;
  box-shadow: none !important;
}
.impact-chip :deep(.v-chip__underlay),
.branch-chip :deep(.v-chip__underlay),
.trigger-chip :deep(.v-chip__underlay) {
  opacity: 0 !important;
}
.impact-chip--accent {
  color: #8ab4f8 !important;
  border-color: rgba(138, 180, 248, 0.35) !important;
  background: rgba(138, 180, 248, 0.08) !important;
}
.impact-chip--accent .impact-num {
  color: #8ab4f8;
}
.impact-chip--zero {
  color: rgba(255, 255, 255, 0.36) !important;
  border-color: rgba(255, 255, 255, 0.06) !important;
  background: transparent !important;
}
.impact-chip--zero .impact-num {
  color: rgba(255, 255, 255, 0.4);
}
.impact-arrow {
  font-size: 12px;
  line-height: 1;
  color: rgba(255, 255, 255, 0.2);
  font-weight: 300;
  flex-shrink: 0;
  user-select: none;
}
.status-chip {
  font-weight: 500;
  letter-spacing: 0.02em;
}
.status-chip--done {
  background: rgba(16, 185, 129, 0.15) !important;
  color: #34d399 !important;
}
.status-chip--fail {
  background: rgba(239, 68, 68, 0.14) !important;
  color: #f87171 !important;
}
.status-chip--run {
  background: rgba(138, 180, 248, 0.12) !important;
  color: #93c5fd !important;
}
.status-chip--wait {
  background: rgba(142, 146, 153, 0.12) !important;
  color: rgba(255, 255, 255, 0.45) !important;
}
.status-chip--debounce {
  background: rgba(251, 191, 36, 0.1) !important;
  color: #fbbf24 !important;
}
.status-chip--muted {
  background: rgba(255, 255, 255, 0.04) !important;
  color: rgba(255, 255, 255, 0.35) !important;
}
@media (max-width: 959px) {
  .job-row {
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas:
      'repo actions'
      'impact impact';
  }
  .job-col-repo {
    grid-area: repo;
  }
  .job-col-impact {
    grid-area: impact;
  }
  .job-col-actions {
    grid-area: actions;
    justify-self: end;
    max-width: none;
    width: auto;
    margin-inline-start: 0;
  }
}
.job-col-actions {
  justify-self: stretch;
  width: 100%;
  max-width: 236px;
  margin-inline-start: auto;
}
.job-pagination-wrapper {
  position: sticky;
  bottom: 0;
  z-index: 3;
  margin-top: 20px;
  padding: 14px 16px 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  background: linear-gradient(180deg, rgba(11, 12, 14, 0.72) 0%, rgba(11, 12, 14, 0.96) 40%);
  backdrop-filter: blur(8px);
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 12px 16px;
  box-sizing: border-box;
}
.job-pagination-left {
  display: flex;
  align-items: center;
  gap: 10px;
  color: rgba(255, 255, 255, 0.6);
  font-size: 13px;
}
.job-pagination-right {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-inline-start: auto;
}
.job-page-text {
  color: rgba(255, 255, 255, 0.5);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.job-page-index {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.42);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.job-page-size-select {
  width: 96px;
  flex: 0 0 96px;
}
.job-page-size-select :deep(.v-field) {
  min-height: 32px !important;
  height: 32px !important;
  background-color: rgba(255, 255, 255, 0.05) !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  border-radius: 6px;
  font-size: 13px;
}
.job-page-size-select :deep(.v-field__outline),
.job-page-size-select :deep(.v-field__overlay) {
  opacity: 0 !important;
}
.job-page-buttons {
  display: flex;
  align-items: center;
  gap: 4px;
}
.job-page-btn {
  width: 32px !important;
  min-width: 32px !important;
  height: 32px !important;
  border-radius: 8px;
  color: rgba(255, 255, 255, 0.6) !important;
}
.job-page-btn:hover:not(.v-btn--disabled) {
  background-color: rgba(255, 255, 255, 0.08) !important;
  color: #ffffff !important;
}
.job-page-btn.v-btn--disabled {
  color: rgba(255, 255, 255, 0.2) !important;
}
</style>