export type JobStatus = 'pending' | 'running' | 'completed' | 'failed'

export type RepoProvider = 'github' | 'gitlab' | 'local'
export type AuthMethod = 'none' | 'token' | 'ssh'

export interface RepoOverviewStats {
  repo_count: number
  indexed_repo_count: number
  analysis_total: number
  high_risk_blocked: number
  avg_analysis_seconds: number
  regression_time_saved_pct: number
  regression_hint: string
}

export interface RepositoryItem {
  id: string
  full_name: string
  provider: RepoProvider
  clone_url: string
  default_branch: string
  description: string | null
  enabled: boolean
  webhook_enabled: boolean
  coverage_threshold: number
  auth_method: AuthMethod
  scan_root: string
  test_suite_id: string | null
  token_configured?: boolean
  ssh_configured?: boolean
  ast_method_count: number
  ast_api_count: number
  last_indexed_at: string | null
  created_at: string | null
  updated_at: string | null
  job_count?: number
}

export interface RepositoryPayload {
  full_name: string
  provider: RepoProvider
  clone_url: string
  default_branch?: string
  description?: string | null
  enabled?: boolean
  webhook_enabled?: boolean
  coverage_threshold?: number
  auth_method?: AuthMethod
  access_token?: string
  ssh_private_key?: string
  scan_root?: string
  test_suite_id?: string | null
}

export interface JobAnalysisStats {
  total: number
  avg_seconds: number
  avg_baseline_apis: number
  avg_impacted_apis: number
  api_convergence_pct: number
  regression_trigger_pct: number
}

export interface JobListItem {
  id: string
  provider: string
  repo: string
  ref: string
  ref_branch: string
  status: JobStatus
  base_sha: string
  head_sha: string
  api_count: number
  changed_files: number
  method_count: number
  trigger_label: string
  created_at: string | null
}

export interface AffectedApi {
  handler: string
  method: string
  path: string
  file: string
  line: number
}

export interface CallPath {
  method: string
  path: string
  chain: string[]
  chain_labels: string[]
  layers: number
}

export interface SuspectFunction {
  qualified_name: string
  file: string
  start_line: number
  end_line: number
  changed_lines: number[]
}

export interface JobDetail {
  id: string
  provider: string
  repo: string
  ref: string
  base_sha: string
  head_sha: string
  status: JobStatus
  affected_apis: { apis: AffectedApi[]; count: number; call_paths?: CallPath[] } | null
  changed_symbols: {
    symbols: string[]
    suspects?: SuspectFunction[]
    line_ranges: { path: string; start: number; end: number }[]
  } | null
  error_message: string | null
  created_at: string | null
}

export interface GraphNode {
  id: string
  label: string
  type: 'api' | 'changed' | 'symbol'
  file?: string
  line?: number
  method?: string | null
  route?: string | null
}

export interface GraphEdge {
  source: string
  target: string
}

export interface JobGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
}