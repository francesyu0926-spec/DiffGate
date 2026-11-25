<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { fetchSystemStatus } from '@/api/client'

const props = defineProps<{ visible: boolean; baseUrl?: string }>()
const emit = defineEmits<{ 'update:visible': [boolean] }>()

const open = computed({
  get: () => props.visible,
  set: (v: boolean) => emit('update:visible', v),
})

const status = ref<Awaited<ReturnType<typeof fetchSystemStatus>> | null>(null)

const localApiOrigin = computed(
  () => props.baseUrl || `${window.location.protocol}//${window.location.hostname}:8000`,
)

const githubUrl = computed(
  () => status.value?.webhook_github_url || `${localApiOrigin.value}/api/v1/webhooks/github`,
)
const gitlabUrl = computed(
  () => status.value?.webhook_gitlab_url || `${localApiOrigin.value}/api/v1/webhooks/gitlab`,
)

const secretHint = computed(() => {
  const gh = status.value?.webhook_secret_github_configured
  const gl = status.value?.webhook_secret_gitlab_configured
  if (gh && gl) return '已在服务端 .env 配置（与 Git 平台 Secret 保持一致）'
  if (gh || gl) return '部分已配置；请补全 .env 中 WEBHOOK_SECRET_* 并重启 API'
  return '请在 .env 设置 WEBHOOK_SECRET_GITHUB / WEBHOOK_SECRET_GITLAB（可运行 setup_webhook_ngrok.ps1）'
})

watch(
  () => open.value,
  async (v) => {
    if (!v) return
    try {
      status.value = await fetchSystemStatus()
    } catch {
      status.value = null
    }
  },
)
</script>

<template>
  <v-navigation-drawer v-model="open" location="right" temporary width="440">
    <v-toolbar title="Webhook 配置指引" />
    <v-card-text>
      <p class="text-body-2 text-medium-emphasis mb-4">
        在 Git 平台配置 Push / Merge Request 回调地址，即可自动触发 AST 逆向追溯。本地公网请使用
        <code class="text-caption">scripts/setup_webhook_ngrok.ps1</code>。
      </p>
      <v-alert
        v-if="status?.webhook_public_base_url"
        type="info"
        variant="tonal"
        density="comfortable"
        class="mb-4"
        :text="`公网基址：${status.webhook_public_base_url}`"
      />
      <v-list lines="two" border rounded="lg">
        <v-list-item title="GitHub Payload URL" :subtitle="githubUrl" />
        <v-list-item title="GitLab Payload URL" :subtitle="gitlabUrl" />
        <v-list-item title="Secret" :subtitle="secretHint" />
      </v-list>
      <v-alert
        type="success"
        variant="tonal"
        class="mt-4"
        text="GitHub：Content type 选 application/json；事件选 Push + Pull requests。Secret 与 .env 中 WEBHOOK_SECRET_GITHUB 一致。"
      />
    </v-card-text>
  </v-navigation-drawer>
</template>