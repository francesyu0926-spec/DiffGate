<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  fetchDashboardOverview,
  fetchRegressionBatchDetail,
  fetchRegressionBatches,
  fetchRegressionOverview,
  fetchWhoami,
  loadStoredActor,
  readApiError,
  submitRegressionGateOverride,
  type GateOverrideReasonCategory,
  type GateTriggerDetail,
  type HighRiskDetails,
  type RegressionBatchDetail,
  type RegressionBatchItem,
} from '@/api/client'
import RepoAutocompleteFilter, { type RepoGateStat } from '@/components/RepoAutocompleteFilter.vue'
import CodeDiffDrawer from '@/components/CodeDiffDrawer.vue'
import GateTriggerDetailDrawer from '@/components/GateTriggerDetailDrawer.vue'
import Md3LoadState from '@/components/Md3LoadState.vue'
import { formatLocalDateTime } from '@/utils/datetime'
import { dismissRegressionFilterMenus } from '@/utils/dismissOverlays'

const router = useRouter()
const route = useRoute()

const loading = ref(false)
const repoFilter = ref<string | null>(null)
const gateFilter = ref<string | null>(null)
const gateFilterMenuOpen = ref(false)
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
const detailLoadError = ref<string | null>(null)
const detailTab = ref<'cases' | 'coverage'>('cases')
const gateDetailDrawerOpen = ref(false)
const gateDetailDrawerMode = ref<'high_risk' | 'trigger'>('trigger')
const expandedCaseKey = ref<string | null>(null)

const overrideDialog = ref(false)
const overrideSubmitting = ref(false)
const sessionActor = ref(loadStoredActor())
const sessionRoleLabel = ref('')
const canManualOverride = ref(false)
const copyShareOpen = ref(false)
const copyShareMessage = ref('')
const overrideCategory = ref<GateOverrideReasonCategory>('hotfix')
const overrideDetail = ref('')
const overrideError = ref('')

