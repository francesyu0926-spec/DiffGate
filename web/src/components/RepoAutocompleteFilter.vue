<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { fetchRepositories } from '@/api/client'

const PINNED_KEY = 'diffgate:pinned-repos'

export type RepoGateStat = { full_name: string; block_count: number; pending_count: number }

type MenuRow =
  | { kind: 'subheader'; title: string; disabled: true }
  | { kind: 'divider'; disabled: true }
  | {
      kind: 'option'
      title: string
      value: string | null
      block_count?: number
      pending_count?: number
      pinned?: boolean
    }

const props = withDefaults(
  defineProps<{
    modelValue: string | null
    gateStats?: RepoGateStat[]
    fieldClass?: string
    triggerWidth?: number
  }>(),
  {
    gateStats: () => [],
    fieldClass: 'filter-select-float',
    triggerWidth: 280,
  },
)

const emit = defineEmits<{ 'update:modelValue': [value: string | null] }>()

const menuOpen = ref(false)
const repoRecords = ref<{ full_name: string; default_branch?: string }[]>([])
const pinnedSet = ref<Set<string>>(new Set())

const menuProps = computed(() => {
  const w = props.triggerWidth
  return {
    rounded: 'lg',
    elevation: 8,
    contentClass: 'repo-autocomplete-menu',
    minWidth: w,
    maxWidth: w,
    maxHeight: 320,
    location: 'bottom start' as const,
  }
})

const statMap = computed(() => {
  const m = new Map<string, { block_count: number; pending_count: number }>()
  for (const s of props.gateStats) {
    m.set(s.full_name, { block_count: s.block_count, pending_count: s.pending_count })
  }
  return m
})

function loadPinned() {
  try {
    const raw = localStorage.getItem(PINNED_KEY)
    const list = raw ? (JSON.parse(raw) as string[]) : []
    pinnedSet.value = new Set(list.filter(Boolean))
  } catch {
    pinnedSet.value = new Set()
  }
}

function savePinned() {
  localStorage.setItem(PINNED_KEY, JSON.stringify([...pinnedSet.value]))
}

function togglePinned(fullName: string) {
  const next = new Set(pinnedSet.value)
  if (next.has(fullName)) next.delete(fullName)
  else next.add(fullName)
  pinnedSet.value = next
  savePinned()
  menuOpen.value = true
}

function isPinned(fullName: string) {
  return pinnedSet.value.has(fullName)
}

function repoRow(fullName: string): MenuRow {
  const st = statMap.value.get(fullName)
  return {
    kind: 'option',
    title: fullName,
    value: fullName,
    block_count: st?.block_count ?? 0,
    pending_count: st?.pending_count ?? 0,
    pinned: isPinned(fullName),
  }
}

const menuItems = computed<MenuRow[]>(() => {
  const names = repoRecords.value.map((r) => r.full_name).sort((a, b) => a.localeCompare(b))
  const pinned = names.filter((n) => pinnedSet.value.has(n))
  const rest = names.filter((n) => !pinnedSet.value.has(n))
  const rows: MenuRow[] = [{ kind: 'option', title: '全部仓库', value: null }]

  if (pinned.length) {
    rows.push({ kind: 'subheader', title: '★ 常用仓库', disabled: true })
    pinned.forEach((n) => rows.push(repoRow(n)))
    if (rest.length) rows.push({ kind: 'divider', disabled: true })
  }
  if (rest.length) {
    rows.push({ kind: 'subheader', title: pinned.length ? '全部仓库' : '已接入仓库', disabled: true })
    rest.forEach((n) => rows.push(repoRow(n)))
  }
  return rows
})

const displayValue = computed(() => {
  if (props.modelValue == null) return '全部仓库'
  return props.modelValue
})

function customFilter(_value: string, query: string, item?: { raw: MenuRow }) {
  const raw = item?.raw
  if (!raw || raw.kind !== 'option') return true
  if (!query.trim()) return true
  const q = query.toLowerCase().trim()
  const title = (raw.title ?? '').toLowerCase()
  if (title.includes(q)) return true
  const parts = title.split(/[/\-_\s.]+/).filter(Boolean)
  return parts.some((p) => p.includes(q))
}

function filterItemProps(itemProps: Record<string, unknown>) {
  const next = { ...itemProps }
  delete next.title
  delete next.subtitle
  return next
}

function onPick(value: string | null | undefined) {
  emit('update:modelValue', value ?? null)
  menuOpen.value = false
}

function menuItemProps(item: MenuRow) {
  if (item.kind === 'option') {
    return { title: item.title, value: item.value }
  }
  return { title: item.kind === 'subheader' ? item.title : '', disabled: true as const }
}

onMounted(async () => {
  loadPinned()
  const repos = await fetchRepositories()
  repoRecords.value = repos.map((r) => ({ full_name: r.full_name, default_branch: r.default_branch }))
})
</script>

