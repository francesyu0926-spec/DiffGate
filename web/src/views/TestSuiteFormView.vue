<script setup lang="ts">
import { computed, onMounted, provide, ref, watch } from 'vue'
import { DG_FORM_FIELD_SPEC_KEY } from '@/form/formFieldLayout'
import { useRoute, useRouter } from 'vue-router'
import {
  createTestSuite,
  fetchRepositories,
  fetchTestSuites,
  fetchTestSuiteBranches,
  parseCloneUrl,
  previewTestSuiteSource,
  readApiError,
  updateTestSuite,
  type TestSuitePreviewResult,
  type RepositoryItem,
  type TestSuiteFramework,
  type TestSuiteGitAuthMethod,
  type TestSuiteItem,
  type TestSuitePayload,
  type TestSuiteSourceType,
} from '@/api/client'
import { suggestSlugFromName } from '@/utils/suggestSlug'
import Md3FilledTextField from '@/components/Md3FilledTextField.vue'
import Md3FilledTextarea from '@/components/Md3FilledTextarea.vue'
import OutlinedInput from '@/components/OutlinedInput.vue'
import OutlinedTextarea from '@/components/OutlinedTextarea.vue'
import OutlinedPasswordInput from '@/components/OutlinedPasswordInput.vue'
import OutlinedSelect, { type OutlinedSelectOption } from '@/components/OutlinedSelect.vue'

const router = useRouter()
const route = useRoute()

provide(DG_FORM_FIELD_SPEC_KEY, true)

const repositoriesAdminHref = computed(() => router.resolve({ name: 'repositories' }).href)

type GitCredentialMode = 'inherit' | 'token' | 'ssh'

const gitCredentialOptions: { title: string; value: GitCredentialMode }[] = [
  { title: '自动继承（推荐）', value: 'inherit' },
  { title: '独立 Access Token', value: 'token' },
  { title: 'SSH 私钥', value: 'ssh' },
]

/** 未选择凭证策略时保持下拉为空（不默认「自动继承」） */
const gitCredentialChosen = ref(false)

const gitCredentialMode = computed({
  get(): GitCredentialMode | null {
    if (!gitCredentialChosen.value) return null
    if (gitAuthPanel.value !== 0) return 'inherit'
    return gitAuthMethod.value === 'ssh' ? 'ssh' : 'token'
  },
  set(v: GitCredentialMode | null | string) {
    if (v === '' || v == null) {
      gitCredentialChosen.value = false
      gitAuthPanel.value = undefined
      gitAuthMethod.value = 'inherit'
      return
    }
    gitCredentialChosen.value = true
    if (v === 'inherit') {
      gitAuthPanel.value = undefined
      gitAuthMethod.value = 'inherit'
    } else {
      gitAuthPanel.value = 0
      gitAuthMethod.value = v as GitCredentialMode
    }
  },
})

const editingId = computed(() => {
  const id = route.params.id as string | undefined
  return route.name === 'test-suite-edit' && id ? id : null
})

const isCreatePage = computed(() => !editingId.value)

const pageTitle = computed(() => (editingId.value ? '编辑用例集' : '新建用例集'))
const pageSubtitle = computed(() =>
  editingId.value
    ? '修改用例来源、关联仓库与同步配置；保存后同步更新仓库侧双向绑定。'
    : '配置接口自动化用例来源并关联业务仓库，用于变更影响后的精准回归召回。',
)
const headerSaveLabel = computed(() => (editingId.value ? '保存用例集' : '创建用例集'))

const submitLoading = ref(false)
const pageLoading = ref(false)
const slugTouched = ref(false)
const slugSuggestion = computed(() => suggestSlugFromName(form.value.name))
const gitRepoPick = ref<'reuse' | 'custom'>('custom')
const repositoryIds = ref<string[]>([])
const repoOptions = ref<RepositoryItem[]>([])
const reposLoading = ref(false)
const gitAuthPanel = ref<number | undefined>(undefined)
const gitAuthMethod = ref<TestSuiteGitAuthMethod>('inherit')
const gitAccessToken = ref('')
const gitSshKey = ref('')
const tokenConfigured = ref(false)
const sshConfigured = ref(false)
const probeLoading = ref(false)
const probePreview = ref<TestSuitePreviewResult | null>(null)
const probeOk = ref<boolean | null>(null)
const cloneUrlHint = ref<string | null>(null)
let cloneUrlParseTimer: ReturnType<typeof setTimeout> | null = null
let gitBranchesFetchTimer: ReturnType<typeof setTimeout> | null = null

const gitBranchOptions = ref<string[]>([])
const gitBranchDefault = ref('main')
const gitBranchesLoading = ref(false)
const gitBranchesHint = ref<string | null>(null)

const snackbar = ref({ show: false, text: '', color: 'success' as 'success' | 'error' })

const nameFieldError = ref('')
const slugFieldError = ref('')

const SLUG_PATTERN = /^[a-z0-9.-]+$/

function validateNameOnBlur() {
  nameFieldError.value = form.value.name.trim() ? '' : '请填写用例集名称'
}

function validateSlugOnBlur() {
  const raw = form.value.slug.trim()
  if (!raw) {
    slugFieldError.value = '请填写唯一标识 (Slug)'
    return
  }
  if (!SLUG_PATTERN.test(raw)) {
    slugFieldError.value = '仅支持小写字母、数字、点与连字符'
    return
  }
  slugFieldError.value = ''
}

const form = ref<TestSuitePayload>({
  slug: '',
  name: '',
  description: '',
  external_ref: '',
  enabled: true,
  source_type: 'git',
  git_url: '',
  git_branch: '',
  case_path: '',
  framework: null,
  git_reuse_repository_id: null,
  skip_ssl_verify: false,
  trigger_webhook_url: '',
})

const sourceSegmentOptions: { value: TestSuiteSourceType; title: string }[] = [
  { value: 'git', title: 'Git 测试仓库 (推荐)' },
  { value: 'webhook', title: '外部 CI / Webhook' },
  { value: 'manual', title: '仅手工登记' },
]

const frameworkTitleMap = computed(() => {
  const map = new Map<TestSuiteFramework, string>()
  for (const opt of frameworkOptions) map.set(opt.value, opt.title)
  return map
})

const probeSuccessHeadline = computed(() => {
  const r = probePreview.value
  if (!r?.success) return ''
  const s = r.summary
  const latency = r.latency_ms ? ` · ${r.latency_ms}ms` : ''
  return `连通性正常 · 共扫描 ${s.matched_files} 个文件，解析出 ${s.total_cases} 条有效用例（覆盖 ${s.covered_api_count} 个 API 接口）${latency}`
})

const probeZeroCasesWarning = computed(() => {
  const r = probePreview.value
  if (!r?.success || r.summary.total_cases > 0) return ''
  const path = (form.value.case_path || '').trim() || '（未填写）'
  const fw =
    frameworkTitleMap.value.get(form.value.framework || 'yaml') ||
      form.value.framework ||
      '（未选择）'
  return `连接成功，但未在 [${path}] 目录下发现 [${fw}] 格式用例，请检查扫描目录或测试框架类型是否匹配。`
})

const PROBE_ERROR_CODE_LABELS: Record<string, string> = {
  preview_timeout: '连接超时（超过 5 秒）',
  preview_source_not_git: '当前来源不支持 Git 预览',
  auth_failed: '认证失败，请检查 Access Token 或 SSH 私钥',
  branch_not_found: '分支不存在或无法访问',
  scan_path_missing: '用例扫描目录在仓库中不存在',
}

