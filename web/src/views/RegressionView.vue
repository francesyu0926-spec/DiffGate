<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  fetchRegressionBatchDetail,
  fetchRegressionBatches,
  fetchRegressionOverview,
  fetchRepositories,
  type RegressionBatchDetail,
  type RegressionBatchItem,
} from '@/api/client'

const router = useRouter()

const loading = ref(false)
const repoFilter = ref<string | null>(null)
const gateFilter = ref<string | null>(null)
const repoOptions = ref<{ title: string; value: string | null }[]>([])

const overview = ref<Awaited<ReturnType<typeof fetchRegressionOverview>> | null>(null)
const batches = ref<RegressionBatchItem[]>([])
const selectedId = ref<string | null>(null)
const detail = ref<RegressionBatchDetail | null>(null)
const detailLoading = ref(false)
const detailTab = ref<'cases' | 'coverage'>('cases')

const gateOptions = [
  { title: '全部状态', value: null },
  { title: '通过', value: 'PASS' },
  { title: '拦截', value: 'BLOCK' },
  { title: '待测', value: 'PENDING' },
]

const kpiCards = computed(() => {
  const k = overview.value?.kpi
  if (!k) return []
  const gate = k.current_gate
  const gateLabel =
    gate === 'PASS' ? 'PASS 放行' : gate === 'BLOCK' ? 'BLOCK 阻断' : gate === 'PENDING' ? '待 CI 回传' : '—'
  const gateColor =
    gate === 'PASS' ? '#81C995' : gate === 'BLOCK' ? '#F28B82' : '#8E9299'
  return [
    {
      title: '累计精准执行用例数',
      value: `${k.executed_cases} 条`,
      sub:
        k.baseline_cases > 0
          ? `从全量 ${k.baseline_cases} 条收敛，用例压缩率 ${k.case_reduction_pct}%`
          : '完成 Diff 分析并触发调度后统计',
      accent: '#8AB4F8',
      icon: 'mdi-filter-variant',
      iconBg: 'rgba(138, 180, 248, 0.15)',
      iconColor: '#8AB4F8',
    },
    {
      title: '最近批次用例通过率',
      value: k.latest_total > 0 ? `${k.latest_pass_rate}%` : '—',
      sub:
        k.latest_total > 0
          ? `通过 ${k.latest_passed} / ${k.latest_total} 条`
          : '暂无已执行用例批次',
      accent: '#81C995',
      icon: 'mdi-check-circle-outline',
      iconBg: 'rgba(52, 168, 83, 0.15)',
      iconColor: '#81C995',
    },
    {
      title: '探针增量行覆盖率',
      value: k.incremental_coverage_pct != null ? `${k.incremental_coverage_pct}%` : '—',
      sub:
        k.changed_lines > 0
          ? `变更 ${k.changed_lines} 行，探针命中 ${k.covered_lines} 行`
          : '待 CI 回传 coverage.py 结果',
      accent: '#FDD663',
      icon: 'mdi-chart-timeline-variant',
      iconBg: 'rgba(253, 214, 99, 0.15)',
      iconColor: '#FDD663',
    },
    {
      title: '当前质量门禁判定',
      value: gateLabel,
      sub: '基于最近一批回归与覆盖率门禁',
      accent: gateColor,
      icon: gate === 'BLOCK' ? 'mdi-shield-alert' : 'mdi-shield-check',
      iconBg: gate === 'BLOCK' ? 'rgba(234, 67, 53, 0.15)' : 'rgba(52, 168, 83, 0.15)',
      iconColor: gateColor,
      valueColor: gateColor,
      isGate: true,
    },
  ]
})

function formatTime(iso: string | null | undefined) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function gateChipClass(gate: string) {
  if (gate === 'PASS') return 'batch-chip--pass'
  if (gate === 'BLOCK') return 'batch-chip--block'
  return 'batch-chip--pending'
}

