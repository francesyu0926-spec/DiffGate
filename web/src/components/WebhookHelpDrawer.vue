<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ visible: boolean; baseUrl?: string }>()
const emit = defineEmits<{ 'update:visible': [boolean] }>()

const open = computed({
  get: () => props.visible,
  set: (v: boolean) => emit('update:visible', v),
})

const origin = computed(() => props.baseUrl || window.location.origin.replace(':5173', ':8010'))

const githubUrl = computed(() => `${origin.value}/api/v1/webhooks/github`)
const gitlabUrl = computed(() => `${origin.value}/api/v1/webhooks/gitlab`)
</script>

<template>
  <v-navigation-drawer v-model="open" location="right" temporary width="420">
    <v-toolbar title="Webhook 配置指引" />
    <v-card-text>
      <p class="text-body-2 text-medium-emphasis mb-4">
        在 Git 平台配置 Push / Merge Request 回调地址，即可自动触发 AST 逆向追溯。
      </p>
      <v-list lines="two" border rounded="lg">
        <v-list-item title="GitHub URL" :subtitle="githubUrl" />
        <v-list-item title="GitLab URL" :subtitle="gitlabUrl" />
        <v-list-item
          title="Secret"
          subtitle="服务端 .env 中 WEBHOOK_SECRET_GITHUB / WEBHOOK_SECRET_GITLAB"
        />
      </v-list>
      <v-alert type="success" variant="tonal" class="mt-4" text="建议事件：Pull Request、Push（GitHub）；Merge Request、Push（GitLab）" />
    </v-card-text>
  </v-navigation-drawer>
</template>