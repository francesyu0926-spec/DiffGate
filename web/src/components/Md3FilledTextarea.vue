<script setup lang="ts">
import { computed, nextTick, ref, useAttrs, watch } from 'vue'

defineOptions({ inheritAttrs: false })

const props = withDefaults(
  defineProps<{
    modelValue?: string
    label?: string
    placeholder?: string
    collapsedLabel?: string
    maxlength?: number
    minHeightPx?: number
    maxHeightPx?: number
  }>(),
  {
    modelValue: '',
    label: '',
    placeholder: '',
    collapsedLabel: '+ 添加描述说明',
    maxlength: 200,
    minHeightPx: 72,
    maxHeightPx: 168,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const attrs = useAttrs()
const focused = ref(false)
const expanded = ref(false)
const textareaRef = ref<HTMLTextAreaElement | null>(null)

const textLen = computed(() => String(props.modelValue ?? '').length)
const hasValue = computed(() => textLen.value > 0)
const floated = computed(() => focused.value || hasValue.value)
const counterText = computed(() => `${textLen.value} / ${props.maxlength}`)
const showCollapse = computed(() => expanded.value && !hasValue.value)

watch(
  hasValue,
  (v) => {
    if (v) expanded.value = true
  },
  { immediate: true },
)

function expand() {
  expanded.value = true
  void nextTick(() => textareaRef.value?.focus())
}

function collapse() {
  expanded.value = false
  focused.value = false
}

function onInput(e: Event) {
  const el = e.target as HTMLTextAreaElement
  emit('update:modelValue', el.value)
  resize()
}

function resize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  const next = Math.min(Math.max(el.scrollHeight, props.minHeightPx), props.maxHeightPx)
  el.style.height = `${next}px`
  el.style.overflowY = el.scrollHeight > props.maxHeightPx ? 'auto' : 'hidden'
}

function onFocus() {
  focused.value = true
  expanded.value = true
}

function onBlur() {
  focused.value = false
}

watch(expanded, (v) => {
  if (v) void nextTick(resize)
})

watch(
  () => props.modelValue,
  () => {
    if (expanded.value) void nextTick(resize)
  },
)
</script>

<template>
  <div
    class="md3-filled md3-filled--textarea"
    :class="{
      'md3-filled--focused': focused,
      'md3-filled--floated': floated,
      'md3-filled--textarea-expanded': expanded,
    }"
  >
    <button
      v-if="!expanded"
      type="button"
      class="md3-filled__expand-btn"
      @click="expand"
    >
      {{ collapsedLabel }}
    </button>
    <template v-else>
      <div class="md3-filled__box md3-filled__box--textarea">
        <button
          v-if="showCollapse"
          type="button"
          class="md3-filled__collapse-btn"
          @click="collapse"
        >
          收起
        </button>
        <textarea
          ref="textareaRef"
          v-bind="attrs"
          class="md3-filled__textarea"
          :value="modelValue"
          :maxlength="maxlength"
          :placeholder="focused ? placeholder : ' '"
          @input="onInput"
          @focus="onFocus"
          @blur="onBlur"
        />
        <label v-if="label || $slots.label" class="md3-filled__label" :for="attrs.id as string | undefined">
          <slot name="label">{{ label }}</slot>
        </label>
      </div>
      <div class="md3-filled__footer md3-filled__footer--textarea">
        <span class="md3-filled__helper" aria-hidden="true" />
        <span class="md3-filled__counter">{{ counterText }}</span>
      </div>
    </template>
  </div>
</template>