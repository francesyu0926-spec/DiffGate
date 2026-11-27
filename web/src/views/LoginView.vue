<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  fetchAuthTokenWizard,
  loginLocalDev,
  loginWithPassword,
  loginWithPat,
  readApiError,
  setAuthPassword,
  type AuthProvider,
} from '@/api/client'
import axios from 'axios'
import { dismissRegressionFilterMenus } from '@/utils/dismissOverlays'

const router = useRouter()
const route = useRoute()

type LoginMode = 'token' | 'password'

const loginMode = ref<LoginMode>('token')
const provider = ref<AuthProvider>('github')
const gitlabBaseUrl = ref('https://gitlab.com')
const accessToken = ref('')
const accountLogin = ref('')
const accountPassword = ref('')
const loading = ref(false)
const error = ref('')
const wizard = ref<Awaited<ReturnType<typeof fetchAuthTokenWizard>> | null>(null)

const passwordSetupOpen = ref(false)
const setupPassword = ref('')
const setupPasswordConfirm = ref('')
const setupSubmitting = ref(false)
const postLoginRedirect = ref('/dashboard')

const isLocalHost = computed(() => {
  const h = window.location.hostname
  return h === 'localhost' || h === '127.0.0.1'
})

const tokenCreateUrl = computed(() => {
  if (!wizard.value) return null
  return provider.value === 'github' ? wizard.value.github.create_url : wizard.value.gitlab.create_url
})

const wizardLinkText = computed(() => {
  if (!wizard.value) return ''
  const row = provider.value === 'github' ? wizard.value.github : wizard.value.gitlab
  return row.wizard_link_text || '没有 Token？点此一键生成 ↗'
})

const tokenPlaceholder = computed(() =>
  provider.value === 'github' ? '请输入 Access Token' : '请输入 glpat- 开头的令牌',
)

const showAccessToken = ref(false)
const showAccountPassword = ref(false)

const wizardLinkLabel = computed(() =>
  provider.value === 'github' ? '5 秒一键生成' : '前往 GitLab 个人令牌生成',
)

async function loadWizard() {
  try {
    wizard.value = await fetchAuthTokenWizard(gitlabBaseUrl.value)
  } catch {
    wizard.value = null
  }
}

function readErr(e: unknown) {
  const status = axios.isAxiosError(e) ? e.response?.status : undefined
  if (status === 404) {
    return '认证接口未就绪，请重启后端 API（.\\scripts\\run_api.ps1）后重试。'
  }
  if (axios.isAxiosError(e)) {
    const detail = e.response?.data?.detail
    if (Array.isArray(detail)) {
      const fields = new Set(
        detail.map((row) => {
          const loc = (row as { loc?: unknown[] })?.loc
          return Array.isArray(loc) ? String(loc[loc.length - 1] ?? '') : ''
        }),
      )
      if (fields.has('login') && fields.has('password')) {
        return '请填写 Git 用户名或邮箱与 DiffGate 登录密码'
      }
      if (fields.has('login')) return '请填写 Git 用户名或邮箱'
      if (fields.has('password')) return '请填写 DiffGate 登录密码'
      if (fields.has('access_token')) {
        return provider.value === 'github'
          ? '请填写 GitHub Personal Access Token'
          : '请填写 GitLab Personal Access Token'
      }
      const msg = (detail[0] as { msg?: string } | undefined)?.msg
      if (msg?.includes('at least 1 character')) return '请完整填写登录信息'
    }
  }
  return readApiError(e, '登录失败，请检查填写内容后重试')
}

function navigateAfterLogin() {
  const redirect = postLoginRedirect.value || '/dashboard'
  void router.replace(redirect)
}

