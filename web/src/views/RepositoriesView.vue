<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  deleteRepository,
  fetchRepoOverview,
  fetchRepositories,
  readApiError,
  reindexRepository,
  triggerRepoAnalysis,
  updateRepository,
} from '@/api/client'
import type { RepoOverviewStats, RepoProvider, RepositoryItem } from '@/api/types'
import { formatLocalDateTime } from '@/utils/datetime'
import Md3LoadState from '@/components/Md3LoadState.vue'

const router = useRouter()
const loading = ref(false)
const keyword = ref('')
const rows = ref<RepositoryItem[]>([])
const overview = ref<RepoOverviewStats | null>(null)
const actionLoading = ref<string | null>(null)
/** 正在重建 AST 的仓库行（菜单关闭后仍可见） */
const reindexingId = ref<string | null>(null)
const deleteDialog = ref(false)
const deleteTarget = ref<RepositoryItem | null>(null)
const kpiTick = ref(0)
const tablePage = ref(1)
const tableItemsPerPage = ref(10)
const tablePerPageOptions = [10, 25, 50]

const tablePageCount = computed(() =>
  Math.max(1, Math.ceil(rows.value.length / tableItemsPerPage.value)),
)
const tableRangeStart = computed(() =>
  rows.value.length === 0 ? 0 : (tablePage.value - 1) * tableItemsPerPage.value + 1,
)
const tableRangeEnd = computed(() =>
  Math.min(tablePage.value * tableItemsPerPage.value, rows.value.length),
)

const canGoPrev = computed(() => tablePage.value > 1)
const canGoNext = computed(() => tablePage.value < tablePageCount.value)

function goFirstPage() {
  tablePage.value = 1
}
function goPrevPage() {
  tablePage.value = Math.max(1, tablePage.value - 1)
}
function goNextPage() {
  tablePage.value = Math.min(tablePageCount.value, tablePage.value + 1)
}
function goLastPage() {
  tablePage.value = tablePageCount.value
}

function isLastTableRow(item: RepositoryItem) {
  const idx = rows.value.findIndex((r) => r.id === item.id)
  return idx >= 0 && idx === rows.value.length - 1
}

function splitRepoFullName(full: string) {
  const i = full.lastIndexOf('/')
  if (i <= 0) return { owner: '', project: full }
  return { owner: full.slice(0, i), project: full.slice(i + 1) }
}

function repoRowProps(data: { item: RepositoryItem }) {
  return {
    class: data.item.enabled ? 'repo-data-row' : 'repo-data-row repo-data-row--disabled',
  }
}

watch(tableItemsPerPage, () => {
  tablePage.value = 1
})
watch(tablePageCount, (n) => {
  if (tablePage.value > n) tablePage.value = n
})

const paginationNavButtons = computed(() => [
  {
    id: 'first',
    label: '第一页',
    icon: 'mdi-chevron-double-left',
    disabled: !canGoPrev.value,
    onClick: goFirstPage,
  },
  {
    id: 'prev',
    label: '上一页',
    icon: 'mdi-chevron-left',
    disabled: !canGoPrev.value,
    onClick: goPrevPage,
  },
  {
    id: 'next',
    label: '下一页',
    icon: 'mdi-chevron-right',
    disabled: !canGoNext.value,
    onClick: goNextPage,
  },
  {
    id: 'last',
    label: '最后一页',
    icon: 'mdi-chevron-double-right',
    disabled: !canGoNext.value,
    onClick: goLastPage,
  },
])

type SnackbarVariant = 'success' | 'error' | 'info'
const snackbar = ref<{ show: boolean; text: string; variant: SnackbarVariant; loading?: boolean }>({
  show: false,
  text: '',
  variant: 'success',
  loading: false,
})

function notify(text: string, variant: SnackbarVariant = 'success') {
  snackbar.value = { show: true, text, variant, loading: false }
}

function notifyInProgress(text: string) {
  snackbar.value = { show: true, text, variant: 'info', loading: true }
}

function isRowReindexing(id: string) {
  return reindexingId.value === id
}

function isRowAnalyzeLoading(id: string) {
  return actionLoading.value === `${id}:analyze`
}

const repoRowMenuProps = {
  contentClass: 'repo-row-action-menu',
  elevation: 12,
  rounded: 'lg',
  minWidth: 220,
  maxWidth: 260,
} as const

function formatIndexedAt(iso: string | null | undefined) {
  const full = formatLocalDateTime(iso)
  if (!full || full === '—') return '—'
  const m = full.match(/^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})/)
  return m ? `${m[1]} ${m[2]}` : full
}

const providerLabel: Record<RepoProvider, string> = {
  github: 'GitHub',
  gitlab: 'GitLab',
  local: '本地',
}

const headers = [
  {
    title: '仓库',
    key: 'full_name',
    width: 248,
    minWidth: 220,
    sortable: true,
    headerProps: { class: 'repo-col-name' },
    cellProps: { class: 'repo-col-name' },
  },
  { title: '来源', key: 'provider', width: 88 },
  { title: '默认分支', key: 'default_branch', width: 110 },
  { title: 'AST 节点规模', key: 'ast_scale', minWidth: 172, sortable: false },
  { title: '关联用例集', key: 'test_suite_id', minWidth: 120 },
  { title: '质量门禁', key: 'coverage_threshold', width: 130, sortable: false },
  { title: '分析次数', key: 'job_count', width: 96, align: 'center' as const },
  { title: '启用', key: 'enabled', width: 88, sortable: false },
  { title: 'Webhook', key: 'webhook_enabled', width: 96, sortable: false },
  { title: '最近索引', key: 'last_indexed_at', minWidth: 156, width: 156 },
  {
    title: '操作',
    key: 'actions',
    sortable: false,
    width: 88,
    align: 'center' as const,
    headerProps: { class: 'repo-col-actions' },
    cellProps: { class: 'repo-col-actions' },
  },
]

const astTotals = computed(() =>
  rows.value.reduce(
    (acc, r) => {
      acc.methods += r.ast_method_count ?? 0
      acc.apis += r.ast_api_count ?? 0
      return acc
    },
    { methods: 0, apis: 0 },
  ),
)

/** 无匹配结果时仍需保留搜索框，便于改关键词或清空 */
const showRepoSearch = computed(
  () => rows.value.length > 0 || keyword.value.trim().length > 0 || (overview.value?.repo_count ?? 0) > 0,
)

const repoCountForTitle = computed(() => overview.value?.repo_count ?? rows.value.length)

