<script setup lang="ts">
import { computed, onMounted, onUnmounted, provide, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDisplay } from 'vuetify'
import NewAnalysisDialog from '@/components/NewAnalysisDialog.vue'
import WebhookHelpDrawer from '@/components/WebhookHelpDrawer.vue'
import { fetchSystemStatus, type SystemStatus } from '@/api/client'

const route = useRoute()
const router = useRouter()
const { mdAndUp } = useDisplay()
const helpVisible = ref(false)
const newAnalysisOpen = ref(false)
const apiOnline = ref(true)
const systemStatus = ref<SystemStatus | null>(null)
provide('openWebhookHelp', () => {
  helpVisible.value = true
})
provide('openNewAnalysis', () => {
  newAnalysisOpen.value = true
})

const engineStatusShort = computed(() => {
  if (!apiOnline.value) return 'API 未连接'
  const st = systemStatus.value
  if (!st?.db_online) return 'Staging · 数据库不可用'
  const ast = st.ast_engine === 'online' ? '引擎就绪' : '引擎异常'
  return `Staging · ${ast}`
})

const engineStatusPanel = computed(() => {
  if (!apiOnline.value) {
    return {
      title: '服务状态',
      worker: 'API 未连接',
      workerOk: false,
      db: '请运行 run_api.ps1',
      dbOk: false,
      redis: '确认前端代理 /api/v1 可达',
      redisOk: false,
    }
  }
  const st = systemStatus.value
  if (!st) {
    return {
      title: '服务状态',
      worker: '加载中…',
      workerOk: false,
      db: '—',
      dbOk: false,
      redis: '—',
      redisOk: false,
    }
  }
  const worker =
    st.worker_mode === 'background'
      ? '后台任务引擎（单机）'
      : st.worker_mode === 'celery'
        ? 'Celery Worker 队列'
        : 'Celery 同步（eager）'
  const redis = st.use_redis ? (st.redis_online ? 'Redis 已连接' : 'Redis 未连接') : '未启用 Redis'
  const db = st.db_online ? '数据库正常' : '数据库异常'
  return {
    title: '服务状态',
    worker,
    workerOk: st.ast_engine === 'online',
    db,
    dbOk: st.db_online,
    redis,
    redisOk: !st.use_redis || st.redis_online,
  }
})

