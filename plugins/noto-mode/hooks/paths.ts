// Path rules: where a path lands, whether it is inside the working directories,
// and which spellings are protected. Pure functions, no engine access.

export type Context = {
  /** The session's working directory, absolute. */
  cwd: string
  /** cwd, the project root and permissions.additionalDirectories, normalized. */
  workingDirs: readonly string[]
}

const hasDrive = (p: string): boolean => /^[a-zA-Z]:/.test(p)

/**
 * Folds a path spelling to one comparable form: forward slashes, `.` and `..`
 * folded, relative to `cwd`, lowercased on Windows. Undefined for a spelling
 * only the shell can expand (`~`, `$VAR`, `%VAR%`, `$env:X`) or an empty one.
 */
export function normalizePath(spelling: string, cwd: string): string | undefined {
  let s = spelling.trim().replace(/^["']+|["']+$/g, '')
  if (s === '' || s === '«sub»') return undefined
  if (/^~|\$|%[^%\s]+%/.test(s)) return undefined
  s = s.replace(/\\/g, '/')
  const gitBash = /^\/([a-zA-Z])(\/|$)/.exec(s)
  if (gitBash !== null) s = `${gitBash[1]}:/${s.slice(3)}`
  const base = cwd.replace(/\\/g, '/')
  if (!(hasDrive(s) || s.startsWith('/'))) {
    if (base === '') return undefined // relative to a directory a `cd` made unknown
    s = `${base}/${s}`
  }
  const drive = hasDrive(s) ? s.slice(0, 2) : ''
  const parts: string[] = []
  for (const seg of (drive === '' ? s : s.slice(2)).split('/')) {
    if (seg === '' || seg === '.') continue
    if (seg === '..') {
      parts.pop()
      continue
    }
    parts.push(seg)
  }
  const out = `${drive}/${parts.join('/')}`
  return hasDrive(base) || drive !== '' ? out.toLowerCase() : out
}

/** Whether `path` is `dir` or beneath it; both already normalized. */
export function isInside(path: string, dir: string): boolean {
  const d = dir.replace(/\/+$/, '')
  return path === d || path === `${d}/` || path.startsWith(`${d}/`)
}

export const isInsideAny = (path: string, dirs: readonly string[]): boolean =>
  dirs.some(d => isInside(path, d))

/** A filesystem root, a home directory, or a system directory: never deleted. */
export function isCriticalPath(path: string): boolean {
  const p = path.replace(/\/+$/, '')
  if (/^([a-z]:)?$/i.test(p)) return true
  if (/^([a-z]:)?\/(users|home)(\/[^/]+)?$/i.test(p)) return true
  if (/^\/root$/.test(p)) return true
  if (/^\/(etc|usr|bin|sbin|lib|lib64|var|boot|sys|proc|dev|opt|srv|mnt|media|applications|library|system|private|volumes)(\/|$)/i.test(p)) return true
  if (/^[a-z]:\/(windows|program files( \(x86\))?|programdata|users\/[^/]+\/appdata)(\/|$)/i.test(p)) return true
  if (/^([a-z]:)?\/(users|home)\/[^/]+\/\.(ssh|gnupg|aws|config|claude|kube|docker|azure|gcloud)$/i.test(p)) return true
  return false
}

/**
 * Paths the mod never approves a write to on its own: Claude Code's own
 * settings and transcripts, the plugin folders, git hooks. The person decides.
 */
export const NEVER_WRITE =
  /(^|\/)\.claude\/(settings[^/]*\.json|\.credentials\.json|projects(\/|$)|history\.jsonl|keybindings\.json|plugins(\/|$)|hooks(\/|$)|dev-mods(\/|$))|(^|\/)\.claude-plugin(\/|$)|(^|\/)hooks\.json$|(^|\/)\.git\/(hooks(\/|$)|config$)/i

/**
 * Credentials, shell startup files and agent instructions: an edit or a read
 * goes to the classifier, as auto mode's protected paths do.
 */
export const SENSITIVE =
  /(^|\/)(\.env(\.[^/]*)?|\.npmrc|\.pypirc|\.netrc|_netrc|\.git-credentials|\.bashrc|\.bash_profile|\.zshrc|\.zprofile|\.profile|\.gitconfig|\.bash_history|\.zsh_history|claude\.md|\.mcp\.json)$|(^|\/)\.(aws|ssh|gnupg|kube|docker|azure|gcloud|config\/gh)(\/|$)|\/(id_rsa|id_ed25519|id_ecdsa|id_dsa)(\.pub)?$|\.(pem|key|p12|pfx|jks|keystore|ppk)$|(^|\/)(secrets?|credentials?|service[-_]account[^/]*)\.(json|ya?ml|toml|txt)$/i

/** A shared scratch or cache directory, where wildcard deletes are blocked. */
export const SCRATCH = /^(\/tmp|\/var\/tmp|\/dev\/shm|[a-z]:\/users\/[^/]+\/appdata\/local\/temp|[a-z]:\/windows\/temp)(\/|$)|\/\.cache(\/|$)/i