const kpiCards = computed(() => {
  const o = overview.value
  void kpiTick.value
  const { methods, apis } = astTotals.value
  return [
    {
      title: '已接入代码仓库数',
      value: o?.repo_count ?? 0,
      sub: `已构建 ${o?.indexed_repo_count ?? 0} 个 · ${methods} 方法 / ${apis} 接口`,
      icon: 'mdi-source-repository',
      iconBg: 'rgba(66, 133, 244, 0.12)',
      iconColor: '#8ab4f8',
      accent: '#8ab4f8',
    },
    {
      title: '累计精准分析次数',
      value: o?.analysis_total ?? 0,
      sub: `平均分析耗时 ${o?.avg_analysis_seconds ?? 0}s`,
      icon: 'mdi-filter-variant',
      iconBg: 'rgba(52, 168, 83, 0.12)',
      iconColor: '#81c995',
      accent: '#81c995',
    },
    {
      title: '累计拦截高危变更',
      value: o?.high_risk_blocked ?? 0,
      sub: '增量覆盖率不达标阻断',
      icon: 'mdi-shield-alert-outline',
      iconBg: 'rgba(234, 67, 53, 0.12)',
      iconColor: '#f28b82',
      accent: '#f28b82',
    },
    {
      title: '回归测试耗时节省',
      value: `${o?.regression_time_saved_pct ?? 0}%`,
      sub: o?.regression_hint ?? '暂无分析任务',
      icon: 'mdi-timer-outline',
      iconBg: 'rgba(253, 214, 99, 0.12)',
      iconColor: '#fdd663',
      accent: '#fdd663',
    },
  ]
})

async function fetchListAndOverview() {
  const [list, stats] = await Promise.all([
    fetchRepositories(keyword.value.trim() || undefined),
    fetchRepoOverview(),
  ])
  rows.value = list
  overview.value = stats
  kpiTick.value++
}

async function load() {
  loading.value = true
  try {
    await fetchListAndOverview()
  } finally {
    loading.value = false
  }
}

/** 增删改/索引后静默刷新 KPI 与列表，避免整表闪烁 */
async function refreshAfterMutation() {
  try {
    await fetchListAndOverview()
  } catch {
    notify('数据刷新失败', 'error')
  }
}

function openCreate() {
  void router.push({ name: 'repository-create' })
}

function openEdit(row: RepositoryItem) {
  void router.push({ name: 'repository-edit', params: { id: row.id } })
}

function askDelete(row: RepositoryItem) {
  deleteTarget.value = row
  deleteDialog.value = true
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  try {
    await deleteRepository(deleteTarget.value.id)
    deleteDialog.value = false
    deleteTarget.value = null
    await refreshAfterMutation()
    notify('仓库已移除，看板数据已更新')
  } catch {
    notify('删除失败', 'error')
  }
}

async function toggleEnabled(row: RepositoryItem, enabled: boolean | null) {
  if (enabled === null) return
  row.enabled = enabled
  try {
    await updateRepository(row.id, { enabled })
    notify(enabled ? '已启用' : '已停用')
  } catch {
    row.enabled = !enabled
    notify('更新失败', 'error')
  }
}

async function onReindex(row: RepositoryItem) {
  const key = `${row.id}:reindex`
  actionLoading.value = key
  reindexingId.value = row.id
  notifyInProgress(`正在重建 AST 索引：${row.full_name}（克隆并扫描，约需数十秒）…`)
  try {
    const res = await reindexRepository(row.id)
    await refreshAfterMutation()
    const m = res.stats?.method_count ?? res.repository.ast_method_count
    const a = res.stats?.api_count ?? res.repository.ast_api_count
    notify(`AST 索引完成：${m} 方法 · ${a} 接口`)
  } catch (err) {
    if (import.meta.env.DEV) console.error('reindex failed', err)
    notify(
      readApiError(err, '索引失败，请检查 Clone 地址、默认分支，或确认已开启「启用分析」'),
      'error',
    )
  } finally {
    actionLoading.value = null
    reindexingId.value = null
  }
}

async function onAnalyze(row: RepositoryItem) {
  actionLoading.value = row.id + ':analyze'
  try {
    const res = await triggerRepoAnalysis(row.id)
    notify('已触发 Diff 分析')
    router.push(`/jobs/${res.job_id}`)
  } catch {
    notify('触发分析失败', 'error')
  } finally {
    actionLoading.value = null
  }
}

let searchDebounce: number | undefined

watch(keyword, () => {
  if (searchDebounce) window.clearTimeout(searchDebounce)
  searchDebounce = window.setTimeout(() => {
    void load()
  }, 320)
})

onMounted(async () => {
  await load()
})
</script>

