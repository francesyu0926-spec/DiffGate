<script setup lang="ts">
import { computed, onActivated, onMounted, provide, ref, watch } from 'vue'
import { DG_FORM_FIELD_SPEC_KEY } from '@/form/formFieldLayout'
import { useRoute, useRouter } from 'vue-router'
import type { VForm } from 'vuetify/components'
import {
  createMonorepoBundle,
  createRepository,
  detectRepositoryProfile,
  fetchRepositories,
  fetchRepoTypeOptions,
  fetchTestSuitePresets,
  fetchTestSuites,
  readApiError,
  type TestSuiteItem,
  reindexRepository,
  testRepositoryNotify,
  updateRepository,
  type DetectRepositoryProfile,
} from '@/api/client'
import type {
  AuthMethod,
  RepoProvider,
  RepositoryItem,
  RepositoryPayload,
} from '@/api/types'
import { parseFullNameFromCloneUrl } from '@/utils/git'
import OutlinedInput from '@/components/OutlinedInput.vue'
import OutlinedTextarea from '@/components/OutlinedTextarea.vue'
import OutlinedPasswordInput from '@/components/OutlinedPasswordInput.vue'
import OutlinedSelect, { type OutlinedSelectOption } from '@/components/OutlinedSelect.vue'

const router = useRouter()
const route = useRoute()

provide(DG_FORM_FIELD_SPEC_KEY, true)

const linkedRepoRows = ref<RepositoryItem[]>([])
const editingId = ref<string | null>(null)
const formRef = ref<VForm | null>(null)
const submitPhase = ref<'idle' | 'saving' | 'indexing'>('idle')
const fullNameManual = ref(false)
type TestSuiteSelectOption = {
  title: string
  value: string
  slug: string
  description?: string | null
  disabled?: boolean
}

const testSuiteOptions = ref<TestSuiteSelectOption[]>([])
const testSuiteOptionsLoading = ref(false)
const accessToken = ref('')
const sshPrivateKey = ref('')
const editingTokenConfigured = ref(false)
const editingSshConfigured = ref(false)
const submitLoading = ref(false)
type SnackbarVariant = 'success' | 'error' | 'info'
const snackbar = ref<{ show: boolean; text: string; variant: SnackbarVariant; loading?: boolean }>({
  show: false,
  text: '',
  variant: 'success',
  loading: false,
})

function notify(text: string, variant: SnackbarVariant = 'success') {
  snackbar.value = { show: true, text, variant, loading: false }
}

function notifyInProgress(text: string) {
  snackbar.value = { show: true, text, variant: 'info', loading: true }
}

const submitButtonLabel = computed(() => {
  if (!submitLoading.value) return editingId.value ? '保存' : '保存并初始化索引'
  if (submitPhase.value === 'indexing') return '正在构建 AST 索引…'
  return editingId.value ? '保存中…' : '保存中…'
})




/** 浮层挂 body，避免卡片 overflow 裁切只露出一项 */
type RepoTypeSelectItem = {
  title: string
  value: string
  icon?: string
  props?: { disabled?: boolean }
}

const REPO_TYPE_OPTION_ICONS: Record<string, string> = {
  auto: 'mdi-radar',
  backend_python: 'mdi-language-python',
  frontend: 'mdi-react',
  backend_node: 'mdi-nodejs',
  backend_go: 'mdi-language-go',
  backend_java: 'mdi-language-java',
}

function repoTypeItem(row: { id?: string; label: string; value?: string; comingSoon?: boolean }) {
  const value = row.value ?? row.id ?? ''
  return {
    title: row.label,
    value,
    icon: REPO_TYPE_OPTION_ICONS[value] ?? 'mdi-code-braces',
    props: row.comingSoon ? { disabled: true } : undefined,
  } satisfies RepoTypeSelectItem
}


const repoForm = ref<RepositoryPayload>({
  full_name: '',
  provider: 'gitlab',
  clone_url: '',
  default_branch: 'main',
  description: '',
  enabled: true,
  webhook_enabled: true,
  coverage_threshold: 80,
  auth_method: 'none',
  scan_root: '.',
  test_suite_id: '',
  webhook_notify_url: '',
  notify_webhook_url: '',
  notify_policy: 'block_only',
  high_risk_paths: [],
  low_risk_paths: [],
  high_risk_api_threshold: undefined,
  high_risk_symbol_threshold: undefined,
  allow_self_override: false,
  repo_type: 'auto',
  api_base_prefix: '/api/v1',
  api_strip_prefix: '',
  linked_repo_ids: [] as string[],
})
const AUTO_REPO_TYPE = 'auto'
const repoTypeItems = ref<RepoTypeSelectItem[]>([
  {
    title: '自动识别（根据仓库地址探测）',
    value: AUTO_REPO_TYPE,
    icon: REPO_TYPE_OPTION_ICONS.auto,
  },
  {
    title: '后端 (Python)',
    value: 'backend_python',
    icon: REPO_TYPE_OPTION_ICONS.backend_python,
  },
  {
    title: '前端 (TS/JS)',
    value: 'frontend',
    icon: REPO_TYPE_OPTION_ICONS.frontend,
  },
  {
    title: '后端 (Node.js/TS)',
    value: 'backend_node',
    icon: REPO_TYPE_OPTION_ICONS.backend_node,
  },
  {
    title: '后端 (Go)',
    value: 'backend_go',
    icon: REPO_TYPE_OPTION_ICONS.backend_go,
  },
  {
    title: '后端 (Java)',
    value: 'backend_java',
    icon: REPO_TYPE_OPTION_ICONS.backend_java,
  },
])
const lastDetect = ref<DetectRepositoryProfile | null>(null)
const detectLoading = ref(false)
const monorepoHint = ref('')
const monorepoDualCreate = ref(false)
const repoTypeManualOverride = ref(false)

function normalizeRepoType(t?: string | null) {
  if (!t || t === 'backend') return 'backend_python'
  return t
}

const pageTitle = computed(() => (editingId.value ? '编辑仓库' : '添加仓库'))

const linkedRepoOptions = computed(() =>
  linkedRepoRows.value
    .filter((r) => r.id !== editingId.value)
    .map((r) => ({ title: r.full_name, value: r.id })),
)

function goBack() {
  void router.push({ name: 'repositories' })
}
const effectiveRepoType = computed(() => {
  const t = repoForm.value.repo_type
  if (t === AUTO_REPO_TYPE && lastDetect.value?.repo_type) {
    return normalizeRepoType(lastDetect.value.repo_type)
  }
  if (t === AUTO_REPO_TYPE) return 'backend_python'
  return normalizeRepoType(t)
})
const autoDetectLabel = computed(() => lastDetect.value?.label || '')
const canTriggerRepoDetect = computed(() => (repoForm.value.clone_url || '').trim().length > 0)
const cloneUrlDetectError = ref('')
const selectedRepoTypeDisplay = computed(() => {
  const v = repoForm.value.repo_type
  return (
    repoTypeItems.value.find((i) => i.value === v) ??
    repoTypeItems.value.find((i) => i.value === AUTO_REPO_TYPE) ?? {
      title: '仓库类型',
      value: v,
      icon: 'mdi-code-braces',
    }
  )
})
const isFrontendRepo = computed(() => effectiveRepoType.value === 'frontend')
const isJavaRepo = computed(() => effectiveRepoType.value === 'backend_java')
const isGoRepo = computed(() => effectiveRepoType.value === 'backend_go')
const scanRootPlaceholder = computed(() => {
  if (isFrontendRepo.value) return 'src 或 web'
  if (isJavaRepo.value) return 'src/main/java'
  if (isGoRepo.value) return '仓库根目录（含 go.mod），默认 .'
  return 'app 或 backend，默认 .'
})
const isLocalProvider = computed(() => repoForm.value.provider === 'local')
const cloneUrlFieldLabel = computed(
  () => `${isLocalProvider.value ? '本地路径 / Clone URL' : 'Clone URL'} *`,
)
const cloneUrlPlaceholder = computed(() =>
  isLocalProvider.value
    ? '例如 D:\\projects\\diffgate-web 或 /data/repos/diffgate-web'
    : 'https://gitlab.com/my-team/order-service.git',
)
const inheritedTestSuiteHint = computed(() => {
  if (repoForm.value.repo_type !== 'frontend' || (repoForm.value.test_suite_id || '').trim()) return ''
  const linked = repoForm.value.linked_repo_ids || []
  const backend = linkedRepoRows.value.find(
    (r) =>
      linked.includes(r.id) &&
      normalizeRepoType(r.repo_type) !== 'frontend' &&
      (r.test_suite_id || '').trim(),
  )
  if (backend?.test_suite_id) {
    return `未填写时将沿用关联后端「${backend.full_name}」的用例集（${backend.test_suite_id}）。`
  }
  return ''
})
const testSuitePlaceholder = computed(() => {
  if (testSuiteOptionsLoading.value) return '加载中…'
  if (testSuiteOptions.value.length) return '请选择关联用例集'
  return '暂无可用用例集'
})
const testSuiteStatusHint = computed(() => {
  if (testSuiteOptionsLoading.value || !testSuiteOptions.value.length) return ''
  if ((repoForm.value.test_suite_id || '').trim()) return ''
  return '目前未选择用例集'
})
const scanRootTooltipActive = computed(
  () => (repoForm.value.scan_root || '').trim().length > 36,
)

type ScanRootOption = {
  path: string
  label: string
  title: string
  value: string
  is_recommended?: boolean
  matched_type?: string | null
  file_summary?: string
}

function repoTypeToMatchedType(typeValue: string): string | null {
  const key = normalizeRepoType(typeValue)
  const map: Record<string, string> = {
    backend_python: 'python',
    backend_java: 'java',
    backend_go: 'go',
    frontend: 'frontend',
    backend_node: 'nodejs',
  }
  return map[key] ?? null
}

function activeMatchedType(): string | null {
  const t = repoForm.value.repo_type
  if (t === AUTO_REPO_TYPE) {
    return lastDetect.value?.detected_type || repoTypeToMatchedType(lastDetect.value?.repo_type || '')
  }
  return repoTypeToMatchedType(t)
}

