<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import CallGraphD3, { type GraphNodePick } from '@/components/CallGraphD3.vue'
import ImpactChainAccordion, { type AccordionDiffPick } from '@/components/ImpactChainAccordion.vue'
import CodeDiffDrawer from '@/components/CodeDiffDrawer.vue'
import { fetchJob, fetchJobGraph, humanizeJobError, refreshJobFullstack, retryJob } from '@/api/client'
import type { CallPath, JobDetail, JobGraph, SuspectFunction } from '@/api/types'
import { cleanRepoRelativePath, splitRepoPath } from '@/utils/repoPath'
import { forceUnlockPageScroll, syncPageScrollLock } from '@/utils/scrollLock'

const props = defineProps<{ id: string }>()
const route = useRoute()
const router = useRouter()

const job = ref<JobDetail | null>(null)
const graph = ref<JobGraph | null>(null)
const loading = ref(false)
let timer: number | undefined
let pollTicks = 0
const POLL_MS = 2500
const MAX_POLL_TICKS = 48

function graphReady(g: JobGraph | null) {
  return Boolean(g?.nodes?.length)
}

function jobHasImpact(j: JobDetail) {
  return (
    (j.changed_symbols?.symbols?.length ?? 0) > 0 ||
    (j.changed_symbols?.suspects?.length ?? 0) > 0 ||
    (j.affected_apis?.apis?.length ?? 0) > 0 ||
    (j.affected_apis?.call_paths?.length ?? 0) > 0
  )
}

async function tryLoadGraph() {
  try {
    const g = await fetchJobGraph(props.id)
    if (graphReady(g)) {
      graph.value = g
      return true
    }
  } catch {
    /* 图数据可能尚未写入，下一轮轮询再试 */
  }
  return false
}

function shouldPoll(): boolean {
  const j = job.value
  if (!j) return pollTicks < MAX_POLL_TICKS
  if (j.status === 'pending' || j.status === 'running' || j.status === 'debouncing') return true
  if (j.status === 'failed') return false
  if (j.status === 'completed') {
    if (graphReady(graph.value)) return false
    if (jobHasImpact(j)) return pollTicks < MAX_POLL_TICKS
    return pollTicks < 8
  }
  return false
}

function reconcilePoll() {
  clearPoll()
  if (!shouldPoll()) return
  timer = window.setInterval(() => {
    pollTicks += 1
    if (pollTicks > MAX_POLL_TICKS) {
      clearPoll()
      return
    }
    void load(true)
  }, POLL_MS)
}

const apis = computed(() => job.value?.affected_apis?.apis ?? [])
const fullstackImpact = computed(() => job.value?.changed_symbols?.fullstack_impact ?? null)
const crossRepoConsumers = computed(() => job.value?.affected_apis?.cross_repo_consumers ?? [])
const frontendPages = computed(() => {
  const norm = fullstackImpact.value?.components
  if (norm?.length) {
    return norm.map((c) => {
      const { dir } = splitRepoPath(c.file)
      return {
        route_path: c.route,
        component_file: c.file,
        component_name: c.name,
        component_dir: dir,
      }
    })
  }
  const raw =
    fullstackImpact.value?.affected_pages ??
    fullstackImpact.value?.affected_routes ??
    []
  const seen = new Set<string>()
  const rows: {
    route_path: string
    component_file: string
    component_name: string
    component_dir: string
    router_file?: string
  }[] = []
  for (const row of raw) {
    const full = cleanRepoRelativePath(row.component_file)
    if (!full || seen.has(full)) continue
    seen.add(full)
    const { name, dir } = splitRepoPath(full)
    rows.push({
      route_path: row.route_path === '—' || String(row.route_path || '').includes('worktrees') ? '—' : row.route_path,
      component_file: full,
      component_name: row.component_name || name,
      component_dir: row.component_dir || dir,
      router_file: row.router_file,
    })
  }
  return rows
})

type AggFrontendCall = {
  file: string
  file_name: string
  file_dir: string
  lines: number[]
  backend_paths: string[]
  backend_methods: string[]
}

const aggregatedFrontendCalls = computed((): AggFrontendCall[] => {
  const matched = fullstackImpact.value?.matched_api_calls
  if (matched?.length) {
    return matched.map((row) => ({
      file: row.file,
      file_name: row.file_name,
      file_dir: splitRepoPath(row.file).dir,
      lines: row.lines,
      backend_paths: [row.endpoint],
      backend_methods: [row.method],
    }))
  }
  const pre = fullstackImpact.value?.frontend_api_calls_aggregated
  if (pre?.length) {
    return pre.map((row) => ({
      ...row,
      file: cleanRepoRelativePath(row.file),
      file_name: row.file_name || splitRepoPath(row.file).name,
      file_dir: row.file_dir || splitRepoPath(row.file).dir,
    }))
  }
  const map = new Map<string, AggFrontendCall>()
  for (const c of fullstackImpact.value?.frontend_api_calls ?? []) {
    if (!c.backend_path) continue
    const full = cleanRepoRelativePath(c.file)
    if (!full) continue
    const { name, dir } = splitRepoPath(full)
    const cur =
      map.get(full) ??
      ({
        file: full,
        file_name: name,
        file_dir: dir,
        lines: [],
        backend_paths: [],
        backend_methods: [],
      } as AggFrontendCall)
    if (c.line && !cur.lines.includes(c.line)) cur.lines.push(c.line)
    if (c.backend_path && !cur.backend_paths.includes(c.backend_path)) cur.backend_paths.push(c.backend_path)
    if (c.backend_method && !cur.backend_methods.includes(c.backend_method.toUpperCase()))
      cur.backend_methods.push(c.backend_method.toUpperCase())
    map.set(full, cur)
  }
  return [...map.values()].map((r) => ({
    ...r,
    lines: [...r.lines].sort((a, b) => a - b),
    backend_paths: [...r.backend_paths].sort(),
    backend_methods: [...r.backend_methods].sort(),
  }))
})

const unresolvedFrontendCalls = computed(() => {
  const groups = fullstackImpact.value?.unresolved_calls
  if (groups?.length) return groups
  return fullstackImpact.value?.unresolved_dynamic_calls ?? []
})

const unresolvedCount = computed(
  () => fullstackImpact.value?.unresolved_count ?? unresolvedFrontendCalls.value.length,
)

const unresolvedFlat = computed(() => {
  const rows: { file: string; line: number }[] = []
  for (const u of unresolvedFrontendCalls.value) {
    const file = cleanRepoRelativePath(
      typeof u.file === 'string' ? u.file : String((u as { file?: string }).file ?? ''),
    )
    if (!file) continue
    const lines = (u as { lines?: number[] }).lines
    if (lines?.length) {
      for (const ln of lines) rows.push({ file, line: ln })
    } else {
      const ln = (u as { line?: number }).line
      if (typeof ln === 'number') rows.push({ file, line: ln })
    }
  }
  return rows
})

/** 左右双表统一可视高度（含表头），保证卡片底边对齐 */
const fullstackTableHeight = 220

function unresolvedFileName(file: string) {
  const parts = file.replace(/\\/g, '/').split('/')
  return parts[parts.length - 1] || file
}

function unresolvedFileDir(file: string) {
  const normalized = file.replace(/\\/g, '/')
  const idx = normalized.lastIndexOf('/')
  if (idx <= 0) return normalized
  return normalized.slice(0, idx)
}

function unresolvedExtBadge(file: string) {
  const name = unresolvedFileName(file)
  const m = name.match(/\.([a-z0-9]+)$/i)
  if (!m) return 'FILE'
  const ext = m[1]!.toUpperCase()
  if (ext.length > 4) return ext.slice(0, 4)
  return ext
}

function openUnresolvedDrawer() {
  unresolvedDrawerOpen.value = true
}

function openUnresolvedAt(file: string, line: number) {
  const { name } = splitRepoPath(file)
  drawerFromUnresolved.value = true
  drawerPick.value = {
    title: name,
    file,
    startLine: line,
    endLine: line,
    nodeType: 'frontend',
  }
  drawerOpen.value = true
  unresolvedDrawerOpen.value = false
}

function onCodeDrawerBackToUnresolved() {
  drawerOpen.value = false
  unresolvedDrawerOpen.value = true
}

const hasFullstackPanel = computed(
  () =>
    frontendPages.value.length > 0 ||
    aggregatedFrontendCalls.value.length > 0 ||
    crossRepoConsumers.value.length > 0,
)

const fullstackBackendTrace = computed(() => {
  const mode = fullstackImpact.value?.trace_mode ?? ''
  return mode === 'backend_api' || mode.includes('backend_api')
})

const fullstackComponentCount = computed(() => frontendPages.value.length)

const fullstackInterfaceCount = computed(() => {
  const paths = new Set<string>()
  for (const row of aggregatedFrontendCalls.value) {
    for (const p of row.backend_paths) paths.add(p)
  }
  if (paths.size > 0) return paths.size
  return apis.value.length
})
const suspects = computed(() => job.value?.changed_symbols?.suspects ?? [])
const symbols = computed(() => job.value?.changed_symbols?.symbols ?? [])

function isApiChainLabel(label: string) {
  return /^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+\//.test(label)
}

function callPathDisplayLayers(row: CallPath & { chain_labels?: string[] }) {
  const labels = row.chain_labels?.length ? row.chain_labels : row.chain ?? []
  if (labels.length > 1) return Math.max(0, labels.length - 1)
  if (typeof row.layers === 'number' && row.layers > 0) return row.layers
  if (labels.length === 1 && isApiChainLabel(labels[0])) return null
  if (typeof row.layers === 'number') return row.layers
  return null
}

const callPathRows = computed(() => {
  const paths = job.value?.affected_apis?.call_paths ?? []
  return paths.map((row) => {
    const chain_labels = row.chain_labels?.length ? row.chain_labels : row.chain ?? []
    return {
      ...row,
      chain_labels,
      display_layers: callPathDisplayLayers({ ...row, chain_labels }),
    }
  })
})

const suspectRows = computed(() => {
  if (suspects.value.length) return suspects.value
  return symbols.value.map((name) => ({
    qualified_name: name,
    file: '—',
    start_line: 0,
    end_line: 0,
    changed_lines: [] as number[],
  }))
})

const suspectSearch = ref('')
const suspectApiOnly = ref(false)
const selectedApiKey = ref<string | null>(null)
const linkHoverApiKey = ref<string | null>(null)
const linkHoverSuspectQname = ref<string | null>(null)
const splitPanePct = ref(45)
const splitRef = ref<HTMLElement | null>(null)
/** 固定表高 + 底部内边距，避免最后一行被圆角容器裁切 */
const impactTableHeight = 392
const suspectTableMaxHeight = 400

function apiRowKey(row: { method?: string; path?: string }) {
  return `${(row.method || 'GET').toUpperCase()} ${row.path ?? ''}`
}

/** 选中接口时左侧只展示该条，避免「已筛」与列表不一致 */
const displayedCallPathRows = computed(() => {
  if (!selectedApiKey.value) return callPathRows.value
  return callPathRows.value.filter((r) => apiRowKey(r) === selectedApiKey.value)
})

/** 筛选后行数很少时左侧表高随内容收缩，避免大块黑空 */
const apiTableLayoutHeight = computed(() => {
  const n = displayedCallPathRows.value.length
  if (selectedApiKey.value && n > 0 && n <= 3) return undefined
  return impactTableHeight
})

const suspectEmptyMinHeight = computed(() => {
  const n = displayedCallPathRows.value.length
  if (selectedApiKey.value && n > 0 && n <= 3) return 260
  return impactTableHeight
})

