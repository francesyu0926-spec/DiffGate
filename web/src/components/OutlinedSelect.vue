<script setup lang="ts">
import { computed, inject, onMounted, onUnmounted, ref, watch } from 'vue'
import { DG_FORM_FIELD_SPEC_KEY } from '@/form/formFieldLayout'

export type OutlinedSelectOption = {
  value: string
  label: string
  badge?: string
  description?: string
  disabled?: boolean
}

const props = withDefaults(
  defineProps<{
    label?: string
    options: OutlinedSelectOption[]
    modelValue?: string | string[]
    multiple?: boolean
    searchable?: boolean
    freeSolo?: boolean
    helperText?: string
    disabled?: boolean
    clearable?: boolean
    labelAbove?: boolean
    placeholder?: string
    loading?: boolean
    /** 多选菜单左侧展示 MD3 复选框样式 */
    menuCheckboxes?: boolean
    /** 多选标签前展示小图标（如 repo） */
    tagLeadingIcon?: 'repo' | ''
    /** 选项列表为空时不展开菜单（由 trigger 侧快捷操作代替） */
    suppressMenuWhenEmpty?: boolean
    /** 浮层菜单附加 class（如新建用例集 MD3） */
    menuSurfaceClass?: string
    /** 仅当选项数大于该值时才展示菜单内搜索框（未设置则沿用 searchable） */
    searchableMin?: number
    /** 默认值（如 `.`）不显示清除；自定义值仅在悬停/聚焦时显示清除 */
    smartClear?: boolean
  }>(),
  {
    label: '',
    modelValue: '',
    multiple: false,
    searchable: false,
    freeSolo: false,
    disabled: false,
    clearable: false,
    placeholder: '',
    loading: false,
    menuCheckboxes: false,
    tagLeadingIcon: '',
    suppressMenuWhenEmpty: false,
    menuSurfaceClass: '',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string | string[]]
}>()

const menuUid = `md-select-${Math.random().toString(36).slice(2, 10)}`
const specForm = inject(DG_FORM_FIELD_SPEC_KEY, false)
const labelAboveEffective = computed(() => props.labelAbove ?? specForm)

const open = ref(false)
const keyword = ref('')
const triggerHover = ref(false)
const triggerFocused = ref(false)
const rootRef = ref<HTMLElement | null>(null)
const triggerRef = ref<HTMLElement | null>(null)
const menuRef = ref<HTMLElement | null>(null)
const freeInputRef = ref<HTMLInputElement | null>(null)

const menuStyle = ref<{ top: string; left: string; width: string }>({
  top: '0px',
  left: '0px',
  width: '0px',
})

const selectedArray = computed(() => {
  if (props.multiple) {
    return Array.isArray(props.modelValue) ? props.modelValue : []
  }
  const v = props.modelValue
  return v != null && String(v).length > 0 ? [String(v)] : []
})

const hasValue = computed(() => {
  if (props.multiple) return selectedArray.value.length > 0
  if (props.freeSolo) return String(props.modelValue ?? '').length > 0
  return selectedArray.value.length > 0
})

const catalogEmpty = computed(() => props.options.length === 0)

const floatingLabel = computed(() => !labelAboveEffective.value)

const showInlinePlaceholder = computed(() => {
  if (!props.placeholder) return false
  if (labelAboveEffective.value) return !hasValue.value
  return !hasValue.value && open.value
})

const showChevron = computed(
  () => !(props.suppressMenuWhenEmpty && catalogEmpty.value && !hasValue.value),
)

const showMenuSearch = computed(() => {
  if (!props.searchable || props.freeSolo) return false
  const min = props.searchableMin
  if (min == null) return props.options.length > 0
  return props.options.length > min
})

const showClearButton = computed(() => {
  if (!props.clearable || props.multiple || props.disabled || props.loading) return false
  if (!hasValue.value) return false
  if (!props.smartClear) return true
  const v = String(props.modelValue ?? '').trim()
  if (v === '.' || v === '') return false
  return triggerFocused.value || triggerHover.value || open.value
})

const filteredOptions = computed(() => {
  let kw = keyword.value.trim().toLowerCase()
  if (!kw && props.freeSolo && !props.multiple) {
    kw = String(props.modelValue ?? '').trim().toLowerCase()
  }
  if (!kw) return props.options
  return props.options.filter(
    (opt) =>
      opt.label.toLowerCase().includes(kw) ||
      opt.value.toLowerCase().includes(kw),
  )
})

function getOptionLabel(val: string) {
  return props.options.find((o) => o.value === val)?.label ?? val
}

function updateMenuPosition() {
  const el = triggerRef.value
  if (!el) return
  const r = el.getBoundingClientRect()
  menuStyle.value = {
    top: `${r.bottom + 4}px`,
    left: `${r.left}px`,
    width: `${r.width}px`,
  }
}

