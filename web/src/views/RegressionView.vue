<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  fetchDashboardOverview,
  fetchRegressionBatchDetail,
  fetchRegressionBatches,
  fetchRegressionOverview,
  readApiError,
  submitRegressionGateOverride,
  type GateOverrideReasonCategory,
  type RegressionBatchDetail,
  type RegressionBatchItem,
} from '@/api/client'
import RepoAutocompleteFilter, { type RepoGateStat } from '@/components/RepoAutocompleteFilter.vue'
import { formatLocalDateTime } from '@/utils/datetime'

const router = useRouter()
const route = useRoute()

const loading = ref(false)
const repoFilter = ref<string | null>(null)
const gateFilter = ref<string | null>(null)
type FilterOption = { title: string; value: string | null; branch?: string | null }

const repoGateStats = ref<RepoGateStat[]>([])
const filterMenuProps = {
  rounded: 'lg',
  elevation: 8,
  contentClass: 'regression-filter-menu',
  minWidth: 240,
  maxWidth: 320,
} as const

/** v-select 会向 itemProps 注入 title，与自定义 title 并存会导致菜单项文字重复 */
function filterSelectItemProps(itemProps: Record<string, unknown>) {
  const next = { ...itemProps }
  delete next.title
  delete next.subtitle
  return next
}

const overview = ref<Awaited<ReturnType<typeof fetchRegressionOverview>> | null>(null)
const batches = ref<RegressionBatchItem[]>([])
const selectedId = ref<string | null>(null)
const detail = ref<RegressionBatchDetail | null>(null)
const detailLoading = ref(false)
const detailTab = ref<'cases' | 'coverage'>('cases')
const expandedCaseKey = ref<string | null>(null)

const overrideDialog = ref(false)
const overrideSubmitting = ref(false)
const overrideActor = ref('admin')
const overrideCategory = ref<GateOverrideReasonCategory>('hotfix')
const overrideDetail = ref('')
const overrideError = ref('')

const overrideReasonOptions = [
  { value: 'hotfix' as const, title: '紧急线上 Hotfix 优先发布' },
  { value: 'branch_unsimulatable' as const, title: '极端异常分支无法模拟' },
  { value: 'non_core_reviewed' as const, title: '非核心逻辑已评审确认无风险' },
  { value: 'other' as const, title: '其他' },
]

function repoShortName(repo: string) {
  const parts = repo.split('/').filter(Boolean)
  return parts[parts.length - 1] ?? repo
}

function formatBatchTime(iso: string | null | undefined) {
  const full = formatLocalDateTime(iso)
  if (!full || full === '—') return '—'
  const m = full.match(/\d{2}:\d{2}$/)
  return m ? m[0] : full
}

