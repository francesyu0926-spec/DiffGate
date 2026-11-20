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
  { title: 'AST 节点规模', key: 'ast_scale', minWidth: 150, sortable: false },
  { title: '关联用例集', key: 'test_suite_id', minWidth: 120 },
  { title: '质量门禁', key: 'coverage_threshold', width: 130, sortable: false },
  { title: '分析次数', key: 'job_count', width: 96, align: 'end' as const },
  { title: '启用', key: 'enabled', width: 88, sortable: false },
  { title: 'Webhook', key: 'webhook_enabled', width: 96, sortable: false },
  { title: '最近索引', key: 'last_indexed_at', minWidth: 140 },
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

const kpiCards = computed(() => {
  const o = overview.value
  void kpiTick.value
  const { methods, apis } = astTotals.value
  return [
    {
      title: '已接入代码仓库数',
      value: o?.repo_count ?? 0,
      sub: `全量 AST 索引已构建 ${o?.indexed_repo_count ?? 0} 个 · ${methods} 方法 / ${apis} 接口`,
    },
    {
      title: '累计精准分析次数',
      value: o?.analysis_total ?? 0,
      sub: `平均分析耗时 ${o?.avg_analysis_seconds ?? 0}s`,
    },
    {
      title: '累计拦截高危变更',
      value: o?.high_risk_blocked ?? 0,
      sub: '增量覆盖率不达标阻断',
    },
    {
      title: '回归测试耗时节省',
      value: `${o?.regression_time_saved_pct ?? 0}%`,
      sub: o?.regression_hint ?? '暂无分析任务',
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
      } catch {
        dialogVisible.value = false
        await refreshAfterMutation()
        notify('仓库已保存，AST 索引构建失败，请在列表中手动重建', 'error')
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
  } catch {
    notify('索引失败，请检查 Clone 地址与分支', 'error')
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
    <div class="d-flex flex-wrap align-center justify-space-between gap-3 mb-4">
      <h2 class="text-h5 font-weight-bold">仓库管理</h2>
      <div class="d-flex flex-wrap align-center gap-2">
        <v-text-field
          v-model="keyword"
          class="repo-search-field"
          density="compact"
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
          class="cta-repo-action text-none"
          variant="flat"
          rounded="pill"
          prepend-icon="mdi-plus"
          @click="openCreate"
        >
          添加仓库
        </v-btn>
      </div>
    </div>

    <v-row class="mb-2 kpi-row" :class="{ 'kpi-row--pulse': kpiTick > 0 }">
      <v-col v-for="card in kpiCards" :key="card.title" cols="12" sm="6" md="3">
        <v-card class="h-100 kpi-card repo-kpi-card" rounded="xl" :border="false">
          <v-card-text>
            <div class="text-body-2 text-medium-emphasis">{{ card.title }}</div>
            <div class="kpi-value text-h4 mt-2">{{ card.value }}</div>
            <div class="text-caption text-medium-emphasis mt-1">{{ card.sub }}</div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-card class="repo-table-card" rounded="xl" :border="false">
      <v-progress-linear v-if="loading && rows.length === 0" indeterminate color="primary" />
      <template v-if="!loading && rows.length === 0">
        <v-card-text class="text-center py-12">
          <v-icon icon="mdi-source-repository" size="56" color="primary" class="mb-4 opacity-80" />
          <div class="text-h6 font-weight-medium">暂无接入的代码仓库</div>
          <p class="text-body-2 text-medium-emphasis mt-2 mx-auto empty-tip">
            点击右上角「添加仓库」配置 Git 地址，自动构建 AST 静态调用链图谱。
          </p>
          <v-btn
            class="cta-repo-action text-none mt-4"
            variant="flat"
            rounded="pill"
            prepend-icon="mdi-plus"
            @click="openCreate"
          >
            立即接入首个仓库
          </v-btn>
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
          <span class="mono text-caption">
            {{ item.ast_method_count }} 方法 / {{ item.ast_api_count }} 接口
          </span>
        </template>
        <template #item.test_suite_id="{ item }">
          <span class="text-truncate d-inline-block" style="max-width: 140px">
            {{ item.test_suite_id || '—' }}
          </span>
        </template>
        <template #item.coverage_threshold="{ item }">
          <v-chip size="small" variant="tonal" color="warning">
            增量覆盖率 ≥ {{ item.coverage_threshold }}%
          </v-chip>
        </template>
        <template #item.job_count="{ item }">
          {{ item.job_count ?? 0 }}
        </template>
        <template #item.enabled="{ item }">
          <v-switch
            :model-value="item.enabled"
            color="primary"
            density="compact"
            hide-details
            @update:model-value="(v) => toggleEnabled(item, v)"
          />
        </template>
        <template #item.webhook_enabled="{ item }">
          <v-chip
            size="small"
            variant="tonal"
            :color="item.webhook_enabled ? 'success' : 'default'"
          >
            {{ item.webhook_enabled ? '开' : '关' }}
          </v-chip>
        </template>
        <template #item.last_indexed_at="{ item }">
          <span class="text-caption text-medium-emphasis">{{ item.last_indexed_at || '—' }}</span>
        </template>
        <template #item.actions="{ item }">
          <v-menu location="bottom end">
            <template #activator="{ props }">
              <v-btn v-bind="props" icon="mdi-dots-vertical" variant="text" size="small" />
            </template>
            <v-list density="compact" min-width="200">
              <v-list-item
                prepend-icon="mdi-database-refresh"
                title="重建 AST 索引"
                :disabled="actionLoading === item.id + ':reindex'"
                @click="onReindex(item)"
              />
              <v-list-item
                prepend-icon="mdi-source-branch"
                title="手动 Diff 分析"
                :disabled="actionLoading === item.id + ':analyze'"
                @click="onAnalyze(item)"
              />
              <v-list-item prepend-icon="mdi-pencil-outline" title="编辑" @click="openEdit(item)" />
              <v-divider />
              <v-list-item
                prepend-icon="mdi-delete-outline"
                title="删除"
                base-color="error"
                @click="askDelete(item)"
              />
            </v-list>
          </v-menu>
        </template>
      </v-data-table>
    </v-card>

    <v-dialog v-model="dialogVisible" max-width="640" scrollable>
      <v-card :title="editingId ? '编辑仓库' : '添加仓库'">
        <v-card-text>
          <v-form ref="formRef" @submit.prevent="submit">
            <v-text-field
              v-model="repoForm.clone_url"
              label="Clone URL"
              :rules="[required]"
              placeholder="https://gitlab.com/my-team/order-service.git"
              class="mb-2"
            />
            <v-text-field
              v-model="repoForm.full_name"
              label="全称"
              :rules="[required]"
              placeholder="group/project"
              class="mb-2"
              @update:model-value="fullNameManual = true"
            />
            <v-select
              v-model="repoForm.provider"
              label="来源"
              :items="providerItems"
              item-title="title"
              item-value="value"
              :rules="[required]"
              class="mb-2"
            />
            <v-select
              v-model="repoForm.auth_method"
              label="认证方式"
              :items="authItems"
              item-title="title"
              item-value="value"
              class="mb-2"
            />
            <v-text-field
              v-if="repoForm.auth_method === 'token'"
              v-model="accessToken"
              label="Access Token"
              type="password"
              :placeholder="
                editingTokenConfigured ? '已配置，留空表示不修改' : '后端静默拉取代码执行 Git Diff / AST'
              "
              class="mb-2"
            />
            <v-textarea
              v-else-if="repoForm.auth_method === 'ssh'"
              v-model="sshPrivateKey"
              label="SSH 私钥"
              rows="4"
              placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
              class="mb-2"
            />
            <v-text-field
              v-model="repoForm.scan_root"
              label="源码根目录"
              placeholder="app 或 src/main/python，默认 ."
              class="mb-2"
            />
            <v-combobox
              v-model="repoForm.test_suite_id"
              label="关联用例集"
              :items="testSuiteOptions"
              clearable
              placeholder="API 测试平台项目标识"
              class="mb-2"
            />
            <v-text-field v-model="repoForm.default_branch" label="默认分支" class="mb-2" />
            <div class="mb-4">
              <div class="text-body-2 mb-2">增量覆盖率阈值：{{ repoForm.coverage_threshold }}%</div>
              <v-slider v-model="repoForm.coverage_threshold" :min="0" :max="100" step="1" color="primary" thumb-label />
            </div>
            <v-textarea v-model="repoForm.description" label="描述" rows="2" class="mb-2" />
            <v-switch v-model="repoForm.enabled" label="启用分析" color="primary" density="comfortable" />
            <v-switch
              v-model="repoForm.webhook_enabled"
              label="接收 Webhook"
              color="primary"
              density="comfortable"
            />
          </v-form>
        </v-card-text>
        <v-card-actions class="px-4 pb-4">
          <v-spacer />
          <v-btn variant="text" @click="dialogVisible = false">取消</v-btn>
          <v-btn color="primary" variant="flat" :loading="submitLoading" @click="submit">
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
.repo-search-field {
  flex: 0 1 280px;
  width: 280px;
  min-width: 240px;
  max-width: 280px;
}
.repo-search-field :deep(.v-field) {
  border: 1px solid rgb(var(--v-theme-outline));
  box-shadow: none;
  font-size: 13px;
}
.repo-search-field :deep(.v-field__outline) {
  opacity: 0 !important;
}
.cta-repo-action {
  background-color: #f1f3f5 !important;
  color: #111315 !important;
  font-weight: 600;
}
.cta-repo-action :deep(.v-icon) {
  color: #111315 !important;
}
.repo-kpi-card {
  background-color: rgb(var(--v-theme-surface)) !important;
  border: 1px solid #2a2e35 !important;
  box-shadow: none !important;
}
.repo-table-card {
  background-color: rgb(var(--v-theme-surface)) !important;
  border: 1px solid #2a2e35 !important;
  box-shadow: none !important;
}
.empty-tip {
  max-width: 400px;
}
.repo-table :deep(.v-table) {
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
</style>