<template>
  <div class="repo-page">
    <header class="repo-page-head">
      <h2 class="repo-page-title">
        仓库管理
        <span class="repo-page-title-count">({{ repoCountForTitle }})</span>
      </h2>
      <div class="repo-toolbar">
        <v-text-field
          v-if="showRepoSearch"
          v-model="keyword"
          class="repo-search-field"
          density="compact"
          variant="solo"
          flat
          hide-details
          rounded="0"
          placeholder="搜索 group/project"
          prepend-inner-icon="mdi-magnify"
          clearable
          @keyup.enter="load"
        />
        <v-btn
          class="text-none cta-new-analysis cta-new-analysis--ghost"
          color="primary"
          size="small"
          variant="outlined"
          rounded="pill"
          prepend-icon="mdi-plus"
          @click="openCreate"
        >
          添加仓库
        </v-btn>
      </div>
    </header>

    <div class="repo-kpi-grid" :class="{ 'repo-kpi-grid--pulse': kpiTick > 0 }">
      <v-card
        v-for="card in kpiCards"
        :key="card.title"
        class="h-100 kpi-card repo-kpi-card"
        rounded="xl"
        :border="false"
      >
        <span class="repo-kpi-accent" :style="{ backgroundColor: card.accent }" aria-hidden="true" />
        <v-card-text class="repo-kpi-inner d-flex flex-column">
          <div class="d-flex align-start justify-space-between gap-2 mb-2">
            <div class="text-body-2 repo-kpi-title">{{ card.title }}</div>
            <v-avatar size="40" rounded="lg" :style="{ backgroundColor: card.iconBg }">
              <v-icon :icon="card.icon" :color="card.iconColor" size="22" />
            </v-avatar>
          </div>
          <div class="kpi-value text-h4">{{ card.value }}</div>
          <div class="repo-kpi-sub-slot">
            <div
              class="text-caption repo-kpi-sub"
              :class="{ 'repo-kpi-sub--warn': 'subWarn' in card && card.subWarn }"
            >
              {{ card.sub }}
            </div>
          </div>
        </v-card-text>
      </v-card>
    </div>

    <v-card class="repo-table-card" rounded="xl" :border="false">
      <v-progress-linear
        v-if="reindexingId"
        class="repo-table-top-progress"
        indeterminate
        color="primary"
        height="2"
      />
      <v-card-text v-if="loading && rows.length === 0" class="repo-table-loading pa-6">
        <Md3LoadState skeleton-type="table-row@6" label="加载仓库列表" />
      </v-card-text>
      <template v-else-if="!loading && rows.length === 0">
        <v-card-text class="repo-empty-panel">
          <div class="repo-empty-module">
            <div class="repo-empty-module__block">
              <div class="repo-empty-module__icon" aria-hidden="true">
                <v-icon icon="mdi-source-repository" size="28" />
              </div>
              <div class="repo-empty-module__text">
                <p class="repo-empty-module__title">
                  {{ keyword.trim() ? '未找到匹配的仓库' : '暂无接入的代码仓库' }}
                </p>
                <p class="repo-empty-module__desc">
                  {{
                    keyword.trim()
                      ? `没有与「${keyword.trim()}」相符的 group/project，请修改关键词或清空搜索。`
                      : '配置 Git 地址，自动构建 AST 静态调用链图谱。'
                  }}
                </p>
              </div>
            </div>
            <div class="repo-empty-module__actions">
              <v-btn
                class="text-none cta-new-analysis cta-new-analysis--ghost"
                color="primary"
                size="small"
                variant="outlined"
                rounded="pill"
                prepend-icon="mdi-plus"
                @click="openCreate"
              >
                添加仓库
              </v-btn>
            </div>
          </div>
        </v-card-text>
      </template>
      <v-data-table
        v-else
        :headers="headers"
        :items="rows"
        :loading="loading"
        item-value="id"
        hover
        :row-props="repoRowProps"
        v-model:page="tablePage"
        v-model:items-per-page="tableItemsPerPage"
        class="repo-table"
        :items-per-page-options="tablePerPageOptions"
      >
        <template #bottom>
          <div class="repo-pagination-wrapper">
            <div class="repo-pagination-left">
              <span class="repo-pagination-label">每页</span>
              <v-select
                v-model="tableItemsPerPage"
                :items="tablePerPageOptions"
                density="compact"
                hide-details
                variant="solo"
                flat
                class="page-size-select"
                menu-icon="mdi-menu-down"
              />
            </div>
            <div class="repo-pagination-right">
              <span class="page-text">
                {{ tableRangeStart }}-{{ tableRangeEnd }} 共 {{ rows.length }}
              </span>
              <div class="page-buttons" role="navigation" aria-label="表格分页">
                <v-btn
                  v-for="btn in paginationNavButtons"
                  :key="btn.id"
                  class="page-btn"
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
        </template>
        <template #item.full_name="{ item }">
          <v-tooltip :text="item.full_name" location="top" :open-delay="280">
            <template #activator="{ props: tipProps }">
              <div v-bind="tipProps" class="repo-name-stack" :title="item.full_name">
                <span class="repo-name-project font-weight-medium">{{
                  splitRepoFullName(item.full_name).project
                }}</span>
                <span v-if="splitRepoFullName(item.full_name).owner" class="repo-name-owner mono">{{
                  splitRepoFullName(item.full_name).owner
                }}</span>
              </div>
            </template>
          </v-tooltip>
        </template>
        <template #item.provider="{ item }">
          {{ providerLabel[item.provider as RepoProvider] }}
        </template>
        <template #item.default_branch="{ item }">
          <span class="mono text-caption">{{ item.default_branch }}</span>
        </template>
        <template #item.ast_scale="{ item }">
          <span
            v-if="isRowReindexing(item.id)"
            class="repo-ast-scale repo-ast-scale--loading d-inline-flex align-center ga-2"
          >
            <v-progress-circular indeterminate size="16" width="2" color="primary" aria-hidden="true" />
            <span>索引中…</span>
          </span>
          <span v-else class="repo-ast-scale mono">
            {{ item.ast_method_count }} 方法 · {{ item.ast_api_count }} 接口
          </span>
        </template>
        <template #item.test_suite_id="{ item }">
          <span class="text-truncate d-inline-block" style="max-width: 140px">
            {{ item.test_suite_id || '—' }}
          </span>
        </template>
        <template #item.coverage_threshold="{ item }">
          <v-chip size="small" variant="flat" class="repo-tone-chip repo-tone-chip--warn">
            增量覆盖率 ≥ {{ item.coverage_threshold }}%
          </v-chip>
        </template>
        <template #item.job_count="{ item }">
          {{ item.job_count ?? 0 }}
        </template>
        <template #item.enabled="{ item }">
          <div class="repo-table-cell repo-table-cell--control">
            <v-switch
              :model-value="item.enabled"
              color="primary"
              density="comfortable"
              hide-details
              inset
              class="repo-table-switch"
              @update:model-value="(v) => toggleEnabled(item, v)"
            />
          </div>
        </template>
        <template #item.webhook_enabled="{ item }">
          <span
            class="repo-webhook-status"
            :class="item.webhook_enabled ? 'repo-webhook-status--on' : 'repo-webhook-status--off'"
          >
            <span v-if="item.webhook_enabled" class="repo-webhook-dot" aria-hidden="true" />
            {{ item.webhook_enabled ? '开' : '关' }}
          </span>
        </template>
        <template #item.last_indexed_at="{ item }">
          <span
            v-if="isRowReindexing(item.id)"
            class="repo-index-time mono repo-index-time--loading text-medium-emphasis"
          >
            重建中
          </span>
          <span v-else class="repo-index-time mono" :title="item.last_indexed_at || undefined">
            {{ formatIndexedAt(item.last_indexed_at) }}
          </span>
        </template>
        <template #item.actions="{ item }">
          <div class="repo-table-cell repo-table-cell--actions">
            <v-menu
              :location="isLastTableRow(item) ? 'top end' : 'bottom end'"
              :offset="8"
              scroll-strategy="reposition"
              :close-on-content-click="true"
              :z-index="2500"
              :menu-props="repoRowMenuProps"
            >
              <template #activator="{ props }">
                <v-btn
                  v-bind="props"
                  class="repo-row-action"
                  icon="mdi-dots-vertical"
                  variant="text"
                  size="small"
                  aria-label="仓库操作"
                  :loading="isRowReindexing(item.id) || isRowAnalyzeLoading(item.id)"
                  :disabled="isRowReindexing(item.id)"
                />
              </template>
              <v-list class="repo-action-menu" density="default" nav>
                <v-list-item
                  class="repo-action-menu__item"
                  rounded="lg"
                  title="重建 AST 索引"
                  :disabled="Boolean(reindexingId)"
                  :loading="isRowReindexing(item.id)"
                  @click="onReindex(item)"
                >
                  <template #prepend>
                    <v-icon icon="mdi-database-refresh" size="18" class="repo-action-menu__icon" />
                  </template>
                </v-list-item>
                <v-list-item
                  class="repo-action-menu__item"
                  rounded="lg"
                  title="手动 Diff 分析"
                  :disabled="actionLoading === item.id + ':analyze'"
                  @click="onAnalyze(item)"
                >
                  <template #prepend>
                    <v-icon icon="mdi-source-branch" size="18" class="repo-action-menu__icon" />
                  </template>
                </v-list-item>
                <v-list-item
                  class="repo-action-menu__item"
                  rounded="lg"
                  title="编辑"
                  @click="openEdit(item)"
                >
                  <template #prepend>
                    <v-icon icon="mdi-pencil-outline" size="18" class="repo-action-menu__icon" />
                  </template>
                </v-list-item>
                <div class="repo-action-menu__separator" role="separator" aria-hidden="true" />
                <v-list-item
                  class="repo-action-menu__item repo-action-menu__item--danger"
                  rounded="lg"
                  title="删除"
                  @click="askDelete(item)"
                >
                  <template #prepend>
                    <v-icon icon="mdi-delete-outline" size="18" class="repo-action-menu__icon" />
                  </template>
                </v-list-item>
              </v-list>
            </v-menu>
          </div>
        </template>
      </v-data-table>
    </v-card>



    <v-dialog v-model="deleteDialog" max-width="400">
      <v-card title="删除仓库">
        <v-card-text>
          确定删除 <strong>{{ deleteTarget?.full_name }}</strong>？此操作不可恢复。
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="deleteDialog = false">取消</v-btn>
          <v-btn color="error" variant="flat" @click="confirmDelete">删除</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar
      v-model="snackbar.show"
      location="bottom"
      position="sticky"
      :timeout="snackbar.loading ? -1 : snackbar.variant === 'error' ? 9000 : 4000"
      :rounded="snackbar.variant === 'error' ? 'lg' : 'pill'"
      elevation="6"
      :color="snackbar.variant === 'error' ? 'error' : undefined"
      :class="[
        'feedback-snackbar',
        snackbar.variant === 'success' && 'feedback-snackbar--success',
        snackbar.variant === 'error' && 'feedback-snackbar--error',
        snackbar.variant === 'info' && 'feedback-snackbar--info',
      ]"
    >
      <div class="d-flex align-start ga-2 px-1 feedback-snackbar__content">
        <v-progress-circular
          v-if="snackbar.loading"
          indeterminate
          size="20"
          width="2"
          color="primary"
          class="feedback-snackbar__icon"
        />
        <v-icon
          v-else
          :icon="snackbar.variant === 'error' ? 'mdi-alert-circle-outline' : 'mdi-check-circle-outline'"
          size="small"
          class="feedback-snackbar__icon"
        />
        <span class="text-body-2 feedback-snackbar__text">{{ snackbar.text }}</span>
      </div>
    </v-snackbar>
  </div>
