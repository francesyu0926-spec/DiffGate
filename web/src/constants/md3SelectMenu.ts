/** MD3 暗色表单：v-select / v-autocomplete 下拉浮层（对齐触发框宽度 + 4px 间距） */
export const dgMd3SelectMenuProps = {
  attach: 'body' as const,
  zIndex: 3000,
  contentClass: 'dg-md3-select-menu',
  width: 'activator' as const,
  maxHeight: 320,
  location: 'bottom' as const,
  offset: 4,
  scrollStrategy: 'reposition' as const,
  elevation: 0,
} as const