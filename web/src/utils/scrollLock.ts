/** 抽屉/遮罩打开时锁定底层页面滚动（兼容 Vuetify v-main + 窗口滚动） */
let locked = false
let savedScrollY = 0

function preventBackgroundScroll(e: Event) {
  const target = e.target
  if (!(target instanceof Element)) return
  if (
    target.closest(
      '.el-drawer__body, .el-drawer, .cdd-body, .cdd-pre, .v-navigation-drawer__content, .v-overlay__content, .fs-unresolved-drawer__list',
    )
  ) {
    return
  }
  e.preventDefault()
}

function applyLock() {
  savedScrollY = window.scrollY
  document.documentElement.classList.add('diffgate-scroll-lock')
  document.body.classList.add('diffgate-scroll-lock')
  document.body.style.position = 'fixed'
  document.body.style.top = `-${savedScrollY}px`
  document.body.style.left = '0'
  document.body.style.right = '0'
  document.body.style.width = '100%'
  window.addEventListener('wheel', preventBackgroundScroll, { passive: false, capture: true })
  window.addEventListener('touchmove', preventBackgroundScroll, { passive: false, capture: true })
}

function releaseLock() {
  window.removeEventListener('wheel', preventBackgroundScroll, { capture: true })
  window.removeEventListener('touchmove', preventBackgroundScroll, { capture: true })
  document.documentElement.classList.remove('diffgate-scroll-lock')
  document.body.classList.remove('diffgate-scroll-lock')
  document.body.style.position = ''
  document.body.style.top = ''
  document.body.style.left = ''
  document.body.style.right = ''
  document.body.style.width = ''
  window.scrollTo(0, savedScrollY)
}

/** 根据「是否有任意抽屉打开」同步锁定状态，避免重复 lock 导致无法解锁 */
export function syncPageScrollLock(shouldLock: boolean) {
  if (shouldLock === locked) return
  locked = shouldLock
  if (locked) applyLock()
  else releaseLock()
}

export function forceUnlockPageScroll() {
  if (!locked) return
  locked = false
  releaseLock()
}

/** @deprecated 使用 syncPageScrollLock */
export function lockPageScroll() {
  syncPageScrollLock(true)
}

/** @deprecated 使用 syncPageScrollLock */
export function unlockPageScroll() {
  syncPageScrollLock(false)
}