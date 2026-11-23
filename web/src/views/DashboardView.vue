<script setup lang="ts">
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { fetchJobAnalysisStats, fetchJobs, fetchRepositories } from '@/api/client'
import type { JobAnalysisStats, JobListItem, JobStatus } from '@/api/types'

const router = useRouter()
const openNewAnalysis = inject<() => void>('openNewAnalysis', () => {})
const loading = ref(false)
const jobs = ref<JobListItem[]>([])
const stats = ref<JobAnalysisStats | null>(null)
const repoFilter = ref<string | null>(null)
const statusFilter = ref<'all' | JobStatus>('all')
const repoOptions = ref<{ title: string; value: string | null }[]>([])

const statusItems = [
  { title: '全部', value: 'all' as const },
  { title: '已完成', value: 'completed' as const },
  { title: '分析中', value: 'running' as const },
  { title: '排队', value: 'pending' as const },
  { title: '失败', value: 'failed' as const },
]

const overviewCards = computed(() => {
  const s = stats.value
  return [
    {
      title: '累计 Diff 分析任务',
      value: `${s?.total ?? 0} 次`,
      sub: `平均图谱追溯耗时 ${s?.avg_seconds ?? 0}s`,
    },
    {
      title: '平均每次影响 API 收敛率',
      value: `${s?.api_convergence_pct ?? 0}%`,
      sub: `平均从 ${s?.avg_baseline_apis ?? 0} 个接口收敛至 ${s?.avg_impacted_apis ?? 0} 个精准接口`,
    },
    {
      title: '关联精准回归触发率',
      value: `${s?.regression_trigger_pct ?? 0}%`,
      sub: '自动推送受影响 API 列表至测试套件',
    },
  ]
})

function statusLabel(status: JobStatus) {
  const map: Record<JobStatus, string> = {
    completed: '已完成',
    running: '分析中',
    pending: '排队中',
    failed: '失败',
  }
  return map[status] ?? status
}

function statusChipClass(status: JobStatus) {
  if (status === 'completed') return 'status-chip--done'
  if (status === 'failed') return 'status-chip--fail'
  if (status === 'running') return 'status-chip--run'
  return 'status-chip--wait'
}

function formatTime(iso: string | null) {
  if (!iso) return '—'
  return iso.replace('T', ' ').replace(/\.\d+Z?$/, '').slice(0, 16)
}