function chainSymbolsForPath(row: CallPath & { chain_labels?: string[] }) {
  const labels = row.chain_labels?.length ? row.chain_labels : row.chain ?? []
  const syms = new Set<string>()
  for (const item of labels) {
    if (!item || isApiChainLabel(item)) continue
    syms.add(item)
    syms.add(item.split('.').pop() ?? item)
  }
  return syms
}

function suspectRelatesToApiKey(row: SuspectFunction, apiKey: string) {
  const pathRow = callPathRows.value.find((r) => apiRowKey(r) === apiKey)
  if (!pathRow) return false
  const syms = chainSymbolsForPath(pathRow)
  const q = row.qualified_name
  const short = q.split('.').pop() ?? q
  return syms.has(q) || syms.has(short)
}

function suspectRelatesToHoveredApi(row: SuspectFunction) {
  if (!linkHoverApiKey.value) return false
  return suspectRelatesToApiKey(row, linkHoverApiKey.value)
}

function apiRelatesToHoveredSuspect(row: (typeof callPathRows.value)[number]) {
  if (!linkHoverSuspectQname.value) return false
  const syms = chainSymbolsForPath(row)
  const q = linkHoverSuspectQname.value
  const short = q.split('.').pop() ?? q
  return syms.has(q) || syms.has(short)
}

function toggleApiFilter(row: (typeof callPathRows.value)[number]) {
  const key = apiRowKey(row)
  selectedApiKey.value = selectedApiKey.value === key ? null : key
}

function clearApiFilter() {
  selectedApiKey.value = null
}

function onSplitResizerPointerDown(e: PointerEvent) {
  const container = splitRef.value
  if (!container) return
  e.preventDefault()
  const rect = container.getBoundingClientRect()
  const onMove = (ev: PointerEvent) => {
    const x = ev.clientX - rect.left
    const pct = Math.min(62, Math.max(32, (x / rect.width) * 100))
    splitPanePct.value = pct
  }
  const onUp = () => {
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
  }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
}

function shortSuspectName(qualifiedName: string) {
  const parts = qualifiedName.replace(/\\/g, '.').split('.').filter(Boolean)
  if (!parts.length) return qualifiedName
  const method = parts[parts.length - 1]
  const prev = parts.length >= 2 ? parts[parts.length - 2] : ''
  const withCall = method.includes('(') ? method : `${method}()`
  if (prev && /^[A-Z]/.test(prev)) return `${prev}.${withCall}`
  return withCall
}

function callersAbove(graphData: JobGraph, nodeId: string) {
  const ids = new Set(graphData.nodes.map((n) => n.id))
  const keys = new Set([nodeId, nodeId.split('.').pop() ?? nodeId])
  const callers: string[] = []
  for (const e of graphData.edges) {
    const hit =
      keys.has(e.target) ||
      [...keys].some((k) => e.target === k || e.target.endsWith(`.${k}`))
    if (hit && ids.has(e.source)) callers.push(e.source)
  }
  return callers
}

function graphReachesApi(graphData: JobGraph | null, qualifiedName: string) {
  if (!graphData?.nodes.length) return false
  const apiIds = new Set(graphData.nodes.filter((n) => n.type === 'api').map((n) => n.id))
  if (!apiIds.size) return false
  const idSet = new Set(graphData.nodes.map((n) => n.id))
  const seeds = [
    qualifiedName,
    ...graphData.nodes
      .filter((n) => n.id === qualifiedName || n.id.endsWith(`.${qualifiedName.split('.').pop()}`))
      .map((n) => n.id),
  ]
  const q = [...new Set(seeds.filter((s) => idSet.has(s))) ]
  const seen = new Set<string>()
  while (q.length) {
    const cur = q.pop()!
    if (seen.has(cur)) continue
    seen.add(cur)
    if (apiIds.has(cur)) return true
    for (const up of callersAbove(graphData, cur)) q.push(up)
  }
  return false
}