const probeFailureMessage = computed(() => {
  const r = probePreview.value
  if (!r || r.success) return ''

  const detail = (r.error_detail || '').trim()
  const msg = (r.message || '').trim()
  const generic = /^(探测失败|连通性探测失败|失败)$/i

  if (msg && !generic.test(msg)) return msg

  const hints: string[] = []
  if (!r.repo_reachable) hints.push('无法连接仓库（请检查 Clone URL、网络或 SSL 设置）')
  else if (r.repo_reachable && !r.branch_exists)
    hints.push('分支不存在或无法访问（请核对分支名或权限）')
  else if (r.repo_reachable && r.branch_exists && !r.scan_path_exists)
    hints.push('用例扫描目录在仓库中不存在')

  if (detail) {
    const codeHint = PROBE_ERROR_CODE_LABELS[detail]
    if (codeHint) hints.push(codeHint)
    else if (!hints.length) hints.push(detail)
  }

  if (hints.length) return hints.join('；')
  return msg || '连通性探测失败，请检查地址、凭据与分支'
})

/** 新建 + Git 来源：需先探测成功方可创建 */
const gitCreateBlocked = computed(
  () => !editingId.value && form.value.source_type === 'git' && probeOk.value !== true,
)

const frameworkOptions: { value: TestSuiteFramework; title: string }[] = [
  { value: 'yaml', title: 'YAML 标准声明' },
  { value: 'pytest', title: 'Pytest (Python)' },
  { value: 'httprunner', title: 'HttpRunner' },
  { value: 'apifox', title: 'Apifox / Postman JSON' },
  { value: 'junit', title: 'JUnit / TestNG (Java)' },
  { value: 'gotest', title: 'Go Test (Go)' },
]

const frameworkSelectOptions = computed((): OutlinedSelectOption[] =>
  frameworkOptions.map((o) => ({ value: o.value, label: o.title })),
)

const linkedRepoSelectOptions = computed((): OutlinedSelectOption[] =>
  repoOptions.value.map((r) => ({ value: r.id, label: r.full_name })),
)

const reposCatalogEmpty = computed(
  () => !reposLoading.value && linkedRepoSelectOptions.value.length === 0,
)

/** 新建页：凭证子表单单独成卡（SSL/探测已并入 Git 内嵌区） */
const showCreateGitAuthCard = computed(
  () =>
    isCreatePage.value &&
    gitRepoPick.value === 'custom' &&
    gitCredentialChosen.value &&
    gitCredentialMode.value != null &&
    gitCredentialMode.value !== 'inherit',
)

const gitCredentialSelectOptions = computed((): OutlinedSelectOption[] =>
  gitCredentialOptions.map((o) => ({ value: o.value, label: o.title })),
)

const gitBranchSelectOptions = computed((): OutlinedSelectOption[] =>
  gitBranchOptions.value.map((b) => ({
    value: b,
    label: b,
    badge: b === gitBranchDefault.value ? '默认' : undefined,
  })),
)

const canFetchGitBranches = computed(() => {
  if (form.value.source_type !== 'git') return false
  if (gitRepoPick.value === 'reuse') {
    return Boolean(String(form.value.git_reuse_repository_id || '').trim())
  }
  return Boolean(String(form.value.git_url || '').trim())
})

const triggerWebhookUrlFilled = computed(() =>
  Boolean(String(form.value.trigger_webhook_url || '').trim()),
)

const frameworkFieldModel = computed({
  get: () => form.value.framework ?? '',
  set: (v: string | string[]) => {
    const s = Array.isArray(v) ? (v[0] ?? '') : v
    form.value.framework = (s || null) as TestSuiteFramework | null
  },
})

const reuseRepoFieldModel = computed({
  get: () => form.value.git_reuse_repository_id ?? '',
  set: (v: string | string[]) => {
    const s = Array.isArray(v) ? (v[0] ?? '') : v
    form.value.git_reuse_repository_id = s || null
  },
})

const gitCredentialSelectModel = computed({
  get: () => gitCredentialMode.value ?? '',
  set: (v: string | string[]) => {
    const s = Array.isArray(v) ? (v[0] ?? '') : v
    gitCredentialMode.value = s === '' ? null : (s as GitCredentialMode)
  },
})

const gitTokenHelper = computed(() => {
  const lines: string[] = []
  if (tokenConfigured.value) lines.push('留空则保留已保存的令牌')
  lines.push('建议使用仅含只读权限的令牌，保存后系统将加密存储。')
  return lines.join(' ')
})

const gitSshHelper = computed(() =>
  sshConfigured.value
    ? '留空则保留已保存的私钥。支持 .pem、id_rsa 等文本私钥，避免漏掉首尾标记行。'
    : '支持读取 .pem、id_rsa 等文本私钥，避免漏掉首尾标记行。',
)

function notify(text: string, color: 'success' | 'error' = 'success') {
  snackbar.value = { show: true, text, color }
}

function goBack() {
  void router.push({ name: 'test-suites' })
}

function defaultForm(): TestSuitePayload {
  return {
    slug: '',
    name: '',
    description: '',
    external_ref: '',
    enabled: true,
    source_type: 'git',
    git_url: '',
    git_branch: '',
    case_path: '',
    framework: null,
    git_reuse_repository_id: null,
    git_auth_method: 'inherit',
    skip_ssl_verify: false,
    trigger_webhook_url: '',
  }
}

function resetGitAuth() {
  gitCredentialChosen.value = false
  gitAuthPanel.value = undefined
  gitAuthMethod.value = 'inherit'
  gitAccessToken.value = ''
  gitSshKey.value = ''
  tokenConfigured.value = false
  sshConfigured.value = false
  probePreview.value = null
  probeOk.value = null
}

function openCreate() {
  slugTouched.value = false
  form.value = defaultForm()
  repositoryIds.value = []
  gitRepoPick.value = 'custom'
  resetGitAuth()
}

function openEdit(row: TestSuiteItem) {
  slugTouched.value = true
  form.value = {
    slug: row.slug,
    name: row.name,
    description: row.description || '',
    external_ref: row.external_ref || '',
    enabled: row.enabled,
    source_type: row.source_type || 'manual',
    git_url: row.git_url || '',
    git_branch: (row.git_branch || '').trim(),
    case_path: (row.case_path || '').trim(),
    framework: row.framework || null,
    git_reuse_repository_id: row.git_reuse_repository_id,
    skip_ssl_verify: Boolean(row.skip_ssl_verify),
    trigger_webhook_url: row.trigger_webhook_url || '',
  }
  repositoryIds.value = [...(row.linked_repository_ids || [])]
  gitRepoPick.value = row.git_reuse_repository_id ? 'reuse' : 'custom'
  const method = row.git_auth_method || 'inherit'
  gitAuthMethod.value =
    method === 'ssh' ? 'ssh' : method === 'token' || row.token_configured ? 'token' : 'token'
  tokenConfigured.value = Boolean(row.token_configured)
  sshConfigured.value = Boolean(row.ssh_configured)
  gitAccessToken.value = ''
  gitSshKey.value = ''
  probePreview.value = null
  gitAuthPanel.value =
    method === 'token' || method === 'ssh' || row.token_configured || row.ssh_configured ? 0 : undefined
  if (gitAuthPanel.value === 0 && method === 'ssh') {
    gitAuthMethod.value = 'ssh'
  }
  gitCredentialChosen.value = (row.source_type || 'manual') === 'git'
}

async function loadRepoOptions() {
  reposLoading.value = true
  try {
    repoOptions.value = await fetchRepositories()
  } catch {
    repoOptions.value = []
  } finally {
    reposLoading.value = false
  }
}

async function loadEditingSuite() {
  if (!editingId.value) {
    openCreate()
    return
  }
  pageLoading.value = true
  try {
    const rows = await fetchTestSuites()
    const row = rows.find((r) => r.id === editingId.value)
    if (!row) {
      notify('用例集不存在或无权访问', 'error')
      goBack()
      return
    }
    openEdit(row)
  } catch (err) {
    notify(readApiError(err, '加载用例集失败'), 'error')
    goBack()
  } finally {
    pageLoading.value = false
  }
}