async function loadList() {
  loading.value = true
  try {
    const [ov, list, repos] = await Promise.all([
      fetchRegressionOverview(repoFilter.value || undefined, gateFilter.value || undefined),
      fetchRegressionBatches(repoFilter.value || undefined, gateFilter.value || undefined),
      fetchRepositories(),
    ])
    overview.value = ov
    batches.value = list
    repoOptions.value = [
      { title: '全部仓库', value: null },
      ...repos.map((r) => ({ title: r.full_name, value: r.full_name })),
    ]
    if (list.length && (!selectedId.value || !list.some((b) => b.job_id === selectedId.value))) {
      selectedId.value = list[0].job_id
      await loadDetail(list[0].job_id)
    }
    if (!list.length) {
      selectedId.value = null
      detail.value = null
    }
  } finally {
    loading.value = false
  }
}

async function loadDetail(jobId: string) {
  detailLoading.value = true
  try {
    detail.value = await fetchRegressionBatchDetail(jobId)
  } catch {
    detail.value = null
  } finally {
    detailLoading.value = false
  }
}

watch(selectedId, (id) => {
  if (id) loadDetail(id)
})

watch([repoFilter, gateFilter], loadList)

onMounted(loadList)
</script>

<template>
  <div class="regression-page">
    <div class="regression-hero d-flex flex-wrap align-start justify-space-between gap-4 mb-4">
      <div>
        <h2 class="text-h5 text-md-h4 font-weight-bold mb-2">精准回归</h2>
        <p class="text-body-2 text-medium-emphasis mb-0 regression-sub">
          基于 AST 影响面动态筛选关联 YAML 用例执行，采集探针增量覆盖率并生成质量门禁判定。
        </p>
      </div>
      <div class="regression-filters d-flex flex-wrap align-center ga-3">
        <v-select
          v-model="repoFilter"
          class="filter-select-float"
          :items="repoOptions"
          item-title="title"
          item-value="value"
          variant="solo"
          flat
          density="compact"
          hide-details
          rounded="lg"
          prepend-inner-icon="mdi-source-repository"
          placeholder="全部仓库"
        />
        <v-select
          v-model="gateFilter"
          class="filter-gate"
          :items="gateOptions"
          item-title="title"
          item-value="value"
          variant="solo"
          flat
          density="compact"
          hide-details
          rounded="lg"
          prepend-inner-icon="mdi-shield-half-full"
        />
        <v-btn
          class="text-none btn-trigger-regression"
          variant="flat"
          rounded="pill"
          prepend-icon="mdi-play-circle-outline"
          @click="router.push('/repositories')"
        >
          手动触发回归
        </v-btn>
      </div>
    </div>

    <v-row class="dashboard-grid dashboard-stack-gap kpi-row">
      <v-col v-for="card in kpiCards" :key="card.title" cols="12" sm="6" lg="3">
        <v-card class="h-100 kpi-card m3-surface-card m3-elevated" rounded="xl" :border="false">
          <span class="kpi-accent" :style="{ backgroundColor: card.accent }" aria-hidden="true" />
          <v-card-text class="kpi-card-inner">
            <div class="d-flex align-start justify-space-between gap-2 mb-3">
              <div class="text-body-2 text-medium-emphasis kpi-title">{{ card.title }}</div>
              <v-avatar size="40" rounded="lg" :style="{ backgroundColor: card.iconBg }">
                <v-icon :icon="card.icon" :color="card.iconColor" size="22" />
              </v-avatar>
            </div>
            <div
              class="kpi-metric"
              :class="{ 'kpi-metric--gate': card.isGate }"
              :style="card.valueColor ? { color: card.valueColor } : undefined"
            >
              {{ card.value }}
            </div>
            <p class="text-caption text-medium-emphasis mt-3 mb-0">{{ card.sub }}</p>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-row class="dashboard-grid master-detail-row">
      <v-col cols="12" lg="4" class="batch-col">
        <v-card class="m3-surface-card m3-elevated batch-panel h-100" rounded="xl" :border="false">
          <v-card-title class="text-subtitle-1 font-weight-medium panel-title">回归执行批次</v-card-title>
          <v-card-text class="batch-list-wrap">
            <v-skeleton-loader v-if="loading" type="list-item@4" />
            <div v-else-if="!batches.length" class="batch-empty text-center py-10 px-4">
              <v-icon icon="mdi-file-document-outline" size="48" color="secondary" class="mb-3" />
              <div class="text-subtitle-1 font-weight-medium">暂无回归批次</div>
              <p class="text-body-2 text-medium-emphasis mt-2 batch-empty-tip">
                完成 Diff 分析后，调度中心将下发匹配接口用例并回传覆盖率。
              </p>
            </div>
            <div v-else class="batch-list">
              <button
                v-for="item in batches"
                :key="item.job_id"
                type="button"
                class="batch-card"
                :class="{ 'batch-card--active': selectedId === item.job_id }"
                @click="selectedId = item.job_id"
              >
                <v-chip
                  size="x-small"
                  variant="flat"
                  rounded="pill"
                  class="batch-chip"
                  :class="gateChipClass(item.gate)"
                >
                  {{ item.gate }}
                </v-chip>
                <span class="mono text-caption text-medium-emphasis d-block mb-1">{{ item.commit }}</span>
                <div class="text-body-2 font-weight-medium text-truncate">{{ item.repo }}</div>
                <div class="text-caption text-medium-emphasis mt-1">
                  {{ formatTime(item.created_at) }} · {{ item.api_impact }} API
                </div>
              </button>
            </div>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" lg="8" class="detail-col">
        <v-card class="m3-surface-card m3-elevated detail-panel h-100" rounded="xl" :border="false">
          <v-card-title class="panel-title d-flex flex-wrap align-center gap-2">
            <span class="text-subtitle-1 font-weight-medium">批次执行详情</span>
            <v-spacer />
            <v-tabs v-model="detailTab" density="compact" class="detail-tabs" color="primary">
              <v-tab value="cases" class="text-none">受影响 API 用例</v-tab>
              <v-tab value="coverage" class="text-none">增量覆盖率</v-tab>
            </v-tabs>
          </v-card-title>
          <v-card-text class="detail-body">
            <div v-if="!selectedId && !loading" class="detail-empty text-center py-12 px-4">
              <p class="text-body-2 text-medium-emphasis">请在左侧选择回归批次</p>
            </div>
            <v-skeleton-loader v-else-if="detailLoading" type="article" />
            <template v-else-if="detail">
              <div class="detail-meta text-caption text-medium-emphasis mono mb-4">
                {{ detail.repo }} @ {{ detail.commit?.slice(0, 8) }} · 门禁 {{ detail.gate }}
              </div>
              <v-window v-model="detailTab">
                <v-window-item value="cases">
                  <p v-if="!detail.cases.length" class="text-body-2 text-medium-emphasis mb-0">
                    本批次无命中 API，未下发 YAML 用例。
                  </p>
                  <div v-else class="case-list">
                    <div
                      v-for="(row, i) in detail.cases"
                      :key="i"
                      class="case-row"
                    >
                      <div class="case-main min-width-0">
                        <div class="mono text-body-2 font-weight-medium">
                          {{ row.method }} {{ row.path }}
                        </div>
                        <div class="text-caption text-medium-emphasis mono">{{ row.yaml_file }}</div>
                      </div>
                      <v-chip
                        size="x-small"
                        variant="flat"
                        rounded="pill"
                        :class="row.status === 'PASS' ? 'case-chip--pass' : 'case-chip--fail'"
                      >
                        {{ row.status }}
                      </v-chip>
                      <span class="mono text-caption case-ms">{{ row.duration_ms }} ms</span>
                    </div>
                  </div>
                </v-window-item>
                <v-window-item value="coverage">
                  <p class="text-body-2 mb-3">
                    增量覆盖率
                    <strong class="mono">{{ detail.incremental_coverage_pct ?? '—' }}%</strong>
                    · 变更 {{ detail.changed_lines }} 行
                  </p>
                  <div v-if="!detail.coverage_lines.length" class="text-medium-emphasis text-body-2">
                    暂无探针命中行数据，请通过 CI 回传 coverage 报告。
                  </div>
                  <pre v-else class="coverage-block mono"><code
                    v-for="(line, idx) in detail.coverage_lines"
                    :key="idx"
                    :class="{
                      'cov-hit': line.covered === true,
                      'cov-miss': line.covered === false,
                      'cov-unknown': line.covered == null,
                    }"
                  >{{ line.prefix }} {{ line.file }}:{{ line.line }}</code></pre>
                </v-window-item>
              </v-window>
            </template>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </div>