const callPathSymbolSet = computed(() => {
  const set = new Set<string>()
  for (const row of callPathRows.value) {
    const extra = row as CallPath & { chain_full?: string[] }
    for (const item of [...(row.chain ?? []), ...(row.chain_labels ?? []), ...(extra.chain_full ?? [])]) {
      if (!item || /^(GET|POST|PUT|PATCH|DELETE)\s+\//.test(item)) continue
      set.add(item)
      set.add(item.split('.').pop() ?? item)
    }
  }
  return set
})

function suspectHitsApi(row: SuspectFunction) {
  const q = row.qualified_name
  const short = q.split('.').pop() ?? q
  if (callPathSymbolSet.value.has(q) || callPathSymbolSet.value.has(short)) return true
  return graphReachesApi(graph.value, q)
}

type SuspectTableRow = SuspectFunction & {
  displayName: string
  locationLine: string
  pathDir: string
  pathFile: string
  lineLabel: string
  hitsApi: boolean
}

const suspectTableRows = computed(() => {
  const q = suspectSearch.value.trim().toLowerCase()
  const rows: SuspectTableRow[] = suspectRows.value.map((row) => {
    const { full, dir, name } = splitRepoPath(row.file !== '—' ? row.file : '')
    const lineLabel =
      row.start_line > 0
        ? `L${row.start_line}${row.end_line > row.start_line ? `-${row.end_line}` : ''}`
        : ''
    const pathFile = name || (row.file !== '—' ? row.file : '—')
    const pathDir = dir ? `${dir}/` : ''
  return {
    ...row,
    displayName: shortSuspectName(row.qualified_name),
    locationLine:
      full && row.start_line
        ? `${full} · L${row.start_line}-${row.end_line}`
        : full || '—',
    pathDir,
    pathFile,
    lineLabel,
    hitsApi: suspectHitsApi(row),
  }
  })
  return rows.filter((row) => {
    if (suspectApiOnly.value && !row.hitsApi) return false
    if (selectedApiKey.value && !suspectRelatesToApiKey(row, selectedApiKey.value)) return false
    if (!q) return true
    return (
      row.qualified_name.toLowerCase().includes(q) ||
      row.displayName.toLowerCase().includes(q) ||
      row.file.toLowerCase().includes(q)
    )
  })
})

const suspectTableLayoutHeight = computed(() => {
  const n = suspectTableRows.value.length
  if (!n) return suspectTableMaxHeight
  const estimated = 44 + n * 58
  return Math.min(suspectTableMaxHeight, Math.max(estimated, 168))
})

function isDirectApiChain(row: CallPath & { chain_labels?: string[] }) {
  const labels = row.chain_labels?.length ? row.chain_labels : row.chain ?? []
  return !labels.some((l) => l && !isApiChainLabel(l))
}

function formatCallChainShort(row: CallPath & { chain_labels?: string[] }) {
  const labels = row.chain_labels?.length ? row.chain_labels : row.chain ?? []
  const nonApi = labels.filter((l) => l && !isApiChainLabel(l))
  if (!nonApi.length) return ''
  const text = nonApi
    .map((l) => {
      const short = l.split('.').pop() ?? l
      return short.includes('(') ? short : `${short}()`
    })
    .join(' → ')
  if (text.length > 56) return `${text.slice(0, 53)}…`
  return text
}

function callPathTooltip(row: (typeof callPathRows.value)[number]) {
  const chain = formatCallChain(row)
  if (row.display_layers == null) return chain
  return `${chain}\n传播跳数: ${row.display_layers}`
}

function impactApiRowClass({ row }: { row: (typeof callPathRows.value)[number] }) {
  const classes: string[] = []
  const key = apiRowKey(row)
  if (selectedApiKey.value === key) classes.push('impact-row--selected')
  if (linkHoverApiKey.value === key || apiRelatesToHoveredSuspect(row)) classes.push('impact-row--linked')
  return classes.join(' ')
}

function impactSuspectRowClass({ row }: { row: SuspectTableRow }) {
  const classes: string[] = []
  if (selectedApiKey.value && suspectRelatesToApiKey(row, selectedApiKey.value)) {
    classes.push('impact-row--linked')
  }
  if (
    linkHoverSuspectQname.value === row.qualified_name ||
    suspectRelatesToHoveredApi(row)
  ) {
    classes.push('impact-row--linked')
  }
  return classes.join(' ')
}

const changedIds = computed(() => symbols.value)

const drawerOpen = ref(false)
const unresolvedDrawerOpen = ref(false)
const drawerFromUnresolved = ref(false)
const drawerPick = ref<{
  title: string
  file: string
  startLine: number
  endLine: number
  nodeType: GraphNodePick['type']
  highlight?: string
  impactPath?: string
} | null>(null)

watch(drawerOpen, (open) => {
  if (!open) drawerFromUnresolved.value = false
})

watch(
  [drawerOpen, unresolvedDrawerOpen],
  ([diffOpen, unresolvedOpen]) => {
    syncPageScrollLock(diffOpen || unresolvedOpen)
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  forceUnlockPageScroll()
})

watch([selectedApiKey, () => suspectTableRows.value.length], () => {
  if (selectedApiKey.value && suspectTableRows.value.length === 0) {
    splitPanePct.value = Math.min(68, Math.max(splitPanePct.value, 58))
  }
})

function drawerEndLine(pick: GraphNodePick) {
  const line = pick.line ?? 1
  if (pick.type === 'api') {
    const graphEnd =
      pick.end_line && pick.end_line > line ? pick.end_line : line + 32
    return Math.min(Math.max(graphEnd, line + 8), line + 40)
  }
  const span = 56
  const maxSpan = 120
  const graphSpan = pick.end_line && pick.end_line > line ? pick.end_line - line : span
  const useSpan = Math.min(Math.max(graphSpan, 12), maxSpan)
  return line + useSpan
}

function formatImpactPath(pick: GraphNodePick, title: string) {
  if (pick.type !== 'api' || !pick.calleeHints?.length) return undefined
  const chain = pick.calleeHints.map((id) => {
    const short = id.split('.').pop() ?? id
    return `${short}() [变更]`
  })
  return `波及路径: ${chain.join(' → ')} → ${title}`
}

function formatCallChain(row: CallPath & { chain_labels?: string[] }) {
  const labels = row.chain_labels?.length ? row.chain_labels : row.chain ?? []
  return labels.join(' → ')
}

function httpPillClass(method: string | undefined) {
  const m = (method || 'GET').toUpperCase()
  if (m === 'POST') return 'http-pill--post'
  if (m === 'PUT' || m === 'PATCH') return 'http-pill--put'
  if (m === 'DELETE') return 'http-pill--delete'
  return 'http-pill--get'
}

function openDrawerFromFrontendAgg(row: AggFrontendCall, line?: number) {
  const ln = line ?? row.lines[0]
  const file = cleanRepoRelativePath(row.file)
  if (!file || !ln) return
  drawerFromUnresolved.value = false
  drawerPick.value = {
    title: row.file_name,
    file,
    startLine: ln,
    endLine: ln,
    nodeType: 'frontend',
    impactPath: row.backend_paths.length ? `命中 ${row.backend_paths.join('、')}` : undefined,
  }
  drawerOpen.value = true
}

function openDrawerFromNode(pick: GraphNodePick) {
  if (!pick.file?.trim() || pick.line == null || pick.line < 1) return
  drawerFromUnresolved.value = false
  const title =
    pick.type === 'api' && pick.method && pick.route
      ? `${pick.method.toUpperCase()} ${pick.route}`
      : pick.label
  drawerPick.value = {
    title,
    file: cleanRepoRelativePath(pick.file),
    startLine: pick.line,
    endLine: drawerEndLine(pick),
    nodeType: pick.type,
    highlight: pick.calleeHints?.join(','),
    impactPath: formatImpactPath(pick, title),
  }
  drawerOpen.value = true
}

function openDrawerFromSuspect(row: SuspectFunction & { displayName?: string }) {
  const file = cleanRepoRelativePath(row.file)
  if (!file || row.file === '—') return
  let start = row.start_line
  let end = row.end_line
  if ((!start || start < 1) && row.changed_lines?.length) {
    const lines = [...row.changed_lines].sort((a, b) => a - b)
    start = lines[0]!
    end = lines[lines.length - 1]!
  }
  if (!start || start < 1) return
  if (!end || end < start) end = start
  drawerFromUnresolved.value = false
  drawerPick.value = {
    title: row.displayName ?? shortSuspectName(row.qualified_name),
    file,
    startLine: start,
    endLine: end,
    nodeType: 'changed',
  }
  drawerOpen.value = true
}

function onAccordionViewDiff(pick: AccordionDiffPick) {
  drawerFromUnresolved.value = false
  drawerPick.value = {
    title: pick.title,
    file: pick.file,
    startLine: pick.startLine,
    endLine: pick.endLine,
    nodeType: pick.nodeType ?? 'changed',
  }
  drawerOpen.value = true
}

function openDrawerFromCallPath(row: (typeof callPathRows.value)[number]) {
  const api = apis.value.find((a) => a.path === row.path && a.method === row.method)
  let file = api?.file ? cleanRepoRelativePath(api.file) : ''
  let line = api?.line ?? 0
  if (!file || line < 1) {
    const method = (row.method || 'GET').toUpperCase()
    const node = graph.value?.nodes?.find(
      (n) =>
        n.type === 'api' &&
        n.route === row.path &&
        (n.method || 'GET').toUpperCase() === method,
    )
    if (node?.file && node.line) {
      file = cleanRepoRelativePath(node.file)
      line = node.line
    }
  }
  if (!file || line < 1) return
  drawerFromUnresolved.value = false
  drawerPick.value = {
    title: `${row.method} ${row.path}`,
    file,
    startLine: line,
    endLine: line + 24,
    nodeType: 'api',
  }
  drawerOpen.value = true
}

const STATUS_LABEL: Record<string, string> = {
  pending: '排队中',
  running: '分析中',
  debouncing: '合并推送',
  superseded: '已取代',
  completed: '已完成',
  failed: '失败',
}

const statusLabel = computed(() => {
  const s = job.value?.status
  if (!s) return '—'
  return STATUS_LABEL[s] ?? s
})

const jobInProgress = computed(() => {
  const s = job.value?.status
  return s === 'pending' || s === 'running' || s === 'debouncing'
})

const showAnalyzingUi = computed(() => (loading.value && !job.value) || jobInProgress.value)

const impactApiTableLoading = computed(
  () => showAnalyzingUi.value && displayedCallPathRows.value.length === 0,
)
const impactSuspectTableLoading = computed(
  () => showAnalyzingUi.value && suspectTableRows.value.length === 0,
)

const impactApiEmptySettled = computed(
  () => !impactApiTableLoading.value && displayedCallPathRows.value.length === 0,
)

const suspectEmptyMinHeightResolved = computed(() => {
  if (impactApiEmptySettled.value) return 200
  return suspectEmptyMinHeight.value
})

const isZeroTopLevelApiImpact = computed(
  () =>
    job.value?.status === 'completed' &&
    apis.value.length === 0 &&
    callPathRows.value.length === 0 &&
    !selectedApiKey.value,
)

const impactApiEmptyCopy = computed(() => {
  if (selectedApiKey.value) {
    return {
      title: '当前筛选下无匹配接口',
      hint: '可点击筛选标签清除条件，查看全部顶层 API。',
    }
  }
  if (isZeroTopLevelApiImpact.value) {
    return {
      title: '本次变更未波及顶层 API',
      hint: '变更仅涉及底层函数，系统未检测到受影响的接口请求。',
    }
  }
  return {
    title: '暂无受影响接口',
    hint: '分析完成后将列出顶层 API 与追溯链路',
  }
})

const analyzingHeadline = computed(() => {
  const s = job.value?.status
  if (s === 'pending') return '排队中，等待分析引擎执行'
  if (s === 'debouncing') return '合并同分支推送，即将开始分析'
  if (s === 'running') return '正在分析变更影响'
  return '加载任务详情…'
})

const analyzingDetail = computed(() => {
  const s = job.value?.status
  if (s === 'pending') return '克隆仓库、解析 Diff 与 AST 将在后台自动进行，页面约每 2.5 秒刷新状态。'
  if (s === 'running') return '正在构建调用链图谱与全栈追溯，完成后将自动展示拓扑与接口列表。'
  return '请稍候…'
})

function shortSha(sha: string) {
  return sha?.slice(0, 8) ?? '—'
}

const commitRange = computed(() => {
  const j = job.value
  if (!j?.base_sha || !j?.head_sha) return '—'
  return `${shortSha(j.base_sha)} → ${shortSha(j.head_sha)}`
})

const commitRangeCompact = computed(() => {
  const j = job.value
  if (!j?.base_sha || !j?.head_sha) return '—'
  return `${j.base_sha.slice(0, 7)} → ${j.head_sha.slice(0, 7)}`
})

const branchDisplayName = computed(() => {
  const ref = job.value?.ref
  if (!ref) return '—'
  if (ref.startsWith('refs/heads/')) return ref.slice('refs/heads/'.length)
  const slash = ref.lastIndexOf('/')
  return slash >= 0 ? ref.slice(slash + 1) : ref
})

const metaChangedLineCount = computed(() => {
  const fromGate = job.value?.gate_result?.changed_lines
  if (fromGate != null && fromGate >= 0) return fromGate
  const ranges = job.value?.changed_symbols?.line_ranges ?? []
  let total = 0
  for (const block of ranges) {
    if (!block || typeof block !== 'object') continue
    const start = Number(block.start ?? 0)
    const end = Number(block.end ?? start)
    if (start > 0) total += Math.max(1, end - start + 1)
  }
  return total
})

const isEmptyImpact = computed(() => {
  const j = job.value
  return Boolean(j && j.status === 'completed' && !jobHasImpact(j))
})

const emptyImpactNotice = computed(() => {
  const j = job.value
  if (!isEmptyImpact.value || !j) return null
  const ds = j.changed_symbols?.diff_summary
  const range = commitRange.value
  if (ds && ds.python_files === 0 && ds.other_files > 0) {
    return `分析已完成（${range}）。本次 diff 无 .py 变更，仅有 ${ds.other_files} 个非 Python 文件，无法生成 AST 影响面。`
  }
  if (ds && ds.python_files === 0 && ds.other_files === 0) {
    return `分析已完成（${range}）。对比范围内无文件差异。`
  }
  return `分析已完成（${range}），但未检测到可映射的 Python 变更行。`
})

const graphEmptyTitle = computed(() => {
  if (showAnalyzingUi.value) return '正在生成调用链拓扑…'
  return isEmptyImpact.value ? '本次无可展示的调用链拓扑' : '暂无调用链子图'
})

const graphEmptyDesc = computed(() => {
  if (showAnalyzingUi.value) return analyzingDetail.value
  if (job.value?.status === 'completed' && showTopologyCompactEmpty.value) {
    return ''
  }
  if (job.value?.status === 'completed') return '当前任务未生成可展示的调用链子图'
  if (!isEmptyImpact.value) return '任务完成后生成变更影响拓扑'
  const ds = job.value?.changed_symbols?.diff_summary
  if (ds && ds.python_files === 0) {
    return '本次提交仅涉及非 Python 文件或无函数级逻辑变更，系统已自动判定为零接口风险。'
  }
  return '未在变更行中定位到可分析的 Python 符号。'
})

const showZeroRiskAutoPass = computed(() => isEmptyImpact.value)

/** 已完成、有底层变更但无 API/调用链：拓扑区折叠为轻量提示条 */
const showTopologyCompactEmpty = computed(() => {
  if (showAnalyzingUi.value) return false
  if (job.value?.status !== 'completed') return false
  if (graphReady(graph.value)) return false
  if (callPathRows.value.length > 0 || apis.value.length > 0) return false
  return true
})

const jobErrorText = computed(() => humanizeJobError(job.value?.error_message))
const retryLoading = ref(false)

async function onRetryJob() {
  if (retryLoading.value) return
  retryLoading.value = true
  try {
    await retryJob(props.id)
    graph.value = null
    await load(true)
    await tryLoadGraph()
  } finally {
    retryLoading.value = false
  }
}

function goRegression() {
  void router.push({ name: 'regression', query: { job: props.id } })
}

function openCodeFromRouteQuery() {
  const rawFile = route.query.file
  if (typeof rawFile !== 'string' || !rawFile.trim()) return
  const file = cleanRepoRelativePath(rawFile)
  if (!file) return
  const startRaw = route.query.start ?? route.query.start_line
  const endRaw = route.query.end ?? route.query.end_line
  const start = Number(startRaw ?? 1)
  const end = Number(endRaw ?? start)
  const startLine = Number.isFinite(start) && start > 0 ? Math.floor(start) : 1
  const endLine = Number.isFinite(end) && end >= startLine ? Math.floor(end) : startLine
  const { name } = splitRepoPath(file)
  drawerFromUnresolved.value = false
  drawerPick.value = {
    title: name,
    file,
    startLine,
    endLine,
    nodeType: 'changed',
  }
  drawerOpen.value = true
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    job.value = await fetchJob(props.id)
    if (job.value.status === 'completed') {
      const apiCount = job.value.affected_apis?.count ?? 0
      const fs = job.value.changed_symbols?.fullstack_impact
      const feCalls = fs?.frontend_api_calls?.length ?? 0
      const needRefresh =
        apiCount > 0 &&
        (!feCalls || !fs?.frontend_api_calls_aggregated?.length || String(fs?.affected_routes?.[0]?.component_file || '').includes('worktrees'))
      if (needRefresh) {
        try {
          await refreshJobFullstack(props.id)
          job.value = await fetchJob(props.id)
          graph.value = null
        } catch {
          /* 仍显示后端拓扑 */
        }
      }
      await tryLoadGraph()
    }
    if (job.value.status === 'failed') {
      clearPoll()
      return
    }
    reconcilePoll()
    openCodeFromRouteQuery()
  } finally {
    if (!silent) loading.value = false
  }
}

function clearPoll() {
  if (timer) window.clearInterval(timer)
  timer = undefined
}

function resetForJob() {
  clearPoll()
  pollTicks = 0
  job.value = null
  graph.value = null
}

watch(
  () => props.id,
  () => {
    resetForJob()
    void load()
  },
)

watch(
  () => [route.query.file, route.query.start, route.query.end] as const,
  () => {
    if (job.value) openCodeFromRouteQuery()
  },
)

onMounted(() => {
  void load()
})

onUnmounted(clearPoll)
</script>

