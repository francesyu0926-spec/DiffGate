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

const router = useRouter()
const loading = ref(false)
const keyword = ref('')
const rows = ref<RepositoryItem[]>([])
const overview = ref<RepoOverviewStats | null>(null)
const dialogVisible = ref(false)
const editingId = ref<string | null>(null)
const formRef = ref<VForm | null>(null)
const actionLoading = ref<string | null>(null)
const fullNameManual = ref(false)
const testSuiteOptions = ref<string[]>([])
const accessToken = ref('')
const sshPrivateKey = ref('')
const editingTokenConfigured = ref(false)
const deleteDialog = ref(false)
const deleteTarget = ref<RepositoryItem | null>(null)
const submitLoading = ref(false)
const kpiTick = ref(0)

type SnackbarVariant = 'success' | 'error'
const snackbar = ref<{ show: boolean; text: string; variant: SnackbarVariant }>({
  show: false,
  text: '',
  variant: 'success',
})

function notify(text: string, variant: SnackbarVariant = 'success') {
  snackbar.value = { show: true, text, variant }
}

const repoRowMenuProps = {
  contentClass: 'repo-row-action-menu',
  elevation: 0,
  rounded: 'lg',
  minWidth: 216,
  maxWidth: 240,
} as const

function formatIndexedAt(iso: string | null | undefined) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) {
    const m = iso.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/)
    return m ? `${m[1]} ${m[2]}` : iso.slice(0, 16).replace('T', ' ')
  }
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
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
  const payload = buildPayload()
  submitLoading.value = true
  try {
    if (editingId.value) {
      await updateRepository(editingId.value, payload)
      dialogVisible.value = false
      await refreshAfterMutation()
      notify('仓库配置已更新')
    } else {
      const created = await createRepository(payload)
      try {
        await reindexRepository(created.id)
        dialogVisible.value = false
        await refreshAfterMutation()
        notify('仓库已接入，AST 调用链图谱构建完成')
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
  actionLoading.value = row.id + ':reindex'
  try {
    await reindexRepository(row.id)
    await refreshAfterMutation()
    notify('仓库已接入，AST 调用链图谱构建完成')
  } catch (err) {
    notify(
      readApiError(err, '索引失败，请检查 Clone 地址、默认分支，或确认已开启「启用分析」'),
      'error',
    )
  } finally {
    actionLoading.value = null
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
  <div>
    <div class="d-flex flex-wrap align-center justify-space-between gap-3 mb-4 repo-page-head">
      <h2 class="text-h5 font-weight-bold repo-page-title">仓库管理</h2>
      <div class="repo-toolbar">
        <v-text-field
          v-if="showRepoSearch"
          v-model="keyword"
          class="repo-search-field"
          density="comfortable"
          variant="solo"
          flat
          hide-details
          rounded="pill"
          placeholder="搜索 group/project"
          prepend-inner-icon="mdi-magnify"
          clearable
          @keyup.enter="load"
        />
        <v-btn
          class="cta-repo-action cta-repo-action--contrast text-none"
          variant="flat"
          rounded="pill"
          height="40"
          prepend-icon="mdi-plus"
          @click="openCreate"
        >
          添加仓库
        </v-btn>
      </div>
    </div>

    <v-row class="mb-2 kpi-row" :class="{ 'kpi-row--pulse': kpiTick > 0 }">
      <v-col v-for="card in kpiCards" :key="card.title" cols="12" sm="6" md="3">
        <v-card class="h-100 kpi-card repo-kpi-card m3-surface-card" rounded="xl" :border="false">
          <span class="repo-kpi-accent" :style="{ backgroundColor: card.accent }" aria-hidden="true" />
          <v-card-text class="repo-kpi-inner">
            <div class="d-flex align-start justify-space-between gap-2 mb-2">
              <div class="text-body-2 repo-kpi-title">{{ card.title }}</div>
              <v-avatar size="40" rounded="lg" :style="{ backgroundColor: card.iconBg }">
                <v-icon :icon="card.icon" :color="card.iconColor" size="22" />
              </v-avatar>
            </div>
            <div class="kpi-value text-h4">{{ card.value }}</div>
            <div
              class="text-caption repo-kpi-sub mt-2"
              :class="{ 'repo-kpi-sub--warn': 'subWarn' in card && card.subWarn }"
            >
              {{ card.sub }}
            </div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-card class="repo-table-card" rounded="xl" :border="false">
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
                class="cta-repo-action cta-repo-action--contrast text-none"
                variant="flat"
                rounded="pill"
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
        class="repo-table"
        :items-per-page="10"
        :items-per-page-options="[10, 25, 50]"
        items-per-page-text="每页"
      >
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
          <span class="repo-ast-scale mono">
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
              density="compact"
              hide-details
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
          <span class="repo-index-time mono" :title="item.last_indexed_at || undefined">
            {{ formatIndexedAt(item.last_indexed_at) }}
          </span>
        </template>
        <template #item.actions="{ item }">
          <div class="repo-table-cell repo-table-cell--actions">
            <v-menu
              location="bottom end"
              origin="overlap"
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
                />
              </template>
              <v-list class="repo-action-menu" density="default" nav>
                <v-list-item
                  class="repo-action-menu__item"
                  rounded="lg"
                  title="重建 AST 索引"
                  :disabled="actionLoading === item.id + ':reindex'"
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
                <v-divider class="repo-action-menu__divider" />
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

    <v-dialog v-model="dialogVisible" max-width="760" scrollable class="repo-dialog">
      <v-card class="repo-dialog-card" :title="editingId ? '编辑仓库' : '添加仓库'">
        <v-card-text class="repo-dialog-body">
          <v-form ref="formRef" class="repo-dialog-form" @submit.prevent="submit">
            <v-row class="repo-form-grid" dense>
              <v-col cols="12" md="4">
                <v-select
                  v-model="repoForm.provider"
                  label="来源"
                  :items="providerItems"
                  item-title="title"
                  item-value="value"
                  :rules="[required]"
                  variant="outlined"
                  density="compact"
                  hide-details="auto"
                  class="repo-form-field"
                />
              </v-col>
              <v-col cols="12" md="8">
                <v-textarea
                  v-model="repoForm.clone_url"
                  label="Clone URL"
                  :rules="[required]"
                  variant="outlined"
                  density="compact"
                  rows="1"
                  auto-grow
                  :max-rows="3"
                  hide-details="auto"
                  placeholder="https://gitlab.com/my-team/order-service.git"
                  class="repo-form-field repo-form-field--url"
                />
              </v-col>

              <v-col cols="12" md="8">
                <v-textarea
                  v-model="repoForm.full_name"
                  label="全称"
                  :rules="[required]"
                  variant="outlined"
                  density="compact"
                  rows="1"
                  auto-grow
                  :max-rows="3"
                  hide-details="auto"
                  placeholder="group/project"
                  class="repo-form-field repo-form-field--name mono"
                  @update:model-value="fullNameManual = true"
                />
              </v-col>
              <v-col cols="12" md="4">
                <v-text-field
                  v-model="repoForm.default_branch"
                  label="默认分支"
                  variant="outlined"
                  density="compact"
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
                  density="compact"
                  hide-details="auto"
                  class="repo-form-field"
                />
              </v-col>
              <v-col cols="12" md="6">
                <v-text-field
                  v-model="repoForm.scan_root"
                  label="源码根目录"
                  variant="outlined"
                  density="compact"
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
                  density="compact"
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
                  density="compact"
                  rows="3"
                  hide-details="auto"
                  placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
                  class="repo-form-field"
                />
              </v-col>

              <v-col cols="12" md="6">
                <v-combobox
                  v-model="repoForm.test_suite_id"
                  label="关联用例集"
                  :items="testSuiteOptions"
                  variant="outlined"
                  density="compact"
                  hide-details="auto"
                  clearable
                  placeholder="API 测试平台项目标识"
                  class="repo-form-field"
                />
              </v-col>
              <v-col cols="12" md="6" class="d-flex flex-column justify-center">
                <div class="text-caption text-medium-emphasis mb-1">
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

              <v-col cols="12">
                <v-text-field
                  v-model="repoForm.description"
                  label="描述"
                  variant="outlined"
                  density="compact"
                  hide-details="auto"
                  class="repo-form-field"
                />
              </v-col>

              <v-col cols="12" sm="6">
                <v-switch
                  v-model="repoForm.enabled"
                  label="启用分析"
                  color="secondary"
                  density="compact"
                  hide-details
                  class="repo-form-switch"
                />
              </v-col>
              <v-col cols="12" sm="6">
                <v-switch
                  v-model="repoForm.webhook_enabled"
                  label="接收 Webhook"
                  color="secondary"
                  density="compact"
                  hide-details
                  class="repo-form-switch"
                />
              </v-col>
            </v-row>
          </v-form>
        </v-card-text>
        <v-card-actions class="px-4 pb-4 repo-dialog-actions">
          <v-spacer />
          <v-btn variant="text" @click="dialogVisible = false">取消</v-btn>
          <v-btn
            class="repo-dialog-submit text-none"
            variant="flat"
            :loading="submitLoading"
            @click="submit"
          >
            {{ editingId ? '保存' : '保存并初始化索引' }}
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
      :timeout="3000"
      rounded="pill"
      elevation="6"
      :color="snackbar.variant === 'error' ? 'error' : undefined"
      :class="[
        'feedback-snackbar',
        snackbar.variant === 'success' && 'feedback-snackbar--success',
      ]"
    >
      <div class="d-flex align-center ga-2 px-1">
        <v-icon
          :icon="snackbar.variant === 'error' ? 'mdi-alert-circle-outline' : 'mdi-check-circle-outline'"
          size="small"
        />
        <span class="text-body-2">{{ snackbar.text }}</span>
      </div>
    </v-snackbar>
  </div>
</template>

<style scoped>
.repo-page-head {
  width: 100%;
  box-sizing: border-box;
}
.repo-page-title {
  flex: 1 1 auto;
  min-width: 0;
}
.repo-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 16px;
  flex: 0 1 auto;
  max-width: 100%;
}
.repo-search-field {
  flex: 0 1 280px;
  width: 280px;
  min-width: 240px;
  max-width: 280px;
}
.repo-search-field :deep(.v-field) {
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  background: rgba(255, 255, 255, 0.04) !important;
  box-shadow: none;
  font-size: 13px;
  min-height: 40px;
}
.repo-search-field :deep(.v-field__input) {
  min-height: 40px;
  padding-top: 0;
  padding-bottom: 0;
}
.repo-search-field :deep(.v-field__prepend-inner .v-icon) {
  opacity: 0.5;
}
.repo-search-field :deep(.v-field__outline) {
  opacity: 0 !important;
}
.cta-repo-action {
  letter-spacing: 0;
  flex-shrink: 0;
}
.cta-repo-action--contrast {
  background-color: #f1f3f5 !important;
  color: #111315 !important;
  font-weight: 700;
  padding-inline: 18px !important;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.28);
}
.cta-repo-action--contrast :deep(.v-btn__overlay) {
  opacity: 0;
}
.cta-repo-action--contrast:hover {
  background-color: #e8eaed !important;
}
.cta-repo-action--contrast :deep(.v-icon) {
  color: #111315 !important;
}
.repo-table-card {
  background-color: rgb(var(--v-theme-surface)) !important;
  border: 1px solid #2a2e35 !important;
  box-shadow: none !important;
}
.m3-surface-card {
  background-color: rgb(var(--v-theme-surface)) !important;
  border: 1px solid rgb(var(--v-theme-outline));
}
.repo-kpi-card {
  position: relative;
  overflow: hidden;
}
.repo-kpi-accent {
  position: absolute;
  left: 0;
  top: 12px;
  bottom: 12px;
  width: 3px;
  border-radius: 0 2px 2px 0;
}
.repo-kpi-inner {
  padding: 18px 20px 20px 22px !important;
}
.repo-kpi-title {
  opacity: 0.72;
}
.repo-kpi-sub {
  line-height: 1.45;
  letter-spacing: 0.02em;
  font-size: 13px !important;
  color: rgba(255, 255, 255, 0.58);
}
.repo-table :deep(thead th) {
  color: rgba(255, 255, 255, 0.62) !important;
  font-weight: 500 !important;
  font-size: 13px !important;
  white-space: nowrap;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08) !important;
}
.repo-table :deep(tbody tr) {
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
.repo-table :deep(tbody td),
.repo-table :deep(.v-data-table__td) {
  vertical-align: middle !important;
  padding-top: 11px !important;
  padding-bottom: 11px !important;
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
  justify-content: flex-end;
}
.repo-tone-chip {
  font-weight: 500;
  letter-spacing: 0.01em;
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
  color: rgba(255, 255, 255, 0.78) !important;
}
.repo-row-action:hover {
  background: rgba(255, 255, 255, 0.08) !important;
}
.repo-table :deep(.v-data-table-footer) {
  padding: 8px 12px 12px !important;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}
.repo-table :deep(.v-data-table-footer__info) {
  min-width: 0;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.55);
}
.repo-table :deep(.v-data-table-footer__items-per-page) {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-inline-end: 8px;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.55);
}
.repo-table :deep(.v-data-table-footer__items-per-page .v-select) {
  max-width: 76px;
}
.repo-table :deep(.v-data-table-footer__items-per-page .v-field) {
  min-height: 32px;
}
.repo-table :deep(.v-pagination) {
  gap: 2px;
}
.repo-table :deep(.v-pagination__first),
.repo-table :deep(.v-pagination__last),
.repo-table :deep(.v-pagination__prev),
.repo-table :deep(.v-pagination__next),
.repo-table :deep(.v-pagination__item) {
  min-width: 36px;
  height: 36px;
  border-radius: 8px;
  color: rgba(255, 255, 255, 0.75);
}
.repo-table :deep(.v-pagination__first:hover),
.repo-table :deep(.v-pagination__last:hover),
.repo-table :deep(.v-pagination__prev:hover),
.repo-table :deep(.v-pagination__next:hover),
.repo-table :deep(.v-pagination__item:hover) {
  background: rgba(255, 255, 255, 0.08);
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
.kpi-value {
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
}

.kpi-row--pulse .kpi-card {
  transition: box-shadow 0.35s ease, border-color 0.35s ease;
}

.feedback-snackbar--success :deep(.v-snackbar__wrapper) {
  background-color: #188038 !important;
  color: #fff;
  min-width: min(520px, 92vw);
  padding-inline: 8px;
}

.repo-dialog-card :deep(.v-card-title) {
  padding: 20px 24px 12px;
  font-size: 1.125rem;
  font-weight: 600;
}
.repo-dialog-body {
  padding: 4px 24px 16px !important;
  max-height: min(58vh, 520px);
  overflow-y: auto;
  overflow-x: hidden;
}
.repo-form-grid {
  margin-top: 0;
  --v-input-control-height: 40px;
}
.repo-form-grid > .v-col {
  padding-top: 6px;
  padding-bottom: 6px;
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
.repo-dialog-submit {
  background-color: #f1f3f5 !important;
  color: #111315 !important;
  font-weight: 700;
  padding-inline: 18px !important;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.22);
}
.repo-dialog-submit:hover {
  background-color: #e8eaed !important;
}
.repo-dialog-actions :deep(.v-btn--variant-text) {
  color: rgba(255, 255, 255, 0.72);
}
.repo-dialog-form :deep(.v-field) {
  border-color: rgba(255, 255, 255, 0.14);
  color: #e8eaed;
}
.repo-dialog-form :deep(.v-field--focused) {
  border-color: rgba(138, 180, 248, 0.55);
}
.repo-dialog-form :deep(.v-field__input) {
  color: #f1f3f5;
  opacity: 1;
  overflow: visible;
  text-overflow: clip;
  white-space: pre-wrap;
  min-height: 1.5em;
}
.repo-dialog-form :deep(.v-label) {
  color: rgba(255, 255, 255, 0.72);
  opacity: 1;
}
.repo-form-field--url :deep(textarea),
.repo-form-field--name :deep(textarea) {
  font-family: var(--diffgate-mono);
  font-size: 13px;
  line-height: 1.5;
  word-break: break-all;
  overflow-wrap: anywhere;
  field-sizing: content;
  min-height: 2.75rem;
  padding-block: 10px;
}
.repo-dialog-form :deep(.v-field__field) {
  align-items: flex-start;
}
.repo-dialog-form :deep(.v-field--active .v-label),
.repo-dialog-form :deep(.v-field--focused .v-label) {
  color: rgba(255, 255, 255, 0.88);
}
.repo-action-menu {
  padding: 4px 0 !important;
  background: transparent !important;
}
.repo-action-menu__item {
  min-height: 40px !important;
  padding: 10px 16px !important;
  margin: 0 4px;
  font-size: 14px;
}
.repo-action-menu__item :deep(.v-list-item__prepend) {
  width: auto;
  min-width: 0;
  margin-inline-end: 12px;
}
.repo-action-menu__item :deep(.v-list-item-title) {
  font-size: 14px;
  font-weight: 500;
  letter-spacing: 0.01em;
}
.repo-action-menu__item :deep(.v-list-item__overlay) {
  opacity: 0 !important;
}
.repo-action-menu__item:not(.v-list-item--disabled):hover {
  background: rgba(255, 255, 255, 0.08);
}
.repo-action-menu__item--danger :deep(.v-list-item-title),
.repo-action-menu__item--danger :deep(.v-icon) {
  color: #f28b82 !important;
}
.repo-action-menu__item--danger:hover {
  background: rgba(244, 67, 54, 0.1) !important;
}
.repo-action-menu__divider {
  margin: 4px 12px;
  border-color: rgba(255, 255, 255, 0.05);
  opacity: 1;
}
</style>

<style>
.repo-row-action-menu {
  z-index: 2500 !important;
  background: #2c2c2c !important;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px !important;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4) !important;
  overflow: hidden;
}
.repo-row-action-menu .v-list {
  background: transparent !important;
}
</style>