const scanRootOptions = computed((): ScanRootOption[] => {
  const prefer = activeMatchedType()
  const legacy = lastDetect.value?.scan_directories
  const rich = lastDetect.value?.directories
  const rows: ScanRootOption[] =
    rich?.length ?
      rich.map((d) => ({
        path: d.path,
        label: d.label,
        title: d.label,
        value: d.path,
        is_recommended: Boolean(d.is_recommended),
        matched_type: d.matched_type ?? null,
        file_summary: d.file_summary,
      }))
    : legacy?.length ?
      legacy.map((d) => ({
        path: d.path,
        label: d.path,
        title: d.path,
        value: d.path,
        is_recommended: Boolean(d.recommended),
      }))
    : []

  if (rows.length) {
    return [...rows].sort((a, b) => {
      const score = (row: ScanRootOption) => {
        let s = row.path === '.' ? 20 : row.path.split('/').length - 1
        if (prefer && row.matched_type === prefer) s -= 100
        if (row.is_recommended) s -= 10
        return s
      }
      const sa = score(a)
      const sb = score(b)
      return sa - sb || a.path.localeCompare(b.path)
    })
  }
  const cur = (repoForm.value.scan_root || '').trim() || '.'
  return [{ path: cur, label: cur, title: cur, value: cur }]
})

function syncScanRootForRepoType(typeValue: string) {
  const prefer =
    typeValue === AUTO_REPO_TYPE ?
      lastDetect.value?.detected_type || repoTypeToMatchedType(lastDetect.value?.repo_type || '')
    : repoTypeToMatchedType(typeValue)

  const dirs = lastDetect.value?.directories
  if (dirs?.length && prefer) {
    const hit =
      dirs.find((d) => d.matched_type === prefer && d.is_recommended) ??
      dirs.find((d) => d.matched_type === prefer)
    if (hit?.path) {
      repoForm.value.scan_root = hit.path
      return
    }
  }

  const cands = lastDetect.value?.candidates
  if (!cands?.length) return
  const key =
    typeValue === AUTO_REPO_TYPE ?
      normalizeRepoType(lastDetect.value?.repo_type || '')
    : normalizeRepoType(typeValue)
  const match = cands.find(
    (c) => normalizeRepoType(c.repo_type_id || c.repo_type || '') === key,
  )
  if (match?.scan_root) repoForm.value.scan_root = match.scan_root
}
const advancedPanels = ref<number[]>([])

const notifyWebhookFilled = computed(() =>
  Boolean(String(repoForm.value.notify_webhook_url || repoForm.value.webhook_notify_url || '').trim()),
)
const testNotifyDisabled = computed(() => !notifyWebhookFilled.value || notifyTesting.value)
const highRiskPathsText = ref('')
const lowRiskPathsText = ref('')
const notifyTesting = ref(false)

const notifyPolicyItems = [
  { title: '关闭通知', value: 'off' as const },
  { title: '仅 BLOCK 时通知（默认）', value: 'block_only' as const },
  { title: '每次门禁结果均通知', value: 'always' as const },
]
const notifyPolicyItemsWhenWebhook = computed(() =>
  notifyPolicyItems.filter((i) => i.value !== 'off'),
)

/** 仅红框，不展示 Vuetify「必填」副文案（见 repo-form-page.css） */
const requiredBorderOnly = (v: unknown) =>
  (v !== null && v !== undefined && String(v).trim() !== '') || false

watch(
  () => repoForm.value.clone_url,
  (url) => {
    if (fullNameManual.value || editingId.value) return
    const parsed = parseFullNameFromCloneUrl(url || '')
    if (parsed) repoForm.value.full_name = parsed
  },
)

watch(
  () => repoForm.value.provider,
  (p) => {
    if (p === 'local') repoForm.value.auth_method = 'none'
  },
)

function onRepoTypePicked(value: string | null) {
  const v = value ?? AUTO_REPO_TYPE
  repoTypeManualOverride.value = v !== AUTO_REPO_TYPE
  if (v !== AUTO_REPO_TYPE) syncScanRootForRepoType(v)
}

watch(
  () => repoForm.value.repo_type,
  (t) => {
    if (t === AUTO_REPO_TYPE) {
      repoTypeManualOverride.value = false
      if (lastDetect.value?.scan_root) repoForm.value.scan_root = lastDetect.value.scan_root
    } else {
      repoTypeManualOverride.value = true
    }
    const key = t === AUTO_REPO_TYPE ? effectiveRepoType.value : normalizeRepoType(t)
    if (repoTypeManualOverride.value && t !== AUTO_REPO_TYPE) {
      syncScanRootForRepoType(t)
      return
    }
    if (key === 'backend_java') {
      const cur = (repoForm.value.scan_root || '').trim()
      if (!cur || cur === '.') repoForm.value.scan_root = 'src/main/java'
    }
    if (key === 'backend_go') {
      const cur = (repoForm.value.scan_root || '').trim()
      if (!cur) repoForm.value.scan_root = '.'
    }
  },
)

function applyDetectResult(r: DetectRepositoryProfile) {
  lastDetect.value = r
  const scan = r.recommended_root || r.suggested_scan_root || r.scan_root
  monorepoHint.value =
    r.monorepo_hint ||
    (r.is_monorepo ? '检测到当前仓库同时包含 frontend 与 backend 模块（Monorepo）。' : '')
  if (r.default_branch) repoForm.value.default_branch = r.default_branch
  if (!(fullNameManual.value && editingId.value)) {
    const name = r.suggested_full_name || r.suggested_name
    if (name) repoForm.value.full_name = name
  }
  if (repoTypeManualOverride.value) {
    if (!r.is_monorepo) monorepoDualCreate.value = false
    return
  }
  repoForm.value.repo_type = AUTO_REPO_TYPE
  repoForm.value.scan_root = scan
  if (!r.is_monorepo) monorepoDualCreate.value = false
}

async function runRepoDetect() {
  const url = (repoForm.value.clone_url || '').trim()
  if (!url) {
    cloneUrlDetectError.value = isLocalProvider.value
      ? '请先填写本地路径或 Clone URL'
      : '请填写 Clone URL'
    return
  }
  cloneUrlDetectError.value = ''
  if (detectLoading.value) return
  detectLoading.value = true
  try {
    const r = await detectRepositoryProfile({
      clone_url: url,
      source_type: repoForm.value.provider,
      branch: repoForm.value.default_branch || 'main',
      auth_mode: repoForm.value.auth_method,
      custom_token:
        repoForm.value.auth_method === 'token' && accessToken.value.trim()
          ? accessToken.value.trim()
          : null,
    })
    applyDetectResult(r)
  } catch {
    lastDetect.value = null
    monorepoHint.value = ''
    monorepoDualCreate.value = false
  } finally {
    detectLoading.value = false
  }
}

async function onCloneUrlBlur() {
  if (!(fullNameManual.value && editingId.value)) {
    const parsed = parseFullNameFromCloneUrl(repoForm.value.clone_url || '')
    if (parsed) {
      repoForm.value.full_name = parsed
      fullNameManual.value = false
    }
  }
  await runRepoDetect()
}

let cloneUrlDetectDebounce: number | undefined
watch(
  () => repoForm.value.clone_url,
  (raw) => {
    const url = (raw || '').trim()
    if (url) cloneUrlDetectError.value = ''
    if (url.length < 8) return
    if (repoTypeManualOverride.value && repoForm.value.repo_type !== AUTO_REPO_TYPE) return
    if (cloneUrlDetectDebounce) window.clearTimeout(cloneUrlDetectDebounce)
    cloneUrlDetectDebounce = window.setTimeout(() => {
      void runRepoDetect()
    }, 700)
  },
)

const providerItems = [
  { title: 'GitLab', value: 'gitlab' as RepoProvider },
  { title: 'GitHub', value: 'github' as RepoProvider },
  { title: '本地', value: 'local' as RepoProvider },
]

const authItems = [
  { title: '无认证（公开/本地）', value: 'none' as AuthMethod },
  { title: 'Access Token（推荐）', value: 'token' as AuthMethod },
  { title: 'SSH 私钥', value: 'ssh' as AuthMethod },
]

const providerSelectOptions = computed((): OutlinedSelectOption[] =>
  providerItems.map((i) => ({ value: i.value, label: i.title })),
)

const authSelectOptions = computed((): OutlinedSelectOption[] =>
  authItems.map((i) => ({ value: i.value, label: i.title })),
)

const scanRootSelectOptions = computed((): OutlinedSelectOption[] =>
  scanRootOptions.value.map((d) => ({
    value: d.path,
    label: d.label,
    badge: d.is_recommended ? '推荐' : undefined,
    description: d.file_summary,
  })),
)

const repoTypeSelectOptions = computed((): OutlinedSelectOption[] =>
  repoTypeItems.value.map((i) => ({
    value: i.value,
    label: i.title,
    disabled: Boolean(i.props?.disabled),
  })),
)

const testSuiteSelectOptions = computed((): OutlinedSelectOption[] =>
  testSuiteOptions.value.map((o) => ({
    value: o.value,
    label: o.title,
    description: (o.description || o.slug || '').trim() || undefined,
    disabled: Boolean(o.disabled),
  })),
)

const linkedRepoSelectOptions = computed((): OutlinedSelectOption[] =>
  linkedRepoOptions.value.map((o) => ({
    value: o.value,
    label: o.title,
  })),
)

const notifyPolicySelectOptions = computed((): OutlinedSelectOption[] =>
  notifyPolicyItemsWhenWebhook.value.map((i) => ({
    value: i.value,
    label: i.title,
  })),
)

function repoTypeIconFor(value: string) {
  return (
    repoTypeItems.value.find((i) => i.value === value)?.icon ??
    REPO_TYPE_OPTION_ICONS[value] ??
    'mdi-code-braces'
  )
}

const accessTokenHelper = computed(() =>
  editingTokenConfigured.value
    ? '已配置，留空表示不修改。后端静默拉取代码执行 Git Diff / AST'
    : '后端静默拉取代码执行 Git Diff / AST',
)

const sshPrivateKeyHelper = computed(
  () =>
    '仅填写私钥；GitHub/GitLab 添加的是配对的公钥（ssh-ed25519 / ssh-rsa），不要粘贴私钥对应的 .pub 行。',
)

function validateRepoCoreFields(): boolean {
  if (!String(repoForm.value.full_name || '').trim()) {
    notify('请填写全称', 'error')
    return false
  }
  if (!String(repoForm.value.clone_url || '').trim()) {
    notify(isLocalProvider.value ? '请填写本地路径 / Clone URL' : '请填写 Clone URL', 'error')
    return false
  }
  return true
}

function openCreate() {
  editingId.value = null
  fullNameManual.value = false
  accessToken.value = ''
  sshPrivateKey.value = ''
  editingTokenConfigured.value = false
  editingSshConfigured.value = false
  Object.assign(repoForm.value, {
    full_name: '',
    provider: 'gitlab' as RepoProvider,
    clone_url: '',
    default_branch: 'main',
    description: '',
    enabled: true,
    webhook_enabled: true,
    coverage_threshold: 80,
    auth_method: 'none' as AuthMethod,
    scan_root: '.',
    test_suite_id: '',
    webhook_notify_url: '',
    notify_webhook_url: '',
    notify_policy: 'block_only',
    high_risk_paths: [],
    low_risk_paths: [],
    high_risk_api_threshold: undefined,
    high_risk_symbol_threshold: undefined,
    allow_self_override: false,
    repo_type: AUTO_REPO_TYPE,
    api_base_prefix: '/api/v1',
  api_strip_prefix: '',
    linked_repo_ids: [],
  })
  lastDetect.value = null
  monorepoHint.value = ''
  monorepoDualCreate.value = false
  repoTypeManualOverride.value = false
  highRiskPathsText.value = ''
  lowRiskPathsText.value = ''
  advancedPanels.value = []
}