<template>
  <div
    v-loading="loading && !job"
    class="page job-detail-page"
    :class="{ 'job-detail-page--busy': showAnalyzingUi }"
  >
    <div class="job-page-head">
      <el-page-header class="job-page-header" @back="$router.push('/analysis')">
        <template #content>
          <span class="mono job-page-title">{{ job?.repo ?? props.id }}</span>
        </template>
      </el-page-header>
      <button
        v-if="job?.status === 'completed'"
        type="button"
        class="job-regression-cta text-none"
        @click="goRegression"
      >
        查看精准回归
        <span class="job-regression-cta__arrow" aria-hidden="true">→</span>
      </button>
    </div>

    <div v-if="showAnalyzingUi" class="job-analyzing-banner mb" role="status" aria-live="polite">
      <span class="job-analyzing-banner__spinner mdi mdi-loading" aria-hidden="true" />
      <div class="job-analyzing-banner__body">
        <p class="job-analyzing-banner__title">{{ analyzingHeadline }}</p>
        <p class="job-analyzing-banner__sub">{{ analyzingDetail }}</p>
      </div>
    </div>

    <div
      class="job-meta-strip"
      :class="{ 'job-meta-strip--muted': showAnalyzingUi }"
      role="group"
      aria-label="任务摘要"
    >
      <span
        class="job-status-badge job-meta-strip__status"
        :class="[
          job?.status ? `job-status-badge--${job.status}` : 'job-status-badge--pending',
          showAnalyzingUi && 'job-status-badge--live',
        ]"
      >
        <span
          v-if="job?.status === 'completed'"
          class="mdi mdi-check job-status-badge__check"
          aria-hidden="true"
        />
        {{ statusLabel }}
      </span>
      <span class="job-meta-strip__sep" aria-hidden="true" />
      <span class="job-meta-strip__part">
        <span class="job-meta-strip__label">影响 API</span>
        <span class="job-meta-strip__colon" aria-hidden="true">：</span>
        <span class="job-meta-strip__num mono">{{ apis.length }}</span>
        <span class="job-meta-strip__unit">个</span>
      </span>
      <span class="job-meta-strip__sep" aria-hidden="true" />
      <span class="job-meta-strip__part">
        <span class="job-meta-strip__label">变更行号</span>
        <span class="job-meta-strip__colon" aria-hidden="true">：</span>
        <span class="job-meta-strip__num mono">{{ metaChangedLineCount }}</span>
        <span class="job-meta-strip__unit">处</span>
      </span>
      <span class="job-meta-strip__sep" aria-hidden="true" />
      <span class="job-meta-strip__part job-meta-strip__part--branch">
        <span class="job-meta-strip__label">分支</span>
        <span class="job-meta-strip__colon" aria-hidden="true">：</span>
        <span class="job-meta-strip__branch">{{ branchDisplayName }}</span>
        <span class="job-meta-strip__range mono" :title="commitRange">({{ commitRangeCompact }})</span>
      </span>
    </div>

    <v-alert
      v-if="job?.status === 'failed' && job?.error_message"
      type="error"
      variant="tonal"
      prominent
      border="start"
      class="job-fail-alert mb-4"
    >
      <div class="job-fail-alert__text">{{ jobErrorText }}</div>
      <div class="job-fail-alert__actions">
        <v-btn
          size="small"
          variant="flat"
          color="primary"
          class="text-none"
          :loading="retryLoading"
          prepend-icon="mdi-refresh"
          @click="onRetryJob"
        >
          重新分析
        </v-btn>
        <v-btn
          size="small"
          variant="text"
          color="primary"
          class="text-none"
          @click="router.push('/repositories')"
        >
          检查仓库凭据
        </v-btn>
      </div>
    </v-alert>
    <div v-else-if="emptyImpactNotice" class="job-tonal-alert mb" role="status">
      <span class="job-tonal-alert__icon mdi mdi-information-outline" aria-hidden="true" />
      <p class="job-tonal-alert__text">{{ emptyImpactNotice }}</p>
      <aside v-if="showZeroRiskAutoPass" class="job-tonal-alert__aside">
        <span class="job-pass-badge">质量门禁自动放行 (PASS)</span>
        <span class="job-pass-sub">非业务代码变更，已跳过冗余回归</span>
      </aside>
    </div>

    <section v-if="hasFullstackPanel" class="job-detail-block job-detail-block--fullstack">
      <header class="fs-module-head">
        <div class="fs-module-head__main">
          <div class="fs-module-head__title-row">
            <span class="fs-module-head__accent" aria-hidden="true" />
            <v-icon class="fs-module-head__glyph" icon="mdi-layers-triple-outline" size="18" aria-hidden="true" />
            <h3 class="fs-module-head__title">全栈影响面</h3>
          </div>
          <p v-if="fullstackBackendTrace" class="fs-module-head__banner" role="note">
            <span class="mdi mdi-information-outline fs-module-head__banner-icon" aria-hidden="true" />
            <span class="fs-module-head__banner-text">
              条件触发：本次变更仅涉及后端，通过 API 反查关联前端组件。
            </span>
          </p>
          <p v-else class="fs-module-head__desc">
            展示受影响前端组件及其对后端 API 的调用命中。
          </p>
        </div>
        <p
          v-if="fullstackComponentCount > 0 || fullstackInterfaceCount > 0"
          class="fs-module-head__stats"
        >
          共匹配到
          <strong>{{ fullstackComponentCount }}</strong>
          个组件、
          <strong>{{ fullstackInterfaceCount }}</strong>
          个接口
        </p>
      </header>
      <div
        v-if="frontendPages.length || aggregatedFrontendCalls.length"
        class="fs-module-body"
      >
      <el-row :gutter="16" class="fullstack-cols">
        <el-col :span="12">
          <div class="job-panel job-panel--table fullstack-panel-half">
            <div class="fs-panel-head fs-panel-head--solo">
              <p class="fs-panel-head__title">受波及前端页面 / 组件</p>
            </div>
            <el-table
              :data="frontendPages"
              size="small"
              empty-text="暂无前端页面波及"
              :height="fullstackTableHeight"
              class="job-click-table fullstack-table"
            >
              <el-table-column label="路由" width="80">
                <template #default="{ row }">
                  <span class="fs-route mono">{{
                    row.route_path === '—' ? 'SPA' : row.route_path
                  }}</span>
                </template>
              </el-table-column>
              <el-table-column label="组件" min-width="160">
                <template #default="{ row }">
                  <div class="fs-path-cell">
                    <span class="fs-file-name">{{ row.component_name }}</span>
                    <span v-if="row.component_dir" class="fs-file-dir">{{ row.component_dir }}/</span>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-col>
        <el-col :span="12">
          <div class="job-panel job-panel--table fullstack-panel-half">
            <div class="fs-panel-head">
              <p class="fs-panel-head__title">前端接口调用点明细</p>
              <button
                v-if="unresolvedCount > 0"
                type="button"
                class="fs-unresolved-pill"
                title="点击查看未解析动态请求详情"
                @click="openUnresolvedDrawer"
              >
                <span class="mdi mdi-alert-circle-outline" aria-hidden="true" />
                未解析动态请求: {{ unresolvedCount }}
              </button>
            </div>
            <el-table
              :data="aggregatedFrontendCalls"
              size="small"
              empty-text="暂无命中受影响 API 的调用"
              :height="fullstackTableHeight"
              class="job-click-table fullstack-table"
              @row-click="(row: AggFrontendCall) => openDrawerFromFrontendAgg(row)"
            >
              <el-table-column label="组件" min-width="140">
                <template #default="{ row }">
                  <div class="fs-path-cell">
                    <span class="fs-file-name">{{ row.file_name }}</span>
                    <span v-if="row.file_dir" class="fs-file-dir">{{ row.file_dir }}/</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="命中接口" min-width="120">
                <template #default="{ row }">
                  <div class="fs-hit-cell">
                    <span
                      v-for="(p, idx) in row.backend_paths"
                      :key="`${p}-${idx}`"
                      class="http-pill fs-api-pill fs-http-pill mono"
                    >{{ (row.backend_methods[idx] || row.backend_methods[0] || 'GET').toUpperCase() }} {{ p }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="行号" width="112" align="right">
                <template #default="{ row }">
                  <div class="fs-lines">
                    <button
                      v-for="ln in row.lines"
                      :key="ln"
                      type="button"
                      class="fs-line-text mono"
                      @click.stop="openDrawerFromFrontendAgg(row, ln)"
                    >
                      L{{ ln }}
                    </button>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-col>
      </el-row>
      </div>
      <div v-if="crossRepoConsumers.length" class="job-panel job-panel--table mt-3">
        <p class="text-caption text-medium-emphasis mb-2">跨仓 HTTP Client 消费方</p>
        <el-table :data="crossRepoConsumers" size="small" max-height="160">
          <el-table-column prop="consumer_repo" label="仓库" min-width="140" show-overflow-tooltip />
          <el-table-column prop="matched_api" label="命中 API" min-width="120" show-overflow-tooltip />
          <el-table-column prop="file" label="文件" min-width="120" show-overflow-tooltip />
          <el-table-column prop="line" label="行" width="56" />
        </el-table>
      </div>
    </section>

    <section class="job-detail-block">
      <ImpactChainAccordion
        :job-id="props.id"
        :call-paths="callPathRows"
        :apis="apis"
        :graph="graph"
        :fullstack="fullstackImpact ?? undefined"
        :suspects="suspects"
        :changed-ids="changedIds"
        panel-title="变更影响拓扑"
        :empty-title="graphEmptyTitle"
        :empty-desc="graphEmptyDesc"
        :processing="showAnalyzingUi"
        :compact-empty="showTopologyCompactEmpty"
        compact-empty-text="本次变更无涉及调用链，暂无拓扑图。"
        @view-diff="onAccordionViewDiff"
      >
        <template #graph>
          <CallGraphD3
            class="impact-accordion-graph-slot"
            :data="graph"
            :changed-ids="changedIds"
            panel-title="D3 拓扑（实验）"
            :empty-title="graphEmptyTitle"
            :empty-desc="graphEmptyDesc"
            :processing="showAnalyzingUi"
            @node-pick="openDrawerFromNode"
          />
        </template>
      </ImpactChainAccordion>
    </section>

    <section
      ref="splitRef"
      class="lists job-detail-tables impact-split"
      :class="{ 'job-detail-tables--waiting': showAnalyzingUi }"
    >
      <div
        class="impact-split__pane"
        :class="{ 'impact-split__pane--api-empty': impactApiEmptySettled }"
        :style="{ flexBasis: `${splitPanePct}%` }"
      >
        <div class="impact-split__head">
          <h3 class="job-section__title job-section__title--tight">受影响顶层接口</h3>
          <span v-if="selectedApiKey" class="impact-filter-chip" role="status">
            <span class="impact-filter-chip__label">已筛 · {{ selectedApiKey }}</span>
            <button
              type="button"
              class="impact-filter-chip__close"
              title="清除接口筛选"
              aria-label="清除接口筛选"
              @click="clearApiFilter"
            >
              <span class="mdi mdi-close" aria-hidden="true" />
            </button>
          </span>
        </div>
        <div
          class="job-panel job-panel--table impact-table-panel"
          :class="{
            'impact-table-panel--loading': impactApiTableLoading,
            'impact-table-panel--empty': !impactApiTableLoading && !displayedCallPathRows.length,
          }"
        >
          <div
            v-if="impactApiTableLoading"
            class="impact-table-skeleton"
            :style="{ minHeight: `${impactTableHeight}px` }"
            role="status"
            aria-live="polite"
            aria-label="正在加载受影响接口列表"
          >
            <div class="impact-table-skeleton__head impact-table-cols" aria-hidden="true">
              <span class="impact-table-skeleton__th">方法</span>
              <span class="impact-table-skeleton__th">接口</span>
              <span class="impact-table-skeleton__th">调用链</span>
            </div>
            <div class="impact-table-skeleton__body">
              <div v-for="row in 6" :key="row" class="impact-table-skeleton__row impact-table-cols">
                <span class="impact-table-skeleton__cell impact-table-skeleton__cell--center">
                  <span class="impact-skel-bar impact-skel-bar--pill" />
                </span>
                <span class="impact-table-skeleton__cell">
                  <span class="impact-skel-bar" />
                </span>
                <span class="impact-table-skeleton__cell">
                  <span class="impact-skel-bar impact-skel-bar--mid" />
                </span>
              </div>
            </div>
          </div>
          <div v-else-if="impactApiEmptySettled" class="impact-api-empty-panel" role="status">
            <div
              class="impact-empty impact-empty--card"
              :class="{ 'impact-empty--safe': isZeroTopLevelApiImpact }"
            >
              <span class="impact-empty__icon-wrap" aria-hidden="true">
                <span
                  class="mdi impact-empty__icon"
                  :class="isZeroTopLevelApiImpact ? 'mdi-shield-check-outline' : 'mdi-api-off'"
                />
              </span>
              <p class="impact-empty__title">{{ impactApiEmptyCopy.title }}</p>
              <p class="impact-empty__hint">{{ impactApiEmptyCopy.hint }}</p>
            </div>
          </div>
          <el-table
            v-else
            :data="displayedCallPathRows"
            size="small"
            :stripe="!selectedApiKey"
            :height="apiTableLayoutHeight ?? impactTableHeight"
            class="job-click-table impact-api-table impact-table-scroll"
            :class="{ 'impact-api-table--compact': apiTableLayoutHeight == null }"
            :row-class-name="impactApiRowClass"
            @row-click="toggleApiFilter"
          >
            <el-table-column prop="method" label="方法" width="15%" align="center" header-align="center">
              <template #default="{ row }">
                <span class="http-pill" :class="httpPillClass(row.method)">{{ row.method }}</span>
              </template>
            </el-table-column>
            <el-table-column label="接口" width="45%" header-align="left" show-overflow-tooltip>
              <template #default="{ row }">
                <button
                  type="button"
                  class="impact-api-path mono"
                  :title="`查看 ${row.method} ${row.path} 源码`"
                  @click.stop="openDrawerFromCallPath(row)"
                >
                  {{ row.path }}
                </button>
              </template>
            </el-table-column>
            <el-table-column label="调用链" width="40%" header-align="left" show-overflow-tooltip>
              <template #default="{ row }">
                <el-tooltip
                  :content="callPathTooltip(row)"
                  placement="top"
                  :show-after="280"
                  popper-class="impact-chain-tooltip"
                >
                  <span
                    v-if="isDirectApiChain(row)"
                    class="chain chain--direct"
                    @mouseenter="linkHoverApiKey = apiRowKey(row)"
                    @mouseleave="linkHoverApiKey = null"
                  >
                    <span class="chain__direct-glyph" aria-hidden="true">↳</span>
                    直达
                  </span>
                  <span
                    v-else
                    class="chain chain--short chain--fn"
                    @mouseenter="linkHoverApiKey = apiRowKey(row)"
                    @mouseleave="linkHoverApiKey = null"
                  >
                    {{ formatCallChainShort(row) }}
                  </span>
                </el-tooltip>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
      <div
        class="impact-split__resizer"
        role="separator"
        aria-orientation="vertical"
        aria-label="调整左右面板宽度"
        title="拖拽调整宽度"
        @pointerdown="onSplitResizerPointerDown"
      />
      <div
        class="impact-split__pane impact-split__pane--right"
        :class="{ 'impact-split__pane--suspect-fit': suspectTableRows.length > 0 }"
        :style="{ flexBasis: `${100 - splitPanePct}%` }"
      >
        <div class="impact-split__head impact-split__head--suspect">
          <h3 class="job-section__title job-section__title--tight">初始变更函数明细</h3>
        </div>
        <div class="suspect-toolbar suspect-toolbar--below-title">
          <div class="suspect-toolbar__search-wrap">
            <span class="mdi mdi-magnify suspect-toolbar__search-icon" aria-hidden="true" />
            <input
              v-model="suspectSearch"
              type="search"
              class="suspect-toolbar__search"
              placeholder="搜索函数或文件名"
              aria-label="搜索变更函数"
            />
          </div>
          <button
            type="button"
            class="suspect-filter-tag"
            :class="{ 'suspect-filter-tag--on': suspectApiOnly }"
            :aria-pressed="suspectApiOnly"
            @click="suspectApiOnly = !suspectApiOnly"
          >
            仅看波及接口
          </button>
        </div>
        <div
          class="job-panel job-panel--table impact-table-panel"
          :class="{
            'impact-table-panel--loading': impactSuspectTableLoading,
            'impact-table-panel--empty': !impactSuspectTableLoading && !suspectTableRows.length,
          }"
        >
          <div
            v-if="impactSuspectTableLoading"
            class="impact-table-skeleton impact-table-skeleton--suspect"
            :style="{ minHeight: `${impactTableHeight}px` }"
            role="status"
            aria-live="polite"
            aria-label="正在加载变更函数列表"
          >
            <div class="impact-table-skeleton__toolbar">
              <span class="impact-skel-bar impact-skel-bar--search" />
              <span class="impact-skel-bar impact-skel-bar--tag" />
            </div>
            <div class="impact-table-skeleton__body">
              <div v-for="row in 5" :key="row" class="impact-table-skeleton__row impact-table-skeleton__row--wide">
                <span class="impact-skel-bar impact-skel-bar--fn" />
                <span class="impact-skel-bar impact-skel-bar--file" />
              </div>
            </div>
          </div>
          <div
            v-else-if="!suspectTableRows.length"
            class="impact-suspect-empty"
            :style="{ minHeight: `${suspectEmptyMinHeightResolved}px` }"
          >
            <span class="impact-suspect-empty__icon-wrap" aria-hidden="true">
              <span class="mdi mdi-code-brackets impact-suspect-empty__icon" />
            </span>
            <p class="impact-suspect-empty__title">
              {{
                selectedApiKey
                  ? '当前接口下无关联的变更函数'
                  : suspectSearch.trim() || suspectApiOnly
                    ? '无匹配的变更函数'
                    : '暂无变更函数'
              }}
            </p>
            <p v-if="selectedApiKey" class="impact-suspect-empty__sub">
              该 API 在调用链中为「直达」，或未索引到变更符号。
            </p>
            <button
              v-if="selectedApiKey"
              type="button"
              class="impact-suspect-empty__cta"
              @click="clearApiFilter"
            >
              清除接口筛选
            </button>
          </div>
          <el-table
            v-else
            :data="suspectTableRows"
            size="small"
            :height="suspectTableLayoutHeight"
            class="job-click-table job-suspect-table impact-table-scroll custom-scrollbar job-suspect-table--fit"
            :row-class-name="impactSuspectRowClass"
            @row-click="openDrawerFromSuspect"
          >
            <el-table-column label="变更函数" min-width="200">
              <template #default="{ row }">
                <el-tooltip
                  :content="row.qualified_name"
                  placement="top"
                  :show-after="320"
                  :disabled="row.qualified_name === row.displayName"
                >
                  <div
                    class="suspect-cell"
                    @mouseenter="linkHoverSuspectQname = row.qualified_name"
                    @mouseleave="linkHoverSuspectQname = null"
                  >
                    <div class="suspect-cell__main">
                      <span class="suspect-cell__name">{{ row.displayName }}</span>
                    </div>
                    <div class="suspect-cell__sub">
                      <span
                        class="suspect-impact-badge"
                        :class="row.hitsApi ? 'suspect-impact-badge--hit' : 'suspect-impact-badge--iso'"
                      >
                        {{ row.hitsApi ? '命中接口' : '孤立变更' }}
                      </span>
                      <span v-if="row.pathFile !== '—'" class="suspect-cell__loc mono">
                        <span v-if="row.pathDir" class="suspect-cell__path-dir">{{ row.pathDir }}</span>
                        <span class="suspect-cell__path-file">{{ row.pathFile }}</span>
                        <span v-if="row.lineLabel" class="suspect-cell__path-lines">{{ row.lineLabel }}</span>
                      </span>
                      <span v-else class="suspect-cell__loc mono">—</span>
                    </div>
                  </div>
                </el-tooltip>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="128" align="right" header-align="right" class-name="suspect-col-actions">
              <template #default="{ row }">
                <button
                  type="button"
                  class="suspect-diff-btn"
                  @click.stop.prevent="openDrawerFromSuspect(row)"
                >
                  <span class="mdi mdi-file-compare suspect-diff-btn__icon" aria-hidden="true" />
                  <span class="suspect-diff-btn__label">查看 Diff</span>
                </button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </section>

    <el-drawer
      v-model="unresolvedDrawerOpen"
      direction="rtl"
      size="min(92vw, 420px)"
      :append-to-body="true"
      :with-header="false"
      class="fs-unresolved-drawer"
      modal-class="fs-unresolved-drawer-overlay"
    >
      <header class="fs-unresolved-drawer__head">
        <span class="mdi mdi-alert-circle-outline fs-unresolved-drawer__warn" aria-hidden="true" />
        <div class="fs-unresolved-drawer__head-text">
          <h3 class="fs-unresolved-drawer__title">未解析动态请求</h3>
          <p class="fs-unresolved-drawer__lead">未参与精确接口匹配</p>
          <p class="fs-unresolved-drawer__hint">
            以下文件使用了动态 URL（模板字符串或变量拼接），需人工确认。
          </p>
        </div>
        <button
          type="button"
          class="fs-unresolved-drawer__close"
          aria-label="关闭"
          @click="unresolvedDrawerOpen = false"
        >
          <span class="mdi mdi-close" aria-hidden="true" />
        </button>
      </header>

      <ul v-if="unresolvedFlat.length" class="fs-unresolved-drawer__list">
        <li
          v-for="(item, i) in unresolvedFlat"
          :key="`${item.file}:${item.line}:${i}`"
          class="fs-unresolved-drawer__item"
        >
          <button
            type="button"
            class="fs-unresolved-row"
            :title="`${item.file} · L${item.line}`"
            @click="openUnresolvedAt(item.file, item.line)"
          >
            <span class="fs-unresolved-row__badge">{{ unresolvedExtBadge(item.file) }}</span>
            <span class="fs-unresolved-row__text">
              <span class="fs-unresolved-row__name">{{ unresolvedFileName(item.file) }}</span>
              <span class="fs-unresolved-row__path mono">
                {{ unresolvedFileDir(item.file) }}<template v-if="item.line"> · L{{ item.line }}</template>
              </span>
            </span>
            <span class="fs-unresolved-row__action">↗ 查看</span>
          </button>
        </li>
      </ul>
      <p v-else class="fs-unresolved-drawer__empty">暂无未解析条目</p>
    </el-drawer>

    <CodeDiffDrawer
      v-if="job"
      v-model:open="drawerOpen"
      :show-back="drawerFromUnresolved"
      @back="onCodeDrawerBackToUnresolved"
      :job-id="props.id"
      :title="drawerPick?.title"
      :file="drawerPick?.file"
      :start-line="drawerPick?.startLine"
      :end-line="drawerPick?.endLine"
      :node-type="drawerPick?.nodeType"
      :highlight="drawerPick?.highlight"
      :impact-path="drawerPick?.impactPath"
      :repo="job.repo"
      :head-sha="job.head_sha"
    />
  </div>
