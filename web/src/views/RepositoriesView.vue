<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import type { VForm } from 'vuetify/components'
import {
  createRepository,
  deleteRepository,
  fetchRepoOverview,
  fetchRepositories,
  fetchTestSuitePresets,
  readApiError,
  reindexRepository,
  triggerRepoAnalysis,
  updateRepository,
} from '@/api/client'
import type {
  AuthMethod,
  RepoOverviewStats,
  RepoProvider,
  RepositoryItem,
  RepositoryPayload,
} from '@/api/types'
import { parseFullNameFromCloneUrl } from '@/utils/git'
import { formatLocalDateTime } from '@/utils/datetime'

const router = useRouter()
const loading = ref(false)
const keyword = ref('')
const rows = ref<RepositoryItem[]>([])
const overview = ref<RepoOverviewStats | null>(null)
const dialogVisible = ref(false)
const editingId = ref<string | null>(null)
const formRef = ref<VForm | null>(null)
const actionLoading = ref<string | null>(null)
/** 正在重建 AST 的仓库行（菜单关闭后仍可见） */
const reindexingId = ref<string | null>(null)
const submitPhase = ref<'idle' | 'saving' | 'indexing'>('idle')
const fullNameManual = ref(false)
const testSuiteOptions = ref<string[]>([])
const accessToken = ref('')
const sshPrivateKey = ref('')
const editingTokenConfigured = ref(false)
const editingSshConfigured = ref(false)
const deleteDialog = ref(false)
const deleteTarget = ref<RepositoryItem | null>(null)
const submitLoading = ref(false)
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

const submitButtonLabel = computed(() => {
  if (!submitLoading.value) return editingId.value ? '保存' : '保存并初始化索引'
  if (submitPhase.value === 'indexing') return '正在构建 AST 索引…'
  return editingId.value ? '保存中…' : '保存中…'
})

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

const repoForm = ref<RepositoryPayload>({
  full_name: '',
  provider: 'gitlab',
  clone_url: '',
  default_branch: 'main',
  description: '',
  enabled: true,
  webhook_enabled: true,
  coverage_threshold: 80,
  auth_method: 'none',
  scan_root: '.',
  test_suite_id: '',
})

const required = (v: unknown) => (v !== null && v !== undefined && String(v).trim() !== '') || '必填'

watch(
  () => repoForm.value.clone_url,
  (url) => {
    if (fullNameManual.value || editingId.value) return
    const parsed = parseFullNameFromCloneUrl(url || '')
    if (parsed) repoForm.value.full_name = parsed
  },
)

const providerLabel: Record<RepoProvider, string> = {
  github: 'GitHub',
  gitlab: 'GitLab',
  local: '本地',
}

const providerItems = [
  { title: 'GitLab', value: 'gitlab' as RepoProvider },
  { title: 'GitHub', value: 'github' as RepoProvider },
  { title: '本地', value: 'local' as RepoProvider },
]

const authItems = [
  { title: '无认证（公开/本地）', value: 'none' as AuthMethod },
  { title: 'Access Token（推荐）', value: 'token' as AuthMethod },
  { title: 'SSH 私钥', value: 'ssh' as AuthMethod },
]

const headers = [
  { title: '仓库', key: 'full_name', minWidth: 140 },
  { title: '来源', key: 'provider', width: 88 },
  { title: '默认分支', key: 'default_branch', width: 110 },
  { title: 'AST 节点规模', key: 'ast_scale', minWidth: 172, sortable: false },
  { title: '关联用例集', key: 'test_suite_id', minWidth: 120 },
  { title: '质量门禁', key: 'coverage_threshold', width: 130, sortable: false },
  { title: '分析次数', key: 'job_count', width: 96, align: 'end' as const },
  { title: '启用', key: 'enabled', width: 88, sortable: false },
  { title: 'Webhook', key: 'webhook_enabled', width: 96, sortable: false },
  { title: '最近索引', key: 'last_indexed_at', minWidth: 156, width: 156 },
  { title: '操作', key: 'actions', sortable: false, width: 120, align: 'end' as const },
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
  editingId.value = null
  fullNameManual.value = false
  accessToken.value = ''
  sshPrivateKey.value = ''
  editingTokenConfigured.value = false
  editingSshConfigured.value = false
  Object.assign(repoForm.value, {
    full_name: '',
    provider: 'gitlab' as RepoProvider,
    clone_url: '',
    default_branch: 'main',
    description: '',
    enabled: true,
    webhook_enabled: true,
    coverage_threshold: 80,
    auth_method: 'none' as AuthMethod,
    scan_root: '.',
    test_suite_id: '',
  })
  dialogVisible.value = true
}

