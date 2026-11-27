<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { fetchDashboardOverview, resolveHotspotJob } from '@/api/client'
import { formatRelativeTime } from '@/utils/datetime'
import RepoAutocompleteFilter from '@/components/RepoAutocompleteFilter.vue'
import { gateVerdictListLabel, gateVerdictToken } from '@/utils/statusTokens'
import CodeDiffDrawer from '@/components/CodeDiffDrawer.vue'

const router = useRouter()
const openWebhookHelp = inject<() => void>('openWebhookHelp', () => {})
const openNewAnalysis = inject<() => void>('openNewAnalysis', () => {})

const days = ref<7 | 30 | 90>(7)
const refreshSpin = ref(false)
const repoFilter = ref<string | null>(null)

const loading = ref(false)
const loadError = ref(false)
const hotspotCodeBusy = ref(false)
const hotspotToast = ref('')
const hotspotToastOpen = ref(false)
const hotspotDrawerOpen = ref(false)
const hotspotDrawerPick = ref<{
  jobId: string
  file: string
  startLine: number
  endLine: number
  title: string
  repo?: string
} | null>(null)
const loadErrorDismissed = ref(false)
const loadErrorVisible = computed(() => loadError.value && !loadErrorDismissed.value)
const dashboard = ref<Awaited<ReturnType<typeof fetchDashboardOverview>> | null>(null)
const chartsPending = ref(false)

/** 首屏 / 硬刷新：尚无数据 */
const pageBooting = computed(() => loading.value && !dashboard.value)
/** 切换筛选或手动刷新：保留旧数据并叠加加载态 */
const pageRefreshing = computed(() => loading.value && !!dashboard.value)
const chartAreaBusy = computed(
  () => pageRefreshing.value || chartsPending.value,
)

const trendRef = ref<HTMLDivElement | null>(null)
const flowPanelEl = ref<HTMLElement | null>(null)
const interceptPanelEl = ref<HTMLElement | null>(null)
let trendChart: echarts.ECharts | null = null
let donutChart: echarts.ECharts | null = null

const gateBaseline = computed(() => dashboard.value?.kpi.gate_baseline ?? 80)

function flowGateAvatarClass(gate: string) {
  if (gate === 'PASS') return 'flow-status-avatar--pass'
  if (gate === 'BLOCK') return 'flow-status-avatar--block'
  return 'flow-status-avatar--pending'
}

function flowGateIcon(gate: string) {
  if (gate === 'PASS') return 'mdi-check'
  if (gate === 'BLOCK') return 'mdi-minus-circle'
  return 'mdi-timer-sand'
}

function flowGateChipIcon(gate: string) {
  if (gate === 'PASS') return 'mdi-check'
  if (gate === 'BLOCK') return 'mdi-minus-circle'
  return 'mdi-timer-sand'
}

function flowGateChipClass(gate: string) {
  const key = (gate || 'PENDING').toUpperCase()
  if (key === 'PASS') return 'gate-status-chip gate-status-chip--pass'
  if (key === 'BLOCK') return 'gate-status-chip gate-status-chip--block'
  if (key === 'OVERRIDDEN') return 'gate-status-chip gate-status-chip--override'
  return 'gate-status-chip gate-status-chip--pending'
}

function coverageBarColor(coverage: number | null) {
  if (coverage == null) return 'secondary'
  return coverage < gateBaseline.value ? 'error' : 'success'
}

/** 绿条仅表示覆盖率数值；BLOCK 时若并非「覆盖率不足」则不用成功色，避免「100% 像已通过」。 */
function flowCoverageBarColor(item: FlowRow) {
  const coverage = item.coverage
  if (item.gate === 'BLOCK') {
    if (item.block_reason === 'incremental_coverage_low' || item.block_reason === 'branch_coverage_low') {
      return 'error'
    }
    if (item.block_reason === 'analysis_failed' || coverage == null) {
      return 'secondary'
    }
    if (coverage != null && coverage >= gateBaseline.value) {
      return 'warning'
    }
    return coverageBarColor(coverage)
  }
  return coverageBarColor(coverage)
}

function flowCoveragePctLabel(item: FlowRow) {
  if (item.gate === 'BLOCK' && item.block_reason === 'analysis_failed') {
    return '—'
  }
  return item.coverage != null ? `${item.coverage}%` : '—'
}

function flowApiImpactHint(item: FlowRow) {
  if (item.changed_files > 0 && item.api_impact === 0) {
    return '已检出变更文件，但未链到对外 API（多为 AST 索引或路由解析不完整）'
  }
  return ''
}

const kpiCards = computed(() => {
  const k = dashboard.value?.kpi
  if (!k) return []
  const pending = k.pending_count ?? 0
  const delta = k.coverage_delta
  const trendPill =
    delta !== 0 ? `${delta > 0 ? '+' : ''}${delta}%` : undefined
  const trendTone = delta > 0 ? 'up' : delta < 0 ? 'down' : undefined
  const coverageSamples = k.coverage_sample_count ?? 0
  const coverageNoData = coverageSamples === 0
  const coverageTone = coverageNoData
    ? ('muted' as const)
    : k.avg_coverage > 0 && k.avg_coverage < k.gate_baseline
      ? ('warn' as const)
      : ('success' as const)
  const passTone =
    k.first_pass_rate >= 100 && k.pass_count > 0
      ? ('success' as const)
      : k.first_pass_rate > 0 && k.first_pass_rate < 60
        ? ('warn' as const)
        : ('info' as const)

  const toneStyle = (
    tone: 'success' | 'warn' | 'danger' | 'info' | 'muted',
  ): { accent: string; iconBg: string; iconColor: string; valueColor: string } => {
    if (tone === 'success')
      return {
        accent: '#81C995',
        iconBg: 'rgba(52, 168, 83, 0.15)',
        iconColor: '#81C995',
        valueColor: '#81C995',
      }
    if (tone === 'warn')
      return {
        accent: '#FDD663',
        iconBg: 'rgba(253, 214, 99, 0.15)',
        iconColor: '#FDD663',
        valueColor: '#FB923C',
      }
    if (tone === 'danger')
      return {
        accent: '#F28B82',
        iconBg: 'rgba(234, 67, 53, 0.15)',
        iconColor: '#F28B82',
        valueColor: '#F28B82',
      }
    if (tone === 'muted')
      return {
        accent: '#8E9299',
        iconBg: 'rgba(142, 146, 153, 0.15)',
        iconColor: '#8E9299',
        valueColor: 'rgba(255, 255, 255, 0.38)',
      }
    return {
      accent: '#8AB4F8',
      iconBg: 'rgba(138, 180, 248, 0.15)',
      iconColor: '#8AB4F8',
      valueColor: '#8AB4F8',
    }
  }

  return [
    {
      title: '平均增量代码覆盖率',
      value: coverageNoData ? '—' : `${k.avg_coverage}%`,
      trendPill: coverageNoData ? undefined : trendPill,
      trendTone,
      sub: coverageNoData ? '暂无覆盖率回传（非 0%）' : `门禁基线 ${k.gate_baseline}%`,
      icon: 'mdi-shield-check-outline',
      action: 'trend' as const,
      ...toneStyle(coverageTone),
    },
    {
      title: '质量门禁一次通过率',
      value: `${k.first_pass_rate}%`,
      trendPill: undefined,
      trendTone: undefined,
      sub: `通过 ${k.pass_count} 次 / 拦截 ${k.block_count} 次${pending ? ` / 待测 ${pending}` : ''}`,
      icon: 'mdi-check-decagram-outline',
      action: 'flows' as const,
      ...toneStyle(passTone),
    },
    {
      title: '累计高危变更拦截',
      value: `${k.high_risk_total} 次`,
      trendPill: undefined,
      trendTone: undefined,
      sub: '点击查看拦截原因分布',
      icon: 'mdi-shield-alert-outline',
      action: 'intercept' as const,
      ...toneStyle('danger'),
    },
    {
      title: '精准测试累计节省工时',
      value: `${k.saved_hours} h`,
      trendPill: undefined,
      trendTone: undefined,
      sub: `用例压缩率均值 ${k.case_compress_pct}%`,
      icon: 'mdi-lightning-bolt-outline',
      action: 'regression' as const,
      ...toneStyle('success'),
    },
  ]
})

type FlowRow = Awaited<ReturnType<typeof fetchDashboardOverview>>['recent_flows'][number]

const coverageDialog = ref(false)
const activeFlow = ref<FlowRow | null>(null)
const flowGateFilter = ref<'BLOCK' | 'PASS' | 'PENDING' | null>(null)
const interceptCardHover = ref(false)

function formatSourceSubline(item: FlowRow) {
  return `${item.commit} · ${formatRelativeTime(item.time)}`
}

const interceptTotal = computed(() => {
  const reasons = dashboard.value?.intercept_reasons ?? []
  return reasons.reduce((sum, r) => sum + r.value, 0)
})

const donutIsEmpty = computed(() => {
  if (!dashboard.value) return true
  const blocked = dashboard.value.kpi.block_count ?? 0
  return blocked === 0 && interceptTotal.value === 0
})

const DONUT_COLORS = ['rgba(234, 139, 130, 0.78)', 'rgba(251, 191, 36, 0.7)', 'rgba(253, 214, 99, 0.62)'] as const

const CHART = {
  axis: 'rgba(255, 255, 255, 0.62)',
  axisLines: 'rgba(255, 255, 255, 0.68)',
  axisPct: 'rgba(138, 180, 248, 0.92)',
  axisDim: '#8E9299',
  grid: 'rgba(255, 255, 255, 0.045)',
  line: '#8AB4F8',
  lineNode: '#1A1D21',
  lineNodeBorder: '#8AB4F8',
  bar: '#252930',
  areaTop: 'rgba(138, 180, 248, 0.12)',
  baseline: '#F28B82',
  centerValue: '#F1F3F5',
  centerLabel: '#8E9299',
  ringGap: '#1A1D21',
  tooltipBg: '#24282E',
  tooltipText: '#F1F3F5',
  donutPlaceholder: '#2C3036',
} as const

const donutLegendItems = computed(() => {
  const reasons = dashboard.value?.intercept_reasons ?? []
  if (!reasons.length) return []
  const items = reasons.map((r) => ({ ...r, name: shortenReasonLabel(r.name) }))
  const total = items.reduce((s, r) => s + r.value, 0)
  const denom = total || 1
  return items.map((r, i) => ({
    name: r.name,
    value: r.value,
    pct: total ? Math.round((r.value / denom) * 100) : 0,
    color: DONUT_COLORS[i % DONUT_COLORS.length],
  }))
})

