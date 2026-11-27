/**
 * DiffGate 状态枚举：徽标文案 + 颜色规范（分析任务 / 门禁裁决 / 探针行）
 * 见产品 UI 规范；样式类名见 styles/status-tokens.css
 */

import type { JobStatus } from '@/api/types'

export type GateVerdict = 'PASS' | 'BLOCK' | 'PENDING' | 'OVERRIDDEN' | string
export type CoverageProbeVisual = 'covered' | 'uncovered' | 'partial' | 'unprobed' | 'ignored'

export interface StatusToken {
  key: string
  label: string
  labelShort?: string
  color: string
  bg: string
  border: string
  badgeClass: string
  hint?: string
  /** RUNNING 等需呼吸灯 */
  pulse?: boolean
  /** CANCELLED 等可弱化 */
  muted?: boolean
}

const JOB_STATUS_ALIASES: Record<string, string> = {
  debouncing: 'pending',
  superseded: 'cancelled',
}

export const JOB_EXECUTION_TOKENS: Record<string, StatusToken> = {
  pending: {
    key: 'pending',
    label: '排队中',
    color: '#94A3B8',
    bg: 'rgba(148, 163, 184, 0.15)',
    border: '#475569',
    badgeClass: 'dg-badge--job-pending',
    hint: '任务已入队，等待调度器认领。',
  },
  running: {
    key: 'running',
    label: '分析中',
    color: '#38BDF8',
    bg: 'rgba(56, 189, 248, 0.15)',
    border: '#0284C7',
    badgeClass: 'dg-badge--job-running',
    pulse: true,
    hint: '正在拉取 Diff、清洗有效行并构建 AST 影响图。',
  },
  awaiting_probe: {
    key: 'awaiting_probe',
    label: '待探针',
    color: '#FBBF24',
    bg: 'rgba(251, 191, 36, 0.15)',
    border: '#D97706',
    badgeClass: 'dg-badge--job-awaiting-probe',
    hint: '静态影响分析完成，等待测试环境回归与覆盖率回传。',
  },
  completed: {
    key: 'completed',
    label: '已完成',
    color: '#34D399',
    bg: 'rgba(52, 211, 153, 0.15)',
    border: '#059669',
    badgeClass: 'dg-badge--job-completed',
    hint: '数据采集结束，已生成最终门禁裁决。',
  },
  failed: {
    key: 'failed',
    label: '分析失败',
    color: '#F87171',
    bg: 'rgba(248, 113, 113, 0.15)',
    border: '#DC2626',
    badgeClass: 'dg-badge--job-failed',
    hint: 'Git 克隆失败或解析异常，悬停查看错误摘要。',
  },
  timeout: {
    key: 'timeout',
    label: '探针超时',
    color: '#FB923C',
    bg: 'rgba(251, 146, 60, 0.15)',
    border: '#EA580C',
    badgeClass: 'dg-badge--job-timeout',
    hint: '超过设定时间未收到探针报告，可重跑回归采集。',
  },
  env_mismatch: {
    key: 'env_mismatch',
    label: '版本错位',
    color: '#F472B6',
    bg: 'rgba(244, 114, 182, 0.15)',
    border: '#DB2777',
    badgeClass: 'dg-badge--job-env-mismatch',
    hint: '测试环境 Commit 与当前提交不一致，已拒绝合并脏数据。',
  },
  cancelled: {
    key: 'cancelled',
    label: '已取代',
    color: '#64748B',
    bg: 'rgba(100, 116, 139, 0.12)',
    border: '#334155',
    badgeClass: 'dg-badge--job-cancelled',
    muted: true,
    hint: '同分支存在更新的提交，当前旧任务已自动终止。',
  },
}

export const GATE_VERDICT_TOKENS: Record<string, StatusToken> = {
  PASS: {
    key: 'PASS',
    label: 'PASS',
    labelShort: '已放行',
    color: '#4ADE80',
    bg: 'rgba(74, 222, 128, 0.16)',
    border: '#16A34A',
    badgeClass: 'dg-badge--gate-pass',
    hint: '覆盖率达标且无高危/破坏性变更，允许合并发布。',
  },
  BLOCK: {
    key: 'BLOCK',
    label: 'BLOCK',
    labelShort: '已拦截',
    color: '#F87171',
    bg: 'rgba(248, 113, 113, 0.18)',
    border: '#DC2626',
    badgeClass: 'dg-badge--gate-block',
    hint: '命中质量红线，展示拦截原因并开放豁免评估入口。',
  },
  OVERRIDDEN: {
    key: 'OVERRIDDEN',
    label: '豁免',
    labelShort: 'OVERRIDDEN',
    color: '#FACC15',
    bg: 'rgba(250, 204, 21, 0.16)',
    border: '#CA8A04',
    badgeClass: 'dg-badge--gate-overridden',
    hint: '原拦截态经 QA/负责人审批后特批放行，悬停查看审批人与原因。',
  },
  PENDING: {
    key: 'PENDING',
    label: 'PENDING',
    labelShort: '待裁决',
    color: '#94A3B8',
    bg: 'rgba(148, 163, 184, 0.15)',
    border: '#475569',
    badgeClass: 'dg-badge--gate-pending',
    hint: '等待探针或 CI 回传后自动裁决。',
  },
}

