<script setup lang="ts">
import axios from 'axios'
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  deleteTestSuite,
  fetchTestSuites,
  readApiError,
  syncTestSuite,
  updateTestSuite,
  type TestSuiteItem,
  type TestSuiteSourceType,
} from '@/api/client'
import Md3LoadState from '@/components/Md3LoadState.vue'

const router = useRouter()

const tsActionTooltipBase = {
  location: 'top' as const,
  openDelay: 120,
  offset: 8,
  contentClass: 'ts-row-tooltip',
}

const loading = ref(false)
const loadError = ref<string | null>(null)
const keyword = ref('')
const rows = ref<TestSuiteItem[]>([])
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
const deleteDialog = ref(false)
const deleteTarget = ref<TestSuiteItem | null>(null)

const syncingId = ref<string | null>(null)

const snackbar = ref({ show: false, text: '', color: 'success' as 'success' | 'error' })

const sourceLabel: Record<TestSuiteSourceType, string> = {
  git: 'Git 仓库',
  webhook: 'Webhook',
  manual: '手工登记',
}

function notify(text: string, color: 'success' | 'error' = 'success') {
  snackbar.value = { show: true, text, color }
}

const headers = [
  { title: '标识 (slug)', key: 'slug', width: '20%' },
  { title: '显示名称', key: 'name', width: '25%' },
  { title: '来源', key: 'source_type', width: '15%', align: 'center' as const },
  { title: '索引 / 用例', key: 'index_stats', width: '10%', align: 'center' as const },
  { title: '关联仓库', key: 'repo_count', width: '10%', align: 'center' as const },
  { title: '启用', key: 'enabled', width: '10%', align: 'center' as const },
  { title: '操作', key: 'actions', sortable: false, width: '10%', align: 'center' as const },
]

function sourceChipClass(source: TestSuiteSourceType | undefined | null) {
  const s = source || 'manual'
  if (s === 'manual') return 'ts-src-chip--manual'
  if (s === 'git') return 'ts-src-chip--git'
  return 'ts-src-chip--webhook'
}

const apiStaleHint = computed(
  () =>
    loadError.value &&
    (loadError.value.includes('404') ||
      loadError.value.toLowerCase().includes('not found') ||
      loadError.value.includes('未找到')),
)

async function load() {
  loading.value = true
  loadError.value = null
  try {
    rows.value = await fetchTestSuites(keyword.value.trim() || undefined)
  } catch (err) {
    rows.value = []
    const msg = readApiError(err, '加载用例集失败')
    loadError.value = msg
    notify(msg, 'error')
    if (axios.isAxiosError(err) && err.response?.status === 404) {
      loadError.value =
        '接口 /api/v1/test-suites 不可用（多为 API 未重启，仍在跑旧代码）。请执行 scripts\\run_api.ps1 后刷新本页。'
    }
  } finally {
    loading.value = false
  }
}

function openCreate() {
  void router.push({ name: 'test-suite-create' })
}

function openEdit(row: TestSuiteItem) {
  void router.push({ name: 'test-suite-edit', params: { id: row.id } })
}

function askDelete(row: TestSuiteItem) {
  deleteTarget.value = row
  deleteDialog.value = true
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  try {
    await deleteTestSuite(deleteTarget.value.id)
    deleteDialog.value = false
    deleteTarget.value = null
    notify('已删除')
    await load()
  } catch (err) {
    notify(readApiError(err, '删除失败'), 'error')
  }
}

async function runSync(row: TestSuiteItem) {
  syncingId.value = row.id
  try {
    const result = await syncTestSuite(row.id)
    row.indexed_api_count = result.indexed_api_count
    row.case_count = result.case_count
    row.last_synced_at = result.last_synced_at
    notify(result.message || '同步完成')
    await load()
  } catch (err) {
    notify(readApiError(err, '同步失败'), 'error')
  } finally {
    syncingId.value = null
  }
}

function formatIndexStats(row: TestSuiteItem) {
  if ((row.source_type || 'manual') === 'manual' && !row.case_count) return '—'
  return `覆盖 ${row.indexed_api_count || 0} 个 API · 共 ${row.case_count || 0} 条`
}