</template>

<style scoped>
.job-detail-page.page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-top: 20px;
}
.job-page-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px 16px;
}
.job-page-header {
  flex: 1 1 auto;
  min-width: 0;
}
.job-page-title {
  font-size: 1.0625rem;
  font-weight: 700;
  color: #ffffff;
  letter-spacing: 0.01em;
}
.job-regression-cta {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 38px;
  padding: 0 16px;
  border: 1px solid rgba(138, 180, 248, 0.45);
  border-radius: 999px;
  background: rgba(59, 100, 180, 0.22);
  color: #aecbfb;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition:
    background 0.2s ease,
    border-color 0.2s ease,
    color 0.2s ease;
}
.job-regression-cta:hover {
  background: rgba(79, 120, 200, 0.35);
  border-color: rgba(138, 180, 248, 0.65);
  color: #d2e3fc;
}
.job-regression-cta__arrow {
  font-weight: 600;
  opacity: 0.85;
}
.job-meta-strip {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  margin-top: 2px;
  margin-bottom: 2px;
  padding: 9px 14px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(30, 30, 30, 0.92);
  box-sizing: border-box;
  font-size: 13px;
  line-height: 1.35;
}
.job-meta-strip__status {
  flex-shrink: 0;
  font-size: 11px;
  padding: 3px 9px;
}
.job-meta-strip__sep {
  width: 1px;
  height: 16px;
  flex-shrink: 0;
  background: rgba(255, 255, 255, 0.12);
}
.job-meta-strip__part {
  display: inline-flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 2px 3px;
  min-width: 0;
}
.job-meta-strip__part--branch {
  flex: 1 1 auto;
  min-width: min(100%, 12rem);
}
.job-meta-strip__label {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.5);
  white-space: nowrap;
}
.job-meta-strip__colon {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.35);
  margin-right: 2px;
}
.job-meta-strip__num {
  font-size: 14px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: #ffffff;
}
.job-meta-strip__unit {
  font-size: 12px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.42);
  margin-left: 1px;
}
.job-meta-strip__branch {
  font-size: 12px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.88);
  padding: 2px 8px;
  border-radius: 5px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.09);
  line-height: 1.25;
}
.job-meta-strip__range {
  font-size: 12px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.62);
  letter-spacing: 0.02em;
  white-space: nowrap;
}
.job-tonal-alert {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 12px 16px;
  padding: 12px 16px;
  border-radius: 12px;
  background: rgba(138, 180, 248, 0.08);
  border: 1px solid rgba(138, 180, 248, 0.25);
}
.job-tonal-alert__text {
  flex: 1 1 12rem;
}
.job-tonal-alert__aside {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  margin-left: auto;
  text-align: right;
  flex: 0 1 auto;
}
.job-pass-badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  color: #81c995;
  background: rgba(129, 201, 149, 0.14);
  border: 1px solid rgba(129, 201, 149, 0.35);
  white-space: nowrap;
}
.job-pass-sub {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.48);
  max-width: 14rem;
  line-height: 1.4;
}
.job-tonal-alert__icon {
  flex-shrink: 0;
  font-size: 20px;
  line-height: 1.4;
  color: #8ab4f8;
}
.job-tonal-alert__text {
  margin: 0;
  font-size: 13px;
  line-height: 1.55;
  color: #c4c7c5;
}
.job-status-badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.2;
}
.job-status-badge__check {
  font-size: 13px;
  line-height: 1;
  margin-right: 4px;
  opacity: 0.95;
}
.job-status-badge--completed {
  background: rgba(16, 185, 129, 0.15);
  color: #34d399;
  border: none;
  gap: 4px;
}
.job-status-badge--running {
  background: rgba(138, 180, 248, 0.15);
  color: #8ab4f8;
  border: 1px solid rgba(138, 180, 248, 0.3);
}
.job-status-badge--debouncing {
  background: rgba(251, 191, 36, 0.12);
  color: #fbbf24;
  border: 1px solid rgba(251, 191, 36, 0.28);
}
.job-status-badge--live {
  gap: 6px;
  padding-inline: 10px 12px;
}
.job-status-badge--live::before {
  content: '';
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
  animation: job-status-pulse 1.4s ease-in-out infinite;
}
.job-analyzing-banner {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 14px 16px;
  border-radius: 12px;
  border: 1px solid rgba(138, 180, 248, 0.28);
  background: rgba(138, 180, 248, 0.08);
}
.job-analyzing-banner__spinner {
  font-size: 22px;
  line-height: 1;
  color: #8ab4f8;
  flex-shrink: 0;
  animation: job-status-spin 0.9s linear infinite;
}
.job-analyzing-banner__title {
  margin: 0 0 4px;
  font-size: 14px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.92);
}
.job-analyzing-banner__sub {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: rgba(255, 255, 255, 0.55);
}
.job-meta-strip--muted .job-meta-strip__num,
.job-meta-strip--muted .job-meta-strip__unit,
.job-meta-strip--muted .job-meta-strip__range {
  opacity: 0.55;
}
.job-detail-page--busy::before {
  content: '';
  position: fixed;
  top: 56px;
  left: 0;
  right: 0;
  height: 2px;
  z-index: 1200;
  background: linear-gradient(
    90deg,
    transparent,
    rgba(138, 180, 248, 0.9) 35%,
    rgba(138, 180, 248, 0.9) 65%,
    transparent
  );
  background-size: 200% 100%;
  animation: job-top-progress 1.35s ease-in-out infinite;
  pointer-events: none;
}
.job-detail-tables--waiting {
  opacity: 0.72;
}
@keyframes job-status-spin {
  to {
    transform: rotate(360deg);
  }
}
@keyframes job-status-pulse {
  0%,
  100% {
    opacity: 0.35;
    transform: scale(0.92);
  }
  50% {
    opacity: 1;
    transform: scale(1);
  }
}
@keyframes job-top-progress {
  0% {
    background-position: 100% 0;
  }
  100% {
    background-position: -100% 0;
  }
}
.job-status-badge--pending {
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.72);
  border: 1px solid #2a2e35;
}
.job-status-badge--failed {
  background: rgba(242, 139, 130, 0.15);
  color: #f28b82;
  border: 1px solid rgba(242, 139, 130, 0.35);
}
.job-detail-block,
.job-detail-tables {
  width: 100%;
}
.job-detail-tables {
  margin-bottom: 28px;
  padding-bottom: 6px;
}
.impact-split {
  display: flex;
  align-items: flex-start;
  gap: 0;
  width: 100%;
  min-height: 0;
}
.impact-split__pane {
  flex: 0 1 auto;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.impact-split__pane--api-empty {
  align-self: flex-start;
}
.impact-split__pane--right {
  flex-grow: 1;
  padding-left: 0;
  border-left: none;
}
.impact-split__pane--suspect-fit {
  align-self: flex-start;
}
/* 透明拖拽条：保留调宽，不画竖线 */
.impact-split__resizer {
  flex: 0 0 10px;
  align-self: stretch;
  margin: 26px 0 0;
  cursor: col-resize;
  border: none;
  border-radius: 0;
  background: transparent;
  touch-action: none;
}
.impact-split__resizer:hover {
  background: rgba(138, 180, 248, 0.06);
}
.impact-table-panel {
  padding-bottom: 2px;
}
.impact-table-panel--loading,
.impact-table-panel--empty {
  overflow: hidden;
}
.impact-table-cols {
  display: grid;
  grid-template-columns: 15% 45% 40%;
  align-items: center;
  column-gap: 8px;
  padding-left: 16px;
  padding-right: 16px;
  box-sizing: border-box;
}
.impact-table-skeleton {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.impact-table-skeleton__head {
  flex-shrink: 0;
  min-height: 44px;
  border-bottom: 1px solid #2a2a2a;
}
.impact-table-skeleton__th {
  font-size: 11px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.6);
  letter-spacing: 0.02em;
}
.impact-table-skeleton__body {
  flex: 1;
  padding: 6px 0 12px;
  overflow: hidden;
}
.impact-table-skeleton__row {
  min-height: 46px;
}
.impact-table-skeleton__row--wide {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 8px;
  padding: 10px 16px;
  min-height: 52px;
  border-bottom: 1px solid rgba(42, 42, 42, 0.65);
}
.impact-table-skeleton__row--wide:last-child {
  border-bottom: none;
}
.impact-table-skeleton__cell {
  display: flex;
  align-items: center;
  min-width: 0;
}
.impact-table-skeleton__cell--center {
  justify-content: center;
}
.impact-table-skeleton__toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid #2a2a2a;
}
.impact-skel-bar {
  display: block;
  height: 12px;
  width: 68%;
  max-width: 100%;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.07);
  position: relative;
  overflow: hidden;
}
.impact-skel-bar::after {
  content: '';
  position: absolute;
  inset: 0;
  transform: translateX(-100%);
  background: linear-gradient(
    90deg,
    transparent,
    rgba(255, 255, 255, 0.09),
    transparent
  );
  animation: impact-skel-shimmer 1.35s ease-in-out infinite;
}
.impact-skel-bar--pill {
  width: 44px;
  height: 22px;
  border-radius: 999px;
}
.impact-skel-bar--mid {
  width: 52%;
}
.impact-skel-bar--search {
  flex: 1;
  height: 34px;
  border-radius: 8px;
  max-width: 220px;
}
.impact-skel-bar--tag {
  width: 96px;
  height: 30px;
  border-radius: 8px;
  flex-shrink: 0;
}
.impact-skel-bar--fn {
  width: 46%;
  height: 11px;
}
.impact-skel-bar--file {
  width: 72%;
  height: 11px;
  opacity: 0.85;
}
@keyframes impact-skel-shimmer {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(100%);
  }
}
.impact-table-scroll--idle :deep(.el-scrollbar__bar) {
  display: none !important;
}
.impact-table-scroll--idle :deep(.el-table__body-wrapper),
.impact-table-scroll--idle :deep(.el-scrollbar__wrap) {
  overflow: hidden !important;
}
.impact-api-table.impact-table-scroll--idle :deep(.el-table__empty-block) {
  min-height: 300px;
}
.impact-table-scroll :deep(.el-table__body-wrapper) {
  padding-bottom: 14px;
  overflow-x: hidden !important;
}
.impact-table-scroll :deep(table.el-table__header),
.impact-table-scroll :deep(table.el-table__body) {
  table-layout: fixed;
  width: 100% !important;
}
.impact-table-scroll :deep(.el-scrollbar__wrap) {
  padding-bottom: 10px;
  overflow-x: hidden !important;
  scrollbar-width: thin;
  scrollbar-color: rgba(120, 128, 140, 0.45) transparent;
}
.impact-table-scroll :deep(.el-scrollbar__wrap::-webkit-scrollbar) {
  width: 6px;
  height: 6px;
}
.impact-table-scroll :deep(.el-scrollbar__wrap::-webkit-scrollbar-track) {
  background: transparent;
}
.impact-table-scroll :deep(.el-scrollbar__wrap::-webkit-scrollbar-thumb) {
  background: rgba(120, 128, 140, 0.35);
  border-radius: 6px;
}
.impact-table-scroll :deep(.el-scrollbar__wrap:hover::-webkit-scrollbar-thumb) {
  background: rgba(150, 158, 170, 0.55);
}
.impact-table-scroll :deep(.el-scrollbar__bar.is-vertical) {
  width: 6px;
  right: 2px;
}
.impact-table-scroll :deep(.el-scrollbar__bar.is-vertical .el-scrollbar__thumb) {
  background: rgba(120, 128, 140, 0.4);
  opacity: 0.55;
}
.impact-table-scroll:hover :deep(.el-scrollbar__bar.is-vertical .el-scrollbar__thumb) {
  opacity: 0.95;
}
.impact-split__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  margin-bottom: 10px;
  min-height: 32px;
}
.impact-split__head--suspect {
  justify-content: space-between;
}
.impact-filter-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  padding: 4px 6px 4px 12px;
  border-radius: 999px;
  border: none;
  background: #2a2e35;
  color: rgba(255, 255, 255, 0.72);
  font-size: 11px;
}
.impact-filter-chip__label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: min(42vw, 280px);
}
.impact-filter-chip__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  padding: 0;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: rgba(255, 255, 255, 0.45);
  cursor: pointer;
  flex-shrink: 0;
}
.impact-filter-chip__close:hover {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.1);
}
.impact-api-table--compact :deep(.el-table__body-wrapper) {
  min-height: 0;
}
.impact-api-path {
  display: inline;
  padding: 0;
  border: none;
  background: transparent;
  color: #e8eaed;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.impact-api-path:hover {
  color: #8ab4f8;
  text-decoration: underline;
}
.chain--short {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}
.chain--direct {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #666a73;
  letter-spacing: 0.02em;
}
.chain__direct-glyph {
  font-size: 13px;
  opacity: 0.85;
}
.chain--fn {
  font-family: ui-monospace, 'Cascadia Code', 'SF Mono', Consolas, monospace;
  font-size: 11.5px;
  color: rgba(255, 255, 255, 0.78);
}
.impact-empty__icon-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 68px;
  height: 68px;
  margin-bottom: 16px;
  border-radius: 50%;
  background: rgba(138, 180, 248, 0.1);
  border: 1px solid rgba(138, 180, 248, 0.14);
  box-shadow: inset 0 0 0 6px rgba(0, 0, 0, 0.18);
}
.impact-empty--safe .impact-empty__icon-wrap {
  background: rgba(16, 185, 129, 0.12);
  border-color: rgba(16, 185, 129, 0.2);
}
.impact-empty__icon {
  font-size: 34px;
  color: #93b8f8;
  line-height: 1;
}
.impact-empty--safe .impact-empty__icon {
  color: #34d399;
}
.impact-empty__title {
  margin: 0 0 10px;
  font-size: 16px;
  font-weight: 700;
  color: #ffffff;
  line-height: 1.35;
}
.impact-empty__hint {
  margin: 0;
  max-width: 300px;
  font-size: 12px;
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.5);
}
.impact-empty__link {
  border: none;
  background: transparent;
  color: #8ab4f8;
  font-size: 12px;
  cursor: pointer;
  text-decoration: underline;
}
.impact-api-table :deep(.el-table__body td.el-table__cell),
.job-suspect-table :deep(.el-table__body td.el-table__cell) {
  padding-top: 11px;
  padding-bottom: 11px;
  vertical-align: middle;
}
.impact-api-table :deep(.el-table__header th.el-table__cell),
.job-suspect-table :deep(.el-table__header th.el-table__cell) {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.6) !important;
  font-weight: 600;
  padding-top: 12px;
  padding-bottom: 12px;
}
.impact-api-table :deep(.el-table__header-wrapper) {
  border-bottom: 1px solid #2a2a2a;
}
.impact-table-panel--empty :deep(.el-table__inner-wrapper::before) {
  display: none;
}
.impact-api-table :deep(.el-table__body td.el-table__cell) {
  padding-top: 13px;
  padding-bottom: 13px;
}
.impact-api-table :deep(.el-table__body td.el-table__cell:nth-child(1)) {
  text-align: center;
}
.impact-api-table :deep(.el-table__body td.el-table__cell:nth-child(2)),
.impact-api-table :deep(.el-table__body td.el-table__cell:nth-child(3)) {
  text-align: left;
}
.job-suspect-table :deep(.el-table__body tr td.el-table__cell) {
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
.job-suspect-table :deep(.el-table__body tr:last-child td.el-table__cell) {
  border-bottom: none;
}
.job-detail-page :deep(tr.impact-row--selected td.el-table__cell) {
  background: rgba(59, 130, 246, 0.15) !important;
  box-shadow: inset 3px 0 0 #3b82f6;
  color: #f1f3f5 !important;
}
.job-detail-page :deep(tr.impact-row--selected .impact-api-path) {
  color: #ffffff;
}
.job-detail-page :deep(tr.impact-row--selected .chain--direct) {
  color: #888888;
}
.impact-api-table :deep(.el-table__body tr td.el-table__cell) {
  border-bottom: 1px solid #2a2a2a;
}
.impact-api-table :deep(.el-table__body tr:last-child td.el-table__cell) {
  border-bottom: none;
}
.impact-suspect-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 32px 20px 40px;
  box-sizing: border-box;
}
.impact-suspect-empty__icon-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  margin-bottom: 14px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.06);
}
.impact-suspect-empty__icon {
  font-size: 28px;
  color: rgba(255, 255, 255, 0.58);
  line-height: 1;
}
.impact-suspect-empty__title {
  margin: 0 0 10px;
  font-size: 14px;
  font-weight: 600;
  color: #ffffff;
}
.impact-suspect-empty__sub {
  margin: 0 0 18px;
  max-width: 300px;
  font-size: 12px;
  line-height: 1.65;
  color: #888888;
}
.impact-suspect-empty__cta {
  height: 34px;
  padding: 0 18px;
  border-radius: 8px;
  border: none;
  background: #2a2a2a;
  color: #ffffff;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease;
}
.impact-suspect-empty__cta:hover {
  background: #363636;
}
.impact-table-panel--empty:not(.impact-table-panel--loading) {
  background-color: #1c1f24;
  background-image: radial-gradient(rgba(255, 255, 255, 0.035) 1px, transparent 1px);
  background-size: 14px 14px;
}
.impact-api-empty-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 232px;
  padding: 28px 20px 32px;
  box-sizing: border-box;
}
.impact-empty--card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  max-width: 320px;
}
.job-detail-page :deep(tr.impact-row--linked td.el-table__cell) {
  background: rgba(253, 214, 99, 0.1) !important;
}
@media (max-width: 768px) {
  .impact-split {
    flex-direction: column;
    gap: 16px;
  }
  .impact-split__pane {
    flex-basis: auto !important;
    width: 100% !important;
  }
  .impact-split__pane--right {
    border-top: 2px solid #3a3e45;
    padding-top: 12px;
  }
  .impact-split__resizer {
    display: none;
  }
  .job-meta-strip__sep {
    display: none;
  }
  .job-meta-strip {
    gap: 8px 10px;
    padding: 10px 12px;
  }
  .job-meta-strip__part {
    flex: 1 1 calc(50% - 6px);
  }
  .job-meta-strip__part--branch {
    flex: 1 1 100%;
  }
}
.job-section__title {
  margin: 4px 0 10px;
  font-size: 1.0625rem;
  font-weight: 600;
  color: #e8eaed;
  letter-spacing: 0.01em;
}
.job-panel {
  background: #1e1e1e;
  border: 1px solid #2a2e35;
  border-radius: 12px;
  overflow: hidden;
}
.job-panel--table {
  padding: 0;
}
.chain {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.82);
}
.sym-list {
  margin: 0;
  padding: 12px 18px 14px;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.78);
}
.job-sym-scroll :deep(.el-scrollbar__view) {
  background: #1a1d21;
}
.job-fail-alert__text {
  font-size: 14px;
  line-height: 1.55;
}
.job-fail-alert__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
.mb {
  margin-bottom: 4px;
}
.job-detail-page :deep(.el-page-header) {
  align-items: center;
}
.job-detail-page :deep(.el-page-header__header) {
  align-items: center;
  gap: 14px;
}
.job-detail-page :deep(.el-page-header__back) {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-right: 0;
  padding: 6px 12px;
  border-radius: 999px;
  background: #2a2e35;
  color: rgba(255, 255, 255, 0.82);
  font-size: 13px;
  font-weight: 500;
  transition: background 0.2s ease;
}
.job-detail-page :deep(.el-page-header__back:hover) {
  background: #363b44;
  color: #ffffff;
}
.job-detail-page :deep(.el-page-header__icon) {
  margin-right: 2px;
  font-size: 14px;
}
.job-detail-page :deep(.el-page-header__divider),
.job-detail-page :deep(.el-divider--vertical) {
  display: none;
}
.job-detail-page :deep(.el-page-header__content) {
  padding-left: 0;
}
.job-detail-page :deep(.el-page-header__content),
.job-detail-page :deep(.el-page-header__title) {
  color: #e8eaed;
}
.job-detail-page :deep(.el-table) {
  --el-table-bg-color: #1a1d21;
  --el-table-tr-bg-color: #1a1d21;
  --el-table-expanded-cell-bg-color: #1a1d21;
  --el-table-header-bg-color: #252930;
  --el-table-row-hover-bg-color: #2a2e35;
  --el-table-border-color: #2a2e35;
  --el-table-text-color: #e8eaed;
  --el-table-header-text-color: rgba(255, 255, 255, 0.72);
  --el-fill-color-lighter: #22262c;
}
.job-detail-page :deep(.el-table__empty-text) {
  color: rgba(255, 255, 255, 0.5);
}
.job-detail-page :deep(.el-table--striped .el-table__body tr.el-table__row--striped td.el-table__cell) {
  background: #1f2329;
}
.job-detail-page :deep(.el-loading-mask) {
  background-color: rgba(11, 12, 14, 0.72);
}
.job-click-table :deep(.el-table__row) {
  cursor: pointer;
}
.job-section-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 12px;
  margin-bottom: 10px;
}
.job-section__title--tight {
  margin: 4px 0 0;
}
.suspect-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px 10px;
  flex: 1 1 auto;
  min-width: min(100%, 14rem);
}
.suspect-toolbar--below-title {
  width: 100%;
  margin: -2px 0 10px;
  justify-content: stretch;
  gap: 12px 16px;
}
.suspect-toolbar__search-wrap {
  flex: 1 1 220px;
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  height: 36px;
  padding: 0 12px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04);
}
.suspect-toolbar__search-icon {
  font-size: 18px;
  color: rgba(255, 255, 255, 0.34);
  flex-shrink: 0;
}
.suspect-toolbar__search {
  flex: 1 1 auto;
  width: 100%;
  min-width: 0;
  height: 100%;
  padding: 0;
  border: none;
  border-radius: 0;
  background: transparent;
  color: #e8eaed;
  font-size: 12px;
  outline: none;
}
.suspect-toolbar__search-wrap:focus-within {
  border-color: rgba(138, 180, 248, 0.45);
}
.suspect-filter-tag {
  flex-shrink: 0;
  height: 36px;
  padding: 0 14px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04);
  color: rgba(255, 255, 255, 0.62);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition:
    background 0.2s ease,
    border-color 0.2s ease,
    color 0.2s ease;
}
.suspect-filter-tag--on {
  color: #fdd663;
  border-color: rgba(253, 214, 99, 0.35);
  background: rgba(253, 214, 99, 0.08);
}
.suspect-filter-tag:hover {
  border-color: rgba(255, 255, 255, 0.18);
}
.job-suspect-table--fit {
  max-height: 400px;
}
.job-suspect-table :deep(.el-table__cell) {
  padding-top: 14px;
  padding-bottom: 14px;
}
.job-suspect-table :deep(.el-table__body tr > td.el-table__cell) {
  background-color: #1a1d21 !important;
  transition: background-color 0.2s ease;
}
.job-suspect-table :deep(.el-table__body tr:hover > td.el-table__cell) {
  background-color: rgba(255, 255, 255, 0.04) !important;
}
.job-suspect-table :deep(td.suspect-col-actions .cell) {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding-right: 12px !important;
  height: 100%;
}
.job-suspect-table :deep(.el-table__body td.el-table__cell) {
  vertical-align: middle;
}
.job-suspect-table.custom-scrollbar :deep(.el-scrollbar__wrap) {
  overflow-x: hidden !important;
  scrollbar-width: thin;
  scrollbar-color: rgba(120, 128, 140, 0.45) transparent;
}
.job-suspect-table.custom-scrollbar :deep(.el-scrollbar__wrap::-webkit-scrollbar) {
  width: 4px;
  height: 4px;
}
.job-suspect-table.custom-scrollbar :deep(.el-scrollbar__wrap::-webkit-scrollbar-button) {
  display: none;
  width: 0;
  height: 0;
}
.job-suspect-table.custom-scrollbar :deep(.el-scrollbar__wrap::-webkit-scrollbar-thumb) {
  background: rgba(120, 128, 140, 0.4);
  border-radius: 4px;
}
.job-suspect-table.custom-scrollbar :deep(.el-scrollbar__wrap::-webkit-scrollbar-track) {
  background: transparent;
}
.job-suspect-table.custom-scrollbar :deep(.el-scrollbar__bar.is-vertical) {
  width: 4px;
  right: 2px;
  opacity: 0.6;
  transition: opacity 0.2s ease;
}
.job-suspect-table.custom-scrollbar:hover :deep(.el-scrollbar__bar.is-vertical) {
  opacity: 1;
}
.job-suspect-table.custom-scrollbar :deep(.el-scrollbar__bar.is-vertical .el-scrollbar__thumb) {
  background: rgba(150, 158, 170, 0.55);
  border-radius: 4px;
}
.job-detail-page .job-suspect-table :deep(tr.impact-row--linked td.el-table__cell) {
  background: rgba(245, 158, 11, 0.06) !important;
  box-shadow: inset 3px 0 0 rgba(245, 158, 11, 0.45);
  animation: impact-suspect-link 1.35s ease-in-out infinite;
}
@keyframes impact-suspect-link {
  0%,
  100% {
    box-shadow: inset 3px 0 0 rgba(245, 158, 11, 0.35);
  }
  50% {
    box-shadow: inset 3px 0 0 rgba(245, 158, 11, 0.9);
  }
}
.suspect-cell {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.suspect-cell__main {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.suspect-cell__sub {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.suspect-cell__name {
  font-size: 14px;
  font-weight: 700;
  color: #ffffff;
  line-height: 1.35;
  word-break: break-word;
}
.suspect-cell__loc {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0;
  font-size: 11.5px;
  line-height: 1.45;
  word-break: break-all;
}
.suspect-cell__path-dir {
  color: rgba(255, 255, 255, 0.38);
}
.suspect-cell__path-file {
  color: rgba(255, 255, 255, 0.62);
}
.suspect-cell__path-lines {
  margin-left: 6px;
  color: rgba(255, 255, 255, 0.36);
  font-variant-numeric: tabular-nums;
}
.suspect-impact-badge {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  font-weight: 600;
  padding: 0;
  letter-spacing: 0.02em;
}
.suspect-impact-badge__dot {
  font-size: 11px;
  line-height: 1;
  opacity: 0.9;
}
.suspect-impact-badge--hit {
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.1);
  border: none;
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 600;
}
.suspect-impact-badge--iso {
  color: rgba(255, 255, 255, 0.55);
  background: rgba(255, 255, 255, 0.07);
  border: 1px solid rgba(255, 255, 255, 0.08);
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 10px;
}
.suspect-diff-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 32px;
  padding: 6px 12px;
  border-radius: 8px;
  border: 1px solid transparent;
  background: transparent;
  color: rgba(138, 180, 248, 0.9);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  position: relative;
  z-index: 2;
  transition:
    background 0.2s ease,
    border-color 0.2s ease,
    color 0.2s ease;
}
.suspect-diff-btn__icon {
  font-size: 15px;
  opacity: 0.88;
}
.suspect-diff-btn:hover {
  color: #d2e3fc;
  background: rgba(138, 180, 248, 0.1);
  border-color: rgba(138, 180, 248, 0.32);
}
.job-suspect-table :deep(.el-table__row:hover .suspect-cell__name) {
  color: #ffffff;
}
.file-cell {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.62);
}
.http-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 3.25rem;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  line-height: 1.4;
}
.http-pill--get {
  color: #4ade80;
  background: rgba(34, 197, 94, 0.1);
  border: none;
  min-width: 2.5rem;
  font-weight: 700;
}
.http-pill--post {
  color: #aecbfa;
  background: rgba(138, 180, 248, 0.1);
  border: 1px solid rgba(138, 180, 248, 0.28);
}
.http-pill--put {
  color: #d4a8ff;
  background: rgba(197, 138, 249, 0.09);
  border: 1px solid rgba(197, 138, 249, 0.26);
}
.http-pill--delete {
  color: #f6aea8;
  background: rgba(242, 139, 130, 0.1);
  border: 1px solid rgba(242, 139, 130, 0.28);
}
.fs-module-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px 24px;
  padding-bottom: 16px;
  margin-bottom: 16px;
  border-bottom: 1px solid #2a2a2a;
}
.fs-module-head__main {
  flex: 1 1 280px;
  min-width: 0;
}
.fs-module-head__title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.fs-module-head__accent {
  width: 3px;
  height: 18px;
  border-radius: 2px;
  background: linear-gradient(180deg, #8ab4f8 0%, #22d3ee 100%);
  flex-shrink: 0;
}
.fs-module-head__glyph {
  color: #8ab4f8;
  opacity: 0.92;
  flex-shrink: 0;
}
.fs-module-head__title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  line-height: 1.35;
  color: #ffffff;
  letter-spacing: 0.01em;
}
.fs-module-head__desc {
  margin: 10px 0 0;
  padding-left: 31px;
  font-size: 12px;
  line-height: 1.55;
  color: #888888;
  max-width: 600px;
}
.fs-module-head__banner {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin: 10px 0 0;
  max-width: 600px;
  padding: 8px 12px;
  font-size: 12px;
  line-height: 1.55;
  color: #9ca3af;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
}
.fs-module-head__banner-icon {
  margin-top: 1px;
  font-size: 15px;
  color: #8ab4f8;
  flex-shrink: 0;
}
.fs-module-head__banner-text {
  color: #888888;
}
.fs-module-head__stats {
  margin: 4px 0 0;
  font-size: 13px;
  line-height: 1.5;
  color: rgba(255, 255, 255, 0.52);
  white-space: nowrap;
  flex-shrink: 0;
}
.fs-module-head__stats strong {
  color: #8ab4f8;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.fs-module-body {
  box-sizing: border-box;
}
.fullstack-cols {
  margin-bottom: 0;
  margin-top: 0;
  align-items: stretch;
}
.mono {
  font-family: ui-monospace, 'Cascadia Code', 'SF Mono', Consolas, monospace;
  font-variant-numeric: tabular-nums;
}
.fullstack-cols :deep(.el-col) {
  display: flex;
}
.fullstack-panel-half {
  flex: 1;
  width: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  padding: 14px 16px 16px !important;
  background: #1e1e1e !important;
  border: 1px solid rgba(255, 255, 255, 0.05) !important;
  border-radius: 12px !important;
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.2);
}
.fullstack-panel-half .fullstack-table {
  flex: 1;
  width: 100%;
}
.fullstack-table :deep(.el-table__header th.el-table__cell) {
  background: transparent !important;
  font-weight: 500;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.6) !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08) !important;
  padding: 10px 10px 12px !important;
}
.fullstack-table :deep(.el-table__body td.el-table__cell) {
  border-bottom: 1px solid rgba(255, 255, 255, 0.05) !important;
  padding: 12px 10px !important;
  vertical-align: middle !important;
}
.fullstack-table :deep(.el-table__body tr:last-child td.el-table__cell) {
  border-bottom: none !important;
}
.fullstack-table :deep(.el-table__body) {
  background: transparent !important;
}
.fullstack-table :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
}
.fullstack-table :deep(.el-table__inner-wrapper::before) {
  display: none;
}
.fs-path-cell {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 2px 6px;
  line-height: 1.45;
}
.fs-file-name {
  font-weight: 600;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.92);
}
.fs-file-dir {
  font-size: 11px;
  font-family: ui-monospace, 'Cascadia Code', 'SF Mono', Consolas, monospace;
  color: rgba(255, 255, 255, 0.38);
}
.fs-route {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.55);
}
.fs-hit-cell {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 8px;
}
.fs-lines {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 4px 10px;
}
.fs-line-text {
  margin: 0;
  padding: 0;
  border: none;
  background: transparent;
  font-size: 11px;
  line-height: 1.4;
  color: rgba(255, 255, 255, 0.4);
  cursor: pointer;
  transition: color 0.15s ease;
}
.fs-line-text:hover {
  color: rgba(255, 255, 255, 0.78);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.fs-api-pill {
  display: inline-flex;
  align-items: center;
  margin: 0;
  font-size: 11px;
  line-height: 1.35;
}
.fs-http-pill {
  min-width: 0 !important;
  padding: 4px 8px !important;
  border-radius: 4px !important;
  font-size: 11px !important;
  font-weight: 500 !important;
  letter-spacing: 0 !important;
  color: #6ee7b7 !important;
  background: rgba(16, 185, 129, 0.1) !important;
  border: 1px solid rgba(16, 185, 129, 0.22) !important;
}
.fs-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-height: 36px;
  margin-bottom: 12px;
  flex-shrink: 0;
}
.fs-panel-head--solo {
  justify-content: flex-start;
}
.fs-panel-head__title {
  margin: 0;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
  color: rgba(255, 255, 255, 0.62);
}
.fs-unresolved-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 28px;
  margin-left: auto;
  padding: 0 12px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.2;
  color: #fb923c;
  background: rgba(251, 146, 60, 0.2);
  border: 1px solid rgba(251, 146, 60, 0.4);
  border-radius: 999px;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  box-shadow: 0 0 0 1px rgba(251, 146, 60, 0.08);
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.fs-unresolved-pill:hover {
  color: #ffedd5;
  background: rgba(251, 146, 60, 0.32);
  border-color: rgba(251, 146, 60, 0.55);
}
.fs-unresolved-pill .mdi {
  font-size: 16px;
  color: #fdba74;
}
</style>

