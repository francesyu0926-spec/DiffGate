/** 滚动时短暂显示滚动条（原生 + Element Plus），静止后自动隐藏 */

const ACTIVE_CLASS = 'diffgate-scrollbar-active'
const IDLE_MS = 720

const hideTimers = new WeakMap<Element, number>()

function scheduleIdle(el: Element) {
  const prev = hideTimers.get(el)
  if (prev != null) window.clearTimeout(prev)
  hideTimers.set(
    el,
    window.setTimeout(() => {
      el.classList.remove(ACTIVE_CLASS)
      hideTimers.delete(el)
    }, IDLE_MS),
  )
}

function activate(el: Element) {
  el.classList.add(ACTIVE_CLASS)
  scheduleIdle(el)
  const ep = el.closest('.el-scrollbar')
  if (ep && ep !== el) {
    ep.classList.add(ACTIVE_CLASS)
    scheduleIdle(ep)
  }
}

function isViewportScrollTarget(target: EventTarget | null): boolean {
  return (
    target === document ||
    target === document.documentElement ||
    target === document.body
  )
}

function activateViewport() {
  activate(document.documentElement)
  activate(document.body)
}

function onScroll(ev: Event) {
  if (isViewportScrollTarget(ev.target)) {
    activateViewport()
    return
  }
  if (ev.target instanceof Element) {
    activate(ev.target)
  }
}

function isScrollable(el: Element): boolean {
  const s = getComputedStyle(el)
  const y = s.overflowY
  const x = s.overflowX
  const canY = (y === 'auto' || y === 'scroll' || y === 'overlay') && el.scrollHeight > el.clientHeight + 1
  const canX = (x === 'auto' || x === 'scroll' || x === 'overlay') && el.scrollWidth > el.clientWidth + 1
  return canY || canX
}

function scrollableFromPoint(start: Element | null): Element | null {
  let node = start
  while (node && node !== document.body) {
    if (isScrollable(node)) return node
    node = node.parentElement
  }
  if (document.documentElement.scrollHeight > document.documentElement.clientHeight + 1) {
    return document.documentElement
  }
  return null
}

function onWheel(ev: WheelEvent) {
  const start = ev.target instanceof Element ? ev.target : null
  const el = scrollableFromPoint(start)
  if (el) activate(el)
}

let installed = false

export function installScrollOverlayScrollbar() {
  if (installed || typeof window === 'undefined') return
  installed = true
  document.addEventListener('scroll', onScroll, { capture: true, passive: true })
  document.addEventListener('wheel', onWheel, { capture: true, passive: true })
}