function formatBranchLabel(ref: string | null | undefined) {
  if (!ref) return ''
  const raw = ref.replace(/^refs\/heads\//i, '').replace(/^refs\/tags\//i, '')
  return raw.slice(0, 24)
}

function formatBatchMeta(item: RegressionBatchItem) {
  const time = formatBatchTime(item.created_at)
  const cov = item.coverage != null ? `${item.coverage}%` : '—'
  return `${item.commit} · ${time} · ${item.api_impact} API · ${cov}`
}

function caseRowKey(row: { method: string; path: string }) {
  return `${row.method}:${row.path}`
}

function toggleCaseRow(row: { method: string; path: string }) {
  const key = caseRowKey(row)
  expandedCaseKey.value = expandedCaseKey.value === key ? null : key
}

function caseAssertions(row: RegressionBatchDetail['cases'][number]) {
  if (row.assertions?.length) return row.assertions
  return row.status === 'FAIL'
    ? ['状态码断言失败', '响应体结构不匹配']
    : ['状态码 200', 'JSON Schema 校验通过']
}

function caseResponsePreview(row: RegressionBatchDetail['cases'][number]) {
  const raw = row.response_preview?.trim()
  if (raw) return raw
  if (row.status === 'FAIL') {
    return JSON.stringify(
      {
        detail: 'assertion failed',
        status: row.http_status ?? 502,
        message: '响应体为空或结构不符合 YAML 断言',
      },
      null,
      2,
    )
  }
  return JSON.stringify({ ok: true, status: row.http_status ?? 200 }, null, 2)
}

const coverageKpi = computed(() => {
  if (
    detail.value?.job_id === selectedId.value &&
    detail.value.incremental_coverage_pct != null
  ) {
    return {
      pct: detail.value.incremental_coverage_pct,
      changed: detail.value.changed_lines ?? 0,
      covered:
        detail.value.covered_lines ??
        detail.value.coverage_lines.filter((l) => l.covered === true).length,
    }
  }
  const k = overview.value?.kpi
  return {
    pct: k?.incremental_coverage_pct ?? null,
    changed: k?.changed_lines ?? 0,
    covered: k?.covered_lines ?? 0,
  }
})

const passKpi = computed(() => {
  if (detail.value?.job_id === selectedId.value && detail.value.cases.length) {
    const passed = detail.value.cases.filter((c) => c.status === 'PASS').length
    const total = detail.value.cases.length
    return {
      passed,
      total,
      rate: total > 0 ? (passed / total) * 100 : null,
    }
  }
  const k = overview.value?.kpi
  if (!k || k.latest_total <= 0) {
    return { passed: 0, total: 0, rate: null as number | null }
  }
  return {
    passed: k.latest_passed,
    total: k.latest_total,
    rate: k.latest_pass_rate,
  }
})

const gateOptions: FilterOption[] = [
  { title: '全部状态', value: null },
  { title: '通过', value: 'PASS' },
  { title: '拦截', value: 'BLOCK' },
  { title: '待测', value: 'PENDING' },
]

const kpiCards = computed(() => {
  const k = overview.value?.kpi
  if (!k) return []
  const gate =
    detail.value?.job_id === selectedId.value && detail.value.gate
      ? detail.value.gate
      : k.current_gate
  const dLabel =
    detail.value?.job_id === selectedId.value ? detail.value.gate_label : undefined
  const gateLabel =
    gate === 'OVERRIDDEN'
      ? dLabel || 'PASS（人工豁免）'
      : gate === 'PASS'
        ? 'PASS 放行'
        : gate === 'BLOCK'
          ? 'BLOCK 阻断'
          : gate === 'PENDING'
            ? '待 CI 回传'
            : '—'
  const gateColor =
    gate === 'OVERRIDDEN'
      ? '#FDD663'
      : gate === 'PASS'
        ? '#81C995'
        : gate === 'BLOCK'
          ? '#F28B82'
          : '#8E9299'
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
      value: passKpi.value.rate != null ? `${passKpi.value.rate.toFixed(1)}%` : '—',
      sub:
        passKpi.value.total > 0
          ? `通过 ${passKpi.value.passed} / ${passKpi.value.total} 条`
          : '暂无已执行用例批次',
      accent: '#81C995',
      icon: 'mdi-check-circle-outline',
      iconBg: 'rgba(52, 168, 83, 0.15)',
      iconColor: '#81C995',
    },
    {
      title: '探针增量行覆盖率',
      value: coverageKpi.value.pct != null ? `${coverageKpi.value.pct}%` : '—',
      sub:
        coverageKpi.value.changed > 0
          ? `变更 ${coverageKpi.value.changed} 行，探针命中 ${coverageKpi.value.covered} 行`
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
      icon:
        gate === 'BLOCK' ? 'mdi-shield-alert' : gate === 'OVERRIDDEN' ? 'mdi-shield-edit' : 'mdi-shield-check',
      iconBg:
        gate === 'BLOCK'
          ? 'rgba(234, 67, 53, 0.15)'
          : gate === 'OVERRIDDEN'
            ? 'rgba(253, 214, 99, 0.18)'
            : 'rgba(52, 168, 83, 0.15)',
      iconColor: gateColor,
      valueColor: gateColor,
      isGate: true,
    },
  ]
})


function gateChipClass(gate: string) {
  if (gate === 'OVERRIDDEN') return 'batch-chip--override'
  if (gate === 'PASS') return 'batch-chip--pass'
  if (gate === 'BLOCK') return 'batch-chip--block'
  return 'batch-chip--pending'
}

function batchGateChipText(gate: string) {
  if (gate === 'OVERRIDDEN') return '豁免'
  return gate
}

function detailGateDisplayText(d: RegressionBatchDetail) {
  return d.gate_label || d.gate
}

function detailMetaGateClass(gate: string) {
  if (gate === 'OVERRIDDEN') return 'detail-gate-chip--override'
  if (gate === 'PASS') return 'detail-gate-chip--pass'
  if (gate === 'BLOCK') return 'detail-gate-chip--block'
  return 'detail-gate-chip--pending'
}