async function toggleEnabled(row: TestSuiteItem, enabled: boolean | null) {
  if (enabled === null) return
  try {
    await updateTestSuite(row.id, { enabled })
    row.enabled = enabled
  } catch (err) {
    notify(readApiError(err, '更新失败'), 'error')
    row.enabled = !enabled
  }
}

let debounce: number | undefined
watch(keyword, () => {
  if (debounce) window.clearTimeout(debounce)
  debounce = window.setTimeout(() => void load(), 320)
})

watch(tableItemsPerPage, () => {
  tablePage.value = 1
})
watch(tablePageCount, (n) => {
  if (tablePage.value > n) tablePage.value = n
})

onMounted(() => void load())
</script>

<template>
  <div class="ts-page">
    <div class="ts-page-rail">
    <header class="ts-page-head">
      <div>
        <h2 class="ts-page-title">用例集管理</h2>
        <p class="ts-page-sub">登记 API 测试平台用例集标识，供仓库「关联用例集」下拉选用。</p>
      </div>
      <div class="ts-toolbar">
        <v-text-field
          v-model="keyword"
          class="ts-search"
          density="compact"
          variant="solo-filled"
          flat
          hide-details
          rounded="lg"
          placeholder="搜索标识 / 名称"
          prepend-inner-icon="mdi-magnify"
          clearable
        />
        <v-btn
          class="text-none ts-create-btn cta-new-analysis cta-new-analysis--ghost"
          color="primary"
          size="small"
          variant="outlined"
          rounded="pill"
          prepend-icon="mdi-plus"
          @click="openCreate"
        >
          新建用例集
        </v-btn>
      </div>
    </header>

    <v-alert
      v-if="loadError"
      type="warning"
      variant="tonal"
      density="comfortable"
      class="ts-api-alert"
      prominent
    >
      <div class="ts-api-alert__text">{{ loadError }}</div>
      <v-btn
        v-if="apiStaleHint"
        class="text-none mt-2"
        size="small"
        variant="outlined"
        color="warning"
        @click="load"
      >
        重试
      </v-btn>
    </v-alert>

    <Md3LoadState v-if="loading && rows.length === 0" mode="skeleton" skeleton-type="table-heading, table-row-divider@4" />

    <v-card v-else class="ts-table-card" rounded="lg" elevation="0">
      <v-data-table
        v-model:page="tablePage"
        v-model:items-per-page="tableItemsPerPage"
        :headers="headers"
        :items="rows"
        :loading="loading"
        item-value="id"
        hover
        class="ts-table"
        :items-per-page-options="tablePerPageOptions"
      >
        <template #bottom>
          <div class="ts-pagination-wrapper">
            <div class="ts-pagination-left">
              <span class="ts-pagination-label">每页</span>
              <v-select
                v-model="tableItemsPerPage"
                :items="tablePerPageOptions"
                density="compact"
                hide-details
                variant="solo"
                flat
                class="ts-page-size-select"
                menu-icon="mdi-menu-down"
              />
            </div>
            <div class="ts-pagination-right">
              <span class="ts-page-text">
                {{ tableRangeStart }}-{{ tableRangeEnd }} 共 {{ rows.length }}
              </span>
              <div class="ts-page-buttons" role="navigation" aria-label="表格分页">
                <v-btn
                  v-for="btn in paginationNavButtons"
                  :key="btn.id"
                  class="ts-page-btn"
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
        <template #item.slug="{ item }">
          <span class="ts-cell-slug mono">{{ item.slug }}</span>
        </template>
        <template #item.name="{ item }">
          <span class="ts-cell-name">{{ item.name }}</span>
        </template>
        <template #item.source_type="{ item }">
          <div class="ts-cell-center">
            <v-chip
              size="x-small"
              variant="flat"
              class="ts-src-chip"
              :class="sourceChipClass(item.source_type)"
            >
              {{ sourceLabel[(item.source_type || 'manual') as TestSuiteSourceType] }}
            </v-chip>
          </div>
        </template>
        <template #item.index_stats="{ item }">
          <div class="ts-cell-center ts-index-cell">
            <span class="ts-cell-muted">{{ formatIndexStats(item) }}</span>
          </div>
        </template>
        <template #item.repo_count="{ item }">
          <div class="ts-cell-center ts-cell-num">{{ item.repo_count }}</div>
        </template>
        <template #item.enabled="{ item }">
          <div class="ts-cell-center">
            <v-switch
              :model-value="item.enabled"
              color="primary"
              density="compact"
              hide-details
              class="ts-table-switch"
              @update:model-value="(v) => toggleEnabled(item, v)"
            />
          </div>
        </template>
        <template #item.actions="{ item }">
          <div class="ts-row-actions">
            <v-tooltip
              v-if="item.source_type !== 'manual'"
              v-bind="tsActionTooltipBase"
            >
              <template #activator="{ props: tip }">
                <span class="ts-action-tip-wrap" v-bind="tip">
                  <v-btn
                    icon="mdi-sync"
                    variant="text"
                    size="small"
                    class="ts-action-btn"
                    :loading="syncingId === item.id"
                    aria-label="同步用例"
                    @click="runSync(item)"
                  />
                </span>
              </template>
              同步用例
            </v-tooltip>
            <v-tooltip v-bind="tsActionTooltipBase">
              <template #activator="{ props: tip }">
                <span class="ts-action-tip-wrap" v-bind="tip">
                  <v-btn
                    icon="mdi-pencil-outline"
                    variant="text"
                    size="small"
                    class="ts-action-btn"
                    aria-label="编辑"
                    @click="openEdit(item)"
                  />
                </span>
              </template>
              编辑
            </v-tooltip>
            <v-tooltip v-bind="{ ...tsActionTooltipBase, contentClass: 'ts-row-tooltip ts-row-tooltip--danger' }">
              <template #activator="{ props: tip }">
                <span class="ts-action-tip-wrap" v-bind="tip">
                  <v-btn
                    icon="mdi-delete-outline"
                    variant="text"
                    size="small"
                    class="ts-action-btn ts-action-btn--danger"
                    aria-label="删除"
                    @click="askDelete(item)"
                  />
                </span>
              </template>
              删除
            </v-tooltip>
          </div>
        </template>
      </v-data-table>
    </v-card>
    </div>


    <v-dialog v-model="deleteDialog" max-width="400">
      <v-card rounded="lg">
        <v-card-title>删除用例集？</v-card-title>
        <v-card-text>
          将删除「{{ deleteTarget?.name }}」。仍有仓库关联时无法删除。
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
      :color="snackbar.color"
      location="top"
      class="ts-feedback-snackbar"
      :timeout="4000"
    >
      {{ snackbar.text }}
    </v-snackbar>
  </div>