function openMenu() {
  if (props.disabled || props.loading) return
  if (props.suppressMenuWhenEmpty && catalogEmpty.value && !hasValue.value) return
  if (!open.value) {
    open.value = true
    updateMenuPosition()
  }
}

function toggleOpen() {
  if (props.disabled || props.loading) return
  if (props.suppressMenuWhenEmpty && catalogEmpty.value && !hasValue.value) return
  open.value = !open.value
  if (open.value) {
    updateMenuPosition()
    if (props.freeSolo && !props.multiple) {
      requestAnimationFrame(() => freeInputRef.value?.focus())
    }
  }
}

function onTriggerClick() {
  if (props.freeSolo && !props.multiple) {
    openMenu()
    requestAnimationFrame(() => freeInputRef.value?.focus())
    return
  }
  toggleOpen()
}

function onFreeSoloFocus() {
  openMenu()
}

function onFreeSoloInputClick() {
  openMenu()
}

function close() {
  open.value = false
  keyword.value = ''
}

function isOptionDisabled(optValue: string) {
  return Boolean(props.options.find((o) => o.value === optValue)?.disabled)
}

function handleSelectOption(optValue: string) {
  if (isOptionDisabled(optValue)) return
  if (props.multiple) {
    const exists = selectedArray.value.includes(optValue)
    const next = exists
      ? selectedArray.value.filter((v) => v !== optValue)
      : [...selectedArray.value, optValue]
    emit('update:modelValue', next)
    return
  }
  emit('update:modelValue', optValue)
  close()
}

function removeTag(e: MouseEvent, tagVal: string) {
  e.stopPropagation()
  emit(
    'update:modelValue',
    selectedArray.value.filter((v) => v !== tagVal),
  )
}

function clearValue(e: MouseEvent) {
  e.stopPropagation()
  emit('update:modelValue', props.multiple ? [] : '')
  close()
}

function onFreeInput(e: Event) {
  const el = e.target as HTMLInputElement
  emit('update:modelValue', el.value)
  if (!props.multiple && props.freeSolo) openMenu()
}

function onTriggerKeydown(e: KeyboardEvent) {
  if (props.disabled) return
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    if (props.freeSolo && !props.multiple) onTriggerClick()
    else toggleOpen()
  }
  if (e.key === 'Escape') close()
}

function onClickOutside(e: MouseEvent) {
  const t = e.target as Node
  if (rootRef.value?.contains(t)) return
  if (menuRef.value?.contains(t)) return
  close()
}

function onScrollOrResize() {
  if (open.value) updateMenuPosition()
}

watch(open, (isOpen) => {
  if (isOpen) {
    updateMenuPosition()
    requestAnimationFrame(updateMenuPosition)
    if (props.searchable && !props.freeSolo) {
      requestAnimationFrame(() => {
        menuRef.value?.querySelector<HTMLInputElement>('.md-field-select-search input')?.focus()
      })
    }
  }
})

onMounted(() => {
  document.addEventListener('mousedown', onClickOutside)
  window.addEventListener('scroll', onScrollOrResize, true)
  window.addEventListener('resize', onScrollOrResize)
})

onUnmounted(() => {
  document.removeEventListener('mousedown', onClickOutside)
  window.removeEventListener('scroll', onScrollOrResize, true)
  window.removeEventListener('resize', onScrollOrResize)
})
</script>