function formatOverrideAudit(mo: NonNullable<RegressionBatchDetail['manual_override']>) {
  const when = formatLocalDateTime(mo.at)
  const t = when.match(/\d{2}:\d{2}/)?.[0] ?? when
  const day = when.match(/\d{4}-\d{2}-\d{2}/)?.[0] ?? ''
  const stamp = day && t ? `${day} ${t}` : when
  return `已由 @${mo.actor} 于 ${stamp} 人工特批放行 · 原因：${mo.reason_category_label}。${mo.reason_detail}`
}

const overrideDetailMinLen = 2

const overrideDetailHint = computed(() => {
  const n = overrideDetail.value.trim().length
  if (n >= overrideDetailMinLen) return ''
  return `详细说明至少 ${overrideDetailMinLen} 个字（当前 ${n} 字）`
})

const overrideSubmitDisabled = computed(
  () => overrideDetail.value.trim().length < overrideDetailMinLen || overrideSubmitting.value,
)

function openOverrideDialog() {
  overrideCategory.value = 'hotfix'
  overrideDetail.value = ''
  overrideError.value = ''
  overrideDialog.value = true
}

async function submitOverride() {
  if (!selectedId.value || overrideDetail.value.trim().length < overrideDetailMinLen) return
  overrideSubmitting.value = true
  overrideError.value = ''
  try {
    await submitRegressionGateOverride(selectedId.value, {
      reason_category: overrideCategory.value,
      reason_detail: overrideDetail.value.trim(),
      actor: overrideActor.value.trim() || 'admin',
    })
    overrideDialog.value = false
    await Promise.all([loadList(), loadDetail(selectedId.value)])
  } catch (err) {
    overrideError.value = readApiError(
      err,
      '提交失败；若接口返回 404，请重启 API（scripts/run_api.ps1）后再试',
    )
  } finally {
    overrideSubmitting.value = false
  }
}

const detailIsSparse = computed(() => {
  if (!detail.value) return false
  const d = detail.value
  return !d.cases.length && !d.coverage_lines.length
})

async function loadList() {
  loading.value = true
  try {
    const [ov, list, dash] = await Promise.all([
      fetchRegressionOverview(repoFilter.value || undefined, gateFilter.value || undefined),
      fetchRegressionBatches(repoFilter.value || undefined, gateFilter.value || undefined),
      fetchDashboardOverview(7),
    ])
    overview.value = ov
    batches.value = list
    repoGateStats.value = dash.repo_gate_stats ?? []
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
  expandedCaseKey.value = null
  if (id) loadDetail(id)
})

watch([repoFilter, gateFilter], loadList)

async function applyJobFromQuery() {
  const q = route.query.job
  const jobId = typeof q === 'string' ? q : Array.isArray(q) ? q[0] : null
  if (!jobId) return
  selectedId.value = jobId
  await loadDetail(jobId)
  const batch = batches.value.find((b) => b.job_id === jobId)
  if (batch?.repo) {
    repoFilter.value = batch.repo
  }
}

onMounted(async () => {
  await loadList()
  await applyJobFromQuery()
})

