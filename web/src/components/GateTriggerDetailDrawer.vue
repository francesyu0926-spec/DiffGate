<script setup lang="ts">
import { computed } from 'vue'
import type { GateTriggerDetail, HighRiskDetails } from '@/api/client'

const props = defineProps<{
  modelValue: boolean
  mode: 'high_risk' | 'trigger'
  triggerDetail?: GateTriggerDetail | null
  highRisk?: HighRiskDetails | null
}>()

const emit = defineEmits<{ 'update:modelValue': [boolean] }>()

const open = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const drawerTitle = computed(() =>
  props.mode === 'high_risk' ? '高危拦截明细' : '门禁触发细节',
)

const summaryText = computed(() => {
  if (props.triggerDetail?.summary) return props.triggerDetail.summary
  if (props.mode === 'high_risk') {
    const hr = props.highRisk
    if (hr?.api_count != null && hr.api_threshold != null) {
      return (
        `影响 API ${hr.api_count} 个（阈值 ≥${hr.api_threshold}），` +
        `变更符号 ${hr.symbol_count ?? '—'} 个（阈值 ≥${hr.symbol_threshold ?? '—'}）`
      )
    }
  }
  return '暂无摘要'
})

const apiCount = computed(() => {
  const hr = props.highRisk
  const m = props.triggerDetail?.metrics
  if (hr?.api_count != null) return hr.api_count
  if (m?.api_impact != null) return m.api_impact
  return props.triggerDetail?.high_risk_items?.apis?.length ?? 0
})

const symbolCount = computed(() => {
  const hr = props.highRisk
  const m = props.triggerDetail?.metrics
  if (hr?.symbol_count != null) return hr.symbol_count
  if (m?.symbol_count != null) return m.symbol_count
  return props.triggerDetail?.high_risk_items?.symbols?.length ?? 0
})

const apiThreshold = computed(() => {
  const hr = props.highRisk
  const m = props.triggerDetail?.metrics
  return hr?.api_threshold ?? m?.api_threshold ?? null
})

const symbolThreshold = computed(() => {
  const hr = props.highRisk
  const m = props.triggerDetail?.metrics
  return hr?.symbol_threshold ?? m?.symbol_threshold ?? null
})

const apiChips = computed(() => {
  const fromTrigger = props.triggerDetail?.high_risk_items?.apis ?? []
  if (fromTrigger.length) {
    return fromTrigger.map((a) => ({
      key: `${a.method ?? 'GET'}:${a.path ?? '/'}`,
      label: `${a.method ?? 'GET'} ${a.path ?? '/'}`,
      meta: a.file ?? '',
    }))
  }
  return (props.highRisk?.matched_impacts ?? []).map((m, i) => ({
    key: `impact-${i}`,
    label: m.backend_api?.trim() || '（未命名接口）',
    meta: [m.frontend_repo, m.page_file].filter(Boolean).join(' · '),
  }))
})

const symbolChips = computed(() => {
  const fromTrigger = props.triggerDetail?.high_risk_items?.symbols ?? []
  if (fromTrigger.length) {
    return fromTrigger.map((s, i) => {
      const q = s.qualified_name ?? ''
      const short = q.split('.').pop() || q || `symbol-${i}`
      return { key: q || String(i), label: short, meta: s.file ?? '' }
    })
  }
  return (props.highRisk?.matched_modules ?? []).map((m, i) => ({
    key: `${m.file}-${m.symbol}-${i}`,
    label: m.symbol || m.file || '（符号）',
    meta: m.reason || m.level || '',
  }))
})

const triggeredBy = computed(() => props.highRisk?.triggered_by ?? [])

function closeDrawer() {
  open.value = false
}
</script>