const interceptBigNumber = computed(() => {
  const items = donutLegendItems.value
  if (!items.length || interceptTotal.value === 0) return null
  if (items.length !== 1) return null
  return {
    total: interceptTotal.value,
    reason: items[0].name,
    pct: items[0].pct,
  }
})

const interceptMultiReason = computed(() => {
  const items = donutLegendItems.value
  if (items.length <= 1) return null
  return items
})

const displayFlows = computed(() => {
  const flows = dashboard.value?.recent_flows ?? []
  if (!flowGateFilter.value) return flows
  return flows.filter((f) => f.gate === flowGateFilter.value)
})

function rowBlockHighlight(item: FlowRow) {
  return interceptCardHover.value && item.gate === 'BLOCK'
}

function flowBlockReasonText(item: FlowRow) {
  if (item.gate !== 'BLOCK') return ''
  const label = item.block_reason_label
    ? shortenReasonLabel(item.block_reason_label)
    : item.block_reason || ''
  return label
}

function flowGateTooltip(item: FlowRow) {
  if (item.gate === 'BLOCK') {
    const summary = item.trigger_detail_summary
    if (summary) return summary
    const label = flowBlockReasonText(item) || '未达质量门禁要求'
    return `因「${label}」被拦截`
  }
  if (item.gate === 'OVERRIDDEN') return '已人工特批放行（审计记录见精准回归详情）'
  if (item.gate === 'PENDING') return '等待 CI 回传覆盖率后，系统将自动裁决门禁'
  if (item.gate === 'PASS') return '已通过质量门禁'
  return ''
}

function openBlockFlows() {
  flowGateFilter.value = 'BLOCK'
  scrollToRef(flowPanelEl.value, 'start')
}

function scrollToQualityFlows() {
  scrollToRef(flowPanelEl.value, 'start')
}

const codeHotspotRows = computed(() => dashboard.value?.code_hotspots ?? [])

function splitHotspotPath(path: string) {
  const norm = path.replace(/\\/g, '/')
  const idx = norm.lastIndexOf('/')
  if (idx <= 0) return { dir: '', name: norm }
  return { dir: norm.slice(0, idx + 1), name: norm.slice(idx + 1) }
}

function hotspotRiskTone(score: number): 'high' | 'mid' | 'low' {
  if (score >= 8) return 'high'
  if (score >= 6) return 'mid'
  return 'low'
}

function hotspotRepoLabel(repo?: string | null) {
  if (!repo) return '—'
  const slash = repo.lastIndexOf('/')
  return slash >= 0 ? repo.slice(slash + 1) : repo
}

function hotspotFileIconClass(path: string) {
  const { name } = splitHotspotPath(path)
  return name.toLowerCase().endsWith('.py')
    ? 'hotspot-path__icon hotspot-path__icon--py'
    : 'hotspot-path__icon'
}

type HotspotRow = NonNullable<
  Awaited<ReturnType<typeof fetchDashboardOverview>>['code_hotspots']
>[number]

async function resolveHotspotJobId(row: HotspotRow) {
  if (row.latest_job_id) {
    return {
      job_id: row.latest_job_id,
      start_line: row.start_line,
      end_line: row.end_line,
      path: row.path,
    }
  }
  try {
    return await resolveHotspotJob(row.path, row.repo, 30)
  } catch {
    return await resolveHotspotJob(row.path, undefined, 30)
  }
}

async function openHotspotCode(row: HotspotRow) {
  if (hotspotCodeBusy.value) return
  hotspotCodeBusy.value = true
  hotspotToastOpen.value = false
  try {
    const resolved = await resolveHotspotJobId(row)
    const file = resolved.path ?? row.path
    const startRaw = resolved.start_line ?? row.start_line ?? 1
    const endRaw = resolved.end_line ?? row.end_line ?? startRaw
    const startLine = startRaw > 0 ? Math.floor(startRaw) : 1
    const endLine = Math.max(startLine, endRaw > 0 ? Math.floor(endRaw) : startLine)
    hotspotDrawerPick.value = {
      jobId: resolved.job_id,
      file,
      startLine,
      endLine,
      title: splitHotspotPath(file).name,
      repo: row.repo ?? undefined,
    }
    hotspotDrawerOpen.value = true
  } catch {
    hotspotToast.value =
      '未找到包含该文件的分析任务。请重启 API 后刷新页面，或到变更影响中打开对应任务查看代码'
    hotspotToastOpen.value = true
  } finally {
    hotspotCodeBusy.value = false
  }
}

function clearFlowGateFilter() {
  flowGateFilter.value = null
}

function scrollToRef(target: HTMLElement | { $el?: HTMLElement } | null, block: ScrollLogicalPosition = 'center') {
  const node =
    target && typeof target === 'object' && '$el' in target
      ? target.$el
      : (target as HTMLElement | null)
  node?.scrollIntoView({ behavior: 'smooth', block })
}

function onKpiNavigate(action?: 'trend' | 'flows' | 'intercept' | 'regression') {
  if (!action) return
  if (action === 'regression') {
    router.push('/regression')
    return
  }
  if (action === 'trend') {
    scrollToRef(trendRef.value, 'center')
    return
  }
  if (action === 'intercept') {
    scrollToRef(interceptPanelEl.value, 'center')
    return
  }
  scrollToRef(flowPanelEl.value, 'start')
}

function flowGateChipLabel(gate: string) {
  if (gate === 'PENDING') return '待处理'
  return gateVerdictListLabel(gate)
}

function flowGateChipTitle(gate: string) {
  return gateVerdictToken(gate).hint
}

function resizeCharts() {
  requestAnimationFrame(() => {
    trendChart?.resize()
    donutChart?.resize()
  })
}

function dismissLoadError() {
  loadErrorDismissed.value = true
}

async function load() {
  loading.value = true
  loadError.value = false
  loadErrorDismissed.value = false
  chartsPending.value = false
  try {
    dashboard.value = await fetchDashboardOverview(days.value, repoFilter.value || undefined)
    chartsPending.value = true
    await nextTick()
    renderCharts()
    resizeCharts()
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
    await nextTick()
    chartsPending.value = false
    resizeCharts()
  }
}

const reasonShortLabels: Record<string, string> = {
  '增量行覆盖率 < 80%': '增量覆盖率不足',
  '核心影响面 API 回归失败': '接口回归失败',
  '高危核心模块未 Code Review': '高危模块未评审',
}

function shortenReasonLabel(name: string) {
  return reasonShortLabels[name] ?? name
}

function trendHasActivity(trend: { changed_lines: number[]; coverage: (number | null)[] }) {
  return (
    trend.changed_lines.some((n) => n > 0) ||
    trend.coverage.some((n) => n != null)
  )
}

const trendShowEmptyOverlay = computed(() => {
  const trend = dashboard.value?.trend
  if (!dashboard.value || !trend) return false
  if (!trend.labels?.length) return true
  return !trendHasActivity(trend)
})

const trendSparseCaption = computed(() => {
  const trend = dashboard.value?.trend
  if (!trend || trendShowEmptyOverlay.value) return ''
  const active = trend.labels.reduce((n, _, i) => {
    const lines = trend.changed_lines[i] ?? 0
    const cov = trend.coverage[i]
    return lines > 0 || cov != null ? n + 1 : n
  }, 0)
  const quiet = trend.labels.length - active
  if (quiet > 0 && active > 0) return `过去 ${quiet} 天无代码变更 · 已聚焦有数据时段`
  return ''
})

const interceptBlockTotal = computed(() => {
  const rows = interceptMultiReason.value
  if (!rows?.length) return 0
  return rows.reduce((sum, r) => sum + r.value, 0)
})

function compactTrendIfSparse(trend: {
  labels: string[]
  changed_lines: number[]
  coverage: (number | null)[]
  threshold: number
}) {
  const activeIdx = trend.labels
    .map((_, i) => i)
    .filter((i) => (trend.changed_lines[i] ?? 0) > 0 || trend.coverage[i] != null)
  if (activeIdx.length === 0 || activeIdx.length === trend.labels.length) {
    return { ...trend, wasCompacted: false }
  }
  return {
    labels: activeIdx.map((i) => trend.labels[i]!),
    changed_lines: activeIdx.map((i) => trend.changed_lines[i] ?? 0),
    coverage: activeIdx.map((i) => trend.coverage[i] ?? null),
    threshold: trend.threshold,
    wasCompacted: true,
  }
}

function trendFocusPercent(
  labels: string[],
  changed_lines: number[],
  coverage: (number | null)[],
): { start: number; end: number } | null {
  const n = labels.length
  if (n <= 4) return null
  let first = -1
  let last = -1
  for (let i = 0; i < n; i += 1) {
    if ((changed_lines[i] ?? 0) > 0 || coverage[i] != null) {
      first = i
      break
    }
  }
  for (let i = n - 1; i >= 0; i -= 1) {
    if ((changed_lines[i] ?? 0) > 0 || coverage[i] != null) {
      last = i
      break
    }
  }
  if (first < 0 || last < 0 || last - first >= n - 2) return null
  const padFirst = Math.max(0, first - 1)
  const padLast = Math.min(n - 1, last + 1)
  if (n <= 1) return { start: 0, end: 100 }
  return {
    start: (padFirst / (n - 1)) * 100,
    end: (padLast / (n - 1)) * 100,
  }
}

const trendEmptyCta = computed(() => {
  if (!trendShowEmptyOverlay.value) return null
  const action = dashboard.value?.home?.suggested_action ?? 'add_repo'
  const map = {
    add_repo: {
      label: '去接入仓库',
      sub: '配置 Git 地址并完成 AST 索引后，趋势将自动更新',
      handler: () => router.push('/repositories'),
    },
    index_repo: {
      label: '去构建 AST 索引',
      sub: '在仓库管理中执行「重新索引」',
      handler: () => router.push('/repositories'),
    },
    run_analysis: {
      label: '触发首次分析',
      sub: '对比 HEAD 变更，生成门禁与趋势数据',
      handler: () => openNewAnalysis(),
    },
    ok: {
      label: '新建分析',
      sub: '本时间范围内暂无任务，可手动触发一次分析',
      handler: () => openNewAnalysis(),
    },
  } as const
  return map[action] ?? map.add_repo
})