watch(
  () => route.query.job,
  () => {
    void applyJobFromQuery()
  },
)
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
        <RepoAutocompleteFilter
          v-model="repoFilter"
          field-class="filter-select-repo"
          :gate-stats="repoGateStats"
        />
        <v-select
          v-model="gateFilter"
          class="filter-gate"
          :items="gateOptions"
          item-title="title"
          item-value="value"
          :menu-props="filterMenuProps"
          variant="solo"
          flat
          density="compact"
          hide-details
          rounded="lg"
          prepend-inner-icon="mdi-shield-half-full"
        >
          <template #item="{ props: itemProps, item }">
            <v-list-item
              v-bind="filterSelectItemProps(itemProps)"
              :title="item.raw.title"
              class="filter-menu-item filter-menu-item--gate"
              :class="{ 'filter-menu-item--selected': gateFilter === item.raw.value }"
              rounded="lg"
              density="comfortable"
            >
              <template #append>
                <v-icon
                  v-if="gateFilter === item.raw.value"
                  icon="mdi-check"
                  size="18"
                  color="#e8eaed"
                  class="filter-menu-item__check"
                />
              </template>
            </v-list-item>
          </template>
        </v-select>
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
                  {{ batchGateChipText(item.gate) }}
                </v-chip>
                <div class="batch-card__head">
                  <div class="batch-card__title text-truncate">{{ repoShortName(item.repo) }}</div>
                  <span
                    v-if="formatBranchLabel(item.ref)"
                    class="batch-branch-tag"
                    :title="item.ref"
                  >
                    {{ formatBranchLabel(item.ref) }}
                  </span>
                </div>
                <div class="batch-card__meta mono text-caption text-medium-emphasis">
                  {{ formatBatchMeta(item) }}
                </div>
              </button>
            </div>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" lg="8" class="detail-col">
        <v-card
          class="m3-surface-card m3-elevated detail-panel h-100"
          :class="{ 'detail-panel--sparse': detailIsSparse }"
          rounded="xl"
          :border="false"
        >
          <div class="detail-head">
            <h3 class="detail-head-title">批次执行详情</h3>
            <v-btn-toggle
              v-model="detailTab"
              mandatory
              density="comfortable"
              class="detail-segment"
              rounded="lg"
              divided
            >
              <v-btn value="cases" size="small" class="text-none detail-segment-btn">受影响 API 用例</v-btn>
              <v-btn value="coverage" size="small" class="text-none detail-segment-btn">增量覆盖率</v-btn>
            </v-btn-toggle>
          </div>
          <v-card-text
            class="detail-body"
            :class="{ 'detail-body--sparse': detailIsSparse && detailTab === 'cases' }"
          >
            <div v-if="!selectedId && !loading" class="detail-empty text-center py-12 px-4">
              <v-icon icon="mdi-cursor-default-click-outline" size="40" color="#5f6368" class="mb-3" />
              <p class="text-body-2 text-medium-emphasis mb-0">请在左侧选择回归批次</p>
            </div>
            <v-skeleton-loader v-else-if="detailLoading" type="article" />
            <template v-else-if="detail">
              <div class="detail-meta" aria-label="批次元数据">
                <div class="detail-meta-item">
                  <span class="detail-meta-label">仓库</span>
                  <span class="detail-meta-value mono text-truncate" :title="detail.repo">{{ detail.repo }}</span>
                </div>
                <div class="detail-meta-item">
                  <span class="detail-meta-label">Commit</span>
                  <span class="detail-meta-value mono">{{ detail.commit?.slice(0, 8) ?? '—' }}</span>
                </div>
                <div class="detail-meta-item detail-meta-item--gate">
                  <span class="detail-meta-label">门禁</span>
                  <div class="detail-gate-row">
                    <v-chip
                      size="small"
                      variant="flat"
                      rounded="pill"
                      class="detail-gate-chip"
                      :class="detailMetaGateClass(detail.gate)"
                    >
                      {{ detailGateDisplayText(detail) }}
                    </v-chip>
                    <v-btn
                      v-if="detail.gate === 'BLOCK'"
                      size="small"
                      variant="outlined"
                      rounded="pill"
                      class="text-none override-gate-btn"
                      @click="openOverrideDialog"
                    >
                      人工豁免放行
                    </v-btn>
                  </div>
                </div>
              </div>
              <p
                v-if="detail.manual_override"
                class="override-audit-banner"
                role="status"
              >
                <v-icon icon="mdi-shield-account" size="18" class="me-2" />
                {{ formatOverrideAudit(detail.manual_override) }}
              </p>
              <div class="detail-tab-content">
                <v-window v-model="detailTab">
                  <v-window-item value="cases">
                    <div
                      v-if="!detail.cases.length"
                      class="detail-hint-box"
                      role="status"
                    >
                      <v-icon icon="mdi-package-variant" size="22" color="#8e9299" class="detail-hint-box__icon" />
                      <p class="detail-hint-box__text mb-0">
                        本批次无命中 API，未下发 YAML 用例。
                      </p>
                    </div>
                    <div v-else class="case-list">
                      <div
                        v-for="row in detail.cases"
                        :key="caseRowKey(row)"
                        class="case-block"
                      >
                        <button
                          type="button"
                          class="case-row"
                          :class="{ 'case-row--open': expandedCaseKey === caseRowKey(row) }"
                          @click="toggleCaseRow(row)"
                        >
                          <div class="case-main min-width-0">
                            <div class="mono text-body-2 font-weight-medium">
                              {{ row.method }} {{ row.path }}
                            </div>
                            <div class="text-caption text-medium-emphasis mono">{{ row.yaml_file }}</div>
                          </div>
                          <div class="case-assertions text-caption">
                            <span
                              v-for="(a, ai) in caseAssertions(row)"
                              :key="ai"
                              class="case-assertion-pill"
                            >
                              {{ a }}
                            </span>
                          </div>
                          <div class="case-row__tail">
                            <v-chip
                              size="x-small"
                              variant="flat"
                              rounded="pill"
                              :class="row.status === 'PASS' ? 'case-chip--pass' : 'case-chip--fail'"
                            >
                              {{ row.status }}
                            </v-chip>
                            <span class="mono text-caption case-ms">{{ row.duration_ms }} ms</span>
                            <span class="case-expand-label">查看报文详情</span>
                            <v-icon
                              :icon="
                                expandedCaseKey === caseRowKey(row)
                                  ? 'mdi-chevron-up'
                                  : 'mdi-chevron-down'
                              "
                              size="18"
                            />
                          </div>
                        </button>
                        <div
                          v-if="expandedCaseKey === caseRowKey(row)"
                          class="case-expand"
                        >
                          <div class="case-expand__section">
                            <span class="case-expand__label">请求</span>
                            <pre class="case-expand__pre mono">{{ row.request_preview || `${row.method} ${row.path}` }}</pre>
                          </div>
                          <div class="case-expand__section">
                            <span class="case-expand__label">响应</span>
                            <pre class="case-expand__pre mono">{{ caseResponsePreview(row) }}</pre>
                          </div>
                        </div>
                      </div>
                    </div>
                  </v-window-item>
                  <v-window-item value="coverage">
                    <div class="coverage-summary">
                      <span class="coverage-summary-label">增量覆盖率</span>
                      <span class="coverage-summary-value mono">
                        {{
                          detail.incremental_coverage_pct != null
                            ? `${detail.incremental_coverage_pct}%`
                            : '—'
                        }}
                      </span>
                      <span class="coverage-summary-divider" aria-hidden="true">·</span>
                      <span class="coverage-summary-meta">变更 {{ detail.changed_lines }} 行</span>
                    </div>
                    <p
                      v-if="detail.incremental_coverage_pct == null && detail.coverage_lines.length"
                      class="coverage-pending-hint"
                    >
                      已展示变更行探针占位；覆盖率百分比待 CI 回传 coverage 报告后更新。
                    </p>
                    <div
                      v-if="!detail.coverage_lines.length"
                      class="detail-hint-box detail-hint-box--compact"
                      role="status"
                    >
                      <v-icon icon="mdi-file-chart-outline" size="22" color="#8e9299" class="detail-hint-box__icon" />
                      <p class="detail-hint-box__text mb-0">
                        暂无探针命中行数据，请通过 CI 回传 coverage 报告。
                      </p>
                    </div>
                    <div v-else class="coverage-scroll-shell">
                      <div class="coverage-scroll mono" tabindex="0">
                        <div
                          v-for="(line, idx) in detail.coverage_lines"
                          :key="idx"
                          class="coverage-line"
                          :class="{
                            'coverage-line--hit': line.covered === true,
                            'coverage-line--miss': line.covered === false,
                            'coverage-line--unknown': line.covered == null,
                          }"
                        >
                          <span class="coverage-line__sign">{{ line.prefix || '+' }}</span>
                          <span class="coverage-line__path">{{ line.file }}</span>
                          <span class="coverage-line__lno">:{{ line.line }}</span>
                        </div>
                      </div>
                    </div>
                  </v-window-item>
                </v-window>
              </div>
            </template>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-dialog v-model="overrideDialog" max-width="520" scrollable>
      <v-card class="override-dialog" rounded="xl">
        <v-card-title class="text-h6 font-weight-bold">人工豁免放行</v-card-title>
        <v-card-subtitle class="text-body-2 text-medium-emphasis pb-0">
          仅记录审计信息并调整门禁展示；请确认已与测试负责人达成共识。
        </v-card-subtitle>
        <v-card-text class="pt-4">
          <div class="text-caption text-medium-emphasis mb-2">原因分类</div>
          <v-radio-group v-model="overrideCategory" hide-details class="override-radio-group">
            <v-radio
              v-for="opt in overrideReasonOptions"
              :key="opt.value"
              :value="opt.value"
              :label="opt.title"
              color="#8ab4f8"
            />
          </v-radio-group>
          <v-textarea
            v-model="overrideDetail"
            class="mt-4"
            label="详细说明（必填）"
            placeholder="例：已与测试负责人确认，该异常分支仅在磁盘损坏时触发，同意发版。"
            rows="3"
            variant="outlined"
            rounded="lg"
            :hint="
              overrideDetailHint ||
              (overrideDetail.trim().length >= overrideDetailMinLen
                ? '已满足最少字数，可提交豁免'
                : `请填写豁免依据，至少 ${overrideDetailMinLen} 个字`)
            "
            persistent-hint
          />
          <p v-if="overrideError" class="override-error mt-3 mb-0" role="alert">{{ overrideError }}</p>
          <v-text-field
            v-model="overrideActor"
            class="mt-3"
            label="操作人"
            variant="outlined"
            density="compact"
            rounded="lg"
            hide-details
          />
        </v-card-text>
        <v-card-actions class="px-4 pb-4">
          <v-spacer />
          <v-btn variant="text" class="text-none" @click="overrideDialog = false">取消</v-btn>
          <v-btn
            color="#8ab4f8"
            variant="flat"
            class="text-none"
            :disabled="overrideSubmitDisabled"
            :loading="overrideSubmitting"
            @click="submitOverride"
          >
            确认豁免
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<style scoped>
.regression-page {
  width: 100%;
  max-width: 100%;
}
.regression-page :deep(.kpi-row),
.regression-page :deep(.master-detail-row) {
  margin-inline: 0;
  width: 100%;
}
.regression-page :deep(.kpi-row > .v-col),
.regression-page :deep(.master-detail-row > .v-col) {
  padding-inline: 8px;
}
.regression-page :deep(.kpi-row > .v-col:first-child),
.regression-page :deep(.master-detail-row > .v-col:first-child) {
  padding-inline-start: 0;
}
.regression-page :deep(.kpi-row > .v-col:last-child),
.regression-page :deep(.master-detail-row > .v-col:last-child) {
  padding-inline-end: 0;
}
.master-detail-row .batch-panel :deep(.v-card-title.panel-title) {
  padding: 20px 22px 12px !important;
}
.regression-sub {
  max-width: 640px;
  line-height: 1.5;
}
.regression-filters {
  margin-inline-start: auto;
  align-items: center;
}
.regression-filters :deep(.repo-autocomplete.filter-select-repo) {
  width: 280px !important;
  min-width: 280px !important;
  max-width: 280px !important;
  flex: 0 0 280px;
}
.filter-gate {
  width: 130px;
  min-width: 130px;
  max-width: 130px;
  flex: 0 0 130px;
}
.regression-filters :deep(.repo-autocomplete.filter-select-repo .v-field__input),
.filter-gate :deep(.v-field__input) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.btn-trigger-regression {
  background: #f1f3f5 !important;
  color: #111315 !important;
}
.regression-filters :deep(.repo-autocomplete.filter-select-repo .v-field),
.regression-filters :deep(.filter-gate .v-field) {
  min-height: 40px;
  height: 40px;
  border: 1px solid #2a2e35;
  background: rgb(var(--v-theme-surface)) !important;
  font-size: 13px;
  border-radius: 10px;
}
.regression-filters :deep(.v-field__outline) {
  opacity: 0 !important;
}
.dashboard-stack-gap {
  margin-bottom: 24px !important;
}
.m3-surface-card {
  background-color: rgb(var(--v-theme-surface)) !important;
  border: 1px solid rgb(var(--v-theme-outline));
}
.m3-elevated {
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.45), 0 2px 8px rgba(0, 0, 0, 0.28);
}
.batch-panel,
.detail-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.batch-panel :deep(.v-card-text.batch-list-wrap) {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
}
.batch-list-wrap {
  flex: 1;
  min-height: 0;
  padding: 0 22px 24px !important;
}
.master-detail-row .detail-panel {
  padding: 20px 22px 24px;
  box-sizing: border-box;
}
.detail-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px 16px;
  padding: 0;
}
.detail-head-title {
  margin: 0;
  font-size: 1.125rem;
  font-weight: 700;
  line-height: 1.3;
  color: #e8eaed;
}
.detail-segment {
  border: 1px solid #2e333b;
  background: #111315;
  overflow: hidden;
}
.detail-segment :deep(.v-btn) {
  min-width: 108px;
  letter-spacing: 0;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.55);
  background: transparent !important;
}
.detail-segment :deep(.v-btn--active) {
  color: #e8eaed !important;
  background: rgba(138, 180, 248, 0.26) !important;
  box-shadow: inset 0 -2px 0 #8ab4f8;
}
.detail-body {
  flex: 1;
  padding: 16px 0 0 !important;
}
.detail-body--sparse {
  min-height: 0 !important;
}
.detail-panel--sparse .detail-body {
  padding-bottom: 28px !important;
}
.detail-tab-content {
  margin-top: 20px;
}
.batch-empty-tip {
  max-width: 300px;
  margin-inline: auto;
  line-height: 1.5;
}
.batch-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding-right: 6px;
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
  transition:
    border-color 0.15s ease,
    background 0.15s ease,
    box-shadow 0.15s ease;
}
.batch-card:hover {
  background: #24282e;
}
.batch-card--active {
  border: 1px solid rgba(138, 180, 248, 0.45);
  background: #242933;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.22), 0 0 0 1px rgba(138, 180, 248, 0.12);
}
.batch-card__head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding-right: 56px;
}
.batch-card__title {
  font-size: 15px;
  font-weight: 700;
  line-height: 1.35;
  color: #f1f3f5;
  min-width: 0;
}
.batch-branch-tag {
  flex-shrink: 0;
  max-width: 92px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 500;
  line-height: 1.35;
  color: rgba(255, 255, 255, 0.62);
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.batch-card__meta {
  margin-top: 6px;
  line-height: 1.45;
  opacity: 0.72;
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
.detail-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 24px;
  padding: 12px 16px;
  border-radius: 12px;
  border: 1px solid #2e333b;
  background: #14171a;
}
.detail-meta-item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  column-gap: 6px;
  min-width: 0;
  max-width: 100%;
}
.detail-meta-item--gate {
  grid-template-columns: auto auto;
  margin-inline-start: auto;
}
.detail-meta-label {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.48);
  flex-shrink: 0;
}
.detail-meta-label::after {
  content: '：';
}
.detail-meta-value {
  font-size: 13px;
  color: #e8eaed;
  max-width: 280px;
}
.detail-gate-chip {
  font-weight: 600;
  font-size: 12px !important;
  padding-inline: 14px !important;
  min-height: 28px !important;
}
.detail-gate-chip :deep(.v-chip__content) {
  padding-inline: 2px;
}
.detail-gate-chip--pass {
  background: rgba(52, 168, 83, 0.18) !important;
  color: #81c995 !important;
}
.detail-gate-chip--block {
  background: rgba(234, 67, 53, 0.18) !important;
  color: #f28b82 !important;
}
.detail-gate-chip--pending {
  background: rgba(142, 146, 153, 0.2) !important;
  color: #bdc1c6 !important;
}
.detail-gate-chip--override {
  background: rgba(253, 214, 99, 0.22) !important;
  color: #fdd663 !important;
}
.detail-gate-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.override-gate-btn {
  border-color: rgba(253, 214, 99, 0.45) !important;
  color: #fdd663 !important;
}
.override-error {
  font-size: 13px;
  line-height: 1.45;
  color: #f28b82;
}
.override-audit-banner {
  display: flex;
  align-items: flex-start;
  margin: 12px 0 4px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid rgba(253, 214, 99, 0.28);
  background: rgba(253, 214, 99, 0.08);
  font-size: 12px;
  line-height: 1.5;
  color: rgba(253, 214, 99, 0.92);
}
.batch-chip--override {
  background: rgba(253, 214, 99, 0.18) !important;
  color: #fdd663 !important;
}
.detail-hint-box {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 12px;
  border: 1px solid #2e333b;
  background: rgba(255, 255, 255, 0.04);
}
.detail-hint-box--compact {
  margin-top: 12px;
}
.detail-hint-box__text {
  font-size: 14px;
  line-height: 1.55;
  color: rgba(255, 255, 255, 0.72);
}
.detail-hint-box__icon {
  flex-shrink: 0;
  margin-top: 2px;
}
.case-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.case-block {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.case-row {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 1.2fr) auto;
  gap: 10px 12px;
  align-items: center;
  width: 100%;
  text-align: left;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid rgb(var(--v-theme-outline));
  background: #1a1d21;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.case-row:hover {
  background: #22262c;
  border-color: #3a4048;
}
.case-row--open {
  border-color: #8ab4f8;
  background: rgba(138, 180, 248, 0.06);
}
.case-assertions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}
.case-assertion-pill {
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04);
  color: rgba(255, 255, 255, 0.72);
  white-space: nowrap;
}
.case-row__tail {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}
.case-expand-label {
  font-size: 11px;
  color: rgba(138, 180, 248, 0.92);
  white-space: nowrap;
}
.case-expand {
  margin-top: -4px;
  padding: 10px 14px 12px;
  border: 1px solid #2e333b;
  border-top: none;
  border-radius: 0 0 12px 12px;
  background: #14171a;
}
.case-expand__section + .case-expand__section {
  margin-top: 10px;
}
.case-expand__label {
  display: block;
  font-size: 11px;
  color: rgba(255, 255, 255, 0.48);
  margin-bottom: 4px;
}
.case-expand__pre {
  margin: 0;
  padding: 8px 10px;
  border-radius: 8px;
  background: #0d0f11;
  font-size: 11px;
  line-height: 1.45;
  color: rgba(255, 255, 255, 0.82);
  white-space: pre-wrap;
  word-break: break-word;
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
.coverage-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px 8px;
  font-size: 14px;
  margin-bottom: 12px;
}
.coverage-summary-label {
  color: rgba(255, 255, 255, 0.55);
}
.coverage-summary-value {
  font-weight: 600;
  color: #fdd663;
  font-size: 1.05rem;
}
.coverage-summary-divider,
.coverage-summary-meta {
  color: rgba(255, 255, 255, 0.5);
  font-size: 13px;
}
.coverage-pending-hint {
  margin: 0 0 10px;
  font-size: 12px;
  line-height: 1.45;
  color: rgba(253, 214, 99, 0.82);
}
.coverage-scroll-shell {
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: #0d0f11;
  overflow: hidden;
}
.coverage-scroll {
  max-height: 400px;
  overflow-x: hidden;
  overflow-y: auto;
  padding: 12px 20px 12px 16px;
  font-size: 12px;
  line-height: 1.6;
}
.coverage-line {
  display: flex;
  flex-wrap: wrap;
  gap: 0 4px;
  padding: 3px 8px;
  border-radius: 4px;
}
.coverage-line--unknown {
  color: #9aa0a6;
}
.coverage-line--unknown .coverage-line__sign {
  color: #4caf50;
}
.coverage-line--hit {
  background: rgba(76, 175, 80, 0.14);
  color: #c8e6c9;
}
.coverage-line--hit .coverage-line__sign {
  color: #4caf50;
  font-weight: 600;
}
.coverage-line--miss {
  background: rgba(234, 67, 53, 0.12);
  color: #f28b82;
}
.coverage-line__sign {
  flex-shrink: 0;
  width: 1.25em;
  color: #4caf50;
  font-weight: 600;
}
.coverage-line__path {
  color: rgba(255, 255, 255, 0.8);
  word-break: break-all;
}
.coverage-line__lno {
  color: rgba(255, 255, 255, 0.34);
}
.master-detail-row {
  align-items: stretch;
}
.master-detail-row .batch-col,
.master-detail-row .detail-col {
  display: flex;
}
.master-detail-row .batch-panel,
.master-detail-row .detail-panel {
  width: 100%;
}
@media (max-width: 1279px) {
  .detail-meta-item--gate {
    margin-inline-start: 0;
    width: 100%;
  }
}
</style>

