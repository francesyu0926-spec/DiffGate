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
const copyHint = ref<string | null>(null)
let copyHintTimer: number | undefined

const localApiOrigin = computed(
  () => props.baseUrl || `${window.location.protocol}//${window.location.hostname}:8000`,
)

const publicBaseUrl = computed(
  () => status.value?.webhook_public_base_url?.trim() || null,
)

const githubUrl = computed(
  () => status.value?.webhook_github_url || `${localApiOrigin.value}/api/v1/webhooks/github`,
)
const gitlabUrl = computed(
  () => status.value?.webhook_gitlab_url || `${localApiOrigin.value}/api/v1/webhooks/gitlab`,
)

const secretReady = computed(
  () =>
  !!status.value?.webhook_secret_github_configured &&
  !!status.value?.webhook_secret_gitlab_configured,
)

const secretPartial = computed(
  () =>
    !!status.value &&
    (!!status.value.webhook_secret_github_configured ||
      !!status.value.webhook_secret_gitlab_configured) &&
    !secretReady.value,
)

async function copyText(text: string, label: string) {
  try {
    await navigator.clipboard.writeText(text)
    copyHint.value = label
    if (copyHintTimer) window.clearTimeout(copyHintTimer)
    copyHintTimer = window.setTimeout(() => {
      copyHint.value = null
    }, 2000)
  } catch {
    copyHint.value = '复制失败，请手动选择'
    copyHintTimer = window.setTimeout(() => {
      copyHint.value = null
    }, 2500)
  }
}

function closeDrawer() {
  open.value = false
}

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
  <v-navigation-drawer
    v-model="open"
    location="right"
    temporary
    width="440"
    class="webhook-help-drawer"
  >
    <header class="whd-header">
      <div class="whd-header__text">
        <div class="whd-header__title">
          <v-icon icon="mdi-transit-connection-variant" size="22" class="whd-header__title-icon" />
          <span>Webhook 配置指引</span>
        </div>
        <p class="whd-header__sub">配置 Git 回调地址以自动触发 AST 逆向追溯。</p>
      </div>
      <v-btn
        class="whd-header__close"
        icon="mdi-close"
        variant="text"
        size="small"
        aria-label="关闭"
        @click="closeDrawer"
      />
    </header>

    <v-divider class="whd-divider" />

    <div class="whd-body">
      <p class="whd-lead">
        在 GitHub / GitLab 仓库设置中填写下方 Payload URL。本地需公网回调时，可运行
        <code class="whd-inline-code">scripts/setup_webhook_ngrok.ps1</code>
        建立隧道。
      </p>

      <section
        v-if="publicBaseUrl"
        class="whd-card whd-card--public"
        aria-labelledby="whd-public-label"
      >
        <div class="whd-card__label" id="whd-public-label">公网基址</div>
        <div class="whd-card__row">
          <code class="whd-url mono">{{ publicBaseUrl }}</code>
          <v-btn
            class="whd-copy-btn text-none"
            variant="text"
            size="small"
            prepend-icon="mdi-content-copy"
            @click="copyText(publicBaseUrl, '公网基址已复制')"
          >
            复制
          </v-btn>
        </div>
      </section>

      <section class="whd-card" aria-labelledby="whd-gh-label">
        <div class="whd-card__label" id="whd-gh-label">GitHub Payload URL</div>
        <div class="whd-card__row">
          <code class="whd-url mono">{{ githubUrl }}</code>
          <v-btn
            class="whd-copy-btn text-none"
            variant="text"
            size="small"
            prepend-icon="mdi-content-copy"
            @click="copyText(githubUrl, 'GitHub URL 已复制')"
          >
            复制
          </v-btn>
        </div>
      </section>

      <section class="whd-card" aria-labelledby="whd-gl-label">
        <div class="whd-card__label" id="whd-gl-label">GitLab Payload URL</div>
        <div class="whd-card__row">
          <code class="whd-url mono">{{ gitlabUrl }}</code>
          <v-btn
            class="whd-copy-btn text-none"
            variant="text"
            size="small"
            prepend-icon="mdi-content-copy"
            @click="copyText(gitlabUrl, 'GitLab URL 已复制')"
          >
            复制
          </v-btn>
        </div>
      </section>

      <section class="whd-card whd-card--secret" aria-labelledby="whd-secret-label">
        <div class="whd-card__label whd-card__label--secret" id="whd-secret-label">
          <v-icon icon="mdi-shield-lock-outline" size="18" />
          Secret
        </div>
        <p class="whd-secret-text mb-0">
          <template v-if="secretReady">
            服务端 <code class="whd-inline-code">.env</code> 已配置（与 Git 平台 Secret 一致）。
          </template>
          <template v-else-if="secretPartial">
            部分已配置；请补全 <code class="whd-inline-code">.env</code> 中
            <code class="whd-inline-code whd-inline-code--accent">WEBHOOK_SECRET_GITHUB</code>
            /
            <code class="whd-inline-code whd-inline-code--accent">WEBHOOK_SECRET_GITLAB</code>
            并重启 API。
          </template>
          <template v-else>
            请在 <code class="whd-inline-code">.env</code> 设置
            <code class="whd-inline-code whd-inline-code--accent">WEBHOOK_SECRET_GITHUB</code>
            /
            <code class="whd-inline-code whd-inline-code--accent">WEBHOOK_SECRET_GITLAB</code>
            （可借助上述 ngrok 脚本）。
          </template>
        </p>
      </section>

      <section class="whd-status" :class="secretReady ? 'whd-status--ok' : 'whd-status--hint'">
        <v-icon
          :icon="secretReady ? 'mdi-check-circle-outline' : 'mdi-information-outline'"
          size="22"
          class="whd-status__icon"
        />
        <div class="whd-status__text">
          <div class="whd-status__title">
            {{ secretReady ? 'GitHub 配置已就绪' : 'GitHub 仓库侧检查项' }}
          </div>
          <p class="whd-status__desc mb-0">
            Content type 选 <code class="whd-inline-code">application/json</code>，事件勾选
            <code class="whd-inline-code">Push</code> +
            <code class="whd-inline-code">Pull requests</code>；Secret 与
            <code class="whd-inline-code whd-inline-code--accent">WEBHOOK_SECRET_GITHUB</code>
            保持一致。
          </p>
        </div>
      </section>

      <v-snackbar
        :model-value="!!copyHint"
        location="bottom"
        color="surface"
        timeout="2000"
        variant="elevated"
      >
        {{ copyHint }}
      </v-snackbar>
    </div>
  </v-navigation-drawer>