async function submit() {
  const slug = form.value.slug.trim().toLowerCase()
  const name = form.value.name.trim()
  if (!slug || !name) {
    notify('请填写标识与名称', 'error')
    return
  }
  submitLoading.value = true
  try {
    const source = form.value.source_type || 'manual'
    const payload: TestSuitePayload = {
      slug,
      name,
      description: (form.value.description || '').trim() || null,
      external_ref: (form.value.external_ref || '').trim() || null,
      enabled: form.value.enabled ?? true,
      source_type: source,
      repository_ids: [...repositoryIds.value],
    }
    if (source === 'git') {
      payload.git_branch = (form.value.git_branch || '').trim() || null
      payload.case_path = (form.value.case_path || '').trim() || null
      payload.framework = form.value.framework || null
      payload.skip_ssl_verify = Boolean(form.value.skip_ssl_verify)
      if (gitRepoPick.value === 'reuse') {
        payload.git_reuse_repository_id = form.value.git_reuse_repository_id || null
        payload.git_url = null
        payload.git_auth_method = 'inherit'
      } else {
        payload.git_reuse_repository_id = null
        payload.git_url = (form.value.git_url || '').trim() || null
        const useCustomAuth = gitAuthPanel.value === 0
        payload.git_auth_method = useCustomAuth ? gitAuthMethod.value : 'inherit'
        if (useCustomAuth && gitAuthMethod.value === 'token' && gitAccessToken.value.trim()) {
          payload.access_token = gitAccessToken.value.trim()
        }
        if (useCustomAuth && gitAuthMethod.value === 'ssh' && gitSshKey.value.trim()) {
          payload.ssh_private_key = gitSshKey.value.trim()
        }
      }
    } else if (source === 'webhook') {
      payload.trigger_webhook_url = (form.value.trigger_webhook_url || '').trim() || null
      payload.external_ref = (form.value.external_ref || '').trim() || null
    }
    if (editingId.value) {
      await updateTestSuite(editingId.value, payload)
      notify('已更新')
    } else {
      await createTestSuite(payload)
      notify('已创建')
    }
    goBack()
  } catch (err) {
    notify(readApiError(err, '保存失败'), 'error')
  } finally {
    submitLoading.value = false
  }
}

function onSlugInput() {
  slugTouched.value = true
}

function applySlugSuggestion() {
  const next = slugSuggestion.value
  if (!next) return
  form.value.slug = next
  slugFieldError.value = ''
}

function toggleSlugAutoLock() {
  if (!slugTouched.value) {
    if (slugSuggestion.value && form.value.slug !== slugSuggestion.value) {
      applySlugSuggestion()
      return
    }
    slugTouched.value = true
    return
  }
  slugTouched.value = false
  applySlugSuggestion()
}

watch(
  () => form.value.name,
  (name) => {
    if (slugTouched.value) return
    const suggested = suggestSlugFromName(name)
    if (suggested) form.value.slug = suggested
  },
)

watch(gitRepoPick, (mode) => {
  if (mode === 'reuse') {
    form.value.git_url = ''
    gitAuthPanel.value = undefined
    cloneUrlHint.value = null
    if (form.value.git_reuse_repository_id) scheduleFetchGitBranches()
  } else {
    form.value.git_reuse_repository_id = null
  }
})

watch(
  () => form.value.git_reuse_repository_id,
  (id) => {
    if (gitRepoPick.value === 'reuse' && id) scheduleFetchGitBranches()
  },
)

watch([gitCredentialMode, () => form.value.skip_ssl_verify], () => {
  if (form.value.source_type !== 'git') return
  scheduleFetchGitBranches()
})

watch(
  () => form.value.git_url,
  (url) => {
    cloneUrlHint.value = null
    if (cloneUrlParseTimer) clearTimeout(cloneUrlParseTimer)
    const trimmed = (url || '').trim()
    if (!trimmed || gitRepoPick.value !== 'custom') return
    cloneUrlParseTimer = setTimeout(() => {
      void (async () => {
        try {
          const meta = await parseCloneUrl(trimmed)
          if (meta.ok && meta.message) {
            cloneUrlHint.value = meta.message
            if (meta.suggested_auth === 'ssh' && gitAuthPanel.value === undefined) {
              gitAuthPanel.value = 0
              gitAuthMethod.value = 'ssh'
            }
          } else if (meta.message) {
            cloneUrlHint.value = meta.message
          }
        } catch {
          cloneUrlHint.value = null
        }
      })()
    }, 400)
  },
)

function buildBranchesRequest() {
  const useCustomAuth = gitAuthPanel.value === 0
  return {
    git_url: gitRepoPick.value === 'custom' ? (form.value.git_url || '').trim() || null : null,
    git_reuse_repository_id:
      gitRepoPick.value === 'reuse' ? form.value.git_reuse_repository_id || null : null,
    git_auth_method: (useCustomAuth ? gitAuthMethod.value : 'inherit') as TestSuiteGitAuthMethod,
    access_token:
      useCustomAuth && gitAuthMethod.value === 'token' ? gitAccessToken.value.trim() || null : null,
    ssh_private_key:
      useCustomAuth && gitAuthMethod.value === 'ssh' ? gitSshKey.value.trim() || null : null,
    skip_ssl_verify: Boolean(form.value.skip_ssl_verify),
    test_suite_id: editingId.value,
  }
}

function scheduleFetchGitBranches() {
  if (gitBranchesFetchTimer) clearTimeout(gitBranchesFetchTimer)
  gitBranchesFetchTimer = setTimeout(() => {
    void fetchGitBranches(false)
  }, 320)
}

const webhookPingLoading = ref(false)

async function pasteWebhookUrl() {
  try {
    const text = (await navigator.clipboard.readText()).trim()
    if (!text) return
    form.value.trigger_webhook_url = text
  } catch {
    notify('无法读取剪贴板，请手动粘贴', 'error')
  }
}

function clearWebhookUrl() {
  form.value.trigger_webhook_url = ''
}

async function sendWebhookPing() {
  const url = (form.value.trigger_webhook_url || '').trim()
  if (!url) {
    notify('请先填写 Webhook URL', 'error')
    return
  }
  webhookPingLoading.value = true
  try {
    await fetch(url, {
      method: 'POST',
      mode: 'no-cors',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ping: true,
        job_id: 'diffgate-ping',
        api_list: [],
      }),
    })
    notify('已发送测试 Ping（浏览器无法读取跨域响应，请到 CI 侧确认是否收到）', 'success')
  } catch (err) {
    notify(readApiError(err, '发送失败'), 'error')
  } finally {
    webhookPingLoading.value = false
  }
}

async function pasteGitUrl() {
  try {
    const text = (await navigator.clipboard.readText()).trim()
    if (!text) return
    form.value.git_url = text
    onGitUrlBlur()
  } catch {
    notify('无法读取剪贴板，请手动粘贴', 'error')
  }
}

const FRAMEWORK_CHIP: Record<string, string> = {
  yaml: 'YAML',
  pytest: 'Py',
  httprunner: 'HR',
  apifox: 'Fx',
  junit: 'Jv',
  gotest: 'Go',
}

function frameworkChip(id: string) {
  return FRAMEWORK_CHIP[id] || id.slice(0, 2).toUpperCase()
}

function onGitUrlBlur() {
  if (gitRepoPick.value !== 'custom') return
  if (!(form.value.git_url || '').trim()) return
  scheduleFetchGitBranches()
}

