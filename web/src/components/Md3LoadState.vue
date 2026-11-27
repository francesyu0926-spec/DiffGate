<script setup lang="ts">
withDefaults(
  defineProps<{
    loading?: boolean
    /** skeleton | overlay（圆环+文案）| linear（顶栏细线） */
    mode?: 'skeleton' | 'overlay' | 'linear'
    skeletonType?: string
    label?: string
    minHeight?: string
    boilerplate?: boolean
  }>(),
  {
    loading: true,
    mode: 'skeleton',
    skeletonType: 'list-item@3',
    label: '加载中…',
    boilerplate: true,
  },
)
</script>

<template>
  <div
    v-if="loading"
    class="md3-load-state"
    :class="`md3-load-state--${mode}`"
    :style="minHeight ? { minHeight } : undefined"
    role="status"
    :aria-label="label"
    aria-live="polite"
  >
    <v-progress-linear
      v-if="mode === 'linear'"
      class="md3-panel-load__track"
      indeterminate
      color="primary"
      height="3"
      rounded
    />
    <div v-else-if="mode === 'overlay'" class="md3-load-overlay-panel">
      <v-progress-circular indeterminate color="primary" size="40" width="3" />
      <span class="md3-load-label">{{ label }}</span>
    </div>
    <v-skeleton-loader
      v-else
      :type="skeletonType"
      class="m3-skeleton-tonal md3-load-skeleton"
      :boilerplate="boilerplate"
    />
  </div>
</template>

<style scoped>
.md3-load-skeleton :deep(.v-skeleton-loader__bone),
.md3-load-skeleton :deep(.v-skeleton-loader__avatar),
.md3-load-skeleton :deep(.v-skeleton-loader__heading),
.md3-load-skeleton :deep(.v-skeleton-loader__text),
.md3-load-skeleton :deep(.v-skeleton-loader__image),
.md3-load-skeleton :deep(.v-skeleton-loader__list-item),
.md3-load-skeleton :deep(.v-skeleton-loader__sentences) {
  background: rgba(255, 255, 255, 0.06) !important;
  box-shadow: none !important;
}
.md3-load-skeleton :deep(.v-skeleton-loader__bone::after),
.md3-load-skeleton :deep(.v-skeleton-loader__avatar::after),
.md3-load-skeleton :deep(.v-skeleton-loader__heading::after),
.md3-load-skeleton :deep(.v-skeleton-loader__text::after) {
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.1), transparent) !important;
  animation: md3-shimmer 1.4s ease-in-out infinite;
}
.md3-load-skeleton {
  background: transparent !important;
}
</style>