<template>
  <v-navigation-drawer
    v-model="open"
    location="right"
    temporary
    :width="440"
    class="gate-trigger-drawer"
  >
    <header class="gtd-header">
      <div class="gtd-header__text">
        <v-icon icon="mdi-alert-decagram-outline" size="22" class="gtd-header__icon" />
        <div>
          <h2 class="gtd-header__title">{{ drawerTitle }}</h2>
          <p class="gtd-header__sub mb-0">点击遮罩或关闭按钮可退出，不再遮挡用例列表。</p>
        </div>
      </div>
      <v-btn
        icon="mdi-close"
        variant="text"
        size="small"
        class="gtd-header__close"
        aria-label="关闭"
        @click="closeDrawer"
      />
    </header>

    <div class="gtd-body">
      <section class="gtd-panel">
        <p class="gtd-summary mb-0" role="status">{{ summaryText }}</p>
        <div v-if="triggeredBy.length" class="gtd-triggered-by mt-3">
          <span class="gtd-section-label">触发方式</span>
          <span class="gtd-triggered-by__val">{{ triggeredBy.join('、') }}</span>
        </div>
      </section>

      <section v-if="apiChips.length" class="gtd-panel gtd-panel--section">
        <div class="gtd-section-head">
          <h3 class="gtd-section-title">
            核心接口
            <strong class="gtd-count">{{ apiCount }}</strong>
            <span class="gtd-section-title__unit">个</span>
          </h3>
          <span v-if="apiThreshold != null" class="gtd-threshold">阈值 ≥{{ apiThreshold }}</span>
        </div>
        <v-divider class="gtd-divider" />
        <div class="gtd-chip-wrap">
          <div
            v-for="chip in apiChips"
            :key="chip.key"
            class="gtd-chip-row"
          >
            <span class="gtd-chip mono">{{ chip.label }}</span>
            <span v-if="chip.meta" class="gtd-chip-meta text-truncate" :title="chip.meta">
              {{ chip.meta }}
            </span>
          </div>
        </div>
      </section>

      <section v-if="symbolChips.length" class="gtd-panel gtd-panel--section">
        <div class="gtd-section-head">
          <h3 class="gtd-section-title">
            变更符号
            <strong class="gtd-count">{{ symbolCount }}</strong>
            <span class="gtd-section-title__unit">个</span>
          </h3>
          <span v-if="symbolThreshold != null" class="gtd-threshold">阈值 ≥{{ symbolThreshold }}</span>
        </div>
        <v-divider class="gtd-divider" />
        <div class="gtd-chip-wrap">
          <div
            v-for="chip in symbolChips"
            :key="chip.key"
            class="gtd-chip-row"
          >
            <span class="gtd-chip gtd-chip--symbol mono">{{ chip.label }}</span>
            <span v-if="chip.meta" class="gtd-chip-meta text-truncate" :title="chip.meta">
              {{ chip.meta }}
            </span>
          </div>
        </div>
      </section>

      <p
        v-if="highRisk?.override_hint"
        class="gtd-hint mb-0"
      >
        {{ highRisk.override_hint }}
      </p>
    </div>
  </v-navigation-drawer>
</template>

<style scoped>
.gate-trigger-drawer {
  background: #2a2a2a !important;
  color: rgba(255, 255, 255, 0.92);
  border-left: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.6);
}
.gtd-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 16px 12px;
}
.gtd-header__text {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-width: 0;
}
.gtd-header__icon {
  flex-shrink: 0;
  margin-top: 2px;
  color: #fbbf24;
}
.gtd-header__title {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  line-height: 1.35;
  color: rgba(255, 255, 255, 0.95);
}
.gtd-header__sub {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.45;
  color: rgba(255, 255, 255, 0.55);
}
.gtd-header__close {
  flex-shrink: 0;
  color: rgba(255, 255, 255, 0.72) !important;
}
.gtd-body {
  padding: 0 16px 20px;
  overflow-y: auto;
  max-height: calc(100vh - 88px);
}
.gtd-panel {
  padding: 16px;
  border-radius: 12px;
  background: #333333;
  border: 1px solid rgba(255, 255, 255, 0.06);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
}
.gtd-panel + .gtd-panel {
  margin-top: 12px;
}
.gtd-summary {
  font-size: 14px;
  line-height: 1.55;
  color: rgba(255, 255, 255, 0.88);
  word-break: break-word;
}
.gtd-triggered-by {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
  font-size: 12px;
}
.gtd-triggered-by__val {
  color: rgba(255, 255, 255, 0.7);
}
.gtd-section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}
.gtd-section-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.95);
}
.gtd-section-title__unit {
  font-weight: 500;
  color: rgba(255, 255, 255, 0.72);
}
.gtd-count {
  margin: 0 2px;
  font-size: 16px;
  font-weight: 700;
  color: #fbbf24;
}
.gtd-section-label {
  font-size: 12px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.82);
}
.gtd-threshold {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.48);
}
.gtd-divider {
  margin: 12px 0;
  border-color: rgba(255, 255, 255, 0.08) !important;
  opacity: 1;
}
.gtd-chip-wrap {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.gtd-chip-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.gtd-chip {
  display: inline-flex;
  align-self: flex-start;
  max-width: 100%;
  padding: 6px 10px;
  border-radius: 8px;
  background: rgba(138, 180, 248, 0.14);
  border: 1px solid rgba(138, 180, 248, 0.28);
  font-size: 12px;
  line-height: 1.4;
  color: #c8daf8;
  word-break: break-all;
}
.gtd-chip--symbol {
  background: rgba(251, 191, 36, 0.12);
  border-color: rgba(251, 191, 36, 0.28);
  color: #fde68a;
}
.gtd-chip-meta {
  font-size: 11px;
  line-height: 1.4;
  color: rgba(255, 255, 255, 0.48);
  padding-left: 2px;
}
.gtd-hint {
  margin-top: 12px;
  padding: 12px 14px;
  border-radius: 10px;
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.22);
  font-size: 12px;
  line-height: 1.5;
  color: rgba(255, 255, 255, 0.72);
}
</style>