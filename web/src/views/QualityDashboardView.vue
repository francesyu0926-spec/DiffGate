<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { fetchDashboardOverview, fetchRepositories } from '@/api/client'

const router = useRouter()
const openWebhookHelp = inject<() => void>('openWebhookHelp', () => {})

const days = ref<1 | 7 | 30 | 90>(7)
const refreshSpin = ref(false)
const repoFilter = ref<string | null>(null)
const repoOptions = ref<{ title: string; value: string | null }[]>([])

const loading = ref(false)
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
  return [
    {
      title: '平均增量代码覆盖率',
      value: `${k.avg_coverage}%`,
      trendPill,
      sub: `门禁基线 ${k.gate_baseline}%`,
      icon: 'mdi-shield-check',
      iconColor: '#81C995',
      iconBg: 'rgba(52, 168, 83, 0.16)',
    },
    {
      title: '质量门禁一次通过率',
      value: `${k.first_pass_rate}%`,
      sub: `通过 ${k.pass_count} 次 / 拦截 ${k.block_count} 次${pending ? ` / 待测 ${pending}` : ''}`,
      icon: 'mdi-check-decagram',
      iconColor: '#8AB4F8',
      iconBg: 'rgba(138, 180, 248, 0.14)',
    },
    {
      title: '累计高危变更拦截',
      value: `${k.high_risk_total} 次`,
      sub: '避免不达标代码合入主干',
      icon: 'mdi-shield-alert',
      iconColor: '#F28B82',
      iconBg: 'rgba(234, 67, 53, 0.14)',
    },
    {
      title: '精准测试累计节省工时',
      value: `${k.saved_hours} h`,
      sub: `用例压缩率均值 ${k.case_compress_pct}%`,
      icon: 'mdi-lightning-bolt-outline',
      iconColor: '#FDD663',
      iconBg: 'rgba(253, 214, 99, 0.14)',
    },
  ]
})

type FlowRow = Awaited<ReturnType<typeof fetchDashboardOverview>>['recent_flows'][number]

const coverageDialog = ref(false)
const callChainDialog = ref(false)
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

const DONUT_COLORS = ['#8AB4F8', '#FDD663', '#F28B82'] as const

const CHART = {
  axis: '#8E9299',
  grid: '#26292E',
  line: '#8AB4F8',
  bar: 'rgba(142, 146, 153, 0.32)',
  areaTop: 'rgba(138, 180, 248, 0.18)',
  baseline: '#F28B82',
  centerValue: '#F1F3F5',
  centerLabel: '#8E9299',
  ringGap: '#1A1D21',
  tooltipBg: '#24282E',
  tooltipText: '#F1F3F5',
} as const