async function fetchGitBranches(manual = false) {
  if (form.value.source_type !== 'git') return
  const payload = buildBranchesRequest()
  const hasSource =
    gitRepoPick.value === 'reuse'
      ? Boolean(payload.git_reuse_repository_id)
      : Boolean(payload.git_url)
  if (!hasSource) {
    if (manual) notify('请先填写仓库地址或选择复用业务仓库', 'error')
    return
  }
  gitBranchesLoading.value = true
  if (manual) gitBranchesHint.value = null
  try {
    const result = await fetchTestSuiteBranches(payload)
    if (result.ok && result.items.length) {
      gitBranchOptions.value = result.items
      gitBranchDefault.value = result.default_branch || 'main'
      gitBranchesHint.value = result.message?.trim() || null
    } else {
      gitBranchOptions.value = []
      gitBranchesHint.value = result.message?.trim() || '未能拉取分支列表，可直接输入分支名'
      if (manual && result.message) notify(result.message, 'error')
    }
  } catch (err) {
    const msg = readApiError(err, '分支列表拉取失败')
    gitBranchesHint.value = msg
    if (manual) notify(msg, 'error')
  } finally {
    gitBranchesLoading.value = false
  }
}

function buildPreviewRequest() {
  const useCustomAuth = gitAuthPanel.value === 0
  const credentialMode: 'auto' | 'token' | 'ssh' = useCustomAuth
    ? gitAuthMethod.value === 'ssh'
      ? 'ssh'
      : 'token'
    : 'auto'
  return {
    source_type: form.value.source_type || 'git',
    clone_url: gitRepoPick.value === 'custom' ? (form.value.git_url || '').trim() || null : null,
    linked_repo_id:
      gitRepoPick.value === 'reuse' ? form.value.git_reuse_repository_id || null : null,
    credential_mode: credentialMode,
    access_token:
      useCustomAuth && gitAuthMethod.value === 'token' ? gitAccessToken.value.trim() || null : null,
    ssh_private_key:
      useCustomAuth && gitAuthMethod.value === 'ssh' ? gitSshKey.value.trim() || null : null,
    verify_ssl: !form.value.skip_ssl_verify,
    branch: (form.value.git_branch || '').trim() || null,
    scan_path: (form.value.case_path || '').trim() || null,
    framework: form.value.framework || null,
    test_suite_id: editingId.value,
  }
}

function clearProbePreview() {
  probePreview.value = null
  probeOk.value = null
}

async function runConnectivityProbe() {
  probeLoading.value = true
  clearProbePreview()
  try {
    const result = await previewTestSuiteSource(buildPreviewRequest())
    probePreview.value = result
    probeOk.value = result.success
    if (result.success && result.summary.total_cases > 0) {
      notify('连通性与用例扫描完成', 'success')
    }
  } catch (err) {
    const msg = readApiError(err, '连通性探测失败')
    probePreview.value = {
      success: false,
      latency_ms: 0,
      repo_reachable: false,
      branch_exists: false,
      scan_path_exists: false,
      summary: { matched_files: 0, total_cases: 0, covered_api_count: 0 },
      sample_cases: [],
      warnings: [],
      error_detail: msg,
      message: msg,
    }
    probeOk.value = false
  } finally {
    probeLoading.value = false
  }
}

watch(
  () => [
    form.value.source_type,
    form.value.git_url,
    form.value.git_branch,
    form.value.case_path,
    form.value.framework,
    gitRepoPick.value,
    form.value.git_reuse_repository_id,
  ],
  () => {
    if (form.value.source_type === 'git') clearProbePreview()
  },
)

onMounted(() => {
  void loadRepoOptions()
  void loadEditingSuite()
})
</script>