function renderCharts() {
  if (!dashboard.value) return
  const trendRaw = dashboard.value.trend
  const trend = compactTrendIfSparse(trendRaw)
  const threshold = trend.threshold

  const trendActive = trendHasActivity(trend)
  const peakLines = Math.max(...trend.changed_lines, 1)
  const linesYMax = peakLines <= 500 ? 500 : Math.ceil(peakLines / 200) * 200
  const hasCoverageSeries = trend.coverage.some((c) => c != null)
  const coverageSeriesData = trend.coverage.map((c) => (c == null ? null : c))
  const focusZoom = trend.wasCompacted
    ? null
    : trendFocusPercent(trend.labels, trend.changed_lines, trend.coverage)
  const splitLine = { show: true, lineStyle: { type: 'dashed' as const, color: CHART.grid } }
  const trendTooltip = {
    trigger: 'axis' as const,
    confine: true,
    backgroundColor: 'rgba(42, 42, 42, 0.96)',
    borderColor: 'rgba(255, 255, 255, 0.1)',
    borderWidth: 1,
    padding: [10, 12] as [number, number],
    extraCssText: 'border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.5);',
    textStyle: { color: CHART.tooltipText, fontSize: 12 },
    axisPointer: {
      type: 'line' as const,
      lineStyle: { color: 'rgba(138, 180, 248, 0.45)', width: 1, type: 'dashed' as const },
    },
    position(
      point: number[],
      _params: unknown,
      _dom: HTMLElement,
      _rect: unknown,
      size: { contentSize: number[]; viewSize: number[] },
    ) {
      const [x, y] = point
      const boxW = size.contentSize[0]
      const viewW = size.viewSize[0]
      let left = x + 14
      if (left + boxW > viewW - 12) left = x - boxW - 14
      const top = Math.max(8, y - size.contentSize[1] / 2)
      return [left, top]
    },
    formatter(params: unknown) {
      const rows = (Array.isArray(params) ? params : [params]) as Array<{
        axisValue?: string
        seriesName?: string
        value?: number | string | null
        color?: string
      }>
      const title = rows[0]?.axisValue ?? ''
      let html = `<div style="font-weight:700;color:#f1f3f5;margin-bottom:8px;font-size:13px;">${title}</div>`
      for (const p of rows) {
        const dot = p.color ?? CHART.line
        const isCov = (p.seriesName ?? '').includes('覆盖率')
        const raw = p.value
        const val =
          raw === '-' || raw == null ? '—' : isCov ? `${raw}%` : String(raw)
        html += `<div style="display:flex;align-items:center;justify-content:space-between;gap:20px;min-width:196px;margin:5px 0;line-height:1.4;">
              <span style="color:rgba(255,255,255,0.78);display:flex;align-items:center;gap:6px;">
                <i style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${dot};flex-shrink:0;"></i>
                ${p.seriesName ?? ''}
              </span>
              <span style="font-weight:700;color:#fff;text-align:right;min-width:3.5em;">${val}</span>
            </div>`
      }
      return html
    },
  }

  if (trendRef.value) {
    if (!trendActive) {
      trendChart?.dispose()
      trendChart = null
    } else {
      trendChart?.dispose()
      trendChart = echarts.init(trendRef.value)
      const axisCommon = {
        type: 'category' as const,
        data: trend.labels,
        axisLine: { lineStyle: { color: CHART.grid } },
        axisTick: { lineStyle: { color: CHART.grid } },
      }
      const dataZoom = focusZoom
        ? [
            {
              type: 'inside' as const,
              xAxisIndex: [0, 1],
              start: focusZoom.start,
              end: focusZoom.end,
              zoomOnMouseWheel: false,
              moveOnMouseMove: false,
            },
          ]
        : []

      trendChart.setOption(
        hasCoverageSeries
          ? {
              color: [CHART.bar, CHART.line],
              axisPointer: { link: [{ xAxisIndex: [0, 1] }] },
              grid: [
                { left: 8, right: 16, top: 28, height: '34%', containLabel: true },
                { left: 8, right: 8, top: '52%', height: '38%', containLabel: true },
              ],
              tooltip: trendTooltip,
              legend: { show: false },
              dataZoom,
              xAxis: [
                { ...axisCommon, gridIndex: 0, axisLabel: { show: false } },
                { ...axisCommon, gridIndex: 1, axisLabel: { color: CHART.axis } },
              ],
              yAxis: [
                {
                  type: 'value',
                  gridIndex: 0,
                  name: '行数',
                  min: 0,
                  max: linesYMax,
                  nameTextStyle: { color: CHART.axisLines, fontSize: 11 },
                  axisLabel: { color: CHART.axisLines, fontSize: 11 },
                  splitLine,
                },
                {
                  type: 'value',
                  gridIndex: 1,
                  name: '%',
                  min: 50,
                  max: 100,
                  splitNumber: 4,
                  nameTextStyle: { color: CHART.axisPct, fontSize: 11 },
                  axisLabel: {
                    color: CHART.axisPct,
                    fontSize: 11,
                    formatter: (v: number) => `${v}%`,
                  },
                  splitLine,
                },
              ],
              series: [
                {
                  name: '变更行数',
                  type: 'bar',
                  xAxisIndex: 0,
                  yAxisIndex: 0,
                  data: trend.changed_lines,
                  itemStyle: { color: trendActive ? 'rgba(255, 255, 255, 0.24)' : 'rgba(37, 41, 48, 0.45)' },
                  barMaxWidth: 32,
                  label: { show: false },
                  emphasis: { itemStyle: { color: 'rgba(255, 255, 255, 0.34)' } },
                },
                {
                  name: '增量覆盖率',
                  type: 'line',
                  xAxisIndex: 1,
                  yAxisIndex: 1,
                  connectNulls: false,
                  smooth: false,
                  showSymbol: false,
                  symbol: 'circle',
                  symbolSize: 7,
                  lineStyle: { width: 2.5, color: trendActive ? CHART.line : 'rgba(138, 180, 248, 0.35)' },
                  z: 3,
                  data: coverageSeriesData,
                  emphasis: {
                    scale: true,
                    focus: 'series',
                    showSymbol: true,
                    symbolSize: 9,
                    itemStyle: {
                      color: CHART.lineNode,
                      borderColor: CHART.lineNodeBorder,
                      borderWidth: 2,
                    },
                  },
                  itemStyle: {
                    color: CHART.lineNode,
                    borderColor: CHART.lineNodeBorder,
                    borderWidth: 2,
                  },
                  markLine: {
                    silent: true,
                    symbol: 'none',
                    lineStyle: { color: '#fb923c', type: 'dashed', width: 1.5 },
                    label: { show: false },
                    data: [{ yAxis: threshold, name: `基线 ${threshold}%` }],
                  },
                },
              ],
            }
          : {
              color: [CHART.bar],
              grid: { left: 8, right: 16, top: 32, bottom: 28, containLabel: true },
              tooltip: trendTooltip,
              legend: { show: false },
              dataZoom,
              xAxis: { ...axisCommon, axisLabel: { color: CHART.axis } },
              yAxis: {
                type: 'value',
                name: '行数',
                min: 0,
                max: linesYMax,
                nameTextStyle: { color: CHART.axisLines, fontSize: 11 },
                axisLabel: { color: CHART.axisLines, fontSize: 11 },
                splitLine,
              },
              series: [
                {
                  name: '变更行数',
                  type: 'bar',
                  data: trend.changed_lines,
                  itemStyle: { color: trendActive ? 'rgba(255, 255, 255, 0.24)' : 'rgba(37, 41, 48, 0.45)' },
                  barMaxWidth: 32,
                  label: { show: false },
                },
              ],
            },
      )
    }
  }

  donutChart?.dispose()
  donutChart = null
}

function onResize() {
  resizeCharts()
}

function openCallChain(item: FlowRow) {
  if (item.job_id) router.push(`/jobs/${item.job_id}`)
}

function openCoverage(item: FlowRow) {
  activeFlow.value = item
  coverageDialog.value = true
}

function filterByRepo(fullName: string) {
  repoFilter.value = fullName
}

onMounted(async () => {
  await load()
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  trendChart?.dispose()
  donutChart?.dispose()
})

async function onManualRefresh() {
  refreshSpin.value = true
  await load()
  window.setTimeout(() => {
    refreshSpin.value = false
  }, 650)
}

watch([days, repoFilter], load)
</script>

