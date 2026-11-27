<script setup lang="ts">
import { computed, onMounted, onUnmounted, provide, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDisplay } from 'vuetify'
import NewAnalysisDialog from '@/components/NewAnalysisDialog.vue'
import WebhookHelpDrawer from '@/components/WebhookHelpDrawer.vue'
import {
  fetchAuthSession,
  fetchSystemStatus,
  hasAppSession,
  loadAuthSession,
  logoutAuth,
  type AuthSession,
  type SystemStatus,
} from '@/api/client'
import MembersManageDialog from '@/components/MembersManageDialog.vue'
import { dismissRegressionFilterMenus } from '@/utils/dismissOverlays'

const route = useRoute()
const router = useRouter()
const { mdAndUp } = useDisplay()
const helpVisible = ref(false)
const newAnalysisOpen = ref(false)
const apiOnline = ref(true)
const systemStatus = ref<SystemStatus | null>(null)
const statusRefreshing = ref(false)
const authSession = ref<AuthSession | null>(loadAuthSession())
const membersOpen = ref(false)

const isAdmin = computed(() => authSession.value?.role === 'admin')
const userMenuLabel = computed(
  () => authSession.value?.display_name || authSession.value?.username || '未登录',
)
const userRoleLabel = computed(() => authSession.value?.role_label || authSession.value?.role || '')

const isLoginRoute = computed(() => route.name === 'login' || Boolean(route.meta.public))

const API_START_CMD = '.\\scripts\\run_api.ps1'
const showDevStartHint = import.meta.env.DEV
provide('openWebhookHelp', () => {
  helpVisible.value = true
})
provide('openNewAnalysis', () => {
  newAnalysisOpen.value = true
})

const engineStatusShort = computed(() => {
  if (!apiOnline.value) return 'API 未连接'
  const st = systemStatus.value
  if (!st?.db_online) return 'Staging · 数据库连接异常'
  const ast = st.ast_engine === 'online' ? '引擎就绪' : '引擎异常'
  return `Staging · ${ast}`
})

