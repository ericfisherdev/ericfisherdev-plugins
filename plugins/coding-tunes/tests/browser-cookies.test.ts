import { describe, expect, test } from 'claude-code/testing'

import { BrowserCookieFinder, cookieSpec, defaultProfileDir } from '../hooks/browser-cookies'
import type { LocalFiles } from '../hooks/browser-cookies'

const HOME = '/home/me'

const ZEN_INI = `[Profile0]
Name=Default (alpha)
IsRelative=1
Path=2z3ukys0.Default (alpha)

[Install6ED35B3CA1B1D2E4]
Default=2z3ukys0.Default (alpha)
Locked=1
`

const FIREFOX_INI = `[Profile1]
Name=work
IsRelative=0
Path=/data/firefox/work

[Profile0]
Name=default
IsRelative=1
Path=abcd.default
Default=1
`

const filesWith = (texts: Record<string, string>, folders: readonly string[]): LocalFiles => ({
  read: async path => texts[path],
  exists: async path => path in texts || folders.includes(path),
})

describe('defaultProfileDir', () => {
  test("prefers the install's default profile", () => {
    expect(defaultProfileDir(ZEN_INI, `${HOME}/.zen`)).toBe(`${HOME}/.zen/2z3ukys0.Default (alpha)`)
  })

  test('falls back to the profile marked Default=1, resolving relative paths', () => {
    expect(defaultProfileDir(FIREFOX_INI, `${HOME}/.mozilla/firefox`)).toBe(`${HOME}/.mozilla/firefox/abcd.default`)
  })

  test('keeps an absolute profile path as written', () => {
    const ini = '[Profile0]\nIsRelative=0\nPath=/data/firefox/work\n'
    expect(defaultProfileDir(ini, `${HOME}/.mozilla/firefox`)).toBe('/data/firefox/work')
  })
})

describe('BrowserCookieFinder', () => {
  test('lists Firefox-family profiles that hold cookies, then Chromium browsers present', async () => {
    const zenProfile = `${HOME}/.zen/2z3ukys0.Default (alpha)`
    const files = filesWith(
      {
        [`${HOME}/.zen/profiles.ini`]: ZEN_INI,
        [`${zenProfile}/cookies.sqlite`]: '',
        [`${HOME}/.mozilla/firefox/profiles.ini`]: FIREFOX_INI,
      },
      [`${HOME}/.config/BraveSoftware/Brave-Browser`],
    )
    const found = await new BrowserCookieFinder(files, HOME).find()

    expect(found).toEqual([
      { label: 'Zen', browser: 'firefox', profile: zenProfile },
      { label: 'Brave', browser: 'brave' },
    ])
  })
})

describe('cookieSpec', () => {
  test('names the profile only when there is one', () => {
    expect(cookieSpec({ label: 'Brave', browser: 'brave' })).toBe('brave')
    expect(cookieSpec({ label: 'Zen', browser: 'firefox', profile: '/p/x (alpha)' })).toBe('firefox:/p/x (alpha)')
  })
})