<template>
  <div
    class="ts-suite-form-page repo-form-page ts-suite-form-page--pure"
    :class="isCreatePage ? 'ts-suite-form-page--create' : 'dg-outlined-form-page'"
  >
    <header class="repo-form-page__topbar">
      <div class="repo-form-page__topbar-main">
        <button type="button" class="ts-page-back-btn" @click="goBack">
          ← 返回
        </button>
        <div class="repo-form-page__titles">
          <h1 class="repo-form-page__title">{{ pageTitle }}</h1>
          <p class="repo-form-page__subtitle">{{ pageSubtitle }}</p>
        </div>
      </div>
    </header>

    <v-progress-linear v-if="pageLoading" indeterminate color="primary" class="mb-2" />

    <form
      class="repo-form-page__body ts-suite-form"
      autocomplete="off"
      @submit.prevent="submit"
    >
      <section class="dg-form-card ts-suite-card ts-suite-card--basic">
        <h2 class="dg-form-card__title">
          <svg
            v-if="isCreatePage"
            class="dg-form-card__title-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.75"
            aria-hidden="true"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
            />
          </svg>
          基础信息
        </h2>
        <div v-if="isCreatePage" class="dg-form-grid-2 dg-form-grid-2--pair ts-basic-md3-pair">
          <div class="dg-form-item form-group md-field-item">
            <Md3FilledTextField
              id="ts-form-name"
              v-model="form.name"
              :maxlength="32"
              helper-text="建议 32 字以内"
              :counter="`${form.name.length} / 32`"
              :error="nameFieldError"
              @blur="validateNameOnBlur"
            >
              <template #label>
                用例集名称 <span class="dg-form-required required-star" aria-hidden="true">*</span>
              </template>
            </Md3FilledTextField>
          </div>
          <div class="dg-form-item form-group md-field-item">
            <Md3FilledTextField
              id="ts-form-slug"
              v-model="form.slug"
              mono
              placeholder="例如：order-service-cases"
              helper-text="仅支持小写字母、数字、点与连字符，创建后作为唯一索引键"
              :error="slugFieldError"
              @update:model-value="onSlugInput"
              @blur="validateSlugOnBlur"
            >
              <template #label>
                唯一标识 (Slug) <span class="dg-form-required required-star" aria-hidden="true">*</span>
              </template>
              <template #append>
                <button
                  type="button"
                  class="ts-slug-lock-btn"
                  :class="{ 'ts-slug-lock-btn--locked': slugTouched }"
                  :title="
                    slugTouched
                      ? '已锁定：点击恢复根据名称自动填充'
                      : slugSuggestion && form.slug !== slugSuggestion
                        ? '填入建议 Slug'
                        : '锁定当前 Slug，不再随名称变化'
                  "
                  :aria-label="slugTouched ? '恢复自动填充 Slug' : '锁定 Slug'"
                  @click.stop="toggleSlugAutoLock"
                >
                  <svg v-if="!slugTouched" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path
                      d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                      stroke="currentColor"
                      stroke-width="1.75"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    />
                  </svg>
                  <svg v-else viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path
                      d="M16 11V7a4 4 0 00-8 0v4M6 11h12v9H6v-9z"
                      stroke="currentColor"
                      stroke-width="1.75"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    />
                  </svg>
                </button>
              </template>
            </Md3FilledTextField>
          </div>
        </div>
        <div v-else class="dg-form-grid-2 dg-form-grid-2--pair">
          <div
            class="dg-form-item form-group md-field-item"
            :class="{ 'ts-field-wrap--error': nameFieldError }"
          >
            <OutlinedInput
              id="ts-form-name"
              v-model="form.name"
              label-above
              maxlength="32"
              placeholder="请填写"
              helper-text="建议 32 字以内"
              @blur="validateNameOnBlur"
            >
              <template #label>
                用例集名称 <span class="dg-form-required required-star" aria-hidden="true">*</span>
              </template>
            </OutlinedInput>
            <p v-if="nameFieldError" class="ts-field-error" role="alert">{{ nameFieldError }}</p>
          </div>
          <div
            class="dg-form-item form-group md-field-item"
            :class="{ 'ts-field-wrap--error': slugFieldError }"
          >
            <OutlinedInput
              id="ts-form-slug"
              v-model="form.slug"
              label-above
              mono
              placeholder="例如 order-service-cases（小写字母、数字、点、连字符）"
              @update:model-value="onSlugInput"
              @blur="validateSlugOnBlur"
            >
              <template #label>
                唯一标识 (Slug) <span class="dg-form-required required-star" aria-hidden="true">*</span>
              </template>
            </OutlinedInput>
            <p v-if="slugFieldError" class="ts-field-error" role="alert">{{ slugFieldError }}</p>
          </div>
        </div>
        <div
          class="dg-form-item dg-form-item--full form-group md-field-item ts-suite-bind-repos-block"
          :class="{ 'ts-suite-bind-repos-block--md3-filled': isCreatePage }"
        >
          <OutlinedSelect
            id="ts-form-repos"
            v-model="repositoryIds"
            :label-above="!isCreatePage"
            :options="linkedRepoSelectOptions"
            multiple
            searchable
            :menu-checkboxes="isCreatePage"
            :tag-leading-icon="isCreatePage ? 'repo' : ''"
            :placeholder="isCreatePage ? '' : '选择要关联的业务仓库'"
            :suppress-menu-when-empty="isCreatePage"
            :menu-surface-class="isCreatePage ? 'md-field-select-menu--md3-create' : ''"
            :disabled="reposLoading"
          >
            <template v-if="isCreatePage && reposCatalogEmpty" #empty-trigger-action>
              <a
                :href="repositoriesAdminHref"
                class="ts-repos-empty-shortcut"
                target="_blank"
                rel="noopener noreferrer"
                @click.stop
              >
                前往接入仓库 ↗
              </a>
            </template>
            <template #label>
              关联业务仓库<span class="md-field-label-sub">（可选，支持多选）</span>
            </template>
            <template #empty>
              <div class="ts-linked-menu-empty ts-linked-menu-empty--compact">
                <svg class="ts-linked-menu-empty__icon" width="26" height="26" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path
                    d="M3 7a2 2 0 012-2h5l2 2h9a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"
                    stroke="currentColor"
                    stroke-width="1.75"
                    stroke-linejoin="round"
                  />
                </svg>
                <p class="ts-linked-menu-empty__title">暂无已接入的业务仓库</p>
                <p class="ts-linked-menu-empty__hint">
                  可先点右下角「创建」保存用例集，稍后再绑定业务仓库。
                </p>
                <a
                  :href="repositoriesAdminHref"
                  class="ts-linked-menu-empty__link"
                  target="_blank"
                  rel="noopener noreferrer"
                  @click.stop
                >前往仓库管理 ↗</a>
              </div>
            </template>
            <template #helper>
              <span class="ts-bind-repos-hint">
                保存后自动写入对应业务仓库的
                <span class="ts-link-repos-mono">test_suite_id</span>
                ，建立双向追溯绑定
              </span>
            </template>
          </OutlinedSelect>
        </div>
        <div v-if="isCreatePage" class="dg-form-item dg-form-item--full form-group md-field-item">
          <Md3FilledTextarea
            id="ts-form-desc"
            :model-value="form.description ?? ''"
            :maxlength="200"
            placeholder="补充说明该用例集覆盖的业务模块或执行注意事项…"
            @update:model-value="(v) => (form.description = v)"
          >
            <template #label>
              描述说明<span class="md-field-label-sub">（可选）</span>
            </template>
          </Md3FilledTextarea>
        </div>
        <div v-else class="dg-form-item dg-form-item--full form-group md-field-item">
          <OutlinedTextarea
            id="ts-form-desc"
            v-model="form.description"
            label-above
            placeholder="补充说明该用例集覆盖的业务模块或执行注意事项…"
            :rows="3"
          >
            <template #label>
              描述说明<span class="md-field-label-sub">（可选）</span>
            </template>
          </OutlinedTextarea>
        </div>
        <div v-if="isCreatePage" class="ts-basic-settings">
          <button
            type="button"
            class="ts-enable-status-bar"
            :aria-pressed="form.enabled"
            @click="form.enabled = !form.enabled"
          >
            <span class="ts-enable-status-bar__copy">
              <span class="ts-enable-status-bar__title-row">
                <span class="ts-enable-status-bar__title">立即启用该用例集</span>
                <span
                  class="ts-enable-status-pill"
                  :class="{ 'ts-enable-status-pill--on': form.enabled }"
                >
                  <span class="ts-enable-status-pill__dot" aria-hidden="true" />
                  <span class="ts-enable-status-pill__text">
                    {{ form.enabled ? '创建后立即生效' : '暂存为草稿' }}
                  </span>
                </span>
              </span>
              <span class="ts-enable-status-bar__hint">启用后在精准回归与仓库配置中可见</span>
            </span>
            <span
              role="switch"
              class="ts-m3-switch ts-m3-switch--create"
              :class="{ 'ts-m3-switch--on': form.enabled }"
              :aria-checked="form.enabled"
              tabindex="-1"
            >
              <span class="ts-m3-switch__thumb" aria-hidden="true">
                <span v-if="form.enabled" class="ts-m3-switch__check">✓</span>
              </span>
            </span>
          </button>
        </div>
        <div v-else class="ts-suite-enable-row ts-suite-enable-row--after-bind">
          <button
            type="button"
            role="switch"
            class="ts-m3-switch"
            :class="{ 'ts-m3-switch--on': form.enabled }"
            :aria-checked="form.enabled"
            @click="form.enabled = !form.enabled"
          >
            <span class="ts-m3-switch__thumb" aria-hidden="true" />
          </button>
          <span class="ts-enable-label">
            <span class="ts-enable-label__main">立即启用该用例集</span>
            <span class="ts-enable-label__sub">（启用后在精准回归与仓库配置中可见）</span>
          </span>
        </div>
      </section>

      <section class="dg-form-card ts-suite-card ts-suite-card--source">
        <h2 class="dg-form-card__title">
          <svg
            v-if="isCreatePage"
            class="dg-form-card__title-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.75"
            aria-hidden="true"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4"
            />
          </svg>
          用例来源与同步方式
        </h2>
        <div class="ts-source-block">
          <div class="ts-source-track" role="tablist" aria-label="用例来源">
            <div class="ts-source-segment">
              <button
                v-for="opt in sourceSegmentOptions"
                :key="opt.value"
                type="button"
                role="tab"
                class="ts-source-segment__btn"
                :class="{ 'ts-source-segment__btn--active': form.source_type === opt.value }"
                :aria-selected="form.source_type === opt.value"
                @click="form.source_type = opt.value"
              >
                {{ opt.title }}
              </button>
            </div>
          </div>
        </div>

        <template v-if="form.source_type === 'git'">
          <div
            class="ts-source-config-stack ts-git-config-stack"
            :class="{ 'ts-source-inset-panel': isCreatePage }"
          >
            <template v-if="isCreatePage">
              <p class="ts-git-origin-field__label ts-git-origin-field__label--inset">代码库位置</p>
              <div class="ts-git-pick-cards" role="radiogroup" aria-label="代码库位置">
                <button
                  type="button"
                  class="ts-git-pick-card"
                  :class="{ 'ts-git-pick-card--active': gitRepoPick === 'custom' }"
                  role="radio"
                  :aria-checked="gitRepoPick === 'custom'"
                  @click="gitRepoPick = 'custom'"
                >
                  <span class="ts-git-pick-card__dot" aria-hidden="true" />
                  <span class="ts-git-pick-card__label">独立仓库</span>
                </button>
                <button
                  type="button"
                  class="ts-git-pick-card"
                  :class="{ 'ts-git-pick-card--active': gitRepoPick === 'reuse' }"
                  role="radio"
                  :aria-checked="gitRepoPick === 'reuse'"
                  @click="gitRepoPick = 'reuse'"
                >
                  <span class="ts-git-pick-card__dot" aria-hidden="true" />
                  <span class="ts-git-pick-card__label">复用业务仓库</span>
                </button>
              </div>
            </template>
            <div v-else class="ts-git-origin-field" role="group" aria-labelledby="ts-git-origin-label">
              <p id="ts-git-origin-label" class="ts-git-origin-field__label outlined-label">
                代码库位置
              </p>
              <div class="ts-native-radio-row" role="radiogroup" aria-label="代码库位置">
                <label class="ts-native-radio">
                  <input v-model="gitRepoPick" type="radio" name="ts-git-origin" value="custom" />
                  <span class="ts-native-radio__dot" aria-hidden="true" />
                  <span class="ts-native-radio__text">独立仓库</span>
                </label>
                <label class="ts-native-radio">
                  <input v-model="gitRepoPick" type="radio" name="ts-git-origin" value="reuse" />
                  <span class="ts-native-radio__dot" aria-hidden="true" />
                  <span class="ts-native-radio__text">复用业务仓库</span>
                </label>
              </div>
            </div>
            <div v-if="gitRepoPick === 'custom'" class="dg-form-item dg-form-item--full form-group md-field-item ts-md3-filled-field">
              <Md3FilledTextField
                v-if="isCreatePage"
                id="ts-form-git-url"
                v-model="form.git_url"
                mono
                placeholder="例如：https://gitlab.com"
                helper-text="Git URL / 本地路径；支持 GitLab、GitHub 等 HTTPS/SSH"
                @blur="onGitUrlBlur"
              >
                <template #label>测试仓库地址</template>
                <template #append>
                  <button
                    type="button"
                    class="ts-md3-paste-btn"
                    title="从剪贴板粘贴"
                    aria-label="粘贴仓库地址"
                    @click.stop="pasteGitUrl"
                  >
                    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" width="20" height="20">
                      <path
                        d="M8 4v2h8V4a2 2 0 00-2-2h-4a2 2 0 00-2 2zM6 6h12a2 2 0 012 2v12a2 2 0 01-2 2H6a2 2 0 01-2-2V8a2 2 0 012-2z"
                        stroke="currentColor"
                        stroke-width="1.75"
                        stroke-linejoin="round"
                      />
                    </svg>
                  </button>
                </template>
              </Md3FilledTextField>
              <OutlinedInput
                v-else
                id="ts-form-git-url"
                v-model="form.git_url"
                label-above
                label="测试仓库地址"
                mono
                placeholder="https://gitlab.com/qa/api-tests.git"
                helper-text="Git URL / 本地路径；支持 GitLab、GitHub 等 HTTPS/SSH"
                @blur="onGitUrlBlur"
              />
            </div>
            <div v-else class="dg-form-item dg-form-item--full form-group md-field-item ts-md3-filled-field">
              <OutlinedSelect
                id="ts-form-git-reuse"
                v-model="reuseRepoFieldModel"
                :label-above="!isCreatePage"
                label="复用业务仓库"
                :options="linkedRepoSelectOptions"
                searchable
                clearable
                :menu-surface-class="isCreatePage ? 'md-field-select-menu--md3-create' : ''"
                :disabled="reposLoading"
              />
            </div>
            <p v-if="gitRepoPick === 'custom' && cloneUrlHint" class="ts-form-hint ts-form-hint--parse">
              {{ cloneUrlHint }}
            </p>
            <div class="ts-suite-git-pair-row" :class="{ 'ts-suite-git-pair-row--md3': isCreatePage }">
              <div class="dg-form-item form-group md-field-item ts-suite-git-pair-row__cell ts-suite-git-branch-cell ts-md3-filled-field">
                <div class="ts-suite-git-branch-wrap" :class="{ 'ts-suite-git-branch-wrap--md3': isCreatePage }">
                  <OutlinedSelect
                    id="ts-form-git-branch"
                    v-model="form.git_branch"
                    :label-above="!isCreatePage"
                    label="目标分支"
                    placeholder="例如 main"
                    :options="gitBranchSelectOptions"
                    searchable
                    free-solo
                    clearable
                    :menu-surface-class="isCreatePage ? 'md-field-select-menu--md3-create' : ''"
                    :disabled="gitBranchesLoading"
                    :helper-text="isCreatePage ? undefined : gitBranchesHint || undefined"
                  >
                    <template v-if="isCreatePage" #empty>
                      暂无分支缓存，点击右侧刷新拉取或直接输入
                    </template>
                  </OutlinedSelect>
                  <button
                    type="button"
                    :class="[
                      isCreatePage
                        ? 'ts-md3-tonal-icon-btn ts-suite-branch-refresh-btn--md3'
                        : 'ts-icon-btn ts-suite-branch-refresh-btn',
                      {
                        'ts-md3-tonal-icon-btn--ready':
                          isCreatePage && canFetchGitBranches && !gitBranchesLoading,
                      },
                    ]"
                    :disabled="gitBranchesLoading || !canFetchGitBranches"
                    :title="
                      canFetchGitBranches
                        ? '刷新分支列表'
                        : '请先填写测试仓库地址'
                    "
                    aria-label="刷新分支列表"
                    @click="fetchGitBranches(true)"
                  >
                    <span v-if="gitBranchesLoading" class="ts-icon-btn__spinner" aria-hidden="true" />
                    <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path
                        d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                        stroke="currentColor"
                        stroke-width="1.75"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                      />
                    </svg>
                  </button>
                </div>
                <p
                  v-if="isCreatePage && gitBranchesHint"
                  class="md-field-helper ts-git-branch-hint"
                >
                  {{ gitBranchesHint }}
                </p>
              </div>
              <div class="dg-form-item form-group md-field-item ts-suite-git-pair-row__cell ts-md3-filled-field">
                <Md3FilledTextField
                  v-if="isCreatePage"
                  id="ts-form-case-path"
                  v-model="form.case_path"
                  mono
                  placeholder="cases/"
                  helper-text="例如 cases/"
                >
                  <template #label>用例扫描目录</template>
                </Md3FilledTextField>
                <OutlinedInput
                  v-else
                  id="ts-form-case-path"
                  v-model="form.case_path"
                  label-above
                  label="用例扫描目录"
                  mono
                  placeholder="cases/"
                  helper-text="例如 cases/"
                />
              </div>
            </div>
            <div
              class="ts-suite-framework-row"
              :class="
                isCreatePage && gitRepoPick === 'custom'
                  ? 'dg-form-grid-2 ts-suite-fw-credential-row'
                  : 'dg-form-item dg-form-item--full form-group md-field-item ts-suite-framework-only'
              "
            >
              <div class="form-group md-field-item ts-md3-filled-field">
                <OutlinedSelect
                  id="ts-form-framework"
                  v-model="frameworkFieldModel"
                  :label-above="!isCreatePage"
                  label="测试框架类型"
                  :options="frameworkSelectOptions"
                  searchable
                  clearable
                  :menu-surface-class="isCreatePage ? 'md-field-select-menu--md3-create' : ''"
                >
                  <template v-if="isCreatePage" #option="{ option }">
                    <div class="ts-framework-opt">
                      <span class="ts-framework-opt__chip" aria-hidden="true">{{ frameworkChip(option.value) }}</span>
                      <span class="ts-framework-opt__label">{{ option.label }}</span>
                    </div>
                  </template>
                </OutlinedSelect>
              </div>
              <div
                v-if="isCreatePage && gitRepoPick === 'custom'"
                class="form-group md-field-item ts-md3-filled-field"
              >
                <OutlinedSelect
                  id="ts-form-git-auth-preset-inline"
                  v-model="gitCredentialSelectModel"
                  :label-above="false"
                  label="凭证模式"
                  :options="gitCredentialSelectOptions"
                  clearable
                  :menu-surface-class="'md-field-select-menu--md3-create'"
                >
                  <template #helper>
                    <span class="ts-credential-inherit-hint">
                      默认自动继承；跨平台仓库可单独指定 Token / SSH。
                    </span>
                  </template>
                </OutlinedSelect>
              </div>
            </div>
            <div
              v-if="isCreatePage"
              class="ts-source-inset-footer"
            >
              <label
                v-if="gitRepoPick === 'custom'"
                class="ts-native-checkbox ts-md3-ssl-check"
              >
                <input v-model="form.skip_ssl_verify" type="checkbox" />
                <span class="ts-native-checkbox__box" aria-hidden="true" />
                <span class="ts-native-checkbox__text">跳过内网自签名 SSL 证书校验</span>
              </label>
              <p v-else class="ts-auth-reuse-hint ts-auth-reuse-hint--inset">
                复用业务仓库时将自动继承该仓库的访问凭据与 SSL 策略。
              </p>
              <div class="ts-suite-probe-block ts-suite-probe-callout ts-suite-probe-callout--inset">
                <div class="ts-suite-probe-callout__actions ts-suite-probe-callout__actions--md3">
                  <button
                    type="button"
                    class="ts-outlined-btn ts-suite-probe-btn ts-suite-probe-btn--md3"
                    :disabled="probeLoading"
                    @click="runConnectivityProbe"
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path
                        d="M13 2L3 14h7l-1 8 10-12h-7l1-8z"
                        stroke="currentColor"
                        stroke-width="2"
                        stroke-linejoin="round"
                      />
                    </svg>
                    {{ probeLoading ? '正在连接仓库并扫描用例…' : '测试连通性并预览用例数' }}
                  </button>
                  <p class="ts-suite-probe-callout__hint ts-suite-probe-callout__hint--inline">
                    点击可提前校验权限并预览识别出的 API 数量
                  </p>
                </div>
                <div
                  v-if="probePreview?.success"
                  class="ts-suite-probe-panel ts-suite-probe-panel--success"
                  role="status"
                >
                  <p class="ts-suite-probe-panel__head">
                    <span class="ts-suite-probe-panel__icon ts-suite-probe-panel__icon--ok" aria-hidden="true">✓</span>
                    <span>{{ probeSuccessHeadline }}</span>
                  </p>
                  <ul v-if="probePreview.sample_cases.length" class="ts-suite-probe-samples">
                    <li v-for="(c, idx) in probePreview.sample_cases" :key="`${c.file_path}-${idx}`">
                      <span class="ts-suite-probe-samples__route">{{ c.method }} {{ c.normalized_route }}</span>
                      <span class="ts-suite-probe-samples__sep">←</span>
                      <span class="ts-suite-probe-samples__title">{{ c.title }}</span>
                    </li>
                  </ul>
                  <p v-if="probeZeroCasesWarning" class="ts-suite-probe-panel__amber">
                    {{ probeZeroCasesWarning }}
                  </p>
                  <ul v-if="probePreview.warnings.length" class="ts-suite-probe-panel__warnings">
                    <li v-for="(w, wi) in probePreview.warnings" :key="wi">{{ w }}</li>
                  </ul>
                </div>
                <div
                  v-else-if="probePreview && !probePreview.success"
                  class="ts-suite-probe-panel ts-suite-probe-panel--error"
                  role="alert"
                >
                  <span class="ts-suite-probe-panel__icon ts-suite-probe-panel__icon--err" aria-hidden="true">!</span>
                  <span class="ts-suite-probe-panel__error-text">{{ probeFailureMessage }}</span>
                  <button
                    type="button"
                    class="ts-suite-probe-retry text-none"
                    :disabled="probeLoading"
                    @click="runConnectivityProbe"
                  >
                    重试
                  </button>
                </div>
              </div>
            </div>
          </div>
        </template>

        <template v-else-if="form.source_type === 'manual'">
          <div class="ts-manual-source-panel ts-manual-info-box" role="status">
            <svg class="ts-manual-source-panel__icon" width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path
                d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"
                stroke="currentColor"
                stroke-width="1.75"
                stroke-linecap="round"
              />
            </svg>
            <p class="ts-manual-source-panel__title">手工登记模式</p>
            <p class="ts-manual-source-panel__desc">
              不配置 Git 或 Webhook；创建后可在变更影响分析中手工维护用例，或由外部脚本上报覆盖率。
            </p>
          </div>
        </template>

        <template v-else-if="form.source_type === 'webhook'">
          <div
            class="ts-source-config-stack ts-git-config-stack ts-webhook-stack"
            :class="{ 'ts-source-inset-panel ts-webhook-inset-panel': isCreatePage }"
          >
            <div class="dg-form-item form-group md-field-item ts-suite-webhook-url-item ts-md3-filled-field">
              <Md3FilledTextField
                v-if="isCreatePage"
                id="ts-form-trigger-url"
                v-model="form.trigger_webhook_url"
                mono
                placeholder="https://ci.example.com/hooks/diffgate"
              >
                <template #label>调度触发 Webhook URL</template>
                <template #append>
                  <button
                    v-if="!triggerWebhookUrlFilled"
                    type="button"
                    class="ts-md3-paste-btn"
                    title="从剪贴板粘贴"
                    aria-label="粘贴 Webhook URL"
                    @click.stop="pasteWebhookUrl"
                  >
                    <svg viewBox="0 0 24 24" fill="none" width="20" height="20" aria-hidden="true">
                      <path
                        d="M8 4v2h8V4a2 2 0 00-2-2h-4a2 2 0 00-2 2zM6 6h12a2 2 0 012 2v12a2 2 0 01-2 2H6a2 2 0 01-2-2V8a2 2 0 012-2z"
                        stroke="currentColor"
                        stroke-width="1.75"
                        stroke-linejoin="round"
                      />
                    </svg>
                  </button>
                  <button
                    v-else
                    type="button"
                    class="ts-md3-paste-btn ts-md3-paste-btn--clear"
                    title="清除"
                    aria-label="清除 Webhook URL"
                    @click.stop="clearWebhookUrl"
                  >
                    <svg viewBox="0 0 24 24" fill="none" width="20" height="20" aria-hidden="true">
                      <path
                        d="M18 6L6 18M6 6l12 12"
                        stroke="currentColor"
                        stroke-width="1.75"
                        stroke-linecap="round"
                      />
                    </svg>
                  </button>
                </template>
                <template #helper>
                  精准回归时将向此地址发送 POST 请求（携带 api_list 与 job_id）
                </template>
              </Md3FilledTextField>
              <OutlinedInput
                v-else
                id="ts-form-trigger-url"
                v-model="form.trigger_webhook_url"
                label-above
                label="调度触发 Webhook URL"
                mono
              >
                <template #helper>
                  例如 <span class="ts-link-repos-mono">https://ci.example.com/hooks/diffgate</span>；
                  精准回归时将 POST <strong>api_list</strong> 与 <strong>job_id</strong>
                </template>
              </OutlinedInput>
            </div>
            <div class="dg-form-item form-group md-field-item ts-md3-filled-field ts-suite-external-ref-item">
              <Md3FilledTextField
                v-if="isCreatePage"
                id="ts-form-external-ref"
                :model-value="form.external_ref ?? ''"
                placeholder="Jenkins Job / 流水线 ID"
                @update:model-value="(v) => (form.external_ref = v)"
              >
                <template #label>外部平台引用 ID</template>
                <template #helper>可选：Jenkins Job / 流水线 ID</template>
              </Md3FilledTextField>
              <OutlinedInput
                v-else
                id="ts-form-external-ref"
                v-model="form.external_ref"
                label-above
                label="外部平台引用 ID"
                helper-text="可选：Jenkins Job / 流水线 ID"
              />
            </div>
            <div v-if="isCreatePage" class="ts-webhook-inset-footer">
              <button
                type="button"
                class="ts-outlined-btn ts-webhook-ping-btn"
                :disabled="webhookPingLoading"
                @click="sendWebhookPing"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path
                    d="M13 2L3 14h7l-1 8 10-12h-7l1-8z"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linejoin="round"
                  />
                </svg>
                {{ webhookPingLoading ? '发送中…' : '发送测试 Ping' }}
              </button>
              <p class="ts-webhook-ping-hint">
                向所填 URL 发送轻量 POST，用于确认回调可收到请求
              </p>
            </div>
          </div>
        </template>
      </section>

      <section
        v-if="form.source_type === 'git' && (!isCreatePage || showCreateGitAuthCard)"
        class="dg-form-card ts-suite-card ts-suite-card--advanced"
        :class="{ 'ts-suite-card--advanced-create': isCreatePage }"
      >
        <h2 v-if="!isCreatePage" class="dg-form-card__title">
          <svg
            class="dg-form-card__title-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.75"
            aria-hidden="true"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
            />
          </svg>
          认证与高级选项
        </h2>
        <div v-if="!isCreatePage" class="ts-auth-advanced-row">
          <div
            v-if="gitRepoPick === 'custom'"
            class="ts-auth-advanced-row__credential"
          >
            <OutlinedSelect
              id="ts-form-git-auth-preset"
              v-model="gitCredentialSelectModel"
              label-above
              label="凭证模式"
              :options="gitCredentialSelectOptions"
              clearable
            >
              <template #helper>
                <span class="ts-credential-inherit-hint">
                  默认自动继承；跨平台或私有仓库可单独指定 Token / SSH。
                  <span
                    v-if="tokenConfigured || sshConfigured"
                    class="ts-suite-auth-panels__badge"
                  >已保存凭证</span>
                </span>
              </template>
            </OutlinedSelect>
          </div>
          <div
            v-if="gitRepoPick === 'custom'"
            class="ts-auth-advanced-row__ssl"
          >
            <label class="ts-native-checkbox">
              <input v-model="form.skip_ssl_verify" type="checkbox" />
              <span class="ts-native-checkbox__box" aria-hidden="true" />
              <span class="ts-native-checkbox__text">跳过内网自签名 SSL 证书校验</span>
            </label>
          </div>
        </div>
        <div
          v-if="gitRepoPick === 'custom' && gitCredentialChosen && gitCredentialMode !== 'inherit'"
          class="ts-suite-auth-subpanel"
        >
          <p class="ts-suite-auth-subpanel__title">指定独立凭证</p>
          <div
            v-if="gitCredentialMode === 'token'"
            class="dg-form-item form-group md-field-item ts-suite-auth-subpanel__field"
          >
            <OutlinedPasswordInput
              id="ts-form-git-token"
              v-model="gitAccessToken"
              label-above
              label="访问令牌 (PAT / Deploy Token)"
              control-class="md-field-control--mono"
              allow-paste
              :helper-text="gitTokenHelper"
            />
          </div>
          <div
            v-else
            class="dg-form-item form-group md-field-item ts-suite-auth-subpanel__field ts-suite-ssh-key-block"
          >
            <OutlinedTextarea
              id="ts-form-git-ssh"
              v-model="gitSshKey"
              label-above
              label="SSH 私钥内容"
              :rows="5"
              allow-file-import
              accept-file-types=".pem,.key,.pub,text/plain"
              control-class="md-field-control--mono"
              :helper-text="gitSshHelper"
            />
          </div>
        </div>
        <p v-else-if="gitRepoPick === 'reuse' && !isCreatePage" class="ts-auth-reuse-hint">
          复用业务仓库时将自动继承该仓库的访问凭据与 SSL 策略。
        </p>
        <div v-if="!isCreatePage" class="ts-suite-probe-block ts-suite-probe-callout">
          <div class="ts-suite-probe-callout__actions">
            <button
              type="button"
              class="ts-outlined-btn ts-suite-probe-btn"
              :disabled="probeLoading"
              @click="runConnectivityProbe"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path
                  d="M13 2L3 14h7l-1 8 10-12h-7l1-8z"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linejoin="round"
                />
              </svg>
              {{ probeLoading ? '正在连接仓库并扫描用例…' : '测试连通性并预览用例数' }}
            </button>
            <p class="ts-suite-probe-callout__hint">
              点击可提前校验权限并预览识别出的 API 数量
            </p>
          </div>
          <div
            v-if="probePreview?.success"
            class="ts-suite-probe-panel ts-suite-probe-panel--success"
            role="status"
          >
            <p class="ts-suite-probe-panel__head">
              <span class="ts-suite-probe-panel__icon ts-suite-probe-panel__icon--ok" aria-hidden="true">✓</span>
              <span>{{ probeSuccessHeadline }}</span>
            </p>
            <ul v-if="probePreview.sample_cases.length" class="ts-suite-probe-samples">
              <li v-for="(c, idx) in probePreview.sample_cases" :key="`${c.file_path}-${idx}`">
                <span class="ts-suite-probe-samples__route">{{ c.method }} {{ c.normalized_route }}</span>
                <span class="ts-suite-probe-samples__sep">←</span>
                <span class="ts-suite-probe-samples__title">{{ c.title }}</span>
              </li>
            </ul>
            <p v-if="probeZeroCasesWarning" class="ts-suite-probe-panel__amber">
              {{ probeZeroCasesWarning }}
            </p>
            <ul v-if="probePreview.warnings.length" class="ts-suite-probe-panel__warnings">
              <li v-for="(w, wi) in probePreview.warnings" :key="wi">{{ w }}</li>
            </ul>
          </div>
          <div
            v-else-if="probePreview && !probePreview.success"
            class="ts-suite-probe-panel ts-suite-probe-panel--error"
            role="alert"
          >
            <span class="ts-suite-probe-panel__icon ts-suite-probe-panel__icon--err" aria-hidden="true">!</span>
            <span class="ts-suite-probe-panel__error-text">{{ probeFailureMessage }}</span>
            <button
              type="button"
              class="ts-suite-probe-retry text-none"
              :disabled="probeLoading"
              @click="runConnectivityProbe"
            >
              重试
            </button>
          </div>
        </div>
      </section>
    </form>

    <footer class="repo-form-page__dock ts-suite-form-dock">
      <div
        class="repo-form-page__dock-inner ts-suite-form-dock__inner"
        :class="{ 'ts-suite-form-dock__inner--create-md3': isCreatePage }"
      >
        <button
          v-if="!isCreatePage"
          type="button"
          class="ts-ghost-btn ts-suite-dock-cancel"
          @click="goBack"
        >
          取消
        </button>
        <div class="repo-form-page__dock-actions ts-suite-dock-actions">
          <button
            v-if="isCreatePage"
            type="button"
            class="ts-ghost-btn ts-suite-dock-cancel"
            @click="goBack"
          >
            取消
          </button>
          <button
            type="button"
            class="ts-primary-btn"
            :disabled="pageLoading || gitCreateBlocked || submitLoading"
            @click="submit"
          >
            {{ submitLoading ? '提交中…' : headerSaveLabel }}
          </button>
        </div>
      </div>
    </footer>

    <v-snackbar
      v-model="snackbar.show"
      :color="snackbar.color"
      location="top"
      :timeout="3200"
    >
      {{ snackbar.text }}
    </v-snackbar>
  </div>
</template>