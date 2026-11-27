<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  fetchRepoBranches,
  fetchRepositories,
  humanizeRepoIndexError,
  readApiError,
  triggerRepoAnalysis,
} from '@/api/client'
import type { RepositoryItem } from '@/api/types'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean] }>()

const router = useRouter()
const loading = ref(false)
const branchesLoading = ref(false)
const submitting = ref(false)
const repos = ref<RepositoryItem[]>([])
const selectedId = ref<string | null>(null)
const branchItems = ref<string[]>([])
const defaultBranch = ref('main')
const targetBranch = ref<string | null>(null)
const compareBaseMode = ref(false)
const baseBranch = ref<string | null>(null)
const error = ref('')
const branchWarning = ref('')

const open = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const enabledRepos = computed(() => repos.value.filter((r) => r.enabled))

const selectedRepo = computed(() =>
  enabledRepos.value.find((r) => r.id === selectedId.value) ?? null,
)

async function loadRepos() {
  loading.value = true
  error.value = ''
  try {
    repos.value = await fetchRepositories()
    if (!selectedId.value && enabledRepos.value.length === 1) {
      selectedId.value = enabledRepos.value[0].id
    }
  } catch {
    error.value = '无法加载仓库列表，请确认后端 API 已启动。'
  } finally {
    loading.value = false
  }
}

async function loadBranches(repoId: string) {
  branchesLoading.value = true
  error.value = ''
  branchWarning.value = ''
  try {
    const data = await fetchRepoBranches(repoId)
    branchItems.value = data.items?.length ? data.items : [data.default_branch]
    defaultBranch.value = data.default_branch
    const repo = selectedRepo.value
    const fallback = repo?.default_branch || data.default_branch
    targetBranch.value = branchItems.value.includes(fallback)
      ? fallback
      : branchItems.value[0] ?? fallback
    const base = data.default_branch || repo?.default_branch || 'main'
    baseBranch.value = branchItems.value.includes(base) ? base : branchItems.value[0] ?? base
  } catch (err) {
    const detail = readApiError(err, '')
    const hint = detail ? humanizeRepoIndexError(detail).replace(/^索引失败：/u, '') : '请确认 API 已启动且仓库 SSH/Token 有效'
    const fb = selectedRepo.value?.default_branch ?? 'main'
    branchItems.value = [fb]
    defaultBranch.value = fb
    targetBranch.value = fb
    baseBranch.value = fb
    branchWarning.value = `无法加载远程分支列表，已回退为默认分支「${fb}」。${hint}`
  } finally {
    branchesLoading.value = false
  }
}

async function startAnalysis() {
  if (!selectedId.value) {
    error.value = '请选择要分析的仓库'
    return
  }
  submitting.value = true
  error.value = ''
  try {
    const payload: { branch?: string; base_branch?: string } = {}
    if (targetBranch.value) payload.branch = targetBranch.value
    if (compareBaseMode.value && baseBranch.value) {
      payload.base_branch = baseBranch.value
    }
    const res = await triggerRepoAnalysis(selectedId.value, payload)
    open.value = false
    await router.push(`/jobs/${res.job_id}`)
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : '触发失败'
    error.value = msg
  } finally {
    submitting.value = false
  }
}

function goRepositories() {
  open.value = false
  router.push('/repositories')
}

watch(selectedId, (id) => {
  if (id) void loadBranches(id)
})

watch(
  () => props.modelValue,
  (visible) => {
    if (visible) {
      selectedId.value = null
      targetBranch.value = null
      baseBranch.value = null
      compareBaseMode.value = false
      branchItems.value = []
      branchWarning.value = ''
      loadRepos()
    }
  },
)
</script>

