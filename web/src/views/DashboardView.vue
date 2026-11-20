<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { fetchJobs } from '@/api/client'
import type { JobListItem } from '@/api/types'

const router = useRouter()
const loading = ref(false)
const jobs = ref<JobListItem[]>([])

const headers = [
  { title: '仓库', key: 'repo' },
  { title: '分支', key: 'ref' },
  { title: '来源', key: 'provider' },
  { title: '状态', key: 'status' },
  { title: '影响 API', key: 'api_count' },
  { title: '提交', key: 'shas' },
  { title: '创建时间', key: 'created_at' },
]

function statusColor(s: string) {
  if (s === 'completed') return 'success'
  if (s === 'failed') return 'error'
  if (s === 'running') return 'warning'
  return 'default'
}

async function load() {
  loading.value = true
  try {
    jobs.value = await fetchJobs()
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="d-flex align-center justify-space-between mb-4">
      <h2 class="text-h5 font-weight-bold">变更影响分析</h2>
      <v-btn color="primary" :loading="loading" prepend-icon="mdi-refresh" @click="load">刷新</v-btn>
    </div>
    <v-card>
      <v-data-table
        :headers="headers"
        :items="jobs"
        :loading="loading"
        item-value="id"
        hover
        @click:row="(_: unknown, ctx: { item: JobListItem }) => router.push(`/jobs/${ctx.item.id}`)"
      >
        <template #item.status="{ item }">
          <v-chip :color="statusColor(item.status)" size="small" variant="tonal">{{ item.status }}</v-chip>
        </template>
        <template #item.ref="{ item }">
          <span class="mono">{{ item.ref }}</span>
        </template>
        <template #item.shas="{ item }">
          <span class="mono">{{ item.base_sha }} → {{ item.head_sha }}</span>
        </template>
      </v-data-table>
    </v-card>
  </div>
</template>