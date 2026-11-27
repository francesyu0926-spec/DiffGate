import axios from 'axios'
import type {
  CodeDiffView,
  GraphNodeType,
  JobAnalysisStats,
  JobDetail,
  JobGraph,
  JobListItem,
  RepoOverviewStats,
  RepositoryItem,
  RepositoryPayload,
} from './types'

const http = axios.create({
  baseURL: '/api/v1',
  timeout: 15000,
})

const ACTOR_STORAGE_KEY = 'diffgate_actor_v1'
const SESSION_STORAGE_KEY = 'diffgate_session_v2'
export const LEGACY_DEV_TOKEN = '__legacy_dev__'

export interface AuthSession {
  token: string
  username: string
  display_name?: string
  role: string
  role_label?: string
  email?: string | null
  avatar_url?: string | null
  user_id?: string
  authenticated?: boolean
  legacy_dev?: boolean
}

export interface AuthMember {
  user_id: string
  username: string
  display_name: string
  email?: string | null
  avatar_url?: string | null
  role: string
  role_label?: string
  role_locked: boolean
  provider: string
  last_login_at?: string | null
}

export interface SessionWhoami {
  username: string
  role: string
  role_label?: string
  email?: string | null
  can_manual_override: boolean
  override_roles: string
}

export interface OverrideEligibility {
  allowed: boolean
  reason?: string | null
  hint?: string | null
  actor_role?: string
  actor_role_label?: string
  auditor_label?: string
  commit_author?: string
  share_url?: string
  share_text?: string
}

export function loadStoredActor(): { username: string; role: string; email?: string } {
  try {
    const raw = localStorage.getItem(ACTOR_STORAGE_KEY)
    if (!raw) return { username: 'developer', role: 'dev' }
    const parsed = JSON.parse(raw) as { username?: string; role?: string; email?: string }
    return {
      username: parsed.username?.trim() || 'developer',
      role: (parsed.role || 'dev').toLowerCase(),
      email: parsed.email?.trim() || undefined,
    }
  } catch {
    return { username: 'developer', role: 'dev' }
  }
}

export function saveStoredActor(username: string, role: string, email?: string) {
  localStorage.setItem(
    ACTOR_STORAGE_KEY,
    JSON.stringify({
      username: username.trim(),
      role: role.trim().toLowerCase(),
      email: email?.trim() || undefined,
    }),
  )
}

export function loadAuthSession(): AuthSession | null {
  try {
    const raw = localStorage.getItem(SESSION_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as AuthSession
    if (parsed?.legacy_dev || parsed?.token === LEGACY_DEV_TOKEN) return parsed
    if (!parsed?.token) return null
    return parsed
  } catch {
    return null
  }
}

export function hasAppSession(): boolean {
  return Boolean(loadAuthSession())
}

export function saveAuthSession(session: AuthSession) {
  localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session))
  saveStoredActor(session.username, session.role, session.email || undefined)
}

export function clearAuthSession() {
  localStorage.removeItem(SESSION_STORAGE_KEY)
}

http.interceptors.request.use((config) => {
  const session = loadAuthSession()
  config.headers = config.headers ?? {}
  if (session?.token && session.token !== LEGACY_DEV_TOKEN) {
    config.headers.Authorization = `Bearer ${session.token}`
  } else if (session?.legacy_dev || session?.token === LEGACY_DEV_TOKEN) {
    config.headers['X-DiffGate-User'] = session.username
    config.headers['X-DiffGate-Role'] = session.role
    if (session.email) config.headers['X-DiffGate-Email'] = session.email
  } else {
    const actor = loadStoredActor()
    config.headers['X-DiffGate-User'] = actor.username
    config.headers['X-DiffGate-Role'] = actor.role
    if (actor.email) config.headers['X-DiffGate-Email'] = actor.email
  }
  return config
})

export async function fetchAuthTokenWizard(gitlabBaseUrl?: string) {
  const { data } = await http.get<{
    github: { create_url: string; scopes_hint: string; wizard_link_text?: string }
    gitlab: { create_url: string; scopes_hint: string; wizard_link_text?: string }
  }>('/auth/token-wizard', { params: { gitlab_base_url: gitlabBaseUrl } })
  return data
}

export type AuthProvider = 'github' | 'gitlab' | 'local'

