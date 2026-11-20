<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { fetchJobAnalysisStats, fetchJobs, fetchRepositories } from '@/api/client'
import type { JobAnalysisStats, JobListItem, JobStatus } from '@/api/types'

const router = useRouter()
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
  router.push('/repositories')
}

watch([repoFilter, statusFilter], load)

onMounted(load)
</script>

<template>
  <div class="analysis-page">
    <div class="d-flex flex-wrap align-start justify-space-between gap-4 mb-4">
      <div>
        <h2 class="text-h5 font-weight-medium mb-1">变更影响分析</h2>
        <p class="text-body-2 text-medium-emphasis mb-0 analysis-sub">
          基于 Git Diff 与 AST 静态调用链图谱，精确追溯代码改动影响的顶层 API 接口。
        </p>
      </div>
      <div class="analysis-actions d-flex flex-wrap align-center ga-2">
        <v-select
          v-model="repoFilter"
          class="analysis-filter-select"
          :items="repoOptions"
          item-title="title"
          item-value="value"
          variant="solo"
          flat
          density="compact"
          hide-details
          rounded="lg"
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
          density="compact"
          hide-details
          rounded="lg"
        />
        <v-tooltip text="刷新列表" location="bottom">
          <template #activator="{ props: tipProps }">
            <v-btn
              v-bind="tipProps"
              class="analysis-refresh"
              variant="flat"
              rounded="circle"
              :loading="loading"
              icon="mdi-refresh"
              aria-label="刷新"
              @click="load"
            />
          </template>
        </v-tooltip>
        <v-btn
          class="cta-analysis text-none"
          variant="flat"
          rounded="pill"
          prepend-icon="mdi-plus"
          @click="openCreate"
        >
          新建分析
        </v-btn>
      </div>
    </div>

    <v-row class="mb-4" dense>
      <v-col v-for="card in overviewCards" :key="card.title" cols="12" md="4">
        <v-card class="overview-card" rounded="xl" :border="false">
          <v-card-text>
            <div class="text-body-2 text-medium-emphasis">{{ card.title }}</div>
            <div class="overview-value mt-2">{{ card.value }}</div>
            <div class="text-caption text-medium-emphasis mt-1">{{ card.sub }}</div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-progress-linear v-if="loading && jobs.length === 0" indeterminate color="primary" class="mb-2 rounded" />

    <div v-if="!loading && jobs.length === 0" class="empty-panel">
      <v-icon icon="mdi-source-branch" size="56" class="empty-icon mb-4" />
      <div class="text-h6 font-weight-medium">暂无变更影响分析记录</div>
      <p class="text-body-2 text-medium-emphasis mt-2 empty-tip">
        点击右上角「新建分析」或向 Git 仓库推送代码，Webhook 将自动触发 AST 逆向追溯。
      </p>
      <v-btn class="cta-analysis text-none mt-4" variant="flat" rounded="pill" prepend-icon="mdi-plus" @click="openCreate">
        新建分析
      </v-btn>
    </div>

    <div v-else class="job-list d-flex flex-column ga-2">
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
          <div class="impact-chain d-flex flex-wrap align-center ga-1">
            <v-chip size="x-small" variant="flat" rounded="pill" class="impact-chip">改 {{ job.changed_files }} 文件</v-chip>
            <v-icon icon="mdi-chevron-right" size="14" class="impact-arrow" />
            <v-chip size="x-small" variant="flat" rounded="pill" class="impact-chip">命中 {{ job.method_count }} 方法</v-chip>
            <v-icon icon="mdi-chevron-right" size="14" class="impact-arrow" />
            <v-chip size="x-small" variant="flat" rounded="pill" class="impact-chip impact-chip--accent">影响 {{ job.api_count }} API</v-chip>
          </div>
        </div>

        <div class="job-col-actions d-flex align-center justify-end ga-2" @click.stop>
          <v-chip size="x-small" variant="flat" rounded="pill" class="status-chip" :class="statusChipClass(job.status)">
            {{ statusLabel(job.status) }}
          </v-chip>
          <v-btn
            size="small"
            variant="flat"
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
</template>

<style scoped>
.analysis-sub {
  max-width: 560px;
  line-height: 1.5;
}
.analysis-filter-select {
  width: 168px;
  min-width: 160px;
  max-width: 180px;
  flex-shrink: 0;
}
.analysis-filter-status {
  width: 112px;
  flex-shrink: 0;
}
.analysis-filter-select :deep(.v-field),
.analysis-filter-status :deep(.v-field) {
  min-height: 34px;
  height: 34px;
  border: 1px solid #2a2e35;
  border-radius: 10px;
  font-size: 13px;
  background-color: rgb(var(--v-theme-surface)) !important;
  box-shadow: none;
}
.analysis-filter-select :deep(.v-field__outline),
.analysis-filter-status :deep(.v-field__outline),
.analysis-filter-select :deep(.v-field__overlay),
.analysis-filter-status :deep(.v-field__overlay) {
  opacity: 0 !important;
}
.analysis-refresh {
  width: 34px;
  height: 34px;
  min-width: 34px;
  border: 1px solid #2a2e35;
  background: rgb(var(--v-theme-surface)) !important;
  box-shadow: none;
}
.cta-analysis,
.cta-graph {
  background-color: #f1f3f5 !important;
  color: #111315 !important;
  font-weight: 600;
}
.cta-analysis :deep(.v-icon),
.cta-graph :deep(.v-icon) {
  color: #111315 !important;
}
.overview-card {
  background: rgb(var(--v-theme-surface)) !important;
  border: 1px solid #2a2e35 !important;
  box-shadow: none !important;
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
  padding: 48px 24px;
  border: 1px solid #2a2e35;
  border-radius: 16px;
  background: rgb(var(--v-theme-surface));
}
.empty-icon {
  color: #8e9299;
  opacity: 0.85;
}
.empty-tip {
  max-width: 420px;
  margin-inline: auto;
}
.job-row {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) auto minmax(0, 1.2fr) auto;
  gap: 12px 16px;
  align-items: center;
  padding: 14px 16px;
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
.branch-chip,
.trigger-chip,
.impact-chip {
  background: #24282e !important;
  color: #8e9299 !important;
}
.impact-chip--accent {
  color: rgb(var(--v-theme-primary)) !important;
}
.impact-arrow {
  color: #5f6368;
  opacity: 0.9;
}
.status-chip--done {
  background: rgba(52, 168, 83, 0.16) !important;
  color: #81c995 !important;
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