<template>
  <div class="dashboard-page">
    <div class="dashboard-hero d-flex flex-wrap align-start justify-space-between gap-4">
      <div>
        <h2 class="text-h5 text-md-h4 font-weight-bold dashboard-head mb-2">质量驾驶舱</h2>
        <p class="text-body-2 dashboard-hero-sub mb-0">
          全链路代码变更风险监控与 CI/CD 质量门禁拦截大盘
        </p>
      </div>
      <div class="dashboard-filters dashboard-toolbar d-flex flex-wrap align-center">
        <RepoAutocompleteFilter
          v-model="repoFilter"
          field-class="filter-select-float"
          :gate-stats="dashboard?.repo_gate_stats ?? []"
        />
        <div class="filter-range-group d-flex align-center flex-shrink-0">
          <v-btn-toggle v-model="days" class="filter-range m3-segmented" mandatory rounded="pill" density="compact">
            <v-btn :value="7" class="filter-range-btn" variant="text">近 7 天</v-btn>
            <v-btn :value="30" class="filter-range-btn" variant="text">近 30 天</v-btn>
            <v-btn :value="90" class="filter-range-btn" variant="text">近 90 天</v-btn>
          </v-btn-toggle>
          <v-btn
            class="filter-refresh filter-refresh-md"
            variant="text"
            icon
            rounded="lg"
            :loading="loading"
            aria-label="刷新大盘数据"
            title="刷新"
            @click="onManualRefresh"
          >
            <v-icon icon="mdi-refresh" :class="{ 'spin-once': refreshSpin && !loading }" />
          </v-btn>
        </div>
      </div>
    </div>

    <v-progress-linear
      v-if="loading"
      class="dashboard-load-bar"
      indeterminate
      color="primary"
      height="3"
      rounded
      aria-hidden="true"
    />

    <div v-if="loadErrorVisible" class="dashboard-load-error" role="alert">
      <span class="mdi mdi-alert-circle-outline dashboard-load-error__icon" aria-hidden="true" />
      <p class="dashboard-load-error__text">
        无法加载驾驶舱数据。请确认已运行
        <code class="dashboard-load-error__code mono">run_api.ps1</code>，且前端代理能访问
        <code class="dashboard-load-error__code mono">/api/v1</code>。
      </p>
      <div class="dashboard-load-error__actions">
        <button
          type="button"
          class="dashboard-load-error__retry"
          :disabled="loading"
          @click="onManualRefresh"
        >
          重新加载
        </button>
        <button
          type="button"
          class="dashboard-load-error__close"
          aria-label="关闭提示"
          @click="dismissLoadError"
        >
          <span class="mdi mdi-close" aria-hidden="true" />
        </button>
      </div>
    </div>

    <div class="load-section load-section--kpi" :aria-busy="loading">
      <v-overlay
        :model-value="pageRefreshing"
        contained
        persistent
        scrim="rgba(26, 29, 33, 0.52)"
        class="m3-load-overlay align-center justify-center"
      >
        <v-progress-circular indeterminate color="primary" size="36" width="3" aria-label="正在刷新" />
      </v-overlay>
      <v-row class="dashboard-grid dashboard-stack-gap kpi-row">
        <template v-if="pageBooting">
          <v-col v-for="n in 4" :key="`kpi-sk-${n}`" cols="12" sm="6" lg="3">
            <v-skeleton-loader type="osseous" class="kpi-skeleton m3-skeleton-tonal" boilerplate />
          </v-col>
        </template>
        <v-col v-for="card in kpiCards" v-else :key="card.title" cols="12" sm="6" lg="3">
          <v-card
            class="h-100 kpi-card kpi-card--nav m3-surface-card m3-elevated"
            rounded="xl"
            :border="false"
            tabindex="0"
            role="button"
            @click="onKpiNavigate(card.action)"
            @keydown.enter="onKpiNavigate(card.action)"
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
                <span
                  v-if="card.trendPill"
                  class="kpi-trend-badge mono"
                  :class="
                    card.trendTone === 'down' ? 'kpi-trend-badge--down' : 'kpi-trend-badge--up'
                  "
                >
                  {{ card.trendPill }}
                </span>
              </div>
              <p class="text-caption kpi-footnote mt-3 mb-0">{{ card.sub }}</p>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>
    </div>

    <v-row class="dashboard-grid dashboard-stack-gap chart-row" align="stretch">
      <v-col cols="12" lg="8" class="chart-col-trend">
        <v-card
          class="h-100 chart-card-equal chart-panel-card m3-surface-card m3-elevated"
          rounded="xl"
          :border="false"
        >
          <v-card-title class="chart-card-title chart-card-title--split">
            <span class="text-subtitle-1 font-weight-medium chart-card-heading">增量代码覆盖率 vs 门禁通过趋势</span>
            <div class="chart-card-title__trailing">
              <span v-if="trendSparseCaption" class="trend-sparse-badge" role="status">
                <span class="mdi mdi-information-outline trend-sparse-badge__icon" aria-hidden="true" />
                {{ trendSparseCaption }}
              </span>
              <div class="trend-legend" aria-hidden="true">
                <span class="trend-legend-item">
                  <span class="trend-legend-swatch trend-legend-swatch--bar" />
                  变更行数
                </span>
                <span class="trend-legend-item">
                  <span class="trend-legend-swatch trend-legend-swatch--line" />
                  增量覆盖率
                </span>
                <span v-if="!trendShowEmptyOverlay" class="trend-legend-item">
                  <span class="trend-legend-swatch trend-legend-swatch--baseline" />
                  基线 {{ gateBaseline }}%
                </span>
              </div>
            </div>
          </v-card-title>
          <v-card-text class="chart-card-body chart-card-body--load">
            <v-skeleton-loader
              v-if="pageBooting"
              type="image"
              height="290"
              class="m3-skeleton-tonal chart-skeleton"
            />
            <div
              v-else
              class="chart-box-wrap load-section"
              :class="{ 'chart-box-wrap--empty': trendShowEmptyOverlay }"
            >
              <v-overlay
                :model-value="chartAreaBusy"
                contained
                persistent
                scrim="rgba(26, 29, 33, 0.48)"
                class="m3-load-overlay align-center justify-center"
              >
                <v-progress-circular indeterminate color="primary" size="36" width="3" aria-label="图表加载中" />
              </v-overlay>
              <div v-show="!trendShowEmptyOverlay" ref="trendRef" class="chart-box" />
              <div
                v-if="trendShowEmptyOverlay && trendEmptyCta"
                class="empty-module chart-empty-state"
                aria-live="polite"
              >
                <div class="empty-module__block">
                  <div class="empty-module__icon" aria-hidden="true">
                    <v-icon icon="mdi-chart-timeline-variant" size="24" />
                  </div>
                  <div class="empty-module__text">
                    <p class="empty-module__title">暂无近期趋势数据</p>
                    <p class="empty-module__desc">请等待代码提交后自动更新，或通过下方操作生成趋势数据。</p>
                  </div>
                </div>
                <div class="empty-module__actions empty-module__actions--single">
                  <v-btn
                    color="primary"
                    variant="flat"
                    rounded="pill"
                    size="small"
                    class="text-none empty-module__cta"
                    prepend-icon="mdi-plus"
                    @click="trendEmptyCta.handler()"
                  >
                    {{ trendEmptyCta.label }}
                  </v-btn>
                </div>
              </div>
            </div>
          </v-card-text>
        </v-card>
      </v-col>
      <v-col cols="12" lg="4" class="chart-col-donut">
        <v-card
          ref="interceptPanelEl"
          class="h-100 chart-card-equal chart-panel-card m3-surface-card m3-elevated chart-card-donut"
          rounded="xl"
          :border="false"
        >
          <v-card-title class="text-subtitle-1 font-weight-medium chart-card-title">门禁拦截原因分布</v-card-title>
          <v-card-text class="chart-card-body donut-card-body pt-0 chart-card-body--load">
            <v-skeleton-loader
              v-if="pageBooting"
              type="image"
              height="220"
              class="m3-skeleton-tonal chart-skeleton"
            />
            <div
              v-else
              class="donut-layout donut-layout--stacked load-section"
              :class="{ 'donut-layout--compact': donutIsEmpty }"
            >
              <v-overlay
                :model-value="chartAreaBusy"
                contained
                persistent
                scrim="rgba(26, 29, 33, 0.48)"
                class="m3-load-overlay align-center justify-center"
              >
                <v-progress-circular indeterminate color="primary" size="36" width="3" aria-label="图表加载中" />
              </v-overlay>
              <template v-if="donutIsEmpty">
                <div class="donut-empty-cluster">
                  <div class="donut-empty-positive">
                    <v-avatar size="68" rounded="circle" class="donut-empty-avatar">
                      <v-icon icon="mdi-shield-check" size="34" color="#81C995" />
                    </v-avatar>
                    <div class="donut-empty-title">暂无拦截</div>
                    <p class="text-caption text-medium-emphasis donut-empty-sub">
                      当前时间范围内无 BLOCK 门禁记录；待处理任务不计入拦截分布。
                    </p>
                  </div>
                </div>
              </template>
              <template v-else-if="interceptBigNumber">
                <button
                  type="button"
                  class="intercept-hero intercept-hero--interactive"
                  role="status"
                  @click="openBlockFlows"
                  @mouseenter="interceptCardHover = true"
                  @mouseleave="interceptCardHover = false"
                >
                  <span class="intercept-hero-detail text-none">
                    查看明细
                    <v-icon icon="mdi-chevron-right" size="16" />
                  </span>
                  <v-avatar size="60" rounded="lg" class="intercept-hero-icon">
                    <v-icon icon="mdi-shield-alert" size="30" color="#EF4444" />
                  </v-avatar>
                  <h3 class="intercept-hero-title">{{ interceptBigNumber.reason }}</h3>
                  <p class="intercept-hero-metric-line">
                    <span class="intercept-hero-num">{{ interceptBigNumber.total }}</span>
                    次拦截
                  </p>
                  <p class="intercept-hero-share">
                    占全部拦截原因的 {{ interceptBigNumber.pct }}%
                  </p>
                </button>
              </template>
              <template v-else-if="interceptMultiReason">
                <div class="intercept-bar-panel">
                  <div class="intercept-bar-list" role="list">
                    <div
                      v-for="row in interceptMultiReason"
                      :key="row.name"
                      class="intercept-bar-row"
                      role="listitem"
                    >
                      <div class="intercept-bar-head">
                        <span class="intercept-bar-name">{{ row.name }}</span>
                        <span class="intercept-bar-stat mono">
                          <span class="intercept-bar-count">{{ row.value }}</span>
                          <span class="intercept-bar-count-unit">次</span>
                          <span class="intercept-bar-pct" :style="{ color: row.color }">· {{ row.pct }}%</span>
                        </span>
                      </div>
                      <div class="intercept-bar-track" aria-hidden="true">
                        <div
                          class="intercept-bar-fill"
                          :style="{ width: `${row.pct}%`, backgroundColor: row.color }"
                        />
                      </div>
                    </div>
                  </div>
                  <div class="intercept-bar-footer">
                    <p v-if="interceptBlockTotal > 0" class="intercept-bar-summary">
                      合计拦截 {{ interceptBlockTotal }} 次
                    </p>
                    <button type="button" class="intercept-bar-cta-ghost" @click="openBlockFlows">
                      查看已拦截记录
                      <span class="mdi mdi-chevron-right" aria-hidden="true" />
                    </button>
                  </div>
                </div>
              </template>
            </div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-row v-if="codeHotspotRows.length > 0" class="dashboard-grid dashboard-stack-gap">
      <v-col cols="12">
        <v-card class="hotspot-panel" rounded="lg" :border="false">
          <v-card-title class="hotspot-panel__head">
            <div class="hotspot-panel__title">
              <v-icon icon="mdi-fire" class="hotspot-panel__title-icon" size="20" aria-hidden="true" />
              <span class="hotspot-panel__title-text">高风险代码热点（近 30 天 Top 5）</span>
            </div>
            <v-btn
              variant="text"
              size="small"
              color="primary"
              class="text-none hotspot-panel__cta"
              append-icon="mdi-chevron-right"
              @click="scrollToQualityFlows"
            >
              查看全部记录
            </v-btn>
          </v-card-title>
          <v-card-text class="hotspot-panel__body">
            <v-table density="compact" class="hotspot-table">
              <thead>
                <tr>
                  <th class="hotspot-th hotspot-th--repo">项目 / 仓库</th>
                  <th class="hotspot-th hotspot-th--path">路径</th>
                  <th class="hotspot-th hotspot-th--num">变更命中</th>
                  <th class="hotspot-th hotspot-th--num">拦截次数</th>
                  <th class="hotspot-th hotspot-th--score">风险分</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(row, rowIdx) in codeHotspotRows"
                  :key="row.path"
                  :class="{ 'hotspot-row--top': rowIdx === 0 }"
                >
                  <td class="hotspot-td hotspot-td--repo">
                    <span class="hotspot-repo-chip" :title="row.repo ?? undefined">{{
                      hotspotRepoLabel(row.repo)
                    }}</span>
                  </td>
                  <td class="hotspot-td hotspot-td--path">
                    <div class="hotspot-path-row">
                      <button type="button" class="hotspot-path hotspot-path--btn" @click="openHotspotCode(row)">
                        <v-icon
                          icon="mdi-file-code-outline"
                          :class="hotspotFileIconClass(row.path)"
                          size="16"
                          aria-hidden="true"
                        />
                        <span class="hotspot-path__text">
                          <span v-if="splitHotspotPath(row.path).dir" class="hotspot-path__dir mono">{{
                            splitHotspotPath(row.path).dir
                          }}</span>
                          <span class="hotspot-path__name">{{ splitHotspotPath(row.path).name }}</span>
                        </span>
                      </button>
                      <button type="button" class="hotspot-view-code" @click.stop="openHotspotCode(row)">
                        查看代码
                      </button>
                    </div>
                  </td>
                  <td class="hotspot-td hotspot-td--num">
                    <span class="hotspot-num mono">{{ row.change_hits }}</span>
                  </td>
                  <td class="hotspot-td hotspot-td--num">
                    <span class="hotspot-num mono">{{ row.block_hits }}</span>
                  </td>
                  <td class="hotspot-td hotspot-td--num hotspot-td--score">
                    <span
                      class="hotspot-risk-badge mono"
                      :class="`hotspot-risk-badge--${hotspotRiskTone(row.score)}`"
                    >
                      {{ row.score }}
                    </span>
                  </td>
                </tr>
              </tbody>
            </v-table>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-row class="dashboard-grid dashboard-stack-gap flow-row">
      <v-col cols="12">
      <v-card
        ref="flowPanelEl"
        class="flow-panel m3-surface-card m3-elevated"
        :class="{ 'flow-panel--empty': dashboard && !dashboard.recent_flows?.length }"
        rounded="xl"
        :border="false"
      >
        <v-card-title
          class="flow-panel-head d-flex flex-wrap align-center gap-2"
          :class="dashboard && !dashboard.recent_flows?.length ? 'py-3' : 'py-4'"
        >
          <span class="text-subtitle-1 font-weight-medium">最近质量门禁动态</span>
          <v-chip
            v-if="flowGateFilter"
            size="small"
            variant="flat"
            rounded="pill"
            closable
            class="flow-filter-chip ms-2"
            @click:close="clearFlowGateFilter"
          >
            仅 {{ flowGateChipLabel(flowGateFilter) }}
          </v-chip>
          <v-spacer />
          <div
            v-if="dashboard?.recent_flows?.length"
            class="d-flex align-center ga-1 flex-wrap flow-panel-actions"
          >
            <v-btn
              variant="text"
              size="small"
              color="primary"
              class="text-none"
              append-icon="mdi-chevron-right"
              @click="router.push('/analysis')"
            >
              查看全部记录
            </v-btn>
            <v-btn
              variant="text"
              size="small"
              color="primary"
              class="text-none"
              prepend-icon="mdi-help-circle-outline"
              @click="openWebhookHelp()"
            >
              配置指引
            </v-btn>
          </div>
        </v-card-title>

        <v-card-text
          class="flow-panel-body load-section"
          :class="{ 'flow-panel-body--empty': dashboard && !dashboard.recent_flows?.length }"
        >
          <v-skeleton-loader
            v-if="pageBooting"
            type="list-item@4"
            class="flow-skeleton m3-skeleton-tonal"
            boilerplate
          />

          <v-overlay
            v-else-if="pageRefreshing"
            :model-value="true"
            contained
            persistent
            scrim="rgba(26, 29, 33, 0.45)"
            class="m3-load-overlay align-center justify-center flow-refresh-overlay"
          >
            <v-progress-circular indeterminate color="primary" size="36" width="3" aria-label="列表刷新中" />
          </v-overlay>

          <div v-else-if="!(dashboard?.recent_flows?.length)" class="flow-empty-inner">
            <div class="empty-module">
              <div class="empty-module__block">
                <div class="empty-module__icon" aria-hidden="true">
                  <v-icon icon="mdi-source-branch" size="24" />
                </div>
                <div class="empty-module__text">
                  <p class="empty-module__title">暂无流水线记录</p>
                  <p class="empty-module__desc">
                    配置 Webhook 或触发分析后，动态将展示在此处。
                  </p>
                </div>
              </div>
              <div class="empty-module__actions empty-module__actions--single">
                <v-btn
                  color="primary"
                  variant="flat"
                  rounded="pill"
                  size="small"
                  class="text-none empty-module__cta"
                  append-icon="mdi-chevron-right"
                  @click="router.push('/repositories')"
                >
                  去配置仓库与 Webhook
                </v-btn>
              </div>
            </div>
          </div>

          <div v-else class="flow-list">
            <article
              v-for="item in displayFlows"
              :key="`${item.repo}-${item.commit}`"
              class="flow-row-card"
              :class="{ 'flow-row-card--block-flash': rowBlockHighlight(item) }"
            >
          <div class="flow-status-avatar" :class="flowGateAvatarClass(item.gate)" aria-hidden="true">
            <v-icon :icon="flowGateIcon(item.gate)" size="18" />
          </div>

          <div class="flow-row-source min-width-0">
            <button type="button" class="repo-link repo-link--title" @click="filterByRepo(item.repo)">
              {{ item.repo }}
            </button>
            <div class="text-caption text-medium-emphasis mono source-sub text-truncate">
              {{ formatSourceSubline(item) }}
            </div>
          </div>

          <div class="flow-row-metrics">
            <div class="flow-row-impact">
              <span class="flow-metric flow-metric--files"
                ><span class="mono">{{ item.changed_files }}</span> 文件</span
              >
              <v-tooltip :text="flowApiImpactHint(item)" :disabled="!flowApiImpactHint(item)" location="top">
                <template #activator="{ props: apiTip }">
                  <span
                    v-bind="apiTip"
                    class="flow-metric flow-metric--api"
                    :class="{ 'flow-metric--suspect': flowApiImpactHint(item) }"
                  >
                    <span class="mono">{{ item.api_impact }}</span> API
                  </span>
                </template>
              </v-tooltip>
            </div>
            <div class="flow-row-progress">
              <div class="gate-progress-wrap" role="presentation">
                <v-progress-linear
                  :model-value="item.coverage ?? 0"
                  :color="flowCoverageBarColor(item)"
                  height="8"
                  rounded
                  class="gate-progress"
                  bg-opacity="0"
                />
              </div>
              <span class="mono text-caption gate-pct">{{ flowCoveragePctLabel(item) }}</span>
            </div>
          </div>

          <div class="flow-row-right">
            <div class="gate-status-slot" :class="{ 'gate-status-slot--stack': item.gate === 'BLOCK' }">
              <v-tooltip
                :text="flowGateTooltip(item)"
                location="top end"
                content-class="gate-status-tooltip"
                :offset="10"
                :open-delay="260"
                :close-delay="60"
                :disabled="!flowGateTooltip(item)"
              >
                <template #activator="{ props: tipProps }">
                  <v-chip
                    v-bind="tipProps"
                    size="x-small"
                    variant="flat"
                    rounded="pill"
                    class="gate-status-chip"
                    :class="flowGateChipClass(item.gate)"
                  >
                    <v-icon :icon="flowGateChipIcon(item.gate)" size="14" class="gate-status-chip-icon" />
                    {{ flowGateChipLabel(item.gate) }}
                  </v-chip>
                </template>
              </v-tooltip>
              <span
                v-if="flowBlockReasonText(item)"
                class="flow-block-reason text-truncate"
                :title="`拦截原因：${flowBlockReasonText(item)}`"
              >
                {{ flowBlockReasonText(item) }}
              </span>
            </div>

            <div class="flow-row-actions d-flex align-center justify-end">
            <v-tooltip text="需关联分析任务" location="top start" :disabled="!!item.job_id">
              <template #activator="{ props: tipProps }">
                <v-btn
                  v-bind="tipProps"
                  class="flow-action-btn"
                  icon="mdi-graph-outline"
                  variant="text"
                  size="small"
                  color="primary"
                  aria-label="查看拓扑"
                  :disabled="!item.job_id"
                  @click="openCallChain(item)"
                />
              </template>
            </v-tooltip>
            <v-btn
              class="flow-action-btn"
              icon="mdi-file-code-outline"
              size="small"
              variant="text"
              color="primary"
              aria-label="代码明细"
              @click="openCoverage(item)"
            />
            </div>
          </div>
            </article>
          </div>
        </v-card-text>
      </v-card>
      </v-col>
    </v-row>

    <v-dialog v-model="coverageDialog" max-width="520">
      <v-card title="增量覆盖率报告">
        <v-card-subtitle v-if="activeFlow">
          Commit {{ activeFlow.commit }} · 门禁 {{ activeFlow.gate }}
        </v-card-subtitle>
        <v-card-text>
          <v-list v-if="activeFlow" density="compact" class="text-body-2">
            <v-list-item title="变更文件" :subtitle="`${activeFlow.changed_files} 个`" />
            <v-list-item title="影响 API" :subtitle="`${activeFlow.api_impact} 个`" />
            <v-list-item
              title="门禁结果"
              :subtitle="activeFlow.gate === 'PENDING' ? '待 CI 回传覆盖率' : activeFlow.gate"
            />
          </v-list>
          <div class="d-flex align-center ga-2 mt-4">
            <v-progress-linear
              :model-value="activeFlow?.coverage ?? 0"
              :color="(activeFlow?.coverage ?? 0) < gateBaseline ? 'error' : 'success'"
              height="10"
              rounded
              class="flex-grow-1"
            />
            <span class="mono text-body-2">{{ activeFlow?.coverage }}%</span>
          </div>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="coverageDialog = false">关闭</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <CodeDiffDrawer
      v-if="hotspotDrawerPick"
      v-model:open="hotspotDrawerOpen"
      :job-id="hotspotDrawerPick.jobId"
      :title="hotspotDrawerPick.title"
      :file="hotspotDrawerPick.file"
      :start-line="hotspotDrawerPick.startLine"
      :end-line="hotspotDrawerPick.endLine"
      node-type="changed"
      :repo="hotspotDrawerPick.repo"
    />

    <v-snackbar v-model="hotspotToastOpen" :timeout="4200" location="bottom" color="#2a2a2a">
      {{ hotspotToast }}
    </v-snackbar>
  </div>
