<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { fetchDashboardOverview } from '@/api/client'
import RepoAutocompleteFilter from '@/components/RepoAutocompleteFilter.vue'

const router = useRouter()
const openWebhookHelp = inject<() => void>('openWebhookHelp', () => {})
const openNewAnalysis = inject<() => void>('openNewAnalysis', () => {})

const days = ref<7 | 30 | 90>(7)
const refreshSpin = ref(false)
const repoFilter = ref<string | null>(null)

const loading = ref(false)
const loadError = ref(false)
const dashboard = ref<Awaited<ReturnType<typeof fetchDashboardOverview>> | null>(null)

const trendRef = ref<HTMLDivElement | null>(null)
const donutRef = ref<HTMLDivElement | null>(null)
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
  if (gate === 'BLOCK') return 'mdi-alert-circle'
  return 'mdi-clock-outline'
}

function flowGateChipClass(gate: string) {
  if (gate === 'PASS') return 'gate-status-chip--pass'
  if (gate === 'BLOCK') return 'gate-status-chip--block'
  return 'gate-status-chip--pending'
}

function coverageBarColor(coverage: number | null) {
  if (coverage == null) return 'secondary'
  return coverage < gateBaseline.value ? 'error' : 'success'
}

const kpiCards = computed(() => {
  const k = dashboard.value?.kpi
  if (!k) return []
  const pending = k.pending_count ?? 0
  const delta = k.coverage_delta
  const trendPill =
    delta !== 0 ? `${delta > 0 ? '+' : ''}${delta}%` : undefined
  const coverageValueColor =
    k.avg_coverage > 0 && k.avg_coverage < k.gate_baseline
      ? '#F28B82'
      : k.avg_coverage >= k.gate_baseline && k.avg_coverage > 0
        ? '#81C995'
        : undefined
  const passValueColor =
    k.first_pass_rate >= 100 && k.pass_count > 0
      ? '#81C995'
      : k.first_pass_rate > 0 && k.first_pass_rate < 60
        ? '#FDD663'
        : undefined

  return [
    {
      title: '平均增量代码覆盖率',
      value: `${k.avg_coverage}%`,
      trendPill,
      sub: `门禁基线 ${k.gate_baseline}%`,
      icon: 'mdi-shield-check',
      iconColor: '#81C995',
      iconBg: 'rgba(52, 168, 83, 0.15)',
      accent: '#81C995',
      valueColor: coverageValueColor,
    },
    {
      title: '质量门禁一次通过率',
      value: `${k.first_pass_rate}%`,
      sub: `通过 ${k.pass_count} 次 / 拦截 ${k.block_count} 次${pending ? ` / 待测 ${pending}` : ''}`,
      icon: 'mdi-check-decagram',
      iconColor: '#8AB4F8',
      iconBg: 'rgba(138, 180, 248, 0.15)',
      accent: '#8AB4F8',
      valueColor: passValueColor,
    },
    {
      title: '累计高危变更拦截',
      value: `${k.high_risk_total} 次`,
      sub: '避免不达标代码合入主干',
      icon: 'mdi-shield-alert',
      iconColor: '#F28B82',
      iconBg: 'rgba(234, 67, 53, 0.15)',
      accent: '#F28B82',
      valueColor: undefined,
    },
    {
      title: '精准测试累计节省工时',
      value: `${k.saved_hours} h`,
      sub: `用例压缩率均值 ${k.case_compress_pct}%`,
      icon: 'mdi-lightning-bolt-outline',
      iconColor: '#FDD663',
      iconBg: 'rgba(253, 214, 99, 0.15)',
      accent: '#FDD663',
      valueColor: undefined,
    },
  ]
})

type FlowRow = Awaited<ReturnType<typeof fetchDashboardOverview>>['recent_flows'][number]

const coverageDialog = ref(false)
const activeFlow = ref<FlowRow | null>(null)

