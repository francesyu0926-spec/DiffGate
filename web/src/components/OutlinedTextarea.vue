<script setup lang="ts">
import { computed, inject, ref, useAttrs } from 'vue'
import { DG_FORM_FIELD_SPEC_KEY } from '@/form/formFieldLayout'

defineOptions({ inheritAttrs: false })

const props = withDefaults(
  defineProps<{
    modelValue?: string
    label?: string
    helperText?: string
    rows?: number
    controlClass?: string
    allowFileImport?: boolean
    acceptFileTypes?: string
    placeholder?: string
    labelAbove?: boolean
  }>(),
  {
    modelValue: '',
    label: '',
    placeholder: ' ',
    rows: 3,
    controlClass: '',
    allowFileImport: false,
    acceptFileTypes: '.pem,.key,.txt,*',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const attrs = useAttrs()
const fileInputRef = ref<HTMLInputElement | null>(null)
const specForm = inject(DG_FORM_FIELD_SPEC_KEY, false)
const labelAboveEffective = computed(() => props.labelAbove ?? specForm)

const filled = computed(() => String(props.modelValue ?? '').length > 0)

const areaClass = computed(() => [
  'md-field-control',
  'md-field-control--textarea',
  'md-field-control--resize-y',
  props.controlClass,
  { 'md-field-control--with-import': props.allowFileImport },
])

function onInput(e: Event) {
  const el = e.target as HTMLTextAreaElement
  emit('update:modelValue', el.value)
}

function openFilePicker() {
  fileInputRef.value?.click()
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    emit('update:modelValue', String(reader.result ?? ''))
  }
  reader.readAsText(file)
  input.value = ''
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
      class="md-field md-field--textarea"
      :class="{ 'md-field--filled': filled, 'md-field--label-above': labelAboveEffective }"
    >
      <textarea
        v-bind="attrs"
        :class="areaClass"
        :rows="rows"
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
      <template v-if="allowFileImport">
        <input
          ref="fileInputRef"
          type="file"
          class="md-field-file-input"
          :accept="acceptFileTypes"
          tabindex="-1"
          @change="onFileChange"
        />
        <button type="button" class="md-field-import-btn" @click="openFilePicker">
          从文件导入
        </button>
      </template>
    </div>
    <p v-if="helperText || $slots.helper" class="md-field-helper">
      <slot name="helper">{{ helperText }}</slot>
    </p>
  </div>
</template>