</template>

<style scoped>
.regression-page {
  width: 100%;
  max-width: 100%;
}
.regression-sub {
  max-width: 640px;
  line-height: 1.5;
}
.regression-filters {
  margin-inline-start: auto;
  align-items: center;
}
.filter-select-float {
  width: 168px;
  max-width: 180px;
}
.filter-gate {
  width: 132px;
}
.btn-trigger-regression {
  background: #f1f3f5 !important;
  color: #111315 !important;
}
.regression-filters :deep(.filter-select-float .v-field),
.regression-filters :deep(.filter-gate .v-field) {
  min-height: 34px;
  border: 1px solid #2a2e35;
  background: rgb(var(--v-theme-surface)) !important;
  font-size: 13px;
}
.regression-filters :deep(.v-field__outline) {
  opacity: 0 !important;
}
.dashboard-stack-gap {
  margin-bottom: 24px !important;
}
.kpi-card {
  position: relative;
  overflow: hidden;
}
.kpi-accent {
  position: absolute;
  left: 0;
  top: 12px;
  bottom: 12px;
  width: 3px;
  border-radius: 0 2px 2px 0;
}
.kpi-card-inner {
  padding: 20px 20px 22px 22px !important;
}
.kpi-title {
  opacity: 0.72;
}
.kpi-metric {
  font-family: var(--diffgate-kpi);
  font-size: 1.75rem;
  font-weight: 500;
  line-height: 1.15;
  font-variant-numeric: tabular-nums;
}
.kpi-metric--gate {
  font-size: 1.35rem;
}
.m3-surface-card {
  background-color: rgb(var(--v-theme-surface)) !important;
  border: 1px solid rgb(var(--v-theme-outline));
}
.m3-elevated {
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.45), 0 2px 8px rgba(0, 0, 0, 0.28);
}
.panel-title {
  padding: 16px 24px 8px !important;
}
.batch-list-wrap,
.detail-body {
  padding: 0 16px 20px 24px !important;
}
.batch-empty-tip {
  max-width: 300px;
  margin-inline: auto;
  line-height: 1.5;
}
.batch-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 520px;
  overflow-y: auto;
}
.batch-card {
  position: relative;
  width: 100%;
  text-align: left;
  padding: 14px 16px;
  border-radius: 16px;
  border: 1px solid rgb(var(--v-theme-outline));
  background: rgb(var(--v-theme-surface));
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.batch-card:hover {
  background: #24282e;
}
.batch-card--active {
  border-color: #8ab4f8;
  background: rgba(138, 180, 248, 0.08);
}
.batch-chip {
  position: absolute;
  top: 12px;
  right: 12px;
}
.batch-chip--pass {
  background: rgba(52, 168, 83, 0.16) !important;
  color: #81c995 !important;
}
.batch-chip--block {
  background: rgba(234, 67, 53, 0.16) !important;
  color: #f28b82 !important;
}
.batch-chip--pending {
  background: rgba(142, 146, 153, 0.16) !important;
  color: #8e9299 !important;
}
.detail-tabs :deep(.v-tab) {
  text-transform: none;
  font-size: 13px;
  min-width: auto;
  letter-spacing: 0;
}
.case-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.case-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 12px;
  align-items: center;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid rgb(var(--v-theme-outline));
  background: #1a1d21;
}
.case-chip--pass {
  background: rgba(52, 168, 83, 0.16) !important;
  color: #81c995 !important;
}
.case-chip--fail {
  background: rgba(234, 67, 53, 0.16) !important;
  color: #f28b82 !important;
}
.case-ms {
  opacity: 0.85;
}
.coverage-block {
  margin: 0;
  padding: 12px;
  border-radius: 12px;
  border: 1px solid rgb(var(--v-theme-outline));
  background: #111315;
  font-size: 12px;
  line-height: 1.6;
  overflow-x: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.coverage-block code.cov-hit {
  display: block;
  background: rgba(52, 168, 83, 0.22);
  color: #c8e6c9;
}
.coverage-block code.cov-miss {
  display: block;
  background: rgba(234, 67, 53, 0.22);
  color: #f28b82;
}
.coverage-block code.cov-unknown {
  display: block;
  color: #8e9299;
}
.master-detail-row {
  align-items: stretch;
}
@media (max-width: 1279px) {
  .batch-list {
    max-height: 320px;
  }
}
</style>