<script setup lang="ts">
import { computed, ref, useAttrs, useSlots } from 'vue'

defineOptions({ inheritAttrs: false })

const props = withDefaults(
  defineProps<{
    modelValue?: string
    /** 浮动标签文案 */
    label?: string
    placeholder?: string
    helperText?: string
    counter?: string
    error?: string
    mono?: boolean
    maxlength?: number
  }>(),
  {
    modelValue: '',
    label: '',
    placeholder: '',
    helperText: '',
    counter: '',
    error: '',
    mono: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  blur: [event: FocusEvent]
}>()

const attrs = useAttrs()
const slots = useSlots()
const focused = ref(false)

const hasValue = computed(() => String(props.modelValue ?? '').length > 0)
const floated = computed(() => focused.value || hasValue.value)
const showError = computed(() => Boolean(props.error))

const inputClass = computed(() => [
  'md3-filled__input',
  {
    'md3-filled__input--mono': props.mono,
    'md3-filled__input--with-append': Boolean(slots.append),
  },
])

function onInput(e: Event) {
  const el = e.target as HTMLInputElement
  emit('update:modelValue', el.value)
}

function onFocus() {
  focused.value = true
}

function onBlur(e: FocusEvent) {
  focused.value = false
  emit('blur', e)
}
</script>

<template>
  <div
    class="md3-filled"
    :class="{
      'md3-filled--focused': focused,
      'md3-filled--floated': floated,
      'md3-filled--error': showError,
    }"
  >
    <div class="md3-filled__box">
      <input
        v-bind="attrs"
        :class="inputClass"
        :value="modelValue"
        :placeholder="focused ? placeholder : ' '"
        :maxlength="maxlength"
        @input="onInput"
        @focus="onFocus"
        @blur="onBlur"
      />
      <label v-if="label || $slots.label" class="md3-filled__label" :for="attrs.id as string | undefined">
        <slot name="label">{{ label }}</slot>
      </label>
      <div v-if="$slots.append" class="md3-filled__append">
        <slot name="append" />
      </div>
    </div>
    <div v-if="helperText || counter || error || $slots.helper" class="md3-filled__footer">
      <span v-if="error" class="md3-filled__helper md3-filled__helper--error" role="alert">{{ error }}</span>
      <span v-else-if="$slots.helper" class="md3-filled__helper">
        <slot name="helper" />
      </span>
      <span v-else-if="helperText" class="md3-filled__helper">{{ helperText }}</span>
      <span v-else class="md3-filled__helper" aria-hidden="true" />
      <span v-if="counter" class="md3-filled__counter">{{ counter }}</span>
    </div>
  </div>
</template>