function openEdit(row: RepositoryItem) {
  editingId.value = row.id
  fullNameManual.value = true
  accessToken.value = ''
  sshPrivateKey.value = ''
  editingTokenConfigured.value = Boolean(row.token_configured)
  editingSshConfigured.value = Boolean(row.ssh_configured)
  Object.assign(repoForm.value, {
    full_name: row.full_name,
    provider: row.provider,
    clone_url: row.clone_url,
    default_branch: row.default_branch,
    description: row.description ?? '',
    enabled: row.enabled,
    webhook_enabled: row.webhook_enabled,
    coverage_threshold: row.coverage_threshold ?? 80,
    auth_method: row.auth_method ?? 'none',
    scan_root: row.scan_root || '.',
    test_suite_id: row.test_suite_id ?? '',
  })
  dialogVisible.value = true
}

function buildPayload(): RepositoryPayload {
  const payload: RepositoryPayload = { ...repoForm.value }
  if (!payload.test_suite_id) payload.test_suite_id = null
  if (repoForm.value.auth_method === 'token' && accessToken.value) {
    payload.access_token = accessToken.value
  }
  if (repoForm.value.auth_method === 'ssh' && sshPrivateKey.value) {
    payload.ssh_private_key = sshPrivateKey.value
  }
  return payload
}

async function submit() {
  const { valid } = (await formRef.value?.validate()) ?? { valid: false }
  if (!valid) return
  if (repoForm.value.auth_method === 'ssh') {
    const pasted = sshPrivateKey.value.trim().length > 0
    if (!pasted && !editingSshConfigured.value) {
      notify('请粘贴 SSH 私钥（与 GitHub Deploy key 配对的那把私钥文件全文）', 'error')
      return
    }
  }
  const payload = buildPayload()
  submitLoading.value = true
  submitPhase.value = 'saving'
  try {
    if (editingId.value) {
      await updateRepository(editingId.value, payload)
      dialogVisible.value = false
      await refreshAfterMutation()
      notify('仓库配置已更新')
    } else {
      const created = await createRepository(payload)
      submitPhase.value = 'indexing'
      notifyInProgress(`正在构建 AST 索引：${created.full_name}…`)
      try {
        const res = await reindexRepository(created.id)
        dialogVisible.value = false
        await refreshAfterMutation()
        const m = res.stats?.method_count ?? res.repository.ast_method_count
        const a = res.stats?.api_count ?? res.repository.ast_api_count
        notify(`AST 索引完成：${m} 方法 · ${a} 接口`)
      } catch (indexErr) {
        dialogVisible.value = false
        await refreshAfterMutation()
        notify(
          readApiError(indexErr, '仓库已保存，AST 索引构建失败，请在列表中手动重建'),
          'error',
        )
      }
    }
  } catch {
    notify('保存失败', 'error')
  } finally {
    submitLoading.value = false
    submitPhase.value = 'idle'
  }
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
  testSuiteOptions.value = await fetchTestSuitePresets()
  await load()
})
</script>

