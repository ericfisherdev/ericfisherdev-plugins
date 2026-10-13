/** Browsers yt-dlp reads cookies from (`--cookies-from-browser`). */
export type CookieBrowser = 'firefox' | 'chrome' | 'chromium' | 'brave' | 'edge' | 'opera' | 'vivaldi'

/** A browser login yt-dlp signs YouTube requests with, for private playlists. */
export type YtCookieSource = {
  /** What the person sees: "Zen", "Firefox", "Brave". */
  label: string
  browser: CookieBrowser
  /** Absolute profile folder, for Firefox forks yt-dlp does not know by name. */
  profile?: string
}

/** Reads the person's own files, outside the shared runtime folder. */
export interface LocalFiles {
  /** Resolves undefined when the file is missing or unreadable. */
  read(path: string): Promise<string | undefined>
  exists(path: string): Promise<boolean>
}

/** The saved choice of browser login, or none. */
export interface CookieSourceSetting {
  ytCookieSource(): Promise<YtCookieSource | null>
}

/** The value of yt-dlp's `--cookies-from-browser`. */
export const cookieSpec = (source: YtCookieSource): string =>
  source.profile === undefined ? source.browser : `${source.browser}:${source.profile}`

const FIREFOX_FAMILY: readonly { label: string; dir: string }[] = [
  { label: 'Zen', dir: '.zen' },
  { label: 'Firefox', dir: '.mozilla/firefox' },
  { label: 'LibreWolf', dir: '.librewolf' },
  { label: 'Floorp', dir: '.floorp' },
]

const CHROMIUM_FAMILY: readonly { label: string; browser: CookieBrowser; dir: string }[] = [
  { label: 'Chrome', browser: 'chrome', dir: '.config/google-chrome' },
  { label: 'Brave', browser: 'brave', dir: '.config/BraveSoftware/Brave-Browser' },
  { label: 'Chromium', browser: 'chromium', dir: '.config/chromium' },
  { label: 'Vivaldi', browser: 'vivaldi', dir: '.config/vivaldi' },
  { label: 'Edge', browser: 'edge', dir: '.config/microsoft-edge' },
  { label: 'Opera', browser: 'opera', dir: '.config/opera' },
]

type IniSections = Map<string, Map<string, string>>

/**
 * The profile folder a Firefox-family `profiles.ini` starts by default:
 * the install's `Default`, else the profile marked `Default=1`, else the first.
 * Relative paths are resolved against `root`.
 */
export const defaultProfileDir = (profilesIni: string, root: string): string | undefined => {
  const sections = parseIni(profilesIni)
  const profiles = [...sections].filter(([name]) => name.startsWith('Profile')).map(([, keys]) => keys)
  const installDefault = [...sections].find(([name, keys]) => name.startsWith('Install') && keys.has('Default'))?.[1].get('Default')
  if (installDefault !== undefined) return resolveProfile(installDefault, true, root)
  const chosen = profiles.find(keys => keys.get('Default') === '1') ?? profiles[0]
  const path = chosen?.get('Path')
  if (chosen === undefined || path === undefined) return undefined

  return resolveProfile(path, chosen.get('IsRelative') !== '0', root)
}

/** Finds the browser logins on this machine that yt-dlp can read. */
export class BrowserCookieFinder {
  constructor(
    private readonly files: LocalFiles,
    private readonly homeDir: string,
  ) {}

  async find(): Promise<YtCookieSource[]> {
    const firefox = await Promise.all(FIREFOX_FAMILY.map(family => this.firefoxProfile(family.label, family.dir)))
    const chromium = await Promise.all(
      CHROMIUM_FAMILY.map(async family =>
        (await this.files.exists(`${this.homeDir}/${family.dir}`)) ? { label: family.label, browser: family.browser } : undefined,
      ),
    )

    return [...firefox, ...chromium].filter((source): source is YtCookieSource => source !== undefined)
  }

  private async firefoxProfile(label: string, dir: string): Promise<YtCookieSource | undefined> {
    const root = `${this.homeDir}/${dir}`
    const ini = await this.files.read(`${root}/profiles.ini`)
    const profile = ini === undefined ? undefined : defaultProfileDir(ini, root)
    if (profile === undefined || !(await this.files.exists(`${profile}/cookies.sqlite`))) return undefined

    return { label, browser: 'firefox', profile }
  }
}

const resolveProfile = (path: string, isRelative: boolean, root: string): string =>
  isRelative ? `${root}/${path}` : path

const parseIni = (text: string): IniSections => {
  const sections: IniSections = new Map()
  let current: Map<string, string> | undefined
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim()
    const header = /^\[(.+)\]$/.exec(line)
    if (header !== null) {
      current = new Map()
      sections.set(header[1] ?? '', current)
      continue
    }
    const separator = line.indexOf('=')
    if (current !== undefined && separator > 0) current.set(line.slice(0, separator), line.slice(separator + 1))
  }

  return sections
}
