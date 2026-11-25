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

function normalizeApiDetail(detail: string): string {
  const trimmed = detail.trim()
  if (!trimmed) return trimmed
  if (trimmed.includes('索引失败') || /git clone|gitpython|fatal:/iu.test(trimmed)) {
    return humanizeRepoIndexError(trimmed)
  }
  if (trimmed.length > 180) return `${trimmed.slice(0, 177)}…`
  return trimmed
}

/** FastAPI `detail` string or validation error message for snackbars. */
export function readApiError(err: unknown, fallback: string): string {
  if (!axios.isAxiosError(err)) return fallback
  const data = err.response?.data as { detail?: string | Array<{ msg?: string }> } | undefined
  const detail = data?.detail
  if (typeof detail === 'string' && detail.trim()) return normalizeApiDetail(detail)
  if (Array.isArray(detail) && detail[0]?.msg) return normalizeApiDetail(detail[0].msg!)
  if (err.code === 'ECONNABORTED') return '请求超时，索引可能仍在进行，请稍后刷新列表'
  return fallback
}

export async function fetchJobs(
  limit = 50,
  offset = 0,
  filters?: { repo?: string; status?: string },
) {
  const { data } = await http.get<{ items: JobListItem[] }>('/jobs', {
    params: { limit, offset, repo: filters?.repo, status: filters?.status },
  })
  return data.items
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

export async function fetchTestSuitePresets() {
  const { data } = await http.get<{ items: string[] }>('/repositories/meta/test-suites')
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

export async function deleteRepository(id: string) {
  await http.delete(`/repositories/${id}`)
}

export async function fetchRepoOverview() {
  const { data } = await http.get<RepoOverviewStats>('/repositories/stats/overview')
  return data
}

export async function reindexRepository(id: string) {
  const { data } = await http.post<{ ok: boolean; repository: RepositoryItem }>(
    `/repositories/${id}/reindex`,
    null,
    { timeout: 120000 },
  )
  return data
}

export async function triggerRepoAnalysis(id: string) {
  const { data } = await http.post<{ ok: boolean; job_id: string }>(`/repositories/${id}/analyze`)
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
    block_reason_label?: string | null
  }[]
}

export async function fetchDashboardOverview(days = 7, repo?: string) {
  const { data } = await http.get<DashboardOverview>('/dashboard/overview', {
    params: { days, repo: repo || undefined },
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
}

export interface RegressionBatchDetail {
  job_id: string
  repo: string
  commit: string
  gate: string
  gate_label?: string
  manual_override?: {
    actor: string
    at: string
    reason_category: string
    reason_category_label: string
    reason_detail: string
  } | null
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
  }[]
  incremental_coverage_pct: number | null
  changed_lines: number
  covered_lines?: number
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

export type GateOverrideReasonCategory =
  | 'hotfix'
  | 'branch_unsimulatable'
  | 'non_core_reviewed'
  | 'other'

export async function submitRegressionGateOverride(
  jobId: string,
  body: {
    reason_category: GateOverrideReasonCategory
    reason_detail: string
    actor?: string
  },
) {
  const { data } = await http.post<{ ok: boolean; gate_result: Record<string, unknown> }>(
    `/regression/batches/${jobId}/override`,
    body,
  )
  return data
}