<style>
.fs-unresolved-drawer-overlay {
  background-color: rgba(0, 0, 0, 0.48) !important;
  overscroll-behavior: none;
  touch-action: none;
}
.fs-unresolved-drawer.el-drawer {
  background: #1e1e1e !important;
}
.fs-unresolved-drawer .el-drawer__body {
  padding: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.fs-unresolved-drawer__head {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 16px 16px 14px;
  border-bottom: 1px solid #2a2a2a;
  flex-shrink: 0;
}
.fs-unresolved-drawer__warn {
  font-size: 22px;
  color: #fdd663;
  flex-shrink: 0;
  margin-top: 2px;
}
.fs-unresolved-drawer__head-text {
  flex: 1;
  min-width: 0;
}
.fs-unresolved-drawer__title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  line-height: 1.35;
  color: #f3f4f6;
}
.fs-unresolved-drawer__lead {
  margin: 6px 0 0;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
  color: #e5e7eb;
}
.fs-unresolved-drawer__hint {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.55;
  color: #888;
}
.fs-unresolved-drawer__close {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: rgba(255, 255, 255, 0.55);
  cursor: pointer;
  transition:
    background 0.15s ease,
    color 0.15s ease;
}
.fs-unresolved-drawer__close:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}
.fs-unresolved-drawer__list {
  margin: 0;
  padding: 0 8px;
  list-style: none;
  overflow-y: auto;
  flex: 1;
}
.fs-unresolved-drawer__item {
  border-bottom: 1px solid #2a2a2a;
}
.fs-unresolved-drawer__item:last-child {
  border-bottom: none;
}
.fs-unresolved-row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  margin: 0;
  padding: 12px 10px;
  text-align: left;
  background: transparent;
  border: none;
  border-radius: 0;
  cursor: pointer;
  transition: background 0.15s ease;
}
.fs-unresolved-row:hover {
  background: rgba(255, 255, 255, 0.05);
}
.fs-unresolved-row:hover .fs-unresolved-row__action {
  color: #8ab4f8;
  border-color: rgba(138, 180, 248, 0.45);
}
.fs-unresolved-row__badge {
  flex-shrink: 0;
  min-width: 34px;
  padding: 3px 5px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.03em;
  text-align: center;
  color: #8ab4f8;
  background: rgba(138, 180, 248, 0.12);
  border-radius: 4px;
}
.fs-unresolved-row__text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.fs-unresolved-row__name {
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.fs-unresolved-row__path {
  font-size: 12px;
  line-height: 1.35;
  color: #888;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.fs-unresolved-row__action {
  flex-shrink: 0;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.52);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 999px;
  transition:
    color 0.15s ease,
    border-color 0.15s ease;
}
.fs-unresolved-drawer__empty {
  margin: 0;
  padding: 24px 16px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.45);
}
</style>