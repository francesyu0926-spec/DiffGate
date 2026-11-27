export type JobStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'debouncing'
  | 'superseded'

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
  webhook_notify_url?: string | null
  notify_webhook_url?: string | null
  notify_policy?: 'off' | 'block_only' | 'always'
  high_risk_paths?: string[] | null
  low_risk_paths?: string[] | null
  high_risk_api_threshold?: number | null
  high_risk_symbol_threshold?: number | null
  allow_self_override?: boolean
  gate_path_rules?: { path_prefix: string; threshold: number; allow_override?: boolean }[] | null
  token_configured?: boolean
  ssh_configured?: boolean
  ast_method_count: number
  ast_api_count: number
  last_indexed_at: string | null
  created_at: string | null
  updated_at: string | null
  job_count?: number
  repo_type?: string
  api_base_prefix?: string
  api_strip_prefix?: string
  linked_repo_ids?: string[] | null
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
  webhook_notify_url?: string | null
  notify_webhook_url?: string | null
  notify_policy?: 'off' | 'block_only' | 'always'
  high_risk_paths?: string[] | null
  low_risk_paths?: string[] | null
  high_risk_api_threshold?: number | null
  high_risk_symbol_threshold?: number | null
  allow_self_override?: boolean
  gate_path_rules?: { path_prefix: string; threshold: number; allow_override?: boolean }[] | null
  repo_type?: string
  api_base_prefix?: string
  api_strip_prefix?: string
  linked_repo_ids?: string[] | null
}

export interface JobAnalysisStats {
  total: number
  avg_seconds: number
  avg_baseline_apis: number
  avg_impacted_apis: number
  api_convergence_pct: number
  regression_trigger_pct: number
  ever_hit_api?: boolean
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
  commit_message?: string | null
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

export interface CrossRepoConsumer {
  consumer_repo: string
  file: string
  line: number
  method: string
  client_path: string
  matched_api: string
  client_kind?: string
}

export interface FullstackImpact {
  engine?: string
  trace_mode?: string
  affected_routes?: {
    route_path: string
    route_name?: string | null
    component_file: string
    component_name?: string
    component_dir?: string
    router_file?: string
  }[]
  affected_pages?: FullstackImpact['affected_routes']
  frontend_api_calls?: {
    method: string
    path: string
    file: string
    line: number
    backend_method?: string
    backend_path?: string
  }[]
  frontend_api_calls_aggregated?: {
    file: string
    file_name: string
    file_dir: string
    lines: number[]
    backend_paths: string[]
    backend_methods: string[]
  }[]
  unresolved_dynamic_calls?: { method: string; path: string; file: string; line: number }[]
  components?: { route: string; file: string; name: string }[]
  matched_api_calls?: {
    method: string
    endpoint: string
    file: string
    file_name: string
    lines: number[]
    lines_display?: string
    first_line?: number
  }[]
  unresolved_calls?: { file: string; lines: number[]; lines_display?: string }[]
  unresolved_count?: number
  changed_frontend_files?: string[]
  stats?: { affected_file_count?: number; route_count?: number; api_call_count?: number }
  index_stats?: { component_files?: number; routes?: number; api_calls?: number }
}

export interface JobDetail {
  id: string
  provider: string
  repo: string
  ref: string
  base_sha: string
  head_sha: string
  status: JobStatus
  affected_apis: {
    apis: AffectedApi[]
    count: number
    call_paths?: CallPath[]
    cross_repo_consumers?: CrossRepoConsumer[]
    cross_repo?: { scanned_repos?: string[]; match_count?: number }
  } | null
  changed_symbols: {
    symbols: string[]
    suspects?: SuspectFunction[]
    line_ranges: { path: string; start: number; end: number }[]
    diff_summary?: {
      python_files: number
      other_files: number
      other_paths?: string[]
    }
    fullstack_impact?: FullstackImpact
  } | null
  gate_result?: {
    changed_files?: number
    changed_lines?: number
    gate?: string
    block_reason_label?: string | null
  } | null
  error_message: string | null
  created_at: string | null
}

export type GraphNodeType = 'api' | 'changed' | 'symbol' | 'frontend'

export interface GraphNode {
  id: string
  label: string
  type: GraphNodeType
  file?: string
  line?: number
  end_line?: number
  method?: string | null
  route?: string | null
}

export interface CodeDiffLine {
  line_no: number | null
  text: string
  kind: 'add' | 'del' | 'ctx'
}

export interface CodeDiffView {
  view: 'diff' | 'source'
  file: string
  start_line: number
  end_line: number
  base_sha: string
  head_sha: string
  lines: CodeDiffLine[]
  highlight_lines: number[]
  hint?: string | null
  source_label?: string | null
  empty_reason?: 'workspace_missing' | 'file_not_found' | 'range_empty' | null
}

export interface GraphEdge {
  source: string
  target: string
}

export interface JobGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
}