async function submitTokenLogin() {
  error.value = ''
  if (!accessToken.value.trim()) {
    error.value =
      provider.value === 'github'
        ? '请填写 GitHub Personal Access Token'
        : '请填写 GitLab Personal Access Token'
    return
  }
  loading.value = true
  postLoginRedirect.value =
    typeof route.query.redirect === 'string' ? route.query.redirect : '/dashboard'
  try {
    const session = await loginWithPat({
      provider: provider.value,
      access_token: accessToken.value.trim() || undefined,
      gitlab_base_url: gitlabBaseUrl.value.trim(),
    })
    if (session.needs_password_setup) {
      passwordSetupOpen.value = true
      return
    }
    navigateAfterLogin()
  } catch (e: unknown) {
    error.value = readErr(e)
  } finally {
    loading.value = false
  }
}

async function submitPasswordLogin() {
  error.value = ''
  if (!accountLogin.value.trim() && !accountPassword.value) {
    error.value = '请填写 Git 用户名或邮箱与 DiffGate 登录密码'
    return
  }
  if (!accountLogin.value.trim()) {
    error.value = '请填写 Git 用户名或邮箱'
    return
  }
  if (!accountPassword.value) {
    error.value = '请填写 DiffGate 登录密码'
    return
  }
  loading.value = true
  postLoginRedirect.value =
    typeof route.query.redirect === 'string' ? route.query.redirect : '/dashboard'
  try {
    await loginWithPassword(accountLogin.value.trim(), accountPassword.value)
    navigateAfterLogin()
  } catch (e: unknown) {
    error.value = readErr(e)
  } finally {
    loading.value = false
  }
}

async function confirmPasswordSetup() {
  setupSubmitting.value = true
  error.value = ''
  try {
    await setAuthPassword(setupPassword.value, setupPasswordConfirm.value)
    passwordSetupOpen.value = false
    navigateAfterLogin()
  } catch (e: unknown) {
    error.value = readErr(e)
  } finally {
    setupSubmitting.value = false
  }
}

function skipPasswordSetup() {
  passwordSetupOpen.value = false
  navigateAfterLogin()
}

function switchToTokenMode() {
  loginMode.value = 'token'
  error.value = ''
}

async function localDevLogin() {
  error.value = ''
  loading.value = true
  try {
    await loginLocalDev()
    await router.replace('/dashboard')
  } catch (e: unknown) {
    error.value = readErr(e)
  } finally {
    loading.value = false
  }
}

watch([accessToken, accountLogin, accountPassword], () => {
  if (error.value) error.value = ''
})

onMounted(() => {
  dismissRegressionFilterMenus()
  void loadWizard()
})
</script>