const overrideReasonOptions = [
  { value: 'hotfix' as const, title: '紧急线上 Hotfix 优先发布' },
  { value: 'fe_be_coordinated' as const, title: '前后端协同改造中' },
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

function batchCoveragePct(item: RegressionBatchItem): number | null {
  if (item.job_id === selectedId.value && detail.value?.job_id === item.job_id) {
    return coverageKpi.value.pct
  }
  const changed = item.changed_lines ?? 0
  const covered = item.covered_lines ?? 0
  if (changed > 0) {
    return Math.round((covered / changed) * 1000) / 10
  }
  return item.coverage ?? null
}

function formatBatchMeta(item: RegressionBatchItem) {
  const time = formatBatchTime(item.created_at)
  const pct = batchCoveragePct(item)
  const cov = pct != null ? `${pct}%` : '—'
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

function coveragePctFromHits(changed: number, covered: number, stored: number | null | undefined) {
  if (changed > 0) {
    return Math.round((covered / changed) * 1000) / 10
  }
  return stored ?? null
}

function resolveCoverageTriple(
  changed: number,
  covered: number,
  storedPct: number | null | undefined,
) {
  return {
    pct: coveragePctFromHits(changed, covered, storedPct),
    changed,
    covered,
  }
}

const coverageKpi = computed(() => {
  if (detail.value?.job_id === selectedId.value) {
    const changed = detail.value.changed_lines ?? 0
    const covered =
      detail.value.covered_lines ??
      (detail.value.coverage_lines ?? []).filter((l) => l.covered === true).length
    return resolveCoverageTriple(changed, covered, detail.value.incremental_coverage_pct)
  }
  const k = overview.value?.kpi
  return resolveCoverageTriple(
    k?.changed_lines ?? 0,
    k?.covered_lines ?? 0,
    k?.incremental_coverage_pct ?? null,
  )
})

const coveragePctToneClass = computed(() => {
  const pct = coverageKpi.value.pct
  if (pct == null) return ''
  if (pct >= 80) return 'coverage-summary-value--good'
  if (pct > 0) return 'coverage-summary-value--warn'
  return 'coverage-summary-value--bad'
})

type CoverageLineRow = RegressionBatchDetail['coverage_lines'][number]
type CoverageFilter = 'all' | 'hit' | 'miss'

const coverageFilter = ref<CoverageFilter>('all')
const expandedCoverageFiles = ref<string[]>([])
const coveragePanelsExpandAll = ref(false)

const detailProbeLines = computed(() => {
  if (detail.value?.job_id !== selectedId.value) return [] as CoverageLineRow[]
  return detail.value.coverage_lines ?? []
})

function buildCoverageLineRanges(lines: CoverageLineRow[]) {
  const ranges: { start: number; end: number; lines: CoverageLineRow[] }[] = []
  for (const ln of lines) {
    const n = ln.line ?? 0
    const last = ranges[ranges.length - 1]
    if (last && n === last.end + 1) {
      last.end = n
      last.lines.push(ln)
    } else {
      ranges.push({ start: n, end: n, lines: [ln] })
    }
  }
  return ranges
}

const coverageFileGroups = computed(() => {
  const map = new Map<string, CoverageLineRow[]>()
  for (const ln of detailProbeLines.value) {
    const f = ln.file || 'unknown'
    const arr = map.get(f) ?? []
    arr.push(ln)
    map.set(f, arr)
  }
  const groups = [...map.entries()].map(([file, fileLines]) => {
    const sorted = [...fileLines].sort((a, b) => (a.line ?? 0) - (b.line ?? 0))
    const hit = sorted.filter((l) => l.covered === true).length
    const miss = sorted.filter((l) => l.covered === false).length
    const unknown = sorted.filter((l) => l.covered == null).length
    const total = sorted.length
    const pct = total > 0 ? Math.round((hit / total) * 1000) / 10 : 0
    return {
      file,
      lines: sorted,
      hit,
      total,
      miss,
      unknown,
      pct,
      ranges: buildCoverageLineRanges(sorted),
    }
  })
  groups.sort((a, b) => {
    if (a.miss !== b.miss) return b.miss - a.miss
    if (a.pct !== b.pct) return a.pct - b.pct
    return a.file.localeCompare(b.file)
  })
  return groups
})

function lineMatchesCoverageFilter(
  covered: boolean | null | undefined,
  mode: CoverageFilter,
): boolean {
  if (mode === 'hit') return covered === true
  if (mode === 'miss') return covered !== true
  return true
}

const filteredCoverageGroups = computed(() => {
  const mode = coverageFilter.value
  return coverageFileGroups.value
    .map((g) => {
      const lines = g.lines.filter((l) => lineMatchesCoverageFilter(l.covered, mode))
      if (!lines.length && mode !== 'all') return null
      const hit = lines.filter((l) => l.covered === true).length
      const miss = lines.filter((l) => l.covered === false).length
      const unknown = lines.filter((l) => l.covered == null).length
      const total = lines.length
      const pct = total > 0 ? Math.round((hit / total) * 1000) / 10 : 0
      return {
        ...g,
        lines,
        hit,
        miss,
        unknown,
        total,
        pct,
        ranges: buildCoverageLineRanges(lines),
      }
    })
    .filter((row): row is NonNullable<typeof row> => row != null)
})

const coverageFilterEmptyText = computed(() => {
  if (coverageFilter.value === 'hit') {
    return '暂无已覆盖行。探针命中为 0 时，请优先查看「未覆盖」或「全部」。'
  }
  if (coverageFilter.value === 'miss') {
    return '暂无未覆盖行。若变更行均为灰点「未探针」，请在「全部」中查看并等待 CI 回传探针结果。'
  }
  return '暂无覆盖率数据。'
})

function resetCoveragePanelExpansion() {
  coveragePanelsExpandAll.value = false
  const groups = coverageFileGroups.value
  const substandard = groups.filter((g) => g.miss > 0 || g.pct < 100)
  expandedCoverageFiles.value = substandard.slice(0, 3).map((g) => g.file)
}

function toggleCoveragePanelsExpandAll() {
  if (coveragePanelsExpandAll.value) {
    expandedCoverageFiles.value = []
    coveragePanelsExpandAll.value = false
    return
  }
  expandedCoverageFiles.value = filteredCoverageGroups.value.map((g) => g.file)
  coveragePanelsExpandAll.value = true
}

function coverageSegTooltip(seg: CoverageLineRow) {
  const state =
    seg.covered === true ? '已覆盖' : seg.covered === false ? '未覆盖' : '未探针'
  return `L${seg.line ?? '—'} · ${state}`
}

const coverageDiffOpen = ref(false)
const coverageDiffPick = ref<{
  title: string
  file: string
  startLine: number
  endLine: number
} | null>(null)

function openCoverageCodeDiff(file: string, startLine: number, endLine?: number) {
  if (!selectedId.value) return
  const norm = file.replace(/\\/g, '/')
  const base = norm.split('/').pop() || norm
  const end = endLine ?? startLine
  coverageDiffPick.value = { title: base, file: norm, startLine, endLine: end }
  coverageDiffOpen.value = true
}

function coverageLineDotClass(covered: boolean | null | undefined) {
  if (covered === true) return 'coverage-probe-chip--hit'
  if (covered === false) return 'coverage-probe-chip--miss'
  return 'coverage-probe-chip--unknown'
}

function splitCoverageFilePath(file: string) {
  const norm = file.replace(/\\/g, '/')
  const idx = norm.lastIndexOf('/')
  if (idx < 0) return { dir: '', name: norm }
  return { dir: `${norm.slice(0, idx + 1)}`, name: norm.slice(idx + 1) }
}

function coverageLineStateLabel(covered: boolean | null | undefined) {
  if (covered === true) return '已覆盖'
  if (covered === false) return '未覆盖'
  return '未探针'
}

const passKpi = computed(() => {
  const cases = detail.value?.cases ?? []
  if (detail.value?.job_id === selectedId.value && cases.length) {
    const passed = cases.filter((c) => c.status === 'PASS').length
    const total = cases.length
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
        k.baseline_cases > 0 && passKpi.value.total > 0
          ? `最近一批 ${passKpi.value.total} 条 · 仓库全量 ${k.baseline_cases} 条 · 压缩率 ${k.case_reduction_pct}%`
          : k.baseline_cases > 0
            ? `仓库 AST 全量接口 ${k.baseline_cases} 条（多批次累计下发 ${k.executed_cases} 条）`
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
      sub: gateKpiSubText(gate),
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
      gateStatus: gate ?? 'PENDING',
    },
  ]
})

function kpiGateChipClass(gate: string) {
  if (gate === 'OVERRIDDEN') return 'kpi-gate-status-chip--override'
  if (gate === 'PASS') return 'kpi-gate-status-chip--pass'
  if (gate === 'BLOCK') return 'kpi-gate-status-chip--block'
  return 'kpi-gate-status-chip--pending'
}

function resolveBlockReasonLabel(): string {
  const d = detail.value
  if (d?.job_id === selectedId.value) {
    return (
      d.block_reason_label ||
      String(d.gate_result?.block_reason_label || '') ||
      ''
    )
  }
  return overview.value?.kpi?.block_reason_label || ''
}

const gateTriggerDetail = computed((): GateTriggerDetail | null => {
  const d = detail.value
  if (!d || d.job_id !== selectedId.value) return null
  if (d.trigger_detail) return d.trigger_detail
  const raw = d.gate_result?.trigger_detail
  return raw && typeof raw === 'object' ? (raw as GateTriggerDetail) : null
})

const highRiskDetails = computed((): HighRiskDetails | null => {
  const d = detail.value
  if (!d || d.job_id !== selectedId.value) return null
  if (d.high_risk_details) return d.high_risk_details
  const raw = d.gate_result?.high_risk_details
  return raw && typeof raw === 'object' ? (raw as HighRiskDetails) : null
})

const showHighRiskDetails = computed(() => {
  const d = detail.value
  if (!d || !['high_risk_unreviewed', 'breaking_contract_change'].includes(String(d.block_reason || '')))
    return false
  const modules = highRiskDetails.value?.matched_modules ?? []
  return modules.length > 0
})

function openGateDetailDrawer(mode: 'high_risk' | 'trigger') {
  gateDetailDrawerMode.value = mode
  gateDetailDrawerOpen.value = true
}

function openKpiGateDetail() {
  if (showHighRiskDetails.value && highRiskDetails.value) {
    openGateDetailDrawer('high_risk')
  } else {
    openGateDetailDrawer('trigger')
  }
}

function gateKpiSubText(gate: string | null | undefined) {
  const label = resolveBlockReasonLabel()
  const td = gateTriggerDetail.value
  if (gate === 'BLOCK' && td?.summary) return td.summary
  if (gate === 'BLOCK' && label) return `拦截原因：${label}`
  if (gate === 'PENDING') {
    return label ? `待处理：${label}` : '等待 CI 回传覆盖率后自动裁决'
  }
  if (gate === 'PASS') return '回归与增量覆盖率均已满足门禁基线'
  if (gate === 'OVERRIDDEN') return '已人工豁免放行，审计记录见批次详情'
  return '基于最近一批回归与覆盖率门禁'
}


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

const canOverrideBatch = computed(() => {
  const ev = detail.value?.override_eligibility
  if (ev) return ev.allowed
  return (
    canManualOverride.value &&
    detail.value?.gate === 'BLOCK' &&
    detail.value?.allow_manual_override !== false
  )
})

const overrideLockHint = computed(() => {
  const ev = detail.value?.override_eligibility
  if (ev?.hint) return ev.hint
  if (detail.value?.allow_manual_override === false) {
    return '命中不可豁免路径规则（如支付核心）'
  }
  return '当前角色为「研发」，仅 QA 或项目负责人可执行豁免。可复制链接发给 QA 审批。'
})

const showOverrideLock = computed(
  () => detail.value?.gate === 'BLOCK' && !canOverrideBatch.value,
)

const overrideLockKind = computed(() => {
  if (!showOverrideLock.value) return null
  if (detail.value?.allow_manual_override === false) return 'path_blocked'
  return detail.value?.override_eligibility?.reason ?? 'insufficient_role'
})

const overrideLockButtonLabel = computed(() =>
  detail.value?.allow_manual_override === false ? '禁止豁免' : '无豁免权限',
)

const showGateBlockBanner = computed(
  () =>
    detail.value?.gate === 'BLOCK' &&
    Boolean(detail.value?.block_reason_label || gateTriggerDetail.value),
)

const gateBannerThreshold = computed(() => {
  const td = gateTriggerDetail.value
  const hr = highRiskDetails.value
  const m = td?.metrics
  const apiCount = hr?.api_count ?? m?.api_impact
  const symCount = hr?.symbol_count ?? m?.symbol_count
  const apiTh = hr?.api_threshold ?? m?.api_threshold
  const symTh = hr?.symbol_threshold ?? m?.symbol_threshold
  if (apiCount == null || symCount == null) return null
  return {
    apiCount,
    symCount,
    apiTh: apiTh ?? null,
    symTh: symTh ?? null,
  }
})

const gateBannerFallbackText = computed(() => {
  if (gateTriggerDetail.value?.summary) return gateTriggerDetail.value.summary
  const label = detail.value?.block_reason_label || detail.value?.block_reason
  return label ? `拦截原因：${label}` : ''
})

const showDetailAlertStack = computed(() => showOverrideLock.value || showGateBlockBanner.value)

const showOverrideButton = computed(
  () =>
    detail.value?.gate === 'BLOCK' &&
    detail.value?.allow_manual_override !== false &&
    canOverrideBatch.value,
)

async function copyOverrideShare() {
  const ev = detail.value?.override_eligibility
  const text =
    ev?.share_text ||
    ev?.share_url ||
    `${window.location.origin}/regression?job_id=${selectedId.value ?? ''}&action=override`
  try {
    await navigator.clipboard.writeText(text)
    copyShareMessage.value = '审批链接已复制，可粘贴到飞书 / 钉钉 @ QA'
    copyShareOpen.value = true
  } catch {
    copyShareMessage.value = '复制失败，请手动复制浏览器地址栏'
    copyShareOpen.value = true
  }
}

function openOverrideDialog() {
  if (!canOverrideBatch.value) {
    overrideError.value = overrideLockHint.value
    return
  }
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
  return !(d.cases?.length ?? 0) && !(d.coverage_lines?.length ?? 0)
})