<template>
  <v-autocomplete
    :model-value="modelValue"
    class="repo-autocomplete"
    :class="fieldClass"
    :style="{ width: `${triggerWidth}px`, minWidth: `${triggerWidth}px`, maxWidth: `${triggerWidth}px` }"
    :items="menuItems"
    :item-props="menuItemProps"
    :custom-filter="customFilter"
    :menu-props="menuProps"
    v-model:menu="menuOpen"
    auto-select-first
    single-line
    hide-details
    variant="solo"
    flat
    density="comfortable"
    rounded="lg"
    prepend-inner-icon="mdi-source-repository"
    :placeholder="displayValue"
    clearable
    @update:model-value="onPick"
  >
    <template #selection="{ item }">
      <span class="text-truncate" :title="String(item?.title ?? displayValue ?? '')">
        {{ item?.title ?? displayValue }}
      </span>
    </template>
    <template #item="{ props: itemProps, item }">
      <template v-if="item.raw.kind === 'subheader'">
        <v-list-subheader class="repo-menu-subheader text-caption font-weight-medium">
          {{ item.raw.title }}
        </v-list-subheader>
      </template>
      <v-divider v-else-if="item.raw.kind === 'divider'" class="repo-menu-divider my-1" />
      <v-list-item
        v-else
        v-bind="filterItemProps(itemProps)"
        :title="item.raw.title"
        class="repo-menu-item"
        :class="{ 'repo-menu-item--selected': modelValue === item.raw.value }"
        rounded="lg"
        density="comfortable"
      >
        <template v-if="item.raw.value" #append>
          <v-btn
            icon
            variant="text"
            size="x-small"
            density="compact"
            class="repo-pin-btn"
            :class="{ 'repo-pin-btn--pinned': item.raw.pinned }"
            :aria-label="item.raw.pinned ? '取消常用' : '设为常用'"
            @click.stop="togglePinned(item.raw.value)"
          >
            <v-icon
              :icon="item.raw.pinned ? 'mdi-star' : 'mdi-star-outline'"
              size="16"
              :color="item.raw.pinned ? '#FBBF24' : 'rgba(241, 243, 245, 0.45)'"
            />
          </v-btn>
          <span
            v-if="(item.raw.block_count ?? 0) > 0"
            class="repo-block-badge"
            :title="`${item.raw.block_count} 次门禁拦截`"
          >
            {{ item.raw.block_count }}
          </span>
          <v-icon
            v-if="modelValue === item.raw.value"
            icon="mdi-check"
            size="18"
            color="#e8eaed"
            class="repo-menu-check"
          />
        </template>
        <template v-else #append>
          <v-icon
            v-if="modelValue == null"
            icon="mdi-check"
            size="18"
            color="#e8eaed"
            class="repo-menu-check"
          />
        </template>
      </v-list-item>
    </template>
  </v-autocomplete>
</template>

<style scoped>
.repo-autocomplete {
  flex: 0 0 auto;
}
.repo-autocomplete :deep(.v-field) {
  min-height: 40px;
  height: 40px;
  border-radius: 10px;
  background-color: rgb(var(--v-theme-surface)) !important;
  font-size: 13px;
  border: 1px solid #2a2e35;
  box-shadow: none;
}
.repo-autocomplete :deep(.v-field__outline),
.repo-autocomplete :deep(.v-field__overlay) {
  opacity: 0 !important;
}
.repo-autocomplete :deep(.v-field__input) {
  min-height: 40px;
  padding-top: 0;
  padding-bottom: 0;
  padding-inline: 2px 8px;
  font-size: 13px;
  flex-wrap: nowrap;
}
.repo-autocomplete :deep(.v-autocomplete__selection) {
  max-width: calc(100% - 4px);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.repo-autocomplete :deep(.v-field__prepend-inner) {
  padding-inline-start: 10px;
  padding-inline-end: 4px;
}
.repo-autocomplete :deep(.v-field__append-inner) {
  padding-inline-end: 6px;
}
</style>

<style>
.repo-autocomplete-menu {
  max-height: 320px !important;
}
.repo-autocomplete-menu .v-list {
  max-height: 320px;
  overflow-y: auto;
}
.repo-menu-subheader {
  min-height: 32px;
  padding-top: 8px;
  color: rgba(241, 243, 245, 0.72);
  letter-spacing: 0.02em;
}
.repo-menu-divider {
  border-color: rgba(255, 255, 255, 0.08);
}
.repo-menu-item .v-list-item-title {
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.repo-menu-item--selected {
  background: rgba(138, 180, 248, 0.12) !important;
}
.repo-menu-item .v-list-item__append {
  display: flex;
  align-items: center;
  gap: 4px;
}
.repo-block-badge {
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 999px;
  background: #f28b82;
  color: #1a1d21;
  font-size: 11px;
  font-weight: 600;
  line-height: 18px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}
.repo-pin-btn {
  opacity: 0.55;
}
.repo-pin-btn--pinned {
  opacity: 1;
}
.repo-menu-item:hover .repo-pin-btn {
  opacity: 1;
}
</style>