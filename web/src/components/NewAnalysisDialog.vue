<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { fetchRepositories, triggerRepoAnalysis } from '@/api/client'
import type { RepositoryItem } from '@/api/types'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean] }>()

const router = useRouter()
const loading = ref(false)
const submitting = ref(false)
const repos = ref<RepositoryItem[]>([])
const selectedId = ref<string | null>(null)
const error = ref('')

const open = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const enabledRepos = computed(() => repos.value.filter((r) => r.enabled))

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

async function startAnalysis() {
  if (!selectedId.value) {
    error.value = '请选择要分析的仓库'
    return
  }
  submitting.value = true
  error.value = ''
  try {
    const res = await triggerRepoAnalysis(selectedId.value)
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

watch(
  () => props.modelValue,
  (visible) => {
    if (visible) {
      selectedId.value = null
      loadRepos()
    }
  },
)
</script>

<template>
  <v-dialog v-model="open" max-width="480" scrollable>
    <v-card rounded="xl" class="m3-surface-card">
      <v-card-title class="text-subtitle-1 font-weight-medium pt-5 px-5 pb-2">新建变更分析</v-card-title>
      <v-card-subtitle class="px-5 pb-0 text-wrap">
        对比仓库当前 HEAD 与上一提交，生成影响 API 与质量门禁结果。
      </v-card-subtitle>
      <v-card-text class="px-5 pt-4">
        <v-alert v-if="error" type="error" variant="tonal" density="compact" class="mb-3 text-body-2">
          {{ error }}
        </v-alert>
        <v-skeleton-loader v-if="loading" type="list-item-two-line" />
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
            class="mb-2"
          />
          <p class="text-caption text-medium-emphasis mb-0">
            分析在后台执行，可在详情页查看调用链与门禁结论。
          </p>
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
          color="primary"
          variant="flat"
          class="text-none"
          rounded="pill"
          :loading="submitting"
          :disabled="!selectedId || loading"
          @click="startAnalysis"
        >
          开始分析
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>