</template>

<style scoped>
.repo-detect-hint {
  margin: 4px 0 0;
  font-size: 0.8125rem;
  color: #4caf50;
  line-height: 1.35;
}
.repo-monorepo-hint {
  font-size: 0.875rem;
}
.repo-type-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.repo-type-select {
  flex: 1;
  min-width: 0;
  width: 100%;
}
.repo-type-selection {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: 100%;
  min-width: 0;
}
.repo-type-selection__text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.repo-type-selection__icon {
  flex-shrink: 0;
  opacity: 0.92;
}
.repo-redetect-btn {
  margin-top: 4px;
  flex-shrink: 0;
}
.repo-page {
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
}
.repo-page-head {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  width: 100%;
  box-sizing: border-box;
  padding: 16px 0;
  margin-bottom: 0 !important;
  border-bottom: 1px solid #2a2a2a;
}
@media (max-width: 720px) {
  .repo-page-head {
    flex-wrap: wrap;
  }
}
.repo-kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 24px;
  width: 100%;
  margin-top: 24px;
  margin-bottom: 24px;
  box-sizing: border-box;
}
@media (max-width: 1280px) {
  .repo-kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 600px) {
  .repo-kpi-grid {
    grid-template-columns: 1fr;
  }
}
.repo-kpi-grid--pulse .repo-kpi-card {
  transition:
    box-shadow 0.35s ease,
    border-color 0.35s ease;
}
.repo-page-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  flex: 0 1 auto;
  min-width: 0;
  font-size: 18px;
  font-weight: 700;
  line-height: 1.2;
  color: #f3f4f6;
  white-space: nowrap;
}
.repo-page-title-count {
  font-size: 14px;
  font-weight: 500;
  color: #888;
  letter-spacing: 0.02em;
}
.repo-toolbar {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex: 0 0 auto;
  margin-left: auto;
}
.repo-search-field {
  flex: 0 0 260px;
  width: 260px;
  max-width: min(260px, 42vw);
}
.repo-search-field :deep(.v-field) {
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
  background: #1a1a1a !important;
  box-shadow: none;
  font-size: 13px;
  min-height: 36px;
  height: 36px;
  border-radius: 6px !important;
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease,
    background 0.18s ease;
}
.repo-search-field :deep(.v-field:hover) {
  border-color: rgba(59, 130, 246, 0.45) !important;
}
.repo-search-field :deep(.v-field--focused) {
  border-color: #3b82f6 !important;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
}
.repo-search-field :deep(.v-field__input) {
  min-height: 36px;
  padding-top: 0;
  padding-bottom: 0;
  padding-inline: 8px 10px;
}
.repo-search-field :deep(.v-field__prepend-inner) {
  padding-inline-start: 10px;
}
.repo-search-field :deep(.v-field__prepend-inner .v-icon) {
  opacity: 0.9;
  color: rgba(255, 255, 255, 0.65);
  font-size: 18px;
}
.repo-search-field :deep(.v-field__outline) {
  opacity: 0 !important;
}
.repo-toolbar .cta-new-analysis,
.repo-empty-module__actions .cta-new-analysis {
  flex-shrink: 0;
}
.cta-new-analysis :deep(.v-btn__prepend .v-icon) {
  font-size: 18px;
}
.repo-table-card {
  background-color: rgb(var(--v-theme-surface)) !important;
  border: 1px solid #2a2e35 !important;
  box-shadow: none !important;
  width: 100%;
  box-sizing: border-box;
  overflow: visible;
}
.repo-kpi-card {
  position: relative;
  overflow: hidden;
  background-color: #1e1e1e !important;
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.24);
}
.repo-kpi-accent {
  position: absolute;
  left: 0;
  top: 14px;
  bottom: 14px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  opacity: 0.88;
}
.repo-kpi-inner {
  padding: 20px 20px 18px 22px !important;
  min-height: 156px;
}
.repo-kpi-sub-slot {
  margin-top: auto;
  min-height: 44px;
  display: flex;
  align-items: flex-end;
  padding-top: 10px;
}
.repo-kpi-title {
  opacity: 0.72;
}
.repo-kpi-sub {
  line-height: 1.45;
  letter-spacing: 0.02em;
  font-size: 13px !important;
  color: rgba(255, 255, 255, 0.62);
}
.repo-table :deep(thead th) {
  color: rgba(255, 255, 255, 0.6) !important;
  font-weight: 600 !important;
  font-size: 13px !important;
  white-space: nowrap;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1) !important;
  padding-top: 14px !important;
  padding-bottom: 14px !important;
  background: rgba(255, 255, 255, 0.02);
}
.repo-table :deep(thead th),
.repo-table :deep(.v-data-table__td) {
  text-align: center !important;
}
.repo-table :deep(thead th .v-data-table-header__content) {
  padding-inline: 0;
  justify-content: center !important;
}
.repo-table :deep(.v-data-table__td-content) {
  display: flex;
  justify-content: center;
  align-items: center;
  width: 100%;
  min-width: 0;
}
.repo-table :deep(.repo-col-name) {
  width: 248px !important;
  min-width: 220px !important;
  max-width: 280px !important;
  overflow: hidden;
}
.repo-table :deep(.repo-col-name .v-data-table__td-content) {
  overflow: hidden;
  min-width: 0;
}
.repo-table :deep(thead th:first-child),
.repo-table :deep(.v-data-table__td:first-child),
.repo-table :deep(thead th:last-child),
.repo-table :deep(.v-data-table__td:last-child) {
  padding-inline: 16px !important;
}
.repo-table :deep(tbody tr) {
  border-bottom: none;
}
.repo-table :deep(.v-data-table__td) {
  border-bottom: 1px solid rgba(255, 255, 255, 0.05) !important;
  box-shadow: none !important;
}
.repo-table :deep(tbody tr:last-child .v-data-table__td) {
  border-bottom: none !important;
}
.repo-table :deep(.v-table__wrapper) {
  border-bottom: none;
}
.repo-table :deep(tbody td),
.repo-table :deep(.v-data-table__td) {
  vertical-align: middle !important;
  padding-top: 18px !important;
  padding-bottom: 18px !important;
  color: rgba(255, 255, 255, 0.88) !important;
  font-size: 13px;
}
.repo-table :deep(tbody tr.repo-data-row:hover > .v-data-table__td) {
  color: rgba(255, 255, 255, 0.94) !important;
}
.repo-table :deep(tr.repo-data-row--disabled > .v-data-table__td) {
  color: rgba(255, 255, 255, 0.38) !important;
}
.repo-table :deep(.v-tooltip__activator) {
  display: block;
  max-width: 100%;
  opacity: 1 !important;
  color: inherit;
}
.repo-table-switch :deep(.v-switch__track) {
  opacity: 1 !important;
  background-color: rgba(255, 255, 255, 0.08) !important;
}
.repo-table-switch :deep(.v-switch__thumb) {
  background-color: #4a4f58 !important;
  color: #4a4f58 !important;
}
.repo-table-switch.v-input--dirty :deep(.v-switch__track) {
  background-color: rgba(138, 180, 248, 0.52) !important;
}
.repo-table-switch.v-input--dirty :deep(.v-switch__thumb) {
  background-color: #8ab4f8 !important;
  color: #8ab4f8 !important;
}
.repo-name-stack {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  min-width: 0;
  max-width: 100%;
  line-height: 1.3;
  text-align: center;
  cursor: default;
}
.repo-name-project {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.94) !important;
}
.repo-name-owner {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  color: rgba(255, 255, 255, 0.48);
}
.repo-table :deep(tr.repo-data-row--disabled .repo-name-project) {
  color: rgba(255, 255, 255, 0.38) !important;
}
.repo-table :deep(tr.repo-data-row--disabled .repo-name-owner) {
  color: rgba(255, 255, 255, 0.28) !important;
}
.repo-ast-scale {
  display: inline-block;
  white-space: nowrap;
  font-size: 13px;
  letter-spacing: 0.01em;
  color: rgba(255, 255, 255, 0.78);
}
.repo-index-time {
  display: inline-block;
  white-space: nowrap;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: rgba(255, 255, 255, 0.5);
}
.repo-webhook-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
}
.repo-webhook-status--on {
  color: #81c995;
}
.repo-webhook-status--off {
  color: rgba(255, 255, 255, 0.42);
}
.repo-webhook-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #81c995;
  box-shadow: 0 0 0 2px rgba(129, 201, 149, 0.22);
  flex-shrink: 0;
}
.repo-table-cell--control,
.repo-table-cell--actions {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 40px;
  width: 100%;
}
.repo-table-cell--actions {
  justify-content: center;
  width: 100%;
  margin-inline: auto;
}
.repo-table :deep(.repo-col-actions .repo-table-cell--actions) {
  justify-content: center;
}
.repo-tone-chip {
  font-weight: 500;
  letter-spacing: 0.01em;
  border-radius: 4px !important;
  padding: 4px 10px !important;
  height: auto !important;
}
.repo-tone-chip :deep(.v-chip__underlay),
.repo-tone-chip :deep(.v-chip__overlay) {
  opacity: 0 !important;
}
.repo-tone-chip--warn {
  background: rgba(245, 158, 11, 0.15) !important;
  color: #fbbf24 !important;
  border-radius: 6px !important;
  font-size: 12px !important;
}
.repo-tone-chip--muted {
  background: rgba(142, 146, 153, 0.14) !important;
  color: #9aa0a6 !important;
}
.repo-row-action {
  width: 40px !important;
  height: 40px !important;
  border-radius: 50% !important;
  color: rgba(255, 255, 255, 0.52) !important;
  background: transparent !important;
}
.repo-row-action:hover {
  background: rgba(255, 255, 255, 0.08) !important;
  color: rgba(255, 255, 255, 0.88) !important;
}
.repo-row-action :deep(.v-btn__overlay),
.repo-row-action :deep(.v-btn__underlay) {
  opacity: 0 !important;
}
.repo-table :deep(.v-data-table-footer) {
  padding: 0 !important;
  border: none !important;
  background: transparent !important;
}
.repo-table :deep(.v-divider) {
  display: none !important;
}
.repo-pagination-wrapper {
  border-top: 1px solid rgba(255, 255, 255, 0.05) !important;
  padding: 16px 24px 20px !important;
  margin-top: 4px;
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 12px 16px;
  background-color: transparent;
}
.repo-pagination-left {
  display: flex;
  align-items: center;
  gap: 10px;
  color: rgba(255, 255, 255, 0.6);
  font-size: 13px;
}
.repo-pagination-right {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-inline-start: auto;
}
.page-text {
  color: rgba(255, 255, 255, 0.5);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.page-size-select {
  width: 96px;
  flex: 0 0 96px;
}
.page-size-select :deep(.v-field) {
  min-height: 34px !important;
  height: 34px !important;
  background-color: rgba(255, 255, 255, 0.05) !important;
  border: 1px solid rgba(255, 255, 255, 0.14) !important;
  border-radius: 8px;
  font-size: 13px;
}
.page-size-select :deep(.v-field__input) {
  min-height: 34px;
  padding: 0 14px !important;
  padding-top: 0;
  padding-bottom: 0;
  justify-content: center;
}
.page-size-select :deep(.v-field__outline),
.page-size-select :deep(.v-field__overlay) {
  opacity: 0 !important;
}
.page-buttons {
  display: flex;
  align-items: center;
  gap: 6px;
}
.repo-pagination-wrapper .page-btn {
  width: 32px !important;
  min-width: 32px !important;
  height: 32px !important;
  border-radius: 999px;
  color: rgba(255, 255, 255, 0.6) !important;
  background: transparent !important;
  transition:
    background 0.2s ease,
    color 0.2s ease;
}
.repo-pagination-wrapper .page-btn :deep(.v-btn__overlay),
.repo-pagination-wrapper .page-btn :deep(.v-btn__underlay) {
  opacity: 0 !important;
}
.repo-pagination-wrapper .page-btn :deep(.v-icon) {
  color: inherit !important;
  opacity: 1 !important;
}
.repo-pagination-wrapper .page-btn:hover:not(.v-btn--disabled) {
  background-color: rgba(255, 255, 255, 0.08) !important;
  color: #ffffff !important;
}
.repo-pagination-wrapper .page-btn.v-btn--disabled {
  color: rgba(255, 255, 255, 0.2) !important;
  opacity: 1 !important;
}
.repo-pagination-wrapper .page-btn.v-btn--disabled :deep(.v-icon) {
  color: rgba(255, 255, 255, 0.2) !important;
}
.repo-kpi-sub--warn {
  color: #f28b82;
  opacity: 0.92;
}
.repo-empty-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 200px;
  max-height: 320px;
  padding: 28px 24px !important;
  box-sizing: border-box;
}
.repo-empty-module {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 24px;
  width: 100%;
  max-width: 28rem;
  margin-inline: auto;
  text-align: center;
}
.repo-empty-module__block {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  width: 100%;
}
.repo-empty-module__text {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  width: 100%;
  max-width: 26rem;
}
.repo-empty-module__icon {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(66, 133, 244, 0.15);
  color: #8ab4f8;
}
.repo-empty-module__title {
  margin: 0;
  font-size: 1.0625rem;
  font-weight: 600;
  color: #e8eaed;
  line-height: 1.35;
}
.repo-empty-module__desc {
  margin: 0;
  font-size: 0.8125rem;
  line-height: 1.55;
  color: rgba(255, 255, 255, 0.6);
  max-width: 400px;
  width: 100%;
}
.repo-empty-module__actions {
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
}
.repo-kpi-card .kpi-value {
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.92);
}