function openEdit(row: RepositoryItem) {
  editingId.value = row.id
  fullNameManual.value = true
  accessToken.value = ''
  sshPrivateKey.value = ''
  editingTokenConfigured.value = Boolean(row.token_configured)
  editingSshConfigured.value = Boolean(row.ssh_configured)
  Object.assign(repoForm.value, {
    full_name: row.full_name,
    provider: row.provider,
    clone_url: row.clone_url,
    default_branch: row.default_branch,
    description: row.description ?? '',
    enabled: row.enabled,
    webhook_enabled: row.webhook_enabled,
    coverage_threshold: row.coverage_threshold ?? 80,
    auth_method: row.auth_method ?? 'none',
    scan_root: row.scan_root || '.',
    test_suite_id: row.test_suite_id ?? '',
    webhook_notify_url: row.notify_webhook_url ?? row.webhook_notify_url ?? '',
    notify_webhook_url: row.notify_webhook_url ?? row.webhook_notify_url ?? '',
    notify_policy: row.notify_policy ?? 'block_only',
    high_risk_paths: row.high_risk_paths ?? [],
    low_risk_paths: row.low_risk_paths ?? [],
    high_risk_api_threshold: row.high_risk_api_threshold ?? undefined,
    high_risk_symbol_threshold: row.high_risk_symbol_threshold ?? undefined,
    allow_self_override: row.allow_self_override ?? false,
    repo_type: normalizeRepoType(row.repo_type),
    api_base_prefix: row.api_base_prefix ?? '',
    api_strip_prefix: row.api_strip_prefix ?? '',
    linked_repo_ids: row.linked_repo_ids ?? [],
  })
  highRiskPathsText.value = (row.high_risk_paths ?? []).join('\n')
  lowRiskPathsText.value = (row.low_risk_paths ?? []).join('\n')
  advancedPanels.value = []
  const rt = normalizeRepoType(row.repo_type)
  repoTypeManualOverride.value = rt !== AUTO_REPO_TYPE
}

function buildPayload(): RepositoryPayload {
  const payload: RepositoryPayload = { ...repoForm.value }
  const patterns = highRiskPathsText.value
    .split(/\r?\n/u)
    .map((s) => s.trim())
    .filter(Boolean)
  payload.high_risk_paths = patterns
  const lowPatterns = lowRiskPathsText.value
    .split(/\r?\n/u)
    .map((s) => s.trim())
    .filter(Boolean)
  payload.low_risk_paths = lowPatterns.length ? lowPatterns : null
  const notifyUrl = (repoForm.value.notify_webhook_url || repoForm.value.webhook_notify_url || '').trim()
  payload.notify_webhook_url = notifyUrl || null
  payload.webhook_notify_url = notifyUrl || null
  if (!payload.test_suite_id) payload.test_suite_id = null
  if (repoForm.value.auth_method === 'token' && accessToken.value) {
    payload.access_token = accessToken.value
  }
  if (repoForm.value.auth_method === 'ssh' && sshPrivateKey.value) {
    payload.ssh_private_key = sshPrivateKey.value
  }
  return payload
}

async function sendTestNotify() {
  const url = (
    repoForm.value.notify_webhook_url ||
    repoForm.value.webhook_notify_url ||
    ''
  ).trim()
  if (!url) {
    notify('请先填写 Webhook 地址', 'error')
    return
  }
  notifyTesting.value = true
  try {
    const r = await testRepositoryNotify(url)
    notify(r.message || '测试消息已发送')
  } catch (err) {
    notify(readApiError(err, '测试发送失败'), 'error')
  } finally {
    notifyTesting.value = false
  }
}

async function submit() {
  if (!validateRepoCoreFields()) return
  const { valid } = (await formRef.value?.validate()) ?? { valid: true }
  if (!valid) return
  if (repoForm.value.auth_method === 'ssh') {
    const pasted = sshPrivateKey.value.trim().length > 0
    if (!pasted && !editingSshConfigured.value) {
      notify('请粘贴 SSH 私钥（与 GitHub Deploy key 配对的那把私钥文件全文）', 'error')
      return
    }
  }
  const payload = buildPayload()
  if (
    !editingId.value &&
    monorepoDualCreate.value &&
    lastDetect.value?.is_monorepo &&
    (lastDetect.value.candidates?.length || 0) >= 2
  ) {
    const cands = (lastDetect.value.candidates || [])
      .filter((c) => c.repo_type_id)
      .map((c) => ({ repo_type_id: c.repo_type_id as string, scan_root: c.scan_root }))
    if (cands.length >= 2) {
      const base = (
        lastDetect.value.suggested_name ||
        parseFullNameFromCloneUrl(repoForm.value.clone_url || '') ||
        repoForm.value.full_name
      ).replace(/\s*\([^)]+\)\s*$/u, '')
      submitLoading.value = true
      submitPhase.value = 'saving'
      try {
        const created = await createMonorepoBundle({
          clone_url: repoForm.value.clone_url,
          provider: repoForm.value.provider,
          default_branch: repoForm.value.default_branch,
          base_full_name: base,
          description: repoForm.value.description || null,
          candidates: cands.slice(0, 8),
        })
        notify(`已一键双建 ${created.length} 条仓库记录并已互相关联`)
        for (const row of created) {
          try {
            await reindexRepository(row.id)
          } catch {
            /* 单条索引失败不阻塞 */
          }
        }
        goBack()
      } catch (err) {
        notify(readApiError(err, 'Monorepo 双建失败'), 'error')
      } finally {
        submitLoading.value = false
        submitPhase.value = 'idle'
      }
      return
    }
  }
  if (payload.repo_type === AUTO_REPO_TYPE) {
    if (!lastDetect.value) await runRepoDetect()
    if (!lastDetect.value) {
      notify('无法自动识别仓库类型，请手动选择仓库类型', 'error')
      return
    }
    payload.repo_type = lastDetect.value.repo_type
    if (!(payload.scan_root || '').trim()) {
      payload.scan_root = lastDetect.value.suggested_scan_root || lastDetect.value.scan_root
    }
  }
  submitLoading.value = true
  submitPhase.value = 'saving'
  try {
    if (editingId.value) {
      await updateRepository(editingId.value, payload)
      notify('仓库配置已更新')
      goBack()
    } else {
      const created = await createRepository(payload)
      submitPhase.value = 'indexing'
      notifyInProgress(`正在构建 AST 索引：${created.full_name}…`)
      try {
        const res = await reindexRepository(created.id)
        const m = res.stats?.method_count ?? res.repository.ast_method_count
        const a = res.stats?.api_count ?? res.repository.ast_api_count
        notify(`AST 索引完成：${m} 方法 · ${a} 接口`)
        goBack()
      } catch (indexErr) {
        notify(
          readApiError(indexErr, '仓库已保存，AST 索引构建失败，请在列表中手动重建'),
          'error',
        )
      }
    }
  } catch {
    notify('保存失败', 'error')
  } finally {
    submitLoading.value = false
    submitPhase.value = 'idle'
  }
}



function mapTestSuiteOption(row: TestSuiteItem, disabledNote = false): TestSuiteSelectOption {
  const slug = row.slug
  const label = row.name === slug ? row.name : `${row.name}（${slug}）`
  return {
    title: disabledNote ? `${label} · 已停用` : label,
    value: slug,
    slug,
    description: row.description,
    disabled: disabledNote || !row.enabled,
  }
}

async function loadTestSuiteOptions() {
  testSuiteOptionsLoading.value = true
  try {
    let rows = await fetchTestSuites(undefined, true)
    const current = (repoForm.value.test_suite_id || '').trim()
    if (current && !rows.some((r) => r.slug === current)) {
      const all = await fetchTestSuites()
      const legacy = all.find((r) => r.slug === current)
      if (legacy) rows = [...rows, legacy]
    }
    testSuiteOptions.value = rows.map((r) => mapTestSuiteOption(r, !r.enabled))
  } catch {
    try {
      const presets = await fetchTestSuitePresets()
      testSuiteOptions.value = presets.map((p) => ({
        title: p.name === p.slug ? p.name : `${p.name}（${p.slug}）`,
        value: p.slug,
        slug: p.slug,
        description: p.description ?? null,
      }))
    } catch {
      testSuiteOptions.value = []
    }
  } finally {
    testSuiteOptionsLoading.value = false
  }
}

function goTestSuitesAdmin() {
  void router.push({ path: '/test-suites' })
}

onActivated(() => {
  void loadTestSuiteOptions()
})

onMounted(async () => {
  await loadTestSuiteOptions()
  try {
    linkedRepoRows.value = await fetchRepositories()
  } catch {
    linkedRepoRows.value = []
  }
  try {
    const meta = await fetchRepoTypeOptions()
    repoTypeItems.value = [
      {
        title: '自动识别（根据仓库地址探测）',
        value: AUTO_REPO_TYPE,
        icon: REPO_TYPE_OPTION_ICONS.auto,
      },
      ...meta.map((row) => {
        const comingSoon = Boolean(row.coming_soon) && !row.index_supported
        return repoTypeItem({
          id: row.id,
          label: comingSoon ? `${row.label}（敬请期待）` : row.label,
          comingSoon,
        })
      }),
    ]
  } catch {
    /* 保留本地默认项 */
  }
  const id = route.params.id as string | undefined
  if (route.name === 'repository-edit' && id) {
    const row = linkedRepoRows.value.find((r) => r.id === id)
    if (!row) {
      notify('仓库不存在或无权访问', 'error')
      goBack()
      return
    }
    openEdit(row)
  } else {
    openCreate()
  }
})
</script>

