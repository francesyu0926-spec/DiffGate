import { computed, inject } from 'vue'

/** 表单项标签布局：stacked=标签在上；notch=顶边凹槽 Outlined */
export type MdFieldLayout = 'notch' | 'stacked'

export function useMdFieldLayout() {
  return inject<MdFieldLayout>('mdFieldLayout', 'notch')
}

/** `labelAbove` 显式传入时优先；否则跟随页面 `provide('mdFieldLayout')` */
export function useResolvedLabelAbove(explicit?: boolean) {
  const layout = useMdFieldLayout()
  return computed(() => {
    if (explicit !== undefined) return explicit
    return layout === 'stacked'
  })
}