<template>
  <div ref="rootRef" class="md-field-root" :class="{ 'md-field-root--label-above': labelAboveEffective }">
    <label
      v-if="labelAboveEffective && (label || $slots.label)"
      class="md-field-label-above outlined-label"
    >
      <slot name="label">{{ label }}</slot>
    </label>
    <div
      class="md-field md-field-select"
      :class="{
        'md-field--open': open,
        'md-field--filled': hasValue,
        'md-field--label-above': labelAboveEffective,
        'md-field-select--floating-label': floatingLabel,
        'md-field-select--disabled': disabled,
        'md-field-select--loading': loading,
        'md-field-select--catalog-empty': catalogEmpty && suppressMenuWhenEmpty,
      }"
    >
      <div
        ref="triggerRef"
        class="md-field-control md-field-select-trigger"
        role="combobox"
        :aria-expanded="open"
        :aria-controls="`${menuUid}-menu`"
        :tabindex="disabled ? -1 : 0"
        @click="onTriggerClick"
        @keydown="onTriggerKeydown"
        @focusin="triggerFocused = true"
        @focusout="triggerFocused = false"
        @mouseenter="triggerHover = true"
        @mouseleave="triggerHover = false"
      >
        <div class="md-field-select-values">
          <template v-if="multiple">
            <span
              v-for="val in selectedArray"
              :key="val"
              class="md-field-tag"
              :class="{ 'md-field-tag--with-icon': tagLeadingIcon === 'repo' }"
            >
              <svg
                v-if="tagLeadingIcon === 'repo'"
                class="md-field-tag__icon"
                viewBox="0 0 24 24"
                fill="none"
                aria-hidden="true"
              >
                <path
                  d="M3 7a2 2 0 012-2h5l2 2h9a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"
                  stroke="currentColor"
                  stroke-width="1.75"
                  stroke-linejoin="round"
                />
              </svg>
              <span class="md-field-tag__text">{{ getOptionLabel(val) }}</span>
              <button
                type="button"
                class="md-field-tag__remove"
                aria-label="移除"
                @click="removeTag($event, val)"
              >
                ×
              </button>
            </span>
            <span
              v-if="!selectedArray.length && showInlinePlaceholder"
              class="md-field-select-placeholder"
            >
              {{ placeholder }}
            </span>
          </template>
          <input
            v-else-if="freeSolo"
            ref="freeInputRef"
            type="text"
            class="md-field-select-free-input"
            :value="String(modelValue ?? '')"
            :disabled="disabled"
            @click.stop="onFreeSoloInputClick"
            @focus="onFreeSoloFocus"
            @input="onFreeInput"
          />
          <span
            v-else-if="!multiple && hasValue"
            class="md-field-select-single-value"
          >
            <slot name="selection" :label="getOptionLabel(String(modelValue))">
              {{ getOptionLabel(String(modelValue)) }}
            </slot>
          </span>
          <span
            v-else-if="!multiple && showInlinePlaceholder"
            class="md-field-select-placeholder"
          >
            {{ placeholder }}
          </span>
        </div>
        <div class="md-field-select-trigger-end">
          <slot name="trigger-affix" />
          <span v-if="loading" class="md-field-select-loading" aria-hidden="true" />
          <button
            v-if="showClearButton"
            type="button"
            class="md-field-select-clear"
            :class="{ 'md-field-select-clear--smart': smartClear }"
            aria-label="清除"
            @click="clearValue"
          >
            ×
          </button>
          <slot v-if="!showChevron" name="empty-trigger-action" />
          <svg
            v-else
            class="md-field-select-chevron"
            :class="{ 'md-field-select-chevron--open': open }"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </div>
      <label v-if="!labelAboveEffective && (label || $slots.label)" class="md-field-label">
        <slot name="label">{{ label }}</slot>
      </label>
    </div>
    <Teleport to="body">
      <div
        v-if="open"
        :id="`${menuUid}-menu`"
        ref="menuRef"
        class="md-field-select-menu md-field-select-menu--floating"
        :class="menuSurfaceClass"
        :style="menuStyle"
        :data-md-select-menu="menuUid"
      >
        <div v-if="showMenuSearch" class="md-field-select-search">
          <input
            v-model="keyword"
            type="text"
            placeholder="输入关键字过滤..."
            @click.stop
          />
        </div>
        <div class="md-field-select-options">
          <div
            v-if="filteredOptions.length === 0"
            class="md-field-select-empty"
          >
            <slot name="empty">暂无匹配选项</slot>
          </div>
          <button
            v-for="opt in filteredOptions"
            :key="opt.value"
            type="button"
            class="md-field-select-option"
            :class="{
              'md-field-select-option--selected': selectedArray.includes(opt.value),
              'md-field-select-option--disabled': opt.disabled,
            }"
            :disabled="opt.disabled"
            @click.stop="handleSelectOption(opt.value)"
          >
            <span
              v-if="multiple && menuCheckboxes"
              class="md-field-select-option__checkbox"
              :class="{ 'md-field-select-option__checkbox--on': selectedArray.includes(opt.value) }"
              aria-hidden="true"
            />
            <slot name="option" :option="opt">
              <div class="md-field-select-option__main">
                <span class="md-field-select-option__title-row">
                  <span class="md-field-select-option__label">{{ opt.label }}</span>
                  <span v-if="opt.badge" class="md-field-select-option__badge">{{ opt.badge }}</span>
                </span>
                <div v-if="opt.description" class="md-field-select-option__desc">
                  {{ opt.description }}
                </div>
              </div>
            </slot>
            <svg
              v-if="selectedArray.includes(opt.value) && !(multiple && menuCheckboxes)"
              class="md-field-select-check"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
            >
              <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          </button>
        </div>
        <div v-if="$slots['menu-footer']" class="md-field-select-menu-footer">
          <slot name="menu-footer" />
        </div>
      </div>
    </Teleport>
    <p v-if="helperText || $slots.helper" class="md-field-helper">
      <slot name="helper">{{ helperText }}</slot>
    </p>
  </div>
</template>