<template>
  <div class="repo-form-page repo-form-page--v2 dg-outlined-form-page">
    <header class="repo-form-page__topbar">
      <div class="repo-form-page__topbar-main">
        <v-btn
          class="text-none repo-form-page__back"
          variant="text"
          size="small"
          prepend-icon="mdi-arrow-left"
          @click="goBack"
        >
          返回
        </v-btn>
        <div class="repo-form-page__titles">
          <h1 class="repo-form-page__title">{{ pageTitle }}</h1>
          <p class="repo-form-page__subtitle">
            配置仓库接入、扫描目录、门禁阈值与 Webhook；
            {{ editingId ? '保存后立即生效' : '保存后将初始化 AST 索引' }}。
          </p>
        </div>
      </div>
    </header>

    <v-form
      ref="formRef"
      class="repo-form-page__body repo-dialog-form dg-dark-form"
      autocomplete="off"
      validate-on="blur lazy"
      @submit.prevent="submit"
    >
      <section class="dg-form-card">
        <h2 class="dg-form-card__title">基础信息</h2>

        <div
          class="dg-form-grid-3 grid-layout dg-form-grid-3--strict dg-form-grid-3--basic-head"
          :class="{ 'dg-form-grid-3--local grid-layout--local': isLocalProvider }"
        >
          <div class="dg-form-item form-group md-field-item">
            <OutlinedSelect
              id="repo-form-provider"
              v-model="repoForm.provider"
              label-above
              :options="providerSelectOptions"
            >
              <template #label>
                来源 <span class="dg-form-required required-star" aria-hidden="true">*</span>
              </template>
            </OutlinedSelect>
          </div>
          <div v-if="!isLocalProvider" class="dg-form-item form-group md-field-item">
            <OutlinedSelect
              id="repo-form-auth"
              v-model="repoForm.auth_method"
              label-above
              label="认证方式"
              :options="authSelectOptions"
            />
          </div>
          <div class="dg-form-item form-group md-field-item">
            <OutlinedInput
              id="repo-form-branch"
              v-model="repoForm.default_branch"
              label-above
              label="默认分支"
              mono
            />
          </div>
        </div>

        <div class="dg-form-grid-2 dg-form-grid-2--pair">
          <div class="dg-form-item form-group md-field-item">
            <OutlinedInput
              id="repo-form-full-name"
              v-model="repoForm.full_name"
              label-above
              @update:model-value="fullNameManual = true"
            >
              <template #label>
                全称 <span class="dg-form-required required-star" aria-hidden="true">*</span>
              </template>
            </OutlinedInput>
          </div>
          <div class="dg-form-item form-group md-field-item">
            <OutlinedInput
              id="repo-form-clone-url"
              v-model="repoForm.clone_url"
              label-above
              mono
              :helper-text="cloneUrlPlaceholder"
              @blur="onCloneUrlBlur"
            >
              <template #label>
                <span>{{ isLocalProvider ? '本地路径 / Clone URL' : 'Clone URL' }}</span>
                <span class="dg-form-required required-star" aria-hidden="true">*</span>
              </template>
            </OutlinedInput>
            <p v-if="cloneUrlDetectError" class="dg-form-error-text error-text">{{ cloneUrlDetectError }}</p>
          </div>
        </div>

        <div class="dg-form-item dg-form-item--full form-group md-field-item">
          <OutlinedTextarea
            id="repo-form-desc"
            v-model="repoForm.description"
            label-above
            :rows="3"
          >
            <template #label>
              描述<span class="md-field-label-sub">（可选）</span>
            </template>
          </OutlinedTextarea>
        </div>

        <div
          v-if="repoForm.auth_method === 'token'"
          class="dg-form-item dg-form-item--full form-group md-field-item"
        >
          <OutlinedPasswordInput
            id="repo-form-access-token"
            v-model="accessToken"
            label-above
            label="Access Token"
            allow-paste
            :helper-text="accessTokenHelper"
          />
        </div>
        <div
          v-else-if="repoForm.auth_method === 'ssh'"
          class="dg-form-item dg-form-item--full form-group md-field-item"
        >
          <OutlinedTextarea
            id="repo-form-ssh-key"
            v-model="sshPrivateKey"
            label-above
            label="SSH 私钥"
            :rows="6"
            allow-file-import
            accept-file-types=".pem,.key,.pub,text/plain"
            control-class="md-field-control--mono"
            :helper-text="sshPrivateKeyHelper"
          />
        </div>
      </section>

      <section class="dg-form-card">
        <h2 class="dg-form-card__title">扫描与联动</h2>
        <div v-if="monorepoHint" class="dg-form-item dg-form-item--full">
          <v-alert type="info" variant="tonal" density="compact" class="repo-monorepo-hint">
            {{ monorepoHint }}
          </v-alert>
          <v-checkbox
            v-if="lastDetect?.is_monorepo && !editingId"
            v-model="monorepoDualCreate"
            density="compact"
            hide-details
            color="primary"
            label="同时创建前后端两条仓库记录，并自动建立跨仓联动"
          />
        </div>

        <div class="dg-form-item form-group md-field-item dg-md-outlined-item--repo-type">
          <div class="repo-type-inline">
            <OutlinedSelect
              id="repo-form-repo-type"
              v-model="repoForm.repo_type"
              label-above
              label="仓库类型"
              :options="repoTypeSelectOptions"
              :disabled="detectLoading"
              :loading="detectLoading"
              searchable
              class="repo-type-select-outlined"
              @update:model-value="onRepoTypePicked"
            >
              <template #selection>
                <span class="repo-type-selection">
                  <v-icon
                    v-if="selectedRepoTypeDisplay.icon"
                    :icon="selectedRepoTypeDisplay.icon"
                    size="18"
                    color="primary"
                    class="repo-type-selection__icon"
                  />
                  <span class="repo-type-selection__text">{{ selectedRepoTypeDisplay.title }}</span>
                </span>
              </template>
              <template #option="{ option }">
                <div class="md-field-select-option__main repo-type-select-option">
                  <v-icon
                    :icon="repoTypeIconFor(option.value)"
                    size="18"
                    color="primary"
                    class="repo-type-select-option__icon"
                  />
                  <span class="md-field-select-option__label">{{ option.label }}</span>
                </div>
              </template>
            </OutlinedSelect>
            <v-tooltip
              location="top"
              :text="canTriggerRepoDetect ? '根据地址重新识别仓库类型与扫描目录' : '请先在上方填写 Clone URL 或本地路径'"
            >
              <template #activator="{ props: tipProps }">
                <v-btn
                  v-bind="tipProps"
                  class="repo-redetect-btn text-none"
                  size="small"
                  variant="outlined"
                  color="primary"
                  :loading="detectLoading"
                  :disabled="detectLoading"
                  @click="runRepoDetect"
                >
                  重新探测
                </v-btn>
              </template>
            </v-tooltip>
          </div>
          <p v-if="!canTriggerRepoDetect" class="dg-form-hint dg-form-hint--spaced">
            填写上方 Clone URL 后可自动探测，或点击「重新探测」
          </p>
          <p
            v-else-if="autoDetectLabel && repoForm.repo_type === AUTO_REPO_TYPE"
            class="dg-form-hint dg-form-hint--success dg-form-hint--spaced"
          >
            已自动识别为：{{ autoDetectLabel }}
          </p>
        </div>

        <div class="dg-form-item form-group md-field-item dg-form-item--full">
          <v-tooltip
            location="top"
            :text="repoForm.scan_root || scanRootPlaceholder"
            :disabled="!scanRootTooltipActive"
          >
            <template #activator="{ props: tipProps }">
              <div v-bind="tipProps" class="repo-form-tooltip-activator">
                <OutlinedSelect
                  id="repo-form-scan-root"
                  v-model="repoForm.scan_root"
                  label-above
                  label="源码根目录"
                  :options="scanRootSelectOptions"
                  searchable
                  free-solo
                  clearable
                  :helper-text="lastDetect ? undefined : scanRootPlaceholder"
                />
              </div>
            </template>
          </v-tooltip>
        </div>

        <div class="dg-form-item form-group md-field-item dg-form-item--full dg-form-suite-field">
          <OutlinedSelect
            id="repo-form-test-suite"
            v-model="repoForm.test_suite_id"
            label-above
            label="关联用例集"
            :options="testSuiteSelectOptions"
            :placeholder="testSuitePlaceholder"
            :disabled="testSuiteOptionsLoading"
            :loading="testSuiteOptionsLoading"
            searchable
            clearable
            class="repo-form-test-suite-outlined"
          >
            <template #trigger-affix>
              <button
                type="button"
                class="dg-suite-field-icon"
                aria-label="用例集管理"
                title="用例集管理"
                @click.stop="goTestSuitesAdmin"
              >
                <v-icon icon="mdi-open-in-new" size="18" aria-hidden="true" />
              </button>
              <button
                type="button"
                class="dg-suite-field-icon"
                aria-label="刷新用例集列表"
                title="刷新列表"
                :disabled="testSuiteOptionsLoading"
                @click.stop="loadTestSuiteOptions"
              >
                <v-icon icon="mdi-refresh" size="18" aria-hidden="true" />
              </button>
            </template>
            <template #empty>
              <div class="repo-test-suite-menu-empty">
                暂无已启用用例集，
                <button type="button" class="dg-inline-link text-none" @click="goTestSuitesAdmin">
                  前往用例集管理新建
                </button>
              </div>
            </template>
            <template #menu-footer>
              <button type="button" class="repo-test-suite-menu-footer-btn" @click="goTestSuitesAdmin">
                用例集管理…
                <span class="repo-test-suite-menu-footer-btn__sub">新建 / 编辑后点此刷新列表</span>
              </button>
            </template>
          </OutlinedSelect>
          <div class="dg-form-suite-meta dg-form-suite-meta--hint-only">
            <p v-if="testSuiteStatusHint" class="dg-form-hint">{{ testSuiteStatusHint }}</p>
            <p v-else-if="inheritedTestSuiteHint" class="dg-form-hint">{{ inheritedTestSuiteHint }}</p>
            <p v-else-if="!testSuiteOptionsLoading && !testSuiteOptions.length" class="dg-form-hint">
              在用例集管理中登记并启用后，将出现在此下拉列表。
            </p>
          </div>
        </div>

        <div v-if="isFrontendRepo" class="dg-form-grid-2 dg-form-grid-2--pair">
          <div class="dg-form-item form-group md-field-item">
            <OutlinedInput
              id="repo-form-api-base"
              v-model="repoForm.api_base_prefix"
              label-above
              label="统一 API 前缀"
              mono
              helper-text="与后端 FastAPI 路由对齐；留空则尝试读取 .env 中 VITE_API_BASE。"
            />
          </div>
          <div class="dg-form-item form-group md-field-item">
            <OutlinedInput
              id="repo-form-api-strip"
              v-model="repoForm.api_strip_prefix"
              label-above
              label="网关剥离前缀"
              mono
              helper-text="先剥离 Nginx/网关对外前缀，再与后端实际路由匹配。"
            />
          </div>
        </div>

        <div class="dg-form-item form-group md-field-item dg-form-item--full">
          <OutlinedSelect
            id="repo-form-linked"
            v-model="repoForm.linked_repo_ids"
            label-above
            label="关联上下游仓库"
            :options="linkedRepoSelectOptions"
            multiple
            searchable
            clearable
            placeholder="选择需要联动的上下游仓库（可选）"
            class="repo-form-linked-outlined"
          >
            <template #empty>
              <div class="repo-linked-menu-empty">
                <v-icon icon="mdi-source-branch" size="22" class="repo-linked-menu-empty__icon" />
                <span>暂无其他可关联仓库</span>
                <span class="repo-linked-menu-empty__hint">先保存本仓库，或接入更多仓库后再关联</span>
              </div>
            </template>
          </OutlinedSelect>
        </div>
      </section>

      <section class="dg-form-card dg-form-card--advanced">
            <v-expansion-panels
              v-model="advancedPanels"
              variant="accordion"
              class="repo-advanced-panels repo-advanced-panels--form-tail"
            >
              <v-expansion-panel elevation="0">
                <v-expansion-panel-title class="repo-advanced-panels__title text-body-2">
                  高级配置（门禁阈值 / 高危目录 / 通知）
                </v-expansion-panel-title>
                <v-expansion-panel-text class="repo-advanced-panel-body">
                  <section class="dg-advanced-block repo-threshold-block">
                    <h3 class="dg-advanced-section-title">门禁阈值</h3>
                    <div class="dg-form-grid-3 dg-advanced-threshold-grid">
                      <div class="dg-form-item form-group md-field-item repo-coverage-field">
                        <label
                          id="repo-form-coverage-label"
                          class="md-field-label-above outlined-label repo-coverage-field__label"
                          for="repo-form-coverage"
                        >
                          增量覆盖率阈值
                        </label>
                        <div
                          class="repo-coverage-outlined repo-coverage-outlined--label-above"
                          role="group"
                          aria-labelledby="repo-form-coverage-label"
                        >
                          <div class="repo-coverage-outlined__inner">
                            <v-slider
                              id="repo-form-coverage"
                              v-model="repoForm.coverage_threshold"
                              class="repo-coverage-outlined__slider"
                              :min="0"
                              :max="100"
                              step="1"
                              color="#3B82F6"
                              track-color="rgba(255, 255, 255, 0.12)"
                              track-size="3"
                              thumb-size="16"
                              hide-details
                              thumb-label="never"
                            />
                            <output class="repo-coverage-outlined__value" for="repo-form-coverage">
                              {{ repoForm.coverage_threshold }}%
                            </output>
                          </div>
                        </div>
                      </div>
                      <div class="dg-form-item form-group dg-md-outlined-item">
                        <v-text-field
                          id="repo-form-api-threshold"
                          v-model.number="repoForm.high_risk_api_threshold"
                          label="高危 API 数量阈值"
                          type="number"
                          variant="outlined"
                          density="comfortable"
                          hide-details
                          autocomplete="off"
                          placeholder="默认 5"
                          class="repo-form-field repo-form-field--number repo-form-field--single-line repo-threshold-number"
                        />
                      </div>
                      <div class="dg-form-item form-group dg-md-outlined-item">
                        <v-text-field
                          id="repo-form-symbol-threshold"
                          v-model.number="repoForm.high_risk_symbol_threshold"
                          label="高危符号数量阈值"
                          type="number"
                          variant="outlined"
                          density="comfortable"
                          hide-details
                          autocomplete="off"
                          placeholder="默认 8"
                          class="repo-form-field repo-form-field--number repo-form-field--single-line repo-threshold-number"
                        />
                      </div>
                    </div>
                  </section>

                  <section class="dg-advanced-block repo-risk-rules-block">
                    <h3 class="dg-advanced-section-title">高危模块分级规则</h3>
                    <div class="dg-form-grid-2 dg-form-grid-2--rules">
                      <div class="dg-form-item form-group dg-md-outlined-item">
                        <v-textarea
                          id="repo-form-high-risk"
                          v-model="highRiskPathsText"
                          label="高危路径黑名单（禁止合入）"
                          variant="outlined"
                          density="comfortable"
                          rows="3"
                          hide-details
                          placeholder="app/payment/**&#10;**/auth.py"
                          class="repo-form-field repo-form-field--mono repo-form-field--risk rules-textarea"
                        />
                      </div>
                      <div class="dg-form-item form-group dg-md-outlined-item">
                        <v-textarea
                          id="repo-form-low-risk"
                          v-model="lowRiskPathsText"
                          label="低危路径白名单（忽略拦截）"
                          variant="outlined"
                          density="comfortable"
                          rows="3"
                          hide-details
                          placeholder="tests/**&#10;app/utils/**"
                          class="repo-form-field repo-form-field--mono repo-form-field--risk rules-textarea"
                        />
                      </div>
                    </div>
                    <p class="dg-glob-hint">
                      每行一条 glob 规则；命中黑名单直接触发高危拦截，命中白名单不计入数量阈值。
                    </p>
                  </section>

                  <section class="dg-advanced-block repo-notify-block">
                    <h3 class="dg-advanced-section-title">IM 门禁通知</h3>
                    <div class="dg-form-item form-group dg-md-outlined-item repo-notify-url-wrap">
                      <div class="repo-notify-row repo-notify-row--v2">
                        <v-text-field
                          v-model="repoForm.notify_webhook_url"
                          id="diffgate-notify-webhook-url"
                          name="diffgate_notify_webhook_url"
                          label="Webhook 地址"
                          type="text"
                          inputmode="url"
                          autocomplete="new-password"
                          autocapitalize="off"
                          spellcheck="false"
                          variant="outlined"
                          density="comfortable"
                          hide-details
                          placeholder="请输入 Webhook 地址（飞书 / 钉钉 / 企业微信）"
                          class="repo-form-field repo-notify-url-field"
                        />
                      <v-btn
                        class="text-none repo-test-notify-btn repo-test-notify-btn--v2"
                        variant="outlined"
                        prepend-icon="mdi-send"
                        :loading="notifyTesting"
                        :disabled="testNotifyDisabled"
                        @click="sendTestNotify"
                      >
                        发送测试消息
                      </v-btn>
                      </div>
                    </div>
                    <div v-if="notifyWebhookFilled" class="dg-form-item form-group md-field-item dg-notify-policy">
                      <OutlinedSelect
                        id="repo-form-notify-policy"
                        v-model="repoForm.notify_policy"
                        label-above
                        label="门禁通知策略"
                        :options="notifyPolicySelectOptions"
                        class="repo-notify-policy-outlined"
                      />
                    </div>
                  </section>
                </v-expansion-panel-text>
              </v-expansion-panel>
            </v-expansion-panels>
      </section>
    </v-form>

    <footer class="repo-form-page__dock">
      <div class="repo-form-page__dock-inner">
        <div class="repo-form-page__dock-switches">
          <v-switch
            v-model="repoForm.enabled"
            label="启用分析"
            color="primary"
            density="comfortable"
            hide-details
            :inset="false"
            class="repo-form-switch repo-form-switch--dock"
          />
          <v-switch
            v-model="repoForm.webhook_enabled"
            label="接收 Webhook"
            color="primary"
            density="comfortable"
            hide-details
            :inset="false"
            class="repo-form-switch repo-form-switch--dock"
          />
          <v-switch
            v-model="repoForm.allow_self_override"
            label="允许提交人自审豁免"
            color="primary"
            density="comfortable"
            hide-details
            :inset="false"
            class="repo-form-switch repo-form-switch--dock"
          />
        </div>
        <v-divider class="repo-form-page__dock-divider" vertical inset />
        <div class="repo-form-page__dock-actions">
          <v-btn class="repo-dialog-cancel text-none" variant="text" @click="goBack"> 取消 </v-btn>
          <v-btn
            class="repo-dialog-submit text-none"
            variant="flat"
            color="primary"
            :loading="submitLoading"
            @click="submit"
          >
            {{ submitButtonLabel }}
          </v-btn>
        </div>
      </div>
    </footer>

    <v-snackbar
      v-model="snackbar.show"
      location="top"
      position="fixed"
      :timeout="snackbar.loading ? -1 : snackbar.variant === 'error' ? 9000 : 4000"
      :rounded="snackbar.variant === 'error' ? 'lg' : 'pill'"
      elevation="6"
      :color="snackbar.variant === 'error' ? 'error' : undefined"
      :class="[
        'feedback-snackbar',
        'feedback-snackbar--top',
        snackbar.variant === 'success' && 'feedback-snackbar--success',
        snackbar.variant === 'error' && 'feedback-snackbar--error',
        snackbar.variant === 'info' && 'feedback-snackbar--info',
      ]"
    >
      <div class="d-flex align-start ga-2 px-1 feedback-snackbar__content">
        <v-progress-circular
          v-if="snackbar.loading"
          indeterminate
          size="20"
          width="2"
          color="primary"
          class="feedback-snackbar__icon"
        />
        <v-icon
          v-else
          :icon="snackbar.variant === 'error' ? 'mdi-alert-circle-outline' : 'mdi-check-circle-outline'"
          size="small"
          class="feedback-snackbar__icon"
        />
        <span class="text-body-2 feedback-snackbar__text">{{ snackbar.text }}</span>
      </div>
    </v-snackbar>

  </div>