async function load() {
  loading.value = true
  try {
    const statusParam = statusFilter.value === 'all' ? undefined : statusFilter.value
    const [list, overview, repos] = await Promise.all([
      fetchJobs(100, 0, {
        repo: repoFilter.value || undefined,
        status: statusParam,
      }),
      fetchJobAnalysisStats(),
      fetchRepositories(),
    ])
    jobs.value = list
    stats.value = overview
    repoOptions.value = [
      { title: '全部仓库', value: null },
      ...repos.map((r) => ({ title: r.full_name, value: r.full_name })),
    ]
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

watch([repoFilter, statusFilter], load)

onMounted(load)
</script>

<template>
  <div class="analysis-page">
    <div class="analysis-grid">
    <div class="analysis-hero d-flex flex-wrap align-start justify-space-between gap-4 mb-4">
      <div>
        <h2 class="text-h5 font-weight-medium mb-1">变更影响分析</h2>
        <p class="text-body-2 text-medium-emphasis mb-0 analysis-sub">
          基于 Git Diff 与 AST 静态调用链图谱，精确追溯代码改动影响的顶层 API 接口。
        </p>
      </div>
      <div class="analysis-toolbar">
        <div class="analysis-toolbar__filters">
          <v-select
            v-model="repoFilter"
            class="analysis-filter-select"
            :items="repoOptions"
            item-title="title"
            item-value="value"
            variant="solo"
            flat
            density="comfortable"
            hide-details
            rounded="lg"
            menu-icon="mdi-menu-down"
            placeholder="全部仓库"
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
        <div class="analysis-toolbar__divider" aria-hidden="true" />
        <div class="analysis-toolbar__actions">
          <v-btn
            class="analysis-refresh"
            variant="text"
            rounded="lg"
            :loading="loading"
            icon="mdi-refresh"
            aria-label="刷新列表"
            title="刷新列表"
            @click="load"
          />
          <v-btn
            class="cta-analysis text-none"
            variant="flat"
            rounded="pill"
            height="40"
            prepend-icon="mdi-plus"
            @click="openCreate"
          >
            新建分析
          </v-btn>
        </div>
      </div>
    </div>

    <div class="analysis-kpi-row mb-4">
      <v-card
        v-for="card in overviewCards"
        :key="card.title"
        class="overview-card flex-grow-1"
        rounded="xl"
        :border="false"
      >
        <v-card-text class="overview-card__inner">
          <div class="text-body-2 text-medium-emphasis">{{ card.title }}</div>
          <div class="overview-value mt-2">{{ card.value }}</div>
          <div class="text-caption text-medium-emphasis mt-1">{{ card.sub }}</div>
        </v-card-text>
      </v-card>
    </div>

    <v-progress-linear v-if="loading && jobs.length === 0" indeterminate color="primary" class="mb-2 rounded" />

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
            <span class="repo-name text-body-2 font-weight-medium">{{ job.repo }}</span>
            <v-chip size="x-small" variant="flat" rounded="pill" class="branch-chip">{{ job.ref_branch }}</v-chip>
          </div>
          <div class="text-caption text-medium-emphasis mono">
            Commit: {{ job.head_sha }} · {{ formatTime(job.created_at) }}
          </div>
        </div>

        <div class="job-col-trigger d-none d-md-flex">
          <v-chip size="x-small" variant="flat" rounded="pill" class="trigger-chip">{{ job.trigger_label }}</v-chip>
        </div>

        <div class="job-col-impact">
          <div class="impact-chain">
            <v-chip size="small" variant="flat" rounded="pill" class="impact-chip">
              改 <span class="impact-num">{{ job.changed_files }}</span> 文件
            </v-chip>
            <v-icon icon="mdi-chevron-right" size="14" class="impact-arrow" />
            <v-chip size="small" variant="flat" rounded="pill" class="impact-chip">
              命中 <span class="impact-num">{{ job.method_count }}</span> 方法
            </v-chip>
            <v-icon icon="mdi-chevron-right" size="14" class="impact-arrow" />
            <v-chip size="small" variant="flat" rounded="pill" class="impact-chip impact-chip--accent">
              影响 <span class="impact-num">{{ job.api_count }}</span> API
            </v-chip>
          </div>
        </div>

        <div class="job-col-actions d-flex align-center justify-end ga-2" @click.stop>
          <v-chip size="x-small" variant="flat" rounded="pill" class="status-chip" :class="statusChipClass(job.status)">
            {{ statusLabel(job.status) }}
          </v-chip>
          <v-btn
            size="small"
            variant="tonal"
            color="primary"
            rounded="pill"
            class="cta-graph text-none"
            @click="openJob(job)"
          >
            查看调用链图谱
          </v-btn>
        </div>
      </article>
    </div>
    </div>
  </div>
</template>

<style scoped>
.analysis-page {
  width: 100%;
}
.analysis-grid {
  width: 100%;
  max-width: 100%;
}
.analysis-hero {
  width: 100%;
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
.analysis-toolbar__filters,
.analysis-toolbar__actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
.analysis-toolbar__divider {
  width: 1px;
  height: 28px;
  flex-shrink: 0;
  background: rgba(255, 255, 255, 0.12);
  margin-inline: 4px;
}
.analysis-filter-select {
  width: 168px;
  min-width: 160px;
  max-width: 180px;
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
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  font-size: 13px;
  background-color: #2a2a2a !important;
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
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: #2a2a2a !important;
  color: rgba(255, 255, 255, 0.88) !important;
  border-radius: 8px !important;
}
.analysis-refresh:hover {
  background: #35393f !important;
}
.cta-analysis {
  font-weight: 600;
  font-size: 13px;
  letter-spacing: 0;
  padding-inline: 16px !important;
  background: rgba(138, 180, 248, 0.18) !important;
  color: #8ab4f8 !important;
  box-shadow: none;
}
.cta-analysis :deep(.v-btn__prepend) {
  margin-inline-end: 8px;
}
.cta-analysis :deep(.v-icon) {
  color: #8ab4f8 !important;
}
.cta-graph {
  font-weight: 600;
  font-size: 13px;
  letter-spacing: 0;
}
.analysis-kpi-row {
  display: flex;
  flex-wrap: wrap;
  gap: 24px;
  width: 100%;
}
.analysis-kpi-row .overview-card {
  flex: 1 1 calc(33.333% - 16px);
  min-width: min(100%, 220px);
}
.overview-card__inner {
  padding: 20px 22px !important;
}
.overview-card {
  background: rgb(var(--v-theme-surface)) !important;
  border: 1px solid #2a2e35 !important;
  box-shadow: none !important;
}
.analysis-panel {
  width: 100%;
}
.job-list {
  gap: 12px;
}
.overview-value {
  font-size: 28px;
  line-height: 1.2;
  letter-spacing: -0.02em;
  color: rgb(var(--v-theme-on-surface));
  font-variant-numeric: tabular-nums;
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
  grid-template-columns: minmax(0, 1.4fr) auto minmax(0, 1.2fr) auto;
  gap: 12px 20px;
  align-items: center;
  padding: 20px 24px;
  border: 1px solid #2a2e35;
  border-radius: 16px;
  background: rgb(var(--v-theme-surface));
  cursor: pointer;
  transition:
    background-color 0.18s ease,
    border-color 0.18s ease;
}
.job-row:hover {
  background: #24282e;
  border-color: #343a42;
}
.repo-name {
  color: rgb(var(--v-theme-on-surface));
}
.impact-chain {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}
.impact-num {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: #e8eaed;
}
.branch-chip,
.trigger-chip,
.impact-chip {
  background: rgba(255, 255, 255, 0.06) !important;
  color: rgba(255, 255, 255, 0.72) !important;
  border: 1px solid rgba(255, 255, 255, 0.08);
  font-size: 12px;
}
.impact-chip--accent {
  color: #8ab4f8 !important;
  border-color: rgba(138, 180, 248, 0.22);
  background: rgba(138, 180, 248, 0.1) !important;
}
.impact-chip--accent .impact-num {
  color: #8ab4f8;
}
.impact-arrow {
  color: #5f6368;
  opacity: 0.75;
  flex-shrink: 0;
}
.status-chip--done {
  background: rgba(52, 168, 83, 0.12) !important;
  color: rgba(129, 201, 149, 0.92) !important;
}
.status-chip--fail {
  background: rgba(234, 67, 53, 0.16) !important;
  color: #f28b82 !important;
}
.status-chip--run {
  background: rgba(138, 180, 248, 0.14) !important;
  color: #8ab4f8 !important;
}
.status-chip--wait {
  background: rgba(142, 146, 153, 0.16) !important;
  color: #8e9299 !important;
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
  }
}
</style>