<style>
.regression-filter-menu {
  border: 1px solid #3a3f47 !important;
  border-radius: 8px !important;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5) !important;
  background: #282c34 !important;
  color-scheme: dark;
}
.regression-filter-menu .v-list {
  background: #282c34;
  padding: 6px 4px;
}
.regression-filter-menu .filter-menu-item {
  min-height: 44px !important;
  padding-inline: 16px 12px !important;
  margin-bottom: 2px;
  color: rgba(255, 255, 255, 0.9);
  background: transparent !important;
}
.regression-filter-menu .filter-menu-item .v-list-item__overlay {
  opacity: 0 !important;
}
.regression-filter-menu .filter-menu-item .v-list-item__underlay {
  display: none;
}
.regression-filter-menu .filter-menu-item .v-list-item__content {
  min-width: 0;
  text-align: left;
}
.regression-filter-menu .filter-menu-item .v-list-item-title {
  font-size: 14px;
  font-weight: 500;
  line-height: 1.35;
  text-align: left;
  color: rgba(255, 255, 255, 0.9);
}
.regression-filter-menu .filter-menu-item .v-list-item-subtitle {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.5);
  margin-top: 2px;
  text-align: left;
}
.regression-filter-menu .filter-menu-item:hover:not(.filter-menu-item--selected),
.regression-filter-menu .filter-menu-item.v-list-item--active:not(.filter-menu-item--selected) {
  background: rgba(255, 255, 255, 0.08) !important;
}
.regression-filter-menu .filter-menu-item--selected,
.regression-filter-menu .filter-menu-item--selected:hover,
.regression-filter-menu .filter-menu-item--selected.v-list-item--active {
  background: rgba(59, 130, 246, 0.15) !important;
}
.regression-filter-menu .filter-menu-item--selected .v-list-item-title,
.regression-filter-menu .filter-menu-item--selected .v-list-item-subtitle {
  color: #ffffff;
}
.regression-filter-menu .filter-menu-item .v-list-item__append {
  width: 28px;
  justify-content: flex-end;
}
.regression-filter-menu .filter-menu-item__check {
  opacity: 1;
}
.regression-filter-menu .filter-menu-item--gate .v-list-item-title {
  font-size: 14px;
}
</style>