</template>

<style scoped>
.webhook-help-drawer {
  background: #141414 !important;
}
.webhook-help-drawer :deep(.v-navigation-drawer__content) {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.whd-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 20px 16px 16px 20px;
  flex-shrink: 0;
}
.whd-header__title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 1.0625rem;
  font-weight: 600;
  line-height: 1.3;
  color: #f3f4f6;
}
.whd-header__title-icon {
  color: #8ab4f8;
  opacity: 0.95;
}
.whd-header__sub {
  margin: 8px 0 0;
  font-size: 0.8125rem;
  line-height: 1.5;
  color: rgba(255, 255, 255, 0.48);
}
.whd-header__close {
  flex-shrink: 0;
  margin-top: -4px;
  color: rgba(255, 255, 255, 0.55);
  transition: color 0.15s ease, background 0.15s ease;
}
.whd-header__close:hover {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.08) !important;
}
.whd-divider {
  opacity: 0.12;
  flex-shrink: 0;
}
.whd-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.whd-lead {
  margin: 0;
  font-size: 0.8125rem;
  line-height: 1.65;
  color: rgba(255, 255, 255, 0.55);
}
.whd-card {
  background: #1e1e1e;
  border: 1px solid #2a2a2a;
  border-radius: 12px;
  padding: 14px 14px 12px;
}
.whd-card--public {
  background: rgba(59, 130, 246, 0.1);
  border-color: rgba(59, 130, 246, 0.22);
  border-left: 3px solid #3b82f6;
  border-radius: 10px;
}
.whd-card__label {
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: rgba(255, 255, 255, 0.62);
  margin-bottom: 10px;
}
.whd-card__label--secret {
  display: flex;
  align-items: center;
  gap: 6px;
}
.whd-card__row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.whd-url {
  flex: 1;
  min-width: 0;
  font-size: 0.75rem;
  line-height: 1.5;
  word-break: break-all;
  color: #e5e7eb;
}
.whd-copy-btn {
  flex-shrink: 0;
  margin: -4px -6px 0 0;
  color: rgba(138, 180, 248, 0.92) !important;
  letter-spacing: 0;
  font-size: 0.75rem;
  font-weight: 600;
}
.whd-copy-btn:hover {
  background: rgba(138, 180, 248, 0.1) !important;
}
.whd-secret-text {
  font-size: 0.8125rem;
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.58);
}
.whd-inline-code {
  font-family: ui-monospace, 'Cascadia Code', 'SF Mono', Consolas, monospace;
  font-size: 0.8125em;
  padding: 1px 6px;
  border-radius: 4px;
  background: #2a2a2a;
  color: rgba(255, 255, 255, 0.82);
}
.whd-inline-code--accent {
  color: #86efac;
}
.whd-status {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 14px;
  border-radius: 12px;
  border: 1px solid transparent;
  margin-top: 4px;
}
.whd-status--ok {
  background: rgba(52, 168, 83, 0.08);
  border-color: rgba(52, 168, 83, 0.35);
}
.whd-status--ok .whd-status__icon {
  color: #81c995;
}
.whd-status--hint {
  background: rgba(255, 255, 255, 0.03);
  border-color: #2f2f2f;
}
.whd-status--hint .whd-status__icon {
  color: rgba(255, 255, 255, 0.45);
}
.whd-status__title {
  font-size: 0.875rem;
  font-weight: 600;
  color: #f9fafb;
  margin-bottom: 6px;
}
.whd-status__desc {
  font-size: 0.75rem;
  line-height: 1.55;
  color: rgba(255, 255, 255, 0.5);
}
</style>