</template>

<style scoped>
.dashboard-page {
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
}
.dashboard-page .dashboard-stack-gap {
  margin-bottom: 24px !important;
}
.dashboard-page .dashboard-stack-gap:last-child {
  margin-bottom: 0 !important;
}
.dashboard-hero {
  width: 100%;
  margin-bottom: 16px;
}
.dashboard-load-error {
  display: flex;
  align-items: center;
  gap: 12px 16px;
  margin-top: 0;
  margin-bottom: 24px;
  padding: 16px 20px;
  border-radius: 10px;
  background: rgba(245, 158, 11, 0.15);
  border: 1px solid rgba(245, 158, 11, 0.3);
  box-sizing: border-box;
}
.dashboard-load-error__icon {
  font-size: 22px;
  line-height: 1;
  color: #fbbf24;
  flex-shrink: 0;
}
.dashboard-load-error__text {
  flex: 1 1 auto;
  margin: 0;
  min-width: 0;
  font-size: 13px;
  line-height: 1.55;
  color: #fde68a;
}
.dashboard-load-error__code {
  padding: 1px 6px;
  font-size: 12px;
  font-weight: 600;
  color: #fcd34d;
  background: rgba(245, 158, 11, 0.14);
  border-radius: 4px;
  white-space: nowrap;
}
.dashboard-load-error__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  margin-inline-start: auto;
}
.dashboard-load-error__retry {
  margin: 0;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 600;
  color: #fbbf24;
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.35);
  border-radius: 8px;
  cursor: pointer;
  white-space: nowrap;
  transition:
    background 0.15s ease,
    border-color 0.15s ease,
    color 0.15s ease;
}
.dashboard-load-error__retry:hover:not(:disabled) {
  color: #fde68a;
  background: rgba(245, 158, 11, 0.2);
  border-color: rgba(245, 158, 11, 0.5);
}
.dashboard-load-error__retry:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.dashboard-load-error__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  margin: 0;
  padding: 0;
  color: rgba(253, 230, 138, 0.85);
  background: transparent;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}
