<script setup lang="ts">
import { computed, onMounted, onUnmounted, provide, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDisplay } from 'vuetify'
import WebhookHelpDrawer from '@/components/WebhookHelpDrawer.vue'
import { fetchSystemStatus } from '@/api/client'

const route = useRoute()
const router = useRouter()
const { mdAndUp } = useDisplay()
const helpVisible = ref(false)
provide('openWebhookHelp', () => {
  helpVisible.value = true
})
const astOnline = ref(true)

const engineStatusText = computed(() =>
  astOnline.value ? 'Staging · 引擎就绪' : 'Staging · 引擎离线',
)

let timer: number | undefined

const navItems = [
  { path: '/dashboard', label: '质量驾驶舱', icon: 'mdi-view-dashboard-outline' },
  { path: '/analysis', label: '变更影响', icon: 'mdi-transit-connection-variant' },
  { path: '/regression', label: '精准回归', icon: 'mdi-file-document-check-outline' },
  { path: '/repositories', label: '仓库管理', icon: 'mdi-source-repository' },
]

function isActive(path: string) {
  if (path === '/analysis') {
    return route.path === '/analysis' || route.path.startsWith('/jobs/')
  }
  return route.path === path || route.path.startsWith(path + '/')
}

async function refreshStatus() {
  try {
    const s = await fetchSystemStatus()
    astOnline.value = s.ast_engine === 'online'
  } catch {
    astOnline.value = false
  }
}

onMounted(() => {
  refreshStatus()
  timer = window.setInterval(refreshStatus, 30000)
})

onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <v-app class="diffgate-app">
    <v-app-bar flat color="surface" border="b" density="comfortable" class="app-bar app-bar--md3-dark">
      <div class="shell bar-track d-flex align-center gap-2">
        <div class="brand d-flex align-center" @click="router.push('/dashboard')">
          <v-avatar color="primary" size="32" class="me-2">
            <span class="text-caption font-weight-bold">DG</span>
          </v-avatar>
          <div class="d-none d-sm-flex align-center ga-2">
            <span class="text-subtitle-1 font-weight-bold">DiffGate</span>
            <span class="text-caption text-medium-emphasis version-label">v2.0</span>
          </div>
        </div>

        <v-divider vertical class="brand-divider d-none d-md-flex" />

        <nav class="d-none d-md-flex nav-cluster">
          <v-btn
            v-for="item in navItems"
            :key="item.path"
            :to="item.path"
            :prepend-icon="item.icon"
            variant="text"
            :class="['nav-tab', isActive(item.path) && 'nav-tab--active']"
            size="small"
          >
            {{ item.label }}
          </v-btn>
        </nav>

        <v-menu v-if="!mdAndUp">
          <template #activator="{ props }">
            <v-btn v-bind="props" icon="mdi-menu" variant="text" />
          </template>
          <v-list>
            <v-list-item
              v-for="item in navItems"
              :key="item.path"
              :prepend-icon="item.icon"
              :title="item.label"
              :active="isActive(item.path)"
              @click="router.push(item.path)"
            />
          </v-list>
        </v-menu>

        <v-spacer />

        <div class="d-flex align-center ga-3 status-group">
          <div class="engine-status d-none d-md-flex align-center ga-2 text-caption text-medium-emphasis">
            <span class="status-dot" :class="astOnline ? 'status-dot--on' : 'status-dot--off'" />
            {{ engineStatusText }}
          </div>
          <v-btn
            class="text-none cta-new-analysis"
            size="small"
            variant="flat"
            rounded="pill"
            prepend-icon="mdi-plus"
            @click="router.push('/repositories')"
          >
            新建分析
          </v-btn>
          <v-btn
            icon="mdi-help-circle-outline"
            variant="text"
            density="comfortable"
            aria-label="帮助"
            @click="helpVisible = true"
          />
        </div>
      </div>
    </v-app-bar>

    <v-main class="bg-background app-main">
      <div class="shell shell-main">
        <router-view />
      </div>
    </v-main>

    <WebhookHelpDrawer v-model:visible="helpVisible" />
  </v-app>
</template>

<style scoped>
.brand {
  cursor: pointer;
  flex-shrink: 0;
}
.app-bar :deep(.v-toolbar__content) {
  width: 100%;
  max-width: none;
  padding: 0;
  display: block;
}
.bar-track {
  min-height: 56px;
}
.nav-cluster {
  gap: 8px;
  margin-left: 4px;
  align-self: stretch;
  align-items: stretch;
}
.nav-tab {
  text-transform: none;
  letter-spacing: normal;
  border-radius: 0 !important;
  color: #5f6368 !important;
  height: 100% !important;
  min-height: 56px;
  position: relative;
  box-shadow: none !important;
}
.nav-tab :deep(.v-btn__overlay),
.nav-tab :deep(.v-btn__underlay) {
  opacity: 0 !important;
}
.nav-tab--active {
  color: #0b57d0 !important;
  font-weight: 600;
  background: transparent !important;
}
.nav-tab--active::after {
  content: '';
  position: absolute;
  left: 10px;
  right: 10px;
  bottom: 0;
  height: 3px;
  border-radius: 3px 3px 0 0;
  background-color: #0b57d0;
}
.brand-divider {
  align-self: stretch;
  height: 28px;
  margin-inline: 12px;
  opacity: 0.65;
  border-color: #e8eaed;
}
.status-group {
  flex-shrink: 0;
}
.version-label {
  font-weight: 500;
  letter-spacing: 0.02em;
}
.engine-status {
  white-space: nowrap;
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-dot--on {
  background-color: #1e8e3e;
  box-shadow: 0 0 0 3px rgba(30, 142, 62, 0.2);
  animation: status-pulse 2.4s ease-in-out infinite;
}
.status-dot--off {
  background-color: #c5221f;
}
.shell-main {
  padding-top: 24px;
  padding-bottom: 32px;
}
@keyframes status-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.65;
  }
}
</style>

<!-- 勿在 scoped 里写 :global(.v-theme--*) .child，会被错误编译为仅 .v-theme--* 并污染整页 v-app -->
<style lang="css">
.v-theme--darkMonochrome .nav-tab {
  color: #8e9299 !important;
}
.v-theme--darkMonochrome .nav-tab--active {
  color: #8ab4f8 !important;
}
.v-theme--darkMonochrome .nav-tab--active::after {
  background-color: #8ab4f8;
}
.v-theme--darkMonochrome .app-bar--md3-dark {
  border-color: #26292e !important;
}
.v-theme--darkMonochrome .brand-divider {
  border-color: #2c3036;
  opacity: 1;
}
.v-theme--darkMonochrome .cta-new-analysis {
  background-color: #f1f3f5 !important;
  color: #111315 !important;
}
.v-theme--darkMonochrome .cta-new-analysis .v-icon {
  color: #111315 !important;
}
</style>