const statusDotOn = computed(() => apiOnline.value && systemStatus.value?.ast_engine === 'online')

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
    systemStatus.value = await fetchSystemStatus()
    apiOnline.value = true
  } catch {
    apiOnline.value = false
    systemStatus.value = null
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
    <v-app-bar flat color="surface" height="56" class="app-bar app-bar--md3-dark">
      <div class="shell bar-track d-flex align-center">
        <div class="brand d-flex align-center" @click="router.push('/dashboard')">
          <v-avatar color="primary" size="32" class="brand-mark">
            <span class="text-caption font-weight-bold">DG</span>
          </v-avatar>
          <div class="d-none d-sm-flex align-center brand-title-row">
            <span class="text-subtitle-1 font-weight-bold brand-name">DiffGate</span>
            <v-chip size="x-small" variant="tonal" class="version-badge" label>v2.0</v-chip>
          </div>
        </div>

        <v-divider vertical class="brand-divider d-none d-md-flex" />

        <nav class="d-none d-md-flex nav-cluster" aria-label="主导航">
          <v-btn
            v-for="item in navItems"
            :key="item.path"
            :to="item.path"
            :prepend-icon="item.icon"
            variant="text"
            rounded="pill"
            :class="['nav-tab', isActive(item.path) && 'nav-tab--active']"
            size="small"
            height="40"
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

        <div class="d-flex align-center status-group">
          <v-menu
            v-if="mdAndUp"
            location="bottom end"
            :close-on-content-click="false"
            offset="10"
            content-class="engine-status-menu"
          >
            <template #activator="{ props: menuProps }">
              <button
                v-bind="menuProps"
                type="button"
                class="engine-status engine-status--tip d-flex align-center text-caption"
                aria-label="查看服务状态"
              >
                <span class="status-dot" :class="statusDotOn ? 'status-dot--on' : 'status-dot--off'" />
                <span class="engine-status-text">{{ engineStatusShort }}</span>
                <v-icon icon="mdi-chevron-down" size="14" class="engine-status-caret" />
              </button>
            </template>
            <v-card class="engine-status-card" rounded="lg" elevation="0">
              <v-card-text class="engine-status-card__inner">
                <div class="engine-status-card__title">{{ engineStatusPanel.title }}</div>
                <div class="engine-status-card__row">
                  <v-icon
                    icon="mdi-circle"
                    size="8"
                    :color="engineStatusPanel.workerOk ? '#81c995' : '#f28b82'"
                    class="engine-status-card__dot"
                  />
                  <span class="engine-status-card__label">任务引擎</span>
                  <span class="engine-status-card__value">{{ engineStatusPanel.worker }}</span>
                </div>
                <div class="engine-status-card__row">
                  <v-icon
                    icon="mdi-circle"
                    size="8"
                    :color="engineStatusPanel.dbOk ? '#81c995' : '#f28b82'"
                    class="engine-status-card__dot"
                  />
                  <span class="engine-status-card__label">数据库</span>
                  <span class="engine-status-card__value">{{ engineStatusPanel.db }}</span>
                </div>
                <div class="engine-status-card__row">
                  <v-icon
                    icon="mdi-circle"
                    size="8"
                    :color="engineStatusPanel.redisOk ? '#81c995' : '#8e9299'"
                    class="engine-status-card__dot"
                  />
                  <span class="engine-status-card__label">缓存</span>
                  <span class="engine-status-card__value">{{ engineStatusPanel.redis }}</span>
                </div>
              </v-card-text>
            </v-card>
          </v-menu>
          <v-btn
            class="text-none cta-new-analysis"
            color="primary"
            size="small"
            variant="flat"
            rounded="pill"
            prepend-icon="mdi-plus"
            @click="newAnalysisOpen = true"
          >
            新建分析
          </v-btn>
          <v-btn
            class="help-btn"
            icon="mdi-help-circle-outline"
            variant="text"
            size="small"
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
    <NewAnalysisDialog v-model="newAnalysisOpen" />
  </v-app>
</template>

<style scoped>
.brand {
  cursor: pointer;
  flex-shrink: 0;
  margin-inline-end: 8px;
}
.brand-mark {
  margin-inline-end: 14px;
}
.brand-title-row {
  gap: 10px;
}
.brand-name {
  line-height: 1.2;
}
.version-badge {
  opacity: 0.72;
  font-size: 0.6875rem !important;
  font-weight: 500;
  letter-spacing: 0.02em;
  height: 20px !important;
  padding-inline: 6px !important;
}
.app-bar :deep(.v-toolbar__content) {
  width: 100%;
  max-width: none;
  height: 56px !important;
  min-height: 56px !important;
  padding: 0;
  display: block;
}
.bar-track {
  width: 100%;
  min-height: 56px;
  box-sizing: border-box;
}
.nav-cluster {
  gap: 24px;
  margin-inline-start: 8px;
  align-items: center;
}
.nav-tab {
  text-transform: none;
  letter-spacing: normal;
  font-weight: 500;
  opacity: 0.6;
  transition: opacity 0.18s ease, background-color 0.18s ease;
  box-shadow: none !important;
}
.nav-tab:hover {
  opacity: 1;
}
.nav-tab--active {
  opacity: 1 !important;
  font-weight: 600;
}
.brand-divider {
  align-self: center;
  height: 28px;
  margin-inline: 20px;
  opacity: 0.5;
}
.status-group {
  flex-shrink: 0;
  gap: 16px;
  margin-inline-start: 12px;
}
.engine-status {
  white-space: nowrap;
  gap: 8px;
}
.engine-status--tip {
  cursor: pointer;
  border: none;
  background: transparent;
  border-radius: 8px;
  padding: 6px 8px;
  margin: -4px -6px;
  font: inherit;
}
.engine-status--tip:hover {
  background: rgba(255, 255, 255, 0.06);
}
.engine-status-text {
  color: #c4c7c5;
}
.engine-status-caret {
  color: #8e9299;
  margin-inline-start: 2px;
  opacity: 0.85;
}
.engine-status-card__inner {
  padding: 12px 16px !important;
}
.engine-status-card__title {
  font-size: 13px;
  font-weight: 600;
  color: #e8eaed;
  margin-bottom: 10px;
}
.engine-status-card__row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  line-height: 1.5;
  padding: 4px 0;
}
.engine-status-card__dot {
  flex-shrink: 0;
}
.engine-status-card__label {
  flex: 0 0 4.5rem;
  color: rgba(255, 255, 255, 0.55);
}
.engine-status-card__value {
  color: rgba(255, 255, 255, 0.9);
  text-align: right;
  flex: 1 1 auto;
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-dot--on {
  background-color: #81c995;
  box-shadow: 0 0 0 3px rgba(129, 201, 149, 0.22);
  animation: status-breathe 2.4s ease-in-out infinite;
}
.status-dot--off {
  background-color: #f28b82;
  box-shadow: 0 0 0 3px rgba(242, 139, 130, 0.2);
  animation: status-breathe-warn 1.8s ease-in-out infinite;
}
.cta-new-analysis {
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(26, 115, 232, 0.35);
}
.cta-new-analysis :deep(.v-btn__prepend .v-icon) {
  font-size: 18px;
}
.help-btn {
  opacity: 0.88;
}
.help-btn:hover {
  opacity: 1;
}
.shell-main {
  padding-top: 24px;
  padding-bottom: 32px;
}
@keyframes status-breathe {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.72;
    transform: scale(0.92);
  }
}
@keyframes status-breathe-warn {
  0%,
  100% {
    opacity: 1;
    box-shadow: 0 0 0 3px rgba(242, 139, 130, 0.25);
  }
  50% {
    opacity: 0.55;
    box-shadow: 0 0 0 6px rgba(242, 139, 130, 0.12);
  }
}
</style>

<!-- 勿在 scoped 里写 :global(.v-theme--*) .child，会被错误编译为仅 .v-theme--* 并污染整页 v-app -->
<style lang="css">
.v-theme--darkMonochrome .nav-tab {
  color: #b0b4bb !important;
}
.v-theme--darkMonochrome .nav-tab--active {
  color: #e8eaed !important;
  background: rgba(138, 180, 248, 0.16) !important;
}
.v-theme--darkMonochrome .nav-tab--active .v-icon {
  color: #8ab4f8 !important;
}
.v-theme--darkMonochrome .app-bar--md3-dark {
  border-bottom: 1px solid rgba(255, 255, 255, 0.08) !important;
  box-shadow: none !important;
}
.v-theme--darkMonochrome .brand-divider {
  border-color: rgba(255, 255, 255, 0.1);
  opacity: 1;
}
.v-theme--darkMonochrome .version-badge {
  --v-chip-height: 20px;
}
.engine-status-menu {
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  border-radius: 8px !important;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5) !important;
  background: #2c2c2c !important;
  overflow: hidden;
}
.engine-status-menu .engine-status-card {
  background: #2c2c2c !important;
  min-width: 260px;
}
</style>