function sessionFromLoginPayload(
  data: AuthSession & { session_token: string; needs_password_setup?: boolean },
): AuthSession & { needs_password_setup?: boolean } {
  const session: AuthSession = {
    token: data.session_token,
    username: data.username,
    display_name: data.display_name,
    role: data.role,
    role_label: data.role_label,
    email: data.email,
    avatar_url: data.avatar_url,
    user_id: data.user_id,
    authenticated: true,
  }
  saveAuthSession(session)
  return { ...session, needs_password_setup: data.needs_password_setup }
}

/** API 未重启、无认证路由时：仅 Header 模拟 admin（无法使用成员管理） */
export function establishLegacyDevSession(): AuthSession {
  const session: AuthSession = {
    token: LEGACY_DEV_TOKEN,
    username: 'local-dev',
    display_name: '本地调试',
    role: 'admin',
    role_label: '管理员',
    email: 'dev@localhost',
    authenticated: true,
    legacy_dev: true,
  }
  saveAuthSession(session)
  return session
}

function isAxiosStatus(err: unknown, code: number) {
  return (err as { response?: { status?: number } })?.response?.status === code
}

export async function loginWithPat(body: {
  provider: AuthProvider
  access_token?: string
  gitlab_base_url?: string
  dev_local?: boolean
}) {
  try {
    const { data } = await http.post<AuthSession & { session_token: string }>('/auth/login', body, {
      timeout: 120000,
    })
    return sessionFromLoginPayload(data)
  } catch (err) {
    if (body.dev_local && isAxiosStatus(err, 404)) {
      try {
        const { data } = await http.post<AuthSession & { session_token: string }>(
          '/system/local-dev-login',
          {},
          { timeout: 60000 },
        )
        return sessionFromLoginPayload(data)
      } catch (err2) {
        if (isAxiosStatus(err2, 404)) {
          return establishLegacyDevSession()
        }
        throw err2
      }
    }
    throw err
  }
}

export async function loginLocalDev() {
  return loginWithPat({ provider: 'local', dev_local: true })
}

export async function loginWithPassword(login: string, password: string) {
  const { data } = await http.post<AuthSession & { session_token: string; needs_password_setup?: boolean }>(
    '/auth/login-password',
    { login, password },
    { timeout: 60000 },
  )
  return sessionFromLoginPayload(data)
}

export async function setAuthPassword(password: string, passwordConfirm: string) {
  await http.post('/auth/set-password', {
    password,
    password_confirm: passwordConfirm,
  })
}

export async function logoutAuth() {
  try {
    await http.post('/auth/logout')
  } finally {
    clearAuthSession()
  }
}

export async function fetchAuthSession() {
  const { data } = await http.get<AuthSession & SessionWhoami>('/auth/session')
  return data
}

export async function fetchAuthMembers() {
  const { data } = await http.get<{ items: AuthMember[] }>('/auth/members')
  return data.items
}

export async function patchAuthMemberRole(userId: string, role: string, roleLocked = true) {
  const { data } = await http.patch<{
    user_id: string
    role: string
    role_label?: string
    role_locked: boolean
  }>(`/auth/members/${userId}`, { role, role_locked: roleLocked })
  return data
}

export async function fetchWhoami() {
  const { data } = await http.get<SessionWhoami>('/system/whoami')
  return data
}