<template>
  <div class="login-shell">
    <div class="login-shell__column">
      <header class="login-shell__brand">
        <div class="login-shell__logo">
          <v-avatar color="primary" size="40" rounded="lg">
            <span class="text-body-2 font-weight-bold">DG</span>
          </v-avatar>
          <div>
            <h1 class="login-shell__title">DiffGate <span class="login-shell__ver">v1.0</span></h1>
          </div>
        </div>
      </header>

      <main class="login-shell__main">
        <div class="login-panel-wrap">
        <section class="login-panel" aria-labelledby="login-mode-tabs">
          <div id="login-mode-tabs" class="login-mode-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              class="login-mode-tabs__btn"
              :class="{ 'login-mode-tabs__btn--active': loginMode === 'token' }"
              :aria-selected="loginMode === 'token'"
              @click="loginMode = 'token'; error = ''"
            >
              令牌登录
            </button>
            <button
              type="button"
              role="tab"
              class="login-mode-tabs__btn"
              :class="{ 'login-mode-tabs__btn--active': loginMode === 'password' }"
              :aria-selected="loginMode === 'password'"
              @click="loginMode = 'password'; error = ''"
            >
              密码登录
            </button>
          </div>

          <div class="login-form-stack">
            <template v-if="loginMode === 'token'">
              <div class="login-platform-tabs" role="group" aria-label="Git 平台">
                <button
                  type="button"
                  class="login-platform-tabs__btn"
                  :class="{ 'login-platform-tabs__btn--active': provider === 'github' }"
                  @click="provider = 'github'"
                >
                  GitHub
                </button>
                <button
                  type="button"
                  class="login-platform-tabs__btn"
                  :class="{ 'login-platform-tabs__btn--active': provider === 'gitlab' }"
                  @click="provider = 'gitlab'"
                >
                  GitLab
                </button>
              </div>

              <div v-if="provider === 'gitlab'" class="login-field-block login-field-block--gitlab">
                <span class="login-field-block__label">GitLab 服务地址</span>
                <v-text-field
                  v-model="gitlabBaseUrl"
                  placeholder="https://gitlab.com"
                  hint="私有化部署请改为内网地址"
                  persistent-hint
                  variant="outlined"
                  density="comfortable"
                  rounded="md"
                  prepend-inner-icon="mdi-web"
                  class="login-field login-field--hint"
                  hide-details="auto"
                  @blur="loadWizard"
                />
              </div>

              <div class="login-field-block login-field-block--token">
                <span class="login-field-block__label">访问令牌</span>
                <v-text-field
                  v-model="accessToken"
                  :type="showAccessToken ? 'text' : 'password'"
                  variant="outlined"
                  density="comfortable"
                  rounded="md"
                  autocomplete="off"
                  prepend-inner-icon="mdi-key-variant"
                  class="login-field login-field--token-input"
                  :placeholder="tokenPlaceholder"
                  :title="provider === 'gitlab' ? '例如 glpat-xxxxxxxxxxxxxxxxxxxx' : undefined"
                  :disabled="loading"
                  hide-details
                  :append-inner-icon="showAccessToken ? 'mdi-eye-off' : 'mdi-eye'"
                  @click:append-inner="showAccessToken = !showAccessToken"
                />
                <div v-if="tokenCreateUrl" class="login-field-extra">
                  <a
                    :href="tokenCreateUrl"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="login-link login-field-extra__link"
                    :title="wizardLinkText"
                  >
                    没有 Token？{{ wizardLinkLabel }} ↗
                  </a>
                  <div v-if="provider === 'gitlab'" class="login-field-extra__scopes-row">
                    <span class="login-scope-chip">read_user</span>
                    <span class="login-scope-chip">read_api</span>
                  </div>
                </div>
              </div>

              <Transition name="login-alert">
                <div v-if="error" class="login-error" role="alert">
                  <v-icon icon="mdi-alert-circle-outline" size="16" class="login-error__icon" />
                  <span class="login-error__text">{{ error }}</span>
                </div>
              </Transition>

              <v-btn
                block
                color="primary"
                variant="flat"
                class="text-none login-primary-btn login-primary-btn--spaced"
                :loading="loading"
                @click="submitTokenLogin"
              >
                <span class="login-primary-btn__label">
                  <v-icon icon="mdi-login" size="20" />
                  登录并同步仓库权限
                </span>
              </v-btn>

              <div v-if="isLocalHost" class="login-local-section">
                <button
                  type="button"
                  class="login-text-btn"
                  :disabled="loading"
                  @click="localDevLogin"
                >
                  本地免密体验登录（调试用）
                </button>
              </div>
            </template>

            <template v-else>
              <div class="login-field-block">
                <span class="login-field-block__label">Git 用户名或邮箱</span>
                <v-text-field
                  v-model="accountLogin"
                  placeholder="用户名或邮箱"
                  variant="outlined"
                  density="comfortable"
                  rounded="md"
                  autocomplete="username"
                  prepend-inner-icon="mdi-account-outline"
                  class="login-field"
                  hide-details
                  :disabled="loading"
                />
              </div>

              <div class="login-field-block login-field-block--tight">
                <div class="login-field-block__head">
                  <span class="login-field-block__label">DiffGate 登录密码</span>
                  <button
                    type="button"
                    class="login-forgot-link login-field-block__aside"
                    title="使用 Git 令牌重新登录即可重置"
                    @click="switchToTokenMode"
                  >
                    忘记密码？
                  </button>
                </div>
                <v-text-field
                  v-model="accountPassword"
                  placeholder="请输入 DiffGate 密码"
                  :type="showAccountPassword ? 'text' : 'password'"
                  variant="outlined"
                  density="comfortable"
                  rounded="md"
                  autocomplete="current-password"
                  prepend-inner-icon="mdi-lock-outline"
                  class="login-field"
                  hide-details
                  :disabled="loading"
                  :append-inner-icon="showAccountPassword ? 'mdi-eye-off' : 'mdi-eye'"
                  @click:append-inner="showAccountPassword = !showAccountPassword"
                />
              </div>

              <Transition name="login-alert">
                <div v-if="error" class="login-error" role="alert">
                  <v-icon icon="mdi-alert-circle-outline" size="16" class="login-error__icon" />
                  <span class="login-error__text">{{ error }}</span>
                </div>
              </Transition>

              <v-btn
                block
                color="primary"
                variant="flat"
                class="text-none login-primary-btn login-primary-btn--spaced"
                :loading="loading"
                @click="submitPasswordLogin"
              >
                <span class="login-primary-btn__label">
                  <v-icon icon="mdi-login" size="20" />
                  立即登录
                </span>
              </v-btn>

              <div class="login-info-bar login-first-time--spaced">
                <p class="login-info-bar__line mb-0">
                  首次使用？请先通过
                  <button type="button" class="login-link login-link--inline" @click="switchToTokenMode">
                    令牌登录
                  </button>
                  绑定 GitHub / GitLab。
                </p>
              </div>
            </template>
          </div>
        </section>
        <p class="login-panel-footer">Token 仅用于本次核验与权限同步，不落库存储</p>
        </div>
      </main>
    </div>

    <v-dialog v-model="passwordSetupOpen" max-width="440" persistent>
      <v-card class="login-setup-card" rounded="xl">
        <v-card-title class="text-subtitle-1 font-weight-bold">设置 DiffGate 独立登录密码</v-card-title>
        <v-card-text>
          <p class="login-setup-lead mb-4">
            设置后，下次可使用「用户名 / 邮箱密码登录」免填 Token。
          </p>
          <v-text-field
            v-model="setupPassword"
            label="新密码"
            type="password"
            variant="outlined"
            density="comfortable"
            rounded="lg"
            autocomplete="new-password"
            class="mb-2"
          />
          <v-text-field
            v-model="setupPasswordConfirm"
            label="确认密码"
            type="password"
            variant="outlined"
            density="comfortable"
            rounded="lg"
            autocomplete="new-password"
          />
          <Transition name="login-alert">
            <div v-if="error && passwordSetupOpen" class="login-error login-error--dialog" role="alert">
              <v-icon icon="mdi-alert-circle-outline" size="16" class="login-error__icon" />
              <span class="login-error__text">{{ error }}</span>
            </div>
          </Transition>
        </v-card-text>
        <v-card-actions class="px-4 pb-4">
          <v-btn variant="text" class="text-none" :disabled="setupSubmitting" @click="skipPasswordSetup">
            暂不设置，跳过
          </v-btn>
          <v-spacer />
          <v-btn
            color="primary"
            class="text-none"
            variant="flat"
            rounded="pill"
            :loading="setupSubmitting"
            @click="confirmPasswordSetup"
          >
            确认设置
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<style scoped>
.login-shell {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  min-height: 100dvh;
  padding: 24px 20px;
  box-sizing: border-box;
  background: #000000;
}
.login-shell__column {
  width: 100%;
  max-width: 440px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  align-items: stretch;
}
.login-shell__brand {
  width: 100%;
  margin: 0 0 24px;
}
.login-shell__logo {
  display: flex;
  align-items: center;
  gap: 14px;
}
.login-shell__title {
  margin: 0;
  font-size: 1.35rem;
  font-weight: 700;
  line-height: 1.3;
  color: #e8eaed;
}
.login-shell__ver {
  font-size: 0.85rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.45);
  margin-left: 4px;
}
.login-shell__main {
  width: 100%;
}
.login-panel-wrap {
  width: 100%;
}
.login-panel {
  width: 100%;
  padding: 40px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: #1c1c1c;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.5);
}
.login-mode-tabs {
  display: flex;
  gap: 0;
  margin: 0 -40px 24px;
  padding: 0 40px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.login-platform-tabs {
  display: flex;
  align-items: center;
  gap: 36px;
  margin-bottom: 20px;
  padding: 0 2px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.login-platform-tabs__btn {
  border: 0;
  padding: 8px 0 12px;
  background: transparent;
  color: rgba(255, 255, 255, 0.48);
  font-size: 14px;
  font-weight: 500;
  line-height: 1.35;
  cursor: pointer;
  position: relative;
  transition: color 0.15s ease;
}
.login-platform-tabs__btn--active {
  color: #ffffff;
  font-weight: 700;
}
.login-platform-tabs__btn--active::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: -1px;
  height: 1px;
  background: rgba(255, 255, 255, 0.32);
}
.login-platform-tabs__btn:hover:not(.login-platform-tabs__btn--active) {
  color: rgba(255, 255, 255, 0.72);
}
.login-mode-tabs__btn {
  flex: 1;
  padding: 8px 2px 12px;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: rgba(255, 255, 255, 0.55);
  font-size: 14px;
  font-weight: 500;
  line-height: 1.35;
  white-space: nowrap;
  cursor: pointer;
  position: relative;
  transition: color 0.15s ease;
}
.login-mode-tabs__btn--active {
  color: #ffffff;
}
.login-mode-tabs__btn--active::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: -1px;
  height: 2px;
  background: #60a5fa;
  border-radius: 2px 2px 0 0;
}
.login-mode-tabs__btn:hover:not(.login-mode-tabs__btn--active) {
  color: rgba(255, 255, 255, 0.82);
}
.login-form-stack {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.login-field-block {
  display: flex;
  flex-direction: column;
  gap: 0;
  margin-bottom: 24px;
}
.login-field-block--gitlab {
  margin-bottom: 20px;
}
.login-field-block--gitlab .login-field--hint :deep(.v-input__details) {
  padding-bottom: 0;
  margin-bottom: 0;
}
.login-field-block--tight {
  margin-bottom: 24px;
}
.login-field-block__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
}
.login-field-block__head .login-field-block__label {
  margin-bottom: 0;
}
.login-field-block__aside {
  flex-shrink: 0;
}
.login-forgot-link {
  padding: 0;
  border: 0;
  background: none;
  font: inherit;
  cursor: pointer;
  font-size: 12px;
  line-height: 1.35;
  font-weight: 400;
  color: rgba(255, 255, 255, 0.5);
  text-decoration: none;
  transition: color 0.15s ease;
}
.login-forgot-link:hover {
  color: #ffffff;
  text-decoration: underline;
  text-underline-offset: 3px;
}
.login-field-block__label {
  margin-bottom: 6px;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.3;
  color: rgba(255, 255, 255, 0.55);
  padding-left: 2px;
}
.login-field-extra {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  margin-top: 10px;
  max-width: 100%;
}
.login-field-extra__link {
  font-size: 12px;
  line-height: 1.4;
}
.login-field-extra__scopes-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.login-scope-chip {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 10px;
  line-height: 1.35;
  color: rgba(255, 255, 255, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: transparent;
}
.login-field :deep(.v-field__prepend-inner),
.login-field :deep(.v-field__append-inner) {
  align-self: center;
}
.login-field :deep(.v-field__prepend-inner) {
  color: rgba(255, 255, 255, 0.58);
  padding-inline-start: 12px;
  padding-inline-end: 8px;
}
.login-field :deep(.v-field__prepend-inner .v-icon) {
  font-size: 16px;
  width: 16px;
  height: 16px;
  opacity: 1;
}
.login-field :deep(.v-field) {
  background: rgba(255, 255, 255, 0.05) !important;
  border-radius: 8px !important;
  min-height: 44px;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.1);
}
.login-field :deep(.v-field--focused) {
  box-shadow: inset 0 0 0 1px rgba(96, 165, 250, 0.45);
}
.login-field :deep(.v-field__input),
.login-field :deep(input) {
  min-height: 44px;
  padding-top: 8px;
  padding-bottom: 8px;
  padding-inline-start: 12px;
  font-size: 14px;
  line-height: 1.35;
}
.login-field :deep(.v-field__outline) {
  --v-field-border-opacity: 0;
}
.login-field :deep(input::placeholder),
.login-field :deep(.v-field__input::placeholder) {
  color: rgba(255, 255, 255, 0.5);
  opacity: 1;
  text-overflow: clip;
  font-size: 13px;
  line-height: 1.35;
}
.login-field--token-input :deep(input::placeholder),
.login-field--token-input :deep(.v-field__input::placeholder) {
  font-size: 13px;
}
.login-field :deep(.v-label) {
  color: rgba(255, 255, 255, 0.78);
}
.login-field--hint :deep(.v-input__details) {
  padding-top: 0;
  min-height: auto;
}
.login-field--hint :deep(.v-messages) {
  margin-top: 4px;
  margin-bottom: 0;
  padding-top: 0;
  color: rgba(255, 255, 255, 0.4);
  font-size: 12px;
  line-height: 1.35;
}
.login-field-block--token {
  margin-bottom: 18px;
}
.login-link {
  color: #60a5fa;
  text-decoration: none;
  font-weight: 500;
}
.login-link:hover,
.login-link--inline:hover {
  text-decoration: underline;
  text-underline-offset: 3px;
}
.login-link--inline {
  padding: 0;
  border: 0;
  background: none;
  font: inherit;
  cursor: pointer;
}
.login-primary-btn--spaced {
  margin-top: 0;
}
.login-primary-btn :deep(.v-btn__content) {
  justify-content: center;
  width: 100%;
}
.login-primary-btn__label {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
.login-local-section {
  margin-top: 24px;
  padding: 24px 0 0;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}
.login-info-bar {
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.06);
}
.login-info-bar__line {
  font-size: 12px;
  line-height: 1.55;
  color: rgba(255, 255, 255, 0.58);
  text-align: left;
}
.login-first-time--spaced {
  margin-top: 20px;
}
.login-primary-btn {
  min-height: 48px !important;
  height: 48px !important;
  border-radius: 8px !important;
  font-weight: 600 !important;
  letter-spacing: 0.02em;
  background-color: #3b6ec8 !important;
  color: #ffffff !important;
  box-shadow: 0 4px 14px rgba(59, 110, 200, 0.35);
}
.login-primary-btn:hover {
  background-color: #4778cd !important;
  box-shadow: 0 6px 18px rgba(59, 110, 200, 0.4);
}
.login-text-btn {
  width: 100%;
  padding: 8px 4px;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: rgba(255, 255, 255, 0.55);
  font-size: 12px;
  line-height: 1.45;
  cursor: pointer;
  transition: color 0.15s ease;
}
.login-text-btn:hover:not(:disabled) {
  color: rgba(255, 255, 255, 0.78);
}
.login-text-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.login-panel-footer {
  margin: 24px 0 0;
  text-align: center;
  font-size: 12px;
  line-height: 1.5;
  color: rgba(255, 255, 255, 0.4);
}
.login-error {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 16px 0 16px;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.4;
  color: #f87171;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.1);
}
.login-error__icon {
  flex-shrink: 0;
  color: #f87171;
  opacity: 0.95;
}
.login-error__text {
  flex: 1;
  min-width: 0;
}
.login-error--dialog {
  margin: 12px 0 0;
}
.login-alert-enter-active {
  transition: opacity 0.22s ease, transform 0.22s ease;
}
.login-alert-leave-active {
  transition: opacity 0.16s ease, transform 0.16s ease;
}
.login-alert-enter-from,
.login-alert-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
.login-setup-card {
  border: 1px solid #2e333b;
  background: #1e2124;
}
.login-setup-lead {
  font-size: 13px;
  line-height: 1.55;
  color: rgba(255, 255, 255, 0.65);
}
</style>