.dashboard-load-error__close:hover {
  color: #fde68a;
  background: rgba(245, 158, 11, 0.15);
}
.dashboard-load-error__close .mdi {
  font-size: 20px;
}
@media (max-width: 720px) {
  .dashboard-load-error {
    flex-wrap: wrap;
  }
  .dashboard-load-error__actions {
    width: 100%;
    justify-content: flex-end;
  }
}
.chart-card-title {
  padding: 16px 24px 8px !important;
}
.chart-panel-card {
  border: 1px solid #2a2a2a !important;
  box-shadow: none !important;
}
.chart-card-title--split {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px 16px;
}
.chart-card-heading {
  line-height: 1.35;
  min-width: 0;
}
.chart-card-title__trailing {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 10px 14px;
  margin-inline-start: auto;
  max-width: min(100%, 520px);
}
.trend-sparse-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  font-size: 10px;
  line-height: 1.35;
  font-weight: 500;
  color: rgba(251, 191, 36, 0.88);
  background: rgba(251, 191, 36, 0.07);
  border: none;
  border-radius: 4px;
  white-space: nowrap;
}
.trend-sparse-badge__icon {
  font-size: 14px;
  opacity: 0.9;
}
.trend-legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px 16px;
}
.trend-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: #9aa0a8;
  white-space: nowrap;
}
.trend-legend-swatch {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  flex-shrink: 0;
}
.trend-legend-swatch--bar {
  background: rgba(255, 255, 255, 0.42);
}
.trend-legend-swatch--line {
  background: #8ab4f8;
}
.trend-legend-swatch--baseline {
  width: 14px;
  height: 0;
  border: none;
  border-radius: 0;
  border-top: 2px dashed #fb923c;
  background: transparent;
}
.chart-card-equal {
  display: flex;
  flex-direction: column;
  width: 100%;
}
.chart-card-equal .chart-card-body {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.chart-col-trend,
.chart-col-donut {
  display: flex;
}
.chart-col-trend > .v-card,
.chart-col-donut > .v-card {
  flex: 1 1 auto;
  width: 100%;
}
.chart-card-body {
  padding: 8px 20px 24px 24px !important;
}
.donut-card-body {
  padding-bottom: 20px !important;
}
.chart-card-donut {
  overflow: hidden;
}
.chart-card-donut :deep(.v-card-text) {
  overflow: hidden;
}
.donut-layout--stacked {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  flex: 1 1 auto;
  min-height: 0;
}
.donut-layout--compact {
  justify-content: center;
  align-items: center;
  gap: 0;
  min-height: 260px;
  height: 100%;
}
.chart-box {
  width: 100%;
  flex: 1 1 auto;
  min-height: 320px;
}
.dashboard-hero-sub {
  color: rgba(255, 255, 255, 0.68) !important;
  opacity: 1 !important;
}
.intercept-hero {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 8px;
  width: 100%;
  min-height: 228px;
  padding: 20px 16px 16px;
  margin: 0;
  border: none;
  border-radius: 14px;
  background: linear-gradient(180deg, rgba(239, 68, 68, 0.06) 0%, transparent 72%);
  color: inherit;
  font: inherit;
}
.intercept-hero--interactive {
  cursor: pointer;
  transition:
    background 0.18s ease,
    box-shadow 0.18s ease,
    transform 0.18s ease;
}
.intercept-hero--interactive:hover,
.intercept-hero--interactive:focus-visible {
  background: linear-gradient(180deg, rgba(239, 68, 68, 0.1) 0%, rgba(255, 255, 255, 0.02) 72%);
  box-shadow: inset 0 0 0 1px rgba(239, 68, 68, 0.22);
  outline: none;
  transform: translateY(-1px);
}
.intercept-hero-detail {
  position: absolute;
  top: 8px;
  right: 4px;
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 12px;
  color: #8ab4f8;
}
.intercept-hero-icon {
  background: rgba(239, 68, 68, 0.16) !important;
  box-shadow: 0 0 0 6px rgba(239, 68, 68, 0.08);
}
.intercept-hero-title {
  margin: 2px 0 0;
  max-width: 280px;
  font-size: 1.125rem;
  font-weight: 600;
  line-height: 1.35;
  color: rgba(255, 255, 255, 0.92);
}
.intercept-hero-metric-line {
  margin: 0;
  font-size: 0.9375rem;
  color: rgba(255, 255, 255, 0.72);
}
.intercept-hero-num {
  font-family: var(--diffgate-kpi);
  font-size: 2.25rem;
  font-weight: 700;
  line-height: 1;
  color: #ef4444;
  margin-right: 2px;
  font-variant-numeric: tabular-nums;
}
.intercept-hero-share {
  margin: 0;
  font-size: 0.8125rem;
  color: rgba(255, 255, 255, 0.5);
}
.intercept-bar-panel {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
  padding: 4px 4px 0;
}
.intercept-bar-list {
  padding: 8px 8px 4px;
  flex: 1 1 auto;
  min-height: 0;
}
.intercept-bar-row {
  margin-bottom: 16px;
}
.intercept-bar-row:last-of-type {
  margin-bottom: 8px;
}
.intercept-bar-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 8px;
}
.intercept-bar-name {
  font-size: 13px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.9);
}
.intercept-bar-stat {
  display: inline-flex;
  align-items: baseline;
  gap: 2px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.45);
  flex-shrink: 0;
}
.intercept-bar-count {
  font-size: 15px;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.92);
  font-variant-numeric: tabular-nums;
}
.intercept-bar-count-unit {
  font-size: 12px;
  font-weight: 500;
  margin-right: 4px;
}
.intercept-bar-pct {
  font-size: 11px;
  font-weight: 500;
  opacity: 0.88;
}
.intercept-bar-track {
  height: 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
}
.intercept-bar-fill {
  height: 100%;
  border-radius: 999px;
  min-width: 4px;
  transition: width 0.35s ease;
  opacity: 0.92;
}
.intercept-bar-summary {
  margin: 0;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.52);
}
.intercept-bar-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-top: auto;
  padding: 12px 8px 8px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}