<template>
  <div class="repo-page">
    <header class="repo-page-head">
      <h2 class="text-h5 font-weight-bold repo-page-title">
        仓库管理
        <span class="repo-page-title-count">({{ repoCountForTitle }})</span>
      </h2>
      <div class="repo-toolbar">
        <v-text-field
          v-if="showRepoSearch"
          v-model="keyword"
          class="repo-search-field"
          density="comfortable"
          variant="solo"
          flat
          hide-details
          rounded="lg"
          placeholder="搜索 group/project"
          prepend-inner-icon="mdi-magnify"
          clearable
          @keyup.enter="load"
        />
        <v-btn
          class="cta-repo-action cta-repo-action--primary text-none"
          variant="flat"
          color="primary"
          rounded="lg"
          height="40"
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
      <v-progress-linear v-if="loading && rows.length === 0" indeterminate color="primary" />
      <template v-if="!loading && rows.length === 0">
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
                class="cta-repo-action cta-repo-action--primary text-none"
                variant="flat"
                color="primary"
                rounded="lg"
                height="40"
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
          <span class="font-weight-medium">{{ item.full_name }}</span>
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
          <v-chip
            size="small"
            variant="flat"
            class="repo-tone-chip"
            :class="item.webhook_enabled ? 'repo-tone-chip--ok' : 'repo-tone-chip--muted'"
          >
            {{ item.webhook_enabled ? '开' : '关' }}
          </v-chip>
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

    <v-dialog v-model="dialogVisible" max-width="760" class="repo-dialog">
      <v-card class="repo-dialog-card" rounded="xl">
        <v-card-title class="repo-dialog-title">
          {{ editingId ? '编辑仓库' : '添加仓库' }}
        </v-card-title>
        <v-divider class="repo-dialog-title-divider" />
        <v-card-text class="repo-dialog-body">
          <v-form ref="formRef" class="repo-dialog-form" @submit.prevent="submit">
            <v-row class="repo-form-grid">
              <v-col cols="12" md="3">
                <v-select
                  v-model="repoForm.provider"
                  label="来源"
                  :items="providerItems"
                  item-title="title"
                  item-value="value"
                  :rules="[required]"
                  variant="outlined"
                  density="comfortable"
                  hide-details="auto"
                  class="repo-form-field"
                />
              </v-col>
              <v-col cols="12" md="9">
                <v-textarea
                  v-model="repoForm.clone_url"
                  label="Clone URL"
                  :rules="[required]"
                  variant="outlined"
                  density="comfortable"
                  rows="1"
                  auto-grow
                  :max-rows="3"
                  hide-details="auto"
                  placeholder="https://gitlab.com/my-team/order-service.git"
                  class="repo-form-field repo-form-field--url"
                />
              </v-col>

              <v-col cols="12" md="6">
                <v-textarea
                  v-model="repoForm.full_name"
                  label="全称"
                  :rules="[required]"
                  variant="outlined"
                  density="comfortable"
                  rows="1"
                  auto-grow
                  :max-rows="3"
                  hide-details="auto"
                  placeholder="group/project"
                  class="repo-form-field repo-form-field--name"
                  @update:model-value="fullNameManual = true"
                />
              </v-col>
              <v-col cols="12" md="6">
                <v-text-field
                  v-model="repoForm.default_branch"
                  label="默认分支"
                  variant="outlined"
                  density="comfortable"
                  hide-details="auto"
                  class="repo-form-field"
                />
              </v-col>

              <v-col cols="12" md="6">
                <v-select
                  v-model="repoForm.auth_method"
                  label="认证方式"
                  :items="authItems"
                  item-title="title"
                  item-value="value"
                  variant="outlined"
                  density="comfortable"
                  hide-details="auto"
                  class="repo-form-field"
                />
              </v-col>
              <v-col cols="12" md="6">
                <v-text-field
                  v-model="repoForm.scan_root"
                  label="源码根目录"
                  variant="outlined"
                  density="comfortable"
                  hide-details="auto"
                  placeholder="app 或 src/main/python，默认 ."
                  class="repo-form-field"
                />
              </v-col>

              <v-col v-if="repoForm.auth_method === 'token'" cols="12">
                <v-text-field
                  v-model="accessToken"
                  label="Access Token"
                  type="password"
                  variant="outlined"
                  density="comfortable"
                  hide-details="auto"
                  :placeholder="
                    editingTokenConfigured ? '已配置，留空表示不修改' : '后端静默拉取代码执行 Git Diff / AST'
                  "
                  class="repo-form-field"
                />
              </v-col>
              <v-col v-else-if="repoForm.auth_method === 'ssh'" cols="12">
                <v-textarea
                  v-model="sshPrivateKey"
                  label="SSH 私钥"
                  variant="outlined"
                  density="comfortable"
                  rows="6"
                  hide-details="auto"
                  placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
                  class="repo-form-field"
                  :hint="
                    editingSshConfigured
                      ? '已配置私钥：留空表示不修改；要更换密钥请粘贴新私钥全文'
                      : '粘贴私钥全文（勿粘贴 .pub 公钥）'
                  "
                  persistent-hint
                />
                <p class="repo-ssh-hint text-caption text-medium-emphasis mt-2 mb-0">
                  仅在此填写<strong class="font-weight-medium">私钥</strong>。在 GitHub / GitLab
                  后台添加的是配对的<strong class="font-weight-medium">公钥</strong>（以
                  <span class="mono">ssh-ed25519</span> 或 <span class="mono">ssh-rsa</span> 开头，通常来自
                  <span class="mono">id_ed25519.pub</span>），不要粘贴私钥行。
                </p>
              </v-col>

              <v-col cols="12" md="6">
                <v-combobox
                  v-model="repoForm.test_suite_id"
                  label="关联用例集"
                  :items="testSuiteOptions"
                  variant="outlined"
                  density="comfortable"
                  hide-details="auto"
                  clearable
                  placeholder="API 测试平台项目标识"
                  class="repo-form-field"
                />
              </v-col>
              <v-col cols="12" md="6" class="d-flex flex-column justify-center repo-form-slider-col">
                <div class="repo-form-slider-label text-medium-emphasis mb-2">
                  增量覆盖率阈值：{{ repoForm.coverage_threshold }}%
                </div>
                <v-slider
                  v-model="repoForm.coverage_threshold"
                  class="repo-coverage-slider"
                  :min="0"
                  :max="100"
                  step="1"
                  color="secondary"
                  hide-details
                  thumb-label
                />
              </v-col>

              <v-col cols="12" class="repo-form-desc-col">
                <v-text-field
                  v-model="repoForm.description"
                  label="描述"
                  variant="outlined"
                  density="comfortable"
                  hide-details="auto"
                  class="repo-form-field"
                />
              </v-col>
            </v-row>
          </v-form>
        </v-card-text>
        <div class="repo-dialog-toggles">
          <v-switch
            v-model="repoForm.enabled"
            label="启用分析"
            color="primary"
            density="comfortable"
            hide-details
            class="repo-form-switch"
          />
          <v-switch
            v-model="repoForm.webhook_enabled"
            label="接收 Webhook"
            color="primary"
            density="comfortable"
            hide-details
            class="repo-form-switch"
          />
        </div>
        <v-divider class="repo-dialog-footer-divider" />
        <v-card-actions class="repo-dialog-actions">
          <v-spacer />
          <v-btn class="repo-dialog-cancel text-none" variant="text" @click="dialogVisible = false">
            取消
          </v-btn>
          <v-btn
            class="repo-dialog-submit text-none"
            variant="flat"
            color="primary"
            :loading="submitLoading"
            @click="submit"
          >
            {{ submitButtonLabel }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

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
.repo-page {
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
}
.repo-page-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 16px 24px;
  width: 100%;
  box-sizing: border-box;
  padding: 24px 0;
  margin-bottom: 0 !important;
  border-bottom: 1px solid #2a2a2a;
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
  align-items: baseline;
  gap: 8px;
  margin: 0;
  flex: 0 1 auto;
  min-width: 0;
  line-height: 40px;
}
.repo-page-title-count {
  font-size: 0.875rem;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.42);
  letter-spacing: 0.02em;
}
.repo-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  flex: 0 0 auto;
  margin-left: auto;
}
.repo-search-field {
  flex: 0 0 auto;
  width: min(300px, 100%);
  min-width: 240px;
  max-width: 320px;
}
.repo-search-field :deep(.v-field) {
  border: 1px solid rgba(255, 255, 255, 0.12) !important;
  background: #1e1e1e !important;
  box-shadow: none;
  font-size: 13px;
  min-height: 40px;
  border-radius: 8px !important;
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease;
}
.repo-search-field :deep(.v-field--focused) {
  border-color: rgb(var(--v-theme-primary)) !important;
  box-shadow: 0 0 0 3px rgba(138, 180, 248, 0.22);
}
.repo-search-field :deep(.v-field__input) {
  min-height: 40px;
  padding-top: 0;
  padding-bottom: 0;
}
.repo-search-field :deep(.v-field__prepend-inner .v-icon) {
  opacity: 0.85;
  color: rgba(255, 255, 255, 0.72);
}
.repo-search-field :deep(.v-field__outline) {
  opacity: 0 !important;
}
.cta-repo-action {
  letter-spacing: 0;
  flex-shrink: 0;
}
.cta-repo-action--primary {
  font-weight: 600;
  padding-inline: 20px !important;
  letter-spacing: 0.01em;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.35);
  transition: filter 0.18s ease;
}
.cta-repo-action--primary :deep(.v-btn__prepend .v-icon) {
  font-size: 20px;
  margin-inline-end: 2px;
}
.cta-repo-action--primary:hover {
  filter: brightness(1.1);
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
  color: rgba(255, 255, 255, 0.78) !important;
  font-weight: 600 !important;
  font-size: 13px !important;
  white-space: nowrap;
  border-bottom: 1px solid rgba(255, 255, 255, 0.07) !important;
  padding-top: 14px !important;
  padding-bottom: 14px !important;
}
.repo-table :deep(thead th:first-child),
.repo-table :deep(tbody td:first-child) {
  padding-left: 24px !important;
}
.repo-table :deep(thead th:last-child),
.repo-table :deep(tbody td:last-child) {
  padding-right: 24px !important;
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
}
.repo-table-switch :deep(.v-switch__track) {
  opacity: 1 !important;
  background-color: rgba(255, 255, 255, 0.14) !important;
}
.repo-table-switch :deep(.v-switch__thumb) {
  background-color: rgba(210, 214, 220, 0.92) !important;
  color: rgba(210, 214, 220, 0.92) !important;
}
.repo-table-switch.v-input--dirty :deep(.v-switch__track) {
  background-color: rgba(138, 180, 248, 0.38) !important;
}
.repo-table-switch.v-input--dirty :deep(.v-switch__thumb) {
  background-color: #b8d4f7 !important;
  color: #b8d4f7 !important;
}
.repo-ast-scale {
  display: inline-block;
  white-space: nowrap;
  font-size: 12px;
  letter-spacing: 0.01em;
}
.repo-index-time {
  display: inline-block;
  white-space: nowrap;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.72);
}
.repo-table-cell--control,
.repo-table-cell--actions {
  display: flex;
  align-items: center;
  min-height: 40px;
}
.repo-table-cell--actions {
  justify-content: center;
  width: 100%;
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
  background: rgba(255, 193, 7, 0.16) !important;
  color: #fdd663 !important;
}
.repo-tone-chip--ok {
  background: rgba(52, 168, 83, 0.16) !important;
  color: #81c995 !important;
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
  min-height: 32px !important;
  height: 32px !important;
  background-color: rgba(255, 255, 255, 0.05) !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  border-radius: 6px;
  font-size: 13px;
}
.page-size-select :deep(.v-field__input) {
  min-height: 32px;
  padding: 0 12px !important;
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
  gap: 4px;
}
.repo-pagination-wrapper .page-btn {
  width: 32px !important;
  min-width: 32px !important;
  height: 32px !important;
  border-radius: 8px;
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
  max-height: min(88vh, 680px);
  border-radius: 16px !important;
  overflow: hidden;
  background: #1c1d21 !important;
}
.repo-dialog-title,
.repo-dialog-title-divider,
.repo-dialog-toggles,
.repo-dialog-footer-divider,
.repo-dialog-actions {
  flex-shrink: 0;
}
.repo-dialog-title {
  padding: 20px 24px 16px !important;
  font-size: 1.25rem !important;
  font-weight: 700 !important;
  letter-spacing: 0.01em;
  color: rgba(255, 255, 255, 0.95) !important;
  line-height: 1.3;
}
.repo-dialog-title-divider,
.repo-dialog-footer-divider {
  border-color: rgba(255, 255, 255, 0.08) !important;
  opacity: 1;
}
.repo-dialog-footer-divider {
  border-color: rgba(255, 255, 255, 0.05) !important;
}
.repo-dialog-body {
  flex: 1 1 auto;
  min-height: 0;
  padding: 20px 10px 0 24px !important;
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-gutter: stable;
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 255, 255, 0.14) transparent;
}
.repo-dialog-form {
  padding-right: 16px;
  max-width: 100%;
  box-sizing: border-box;
}
.repo-dialog-form .repo-form-grid {
  margin-inline: 0 !important;
  width: 100%;
  max-width: 100%;
}
.repo-dialog-body::-webkit-scrollbar {
  width: 6px;
}
.repo-dialog-body::-webkit-scrollbar-track {
  background: transparent;
}
.repo-dialog-body::-webkit-scrollbar-thumb {
  background-color: rgba(255, 255, 255, 0.12);
  border-radius: 999px;
  border: 2px solid transparent;
  background-clip: padding-box;
  transition: background-color 0.2s ease;
}
.repo-dialog-body:hover::-webkit-scrollbar-thumb {
  background-color: rgba(255, 255, 255, 0.26);
}
.repo-dialog-body::-webkit-scrollbar-thumb:hover {
  background-color: rgba(255, 255, 255, 0.36);
}
.repo-dialog-body::-webkit-scrollbar-button,
.repo-dialog-body::-webkit-scrollbar-corner {
  display: none;
  width: 0;
  height: 0;
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
.repo-form-slider-col {
  padding-bottom: 16px !important;
}
.repo-form-slider-label {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.72);
  margin-bottom: 8px !important;
}
.repo-dialog-toggles {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px 24px;
  padding: 0 24px 16px;
}
.repo-dialog-toggles .repo-form-switch {
  flex: 1 1 200px;
  max-width: calc(50% - 12px);
  margin: 0;
}
.repo-coverage-slider :deep(.v-slider-track__background) {
  background-color: rgba(255, 255, 255, 0.12);
}
.repo-coverage-slider :deep(.v-slider-track__fill) {
  background-color: #9aa0a6 !important;
}
.repo-coverage-slider :deep(.v-slider-thumb__surface) {
  background-color: #e8eaed !important;
  border-color: #c4c7cc !important;
}
.repo-form-switch :deep(.v-switch__track) {
  opacity: 0.85;
}
.repo-dialog-actions {
  padding: 16px 24px 20px !important;
  gap: 8px;
}
.repo-dialog-cancel {
  color: rgba(255, 255, 255, 0.65) !important;
  font-weight: 500;
}
.repo-dialog-cancel:hover {
  color: rgba(255, 255, 255, 0.88) !important;
  background: rgba(255, 255, 255, 0.06) !important;
}
.repo-dialog-submit {
  font-weight: 600;
  padding-inline: 20px !important;
  min-height: 40px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
}
.repo-dialog-form :deep(.v-field) {
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: #e8eaed;
  min-height: 44px;
  border-radius: 8px;
}
.repo-dialog-form :deep(.v-field--focused) {
  border-color: rgba(138, 180, 248, 0.65) !important;
  box-shadow: 0 0 0 1px rgba(138, 180, 248, 0.28);
}
.repo-dialog-form :deep(.v-field__input) {
  color: #f1f3f5;
  opacity: 1;
  overflow: visible;
  text-overflow: clip;
  white-space: pre-wrap;
  min-height: 1.5em;
  padding-inline: 12px !important;
}
.repo-dialog-form :deep(.v-label) {
  color: rgba(255, 255, 255, 0.72);
  opacity: 1;
  margin-bottom: 8px;
}
.repo-form-field--url :deep(textarea),
.repo-form-field--name :deep(textarea) {
  font-family: var(--diffgate-mono);
  font-size: 13px;
  line-height: 1.5;
  word-break: break-all;
  overflow-wrap: anywhere;
  field-sizing: content;
  min-height: 44px;
  padding-block: 12px;
}
.repo-form-field--name :deep(.v-label),
.repo-form-field--url :deep(.v-label) {
  font-family: 'Noto Sans SC', Roboto, 'Segoe UI', system-ui, sans-serif;
}
.repo-dialog-form :deep(.v-field__field) {
  align-items: flex-start;
}
.repo-dialog-form :deep(.v-field--active .v-label),
.repo-dialog-form :deep(.v-field--focused .v-label) {
  color: rgba(255, 255, 255, 0.88);
}
</style>

<!-- v-menu 挂到 body，菜单样式必须全局且铺在 .repo-row-action-menu 下 -->
<style>
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
</style>