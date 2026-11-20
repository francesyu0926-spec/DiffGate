<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import CallGraphG6 from '@/components/CallGraphG6.vue'
import { fetchJob, fetchJobGraph } from '@/api/client'
import type { JobDetail, JobGraph } from '@/api/types'

const props = defineProps<{ id: string }>()

const job = ref<JobDetail | null>(null)
const graph = ref<JobGraph | null>(null)
const loading = ref(false)
let timer: number | undefined

const apis = computed(() => job.value?.affected_apis?.apis ?? [])
const callPaths = computed(
  () => job.value?.affected_apis?.call_paths ?? [],
)
const suspects = computed(() => job.value?.changed_symbols?.suspects ?? [])
const symbols = computed(() => job.value?.changed_symbols?.symbols ?? [])

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    job.value = await fetchJob(props.id)
    if (job.value.status === 'completed') {
      try {
        graph.value = await fetchJobGraph(props.id)
      } catch {
        graph.value = null
      }
      clearPoll()
    }
  } finally {
    if (!silent) loading.value = false
  }
}

function schedulePoll() {
  clearPoll()
  if (job.value && ['pending', 'running'].includes(job.value.status)) {
    timer = window.setInterval(() => load(true), 3000)
  }
}

function clearPoll() {
  if (timer) window.clearInterval(timer)
}

onMounted(async () => {
  await load()
  schedulePoll()
})

onUnmounted(clearPoll)
</script>

<template>
  <div v-loading="loading" class="page">
    <el-page-header @back="$router.push('/analysis')">
      <template #content>
        <span class="mono">{{ job?.repo ?? props.id }}</span>
      </template>
    </el-page-header>

    <el-row :gutter="16" class="meta">
      <el-col :span="6"><el-statistic title="状态" :value="job?.status ?? '-'" /></el-col>
      <el-col :span="6"><el-statistic title="影响 API" :value="apis.length" /></el-col>
      <el-col :span="6"><el-statistic title="变更符号" :value="symbols.length" /></el-col>
      <el-col :span="6"><el-statistic title="分支" :value="job?.ref ?? '-'" /></el-col>
    </el-row>

    <el-alert
      v-if="job?.error_message"
      type="error"
      :title="job.error_message"
      show-icon
      :closable="false"
      class="mb"
    />

    <h3>调用链影响面（G6）</h3>
    <CallGraphG6 :data="graph" />

    <h3>逆向追溯链路（Step 3 → 4）</h3>
    <el-table :data="callPaths" size="small" stripe empty-text="完成后展示 BFS 调用链">
      <el-table-column prop="method" label="方法" width="80" />
      <el-table-column prop="path" label="接口" min-width="160" />
      <el-table-column label="调用链" min-width="320">
        <template #default="{ row }">
          <span class="chain">{{ row.chain_labels.join(' → ') }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="layers" label="层数" width="70" />
    </el-table>

    <el-row :gutter="16" class="lists">
      <el-col :span="12">
        <h3>受影响接口</h3>
        <el-table :data="apis" size="small" stripe>
          <el-table-column prop="method" label="方法" width="80" />
          <el-table-column prop="path" label="路径" />
          <el-table-column prop="handler" label="Handler" show-overflow-tooltip />
        </el-table>
      </el-col>
      <el-col :span="12">
        <h3>嫌疑函数（Step 2）</h3>
        <el-table :data="suspects" size="small" stripe empty-text="无 Git 命中或展示符号列表">
          <el-table-column prop="qualified_name" label="函数" show-overflow-tooltip />
          <el-table-column label="行号" width="120">
            <template #default="{ row }">{{ row.start_line }}-{{ row.end_line }}</template>
          </el-table-column>
        </el-table>
        <el-scrollbar v-if="!suspects.length" height="120px">
          <ul class="sym-list">
            <li v-for="s in symbols" :key="s">{{ s }}</li>
          </ul>
        </el-scrollbar>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.meta {
  margin-top: 4px;
}
.lists h3,
.page > h3 {
  margin: 8px 0;
  font-size: 16px;
}
.chain {
  font-size: 12px;
}
.sym-list {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
}
.mb {
  margin-bottom: 4px;
}
</style>