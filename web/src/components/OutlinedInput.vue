<script setup lang="ts">
import { computed, inject, useAttrs } from 'vue'
import { DG_FORM_FIELD_SPEC_KEY } from '@/form/formFieldLayout'

defineOptions({ inheritAttrs: false })

const props = withDefaults(
  defineProps<{
    modelValue?: string
    label?: string
    /** 与 React OutlinedInput 的 helperText 一致 */
    helperText?: string
    /** @deprecated 使用 helperText */
    helper?: string
    controlClass?: string
    mono?: boolean
    textarea?: boolean
    rows?: number
    /** 空值时控件内占位（浮动 label 仍用空格触发 :placeholder-shown） */
    placeholder?: string
    /** 标签置于控件上方，避免与上一行 helper 重叠 */
    labelAbove?: boolean
  }>(),
  {
    modelValue: '',
    label: '',
    placeholder: ' ',
    controlClass: '',
    mono: false,
    textarea: false,
    rows: 3,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const attrs = useAttrs()
const specForm = inject(DG_FORM_FIELD_SPEC_KEY, false)
const labelAboveEffective = computed(() => props.labelAbove ?? specForm)

const helperLine = computed(() => props.helperText || props.helper || '')

const filled = computed(() => String(props.modelValue ?? '').length > 0)

const inputClass = computed(() => [
  'md-field-control',
  props.controlClass,
  { 'md-field-control--mono': props.mono },
])

function onInput(e: Event) {
  const el = e.target as HTMLInputElement | HTMLTextAreaElement
  emit('update:modelValue', el.value)
}
</script>

<template>
  <div class="md-field-root" :class="{ 'md-field-root--label-above': labelAboveEffective }">
    <label
      v-if="labelAboveEffective && (label || $slots.label)"
      class="md-field-label-above outlined-label"
      :for="attrs.id as string | undefined"
    >
      <slot name="label">{{ label }}</slot>
    </label>
    <div
      class="md-field"
      :class="{
        'md-field--textarea': textarea,
        'md-field--filled': filled,
        'md-field--label-above': labelAboveEffective,
      }"
    >
      <textarea
        v-if="textarea"
        v-bind="attrs"
        :class="inputClass"
        :rows="rows"
        :placeholder="placeholder"
        :value="modelValue"
        @input="onInput"
      />
      <input
        v-else
        v-bind="attrs"
        :class="inputClass"
        :placeholder="placeholder"
        :value="modelValue"
        @input="onInput"
      />
      <label
        v-if="!labelAboveEffective && (label || $slots.label)"
        class="md-field-label"
        :for="attrs.id as string | undefined"
      >
        <slot name="label">{{ label }}</slot>
      </label>
    </div>
    <p v-if="helperLine || $slots.helper" class="md-field-helper">
      <slot name="helper">{{ helperLine }}</slot>
    </p>
  </div>
</template>