const engineStatusPanel = computed(() => {
  const apiDownHint = showDevStartHint
    ? '本地 API 未响应，请确认已启动服务。'
    : '本地服务未响应，请稍后重试或联系管理员。'

  if (!apiOnline.value) {
    return {
      title: '服务状态',
      worker: 'API 未连接',
      workerOk: false,
      db: '数据库',
      dbOk: false,
      dbHint: apiDownHint,
      dbDetail: true,
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
      db: '数据库',
      dbOk: false,
      dbHint: null,
      dbDetail: false,
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
  const dbOk = Boolean(st.db_online)
  const dbHint = dbOk
    ? null
    : showDevStartHint
      ? '连接失败，请确认本地已启动 API 服务。'
      : '数据库连接异常，请联系系统管理员或稍后重试。'
  return {
    title: '服务状态',
    worker,
    workerOk: st.ast_engine === 'online',
    db: dbOk ? '数据库正常' : '数据库',
    dbOk,
    dbHint,
    dbDetail: !dbOk,
    redis,
    redisOk: !st.use_redis || st.redis_online,
  }
})

const statusDotOn = computed(
  () =>
    apiOnline.value &&
    Boolean(systemStatus.value?.db_online) &&
    systemStatus.value?.ast_engine === 'online',
)

let timer: number | undefined

const navItems = [
  { path: '/dashboard', label: '质量驾驶舱', icon: 'mdi-view-dashboard-outline' },
  { path: '/analysis', label: '变更影响', icon: 'mdi-transit-connection-variant' },
  { path: '/regression', label: '精准回归', icon: 'mdi-file-document-check-outline' },
  { path: '/repositories', label: '仓库管理', icon: 'mdi-source-repository' },
  { path: '/test-suites', label: '用例集管理', icon: 'mdi-clipboard-list-outline' },
]

function isActive(path: string) {
  if (path === '/analysis') {
    return route.path === '/analysis' || route.path.startsWith('/jobs/')
  }
  return route.path === path || route.path.startsWith(path + '/')
}

async function refreshStatus() {
  statusRefreshing.value = true
  try {
    systemStatus.value = await fetchSystemStatus()
    apiOnline.value = true
  } catch {
    apiOnline.value = false
    systemStatus.value = null
  } finally {
    statusRefreshing.value = false
  }
}

async function copyStartCmd() {
  try {
    await navigator.clipboard.writeText(API_START_CMD)
  } catch {
    /* ignore */
  }
}

async function refreshAuth() {
  if (!hasAppSession()) {
    authSession.value = null
    return
  }
  try {
    const s = await fetchAuthSession()
    const base = loadAuthSession()
    if (base) {
      authSession.value = {
        ...base,
        username: s.username,
        role: s.role,
        role_label: s.role_label,
        email: s.email,
        display_name: s.display_name,
        avatar_url: s.avatar_url,
        authenticated: s.authenticated,
      }
    }
  } catch {
    const cached = loadAuthSession()
    if (cached) authSession.value = cached
  }
}

async function onLogout() {
  await logoutAuth()
  authSession.value = null
  router.push('/login')
}

watch(
  isLoginRoute,
  (onLogin) => {
    if (onLogin) {
      dismissRegressionFilterMenus()
      return
    }
    const cached = loadAuthSession()
    if (cached) authSession.value = cached
    void refreshAuth()
  },
  { flush: 'post' },
)

onMounted(() => {
  if (isLoginRoute.value) dismissRegressionFilterMenus()
  refreshStatus()
  refreshAuth()
  timer = window.setInterval(refreshStatus, 30000)
})

onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <v-app class="diffgate-app" :class="{ 'diffgate-app--login': isLoginRoute }">
    <router-view v-if="isLoginRoute" />

    <template v-else>
    <v-app-bar flat color="surface" height="56" class="app-bar app-bar--md3-dark">
      <div class="shell bar-track d-flex align-center">
        <div class="brand d-flex align-center" @click="router.push('/dashboard')">
          <v-avatar color="primary" size="32" class="brand-mark">
            <span class="text-caption font-weight-bold">DG</span>
          </v-avatar>
          <div class="d-none d-sm-flex align-center brand-title-row">
            <span class="text-subtitle-1 font-weight-bold brand-name">DiffGate</span>
            <span class="version-text">v1.0</span>
          </div>
        </div>

        <nav class="d-none d-md-flex nav-cluster" aria-label="主导航">
          <v-btn
            v-for="item in navItems"
            :key="item.path"
            :to="item.path"
            :prepend-icon="item.icon"
            variant="text"
            rounded="0"
            :class="['nav-tab', isActive(item.path) && 'nav-tab--active']"
            size="small"
            height="44"
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
                <template v-if="engineStatusPanel.dbDetail">
                  <div class="engine-status-card__row engine-status-card__row--title">
                    <v-icon
                      icon="mdi-circle"
                      size="8"
                      color="#f28b82"
                      class="engine-status-card__dot"
                    />
                    <span class="engine-status-card__label">数据库</span>
                  </div>
                  <div class="engine-status-card__detail">
                    <p class="engine-status-card__hint">
                      {{ engineStatusPanel.dbHint }}
                      <button
                        type="button"
                        class="engine-status-card__retry text-none"
                        :disabled="statusRefreshing"
                        @click="refreshStatus"
                      >
                        {{ statusRefreshing ? '检测中…' : '重试' }}
                      </button>
                    </p>
                    <div v-if="showDevStartHint" class="engine-status-card__cmd">
                      <code class="engine-status-card__code mono">{{ API_START_CMD }}</code>
                      <v-btn
                        icon="mdi-content-copy"
                        size="x-small"
                        variant="text"
                        color="#f28b82"
                        aria-label="复制启动命令"
                        @click="copyStartCmd"
                      />
                    </div>
                  </div>
                </template>
                <div v-else class="engine-status-card__row">
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
            class="text-none cta-new-analysis cta-new-analysis--ghost"
            color="primary"
            size="small"
            variant="outlined"
            rounded="pill"
            prepend-icon="mdi-plus"
            @click="newAnalysisOpen = true"
          >
            新建分析
          </v-btn>
          <v-menu
            v-if="authSession"
            location="bottom end"
            :offset="8"
            content-class="user-menu-surface"
          >
            <template #activator="{ props: menuProps }">
              <v-btn
                v-bind="menuProps"
                class="user-menu-btn text-none"
                variant="text"
                size="small"
                rounded="pill"
              >
                <v-avatar size="28" :image="authSession.avatar_url || undefined" class="me-2">
                  <span v-if="!authSession.avatar_url" class="text-caption font-weight-bold">
                    {{ authSession.username.slice(0, 1).toUpperCase() }}
                  </span>
                </v-avatar>
                <span class="d-none d-lg-inline user-menu-btn__name">{{ userMenuLabel }}</span>
                <v-icon icon="mdi-chevron-down" size="16" class="ms-1" />
              </v-btn>
            </template>
            <v-list class="user-menu-list" bg-color="transparent" density="comfortable" nav>
              <div class="user-menu-profile" aria-hidden="true">
                <v-avatar
                  size="36"
                  color="rgba(255, 255, 255, 0.08)"
                  :image="authSession.avatar_url || undefined"
                >
                  <span v-if="!authSession.avatar_url" class="text-body-2 font-weight-bold">
                    {{ authSession.username.slice(0, 1).toUpperCase() }}
                  </span>
                </v-avatar>
                <div class="user-menu-profile__meta">
                  <span class="user-menu-profile__name">{{ userMenuLabel }}</span>
                  <span v-if="userRoleLabel" class="user-menu-role-chip">{{ userRoleLabel }}</span>
                </div>
              </div>
              <v-divider class="user-menu-divider" />
              <v-list-item
                v-if="isAdmin"
                class="user-menu-action"
                rounded="lg"
                prepend-icon="mdi-account-group-outline"
                title="成员与角色"
                @click="membersOpen = true"
              />
              <v-list-item
                class="user-menu-action user-menu-action--logout"
                rounded="lg"
                prepend-icon="mdi-logout"
                title="退出登录"
                @click="onLogout"
              />
            </v-list>
          </v-menu>
          <v-btn
            v-else
            class="text-none"
            variant="tonal"
            size="small"
            rounded="pill"
            to="/login"
          >
            登录
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
    <MembersManageDialog v-model="membersOpen" />
    </template>
  </v-app>
</template>

<style scoped>
.user-menu-btn {
  color: rgba(255, 255, 255, 0.82) !important;
  max-width: 200px;
}
.user-menu-btn__name {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
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
.version-text {
  font-size: 0.6875rem;
  font-weight: 500;
  letter-spacing: 0.04em;
  color: #777777;
  margin-inline-start: 2px;
}
.brand-mark {
  align-self: center;
}
.brand-title-row {
  align-items: baseline;
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
.nav-tab {
  position: relative;
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
.engine-status-card__row--title {
  padding-bottom: 0;
}
.engine-status-card__detail {
  margin: 0 0 8px 1.25rem;
  padding-left: 4px;
  border-left: 2px solid rgba(242, 139, 130, 0.35);
}
.engine-status-card__hint {
  margin: 0 0 8px;
  font-size: 12px;
  line-height: 1.45;
  color: #f4a9a3;
}
.engine-status-card__retry {
  margin-left: 8px;
  padding: 0;
  border: none;
  background: none;
  color: #8ab4f8;
  font-size: 12px;
  cursor: pointer;
  text-decoration: underline;
}
.engine-status-card__retry:disabled {
  opacity: 0.6;
  cursor: wait;
}
.engine-status-card__cmd {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 8px;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.28);
  border: 1px solid rgba(242, 139, 130, 0.25);
}
.engine-status-card__code {
  flex: 1;
  font-size: 11px;
  color: #e8c4c0;
  word-break: break-all;
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-dot--on {
  background-color: #22c55e;
  box-shadow: 0 0 8px rgba(34, 197, 94, 0.5);
  animation: status-breathe 2.4s ease-in-out infinite;
}
.status-dot--off {
  background-color: #f28b82;
  box-shadow: 0 0 0 3px rgba(242, 139, 130, 0.2);
  animation: status-breathe-warn 1.8s ease-in-out infinite;
}
.help-btn {
  margin-inline-start: 4px;
}
.cta-new-analysis--ghost {
  font-weight: 600;
  border-color: rgba(138, 180, 248, 0.55) !important;
  color: #8ab4f8 !important;
  background: transparent !important;
  box-shadow: none !important;
}
.cta-new-analysis--ghost:hover {
  background: rgba(37, 99, 235, 0.22) !important;
  border-color: rgba(138, 180, 248, 0.85) !important;
  color: #d2e3fc !important;
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
.v-theme--darkMonochrome .nav-tab {
  color: #777777 !important;
}
.v-theme--darkMonochrome .nav-tab:hover {
  color: #ffffff !important;
}
.v-theme--darkMonochrome .nav-tab--active {
  color: #ffffff !important;
  background: transparent !important;
}
.v-theme--darkMonochrome .nav-tab--active .v-icon {
  color: #8ab4f8 !important;
}
.v-theme--darkMonochrome .nav-tab--active::after {
  content: '';
  position: absolute;
  left: 14px;
  right: 14px;
  bottom: 6px;
  height: 2px;
  border-radius: 1px;
  background: #8ab4f8;
  pointer-events: none;
}
.v-theme--darkMonochrome .app-bar--md3-dark {
  background: #151515 !important;
  border-bottom: 1px solid #2a2a2a !important;
  box-shadow: none !important;
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
.user-menu-surface {
  border-radius: 8px !important;
  overflow: hidden;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5) !important;
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.user-menu-list {
  background: #2a2a2a !important;
  min-width: 240px;
  padding: 4px 0 6px !important;
}
.user-menu-profile {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px 12px;
  pointer-events: none;
  user-select: none;
}
.user-menu-profile__meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.user-menu-profile__name {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.35;
  color: #ffffff;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.user-menu-role-chip {
  display: inline-flex;
  align-self: flex-start;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  line-height: 1.35;
  color: rgba(255, 255, 255, 0.55);
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
}
.user-menu-divider {
  margin: 0 12px 6px;
  opacity: 1;
  border-color: rgba(255, 255, 255, 0.08) !important;
}
.user-menu-list .user-menu-action.v-list-item {
  min-height: 40px;
  padding-block: 10px;
  padding-inline: 16px;
  color: rgba(255, 255, 255, 0.8);
}
.user-menu-list .user-menu-action .v-list-item-title {
  font-size: 14px;
  line-height: 1.35;
  font-weight: 500;
}
.user-menu-list .user-menu-action .v-list-item__prepend > .v-icon {
  font-size: 16px;
  opacity: 0.92;
}
.user-menu-list .user-menu-action .v-list-item__prepend {
  margin-inline-end: 12px;
}
.user-menu-list .user-menu-action:hover {
  background: rgba(255, 255, 255, 0.08);
}
.user-menu-list .user-menu-action--logout {
  margin-top: 4px;
}
.user-menu-list .user-menu-action--logout:hover {
  background: rgba(239, 68, 68, 0.12);
}
</style>