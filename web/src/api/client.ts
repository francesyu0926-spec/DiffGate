import axios from 'axios'
import type {
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
  )
  return data
}

export async function triggerRepoAnalysis(id: string) {
  const { data } = await http.post<{ ok: boolean; job_id: string }>(`/repositories/${id}/analyze`)
  return data
}

export interface SystemStatus {
  ast_engine: string
  redis_online: boolean
  use_redis: boolean
  worker_mode: string
  worker_online: number
}

export interface DashboardOverview {
  kpi: {
    avg_coverage: number
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
    coverage: number[]
    threshold: number
  }
  intercept_reasons: { name: string; value: number }[]
  recent_flows: {
    commit: string
    repo: string
    changed_files: number
    api_impact: number
    coverage: number | null
    gate: string
    time: string | null
    job_id: string | null
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
  gate_result: Record<string, unknown>
  cases: {
    method: string
    path: string
    yaml_file: string
    status: string
    duration_ms: number
  }[]
  coverage_lines: {
    file: string
    line: number
    covered: boolean | null
    prefix: string
  }[]
  incremental_coverage_pct: number | null
  changed_lines: number
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