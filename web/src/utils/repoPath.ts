/** 与后端 fullstack_normalize.clean_repo_rel_path 一致的 worktree 前缀剥离 */
const WORKTREE_PREFIX_RE =
  /^(?:.*?[/\\])?worktrees[/\\][0-9a-fA-F-]{8,36}[/\\](?:[^/\\]+[/\\])?/

const TOP_LEVEL = ['frontend/', 'backend/', 'web/', 'packages/'] as const

/** 去掉 worktree 沙箱前缀，保留仓库内相对路径。 */
export function cleanRepoRelativePath(path: string | undefined | null): string {
  if (!path) return ''
  let p = path.replace(/\\/g, '/').replace(/^\.\//, '').replace(/^\/+/, '')
  p = p.replace(WORKTREE_PREFIX_RE, '')
  if (TOP_LEVEL.some((t) => p.startsWith(t))) {
    return p.replace(/^\/+/, '')
  }
  for (const anchor of ['frontend/', 'backend/', 'web/', 'src/', 'app/', 'packages/']) {
    const idx = p.indexOf(anchor)
    if (idx > 0) {
      p = p.slice(idx)
      break
    }
  }
  return p.replace(/^\/+/, '')
}

export function splitRepoPath(path: string | undefined | null) {
  const full = cleanRepoRelativePath(path)
  if (!full) return { full: '', dir: '', name: '' }
  const parts = full.split('/')
  const name = parts[parts.length - 1] ?? full
  const dir = parts.length > 1 ? parts.slice(0, -1).join('/') : ''
  return { full, dir, name }
}