const donutLegendItems = computed(() => {
  const reasons = dashboard.value?.intercept_reasons ?? []
  const items = reasons.map((r) => ({
    ...r,
    name: shortenReasonLabel(r.name),
  }))
  const total = items.reduce((s, r) => s + r.value, 0) || 1
  return items.map((r, i) => ({
    name: r.name,
    value: r.value,
    pct: Math.round((r.value / total) * 100),
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
  try {
    dashboard.value = await fetchDashboardOverview(days.value, repoFilter.value || undefined)
    await nextTick()
    renderCharts()
    resizeCharts()
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

function renderCharts() {
  if (!dashboard.value) return
  const { trend, intercept_reasons, kpi } = dashboard.value
  const threshold = trend.threshold
  const donutData = intercept_reasons.map((r) => ({
    ...r,
    name: shortenReasonLabel(r.name),
  }))

  if (trendRef.value) {
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
      legend: {
        data: ['变更行数', '增量覆盖率'],
        top: 4,
        textStyle: { color: CHART.axis, fontSize: 12 },
      },
      grid: { left: 48, right: 24, top: 44, bottom: 28 },
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
          axisLabel: { formatter: '{value}%', color: CHART.axis },
          splitLine: { show: false },
          axisLine: { lineStyle: { color: CHART.grid } },
        },
      ],
      series: [
        {
          name: '变更行数',
          type: 'bar',
          data: trend.changed_lines,
          itemStyle: { color: CHART.bar },
          barMaxWidth: 28,
        },
        {
          name: '增量覆盖率',
          type: 'line',
          yAxisIndex: 1,
          smooth: true,
          symbol: 'circle',
          symbolSize: 8,
          lineStyle: { width: 3, color: CHART.line },
          data: trend.coverage,
          areaStyle: {
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
          },
          itemStyle: {
            color: CHART.line,
            borderColor: CHART.ringGap,
            borderWidth: 2,
          },
          markLine: {
            silent: true,
            symbol: 'none',
            lineStyle: { color: CHART.baseline, type: 'dashed', width: 1.5 },
            label: {
              show: true,
              formatter: `门禁基线 ${threshold}%`,
              position: 'insideEndTop',
              color: CHART.baseline,
              fontSize: 11,
              distance: 6,
            },
            data: [{ yAxis: threshold }],
          },
        },
      ],
    })
  }

  if (donutRef.value) {
    donutChart?.dispose()
    donutChart = echarts.init(donutRef.value)
    const centerTotal = kpi.block_count || interceptTotal.value
    donutChart.setOption({
      tooltip: {
        trigger: 'item',
        formatter: '{b}: {c} 次 ({d}%)',
        backgroundColor: CHART.tooltipBg,
        borderColor: CHART.grid,
        textStyle: { color: CHART.tooltipText, fontSize: 12 },
      },
      legend: { show: false },
      graphic: [
        {
          type: 'text',
          left: '26%',
          top: '44%',
          style: {
            text: `${centerTotal} 次`,
            font: '700 22px Roboto, sans-serif',
            fill: CHART.centerValue,
            textAlign: 'center',
          },
        },
        {
          type: 'text',
          left: '26%',
          top: '54%',
          style: {
            text: '累计拦截',
            font: '400 12px "Noto Sans SC", sans-serif',
            fill: CHART.centerLabel,
            textAlign: 'center',
          },
        },
      ],
      series: [
        {
          type: 'pie',
          radius: ['40%', '70%'],
          center: ['26%', '50%'],
          data: donutData,
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
}

function onResize() {
  resizeCharts()
}

function openCallChain(item: FlowRow) {
  if (item.job_id) {
    router.push(`/jobs/${item.job_id}`)
    return
  }
  activeFlow.value = item
  callChainDialog.value = true
}

function openCoverage(item: FlowRow) {
  activeFlow.value = item
  coverageDialog.value = true
}

function filterByRepo(fullName: string) {
  repoFilter.value = fullName
}

function demoCallPaths(item: FlowRow) {
  const api = item.api_impact > 0 ? 'POST /api/v1/orders' : 'GET /api/v1/health'
  return [
    `handlers.checkout → services.order → ${api}`,
    `middleware.auth → policies.gate → ${api}`,
    `git diff (${item.commit}) → ast.bfs → ${item.api_impact} 个 API`,
  ]
}

onMounted(async () => {
  const repos = await fetchRepositories()
  repoOptions.value = [
    { title: '全部仓库', value: null },
    ...repos.map((r) => ({ title: r.full_name, value: r.full_name })),
  ]
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
  <div>
    <div class="d-flex flex-wrap align-start justify-space-between gap-4 mb-4">
      <div>
        <h2 class="text-h5 font-weight-medium dashboard-head mb-1">质量驾驶舱</h2>
        <p class="text-body-2 text-medium-emphasis mb-0">
          全链路代码变更风险监控与 CI/CD 质量门禁拦截大盘
        </p>
      </div>
      <div class="dashboard-filters d-flex flex-wrap align-center ga-2">
        <v-select
          v-model="repoFilter"
          class="filter-select filter-select-float"
          :items="repoOptions"
          item-title="title"
          item-value="value"
          variant="solo"
          flat
          density="compact"
          hide-details
          rounded="pill"
          prepend-inner-icon="mdi-source-repository"
          placeholder="全部仓库"
          min-width="220"
          max-width="260"
        />
        <v-btn-toggle v-model="days" class="filter-range m3-segmented" mandatory rounded="pill" density="compact">
          <v-btn :value="1" class="filter-range-btn" variant="text">今天</v-btn>
          <v-btn :value="7" class="filter-range-btn" variant="text">近 7 天</v-btn>
          <v-btn :value="30" class="filter-range-btn" variant="text">近 30 天</v-btn>
          <v-btn :value="90" class="filter-range-btn" variant="text">近 90 天</v-btn>
        </v-btn-toggle>
        <v-tooltip text="刷新大盘数据" location="bottom">
          <template #activator="{ props: tipProps }">
            <v-btn
              v-bind="tipProps"
              class="filter-refresh filter-refresh-float"
              variant="flat"
              rounded="circle"
              :loading="loading"
              aria-label="刷新大盘数据"
              @click="onManualRefresh"
            >
              <v-icon icon="mdi-refresh" :class="{ 'spin-once': refreshSpin && !loading }" />
            </v-btn>
          </template>
        </v-tooltip>
      </div>
    </div>

    <v-row class="mb-3" dense>
      <v-col v-for="(card, index) in kpiCards" :key="card.title" cols="12" sm="6" lg="3">
        <v-card
          class="h-100 kpi-card m3-surface-card"
          :class="index === 0 ? 'kpi-card--hero' : 'kpi-card--muted'"
          rounded="xl"
          :border="false"
        >
          <v-card-text class="position-relative kpi-card-inner">
            <v-avatar size="44" rounded="lg" :style="{ backgroundColor: card.iconBg }" class="kpi-icon">
              <v-icon :icon="card.icon" :color="card.iconColor" size="24" />
            </v-avatar>
            <div class="text-body-2 text-medium-emphasis pe-2">{{ card.title }}</div>
            <div class="kpi-metric mt-2">{{ card.value }}</div>
            <div class="d-flex flex-wrap align-center ga-1 mt-2">
              <v-chip
                v-if="'trendPill' in card && card.trendPill"
                size="x-small"
                variant="flat"
                rounded="pill"
                class="kpi-trend-pill kpi-trend-pill--up"
              >
                {{ card.trendPill }}
              </v-chip>
              <span class="text-caption text-medium-emphasis">{{ card.sub }}</span>
            </div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-row class="mb-3" dense>
      <v-col cols="12" lg="8">
        <v-card class="m3-surface-card" rounded="xl" :border="false">
          <v-card-title class="text-subtitle-1 font-weight-medium">增量代码覆盖率 vs 门禁通过趋势</v-card-title>
          <v-card-text>
            <v-skeleton-loader v-if="loading && !dashboard" type="image" height="290" />
            <div v-show="dashboard" ref="trendRef" class="chart-box" />
          </v-card-text>
        </v-card>
      </v-col>
      <v-col cols="12" lg="4">
        <v-card class="h-100 m3-surface-card chart-card-donut" rounded="xl" :border="false">
          <v-card-title class="text-subtitle-1 font-weight-medium">门禁拦截原因分布</v-card-title>
          <v-card-text class="pt-0 pb-4">
            <v-skeleton-loader v-if="loading && !dashboard" type="image" height="290" />
            <div v-show="dashboard" class="donut-layout">
              <div ref="donutRef" class="donut-chart-canvas" />
              <div class="donut-legend-panel">
                <div
                  v-for="(row, idx) in donutLegendItems"
                  :key="row.name"
                  class="donut-legend-row"
                  :class="{ 'donut-legend-row--divided': idx > 0 }"
                >
                  <div class="donut-legend-label">
                    <span class="donut-legend-dot" :style="{ backgroundColor: row.color }" />
                    <span class="donut-legend-name">{{ row.name }}</span>
                  </div>
                  <span class="donut-legend-stat mono">{{ row.value }} 次 {{ row.pct }}%</span>
                </div>
              </div>
            </div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <section class="flow-section">
      <div class="flow-section-head d-flex flex-wrap align-center justify-space-between gap-2 mb-3">
        <span class="text-subtitle-1 font-weight-medium">最近质量门禁动态</span>
        <div class="d-flex align-center ga-1 flex-wrap">
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
      </div>

      <v-skeleton-loader v-if="loading && !dashboard" type="list-item@4" class="flow-skeleton" />

      <div v-else-if="!(dashboard?.recent_flows?.length)" class="text-center py-10 text-medium-emphasis">
        暂无流水线记录
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

          <div class="flow-row-impact d-none d-sm-flex">
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

          <div class="flow-row-actions d-flex justify-end ga-1">
            <v-btn
              icon="mdi-graph-outline"
              variant="text"
              size="small"
              color="primary"
              aria-label="查看拓扑"
              @click="openCallChain(item)"
            />
            <v-btn
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
    </section>

    <v-dialog v-model="callChainDialog" max-width="560">
      <v-card title="AST 反向调用链预览">
        <v-card-subtitle v-if="activeFlow" class="mono text-body-2">
          {{ activeFlow.repo }} @ {{ activeFlow.commit }}
        </v-card-subtitle>
        <v-card-text>
          <v-alert
            v-if="!activeFlow?.job_id"
            type="info"
            variant="tonal"
            density="compact"
            text="演示流水线：接入 Webhook 后将跳转至 G6 拓扑页。"
            class="mb-3"
          />
          <v-list v-if="activeFlow" density="compact" class="mono text-caption">
            <v-list-item v-for="(line, i) in demoCallPaths(activeFlow)" :key="i" :title="line" />
          </v-list>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="callChainDialog = false">关闭</v-btn>
          <v-btn
            v-if="activeFlow?.job_id"
            color="primary"
            variant="flat"
            @click="router.push(`/jobs/${activeFlow!.job_id}`)"
          >
            打开 G6 拓扑
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="coverageDialog" max-width="520">
      <v-card title="增量覆盖率报告">
        <v-card-subtitle v-if="activeFlow">
          Commit {{ activeFlow.commit }} · 门禁 {{ activeFlow.gate }}
        </v-card-subtitle>
        <v-card-text>
          <h4 class="text-subtitle-2 mb-2">变更命中（高亮示意）</h4>
          <pre class="coverage-snippet mono">@@ checkout_service.py @@
-    if coverage &lt; 0.8:  # legacy
+    if coverage &lt; {{ gateBaseline / 100 }}:
         raise QualityGateError("增量覆盖率不足")
     affected_apis = {{ activeFlow?.api_impact ?? 0 }}</pre>
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
.chart-box {
  height: 300px;
  width: 100%;
}
.chart-card-donut {
  overflow: hidden;
}
.chart-card-donut :deep(.v-card-text) {
  overflow: hidden;
}
.donut-layout {
  display: grid;
  grid-template-columns: minmax(0, 0.84fr) minmax(0, 1.16fr);
  align-items: center;
  column-gap: 6px;
  min-height: 280px;
}
.donut-chart-canvas {
  width: 100%;
  max-width: 172px;
  height: 280px;
  min-width: 0;
  margin-inline: auto;
  justify-self: center;
}
.donut-legend-panel {
  min-width: 0;
  padding-right: 6px;
  padding-left: 14px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 0;
}
.donut-legend-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 0;
}
.donut-legend-row--divided {
  border-top: 1px solid rgb(var(--v-theme-outline));
}
.donut-legend-label {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.donut-legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.donut-legend-name {
  font-size: 13px;
  color: rgb(var(--v-theme-on-surface));
  line-height: 1.3;
  white-space: nowrap;
  opacity: 0.88;
}
.donut-legend-stat {
  font-size: 12px;
  font-weight: 600;
  color: rgb(var(--v-theme-on-surface));
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.m3-surface-card {
  background-color: rgb(var(--v-theme-surface)) !important;
  border: 1px solid rgb(var(--v-theme-outline));
  box-shadow: none;
}
.kpi-card-inner {
  padding-top: 20px !important;
  padding-right: 56px !important;
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
.kpi-icon {
  position: absolute;
  top: 20px;
  right: 20px;
}
.kpi-trend-pill {
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}

.dashboard-filters .filter-select-float :deep(.v-field) {
  min-height: 36px;
  height: 36px;
  border-radius: 9999px;
  background-color: rgb(var(--v-theme-surface)) !important;
  font-size: 13px;
  border: 1px solid rgb(var(--v-theme-outline));
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
  font-size: 13px;
}
.dashboard-filters .m3-segmented {
  background-color: #24282e;
  border: 1px solid rgb(var(--v-theme-outline));
  border-radius: 9999px;
  padding: 2px;
  box-shadow: none;
  height: 36px;
  gap: 2px;
}
.dashboard-filters .m3-segmented :deep(.v-btn) {
  height: 32px !important;
  min-height: 32px;
  font-size: 13px;
  letter-spacing: 0;
  text-transform: none;
  color: rgb(var(--v-theme-secondary));
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  border-radius: 9999px !important;
}
.dashboard-filters .m3-segmented :deep(.v-btn__overlay),
.dashboard-filters .m3-segmented :deep(.v-btn__underlay) {
  opacity: 0 !important;
}
.dashboard-filters .m3-segmented :deep(.v-btn.v-btn--active) {
  background-color: #2c3036 !important;
  color: rgb(var(--v-theme-on-surface)) !important;
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.35);
}
.dashboard-filters .filter-refresh-float {
  width: 36px;
  height: 36px;
  min-width: 36px;
  background-color: rgb(var(--v-theme-surface)) !important;
  border: 1px solid rgb(var(--v-theme-outline));
  box-shadow: none;
}
.dashboard-filters .filter-refresh-float :deep(.v-btn__overlay) {
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
  background-color: #24282e !important;
  border-color: #2c3036 !important;
}
.kpi-card--muted {
  background-color: rgb(var(--v-theme-surface)) !important;
}
.kpi-metric {
  font-family: var(--diffgate-kpi);
  font-size: 36px;
  font-weight: 400;
  line-height: 1.15;
  color: rgb(var(--v-theme-on-surface));
  font-variant-numeric: tabular-nums;
  letter-spacing: -1px;
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
  background: rgba(142, 146, 153, 0.16) !important;
  color: #8e9299 !important;
}
.repo-link--title {
  font-size: 14px;
  font-weight: 500;
}
.gate-progress {
  flex: 1 1 88px;
  max-width: 120px;
  min-width: 72px;
}
.flow-section {
  margin-top: 4px;
}
.flow-section-head {
  padding: 4px 2px 0;
}
.flow-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.flow-row-card {
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr) auto auto auto;
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
  gap: 6px;
  flex-wrap: nowrap;
}
.flow-row-gate {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.gate-pct {
  flex-shrink: 0;
  color: rgb(var(--v-theme-on-surface));
  opacity: 0.88;
}
.flow-row-actions {
  opacity: 0.4;
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
.coverage-snippet {
  background: #24282e;
  border: 1px solid rgb(var(--v-theme-outline));
  border-radius: 12px;
  padding: 12px;
  font-size: 12px;
  line-height: 1.5;
  margin: 0;
  overflow-x: auto;
  color: rgb(var(--v-theme-on-surface));
}
</style>