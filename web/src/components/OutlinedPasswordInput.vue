<script setup lang="ts">
import { computed, inject, ref, useAttrs } from 'vue'
import { DG_FORM_FIELD_SPEC_KEY } from '@/form/formFieldLayout'

defineOptions({ inheritAttrs: false })

const props = withDefaults(
  defineProps<{
    modelValue?: string
    label?: string
    helperText?: string
    controlClass?: string
    allowPaste?: boolean
    placeholder?: string
    labelAbove?: boolean
  }>(),
  {
    modelValue: '',
    label: '',
    controlClass: '',
    allowPaste: false,
    placeholder: ' ',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const attrs = useAttrs()
const visible = ref(false)
const specForm = inject(DG_FORM_FIELD_SPEC_KEY, false)
const labelAboveEffective = computed(() => props.labelAbove ?? specForm)

const filled = computed(() => String(props.modelValue ?? '').length > 0)

const inputClass = computed(() => [
  'md-field-control',
  'md-field-control--password',
  props.controlClass,
  { 'md-field-control--password-paste': props.allowPaste },
])

function onInput(e: Event) {
  const el = e.target as HTMLInputElement
  emit('update:modelValue', el.value)
}

function toggleVisible() {
  visible.value = !visible.value
}

async function pasteFromClipboard() {
  try {
    const text = await navigator.clipboard.readText()
    if (text) emit('update:modelValue', text.trim())
  } catch {
    /* 剪贴板权限拒绝 */
  }
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
      :class="{ 'md-field--filled': filled, 'md-field--label-above': labelAboveEffective }"
    >
      <input
        v-bind="attrs"
        :type="visible ? 'text' : 'password'"
        :class="inputClass"
        :placeholder="placeholder"
        :value="modelValue"
        autocomplete="off"
        @input="onInput"
      />
      <label
        v-if="!labelAboveEffective && (label || $slots.label)"
        class="md-field-label"
        :for="attrs.id as string | undefined"
      >
        <slot name="label">{{ label }}</slot>
      </label>
      <div class="md-field-affix">
        <button
          v-if="allowPaste"
          type="button"
          class="md-field-affix-btn"
          title="从剪贴板粘贴"
          @click="pasteFromClipboard"
        >
          <svg class="md-field-affix-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"
            />
          </svg>
        </button>
        <button
          type="button"
          class="md-field-affix-btn"
          :title="visible ? '隐藏内容' : '显示明文'"
          @click="toggleVisible"
        >
          <svg
            v-if="visible"
            class="md-field-affix-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"
            />
          </svg>
          <svg
            v-else
            class="md-field-affix-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
          >
            <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
            />
          </svg>
        </button>
      </div>
    </div>
    <p v-if="helperText || $slots.helper" class="md-field-helper">
      <slot name="helper">{{ helperText }}</slot>
    </p>
  </div>
</template>