</template>

<style scoped>
.repo-detect-hint {
  margin: 4px 0 0;
  font-size: 0.8125rem;
  color: #4caf50;
  line-height: 1.35;
}
.repo-monorepo-hint {
  font-size: 0.875rem;
}
.repo-type-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.repo-type-select {
  flex: 1;
  min-width: 0;
  width: 100%;
}
.repo-type-selection {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: 100%;
  min-width: 0;
}
.repo-type-selection__text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.repo-type-selection__icon {
  flex-shrink: 0;
  opacity: 0.92;
}
.repo-redetect-btn {
  margin-top: 4px;
  flex-shrink: 0;
  min-width: 88px;
}
.repo-detect-url-hint {
  margin: 6px 0 0;
  line-height: 1.35;
}
.repo-page {
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
}
.repo-page-head {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  width: 100%;
  box-sizing: border-box;
  padding: 16px 0;
  margin-bottom: 0 !important;
  border-bottom: 1px solid #2a2a2a;
}
@media (max-width: 720px) {
  .repo-page-head {
    flex-wrap: wrap;
  }
}
.repo-kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 24px;
  width: 100%;
  margin-top: 24px;
  margin-bottom: 24px;
  box-sizing: border-box;
}
@media (max-width: 1280px) {
  .repo-kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 600px) {
  .repo-kpi-grid {
    grid-template-columns: 1fr;
  }
}
.repo-kpi-grid--pulse .repo-kpi-card {
  transition:
    box-shadow 0.35s ease,
    border-color 0.35s ease;
}
.repo-page-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  flex: 0 1 auto;
  min-width: 0;
  font-size: 18px;
  font-weight: 700;
  line-height: 1.2;
  color: #f3f4f6;
  white-space: nowrap;
}
.repo-page-title-count {
  font-size: 14px;
  font-weight: 500;
  color: #888;
  letter-spacing: 0.02em;
}
.repo-toolbar {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex: 0 0 auto;
  margin-left: auto;
}
.repo-search-field {
  flex: 0 0 260px;
  width: 260px;
  max-width: min(260px, 42vw);
}
.repo-search-field :deep(.v-field) {
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
  background: #1a1a1a !important;
  box-shadow: none;
  font-size: 13px;
  min-height: 36px;
  height: 36px;
  border-radius: 6px !important;
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease,
    background 0.18s ease;
}
.repo-search-field :deep(.v-field:hover) {
  border-color: rgba(59, 130, 246, 0.45) !important;
}
.repo-search-field :deep(.v-field--focused) {
  border-color: #3b82f6 !important;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
}
.repo-search-field :deep(.v-field__input) {
  min-height: 36px;
  padding-top: 0;
  padding-bottom: 0;
  padding-inline: 8px 10px;
}
.repo-search-field :deep(.v-field__prepend-inner) {
  padding-inline-start: 10px;
}
.repo-search-field :deep(.v-field__prepend-inner .v-icon) {
  opacity: 0.9;
  color: rgba(255, 255, 255, 0.65);
  font-size: 18px;
}
.repo-search-field :deep(.v-field__outline) {
  opacity: 0 !important;
}
.repo-toolbar .cta-new-analysis,
.repo-empty-module__actions .cta-new-analysis {
  flex-shrink: 0;
}
.cta-new-analysis :deep(.v-btn__prepend .v-icon) {
  font-size: 18px;
}
.repo-table-card {
  background-color: rgb(var(--v-theme-surface)) !important;
  border: 1px solid #2a2e35 !important;
  box-shadow: none !important;
  width: 100%;
  box-sizing: border-box;
  overflow: visible;
}
.repo-kpi-card {
  position: relative;
  overflow: hidden;
  background-color: #1e1e1e !important;
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.24);
}
.repo-kpi-accent {
  position: absolute;
  left: 0;
  top: 14px;
  bottom: 14px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  opacity: 0.88;
}
.repo-kpi-inner {
  padding: 20px 20px 18px 22px !important;
  min-height: 156px;
}
.repo-kpi-sub-slot {
  margin-top: auto;
  min-height: 44px;
  display: flex;
  align-items: flex-end;
  padding-top: 10px;
}
.repo-kpi-title {
  opacity: 0.72;
}
.repo-kpi-sub {
  line-height: 1.45;
  letter-spacing: 0.02em;
  font-size: 13px !important;
  color: rgba(255, 255, 255, 0.62);
}
.repo-table :deep(thead th) {
  color: rgba(255, 255, 255, 0.6) !important;
  font-weight: 600 !important;
  font-size: 13px !important;
  white-space: nowrap;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1) !important;
  padding-top: 14px !important;
  padding-bottom: 14px !important;
  background: rgba(255, 255, 255, 0.02);
}
.repo-table :deep(thead th),
.repo-table :deep(.v-data-table__td) {
  text-align: center !important;
}
.repo-table :deep(thead th .v-data-table-header__content) {
  padding-inline: 0;
  justify-content: center !important;
}
.repo-table :deep(.v-data-table__td-content) {
  display: flex;
  justify-content: center;
  align-items: center;
  width: 100%;
  min-width: 0;
}
.repo-table :deep(.repo-col-name) {
  width: 248px !important;
  min-width: 220px !important;
  max-width: 280px !important;
  overflow: hidden;
}
.repo-table :deep(.repo-col-name .v-data-table__td-content) {
  overflow: hidden;
  min-width: 0;
}
.repo-table :deep(thead th:first-child),
.repo-table :deep(.v-data-table__td:first-child),
.repo-table :deep(thead th:last-child),
.repo-table :deep(.v-data-table__td:last-child) {
  padding-inline: 16px !important;
}
.repo-table :deep(tbody tr) {
  border-bottom: none;
}
.repo-table :deep(.v-data-table__td) {
  border-bottom: 1px solid rgba(255, 255, 255, 0.05) !important;
  box-shadow: none !important;
}
.repo-table :deep(tbody tr:last-child .v-data-table__td) {
  border-bottom: none !important;
}
.repo-table :deep(.v-table__wrapper) {
  border-bottom: none;
}
.repo-table :deep(tbody td),
.repo-table :deep(.v-data-table__td) {
  vertical-align: middle !important;
  padding-top: 18px !important;
  padding-bottom: 18px !important;
  color: rgba(255, 255, 255, 0.88) !important;
  font-size: 13px;
}
.repo-table :deep(tbody tr.repo-data-row:hover > .v-data-table__td) {
  color: rgba(255, 255, 255, 0.94) !important;
}
.repo-table :deep(tr.repo-data-row--disabled > .v-data-table__td) {
  color: rgba(255, 255, 255, 0.38) !important;
}
.repo-table :deep(.v-tooltip__activator) {
  display: block;
  max-width: 100%;
  opacity: 1 !important;
  color: inherit;
}
.repo-table-switch :deep(.v-switch__track) {
  opacity: 1 !important;
  background-color: rgba(255, 255, 255, 0.08) !important;
}
.repo-table-switch :deep(.v-switch__thumb) {
  background-color: #4a4f58 !important;
  color: #4a4f58 !important;
}
.repo-table-switch.v-input--dirty :deep(.v-switch__track) {
  background-color: rgba(138, 180, 248, 0.52) !important;
}
.repo-table-switch.v-input--dirty :deep(.v-switch__thumb) {
  background-color: #8ab4f8 !important;
  color: #8ab4f8 !important;
}
.repo-name-stack {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  min-width: 0;
  max-width: 100%;
  line-height: 1.3;
  text-align: center;
  cursor: default;
}
.repo-name-project {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.94) !important;
}
.repo-name-owner {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  color: rgba(255, 255, 255, 0.48);
}
.repo-table :deep(tr.repo-data-row--disabled .repo-name-project) {
  color: rgba(255, 255, 255, 0.38) !important;
}
.repo-table :deep(tr.repo-data-row--disabled .repo-name-owner) {
  color: rgba(255, 255, 255, 0.28) !important;
}
.repo-ast-scale {
  display: inline-block;
  white-space: nowrap;
  font-size: 13px;
  letter-spacing: 0.01em;
  color: rgba(255, 255, 255, 0.78);
}
.repo-index-time {
  display: inline-block;
  white-space: nowrap;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: rgba(255, 255, 255, 0.5);
}
.repo-webhook-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
}
.repo-webhook-status--on {
  color: #81c995;
}
.repo-webhook-status--off {
  color: rgba(255, 255, 255, 0.42);
}
.repo-webhook-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #81c995;
  box-shadow: 0 0 0 2px rgba(129, 201, 149, 0.22);
  flex-shrink: 0;
}
.repo-table-cell--control,
.repo-table-cell--actions {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 40px;
  width: 100%;
}
.repo-table-cell--actions {
  justify-content: center;
  width: 100%;
  margin-inline: auto;
}
.repo-table :deep(.repo-col-actions .repo-table-cell--actions) {
  justify-content: center;
}
.repo-tone-chip {
  font-weight: 500;
  letter-spacing: 0.01em;
  border-radius: 4px !important;
  padding: 4px 10px !important;
  height: auto !important;
}
.repo-tone-chip :deep(.v-chip__underlay),
.repo-tone-chip :deep(.v-chip__overlay) {
  opacity: 0 !important;
}
.repo-tone-chip--warn {
  background: rgba(245, 158, 11, 0.15) !important;
  color: #fbbf24 !important;
  border-radius: 6px !important;
  font-size: 12px !important;
}
.repo-tone-chip--muted {
  background: rgba(142, 146, 153, 0.14) !important;
  color: #9aa0a6 !important;
}
.repo-row-action {
  width: 40px !important;
  height: 40px !important;
  border-radius: 50% !important;
  color: rgba(255, 255, 255, 0.52) !important;
  background: transparent !important;
}
.repo-row-action:hover {
  background: rgba(255, 255, 255, 0.08) !important;
  color: rgba(255, 255, 255, 0.88) !important;
}
.repo-row-action :deep(.v-btn__overlay),
.repo-row-action :deep(.v-btn__underlay) {
  opacity: 0 !important;
}
.repo-table :deep(.v-data-table-footer) {
  padding: 0 !important;
  border: none !important;
  background: transparent !important;
}
.repo-table :deep(.v-divider) {
  display: none !important;
}
.repo-pagination-wrapper {
  border-top: 1px solid rgba(255, 255, 255, 0.05) !important;
  padding: 16px 24px 20px !important;
  margin-top: 4px;
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 12px 16px;
  background-color: transparent;
}
.repo-pagination-left {
  display: flex;
  align-items: center;
  gap: 10px;
  color: rgba(255, 255, 255, 0.6);
  font-size: 13px;
}
.repo-pagination-right {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-inline-start: auto;
}
.page-text {
  color: rgba(255, 255, 255, 0.5);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.page-size-select {
  width: 96px;
  flex: 0 0 96px;
}
.page-size-select :deep(.v-field) {
  min-height: 34px !important;
  height: 34px !important;
  background-color: rgba(255, 255, 255, 0.05) !important;
  border: 1px solid rgba(255, 255, 255, 0.14) !important;
  border-radius: 8px;
  font-size: 13px;
}
.page-size-select :deep(.v-field__input) {
  min-height: 34px;
  padding: 0 14px !important;
  padding-top: 0;
  padding-bottom: 0;
  justify-content: center;
}
.page-size-select :deep(.v-field__outline),
.page-size-select :deep(.v-field__overlay) {
  opacity: 0 !important;
}
.page-buttons {
  display: flex;
  align-items: center;
  gap: 6px;
}
.repo-pagination-wrapper .page-btn {
  width: 32px !important;
  min-width: 32px !important;
  height: 32px !important;
  border-radius: 999px;
  color: rgba(255, 255, 255, 0.6) !important;
  background: transparent !important;
  transition:
    background 0.2s ease,
    color 0.2s ease;
}
.repo-pagination-wrapper .page-btn :deep(.v-btn__overlay),
.repo-pagination-wrapper .page-btn :deep(.v-btn__underlay) {
  opacity: 0 !important;
}
.repo-pagination-wrapper .page-btn :deep(.v-icon) {
  color: inherit !important;
  opacity: 1 !important;
}
.repo-pagination-wrapper .page-btn:hover:not(.v-btn--disabled) {
  background-color: rgba(255, 255, 255, 0.08) !important;
  color: #ffffff !important;
}
.repo-pagination-wrapper .page-btn.v-btn--disabled {
  color: rgba(255, 255, 255, 0.2) !important;
  opacity: 1 !important;
}
.repo-pagination-wrapper .page-btn.v-btn--disabled :deep(.v-icon) {
  color: rgba(255, 255, 255, 0.2) !important;
}
.repo-kpi-sub--warn {
  color: #f28b82;
  opacity: 0.92;
}
.repo-empty-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 200px;
  max-height: 320px;
  padding: 28px 24px !important;
  box-sizing: border-box;
}
.repo-empty-module {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 24px;
  width: 100%;
  max-width: 28rem;
  margin-inline: auto;
  text-align: center;
}
.repo-empty-module__block {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  width: 100%;
}
.repo-empty-module__text {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  width: 100%;
  max-width: 26rem;
}
.repo-empty-module__icon {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(66, 133, 244, 0.15);
  color: #8ab4f8;
}
.repo-empty-module__title {
  margin: 0;
  font-size: 1.0625rem;
  font-weight: 600;
  color: #e8eaed;
  line-height: 1.35;
}
.repo-empty-module__desc {
  margin: 0;
  font-size: 0.8125rem;
  line-height: 1.55;
  color: rgba(255, 255, 255, 0.6);
  max-width: 400px;
  width: 100%;
}
.repo-empty-module__actions {
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
}
.repo-kpi-card .kpi-value {
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.92);
}