/** Turn verbose git/索引 failures into short Chinese hints for snackbars. */
export function humanizeRepoIndexError(raw: string): string {
  const body = raw.replace(/^索引失败:\s*/u, '').trim()
  const lower = body.toLowerCase()

  if (lower.includes('尚未保存私钥') || lower.includes('需要配置 ssh 私钥')) {
    return body.includes('索引失败') ? body.replace(/^索引失败:\s*/u, '索引失败：') : `索引失败：${body}`
  }
  if (lower.includes('error in libcrypto') || lower.includes('unprotected private key')) {
    return '索引失败：SSH 私钥在 Windows 上无法加载（多为临时文件权限）。已修复后端逻辑，请重启 API 后再次重建索引；若仍失败请重新粘贴私钥并保存。'
  }
  if (lower.includes('permission denied (publickey)') || /publickey|public key/u.test(lower)) {
    return '索引失败：SSH 公钥认证被拒绝。请确认 GitHub Deploy key 与私钥为同一对，或改用 HTTPS + Token。'
  }
  if (
    lower.includes('authentication failed') ||
    lower.includes('invalid username or password') ||
    lower.includes('access denied')
  ) {
    return '索引失败：Git 认证失败。请检查 Access Token、账号权限，或 SSH 私钥是否与该仓库匹配。'
  }
  if (lower.includes('repository not found') || lower.includes('could not find remote ref')) {
    return '索引失败：远程仓库不存在、无权限，或默认分支不正确。请核对 Clone URL 与分支名。'
  }
  if (lower.includes('could not read from remote repository')) {
    return '索引失败：无法从远程读取仓库。请确认认证方式、分支与网络可达性。'
  }
  if (lower.includes('command') && lower.includes('git clone') && lower.includes('timed out')) {
    return '索引失败：克隆超时。请检查网络或仓库体积，稍后重试。'
  }

  const firstLine = body.split(/\r?\n/u).find((line) => line.trim())?.trim() ?? body
  let brief = firstLine
    .replace(/Cmd\([^)]*\):\s*/gi, '')
    .replace(/cmd:\s*\[[^\]]*\]\s*/gi, '')
    .replace(/['"][^'"]*(?:\\|\/)[^'"]*['"]/g, '')
    .replace(/\s{2,}/g, ' ')
    .trim()
  if (!brief) brief = '请检查 Clone 地址、认证方式与默认分支'
  if (brief.length > 96) brief = `${brief.slice(0, 93)}…`
  return `索引失败：${brief}`
}

/** 任务详情失败横幅：worktree 纯路径、Git 认证等 → 可读说明 */
export function humanizeJobError(raw: string | null | undefined): string {
  if (!raw?.trim()) return '分析失败，请重试。'
  const body = raw.trim()
  const lower = body.toLowerCase()
  if (
    /^[a-z]:\\.*worktrees\\[0-9a-f-]{8,}/i.test(body) &&
    !body.includes('请') &&
    body.length < 200
  ) {
    return (
      '分析沙箱 worktree 未成功挂载（仅记录了磁盘路径）。' +
      '请在本页点击「重新分析」，并在仓库管理确认 SSH/HTTPS 凭据与 AST 索引。'
    )
  }
  if (lower.includes('permission denied') || lower.includes('publickey')) {
    return '分析失败：Git SSH 认证被拒绝。请在「仓库管理」配置私钥或 HTTPS Token 后重新分析。'
  }
  if (lower.includes('invalid reference') || body.includes('缺少提交')) {
    return '分析失败：本地克隆不包含该次 Push 的提交。请配置凭据后重试，或对该仓库重新克隆/索引。'
  }
  if (body.length > 320) return `${body.slice(0, 317)}…`
  return body
}

function normalizeApiDetail(detail: string): string {
  const trimmed = detail.trim()
  if (!trimmed) return trimmed
  if (trimmed.includes('索引失败') || /git clone|gitpython|fatal:/iu.test(trimmed)) {
    return humanizeRepoIndexError(trimmed)
  }
  if (trimmed.length > 180) return `${trimmed.slice(0, 177)}…`
  return trimmed
}

const AXIOS_STATUS_RE = /^Request failed with status code (\d+)$/i

function isAxiosGenericMessage(msg: string): boolean {
  return AXIOS_STATUS_RE.test(msg.trim())
}

/** FastAPI `detail` string or validation error message for snackbars. */
export function readApiError(err: unknown, fallback: string): string {
  if (err instanceof Error && isAxiosGenericMessage(err.message)) return fallback
  if (!axios.isAxiosError(err)) return fallback
  const data = err.response?.data as { detail?: string | Array<{ msg?: string }> } | undefined
  const detail = data?.detail
  if (typeof detail === 'string' && detail.trim()) {
    if (isAxiosGenericMessage(detail)) return fallback
    return normalizeApiDetail(detail)
  }
  if (Array.isArray(detail) && detail[0]?.msg) {
    const msg = detail[0].msg!
    if (isAxiosGenericMessage(msg)) return fallback
    return normalizeApiDetail(msg)
  }
  if (err.code === 'ECONNABORTED') return '请求超时，索引可能仍在进行，请稍后刷新列表'
  if (isAxiosGenericMessage(err.message)) return fallback
  return fallback
}

export type ApiErrorView = { message: string; code?: number }

/** Human-facing error for modals: hides axios noise and surfaces HTTP status as secondary hint. */
export function formatApiErrorView(err: unknown, fallback: string): ApiErrorView {
  const code = axios.isAxiosError(err) ? err.response?.status : undefined
  let message = readApiError(err, fallback)
  if (code && code >= 500 && message === fallback) {
    message = fallback.includes('分析') ? '分析请求失败，请稍后重试' : '服务异常，请稍后重试'
  }
  return { message, code }
}

export type JobListPage = {
  items: JobListItem[]
  total: number
  limit: number
  offset: number
}

export async function fetchJobs(
  limit = 50,
  offset = 0,
  filters?: { repo?: string; status?: string },
) {
  const { data } = await http.get<Partial<JobListPage> & { items: JobListItem[] }>('/jobs', {
    params: { limit, offset, repo: filters?.repo, status: filters?.status },
  })
  let total = data.total
  if (typeof total !== 'number' || !Number.isFinite(total)) {
    total =
      data.items.length < limit
        ? offset + data.items.length
        : offset + data.items.length + limit
  }
  return {
    items: data.items,
    total,
    limit: data.limit ?? limit,
    offset: data.offset ?? offset,
  }
}

export async function fetchJobAnalysisStats() {
  const { data } = await http.get<JobAnalysisStats>('/jobs/stats/overview')
  return data
}

export async function fetchJob(jobId: string) {
  const { data } = await http.get<JobDetail>(`/jobs/${jobId}`)
  return data
}

export async function fetchJobGraph(jobId: string) {
  const { data } = await http.get<JobGraph>(`/jobs/${jobId}/graph`)
  return data
}

export async function refreshJobFullstack(jobId: string) {
  const { data } = await http.post<{ ok: boolean }>(`/jobs/${jobId}/refresh-fullstack`)
  return data
}

export async function retryJob(jobId: string) {
  const { data } = await http.post<{ ok: boolean; job_id: string }>(`/jobs/${jobId}/retry`)
  return data
}

export async function fetchJobCodeDiff(
  jobId: string,
  params: {
    file: string
    start_line: number
    end_line: number
    node_type?: GraphNodeType
    highlight?: string
  },
) {
  const { data } = await http.get<CodeDiffView>(`/jobs/${jobId}/code-diff`, { params })
  return data
}

export type TestSuitePreset = {
  slug: string
  name: string
  description?: string | null
}

export type TestSuiteSourceType = 'git' | 'webhook' | 'manual'
export type TestSuiteFramework = 'yaml' | 'pytest' | 'httprunner' | 'apifox' | 'junit' | 'gotest'
export type TestSuiteGitAuthMethod = 'inherit' | 'token' | 'ssh'

export type TestSuiteItem = {
  id: string
  slug: string
  name: string
  description: string | null
  external_ref: string | null
  enabled: boolean
  source_type: TestSuiteSourceType
  git_url: string | null
  git_branch: string | null
  case_path: string | null
  framework: TestSuiteFramework | null
  git_reuse_repository_id: string | null
  git_auth_method?: TestSuiteGitAuthMethod
  token_configured?: boolean
  ssh_configured?: boolean
  skip_ssl_verify?: boolean
  trigger_webhook_url: string | null
  indexed_api_count: number
  case_count: number
  last_synced_at: string | null
  repo_count: number
  linked_repository_ids: string[]
  created_at: string | null
  updated_at: string | null
}

export type TestSuitePayload = {
  slug: string
  name: string
  description?: string | null
  external_ref?: string | null
  enabled?: boolean
  source_type?: TestSuiteSourceType
  git_url?: string | null
  git_branch?: string | null
  case_path?: string | null
  framework?: TestSuiteFramework | null
  git_reuse_repository_id?: string | null
  git_auth_method?: TestSuiteGitAuthMethod
  access_token?: string | null
  ssh_private_key?: string | null
  skip_ssl_verify?: boolean
  trigger_webhook_url?: string | null
  repository_ids?: string[]
}

export type CloneUrlMeta = {
  ok: boolean
  provider?: string
  transport?: string
  full_name?: string
  host?: string | null
  base_url?: string | null
  project_path?: string | null
  suggested_auth?: string
  local_valid?: boolean
  message?: string
}

export type TestSuiteProbeResult = {
  ok: boolean
  message: string
  case_count: number
  api_count: number
  url_meta?: CloneUrlMeta
  credential_source?: string
}

export async function parseCloneUrl(cloneUrl: string, provider?: 'github' | 'gitlab' | 'local') {
  const { data } = await http.post<CloneUrlMeta>('/repositories/parse-clone-url', {
    clone_url: cloneUrl,
    ...(provider ? { provider } : {}),
  })
  return data
}

export type TestSuiteProbePayload = {
  git_url?: string | null
  git_branch?: string | null
  case_path?: string | null
  framework?: TestSuiteFramework | null
  git_reuse_repository_id?: string | null
  git_auth_method?: TestSuiteGitAuthMethod
  access_token?: string | null
  ssh_private_key?: string | null
  skip_ssl_verify?: boolean | null
}

export type TestSuitePreviewPayload = {
  source_type?: TestSuiteSourceType
  clone_url?: string | null
  linked_repo_id?: string | null
  credential_mode?: 'auto' | 'token' | 'ssh'
  access_token?: string | null
  ssh_private_key?: string | null
  verify_ssl?: boolean
  branch?: string | null
  scan_path?: string | null
  framework?: TestSuiteFramework | null
  test_suite_id?: string | null
}

export type TestSuitePreviewCaseSample = {
  title: string
  method: string
  normalized_route: string
  file_path: string
}

export type TestSuitePreviewSummary = {
  matched_files: number
  total_cases: number
  covered_api_count: number
}

export type TestSuitePreviewResult = {
  success: boolean
  latency_ms: number
  repo_reachable: boolean
  branch_exists: boolean
  scan_path_exists: boolean
  summary: TestSuitePreviewSummary
  sample_cases: TestSuitePreviewCaseSample[]
  warnings: string[]
  error_detail?: string | null
  message?: string | null
  credential_source?: string | null
  url_meta?: CloneUrlMeta
}

export async function previewTestSuiteSource(body: TestSuitePreviewPayload) {
  const { data } = await http.post<TestSuitePreviewResult>('/test-suites/preview', body)
  return data
}

export async function probeTestSuiteSource(body: TestSuiteProbePayload) {
  const method = body.git_auth_method || 'inherit'
  const credential_mode: 'auto' | 'token' | 'ssh' =
    method === 'ssh' ? 'ssh' : method === 'token' ? 'token' : 'auto'
  const preview = await previewTestSuiteSource({
    source_type: 'git',
    clone_url: body.git_reuse_repository_id ? null : body.git_url ?? null,
    linked_repo_id: body.git_reuse_repository_id ?? null,
    credential_mode,
    access_token: body.access_token ?? null,
    ssh_private_key: body.ssh_private_key ?? null,
    verify_ssl: body.skip_ssl_verify === false ? false : true,
    branch: body.git_branch ?? 'main',
    scan_path: body.case_path ?? null,
    framework: body.framework ?? 'yaml',
  })
  return {
    ok: preview.success,
    message: preview.message || '',
    case_count: preview.summary?.total_cases ?? 0,
    api_count: preview.summary?.covered_api_count ?? 0,
    credential_source: preview.credential_source ?? undefined,
    url_meta: preview.url_meta,
  } satisfies TestSuiteProbeResult
}

export type TestSuiteBranchesPayload = {
  git_url?: string | null
  git_reuse_repository_id?: string | null
  git_auth_method?: TestSuiteGitAuthMethod
  access_token?: string | null
  ssh_private_key?: string | null
  skip_ssl_verify?: boolean | null
  test_suite_id?: string | null
}

export type RepositoryBranchItem = {
  name: string
  is_default: boolean
}

export type RepositoryBranchesDetectPayload = {
  clone_url?: string | null
  credential_mode?: 'auto' | 'token' | 'ssh'
  access_token?: string | null
  ssh_private_key?: string | null
  verify_ssl?: boolean
  linked_repo_id?: string | null
  test_suite_id?: string | null
}

export type RepositoryBranchesDetectResult = {
  success: boolean
  source: string
  default_branch: string
  branches: RepositoryBranchItem[]
  error_message?: string | null
}

export async function fetchRepositoryBranches(body: RepositoryBranchesDetectPayload) {
  const { data } = await http.post<RepositoryBranchesDetectResult>('/repositories/branches', {
    clone_url: body.clone_url ?? null,
    credential_mode: body.credential_mode ?? 'auto',
    access_token: body.access_token ?? null,
    ssh_private_key: body.ssh_private_key ?? null,
    verify_ssl: body.verify_ssl ?? true,
    linked_repo_id: body.linked_repo_id ?? null,
    test_suite_id: body.test_suite_id ?? null,
  })
  return data
}

export type TestSuiteBranchesResult = {
  ok: boolean
  items: string[]
  default_branch: string
  message?: string
  source?: string
}

export async function fetchTestSuiteBranches(body: TestSuiteBranchesPayload) {
  const method = body.git_auth_method || 'inherit'
  const credential_mode: 'auto' | 'token' | 'ssh' =
    method === 'ssh' ? 'ssh' : method === 'token' ? 'token' : 'auto'
  const linked = body.git_reuse_repository_id ?? null
  const detect = await fetchRepositoryBranches({
    clone_url: linked ? null : body.git_url ?? null,
    credential_mode,
    access_token: body.access_token ?? null,
    ssh_private_key: body.ssh_private_key ?? null,
    verify_ssl: body.skip_ssl_verify === false ? false : true,
    linked_repo_id: linked,
    test_suite_id: body.test_suite_id ?? null,
  })
  return {
    ok: detect.success,
    items: (detect.branches || []).map((b) => b.name),
    default_branch: detect.default_branch || 'main',
    message: detect.error_message || undefined,
    source: detect.source,
  } satisfies TestSuiteBranchesResult
}

export async function fetchTestSuitePresets() {
  const { data } = await http.get<{ items: TestSuitePreset[] }>('/repositories/meta/test-suites')
  return data.items
}

export async function fetchTestSuites(q?: string, enabledOnly?: boolean) {
  const { data } = await http.get<{ items: TestSuiteItem[] }>('/test-suites', {
    params: {
      ...(q ? { q } : {}),
      ...(enabledOnly ? { enabled_only: true } : {}),
    },
  })
  return data.items
}

export async function createTestSuite(body: TestSuitePayload) {
  const { data } = await http.post<TestSuiteItem>('/test-suites', body)
  return data
}

export async function updateTestSuite(id: string, body: Partial<TestSuitePayload>) {
  const { data } = await http.patch<TestSuiteItem>(`/test-suites/${id}`, body)
  return data
}

export async function deleteTestSuite(id: string) {
  await http.delete(`/test-suites/${id}`)
}

export type TestSuiteSyncStats = {
  added: number
  updated: number
  removed: number
  api_count: number
  case_count: number
}

export async function syncTestSuite(id: string) {
  const { data } = await http.post<
    TestSuiteItem & { message?: string; sync_stats?: TestSuiteSyncStats; skipped?: boolean }
  >(`/test-suites/${id}/sync`)
  return data
}

export type RepoTypeMeta = {
  id: string
  label: string
  language: string
  index_supported?: boolean
  coming_soon?: boolean
  preview_only?: boolean
  coverage_hint?: string
}

export async function fetchRepoTypeOptions() {
  const { data } = await http.get<{ items: RepoTypeMeta[] }>('/repositories/meta/repo-types')
  return data.items
}

export type DetectRepositoryCandidate = {
  repo_type: string
  repo_type_id?: string
  scan_root: string
  label: string
  framework?: string | null
  suggested_full_name?: string
}

export type DetectRepositoryDirectory = {
  path: string
  label: string
  is_recommended?: boolean
  matched_type?: string | null
  file_summary?: string
}

/** @deprecated 使用 directories */
export type DetectRepositoryScanDirectory = {
  path: string
  recommended?: boolean
}

export type DetectRepositoryProfile = {
  success?: boolean
  repo_type: string
  scan_root: string
  label: string
  confidence?: string
  monorepo_hint?: string | null
  is_monorepo?: boolean
  detected_type?: string
  suggested_scan_root?: string
  recommended_root?: string
  suggested_name?: string
  suggested_full_name?: string
  default_branch?: string
  framework?: string | null
  candidates?: DetectRepositoryCandidate[]
  directories?: DetectRepositoryDirectory[]
  scan_directories?: DetectRepositoryScanDirectory[]
  error_message?: string | null
}

export async function detectRepositoryProfile(payload: {
  clone_url: string
  source_type: string
  branch?: string
  auth_mode?: string
  custom_token?: string | null
  provider?: string
  default_branch?: string
}) {
  const { data } = await http.post<DetectRepositoryProfile>('/repositories/detect', payload)
  return data
}

export async function createMonorepoBundle(payload: {
  clone_url: string
  provider: string
  default_branch?: string
  base_full_name: string
  candidates: Array<{ repo_type_id: string; scan_root: string }>
  description?: string | null
}) {
  const { data } = await http.post<{ items: RepositoryItem[] }>('/repositories/monorepo-bundle', payload)
  return data.items
}

export async function fetchRepositories(q?: string) {
  const { data } = await http.get<{ items: RepositoryItem[] }>('/repositories', {
    params: q ? { q } : {},
  })
  return data.items
}

export async function createRepository(payload: RepositoryPayload) {
  const { data } = await http.post<RepositoryItem>('/repositories', payload)
  return data
}

export async function updateRepository(id: string, payload: Partial<RepositoryPayload>) {
  const { data } = await http.patch<RepositoryItem>(`/repositories/${id}`, payload)
  return data
}

export async function testRepositoryNotify(webhookUrl: string) {
  const url = webhookUrl.trim()
  const { data } = await http.post<{ success: boolean; platform: string; message: string }>(
    '/repositories/test-notify',
    { webhook_url: url },
  )
  return data
}

export async function deleteRepository(id: string) {
  await http.delete(`/repositories/${id}`)
}

export async function fetchRepoOverview() {
  const { data } = await http.get<RepoOverviewStats>('/repositories/stats/overview')
  return data
}

export async function reindexRepository(id: string) {
  const { data } = await http.post<{
    ok: boolean
    repository: RepositoryItem
    stats?: { method_count: number; api_count: number; scan_root?: string; scan_root_auto_fixed?: boolean }
  }>(`/repositories/${id}/reindex`, null, { timeout: 120000 })
  return data
}

export async function fetchRepoBranches(id: string) {
  const { data } = await http.get<{
    items: string[]
    default_branch: string
    cache_ttl_sec?: number
  }>(`/repositories/${id}/branches`, { timeout: 45000 })
  return data
}

export async function triggerRepoAnalysis(
  id: string,
  opts?: { branch?: string; base_branch?: string },
) {
  const { data } = await http.post<{ ok: boolean; job_id: string }>(
    `/repositories/${id}/analyze`,
    opts ?? {},
  )
  return data
}

export interface SystemStatus {
  webhook_public_base_url?: string | null
  webhook_github_url?: string | null
  webhook_gitlab_url?: string | null
  webhook_secret_github_configured?: boolean
  webhook_secret_gitlab_configured?: boolean
  api_online?: boolean
  db_online?: boolean
  ast_engine: string
  redis_online: boolean
  use_redis: boolean
  worker_mode: string
  worker_online: number
}

export type HomeSuggestedAction = 'add_repo' | 'index_repo' | 'run_analysis' | 'ok'

export interface DashboardOverview {
  home?: {
    repo_count: number
    indexed_repo_count: number
    jobs_in_range: number
    analysis_total: number
    suggested_action: HomeSuggestedAction
  }
  kpi: {
    avg_coverage: number
    coverage_sample_count?: number
    coverage_delta: number
    gate_baseline: number
    first_pass_rate: number
    pass_count: number
    block_count: number
    pending_count?: number
    high_risk_total: number
    saved_hours: number
    case_compress_pct: number
  }
  trend: {
    labels: string[]
    changed_lines: number[]
    coverage: (number | null)[]
    threshold: number
  }
  intercept_reasons: { name: string; value: number }[]
  repo_gate_stats: { full_name: string; block_count: number; pending_count: number }[]
  recent_flows: {
    commit: string
    repo: string
    changed_files: number
    api_impact: number
    coverage: number | null
    gate: string
    time: string | null
    job_id: string | null
    block_reason?: string | null
    block_reason_label?: string | null
    trigger_detail_summary?: string | null
  }[]
  code_hotspots?: {
    path: string
    change_hits: number
    block_hits: number
    score: number
    latest_job_id?: string | null
    repo?: string | null
    start_line?: number
    end_line?: number
  }[]
}

export async function fetchDashboardOverview(days = 7, repo?: string) {
  const { data } = await http.get<DashboardOverview>('/dashboard/overview', {
    params: { days, repo: repo || undefined },
  })
  return data
}

export async function resolveHotspotJob(path: string, repo?: string | null, days = 30) {
  const { data } = await http.get<{
    job_id: string
    repo: string
    path?: string
    start_line?: number
    end_line?: number
  }>('/dashboard/hotspot-resolve', {
    params: { path, repo: repo || undefined, days },
  })
  return data
}

export async function fetchSystemStatus() {
  const { data } = await http.get<SystemStatus>('/system/status')
  return data
}

export interface RegressionOverview {
  kpi: {
    executed_cases: number
    baseline_cases: number
    case_reduction_pct: number
    latest_pass_rate: number
    latest_passed: number
    latest_total: number
    avg_response_ms: number
    incremental_coverage_pct: number | null
    changed_lines: number
    covered_lines: number
    current_gate: string | null
    block_reason?: string | null
    block_reason_label?: string | null
  }
}

export interface GateTriggerDetail {
  kind: string
  summary: string
  metrics?: Record<string, number>
  high_risk_items?: {
    apis?: { method?: string; path?: string; file?: string; status_code?: number | null; error?: string }[]
    symbols?: { qualified_name?: string; file?: string | null }[]
  }
}

export interface RegressionBatchItem {
  job_id: string
  repo: string
  commit: string
  ref: string
  gate: string
  created_at: string | null
  api_impact: number
  coverage: number | null
  changed_lines?: number
  covered_lines?: number
}

export interface PrecisionRecallResult {
  bound: boolean
  test_suite_slug: string | null
  test_suite_name: string | null
  repository?: string
  total_indexed_cases: number
  affected_fingerprints: string[]
  affected_contract_keys?: string[]
  hit_cases: Array<{
    case_uid: string
    title: string
    run_selector: string
    file_path?: string | null
    source_framework: string
    matched_fingerprints: string[]
    matched_contract_keys?: string[]
  }>
  hit_case_count: number
  case_reduction_pct: number | null
  gaps: Array<{
    fingerprint: string
    contract_key?: string
    missing: boolean
    label: string
  }>
  execution: {
    framework: string
    case_uids: string[]
    selectors: string[]
    pytest_command: string | null
    yaml_paths: string[] | null
    shell_one_liner: string | null
  }
  webhook_payload?: Record<string, unknown>
  webhook_dispatch_url?: string | null
}

export interface HighRiskDetails {
  triggered_by?: string[]
  api_count?: number
  api_threshold?: number
  symbol_count?: number
  symbol_threshold?: number
  override_hint?: string
  matched_impacts?: {
    backend_api?: string
    page_file?: string
    frontend_repo?: string
  }[]
  matched_modules?: {
    file: string | null
    symbol: string | null
    level?: string
    reason: string
  }[]
}

export interface RegressionBatchDetail {
  job_id: string
  repo: string
  commit: string
  gate: string
  gate_label?: string
  block_reason?: string | null
  block_reason_label?: string | null
  trigger_detail?: GateTriggerDetail | null
  high_risk_details?: HighRiskDetails | null
  notify_status?: { sent?: boolean; sent_at?: string | null; error_msg?: string | null }
  manual_override?: {
    actor: string
    auditor_role?: string
    at: string
    reason_category: string
    reason_category_label: string
    reason_detail: string
  } | null
  allow_manual_override?: boolean
  override_eligibility?: OverrideEligibility
  gate_result: Record<string, unknown>
  cases: {
    method: string
    path: string
    yaml_file: string
    status: string
    duration_ms: number
    assertions?: string[]
    request_preview?: string
    response_preview?: string
    http_status?: number | null
  }[]
  coverage_lines: {
    file: string
    line: number
    covered: boolean | null
    prefix: string
    ignored?: boolean
    filter_reason?: string | null
  }[]
  incremental_coverage_pct: number | null
  changed_lines: number
  covered_lines?: number
  diff_lines_total?: number | null
  executable_changed_lines?: number | null
  lines_filtered?: number | null
  coverage_not_required?: boolean
  execution_status?: string
  execution_phase_label?: string | null
  probe_ui_hint?: string | null
  precision_recall?: PrecisionRecallResult
}

export async function fetchRegressionOverview(repo?: string, gate?: string) {
  const { data } = await http.get<RegressionOverview>('/regression/overview', {
    params: { repo: repo || undefined, gate: gate || undefined },
  })
  return data
}

export async function fetchRegressionBatches(repo?: string, gate?: string, limit = 30) {
  const { data } = await http.get<{ items: RegressionBatchItem[] }>('/regression/batches', {
    params: { repo: repo || undefined, gate: gate || undefined, limit },
  })
  return data.items
}

export async function fetchRegressionBatchDetail(jobId: string) {
  const { data } = await http.get<RegressionBatchDetail>(`/regression/batches/${jobId}`)
  return data
}

export async function runRegressionCoverageProbe(jobId: string) {
  const { data } = await http.post<{ ok: boolean; job_id: string; status: string }>(
    `/regression/batches/${jobId}/run-coverage`,
  )
  return data
}

export type GateOverrideReasonCategory =
  | 'hotfix'
  | 'branch_unsimulatable'
  | 'non_core_reviewed'
  | 'fe_be_coordinated'
  | 'other'

export async function submitRegressionGateOverride(
  jobId: string,
  body: {
    reason_category: GateOverrideReasonCategory
    reason_detail: string
  },
) {
  const { data } = await http.post<{ ok: boolean; gate_result: Record<string, unknown> }>(
    `/regression/batches/${jobId}/override`,
    body,
  )
  return data
}