function formatTriggerTime(iso: string | null | undefined) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso.replace('T', ' ').replace(/\.\d+Z?$/, '')
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function formatRelativeTime(iso: string | null | undefined) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const diffMin = Math.max(0, Math.floor((Date.now() - d.getTime()) / 60000))
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin} 分钟前`
  const hours = Math.floor(diffMin / 60)
  if (hours < 48) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 14) return `${days} 天前`
  return formatTriggerTime(iso).slice(0, 16)
}

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

const DONUT_COLORS = ['#8AB4F8', '#FDD663', '#F28B82'] as const

const CHART = {
  axis: 'rgba(255, 255, 255, 0.6)',
  axisDim: '#8E9299',
  grid: 'rgba(255, 255, 255, 0.1)',
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

function resizeCharts() {
  requestAnimationFrame(() => {
    trendChart?.resize()
    donutChart?.resize()
  })
}

async function load() {
  loading.value = true
  loadError.value = false
  try {
    dashboard.value = await fetchDashboardOverview(days.value, repoFilter.value || undefined)
    await nextTick()
    renderCharts()
    resizeCharts()
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
    await nextTick()
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
    trend.coverage.some((n) => n != null && n > 0)
  )
}

const trendShowEmptyOverlay = computed(() => {
  const trend = dashboard.value?.trend
  if (!dashboard.value || !trend) return false
  if (!trend.labels?.length) return true
  return !trendHasActivity(trend)
})

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
  const { intercept_reasons, kpi } = dashboard.value
  const trend = dashboard.value.trend
  const threshold = trend.threshold

  const donutData = intercept_reasons.map((r) => ({
    ...r,
    name: shortenReasonLabel(r.name),
  }))
  const donutSum = donutData.reduce((s, r) => s + r.value, 0)
  const pieData =
    donutSum > 0
      ? donutData.filter((d) => d.value > 0)
      : [{ name: '', value: 1, itemStyle: { color: 'transparent' }, tooltip: { show: false } }]

  const trendActive = trendHasActivity(trend)

  if (trendRef.value) {
    if (!trendActive) {
      trendChart?.dispose()
      trendChart = null
    } else {
    trendChart?.dispose()
    trendChart = echarts.init(trendRef.value)
    trendChart.setOption({
      color: [CHART.bar, CHART.line],
      tooltip: {
        trigger: 'axis',
        backgroundColor: CHART.tooltipBg,
        borderColor: CHART.grid,
        textStyle: { color: CHART.tooltipText, fontSize: 12 },
      },
      legend: { show: false },
      graphic: [],
      xAxis: {
        type: 'category',
        data: trend.labels,
        axisLabel: { color: CHART.axis },
        axisLine: { lineStyle: { color: CHART.grid } },
        axisTick: { lineStyle: { color: CHART.grid } },
      },
      yAxis: [
        {
          type: 'value',
          name: '行数',
          min: 0,
          max: 500,
          nameTextStyle: { color: CHART.axis },
          axisLabel: { color: CHART.axis },
          splitLine: { lineStyle: { type: 'dashed', color: CHART.grid } },
        },
        {
          type: 'value',
          name: '%',
          min: 50,
          max: 100,
          nameTextStyle: { color: CHART.axis },
          axisLabel: {
            color: CHART.axis,
            formatter: (v: number) => (v === threshold ? '' : `${v}%`),
          },
          splitLine: { show: false },
          axisLine: { lineStyle: { color: CHART.grid } },
        },
      ],
      series: [
        {
          name: '变更行数',
          type: 'bar',
          data: trend.changed_lines,
          itemStyle: { color: trendActive ? CHART.bar : 'rgba(37, 41, 48, 0.45)' },
          barMaxWidth: 28,
        },
        {
          name: '增量覆盖率',
          type: 'line',
          yAxisIndex: 1,
          smooth: true,
          showSymbol: false,
          symbol: 'circle',
          symbolSize: 8,
          lineStyle: { width: 2, color: trendActive ? CHART.line : 'rgba(138, 180, 248, 0.35)' },
          data: trend.coverage.map((c) => (c == null ? '-' : c)),
          areaStyle: trendActive
            ? {
                color: {
                  type: 'linear',
                  x: 0,
                  y: 0,
                  x2: 0,
                  y2: 1,
                  colorStops: [
                    { offset: 0, color: CHART.areaTop },
                    { offset: 1, color: 'rgba(138, 180, 248, 0)' },
                  ],
                },
              }
            : undefined,
          emphasis: {
            scale: true,
            focus: 'series',
            symbol: 'circle',
            symbolSize: 8,
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
            lineStyle: { color: CHART.baseline, type: 'dashed', width: 1.5 },
            label: {
              show: true,
              formatter: `门禁基线 ${threshold}%`,
              position: 'end',
              color: CHART.baseline,
              fontSize: 11,
              distance: 6,
              align: 'right',
              verticalAlign: 'middle',
            },
            data: [{ yAxis: threshold }],
          },
        },
      ],
    })
    }
  }

  if (donutRef.value) {
    if (donutSum === 0) {
      donutChart?.dispose()
      donutChart = null
    } else {
      donutChart?.dispose()
      donutChart = echarts.init(donutRef.value)
      const centerTotal = kpi.block_count || interceptTotal.value
      const numSize = centerTotal >= 10 ? 26 : 28
      const donutCenter: [string, string] = ['50%', '46%']
      donutChart.setOption({
        tooltip: {
          trigger: 'item',
          formatter: '{b}: {c} 次 ({d}%)',
          backgroundColor: CHART.tooltipBg,
          borderColor: CHART.grid,
          textStyle: { color: CHART.tooltipText, fontSize: 12 },
        },
        legend: { show: false },
        title: {
          text: '累计拦截',
          subtext: `{num|${centerTotal}}{unit|次}`,
          left: donutCenter[0],
          top: donutCenter[1],
          textAlign: 'center',
          textVerticalAlign: 'middle',
          textStyle: {
            fontSize: 12,
            fontWeight: 400,
            color: CHART.centerLabel,
            fontFamily: '"Noto Sans SC", system-ui, sans-serif',
          },
          subtextStyle: {
            color: CHART.centerValue,
            fontFamily: 'Roboto, system-ui, sans-serif',
            rich: {
              num: {
                fontSize: numSize,
                fontWeight: 700,
                color: CHART.centerValue,
                padding: [0, 2, 0, 0],
              },
              unit: {
                fontSize: 14,
                fontWeight: 500,
                color: CHART.centerLabel,
                verticalAlign: 'bottom',
                padding: [0, 0, 4, 0],
              },
            },
          },
          itemGap: 8,
        },
        series: [
          {
            type: 'pie',
            radius: ['72%', '88%'],
            center: donutCenter,
            data: pieData,
            label: { show: false },
            labelLine: { show: false },
            itemStyle: {
              borderColor: CHART.ringGap,
              borderWidth: 2,
            },
            color: [...DONUT_COLORS],
          },
        ],
      })
    }
  } else if (donutSum === 0) {
    donutChart?.dispose()
    donutChart = null
  }
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
    <div class="dashboard-hero d-flex flex-wrap align-start justify-space-between gap-4 mb-4">
      <div>
        <h2 class="text-h5 text-md-h4 font-weight-bold dashboard-head mb-2">质量驾驶舱</h2>
        <p class="text-body-2 text-medium-emphasis mb-0">
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

    <v-alert
      v-if="loadError"
      type="warning"
      variant="tonal"
      density="comfortable"
      class="mb-4"
      rounded="lg"
      prominent
    >
      无法加载驾驶舱数据。请确认已运行 <code class="mono">run_api.ps1</code>，且前端代理能访问
      <code class="mono">/api/v1</code>。
    </v-alert>

    <v-row class="dashboard-grid dashboard-stack-gap kpi-row">
      <v-col v-for="(card, index) in kpiCards" :key="card.title" cols="12" sm="6" lg="3">
        <v-card
          class="h-100 kpi-card m3-surface-card m3-elevated"
          :class="index === 0 ? 'kpi-card--hero' : 'kpi-card--muted'"
          rounded="xl"
          :border="false"
        >
          <span class="kpi-accent" :style="{ backgroundColor: card.accent }" aria-hidden="true" />
          <v-card-text class="kpi-card-inner">
            <div class="d-flex align-start justify-space-between gap-2 mb-3">
              <div class="text-body-2 text-medium-emphasis kpi-title">{{ card.title }}</div>
              <v-avatar size="40" rounded="lg" :style="{ backgroundColor: card.iconBg }" class="kpi-icon-tonal">
                <v-icon :icon="card.icon" :color="card.iconColor" size="22" />
              </v-avatar>
            </div>
            <div
              class="kpi-metric"
              :style="card.valueColor ? { color: card.valueColor } : undefined"
            >
              {{ card.value }}
            </div>
            <div class="d-flex flex-wrap align-center ga-1 mt-3">
              <v-chip
                v-if="'trendPill' in card && card.trendPill"
                size="x-small"
                variant="flat"
                rounded="pill"
                class="kpi-trend-pill kpi-trend-pill--up"
              >
                {{ card.trendPill }}
              </v-chip>
              <span class="text-caption text-medium-emphasis kpi-sub">{{ card.sub }}</span>
            </div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-row class="dashboard-grid dashboard-stack-gap chart-row" align="stretch">
      <v-col cols="12" lg="8" class="chart-col-trend">
        <v-card
          class="h-100 chart-card-equal m3-surface-card m3-elevated"
          rounded="xl"
          :border="false"
        >
          <v-card-title class="chart-card-title chart-card-title--split">
            <span class="text-subtitle-1 font-weight-medium chart-card-heading">增量代码覆盖率 vs 门禁通过趋势</span>
            <div class="trend-legend" aria-hidden="true">
              <span class="trend-legend-item">
                <span class="trend-legend-swatch trend-legend-swatch--bar" />
                变更行数
              </span>
              <span class="trend-legend-item">
                <span class="trend-legend-swatch trend-legend-swatch--line" />
                增量覆盖率
              </span>
            </div>
          </v-card-title>
          <v-card-text class="chart-card-body">
            <v-skeleton-loader v-if="loading && !dashboard" type="image" height="290" />
            <div
              v-show="dashboard"
              class="chart-box-wrap"
              :class="{ 'chart-box-wrap--empty': trendShowEmptyOverlay }"
            >
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
                    <p class="empty-module__title">暂无近期数据</p>
                    <p class="empty-module__desc">{{ trendEmptyCta.sub }}</p>
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
          class="h-100 chart-card-equal m3-surface-card m3-elevated chart-card-donut"
          rounded="xl"
          :border="false"
        >
          <v-card-title class="text-subtitle-1 font-weight-medium chart-card-title">门禁拦截原因分布</v-card-title>
          <v-card-text class="chart-card-body donut-card-body pt-0">
            <v-skeleton-loader v-if="loading && !dashboard" type="image" height="220" />
            <div
              v-show="dashboard"
              class="donut-layout donut-layout--stacked"
              :class="{ 'donut-layout--compact': donutIsEmpty }"
            >
              <template v-if="donutIsEmpty">
                <div class="donut-empty-cluster">
                  <div class="donut-empty-positive">
                    <v-avatar size="68" rounded="circle" class="donut-empty-avatar">
                      <v-icon icon="mdi-shield-check" size="34" color="#81C995" />
                    </v-avatar>
                    <div class="donut-empty-title">暂无拦截</div>
                    <p class="text-caption text-medium-emphasis donut-empty-sub">
                      当前时间范围内无 BLOCK 门禁记录；待决任务不计入拦截分布。
                    </p>
                  </div>
                </div>
              </template>
              <template v-else>
                <div ref="donutRef" class="donut-chart-canvas donut-chart-canvas--stacked" />
                <div class="donut-legend-panel">
                  <div
                    v-for="(row, idx) in donutLegendItems"
                    :key="row.name"
                    class="donut-legend-row"
                    :class="{ 'donut-legend-row--divided': idx > 0 }"
                  >
                    <div class="donut-legend-label">
                      <span class="donut-legend-mark" :style="{ backgroundColor: row.color }" />
                      <span class="donut-legend-name">{{ row.name }}</span>
                    </div>
                    <span class="donut-legend-stat mono">{{ row.value }} 次 {{ row.pct }}%</span>
                  </div>
                </div>
              </template>
            </div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-row class="dashboard-grid dashboard-stack-gap flow-row">
      <v-col cols="12">
      <v-card
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
          class="flow-panel-body"
          :class="{ 'flow-panel-body--empty': dashboard && !dashboard.recent_flows?.length }"
        >
          <v-skeleton-loader v-if="loading && !dashboard" type="list-item@4" class="flow-skeleton" />

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
              v-for="item in dashboard!.recent_flows"
              :key="`${item.repo}-${item.commit}`"
              class="flow-row-card"
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

          <div class="flow-row-impact d-none d-sm-flex align-center">
            <v-chip size="x-small" variant="flat" rounded="pill" class="impact-chip">{{ item.changed_files }} 文件</v-chip>
            <v-chip size="x-small" variant="flat" rounded="pill" class="impact-chip impact-chip--accent">{{ item.api_impact }} API</v-chip>
          </div>

          <div class="flow-row-gate">
            <v-progress-linear
              :model-value="item.coverage ?? 0"
              :color="coverageBarColor(item.coverage)"
              height="8"
              rounded
              class="gate-progress"
            />
            <span class="mono text-caption gate-pct">{{ item.coverage != null ? `${item.coverage}%` : '—' }}</span>
            <v-chip
              size="x-small"
              variant="flat"
              rounded="pill"
              class="gate-status-chip"
              :class="flowGateChipClass(item.gate)"
            >
              {{ item.gate }}
            </v-chip>
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
}
.chart-card-title {
  padding: 16px 24px 8px !important;
}
.chart-card-title--split {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px 16px;
}
.chart-card-heading {
  line-height: 1.35;
  min-width: 0;
}
.trend-legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px 16px;
  margin-inline-start: auto;
}
.trend-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #8e9299;
  white-space: nowrap;
}
.trend-legend-swatch {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  flex-shrink: 0;
}
.trend-legend-swatch--bar {
  background: rgba(255, 255, 255, 0.38);
  height: 8px;
  width: 14px;
  border-radius: 2px;
}
.trend-legend-swatch--line {
  background: #8ab4f8;
  border-radius: 999px;
  width: 10px;
  height: 10px;
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
  min-height: 280px;
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
  opacity: 0.9;
}
.kpi-card-inner {
  padding: 20px 20px 22px 22px !important;
}
.kpi-title {
  line-height: 1.35;
  opacity: 0.72;
}
.kpi-icon-tonal {
  flex-shrink: 0;
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
.kpi-trend-pill {
  font-weight: 500;
  font-variant-numeric: tabular-nums;
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
  min-height: 40px;
  height: 40px;
  border-radius: 10px;
  background-color: rgb(var(--v-theme-surface)) !important;
  font-size: 13px;
  border: 1px solid #2a2e35;
  box-shadow: none;
}
.dashboard-filters .filter-select-float :deep(.v-field__outline),
.dashboard-filters .filter-select-float :deep(.v-field__overlay) {
  opacity: 0 !important;
}
.dashboard-filters .filter-select-float :deep(.v-field__input) {
  min-height: 40px;
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
  height: 40px;
  gap: 2px;
}
.dashboard-filters .m3-segmented :deep(.v-btn) {
  height: 34px !important;
  min-height: 34px;
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
  width: 40px;
  height: 40px;
  min-width: 40px;
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
.kpi-card--hero {
  background-color: #252a31 !important;
  border-color: #32373f !important;
}
.kpi-card--muted {
  background-color: rgb(var(--v-theme-surface)) !important;
}
.kpi-metric {
  font-family: var(--diffgate-kpi);
  font-size: 2.25rem;
  font-weight: 600;
  line-height: 1.12;
  color: rgb(var(--v-theme-on-surface));
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
}
.kpi-sub {
  color: rgba(255, 255, 255, 0.62) !important;
  opacity: 1;
  font-size: 13px !important;
}
.kpi-trend-pill--up {
  background: rgba(52, 168, 83, 0.16) !important;
  color: #81c995 !important;
}
.impact-chip {
  background: #24282e !important;
  color: rgb(var(--v-theme-secondary)) !important;
}
.impact-chip--accent {
  color: rgb(var(--v-theme-primary)) !important;
}
.gate-status-chip--pass {
  background: rgba(52, 168, 83, 0.16) !important;
  color: #81c995 !important;
}
.gate-status-chip--block {
  background: rgba(234, 67, 53, 0.16) !important;
  color: #f28b82 !important;
}
.gate-status-chip--pending {
  background: rgba(253, 214, 99, 0.18) !important;
  color: #fdd663 !important;
}
.gate-status-chip {
  flex-shrink: 0;
  padding-inline: 10px !important;
  min-width: 4.75rem;
  justify-content: center;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.repo-link--title {
  font-size: 14px;
  font-weight: 500;
}
.gate-progress {
  flex: 1 1 64px;
  max-width: 88px;
  min-width: 56px;
}
.flow-row-actions {
  gap: 8px;
  flex-shrink: 0;
}
.flow-action-btn {
  width: 40px !important;
  height: 40px !important;
  border-radius: 50% !important;
}
.flow-action-btn:hover:not(:disabled) {
  background: rgba(138, 180, 248, 0.12) !important;
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
  padding: 0 24px 20px !important;
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
  gap: 8px;
}
.flow-row-card {
  display: grid;
  grid-template-columns: 40px minmax(0, 1.15fr) auto minmax(168px, 1fr) auto;
  align-items: center;
  column-gap: 12px;
  row-gap: 8px;
  padding: 14px 16px;
  background: rgb(var(--v-theme-surface));
  border: 1px solid rgb(var(--v-theme-outline));
  border-radius: 16px;
  box-shadow: none;
  transition:
    background-color 0.18s ease,
    border-color 0.18s ease;
}
.flow-row-card:hover {
  background: #24282e;
  border-color: #343a42;
}
.flow-status-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
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
  min-width: 0;
}
.flow-row-impact {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: nowrap;
}
.flow-row-gate {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex-wrap: nowrap;
}
.gate-pct {
  flex-shrink: 0;
  color: rgb(var(--v-theme-on-surface));
  opacity: 0.88;
}
.flow-row-actions {
  opacity: 0.55;
  transition: opacity 0.18s ease;
}
.flow-row-card:hover .flow-row-actions {
  opacity: 1;
}
.flow-skeleton :deep(.v-skeleton-loader__list-item) {
  margin-bottom: 8px;
  border-radius: 16px;
}
@media (max-width: 959px) {
  .flow-row-card {
    grid-template-columns: 40px minmax(0, 1fr) auto;
    grid-template-areas:
      'status source actions'
      'status gate gate';
  }
  .flow-status-avatar {
    grid-area: status;
  }
  .flow-row-source {
    grid-area: source;
  }
  .flow-row-gate {
    grid-area: gate;
    grid-column: 2 / -1;
  }
  .flow-row-actions {
    grid-area: actions;
  }
}
</style>