.feedback-snackbar--success :deep(.v-snackbar__wrapper) {
  background-color: #188038 !important;
  color: #fff;
  min-width: min(520px, 92vw);
  padding-inline: 8px;
}
.feedback-snackbar--error :deep(.v-snackbar__wrapper) {
  max-width: min(560px, 92vw);
  padding: 12px 16px !important;
}
.feedback-snackbar--info :deep(.v-snackbar__wrapper) {
  background-color: #2a2f36 !important;
  color: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(138, 180, 248, 0.35);
  min-width: min(420px, 92vw);
  max-width: min(560px, 92vw);
}
.repo-table-top-progress {
  position: sticky;
  top: 0;
  z-index: 2;
}
.repo-ast-scale--loading {
  color: rgba(138, 180, 248, 0.92);
  font-size: 13px;
}
.repo-index-time--loading {
  color: rgba(138, 180, 248, 0.85) !important;
}
.feedback-snackbar__content {
  width: 100%;
}
.feedback-snackbar__icon {
  flex-shrink: 0;
  margin-top: 2px;
}
.feedback-snackbar__text {
  line-height: 1.45;
  text-align: left;
  white-space: normal;
  word-break: break-word;
}

.repo-dialog :deep(.v-overlay__content) {
  border-radius: 16px;
  overflow: visible;
}
.repo-dialog-card {
  display: flex;
  flex-direction: column;
  max-height: min(90vh, 760px);
  border-radius: 16px !important;
  overflow: hidden;
  background: var(--dg-surface-modal, #1e1e1e) !important;
}
.dg-dark-form-surface.repo-dialog-card {
  background: var(--dg-surface-modal, #1e1e1e) !important;
}
.repo-dialog-title,
.repo-dialog-title-divider,
.repo-dialog-footer-divider,
.repo-dialog-actions {
  flex-shrink: 0;
}
.repo-dialog-title {
  position: sticky;
  top: 0;
  z-index: 3;
  padding: 20px 24px 16px !important;
  font-size: 1.25rem !important;
  font-weight: 700 !important;
  letter-spacing: 0.01em;
  color: rgba(255, 255, 255, 0.95) !important;
  line-height: 1.3;
  background: var(--dg-surface-modal, #1e1e1e);
}
.repo-dialog-title-divider {
  position: sticky;
  top: 56px;
  z-index: 3;
  background: var(--dg-surface-modal, #1e1e1e);
}
.repo-dialog-title-divider,
.repo-dialog-footer-divider {
  border-color: rgba(255, 255, 255, 0.08) !important;
  opacity: 1;
}
.repo-dialog-footer-divider {
  border-color: rgba(255, 255, 255, 0.05) !important;
}
.repo-dialog-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
  padding: 16px 24px 12px;
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 255, 255, 0.2) transparent;
}
.repo-dialog-scroll::-webkit-scrollbar {
  width: 4px;
}
.repo-dialog-scroll::-webkit-scrollbar-track {
  background: transparent;
}
.repo-dialog-scroll::-webkit-scrollbar-button {
  display: none;
  height: 0;
  width: 0;
}
.repo-dialog-scroll::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.18);
  border-radius: 999px;
}
.repo-dialog-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.32);
}
.repo-dialog-form {
  max-width: 100%;
  box-sizing: border-box;
  contain: layout style;
}
.repo-dialog-form .repo-form-grid {
  margin-inline: 0 !important;
  width: 100%;
  max-width: 100%;
}
.repo-form-grid {
  margin-top: 0;
  --v-input-control-height: 44px;
}
.repo-form-grid > .v-col {
  padding-top: 8px;
  padding-bottom: 16px;
}
.repo-form-grid > .v-col.repo-form-desc-col {
  padding-bottom: 24px !important;
}
.repo-field-caption {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 400;
  color: var(--form-label, rgba(255, 255, 255, 0.6));
}
.repo-threshold-grid > .v-col {
  padding-bottom: 12px;
}
.repo-form-section-title {
  margin: 4px 0 0;
  padding-inline: 0;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.45);
}
.repo-form-section-divider {
  border-color: rgba(255, 255, 255, 0.06) !important;
  opacity: 1;
}
.repo-form-field--frontend :deep(.v-field) {
  border-color: rgba(129, 201, 149, 0.45);
  background: rgba(129, 201, 149, 0.06);
}
.repo-field-help {
  vertical-align: middle;
  opacity: 0.65;
  cursor: help;
}
.repo-advanced-panels {
  margin-inline: 0;
}
.repo-advanced-panels :deep(.v-expansion-panel) {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 12px !important;
}
.repo-advanced-panels :deep(.v-expansion-panel-title) {
  padding-inline: 16px !important;
}
.repo-advanced-panels :deep(.v-expansion-panel-text__wrapper) {
  padding: 8px 16px 16px !important;
}
.repo-advanced-panel-body :deep(.v-expansion-panel-text__wrapper) {
  padding-inline: 16px !important;
}
.repo-advanced-panels__title {
  min-height: 44px !important;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.78) !important;
}
.repo-form-grid--align {
  margin-inline: 0 !important;
}
.repo-form-grid--align > .v-col {
  padding-inline: 0;
}
.repo-advanced-block + .repo-advanced-block {
  margin-top: 24px;
  padding-top: 24px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}