</template>

<style scoped>
.ts-page {
  width: 100%;
  max-width: 100%;
  margin: 0;
  padding: 0 0 32px;
  box-sizing: border-box;
  color: rgba(255, 255, 255, 0.9);
}
.ts-page-rail {
  width: 100%;
  max-width: 100%;
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}
.ts-page-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  width: 100%;
  box-sizing: border-box;
  margin-bottom: 20px;
  padding: 0 0 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.ts-page-title {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 700;
  color: #f3f4f6;
}
.ts-page-sub {
  margin: 6px 0 0;
  font-size: 0.8125rem;
  color: rgba(255, 255, 255, 0.48);
}
.ts-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
}
.ts-search {
  width: 260px;
}
.ts-search :deep(.v-field) {
  min-height: 40px !important;
  height: 40px !important;
  background: rgba(255, 255, 255, 0.05) !important;
  border: 1px solid rgba(255, 255, 255, 0.12) !important;
  border-radius: 8px;
  box-shadow: none !important;
}
.ts-search :deep(.v-field__input) {
  min-height: 40px;
  padding-top: 0;
  padding-bottom: 0;
  font-size: 13px;
}
.ts-search :deep(input::placeholder) {
  color: rgba(255, 255, 255, 0.48) !important;
  opacity: 1;
}
.ts-search :deep(.v-field__prepend-inner .v-icon) {
  color: rgba(255, 255, 255, 0.38) !important;
  opacity: 1;
}
.ts-create-btn {
  height: 40px !important;
  min-height: 40px !important;
}
.ts-create-btn :deep(.v-btn__prepend) {
  margin-inline-end: 8px !important;
}
.ts-api-alert {
  margin-bottom: 16px;
  border: 1px solid rgba(253, 214, 99, 0.25);
}
.ts-api-alert__text {
  font-size: 13px;
  line-height: 1.5;
  color: rgba(255, 255, 255, 0.88);
}
.ts-table-card {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: #1c1c1c !important;
  overflow: hidden;
  margin-inline: 0;
  padding: 0 !important;
}
.ts-table-card :deep(.v-card-item),
.ts-table-card :deep(.v-card-text) {
  padding: 0 !important;
}
.ts-table {
  width: 100%;
}
.ts-table :deep(table) {
  table-layout: fixed;
  width: 100%;
}
.ts-table :deep(.v-data-table__thead th) {
  color: rgba(255, 255, 255, 0.6) !important;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.03em;
  background: #1c1c1c !important;
  padding: 12px 16px !important;
  vertical-align: middle;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08) !important;
}
.ts-table :deep(.v-data-table__td) {
  color: rgba(255, 255, 255, 0.88) !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05) !important;
  background: #1c1c1c !important;
  padding: 16px !important;
  vertical-align: middle;
}
.ts-table :deep(.v-data-table-header__content) {
  justify-content: inherit;
}
.ts-table :deep(.v-data-table__tr:hover > .v-data-table__td) {
  background: rgba(255, 255, 255, 0.05) !important;
}
.ts-table :deep(tbody .v-data-table__tr:last-child .v-data-table__td) {
  border-bottom: none !important;
}
.ts-cell-slug {
  color: #ffffff !important;
  font-size: 13px;
  font-weight: 500;
}
.ts-cell-name {
  color: rgba(255, 255, 255, 0.78);
  font-size: 14px;
}
.ts-cell-muted {
  color: rgba(255, 255, 255, 0.42);
  font-size: 12px;
}
.ts-cell-center {
  display: flex;
  justify-content: center;
  width: 100%;
}
.ts-cell-num {
  font-variant-numeric: tabular-nums;
  color: rgba(255, 255, 255, 0.72);
}
.ts-src-chip {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
  border-radius: 6px !important;
  height: 22px !important;
}
.ts-src-chip--manual {
  background: rgba(255, 255, 255, 0.1) !important;
  color: rgba(255, 255, 255, 0.88) !important;
}
.ts-src-chip--git,
.ts-src-chip--webhook {
  background: rgba(59, 130, 246, 0.1) !important;
  color: #93c5fd !important;
}
.ts-webhook-hint {
  color: rgba(255, 255, 255, 0.45);
  line-height: 1.45;
}
.ts-webhook-hint .mono {
  color: rgba(138, 180, 248, 0.9);
}
.ts-feedback-snackbar {
  top: 72px !important;
  bottom: auto !important;
}
.ts-index-cell {
  font-size: 11px;
  line-height: 1.35;
  padding-inline: 4px;
}
.ts-row-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  position: relative;
}
.ts-action-tip-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  line-height: 0;
  vertical-align: middle;
}
.ts-table :deep(.ts-row-actions .v-tooltip__activator) {
  display: inline-flex !important;
  width: 28px !important;
  max-width: 28px !important;
  justify-content: center;
  align-items: center;
}
.ts-action-btn {
  width: 28px !important;
  height: 28px !important;
  min-width: 28px !important;
  border-radius: 999px !important;
  color: rgba(255, 255, 255, 0.6) !important;
}
.ts-action-btn:hover {
  background: rgba(255, 255, 255, 0.1) !important;
  color: rgba(255, 255, 255, 0.92) !important;
}
.ts-action-btn--danger:hover {
  color: #f87171 !important;
  background: rgba(248, 113, 113, 0.14) !important;
}
.ts-table-switch :deep(.v-switch__track) {
  opacity: 1 !important;
  background-color: rgba(255, 255, 255, 0.22) !important;
}
.ts-table-switch :deep(.v-switch__thumb) {
  background-color: rgba(255, 255, 255, 0.88) !important;
  color: rgba(255, 255, 255, 0.88) !important;
}
.ts-table-switch.v-input--dirty :deep(.v-switch__track) {
  background-color: rgba(59, 130, 246, 0.8) !important;
}
.ts-table-switch.v-input--dirty :deep(.v-switch__thumb) {
  background-color: #ffffff !important;
}
.ts-table :deep(.v-data-table-footer) {
  padding: 0 !important;
  margin: 0 !important;
  min-height: 0 !important;
  border: none !important;
  background: transparent !important;
}
.ts-table :deep(.v-divider) {
  display: none !important;
  border-color: transparent !important;
  opacity: 0 !important;
}
.ts-pagination-wrapper {
  border-top: 1px solid rgba(255, 255, 255, 0.05);
  padding: 16px 20px 18px;
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 12px 16px;
  background: #181818;
}
.ts-pagination-left {
  display: flex;
  align-items: center;
  gap: 10px;
  color: rgba(255, 255, 255, 0.5);
  font-size: 13px;
}
.ts-pagination-right {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-inline-start: auto;
}
.ts-page-text {
  color: rgba(255, 255, 255, 0.5);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.ts-page-size-select {
  width: 88px;
  flex: 0 0 88px;
}
.ts-page-size-select :deep(.v-field) {
  min-height: 34px !important;
  height: 34px !important;
  background-color: rgba(255, 255, 255, 0.05) !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  border-radius: 8px;
  font-size: 13px;
}
.ts-page-size-select :deep(.v-field__input) {
  min-height: 34px;
  padding: 0 12px !important;
  justify-content: center;
  text-align: center;
}
.ts-page-size-select :deep(.v-field__outline),
.ts-page-size-select :deep(.v-field__overlay) {
  opacity: 0 !important;
}
.ts-page-buttons {
  display: flex;
  align-items: center;
  gap: 4px;
}
.ts-pagination-wrapper .ts-page-btn {
  width: 32px !important;
  min-width: 32px !important;
  height: 32px !important;
  border-radius: 8px;
  color: rgba(255, 255, 255, 0.6) !important;
  background: transparent !important;
}
.ts-pagination-wrapper .ts-page-btn :deep(.v-btn__overlay),
.ts-pagination-wrapper .ts-page-btn :deep(.v-btn__underlay) {
  opacity: 0 !important;
}
.ts-pagination-wrapper .ts-page-btn:hover:not(.v-btn--disabled) {
  background-color: rgba(255, 255, 255, 0.08) !important;
  color: #ffffff !important;
}
.ts-pagination-wrapper .ts-page-btn.v-btn--disabled {
  opacity: 0.3 !important;
  color: rgba(255, 255, 255, 0.35) !important;
}
.ts-cell-slug.mono {
  font-family: ui-monospace, Consolas, 'Courier New', monospace;
}
.mono {
  font-family: ui-monospace, Consolas, 'Courier New', monospace;
  font-size: 12px;
}
</style>

<style>
/* 表格行内操作 tooltip（teleport 到 body，需全局样式） */
.v-overlay__content.ts-row-tooltip {
  background: #2c2c2c !important;
  color: #ffffff !important;
  width: max-content !important;
  max-width: none !important;
  min-width: 0 !important;
  padding: 6px 12px !important;
  margin-bottom: 8px;
  font-size: 12px !important;
  font-weight: 500;
  line-height: 1.35 !important;
  text-align: center;
  border-radius: 6px !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5) !important;
  opacity: 1 !important;
}
.v-overlay__content.ts-row-tooltip .v-tooltip__content {
  padding: 0 !important;
  color: #ffffff !important;
  font-size: 12px !important;
  line-height: 1.35 !important;
}
.v-overlay__content.ts-row-tooltip::after {
  content: '';
  position: absolute;
  left: 50%;
  bottom: -4px;
  width: 8px;
  height: 8px;
  margin-left: -4px;
  transform: rotate(45deg);
  background: #2c2c2c;
  border-right: 1px solid rgba(255, 255, 255, 0.1);
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  pointer-events: none;
}
.v-overlay__content.ts-row-tooltip--danger,
.v-overlay__content.ts-row-tooltip--danger .v-tooltip__content {
  color: #f87171 !important;
}
</style>