<template>
  <v-dialog v-model="open" max-width="520" scrollable>
    <v-card rounded="xl" class="m3-surface-card new-analysis-dialog">
      <v-card-title class="text-subtitle-1 font-weight-medium pt-5 px-5 pb-2">新建变更分析</v-card-title>
      <v-card-subtitle class="px-5 pb-0 text-wrap">
        默认对比当前分支最新提交；开启「基准分支对比」可累计评估功能分支相对 main 的全部改动（等同 MR/PR
        三点 diff）。
      </v-card-subtitle>
      <v-card-text class="px-5 pt-4">
        <v-alert v-if="error" type="error" variant="tonal" density="compact" class="mb-3 text-body-2">
          {{ error }}
        </v-alert>
        <v-alert
          v-if="branchWarning"
          type="warning"
          variant="tonal"
          density="compact"
          class="mb-3 text-body-2"
        >
          <div>{{ branchWarning }}</div>
          <v-btn
            v-if="selectedId"
            size="small"
            variant="text"
            class="text-none px-0 mt-1"
            :loading="branchesLoading"
            @click="loadBranches(selectedId)"
          >
            重试加载分支
          </v-btn>
        </v-alert>
        <v-skeleton-loader v-if="loading" type="list-item-two-line" class="m3-skeleton-tonal" boilerplate />
        <template v-else-if="enabledRepos.length">
          <v-select
            v-model="selectedId"
            :items="enabledRepos"
            item-title="full_name"
            item-value="id"
            label="选择仓库"
            variant="outlined"
            density="comfortable"
            hide-details="auto"
            class="mb-3"
          />
          <v-skeleton-loader
            v-if="branchesLoading"
            type="list-item"
            class="m3-skeleton-tonal mb-2"
            boilerplate
          />
          <template v-else-if="selectedId">
            <v-select
              v-model="targetBranch"
              :items="branchItems"
              label="目标分支"
              variant="outlined"
              density="comfortable"
              hide-details="auto"
              class="mb-3"
              no-data-text="暂无分支"
            />
            <div class="new-analysis-branch-mode mb-3">
              <v-switch
                v-model="compareBaseMode"
                color="primary"
                density="compact"
                hide-details
                inset
                label="对比基准分支（合入 main 前全量评估）"
              />
            </div>
            <v-select
              v-if="compareBaseMode"
              v-model="baseBranch"
              :items="branchItems"
              label="基准分支"
              variant="outlined"
              density="comfortable"
              hide-details="auto"
              class="mb-2"
              no-data-text="暂无分支"
            />
            <p class="text-caption text-medium-emphasis mb-0">
              分析在后台执行，可在详情页查看调用链与门禁结论。
            </p>
          </template>
        </template>
        <div v-else class="text-center py-4">
          <v-icon icon="mdi-source-repository" size="40" color="secondary" class="mb-2" />
          <div class="text-body-2 text-medium-emphasis">尚未接入可用仓库</div>
        </div>
      </v-card-text>
      <v-card-actions class="px-5 pb-5 pt-2">
        <v-btn variant="text" class="text-none" @click="open = false">取消</v-btn>
        <v-spacer />
        <v-btn
          v-if="!enabledRepos.length && !loading"
          color="primary"
          variant="flat"
          class="text-none"
          rounded="pill"
          @click="goRepositories"
        >
          去接入仓库
        </v-btn>
        <v-btn
          v-else
          variant="flat"
          class="text-none new-analysis-start-btn"
          rounded="pill"
          :loading="submitting"
          :disabled="!selectedId || loading || branchesLoading"
          @click="startAnalysis"
        >
          开始分析
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<style scoped>
.new-analysis-branch-mode :deep(.v-label) {
  font-size: 13px;
  opacity: 0.88;
}
.new-analysis-start-btn {
  background: #ffffff !important;
  color: #121212 !important;
  font-weight: 600;
  min-width: 108px;
}
.new-analysis-start-btn:hover {
  background: #f0f0f0 !important;
}
.new-analysis-start-btn.v-btn--disabled {
  opacity: 0.45;
}
</style>