export const COVERAGE_PROBE_TOKENS: Record<CoverageProbeVisual, StatusToken> = {
  covered: {
    key: 'covered',
    label: '已覆盖',
    color: '#22C55E',
    bg: 'rgba(34, 197, 94, 0.2)',
    border: '#16A34A',
    badgeClass: 'dg-probe-dot--covered',
    hint: '探针命中且该行已执行。',
  },
  uncovered: {
    key: 'uncovered',
    label: '未覆盖',
    color: '#EF4444',
    bg: 'rgba(239, 68, 68, 0.2)',
    border: '#DC2626',
    badgeClass: 'dg-probe-dot--uncovered',
    hint: '探针已下发但命中为 0，需补充用例。',
  },
  partial: {
    key: 'partial',
    label: '部分分支覆盖',
    color: '#EAB308',
    bg: 'rgba(234, 179, 8, 0.22)',
    border: '#CA8A04',
    badgeClass: 'dg-probe-dot--partial',
    hint: '条件分支仅走了其中一条路（如 if/else、and/or）。',
  },
  unprobed: {
    key: 'unprobed',
    label: '未探针',
    color: '#64748B',
    bg: 'transparent',
    border: '#64748B',
    badgeClass: 'dg-probe-dot--unprobed',
    hint: '尚未收到探针数据。',
  },
  ignored: {
    key: 'ignored',
    label: '已过滤',
    color: '#334155',
    bg: 'transparent',
    border: '#334155',
    badgeClass: 'dg-probe-dot--ignored',
    hint: '注释/空行/import/类型声明等非分母行。',
  },
}

function normJobStatus(status: string | undefined): string {
  const s = (status || 'pending').toLowerCase()
  return JOB_STATUS_ALIASES[s] || s
}

export function jobExecutionToken(status: JobStatus | string | undefined): StatusToken {
  const key = normJobStatus(status)
  return JOB_EXECUTION_TOKENS[key] ?? JOB_EXECUTION_TOKENS.pending
}

export function jobExecutionLabel(status: JobStatus | string | undefined): string {
  return jobExecutionToken(status).label
}

export function jobExecutionBadgeClass(status: JobStatus | string | undefined): string {
  const t = jobExecutionToken(status)
  return `dg-badge dg-badge--job ${t.badgeClass}${t.pulse ? ' dg-badge--pulse' : ''}${t.muted ? ' dg-badge--muted' : ''}`
}

export function gateVerdictToken(gate: GateVerdict | null | undefined): StatusToken {
  const key = (gate || 'PENDING').toUpperCase()
  return GATE_VERDICT_TOKENS[key] ?? GATE_VERDICT_TOKENS.PENDING
}

/** 列表短文案：PASS→已放行，BLOCK→已拦截 */
export function gateVerdictListLabel(gate: GateVerdict | null | undefined): string {
  const t = gateVerdictToken(gate)
  if (gate === 'OVERRIDDEN') return t.label
  if (gate === 'PASS' || gate === 'BLOCK') return t.labelShort ?? t.label
  return t.label
}

/** 详情区主文案：豁免显示「豁免」，其余用大写枚举 */
export function gateVerdictDetailLabel(gate: GateVerdict | null | undefined, gateLabel?: string | null): string {
  if (gateLabel?.trim()) return gateLabel.trim()
  if (gate === 'OVERRIDDEN') return '豁免'
  return (gate || 'PENDING').toUpperCase()
}

export function gateVerdictBadgeClass(gate: GateVerdict | null | undefined): string {
  const t = gateVerdictToken(gate)
  return `dg-badge dg-badge--gate ${t.badgeClass}`
}

export function coverageProbeVisual(
  covered: boolean | null | undefined,
  ignored?: boolean,
  branchPartial?: boolean,
): CoverageProbeVisual {
  if (ignored) return 'ignored'
  if (branchPartial && covered === true) return 'partial'
  if (covered === true) return 'covered'
  if (covered === false) return 'uncovered'
  return 'unprobed'
}

export function coverageProbeToken(
  covered: boolean | null | undefined,
  ignored?: boolean,
  branchPartial?: boolean,
): StatusToken {
  return COVERAGE_PROBE_TOKENS[coverageProbeVisual(covered, ignored, branchPartial)]
}

export function coverageProbeDotClass(
  covered: boolean | null | undefined,
  ignored?: boolean,
  branchPartial?: boolean,
): string {
  return `coverage-probe-chip ${coverageProbeToken(covered, ignored, branchPartial).badgeClass}`
}

export function coverageProbeStateLabel(
  covered: boolean | null | undefined,
  ignored?: boolean,
  branchPartial?: boolean,
): string {
  return coverageProbeToken(covered, ignored, branchPartial).label
}

export function coverageProbeDotTitle(
  covered: boolean | null | undefined,
  ignored?: boolean,
  branchPartial?: boolean,
): string {
  const t = coverageProbeToken(covered, ignored, branchPartial)
  if (t.key === 'partial') return '存在未走到的条件分支'
  return t.hint || t.label
}