.intercept-bar-cta-ghost {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 4px 2px;
  font-size: 13px;
  font-weight: 600;
  color: #8ab4f8;
  background: transparent;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition:
    background 0.15s ease,
    color 0.15s ease;
  flex-shrink: 0;
}
.intercept-bar-cta-ghost:hover {
  color: #c5d9fc;
  background: rgba(138, 180, 248, 0.08);
}
.flow-filter-chip {
  background: rgba(239, 68, 68, 0.12) !important;
  color: #ef4444 !important;
}
.flow-row-card--block-flash {
  animation: block-row-pulse 1.4s ease-in-out infinite;
}
@keyframes block-row-pulse {
  0%,
  100% {
    box-shadow: inset 0 0 0 0 rgba(239, 68, 68, 0);
  }
  50% {
    box-shadow: inset 0 0 0 1px rgba(239, 68, 68, 0.35);
  }
}
.gate-status-slot {
  flex: 0 1 auto;
  min-width: 0;
  max-width: 148px;
  display: flex;
  justify-content: flex-end;
}
.gate-status-chip-icon {
  margin-right: 3px;
}
.donut-empty-cluster {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 20px;
  width: 100%;
  height: 100%;
  min-height: 240px;
  padding: 12px 8px 8px;
  flex: 1 1 auto;
  box-sizing: border-box;
}
.donut-empty-positive {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 0 12px;
  width: 100%;
}
.donut-empty-avatar {
  background: rgba(52, 168, 83, 0.14) !important;
}
.donut-empty-title {
  margin-top: 12px;
  font-size: 1.0625rem;
  font-weight: 500;
  color: rgb(var(--v-theme-on-surface));
}
.donut-empty-sub {
  margin: 8px 0 4px;
  max-width: 220px;
}
.donut-chart-canvas--stacked {
  width: 100%;
  height: 168px;
  min-width: 0;
  margin-inline: auto;
}
.donut-empty-cluster .donut-legend-panel {
  padding-top: 0;
}
.donut-legend-panel {
  display: flex;
  flex-direction: column;
  width: 100%;
  padding: 4px 12px 0;
  gap: 0;
  box-sizing: border-box;
}
.donut-empty-cluster .donut-legend-panel {
  max-width: 100%;
}
.donut-legend-panel--idle {
  opacity: 0.55;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 6px 14px 8px !important;
  gap: 0;
}
.donut-legend-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  width: 100%;
  padding: 12px 0;
  box-sizing: border-box;
}
.donut-legend-row--divided {
  border-top: 1px solid rgba(255, 255, 255, 0.07);
}
.donut-empty-cluster .donut-legend-row:first-child {
  padding-top: 10px;
}
.donut-empty-cluster .donut-legend-row:last-child {
  padding-bottom: 10px;
}
.donut-legend-label {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1 1 auto;
}
.donut-legend-mark {
  width: 4px;
  height: 14px;
  border-radius: 2px;
  flex-shrink: 0;
}
.donut-legend-name {
  font-size: 13px;
  color: rgb(var(--v-theme-on-surface));
  line-height: 1.35;
  letter-spacing: 0.01em;
  white-space: nowrap;
  opacity: 0.88;
}
.donut-legend-stat {
  font-size: 12px;
  font-weight: 600;
  color: rgb(var(--v-theme-on-surface));
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0;
  text-align: right;
  flex-shrink: 0;
  margin-inline-start: auto;
  min-width: 5.5rem;
}
.chart-box-wrap {
  position: relative;
  width: 100%;
  flex: 1 1 auto;
  min-height: 280px;
  display: flex;
  flex-direction: column;
}
.chart-box-wrap--empty {
  min-height: 280px;
  align-items: center;
  justify-content: center;
  padding-inline: 8px;
}
.chart-box-wrap--empty .empty-module {
  width: 100%;
  max-width: 28rem;
  margin-inline: auto;
}
.chart-card-body:has(.chart-box-wrap--empty) {
  padding-inline: 24px !important;
}
.chart-box-wrap .chart-box {
  flex: 1 1 auto;
  min-height: 280px;
}
.empty-module {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 24px;
  width: 100%;
  max-width: 28rem;
  padding: 20px 24px;
  margin-inline: auto;
  text-align: center;
  box-sizing: border-box;
}
.empty-module__block {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  width: 100%;
  max-width: 26rem;
}
.empty-module__text {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  width: 100%;
}
.empty-module__icon {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: rgba(138, 180, 248, 0.12);
  color: #8ab4f8;
}
.empty-module__title {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  line-height: 1.35;
  color: #e8eaed;
}
.empty-module__desc {
  margin: 0;
  font-size: 0.8125rem;
  line-height: 1.55;
  color: rgba(255, 255, 255, 0.6);
  max-width: 26rem;
  width: 100%;
}
.empty-module__actions {
  display: flex;
  flex-direction: row;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 16px;
}
.empty-module__actions--single {
  gap: 0;
}
.empty-module__cta {
  font-weight: 600;
  padding-inline: 16px !important;
  min-width: 0;
  letter-spacing: 0;
}
.empty-module__cta :deep(.v-icon) {
  opacity: 1;
}
.chart-empty-state {
  min-height: 240px;
  flex: 0 0 auto;
}
.m3-surface-card {
  background-color: rgb(var(--v-theme-surface)) !important;
  border: 1px solid rgba(255, 255, 255, 0.05);
  box-shadow: none;
}
.m3-elevated {
  box-shadow:
    0 1px 2px rgba(0, 0, 0, 0.45),
    0 2px 8px rgba(0, 0, 0, 0.28);
}
.repo-link {
  display: inline-flex;
  align-items: center;
  border: none;
  background: none;
  padding: 0;
  font-size: 13px;
  color: rgb(var(--v-theme-primary));
  cursor: pointer;
  text-align: left;
}
.repo-link:hover {
  opacity: 0.88;
  text-decoration: underline;
}
.dashboard-filters,
.dashboard-toolbar {
  align-items: center;
  margin-inline-start: auto;
  flex-shrink: 0;
  gap: 12px;
}
.filter-range-group {
  gap: 8px;
  border-inline-start: 1px solid rgba(255, 255, 255, 0.08);
  margin-inline-start: 4px;
  padding-inline-start: 12px;
}
.dashboard-filters :deep(.repo-autocomplete.filter-select-float) {
  flex: 0 0 280px;
  width: 280px !important;
  min-width: 280px !important;
  max-width: 280px !important;
}
.dashboard-filters .filter-select-float :deep(.v-field) {
  min-height: 36px;
  height: 36px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04) !important;
  font-size: 13px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow: none;
}
.dashboard-filters .filter-select-float :deep(.v-field__outline),
.dashboard-filters .filter-select-float :deep(.v-field__overlay) {
  opacity: 0 !important;
}
.dashboard-filters .filter-select-float :deep(.v-field__input) {
  min-height: 36px;
  padding-top: 0;
  padding-bottom: 0;
  padding-inline: 2px 8px;
  font-size: 13px;
}
.dashboard-filters .filter-select-float :deep(.v-field__prepend-inner) {
  padding-inline-start: 10px;
  padding-inline-end: 4px;
}
.dashboard-filters .filter-select-float :deep(.v-field__append-inner) {
  padding-inline-end: 6px;
}
.dashboard-filters .m3-segmented {
  background-color: #1a1d21;
  border: 1px solid #2a2e35;
  border-radius: 9999px;
  padding: 2px;
  box-shadow: none;
  height: 36px;
  gap: 2px;
}
.dashboard-filters .m3-segmented :deep(.v-btn) {
  height: 30px !important;
  min-height: 30px;
  font-size: 13px;
  letter-spacing: 0;
  text-transform: none;
  color: rgb(var(--v-theme-secondary));
  background: rgba(255, 255, 255, 0.04) !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  box-shadow: none !important;
  border-radius: 9999px !important;
}
.dashboard-filters .m3-segmented :deep(.v-btn__overlay),
.dashboard-filters .m3-segmented :deep(.v-btn__underlay) {
  opacity: 0 !important;
}
.dashboard-filters .m3-segmented :deep(.v-btn:hover:not(.v-btn--active)) {
  background-color: rgba(255, 255, 255, 0.08) !important;
}
.dashboard-filters .m3-segmented :deep(.v-btn.v-btn--active) {
  background-color: #32373f !important;
  color: #f1f3f5 !important;
  font-weight: 600;
  border-color: transparent !important;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.35);
}
.dashboard-filters .filter-refresh-md {
  width: 36px;
  height: 36px;
  min-width: 36px;
  border-radius: 8px !important;
  color: rgba(255, 255, 255, 0.78);
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04) !important;
  box-shadow: none;
}
.dashboard-filters .filter-refresh-md:hover {
  background: rgba(255, 255, 255, 0.1) !important;
  color: #e8eaed;
}
.dashboard-filters .filter-refresh-md :deep(.v-btn__overlay) {
  opacity: 0 !important;
}
@keyframes spin-once {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
.spin-once {
  animation: spin-once 0.65s ease;
}
.dashboard-head {
  letter-spacing: -0.01em;
}
.flow-metric {
  font-size: 12px;
  line-height: 1.35;
  color: rgba(255, 255, 255, 0.72);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.flow-metric .mono {
  font-variant-numeric: tabular-nums;
}
.flow-metric--files {
  flex-shrink: 0;
  min-width: 4.5em;
  text-align: right;
}
.flow-metric--api {
  flex-shrink: 0;
  min-width: 3.5em;
  text-align: right;
  color: rgba(255, 255, 255, 0.78);
}
.flow-metric--suspect {
  color: #fdba74;
}
.gate-status-chip--pass {
  background: rgba(16, 185, 129, 0.12) !important;
  color: #6ee7b7 !important;
  border: none !important;
}
.gate-status-chip--block {
  background: rgba(239, 68, 68, 0.12) !important;
  color: #fca5a5 !important;
  border: none !important;
}
.gate-status-chip--pending {
  background: rgba(245, 158, 11, 0.12) !important;
  color: #fcd34d !important;
  border: none !important;
}
.gate-status-chip {
  flex-shrink: 0;
  padding-inline: 10px !important;
  width: auto;
  min-width: 0;
  justify-content: center;
  font-weight: 600;
  font-size: 12px !important;
  letter-spacing: 0;
  border-radius: 6px !important;
}
.repo-link--title {
  font-size: 14px;
  font-weight: 600;
  color: #ffffff;
}
.source-sub {
  color: rgba(255, 255, 255, 0.5) !important;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.01em;
}
.gate-progress-wrap {
  flex: 1 1 112px;
  width: 112px;
  max-width: 140px;
  min-width: 96px;
  height: 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
  position: relative;
}
.gate-progress {
  width: 100%;
  height: 8px !important;
  min-width: 0;
}
.gate-progress :deep(.v-progress-linear__background),
.gate-progress :deep(.v-progress-linear__buffer) {
  opacity: 0 !important;
}
.gate-progress :deep(.v-progress-linear__determinate),
.gate-progress :deep(.v-progress-linear__indeterminate) {
  border-radius: 999px;
}
.flow-row-actions {
  gap: 8px;
  flex-shrink: 0;
}
.flow-action-btn {
  width: 32px !important;
  height: 32px !important;
  min-width: 32px !important;
  border-radius: 50% !important;
  color: rgba(255, 255, 255, 0.82) !important;
}
.flow-action-btn :deep(.v-icon) {
  opacity: 0.92;
}
.flow-action-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.1) !important;
  color: #ffffff !important;
}
.flow-action-btn:hover:not(:disabled) :deep(.v-icon) {
  opacity: 1;
}
.chart-row {
  align-items: stretch;
}
.chart-row .chart-card-body {
  flex: 1 1 auto;
  min-height: 280px;
}
.flow-panel {
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
}
.flow-panel--empty {
  max-height: 400px;
}
.flow-panel-head {
  padding-inline: 24px !important;
  min-height: 48px;
}
.flow-panel-body {
  padding: 0 0 8px !important;
}
.flow-panel-body--empty {
  padding: 0 24px 16px !important;
}
.flow-panel-actions {
  flex-shrink: 0;
}
.flow-empty-inner {
  width: 100%;
  min-height: 200px;
  max-height: 240px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 16px 24px;
  box-sizing: border-box;
}
.flow-list {
  display: flex;
  flex-direction: column;
  gap: 0;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}
