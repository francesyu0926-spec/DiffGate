/** 移除仍挂在 body 上的 Vuetify 浮层（如精准回归门禁筛选菜单误显到登录页）。 */
export function dismissRegressionFilterMenus() {
  if (typeof document === 'undefined') return
  document.querySelectorAll('.regression-filter-menu').forEach((el) => {
    const overlay = el.closest('.v-overlay')
    if (overlay instanceof HTMLElement) {
      overlay.remove()
    }
  })
}