.repo-dialog-toggles-hint {
  margin-top: 4px;
  padding-bottom: 4px;
}
.repo-dialog-toggles {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px 24px;
  padding: 4px 0 2px;
}
.repo-dialog-footer-fixed {
  flex-shrink: 0;
  padding: 8px 24px 4px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  background: var(--dg-surface-modal, #1e1e1e);
}
.repo-dialog-toggles-bar {
  background: rgba(255, 255, 255, 0.03);
  padding: 12px 24px 10px;
}
.repo-dialog-toggles-bar--separated {
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}
.repo-advanced-subtitle {
  margin: 0 0 8px;
  padding-inline: 0;
  font-size: 13px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.72);
}
.repo-coverage-combo {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 44px;
  padding: 6px 8px 6px 4px;
  border-radius: 6px;
  border: 1px solid var(--form-border-default, rgba(255, 255, 255, 0.1));
  background: var(--form-bg, rgba(255, 255, 255, 0.03));
  transition: border-color 0.2s ease;
}
.repo-coverage-combo:hover {
  border-color: var(--form-border-hover, rgba(255, 255, 255, 0.2));
}
.repo-coverage-combo__slider {
  flex: 1 1 auto;
  min-width: 0;
  padding-inline: 6px 2px;
}
.repo-coverage-combo__tag {
  flex: 0 0 104px;
  width: 104px;
  max-width: 104px;
}
.repo-coverage-combo:not(.repo-coverage-combo--v2) .repo-coverage-combo__tag :deep(.v-field) {
  margin-top: 0 !important;
  min-height: 36px !important;
  border: none !important;
  background: rgba(255, 255, 255, 0.05) !important;
  border-radius: 4px !important;
  box-shadow: none !important;
  overflow: visible;
}
.repo-coverage-combo__tag :deep(.v-field__outline) {
  display: none !important;
}
.repo-coverage-combo__tag :deep(.v-field__field) {
  align-items: center;
  min-height: 36px;
}
.repo-coverage-combo__tag :deep(.v-field__input) {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.25;
  color: rgba(255, 255, 255, 0.92);
  padding: 6px 4px 6px 8px !important;
  min-height: 24px;
  text-align: center;
}
.repo-coverage-combo__tag :deep(.v-field__suffix) {
  padding-inline-end: 8px !important;
  font-size: 13px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.75);
  opacity: 1;
}
.repo-threshold-block .repo-threshold-number :deep(.v-field) {
  margin-top: 0 !important;
  min-height: 48px !important;
  max-height: 48px !important;
  height: 48px !important;
}

.repo-threshold-block .repo-threshold-number :deep(.v-field__input) {
  min-height: 48px !important;
  max-height: 48px !important;
  padding-block: 0 !important;
}

.repo-threshold-block .repo-coverage-outlined {
  min-height: 48px !important;
  max-height: 48px !important;
  height: 48px !important;
}