.feedback-snackbar--success :deep(.v-snackbar__wrapper) {
  background-color: #188038 !important;
  color: #fff;
  min-width: min(520px, 92vw);
  padding-inline: 8px;
}
.feedback-snackbar--error :deep(.v-snackbar__wrapper) {
  max-width: min(560px, 92vw);
  padding: 12px 16px !important;
}
.feedback-snackbar--info :deep(.v-snackbar__wrapper) {
  background-color: #2a2f36 !important;
  color: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(138, 180, 248, 0.35);
  min-width: min(420px, 92vw);
  max-width: min(560px, 92vw);
}
.repo-table-top-progress {
  position: sticky;
  top: 0;
  z-index: 2;
}
.repo-ast-scale--loading {
  color: rgba(138, 180, 248, 0.92);
  font-size: 13px;
}
.repo-index-time--loading {
  color: rgba(138, 180, 248, 0.85) !important;
}
.feedback-snackbar__content {
  width: 100%;
}
.feedback-snackbar__icon {
  flex-shrink: 0;
  margin-top: 2px;
}
.feedback-snackbar__text {
  line-height: 1.45;
  text-align: left;
  white-space: normal;
  word-break: break-word;
}

.repo-dialog :deep(.v-overlay__content) {
  border-radius: 16px;
  overflow: visible;
}
.repo-dialog-card {
  display: flex;
  flex-direction: column;
  max-height: min(90vh, 760px);
  border-radius: 16px !important;
  overflow: hidden;
  background: var(--dg-surface-modal, #1e1e1e) !important;
}
.dg-dark-form-surface.repo-dialog-card {
  background: var(--dg-surface-modal, #1e1e1e) !important;
}
.repo-dialog-title,
.repo-dialog-title-divider,
.repo-dialog-footer-divider,
.repo-dialog-actions {
  flex-shrink: 0;
}
.repo-dialog-title {
  position: sticky;
  top: 0;
  z-index: 3;
  padding: 20px 24px 16px !important;
  font-size: 1.25rem !important;
  font-weight: 700 !important;
  letter-spacing: 0.01em;
  color: rgba(255, 255, 255, 0.95) !important;
  line-height: 1.3;
  background: var(--dg-surface-modal, #1e1e1e);
}
.repo-dialog-title-divider {
  position: sticky;
  top: 56px;
  z-index: 3;
  background: var(--dg-surface-modal, #1e1e1e);
}
.repo-dialog-title-divider,
.repo-dialog-footer-divider {
  border-color: rgba(255, 255, 255, 0.08) !important;
  opacity: 1;
}
.repo-dialog-footer-divider {
  border-color: rgba(255, 255, 255, 0.05) !important;
}
.repo-dialog-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
  padding: 16px 24px 12px;
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 255, 255, 0.2) transparent;
}
.repo-dialog-scroll::-webkit-scrollbar {
  width: 4px;
}
.repo-dialog-scroll::-webkit-scrollbar-track {
  background: transparent;
}
.repo-dialog-scroll::-webkit-scrollbar-button {
  display: none;
  height: 0;
  width: 0;
}
.repo-dialog-scroll::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.18);
  border-radius: 999px;
}
.repo-dialog-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.32);
}
.repo-dialog-form {
  max-width: 100%;
  box-sizing: border-box;
  contain: layout style;
}
.repo-dialog-form .repo-form-grid {
  margin-inline: 0 !important;
  width: 100%;
  max-width: 100%;
}
.repo-form-grid {
  margin-top: 0;
  --v-input-control-height: 44px;
}
.repo-form-grid > .v-col {
  padding-top: 8px;
  padding-bottom: 16px;
}
.repo-form-grid > .v-col.repo-form-desc-col {
  padding-bottom: 24px !important;
}
.repo-field-caption {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 400;
  color: var(--form-label, rgba(255, 255, 255, 0.6));
}
.repo-threshold-grid > .v-col {
  padding-bottom: 12px;
}
.repo-form-section-title {
  margin: 4px 0 0;
  padding-inline: 0;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.45);
}
.repo-form-section-divider {
  border-color: rgba(255, 255, 255, 0.06) !important;
  opacity: 1;
}
.repo-form-field--frontend :deep(.v-field) {
  border-color: rgba(129, 201, 149, 0.45);
  background: rgba(129, 201, 149, 0.06);
}
.repo-field-help {
  vertical-align: middle;
  opacity: 0.65;
  cursor: help;
}
.repo-advanced-panels {
  margin-inline: 0;
}
.repo-advanced-panels :deep(.v-expansion-panel) {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 12px !important;
}
.repo-advanced-panels :deep(.v-expansion-panel-title) {
  padding-inline: 16px !important;
}
.repo-advanced-panels :deep(.v-expansion-panel-text__wrapper) {
  padding: 8px 16px 16px !important;
}
.repo-advanced-panel-body :deep(.v-expansion-panel-text__wrapper) {
  padding-inline: 16px !important;
}
.repo-advanced-panels__title {
  min-height: 44px !important;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.78) !important;
}
.repo-form-grid--align {
  margin-inline: 0 !important;
}
.repo-form-grid--align > .v-col {
  padding-inline: 0;
}
.repo-advanced-block + .repo-advanced-block {
  margin-top: 24px;
  padding-top: 24px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}