.flow-row-card {
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr);
  align-items: center;
  column-gap: 16px;
  row-gap: 8px;
  padding: 16px 24px;
  background: transparent;
  border: none;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 0;
  box-shadow: none;
  transition: background-color 0.18s ease;
}
.flow-row-card:hover {
  background: rgba(255, 255, 255, 0.04);
}
.flow-status-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  grid-column: 1;
  align-self: start;
}
.flow-status-avatar--pass {
  background: rgba(52, 168, 83, 0.16);
  color: #81c995;
}
.flow-status-avatar--block {
  background: rgba(234, 67, 53, 0.16);
  color: #f28b82;
}
.flow-status-avatar--pending {
  background: rgba(142, 146, 153, 0.16);
  color: #8e9299;
}
.flow-row-source {
  grid-column: 2;
  min-width: 0;
}
.flow-row-metrics {
  grid-column: 2;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px 20px;
  min-width: 0;
}
.flow-row-impact {
  display: inline-flex;
  align-items: center;
  gap: 16px;
  flex-shrink: 0;
}
.flow-row-progress {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1 1 160px;
  min-width: 0;
  max-width: 220px;
}
.flow-row-right {
  grid-column: 2;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px 12px;
  min-width: 0;
}
.gate-pct {
  flex-shrink: 0;
  width: 44px;
  min-width: 44px;
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: rgba(255, 255, 255, 0.88);
}
@media (min-width: 960px) {
  .flow-row-card {
    grid-template-columns: 40px minmax(0, 30%) minmax(240px, 40%) minmax(0, 30%);
  }
  .flow-row-source,
  .flow-row-metrics,
  .flow-row-right {
    grid-column: auto;
  }
  .flow-status-avatar {
    align-self: center;
  }
  .flow-row-metrics {
    gap: 20px;
  }
  .flow-row-right {
    justify-self: stretch;
  }
}
.gate-status-slot--stack {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  min-width: 0;
  max-width: 132px;
}
.flow-block-reason {
  font-size: 10px;
  line-height: 1.35;
  color: rgba(232, 168, 163, 0.92);
  max-width: 100%;
  text-align: right;
}
.flow-row-actions {
  opacity: 0.82;
  transition: opacity 0.18s ease;
  gap: 4px;
}
.flow-row-card:hover .flow-row-actions {
  opacity: 1;
}
.dashboard-load-bar {
  margin: -4px 0 16px;
  opacity: 0.95;
}
.load-section {
  position: relative;
}
.load-section--kpi {
  margin-bottom: 24px;
}
.chart-card-body--load {
  min-height: 220px;
}
.kpi-skeleton {
  border-radius: 16px;
  min-height: 168px;
}
.m3-skeleton-tonal :deep(.v-skeleton-loader__bone),
.m3-skeleton-tonal :deep(.v-skeleton-loader__image) {
  background: rgba(255, 255, 255, 0.06) !important;
}
.m3-skeleton-tonal :deep(.v-skeleton-loader__bone::after) {
  background: linear-gradient(
    90deg,
    transparent,
    rgba(255, 255, 255, 0.07),
    transparent
  ) !important;
}
.chart-skeleton {
  border-radius: 12px;
  overflow: hidden;
}
.m3-load-overlay :deep(.v-overlay__content) {
  display: flex;
  align-items: center;
  justify-content: center;
}
.flow-refresh-overlay {
  min-height: 120px;
}
.hotspot-panel {
  background: #151515 !important;
  border: 1px solid #2a2a2a !important;
  border-radius: 8px !important;
  box-shadow: none !important;
  overflow: hidden;
}
.hotspot-panel__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 16px;
  padding: 16px 20px 12px !important;
}
.hotspot-panel__title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.hotspot-panel__title-icon {
  color: #fb923c;
  flex-shrink: 0;
}
.hotspot-panel__title-text {
  font-size: 15px;
  font-weight: 600;
  color: #ffffff;
  letter-spacing: 0.01em;
}
.hotspot-panel__cta {
  font-weight: 500;
}
.hotspot-panel__body {
  padding: 0 16px 12px !important;
}
.hotspot-table {
  background: transparent !important;
}
.hotspot-table :deep(table) {
  width: 100%;
  table-layout: fixed;
}
.hotspot-th {
  font-size: 12px !important;
  font-weight: 500 !important;
  color: rgba(255, 255, 255, 0.55) !important;
  border-bottom: 1px solid #2a2a2a !important;
  padding: 8px 10px !important;
  white-space: nowrap;
}
.hotspot-th--repo {
  text-align: left !important;
  width: 124px;
  padding-left: 4px !important;
}
.hotspot-th--path {
  text-align: left !important;
  width: auto;
  padding-left: 4px !important;
}
.hotspot-th--num {
  text-align: center !important;
  width: 80px;
  padding-inline: 10px !important;
}
.hotspot-th--score {
  text-align: center !important;
  width: 72px;
  padding-inline: 8px !important;
}
.hotspot-table :deep(tbody tr) {
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  background: #1a1a1a;
  transition: background 0.15s ease;
}
.hotspot-table :deep(tbody tr:hover) {
  background: #252525 !important;
}
.hotspot-table :deep(tbody tr:last-child) {
  border-bottom: none;
}
.hotspot-row--top {
  background: linear-gradient(90deg, rgba(239, 68, 68, 0.08) 0%, rgba(239, 68, 68, 0.03) 40%, #1a1a1a 100%);
  box-shadow: inset 3px 0 0 #ef4444;
}
.hotspot-row--top:hover {
  background: #252525 !important;
}
.hotspot-td {
  padding: 11px 10px !important;
  vertical-align: middle !important;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.86);
}
.hotspot-td--repo {
  text-align: left;
  padding-left: 4px !important;
  vertical-align: middle !important;
}
.hotspot-td--path {
  text-align: left;
  padding-left: 4px !important;
  vertical-align: middle !important;
}
.hotspot-td--num {
  text-align: center;
  padding-inline: 10px !important;
  vertical-align: middle !important;
}
.hotspot-td--score {
  text-align: center;
  vertical-align: middle !important;
}
.hotspot-repo-chip {
  display: inline-block;
  max-width: 112px;
  padding: 3px 9px;
  font-size: 11px;
  font-weight: 500;
  line-height: 1.35;
  color: rgba(255, 255, 255, 0.58);
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}
.hotspot-num {
  display: inline-block;
  width: 100%;
  text-align: center;
  font-size: 13px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.9);
  font-variant-numeric: tabular-nums;
}
.hotspot-path-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  min-width: 0;
}
.hotspot-path--btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1 1 auto;
  margin: 0;
  padding: 0;
  border: none;
  background: transparent;
  text-align: left;
  cursor: pointer;
  color: inherit;
}
.hotspot-path {
  display: inline-flex;
  align-items: flex-start;
  gap: 8px;
  min-width: 0;
}
.hotspot-path__icon {
  color: rgba(255, 255, 255, 0.38);
  flex-shrink: 0;
}
.hotspot-path__icon--py {
  color: #8ab4f8;
}
.hotspot-path__text {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0 2px;
  min-width: 0;
  line-height: 1.4;
}
.hotspot-table :deep(tbody tr:hover) .hotspot-path__name {
  color: #c5d9fc;
}
.hotspot-path__dir {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.36);
}
.hotspot-path__name {
  font-size: 13px;
  font-weight: 600;
  color: #f8fafc;
  transition: color 0.15s ease;
}
.hotspot-view-code {
  flex-shrink: 0;
  opacity: 0;
  margin: 0;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 500;
  color: #8ab4f8;
  background: transparent;
  border: 1px solid rgba(138, 180, 248, 0.28);
  border-radius: 999px;
  white-space: nowrap;
  cursor: pointer;
  transition:
    opacity 0.15s ease,
    background 0.15s ease,
    border-color 0.15s ease;
}
.hotspot-table :deep(tbody tr:hover) .hotspot-view-code {
  opacity: 1;
}
.hotspot-view-code:hover {
  background: rgba(138, 180, 248, 0.1);
  border-color: rgba(138, 180, 248, 0.45);
}
.hotspot-risk-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 32px;
  height: 26px;
  padding: 0 10px;
  font-size: 12px;
  font-weight: 700;
  border-radius: 999px;
  font-variant-numeric: tabular-nums;
}
.hotspot-risk-badge--high {
  color: #fecaca;
  background: rgba(239, 68, 68, 0.14);
  border: 1px solid rgba(248, 113, 113, 0.55);
  box-shadow: 0 0 0 1px rgba(239, 68, 68, 0.2), 0 0 12px rgba(239, 68, 68, 0.28);
}
.hotspot-risk-badge--mid {
  color: #fed7aa;
  background: rgba(251, 146, 60, 0.09);
  border: 1px solid rgba(251, 146, 60, 0.26);
}
.hotspot-risk-badge--low {
  color: rgba(255, 255, 255, 0.68);
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.flow-skeleton :deep(.v-skeleton-loader__list-item) {
  margin-bottom: 8px;
  border-radius: 16px;
}
@media (max-width: 959px) {
  .flow-row-card {
    padding: 14px 16px;
    row-gap: 10px;
  }
  .flow-status-avatar {
    grid-row: 1 / span 3;
  }
  .flow-row-progress {
    max-width: 100%;
  }
  .gate-progress-wrap {
    flex: 1 1 120px;
    max-width: 100%;
  }
}
</style>

<style>
/* Teleported Vuetify tooltips — must be global */
.v-overlay__content.gate-status-tooltip {
  background: rgba(44, 44, 44, 0.98) !important;
  color: rgba(255, 255, 255, 0.88) !important;
  padding: 8px 12px !important;
  line-height: 1.5 !important;
  font-size: 12px !important;
  font-weight: 400;
  letter-spacing: 0.01em;
  border-radius: 8px !important;
  border: 1px solid rgba(255, 255, 255, 0.12) !important;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5) !important;
  max-width: min(260px, 92vw);
  text-align: left;
  opacity: 1 !important;
}
.v-overlay__content.gate-status-tooltip .v-tooltip__content {
  color: rgba(255, 255, 255, 0.88) !important;
  line-height: 1.5 !important;
}
</style>