.repo-threshold-block .repo-threshold-number :deep(.v-label.v-field-label),
.repo-threshold-block .repo-threshold-number :deep(.v-label.v-field-label--floating) {
  white-space: nowrap;
}
.repo-risk-group-title {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.88);
}
.repo-risk-path-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 20px;
  width: 100%;
}
.repo-risk-path-col {
  min-width: 0;
}
@media (max-width: 560px) {
  .repo-risk-path-grid {
    grid-template-columns: 1fr;
  }
}
.repo-glob-hint {
  margin: 12px 0 0;
  padding: 0;
  font-size: 12px;
  line-height: 1.5;
  color: rgba(255, 255, 255, 0.4);
}
.repo-risk-rules-block .repo-glob-hint,
.repo-risk-rules-block .dg-glob-hint {
  margin: 8px 0 0;
  text-align: left;
  color: rgba(255, 255, 255, 0.5);
}
.repo-advanced-block.repo-notify-block {
  margin-top: 0;
  padding-top: 0;
  border-top: none;
}
.repo-notify-section-title {
  margin: 0 0 8px;
  padding: 0;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
  color: rgba(255, 255, 255, 0.88);
}
.repo-notify-row {
  display: flex;
  align-items: stretch;
  gap: 12px;
  width: 100%;
  max-width: 100%;
}
.repo-notify-url-field {
  flex: 1 1 auto;
  min-width: 0;
  margin: 0;
}
.repo-notify-url-field {
  margin-top: 0;
}
.repo-notify-policy-field {
  margin-top: 16px;
  max-width: 50%;
}
.repo-advanced-panels--form-tail {
  margin-bottom: 24px;
}
.repo-override-switch :deep(.v-selection-control) {
  align-items: center;
  min-height: 40px;
}
.repo-override-switch :deep(.v-label) {
  font-size: 14px;
  color: rgba(255, 255, 255, 0.82);
  opacity: 1;
}
.repo-test-notify-btn {
  flex: 0 0 auto;
  min-height: 40px !important;
  height: 40px;
  padding-inline: 16px !important;
  border-color: rgba(255, 255, 255, 0.18) !important;
  background: transparent !important;
  color: rgba(255, 255, 255, 0.72) !important;
  font-weight: 500;
}
.repo-test-notify-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.06) !important;
  border-color: rgba(255, 255, 255, 0.28) !important;
  color: rgba(255, 255, 255, 0.88) !important;
}
.repo-test-notify-btn:disabled {
  opacity: 0.45;
}
.repo-dialog-toggles .repo-form-switch {
  flex: 1 1 180px;
  max-width: calc(33.33% - 14px);
  min-width: 160px;
  margin: 0;
}
@media (max-width: 720px) {
  .repo-dialog-toggles .repo-form-switch {
    max-width: calc(50% - 10px);
  }
}
.repo-coverage-slider :deep(.v-slider-track__background) {
  background-color: rgba(255, 255, 255, 0.16);
  opacity: 1;
}
.repo-coverage-slider :deep(.v-slider-track__fill) {
  background-color: var(--form-border-focus, #3b82f6) !important;
  opacity: 1;
}
.repo-coverage-slider :deep(.v-slider-thumb__surface) {
  background-color: var(--form-border-focus, #3b82f6) !important;
  border-color: #2563eb !important;
}
.repo-form-switch:not(.repo-form-switch--dock) :deep(.v-switch__track) {
  opacity: 0.85;
}
.repo-dialog-actions {
  position: sticky;
  bottom: 0;
  z-index: 3;
  padding: 16px 24px 20px !important;
  gap: 8px;
  background: var(--dg-surface-modal, #1e1e1e);
  box-shadow: 0 -8px 24px rgba(0, 0, 0, 0.25);
}
.repo-dialog-cancel {
  color: rgba(255, 255, 255, 0.65) !important;
  font-weight: 500;
}
.repo-dialog-cancel:hover {
  color: rgba(255, 255, 255, 0.88) !important;
  background: transparent !important;
}
.repo-dialog-submit {
  font-weight: 600;
}
.repo-dialog-form:not(.dg-md3-form) :deep(.v-field__input) {
  overflow: visible;
  text-overflow: clip;
  white-space: pre-wrap;
  min-height: 1.5em;
  padding-inline: 12px !important;
}
.repo-form-field--url :deep(textarea),
.repo-form-field--name :deep(textarea) {
  font-family: var(--diffgate-mono);
  font-size: 13px;
  line-height: 1.5;
  word-break: break-all;
  overflow-wrap: anywhere;
  min-height: 44px;
  max-height: 96px;
  padding-block: 12px;
}
.repo-form-field--name :deep(.v-label),
.repo-form-field--url :deep(.v-label) {
  font-family: 'Noto Sans SC', Roboto, 'Segoe UI', system-ui, sans-serif;
}
.repo-dialog-form:not(.dg-md3-form) :deep(.v-field__field) {
  align-items: flex-start;
}

.repo-form-page--v2 .repo-dialog-form.dg-md3-form .v-select.repo-form-field :deep(.v-field__field) {
  align-items: center !important;
}

.repo-form-page--v2 .repo-dialog-form.dg-md3-form .v-select.repo-form-field :deep(.v-field__input) {
  min-height: 48px !important;
  align-items: center !important;
  white-space: nowrap;
}
.repo-dialog-form.dg-dark-form .repo-form-grid > .v-col {
  padding-top: 12px;
}

.repo-form-page {
  max-width: 1000px;
  margin: 0 auto;
  padding: 0 32px 96px;
  min-height: calc(100vh - 64px);
  display: flex;
  flex-direction: column;
  gap: 24px;
  box-sizing: border-box;
}

.repo-form-page--v2 {
  background: #0f0f11;
  margin-inline: auto;
  box-shadow: none;
}

.repo-form-page--v2::-webkit-scrollbar {
  width: 6px;
}
.repo-form-page--v2::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.12);
  border-radius: 6px;
}

.repo-form-page__topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 0 16px;
  margin: 0 -32px;
  padding-inline: 32px;
  background: rgba(18, 18, 18, 0.92);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.repo-form-page__topbar-main {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-width: 0;
}

.repo-form-page__titles {
  min-width: 0;
}

.repo-form-page__back {
  margin-top: 2px;
  flex-shrink: 0;
  color: rgba(255, 255, 255, 0.72) !important;
}

.repo-form-page__title {
  font-size: 1.375rem;
  font-weight: 700;
  margin: 0;
  line-height: 1.35;
  letter-spacing: -0.02em;
}

.repo-form-page__subtitle {
  margin: 4px 0 0;
  font-size: 0.8125rem;
  color: rgba(255, 255, 255, 0.42);
  line-height: 1.45;
  max-width: 56ch;
}

.repo-form-page__top-save {
  flex-shrink: 0;
  margin-top: 2px;
}

.repo-form-page__body {
  display: flex;
  flex-direction: column;
  gap: 32px;
}

.repo-form-page__body > .dg-form-card + .dg-form-card {
  margin-top: 0;
}

.repo-form-section-card {
  padding: 28px 32px 32px !important;
  border: 1px solid #2a2a2d !important;
  border-radius: 12px !important;
  background: #161618 !important;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.28);
  overflow: visible !important;
}

.repo-form-page--v2 .repo-form-grid--strict > .v-col {
  padding-top: 16px;
}

.repo-form-page--v2 .repo-form-field--mono :deep(input),
.repo-form-page--v2 .repo-form-field--mono :deep(textarea),
.repo-form-page--v2 .repo-form-field--url :deep(textarea) {
  font-family: ui-monospace, 'Cascadia Code', Consolas, monospace;
  font-size: 13px;
}


.repo-form-section-card--advanced {
  padding-top: 12px !important;
}

.repo-form-section-card--advanced :deep(.repo-advanced-panels--form-tail) {
  margin-top: 0;
}

.repo-form-page__dock {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 25;
  padding: 14px 24px;
  background: #161618;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: 0 -12px 40px rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(10px);
}

.repo-form-page__dock-inner {
  max-width: 1000px;
  margin: 0 auto;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 12px 20px;
}

.repo-form-page__dock-switches {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px 24px;
  margin-right: auto;
}

.repo-form-page__dock-switches .repo-form-switch {
  flex: 0 0 auto;
}

.repo-form-page__dock-divider {
  align-self: stretch;
  min-height: 36px;
  opacity: 0.35;
}

.repo-form-page__dock-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

@media (max-width: 720px) {
  .repo-form-page__topbar {
    flex-direction: column;
    align-items: stretch;
  }
  .repo-form-page__top-save {
    align-self: flex-end;
  }
  .repo-form-page__dock-inner {
    flex-direction: column;
    align-items: stretch;
  }
  .repo-form-page__dock-divider {
    display: none;
  }
  .repo-form-page__dock-switches {
    margin-right: 0;
  }
  .repo-form-page__dock-actions {
    justify-content: flex-end;
  }
}
</style>

<!-- v-menu 挂到 body，菜单样式必须全局且铺在 .repo-row-action-menu 下 -->
<style>
.repo-row-action-menu {
  z-index: 2600 !important;
  background-color: #353b45 !important;
  border: none !important;
  outline: none !important;
  border-radius: 8px !important;
  box-shadow:
    0 14px 36px rgba(0, 0, 0, 0.52),
    0 4px 14px rgba(0, 0, 0, 0.32) !important;
  overflow: hidden;
  isolation: isolate;
  opacity: 1 !important;
}
.repo-row-action-menu .v-overlay__content {
  border: none !important;
  box-shadow: none !important;
}
.repo-row-action-menu .v-list,
.repo-row-action-menu .repo-action-menu {
  background-color: #353b45 !important;
  padding: 6px !important;
}
.repo-row-action-menu .repo-action-menu__item.v-list-item {
  min-height: 40px !important;
  padding: 8px 12px !important;
  margin: 2px 0;
  font-size: 14px;
  border-radius: 6px !important;
  transition: background-color 0.15s ease;
}
.repo-row-action-menu .repo-action-menu__item .v-list-item__prepend {
  width: 20px;
  min-width: 20px;
  margin-inline-end: 12px !important;
  display: flex;
  align-items: center;
  justify-content: center;
}
.repo-row-action-menu .repo-action-menu__item .v-list-item-title {
  font-size: 14px;
  font-weight: 500;
  letter-spacing: 0.01em;
  line-height: 1.35;
  color: rgba(255, 255, 255, 0.92);
}
.repo-row-action-menu .repo-action-menu__item .v-list-item__overlay {
  opacity: 0 !important;
}
.repo-row-action-menu .repo-action-menu__item:not(.v-list-item--disabled):hover {
  background: rgba(255, 255, 255, 0.1) !important;
}
.repo-row-action-menu .repo-action-menu__item--danger .v-list-item-title,
.repo-row-action-menu .repo-action-menu__item--danger .v-icon {
  color: #f28b82 !important;
}
.repo-row-action-menu .repo-action-menu__item--danger:not(.v-list-item--disabled):hover {
  background: rgba(242, 139, 130, 0.16) !important;
}
.repo-row-action-menu .repo-action-menu__separator {
  display: block;
  height: 1px;
  margin: 6px 16px 4px;
  border: none;
  background: rgba(255, 255, 255, 0.03);
  box-shadow: none;
  pointer-events: none;
}

.dg-md3-select-menu.repo-linked-repo-menu.v-overlay__content {
  z-index: 2800 !important;
}

.repo-linked-menu-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px 16px;
  text-align: center;
  color: rgba(255, 255, 255, 0.4);
  font-size: 13px;
  line-height: 1.45;
}

.repo-linked-menu-empty__icon {
  color: rgba(255, 255, 255, 0.35) !important;
  opacity: 1;
}

.repo-linked-menu-empty__hint {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.32);
  max-width: 220px;
}
</style>