.repo-dialog-toggles-hint {
  margin-top: 4px;
  padding-bottom: 4px;
}
.repo-dialog-toggles {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px 24px;
  padding: 4px 0 2px;
}
.repo-dialog-footer-fixed {
  flex-shrink: 0;
  padding: 8px 24px 4px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  background: var(--dg-surface-modal, #1e1e1e);
}
.repo-dialog-toggles-bar {
  background: rgba(255, 255, 255, 0.03);
  padding: 12px 24px 10px;
}
.repo-dialog-toggles-bar--separated {
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}
.repo-advanced-subtitle {
  margin: 0 0 8px;
  padding-inline: 0;
  font-size: 13px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.72);
}
.repo-coverage-combo {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 44px;
  padding: 6px 8px 6px 4px;
  border-radius: 6px;
  border: 1px solid var(--form-border-default, rgba(255, 255, 255, 0.1));
  background: var(--form-bg, rgba(255, 255, 255, 0.03));
  transition: border-color 0.2s ease;
}
.repo-coverage-combo:hover {
  border-color: var(--form-border-hover, rgba(255, 255, 255, 0.2));
}
.repo-coverage-combo__slider {
  flex: 1 1 auto;
  min-width: 0;
  padding-inline: 6px 2px;
}
.repo-coverage-combo__tag {
  flex: 0 0 104px;
  width: 104px;
  max-width: 104px;
}
.repo-coverage-combo__tag :deep(.v-field) {
  margin-top: 0 !important;
  min-height: 36px !important;
  border: none !important;
  background: rgba(255, 255, 255, 0.05) !important;
  border-radius: 4px !important;
  box-shadow: none !important;
  overflow: visible;
}
.repo-coverage-combo__tag :deep(.v-field__outline) {
  display: none !important;
}
.repo-coverage-combo__tag :deep(.v-field__field) {
  align-items: center;
  min-height: 36px;
}
.repo-coverage-combo__tag :deep(.v-field__input) {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.25;
  color: rgba(255, 255, 255, 0.92);
  padding: 6px 4px 6px 8px !important;
  min-height: 24px;
  text-align: center;
}
.repo-coverage-combo__tag :deep(.v-field__suffix) {
  padding-inline-end: 8px !important;
  font-size: 13px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.75);
  opacity: 1;
}
.repo-threshold-block .repo-threshold-number :deep(.v-field) {
  margin-top: 0 !important;
}
.repo-risk-group-title {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.88);
}
.repo-risk-path-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 20px;
  width: 100%;
}
.repo-risk-path-col {
  min-width: 0;
}
@media (max-width: 560px) {
  .repo-risk-path-grid {
    grid-template-columns: 1fr;
  }
}
.repo-glob-hint {
  margin: 12px 0 0;
  padding: 0;
  font-size: 12px;
  line-height: 1.5;
  color: rgba(255, 255, 255, 0.4);
}
.repo-risk-rules-block .repo-glob-hint {
  margin-bottom: 20px;
}
.repo-advanced-block.repo-notify-block {
  margin-top: 0;
  padding-top: 0;
  border-top: none;
}
.repo-notify-section-title {
  margin: 0 0 8px;
  padding: 0;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
  color: rgba(255, 255, 255, 0.88);
}
.repo-notify-row {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  max-width: 100%;
}
.repo-notify-url-field {
  flex: 1 1 auto;
  min-width: 0;
  margin: 0;
}
.repo-notify-url-field {
  margin-top: 0;
}
.repo-notify-policy-field {
  margin-top: 16px;
  max-width: 50%;
}
.repo-advanced-panels--form-tail {
  margin-bottom: 24px;
}
.repo-override-switch :deep(.v-selection-control) {
  align-items: center;
  min-height: 40px;
}
.repo-override-switch :deep(.v-label) {
  font-size: 14px;
  color: rgba(255, 255, 255, 0.82);
  opacity: 1;
}
.repo-test-notify-btn {
  flex: 0 0 auto;
  min-height: 44px !important;
  height: 44px;
  padding-inline: 16px !important;
  border-color: rgba(255, 255, 255, 0.18) !important;
  background: transparent !important;
  color: rgba(255, 255, 255, 0.72) !important;
  font-weight: 500;
}
.repo-test-notify-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.06) !important;
  border-color: rgba(255, 255, 255, 0.28) !important;
  color: rgba(255, 255, 255, 0.88) !important;
}
.repo-test-notify-btn:disabled {
  opacity: 0.45;
}
.repo-dialog-toggles .repo-form-switch {
  flex: 1 1 180px;
  max-width: calc(33.33% - 14px);
  min-width: 160px;
  margin: 0;
}
@media (max-width: 720px) {
  .repo-dialog-toggles .repo-form-switch {
    max-width: calc(50% - 10px);
  }
}
.repo-coverage-slider :deep(.v-slider-track__background) {
  background-color: rgba(255, 255, 255, 0.16);
  opacity: 1;
}
.repo-coverage-slider :deep(.v-slider-track__fill) {
  background-color: var(--form-border-focus, #3b82f6) !important;
  opacity: 1;
}
.repo-coverage-slider :deep(.v-slider-thumb__surface) {
  background-color: var(--form-border-focus, #3b82f6) !important;
  border-color: #2563eb !important;
}
.repo-form-switch :deep(.v-switch__track) {
  opacity: 0.85;
}
.repo-dialog-actions {
  position: sticky;
  bottom: 0;
  z-index: 3;
  padding: 16px 24px 20px !important;
  gap: 8px;
  background: var(--dg-surface-modal, #1e1e1e);
  box-shadow: 0 -8px 24px rgba(0, 0, 0, 0.25);
}
.repo-dialog-cancel {
  color: rgba(255, 255, 255, 0.65) !important;
  font-weight: 500;
}
.repo-dialog-cancel:hover {
  color: rgba(255, 255, 255, 0.88) !important;
  background: transparent !important;
}
.repo-dialog-submit {
  font-weight: 600;
  padding-inline: 20px !important;
  min-height: 44px;
  background: #3b82f6 !important;
  color: #ffffff !important;
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.35);
}
.repo-dialog-submit:hover {
  background: #2563eb !important;
}
.repo-dialog-form :deep(.v-field__input) {
  overflow: visible;
  text-overflow: clip;
  white-space: pre-wrap;
  min-height: 1.5em;
  padding-inline: 12px !important;
}
.repo-form-field--url :deep(textarea),
.repo-form-field--name :deep(textarea) {
  font-family: var(--diffgate-mono);
  font-size: 13px;
  line-height: 1.5;
  word-break: break-all;
  overflow-wrap: anywhere;
  min-height: 44px;
  max-height: 96px;
  padding-block: 12px;
}
.repo-form-field--name :deep(.v-label),
.repo-form-field--url :deep(.v-label) {
  font-family: 'Noto Sans SC', Roboto, 'Segoe UI', system-ui, sans-serif;
}
.repo-dialog-form :deep(.v-field__field) {
  align-items: flex-start;
}
.repo-dialog-form.dg-dark-form .repo-form-grid > .v-col {
  padding-top: 12px;
}
</style>

<style>
/* v-menu 挂到 body，菜单样式必须全局且铺在 .repo-row-action-menu 下 */
.repo-row-action-menu {
  z-index: 2600 !important;
  background-color: #353b45 !important;
  border: none !important;
  outline: none !important;
  border-radius: 8px !important;
  box-shadow:
    0 14px 36px rgba(0, 0, 0, 0.52),
    0 4px 14px rgba(0, 0, 0, 0.32) !important;
  overflow: hidden;
  isolation: isolate;
  opacity: 1 !important;
}
.repo-row-action-menu .v-overlay__content {
  border: none !important;
  box-shadow: none !important;
}
.repo-row-action-menu .v-list,
.repo-row-action-menu .repo-action-menu {
  background-color: #353b45 !important;
  padding: 6px !important;
}
.repo-row-action-menu .repo-action-menu__item.v-list-item {
  min-height: 40px !important;
  padding: 8px 12px !important;
  margin: 2px 0;
  font-size: 14px;
  border-radius: 6px !important;
  transition: background-color 0.15s ease;
}
.repo-row-action-menu .repo-action-menu__item .v-list-item__prepend {
  width: 20px;
  min-width: 20px;
  margin-inline-end: 12px !important;
  display: flex;
  align-items: center;
  justify-content: center;
}
.repo-row-action-menu .repo-action-menu__item .v-list-item-title {
  font-size: 14px;
  font-weight: 500;
  letter-spacing: 0.01em;
  line-height: 1.35;
  color: rgba(255, 255, 255, 0.92);
}
.repo-row-action-menu .repo-action-menu__item .v-list-item__overlay {
  opacity: 0 !important;
}
.repo-row-action-menu .repo-action-menu__item:not(.v-list-item--disabled):hover {
  background: rgba(255, 255, 255, 0.1) !important;
}
.repo-row-action-menu .repo-action-menu__item--danger .v-list-item-title,
.repo-row-action-menu .repo-action-menu__item--danger .v-icon {
  color: #f28b82 !important;
}
.repo-row-action-menu .repo-action-menu__item--danger:not(.v-list-item--disabled):hover {
  background: rgba(242, 139, 130, 0.16) !important;
}
.repo-row-action-menu .repo-action-menu__separator {
  display: block;
  height: 1px;
  margin: 6px 16px 4px;
  border: none;
  background: rgba(255, 255, 255, 0.03);
  box-shadow: none;
  pointer-events: none;
}

.repo-linked-repo-menu.v-overlay__content {
  z-index: 2800 !important;
  background: #2c2c2c !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  border-radius: 8px !important;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5) !important;
  overflow: hidden;
  opacity: 1 !important;
}

.repo-linked-repo-menu .v-list {
  background: transparent !important;
  padding: 6px !important;
}

.repo-linked-repo-menu .v-list-item {
  border-radius: 6px !important;
  min-height: 40px !important;
}

.repo-linked-repo-menu .v-list-item-title {
  color: rgba(255, 255, 255, 0.9) !important;
  font-size: 14px;
}

.repo-linked-repo-menu .v-list-item:hover {
  background: rgba(255, 255, 255, 0.06) !important;
}

.repo-linked-menu-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px 16px;
  text-align: center;
  color: rgba(255, 255, 255, 0.4);
  font-size: 13px;
  line-height: 1.45;
}

.repo-linked-menu-empty__icon {
  color: rgba(255, 255, 255, 0.35) !important;
  opacity: 1;
}

.repo-linked-menu-empty__hint {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.32);
  max-width: 220px;
}
</style>