const listLoadError = ref<string | null>(null)

const showKpiSkeleton = computed(() => loading.value && !overview.value)

async function loadList() {
  loading.value = true
  listLoadError.value = null
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
  } catch (err) {
    listLoadError.value = readApiError(err, '加载回归列表失败')
    batches.value = []
    overview.value = null
  } finally {
    loading.value = false
  }
}

async function loadDetail(jobId: string) {
  detailLoading.value = true
  detailLoadError.value = null
  try {
    detail.value = await fetchRegressionBatchDetail(jobId)
    const batch = batches.value.find((b) => b.job_id === jobId)
    if (batch && detail.value) {
      batch.coverage = detail.value.incremental_coverage_pct
      batch.changed_lines = detail.value.changed_lines
      batch.covered_lines = detail.value.covered_lines
    }
    resetCoveragePanelExpansion()
  } catch (err) {
    detail.value = null
    detailLoadError.value = readApiError(err, '加载批次详情失败')
  } finally {
    detailLoading.value = false
  }
}

watch(selectedId, (id) => {
  expandedCaseKey.value = null
  coverageFilter.value = 'all'
  gateDetailDrawerOpen.value = false
  if (id) loadDetail(id)
})

watch(coverageFilter, () => {
  coveragePanelsExpandAll.value = false
})

watch([repoFilter, gateFilter], loadList)

onBeforeUnmount(() => {
  gateFilterMenuOpen.value = false
  dismissRegressionFilterMenus()
})

async function applyJobFromQuery() {
  const qJob = route.query.job_id ?? route.query.job ?? route.query.batch
  const jobId = typeof qJob === 'string' ? qJob : Array.isArray(qJob) ? qJob[0] : null
  if (!jobId) return
  selectedId.value = jobId
  await loadDetail(jobId)
  const batch = batches.value.find((b) => b.job_id === jobId)
  if (batch?.repo) {
    repoFilter.value = batch.repo
  }
  const action = route.query.action
  if (action === 'override' && canOverrideBatch.value && detail.value?.gate === 'BLOCK') {
    openOverrideDialog()
  }
}

onMounted(async () => {
  try {
    const who = await fetchWhoami()
    canManualOverride.value = who.can_manual_override
    sessionRoleLabel.value = who.role_label || who.role
    sessionActor.value = {
      username: who.username,
      role: who.role,
      email: who.email || undefined,
    }
  } catch {
    canManualOverride.value = ['qa', 'pm', 'admin', 'owner'].includes(sessionActor.value.role)
  }
  await loadList()
  await applyJobFromQuery()
})

onActivated(() => {
  void applyJobFromQuery()
})

watch(
  () => route.query.job,
  () => {
    void applyJobFromQuery()
  },
)
</script>

<template>
  <v-snackbar v-model="copyShareOpen" :timeout="2200" location="top" color="surface-variant">
    {{ copyShareMessage }}
  </v-snackbar>
  <div class="regression-page">
    <div class="regression-hero mb-4">
      <div class="regression-hero__intro">
        <h2 class="text-h5 text-md-h4 font-weight-bold regression-hero__title">精准回归</h2>
        <p class="text-body-2 mb-0 regression-sub">
          基于 AST 影响面动态筛选关联 YAML 用例执行，采集探针增量覆盖率并生成质量门禁判定。
        </p>
      </div>
      <div class="regression-filters d-flex flex-wrap align-center">
        <RepoAutocompleteFilter
          v-model="repoFilter"
          field-class="filter-select-repo"
          :gate-stats="repoGateStats"
        />
        <v-select
          v-model="gateFilter"
          v-model:menu="gateFilterMenuOpen"
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
          rounded="lg"
          color="#8ab4f8"
          prepend-icon="mdi-play-circle-outline"
          @click="router.push('/repositories')"
        >
          手动触发回归
        </v-btn>
      </div>
    </div>

    <v-row v-if="showKpiSkeleton" class="dashboard-grid dashboard-stack-gap kpi-row">
      <v-col v-for="n in 4" :key="`kpi-skel-${n}`" cols="12" sm="6" lg="3">
        <v-skeleton-loader type="osseous" class="m3-skeleton-tonal kpi-skeleton-md3" boilerplate />
      </v-col>
    </v-row>
    <v-row v-else-if="kpiCards.length" class="dashboard-grid dashboard-stack-gap kpi-row">
      <v-col v-for="card in kpiCards" :key="card.title" cols="12" sm="6" lg="3">
        <v-card class="h-100 kpi-card m3-surface-card m3-elevated" rounded="xl" :border="false">
          <span
            v-if="!card.isGate"
            class="kpi-accent"
            :style="{ backgroundColor: card.accent }"
            aria-hidden="true"
          />
          <v-card-text class="kpi-card-inner">
            <div class="d-flex align-start justify-space-between gap-2 mb-3">
              <div class="text-body-2 text-medium-emphasis kpi-title">{{ card.title }}</div>
              <v-avatar size="40" rounded="lg" :style="{ backgroundColor: card.iconBg }">
                <v-icon :icon="card.icon" :color="card.iconColor" size="22" />
              </v-avatar>
            </div>
            <v-chip
              v-if="card.isGate"
              size="small"
              variant="flat"
              rounded="lg"
              class="kpi-gate-status-chip"
              :class="kpiGateChipClass(card.gateStatus)"
            >
              {{ card.value }}
            </v-chip>
            <div
              v-else
              class="kpi-metric"
              :style="card.valueColor ? { color: card.valueColor } : undefined"
            >
              {{ card.value }}
            </div>
            <p class="text-caption text-medium-emphasis mt-3 mb-0">{{ card.sub }}</p>
            <button
              v-if="
                card.isGate &&
                selectedId &&
                detail?.gate === 'BLOCK' &&
                (gateTriggerDetail || (showHighRiskDetails && highRiskDetails))
              "
              type="button"
              class="kpi-gate-detail-link text-caption text-none"
              @click="openKpiGateDetail"
            >
              查看高危明细 ›
            </button>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-row class="dashboard-grid master-detail-row">
      <v-col cols="12" lg="4" class="batch-col">
        <v-card class="m3-surface-card m3-elevated batch-panel h-100" rounded="xl" :border="false">
          <v-card-title class="text-subtitle-1 font-weight-medium panel-title">回归执行批次</v-card-title>
          <v-card-text class="batch-list-wrap">
            <Md3LoadState
              v-if="loading"
              mode="overlay"
              label="加载回归批次…"
              min-height="320px"
            />
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
          <Md3LoadState v-if="detailLoading" mode="linear" label="加载中" class="detail-panel-top-progress" />
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
            <Md3LoadState
              v-else-if="detailLoading"
              mode="overlay"
              label="加载批次详情…"
              min-height="280px"
            />
            <div
              v-else-if="selectedId && detailLoadError"
              class="detail-empty text-center py-12 px-4"
            >
              <v-icon icon="mdi-alert-circle-outline" size="40" color="#f28b82" class="mb-3" />
              <p class="text-body-2 text-medium-emphasis mb-2">{{ detailLoadError }}</p>
              <v-btn
                size="small"
                variant="tonal"
                class="text-none"
                @click="selectedId && loadDetail(selectedId)"
              >
                重试
              </v-btn>
            </div>
            <div
              v-else-if="selectedId && !detail"
              class="detail-empty text-center py-12 px-4"
            >
              <p class="text-body-2 text-medium-emphasis mb-0">暂无批次详情，请重新选择左侧批次</p>
            </div>
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
                  <div class="detail-gate-col">
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
                        v-if="showOverrideButton"
                        size="small"
                        variant="outlined"
                        rounded="pill"
                        class="text-none override-gate-btn"
                        @click="openOverrideDialog"
                      >
                        人工豁免放行
                      </v-btn>
                    </div>
                    <p
                      v-if="detail.gate === 'PENDING' && detail.block_reason_label"
                      class="detail-gate-reason detail-gate-reason--pending"
                      role="status"
                    >
                      {{ detail.block_reason_label }}
                    </p>
                  </div>
                </div>
              </div>
              <div v-if="showDetailAlertStack" class="detail-alert-stack">
                <div
                  v-if="showOverrideLock"
                  class="detail-rbac-banner"
                  role="status"
                  :aria-label="overrideLockHint"
                >
                  <div class="detail-rbac-banner__body">
                    <v-icon icon="mdi-shield-lock-outline" size="20" class="detail-rbac-banner__icon" />
                    <p class="detail-rbac-banner__text mb-0">
                      <template v-if="overrideLockKind === 'path_blocked'">
                        命中<strong class="detail-rbac-kw">不可豁免路径</strong>规则（如支付核心），请联系管理员处理。
                      </template>
                      <template v-else-if="overrideLockKind === 'self_submit'">
                        触发<strong class="detail-rbac-kw">提交人与审批人互斥</strong>规则，请联系其他
                        <strong class="detail-rbac-kw">QA</strong> / 负责人进行豁免。
                      </template>
                      <template v-else>
                        当前角色为
                        <strong class="detail-rbac-kw">
                          「{{ detail.override_eligibility?.actor_role_label || '研发' }}」
                        </strong>
                        ，仅 <strong class="detail-rbac-kw">QA</strong> 或
                        <strong class="detail-rbac-kw">项目负责人</strong> 可执行豁免。可复制链接发给 QA 审批。
                      </template>
                    </p>
                  </div>
                  <div class="detail-rbac-banner__actions">
                    <v-tooltip :text="overrideLockHint" location="top">
                      <template #activator="{ props: tipProps }">
                        <span v-bind="tipProps" class="detail-rbac-lock-btn" aria-disabled="true">
                          <v-icon icon="mdi-lock" size="14" class="detail-rbac-lock-btn__icon" />
                          {{ overrideLockButtonLabel }}
                        </span>
                      </template>
                    </v-tooltip>
                    <v-btn
                      v-if="detail.override_eligibility?.share_url"
                      size="small"
                      variant="text"
                      class="text-none detail-rbac-share-btn"
                      prepend-icon="mdi-link-variant"
                      @click.stop="copyOverrideShare"
                    >
                      复制审批链接
                    </v-btn>
                  </div>
                </div>
                <div
                  v-if="showGateBlockBanner"
                  class="detail-gate-banner"
                  role="status"
                >
                  <p class="detail-gate-banner__summary mb-0">
                    <template v-if="gateBannerThreshold">
                      影响 API
                      <strong class="detail-gate-count">{{ gateBannerThreshold.apiCount }}</strong>
                      个
                      <span v-if="gateBannerThreshold.apiTh != null"
                        >（阈值 ≥{{ gateBannerThreshold.apiTh }}）</span
                      >，变更符号
                      <strong class="detail-gate-count">{{ gateBannerThreshold.symCount }}</strong>
                      个
                      <span v-if="gateBannerThreshold.symTh != null"
                        >（阈值 ≥{{ gateBannerThreshold.symTh }}）</span
                      >
                    </template>
                    <span v-else>{{ gateBannerFallbackText }}</span>
                  </p>
                  <div class="detail-gate-banner__actions">
                    <button
                      v-if="showHighRiskDetails && highRiskDetails"
                      type="button"
                      class="detail-gate-link detail-gate-text-btn text-none"
                      @click="openGateDetailDrawer('high_risk')"
                    >
                      查看高危明细
                    </button>
                    <span
                      v-if="showHighRiskDetails && highRiskDetails && gateTriggerDetail"
                      class="detail-gate-banner__sep"
                      aria-hidden="true"
                    >|</span>
                    <button
                      v-if="gateTriggerDetail"
                      type="button"
                      class="detail-gate-link detail-gate-text-btn text-none"
                      @click="openGateDetailDrawer('trigger')"
                    >
                      触发细节
                    </button>
                    <span
                      v-if="
                        selectedId &&
                        ((showHighRiskDetails && highRiskDetails) || gateTriggerDetail)
                      "
                      class="detail-gate-banner__sep"
                      aria-hidden="true"
                    >|</span>
                    <router-link
                      v-if="selectedId"
                      :to="{ name: 'job-detail', params: { id: selectedId } }"
                      class="detail-gate-link detail-gate-text-btn"
                    >
                      查看变更影响 ›
                    </router-link>
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
              <div class="detail-tab-content" :class="{ 'detail-tab-content--after-alerts': showDetailAlertStack }">
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
                    <div class="coverage-hero">
                      <div class="coverage-hero__left">
                        <div class="coverage-hero__metrics">
                          <div class="coverage-hero__pct-block">
                            <span class="coverage-summary-label">增量覆盖率</span>
                            <span class="coverage-summary-value mono" :class="coveragePctToneClass">
                              {{ coverageKpi.pct != null ? `${coverageKpi.pct}%` : '—' }}
                            </span>
                          </div>
                          <p class="coverage-hit-line mb-0">
                            命中
                            <span class="mono">{{ coverageKpi.covered }}</span>
                            <span class="coverage-hit-line__sep">/</span>
                            <span class="mono">{{ coverageKpi.changed }}</span> 行
                          </p>
                        </div>
                        <div class="coverage-legend coverage-legend--inline" aria-label="探针图例">
                          <span class="coverage-legend__item"
                            ><span class="coverage-legend__dot coverage-legend__dot--hit" />已覆盖</span
                          >
                          <span class="coverage-legend__item"
                            ><span class="coverage-legend__dot coverage-legend__dot--miss" />未覆盖</span
                          >
                          <span class="coverage-legend__item"
                            ><span class="coverage-legend__dot coverage-legend__dot--unknown" />未探针</span
                          >
                          <span class="coverage-legend__item"
                            ><span class="coverage-legend__plus">+</span>新增行</span
                          >
                        </div>
                        <p class="coverage-legend-hint mb-0">提示：点击蓝色行号在本页打开 Code Diff</p>
                      </div>
                      <div class="coverage-hero__right">
                        <v-btn-toggle
                          v-model="coverageFilter"
                          mandatory
                          density="comfortable"
                          rounded="pill"
                          class="coverage-filter-toggle"
                        >
                          <v-btn value="all" size="small" class="text-none">全部</v-btn>
                          <v-btn value="miss" size="small" class="text-none">未覆盖</v-btn>
                          <v-btn value="hit" size="small" class="text-none">已覆盖</v-btn>
                        </v-btn-toggle>
                        <v-btn
                          v-if="detail.coverage_lines.length"
                          size="small"
                          variant="text"
                          class="text-none coverage-expand-all-btn"
                          :prepend-icon="coveragePanelsExpandAll ? 'mdi-unfold-less-horizontal' : 'mdi-unfold-more-horizontal'"
                          @click="toggleCoveragePanelsExpandAll"
                        >
                          {{ coveragePanelsExpandAll ? '全部收起' : '全部展开' }}
                        </v-btn>
                      </div>
                    </div>
                    <p
                      v-if="coverageKpi.pct == null && detail.coverage_lines.length"
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
                    <div v-else class="coverage-accordion-shell">
                      <div
                        v-if="!filteredCoverageGroups.length"
                        class="detail-hint-box detail-hint-box--compact coverage-filter-empty"
                        role="status"
                      >
                        <v-icon icon="mdi-filter-off-outline" size="22" color="#8e9299" class="detail-hint-box__icon" />
                        <p class="detail-hint-box__text mb-0">{{ coverageFilterEmptyText }}</p>
                      </div>
                      <v-expansion-panels
                        v-else
                        v-model="expandedCoverageFiles"
                        multiple
                        variant="accordion"
                        class="coverage-file-panels"
                      >
                        <v-expansion-panel
                          v-for="group in filteredCoverageGroups"
                          :key="group.file"
                          :value="group.file"
                          elevation="0"
                          class="coverage-file-panel"
                        >
                          <v-expansion-panel-title class="coverage-file-head text-none">
                            <span class="coverage-file-path mono text-truncate">
                              <span
                                v-if="splitCoverageFilePath(group.file).dir"
                                class="coverage-file-path__dir"
                              >
                                {{ splitCoverageFilePath(group.file).dir }}
                              </span>
                              <span class="coverage-file-path__name">
                                {{ splitCoverageFilePath(group.file).name }}
                              </span>
                            </span>
                            <div class="coverage-file-badges">
                              <span
                                class="coverage-file-stat mono"
                                :class="{ 'coverage-file-stat--low': group.pct < 80 }"
                              >
                                {{ group.pct }}%
                              </span>
                              <span v-if="group.miss > 0" class="coverage-file-badge coverage-file-badge--miss">
                                {{ group.miss }} 行未覆盖
                              </span>
                              <span
                                v-else-if="group.unknown > 0"
                                class="coverage-file-badge coverage-file-badge--probe"
                              >
                                {{ group.unknown }} 行待探针
                              </span>
                            </div>
                          </v-expansion-panel-title>
                          <v-expansion-panel-text class="coverage-file-body">
                            <div
                              v-for="(range, ri) in group.ranges"
                              :key="`${group.file}-${range.start}-${ri}`"
                              class="coverage-range-block"
                            >
                              <div
                                v-for="seg in range.lines"
                                :key="`${group.file}-L${seg.line}`"
                                class="coverage-probe-row"
                              >
                                <v-tooltip location="left" :text="coverageSegTooltip(seg)">
                                  <template #activator="{ props: tipProps }">
                                    <button
                                      v-bind="tipProps"
                                      type="button"
                                      class="coverage-line-no mono"
                                      @click="openCoverageCodeDiff(group.file, seg.line ?? range.start)"
                                    >
                                      :{{ seg.line }}
                                    </button>
                                  </template>
                                </v-tooltip>
                                <button
                                  type="button"
                                  class="coverage-probe-chip"
                                  :class="coverageLineDotClass(seg.covered)"
                                  :aria-label="`${seg.line} ${coverageLineStateLabel(seg.covered)}`"
                                  @click="openCoverageCodeDiff(group.file, seg.line ?? range.start)"
                                />
                                <span class="coverage-probe-state text-caption">
                                  {{ coverageLineStateLabel(seg.covered) }}
                                </span>
                              </div>
                            </div>
                          </v-expansion-panel-text>
                        </v-expansion-panel>
                      </v-expansion-panels>
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
          <div
            v-if="highRiskDetails?.matched_modules?.length || gateTriggerDetail"
            class="override-risk-panel"
            aria-label="高危触发范围"
          >
            <p class="override-risk-panel__title">
              {{ gateTriggerDetail?.summary || detail?.block_reason_label || '高危模块未评审' }}
            </p>
            <p
              v-if="highRiskDetails?.override_hint"
              class="text-caption text-medium-emphasis mb-2"
            >
              {{ highRiskDetails.override_hint }}
            </p>
            <ul v-if="highRiskDetails?.matched_impacts?.length" class="override-risk-list mb-2">
              <li
                v-for="(m, i) in highRiskDetails.matched_impacts.slice(0, 10)"
                :key="`bc-${i}`"
                class="override-risk-item mono"
              >
                {{ m.backend_api }} → {{ m.page_file }}
                <span class="override-risk-meta">{{ m.frontend_repo }}</span>
              </li>
            </ul>
            <ul v-if="highRiskDetails?.matched_modules?.length" class="override-risk-list mb-2">
              <li
                v-for="(m, i) in highRiskDetails.matched_modules.slice(0, 12)"
                :key="`hr-${i}`"
                class="override-risk-item mono"
              >
                <v-chip v-if="m.level" size="x-small" variant="flat" class="mr-1">{{ m.level }}</v-chip>
                <span v-if="m.file">{{ m.file }}</span>
                <span v-if="m.symbol" class="override-risk-meta">{{ m.symbol }}</span>
                <span class="override-risk-meta d-block">{{ m.reason }}</span>
              </li>
            </ul>
            <ul v-else-if="gateTriggerDetail?.high_risk_items?.apis?.length" class="override-risk-list mb-2">
              <li
                v-for="(api, i) in gateTriggerDetail.high_risk_items.apis.slice(0, 6)"
                :key="`api-${i}`"
                class="override-risk-item mono"
              >
                {{ api.method }} {{ api.path }}
                <span v-if="api.file" class="override-risk-meta">{{ api.file }}</span>
              </li>
            </ul>
            <ul v-else-if="gateTriggerDetail?.high_risk_items?.symbols?.length" class="override-risk-list">
              <li
                v-for="(sym, i) in gateTriggerDetail.high_risk_items.symbols.slice(0, 8)"
                :key="`sym-${i}`"
                class="override-risk-item mono"
              >
                {{ sym.qualified_name }}
                <span v-if="sym.file" class="override-risk-meta">{{ sym.file }}</span>
              </li>
            </ul>
          </div>
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
          <p class="text-caption text-medium-emphasis mt-2 mb-0">
            审批人：{{ sessionActor.username }}（{{ sessionRoleLabel || sessionActor.role }}）
          </p>
          <p v-if="overrideError" class="override-error mt-3 mb-0" role="alert">{{ overrideError }}</p>
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

    <GateTriggerDetailDrawer
      v-model="gateDetailDrawerOpen"
      :mode="gateDetailDrawerMode"
      :trigger-detail="gateTriggerDetail"
      :high-risk="highRiskDetails"
    />

    <CodeDiffDrawer
      v-if="selectedId && detail"
      v-model:open="coverageDiffOpen"
      :job-id="selectedId"
      :title="coverageDiffPick?.title"
      :file="coverageDiffPick?.file"
      :start-line="coverageDiffPick?.startLine"
      :end-line="coverageDiffPick?.endLine"
      node-type="changed"
      :repo="detail.repo"
      :head-sha="detail.commit"
    />
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
.regression-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: start;
  gap: 16px 24px;
  width: 100%;
}
.regression-hero__title {
  margin-bottom: 8px !important;
}
.regression-sub {
  max-width: 640px;
  color: rgba(255, 255, 255, 0.6);
  line-height: 1.6;
}
.regression-filters {
  justify-self: end;
  align-items: center;
  gap: 16px;
  flex-wrap: nowrap;
  max-width: 100%;
}
@media (max-width: 1100px) {
  .regression-hero {
    grid-template-columns: 1fr;
  }
  .regression-filters {
    justify-self: stretch;
    justify-content: flex-end;
    flex-wrap: wrap;
  }
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
  min-height: 40px !important;
  height: 40px;
  padding-inline: 18px !important;
  color: #fff !important;
  font-weight: 600;
  letter-spacing: 0.01em;
  box-shadow: 0 2px 12px rgba(138, 180, 248, 0.32);
}
.btn-trigger-regression:hover {
  box-shadow: 0 4px 18px rgba(138, 180, 248, 0.42);
}
.regression-filters :deep(.repo-autocomplete.filter-select-repo .v-field),
.regression-filters :deep(.filter-gate .v-field) {
  min-height: 40px;
  height: 40px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04) !important;
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
.detail-panel-top-progress {
  flex-shrink: 0;
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
.batch-list-wrap :deep(.md3-load-overlay-panel) {
  min-height: 280px;
  background: rgba(255, 255, 255, 0.02);
  border-color: rgba(255, 255, 255, 0.06);
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
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  border-radius: 10px;
  box-shadow: none;
  overflow: visible;
}
.detail-segment :deep(.v-btn) {
  min-width: 108px;
  letter-spacing: 0;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.58);
  background: transparent !important;
  box-shadow: none !important;
}
.detail-segment :deep(.v-btn--active) {
  color: #e8eaed !important;
  background: rgba(138, 180, 248, 0.14) !important;
  box-shadow: inset 0 -2px 0 #8ab4f8 !important;
}
.detail-tab-content {
  margin-top: 12px;
}
.detail-tab-content :deep(.v-window),
.detail-tab-content :deep(.v-window__container),
.detail-tab-content :deep(.v-window-item) {
  overflow: visible;
  box-shadow: none;
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
  border-radius: 8px !important;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.batch-chip--pass {
  background: rgba(52, 168, 83, 0.12) !important;
  color: #9ed9a8 !important;
  border: 1px solid rgba(129, 201, 149, 0.22);
}
.batch-chip--block {
  background: rgba(234, 67, 53, 0.12) !important;
  color: #e8a8a3 !important;
  border: 1px solid rgba(242, 139, 130, 0.22);
}
.batch-chip--pending {
  background: rgba(142, 146, 153, 0.12) !important;
  color: #a8adb5 !important;
  border: 1px solid rgba(142, 146, 153, 0.2);
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
  grid-template-columns: auto minmax(0, 1fr);
  margin-inline-start: auto;
  align-items: start;
}
.detail-gate-col {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
  min-width: 0;
  max-width: min(320px, 42vw);
}
.detail-gate-reason {
  margin: 0;
  font-size: 12px;
  line-height: 1.45;
  text-align: right;
  color: rgba(242, 139, 130, 0.92);
}
.detail-gate-reason--pending {
  color: rgba(255, 255, 255, 0.58);
}
.detail-alert-stack {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-top: 12px;
  margin-bottom: 16px;
}
.detail-tab-content--after-alerts {
  margin-top: 0 !important;
}
.detail-rbac-banner {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px 16px;
  margin-top: 0;
  padding: 12px 16px;
  border-radius: 12px;
  border: 1px solid rgba(245, 158, 11, 0.28);
  background: rgba(245, 158, 11, 0.1);
}
.detail-rbac-banner__body {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  flex: 1 1 220px;
  min-width: 0;
}
.detail-rbac-banner__icon {
  flex-shrink: 0;
  margin-top: 1px;
  color: #fbbf24;
  opacity: 0.92;
}
.detail-rbac-banner__text {
  font-size: 13px;
  line-height: 1.55;
  color: rgba(255, 255, 255, 0.72);
}
.detail-rbac-kw {
  font-weight: 600;
  color: #fde68a;
}
.detail-rbac-banner__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 10px 12px;
  flex-shrink: 0;
}
.detail-rbac-lock-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-height: 32px;
  padding: 8px 14px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.035);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.2;
  color: rgba(255, 255, 255, 0.36);
  cursor: not-allowed;
  user-select: none;
  white-space: nowrap;
  pointer-events: auto;
}
.detail-rbac-lock-btn__icon {
  color: rgba(255, 255, 255, 0.32);
  flex-shrink: 0;
}
.detail-rbac-share-btn {
  color: #8ab4f8 !important;
  opacity: 0.92;
}
.detail-gate-banner {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 12px;
  margin-top: 0;
  padding: 12px 16px;
  border-radius: 12px;
  border: 1px solid rgba(242, 139, 130, 0.22);
  background: rgba(234, 67, 53, 0.08);
}
.detail-gate-banner__summary {
  font-size: 13px;
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.78);
}
.detail-gate-count {
  font-size: 15px;
  font-weight: 700;
  color: #fbbf24;
  margin: 0 2px;
}
.detail-gate-banner__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px 12px;
  padding-top: 2px;
}
.detail-gate-banner__sep {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.32);
  user-select: none;
  padding: 0 2px;
}
.detail-gate-link {
  font-size: 12px;
  color: #8ab4f8;
  text-decoration: none;
  background: none;
  border: 0;
  padding: 2px 0;
  cursor: pointer;
}
.detail-gate-text-btn:hover,
.detail-gate-text-btn:focus-visible {
  text-decoration: underline;
  text-underline-offset: 3px;
}
.detail-gate-tip-pre {
  margin: 0;
  font-size: 12px;
  line-height: 1.45;
  white-space: pre-wrap;
  font-family: inherit;
}
.kpi-gate-detail-link {
  display: inline-block;
  margin-top: 6px;
  padding: 0;
  border: 0;
  background: none;
  color: #8ab4f8;
  text-decoration: none;
  cursor: pointer;
  font: inherit;
  text-align: left;
}
.kpi-gate-detail-link:hover {
  text-decoration: underline;
}
.override-risk-panel {
  margin-bottom: 16px;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid rgba(242, 139, 130, 0.22);
  background: rgba(234, 67, 53, 0.08);
}
.override-risk-panel__title {
  margin: 0 0 8px;
  font-size: 12px;
  line-height: 1.45;
  color: rgba(255, 255, 255, 0.82);
}
.override-risk-list {
  margin: 0;
  padding: 0;
  list-style: none;
}
.override-risk-item {
  font-size: 11px;
  line-height: 1.5;
  color: rgba(255, 255, 255, 0.78);
}
.override-risk-meta {
  margin-left: 6px;
  color: rgba(255, 255, 255, 0.45);
  font-size: 10px;
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
  background: rgba(253, 214, 99, 0.14) !important;
  color: #f0d78a !important;
  border: 1px solid rgba(253, 214, 99, 0.26);
}
.kpi-gate-status-chip {
  font-size: 13px !important;
  font-weight: 600;
  letter-spacing: 0.02em;
  padding-inline: 12px !important;
  min-height: 32px !important;
}
.kpi-gate-status-chip--pass {
  background: rgba(52, 168, 83, 0.14) !important;
  color: #9ed9a8 !important;
}
.kpi-gate-status-chip--block {
  background: rgba(234, 67, 53, 0.14) !important;
  color: #e8a8a3 !important;
}
.kpi-gate-status-chip--pending {
  background: rgba(142, 146, 153, 0.14) !important;
  color: #a8adb5 !important;
}
.kpi-gate-status-chip--override {
  background: rgba(253, 214, 99, 0.16) !important;
  color: #f0d78a !important;
}
.case-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.case-main .mono.text-body-2 {
  line-height: 1.48;
}
.case-main .text-caption {
  line-height: 1.5;
  margin-top: 2px;
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
.coverage-hero {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 20px 32px;
  margin-bottom: 16px;
  padding: 16px 24px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.07);
  background: rgba(255, 255, 255, 0.02);
}
.coverage-hero__left {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  flex: 1 1 280px;
}
.coverage-hero__metrics {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 12px 20px;
}
.coverage-hero__pct-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.coverage-hit-line {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.42);
  padding-bottom: 6px;
}
.coverage-hit-line__sep {
  margin-inline: 4px;
  opacity: 0.4;
}
.coverage-hero__right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  justify-content: center;
  gap: 16px;
  flex-shrink: 0;
}
.coverage-expand-all-btn {
  color: rgba(138, 180, 248, 0.95) !important;
  min-width: 0;
  padding-inline: 8px !important;
  font-size: 12px !important;
}
.coverage-legend-hint {
  margin-top: 8px;
  font-size: 11px;
  line-height: 1.45;
  color: rgba(255, 255, 255, 0.4);
  max-width: 480px;
}
.coverage-filter-toggle {
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(0, 0, 0, 0.22);
  padding: 4px;
  border-radius: 999px;
}
.coverage-filter-toggle :deep(.v-btn) {
  min-height: 32px;
  height: auto;
  padding: 4px 12px !important;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.58) !important;
  background: transparent !important;
  box-shadow: none !important;
  border-radius: 999px !important;
}
.coverage-filter-toggle :deep(.v-btn--active) {
  background: rgba(255, 255, 255, 0.14) !important;
  color: #f1f3f5 !important;
}
.coverage-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.72);
}
.coverage-legend--inline {
  margin-top: 0;
}
.coverage-legend__item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.coverage-legend__dot {
  width: 10px;
  height: 10px;
  border-radius: 3px;
}
.coverage-legend__dot--hit {
  background: #81c995;
}
.coverage-legend__dot--miss {
  background: #f28b82;
}
.coverage-legend__dot--unknown {
  background: #8e9299;
}
.coverage-legend__plus {
  font-weight: 700;
  color: rgba(255, 255, 255, 0.72);
}
.coverage-accordion-shell {
  max-height: min(56vh, 520px);
  overflow: auto;
  overscroll-behavior: contain;
  padding-right: 4px;
}
.coverage-filter-empty {
  margin-top: 4px;
}
.coverage-file-panels {
  background: transparent;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.coverage-file-panel {
  margin-bottom: 0;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  overflow: hidden;
  background: #1a1a1a;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.22);
}
.coverage-file-head {
  padding: 12px 16px !important;
  min-height: 48px !important;
  gap: 12px;
}
.coverage-file-head :deep(.v-expansion-panel-title__icon) {
  margin-inline-start: 8px;
  color: rgba(255, 255, 255, 0.45);
}
.coverage-file-path {
  flex: 1 1 auto;
  min-width: 0;
  font-size: 13px;
  line-height: 1.35;
}
.coverage-file-path__dir {
  color: rgba(255, 255, 255, 0.48);
}
.coverage-file-path__name {
  font-weight: 700;
  color: #e8eaed;
}
.coverage-file-badges {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-shrink: 0;
}
.coverage-file-stat {
  font-size: 15px;
  font-weight: 700;
  color: #fdd663;
}
.coverage-file-stat--low {
  color: #f28b82;
}
.coverage-file-badge {
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.35;
  white-space: nowrap;
}
.coverage-file-badge--miss {
  background: rgba(234, 67, 53, 0.16);
  color: #f0a8a3;
  border: 1px solid rgba(242, 139, 130, 0.22);
}
.coverage-file-badge--probe {
  background: rgba(253, 167, 75, 0.14);
  color: #f0b878;
  border: 1px solid rgba(253, 167, 75, 0.28);
}
.coverage-file-body :deep(.v-expansion-panel-text__wrapper) {
  padding: 8px 24px 16px !important;
}
.coverage-range-block + .coverage-range-block {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed rgba(255, 255, 255, 0.08);
}
.coverage-probe-row {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 32px;
  margin-bottom: 8px;
}
.coverage-probe-row:last-child {
  margin-bottom: 0;
}
.coverage-line-no {
  flex: 0 0 56px;
  width: 56px;
  padding: 4px 6px;
  margin: 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #8ab4f8;
  font-size: 13px;
  font-weight: 600;
  text-align: right;
  cursor: pointer;
  transition: background 0.15s ease;
}
.coverage-line-no:hover {
  background: rgba(138, 180, 248, 0.12);
}
.coverage-probe-chip {
  flex: 0 0 18px;
  width: 18px;
  height: 18px;
  padding: 0;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  transition: transform 0.12s ease, box-shadow 0.12s ease;
}
.coverage-probe-chip:hover {
  transform: scale(1.06);
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.2);
}
.coverage-probe-chip--hit {
  background: rgba(129, 201, 149, 0.95);
}
.coverage-probe-chip--miss {
  background: rgba(242, 139, 130, 0.95);
}
.coverage-probe-chip--unknown {
  background: rgba(95, 100, 110, 0.95);
  border: 1px solid rgba(255, 255, 255, 0.12);
}
.coverage-probe-state {
  color: rgba(255, 255, 255, 0.42);
  font-size: 11px;
}
.coverage-summary-label {
  color: rgba(255, 255, 255, 0.5);
  font-size: 12px;
  line-height: 1.3;
}
.coverage-summary-value {
  font-weight: 700;
  font-size: 2rem;
  line-height: 1.05;
  letter-spacing: -0.02em;
}
.coverage-summary-value--good {
  color: #9ed9a8;
}
.coverage-summary-value--warn {
  color: #fdd663;
}
.coverage-summary-value--bad {
  color: #f28b82;
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