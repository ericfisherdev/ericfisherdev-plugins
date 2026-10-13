import type { Clock, CommandRunner, HttpClient, KeyValueStore } from '../ports'
import { PlayerError } from './music-player'

export const SPOTIFY_REDIRECT_PORT = 8898
export const SPOTIFY_REDIRECT_URI = `http://127.0.0.1:${SPOTIFY_REDIRECT_PORT}/callback`
const SCOPES = 'user-read-playback-state user-modify-playback-state user-read-currently-playing'
const TOKEN_URL = 'https://accounts.spotify.com/api/token'
const TOKENS_KEY = 'spotifyTokens'
const REFRESH_MARGIN_MS = 60_000
const LOGIN_TIMEOUT_S = 300

type StoredTokens = {
  clientId: string
  accessToken: string
  refreshToken: string
  expiresAt: number
}

type TokenReply = { access_token: string; refresh_token?: string; expires_in: number }

/** Opens the login page and waits for the redirect's code. */
export interface LoginBrowser {
  /** Resolves the authorization code; rejects when denied or timed out. */
  login(authorizeUrl: string, state: string): Promise<string>
}

/** Supplies a valid Spotify access token. */
export interface AccessTokenSource {
  /** Rejects with PlayerError `not-authorized` when no usable login exists. */
  accessToken(): Promise<string>
}

/** Spotify's Authorization Code with PKCE flow; tokens kept in the plugin store. */
export class SpotifyAuth implements AccessTokenSource {
  constructor(
    private readonly http: HttpClient,
    private readonly store: KeyValueStore,
    private readonly clock: Clock,
  ) {}

  async accessToken(): Promise<string> {
    const tokens = (await this.store.get(TOKENS_KEY)) as StoredTokens | undefined
    if (tokens === undefined) throw new PlayerError('not-authorized', 'Spotify is not linked: run /coding-tunes --setup')
    if (tokens.expiresAt - REFRESH_MARGIN_MS > (await this.clock.now())) return tokens.accessToken

    return (await this.refresh(tokens)).accessToken
  }

  /** Rejects with PlayerError `not-authorized` when the login fails. */
  async authorize(clientId: string, browser: LoginBrowser): Promise<void> {
    const verifier = randomUrlSafe(64)
    const state = randomUrlSafe(16)
    const params = new URLSearchParams({
      client_id: clientId,
      response_type: 'code',
      redirect_uri: SPOTIFY_REDIRECT_URI,
      scope: SCOPES,
      code_challenge_method: 'S256',
      code_challenge: await codeChallenge(verifier),
      state,
    })
    const code = await browser.login(`https://accounts.spotify.com/authorize?${params}`, state)
    const reply = await this.requestTokens({
      grant_type: 'authorization_code',
      code,
      redirect_uri: SPOTIFY_REDIRECT_URI,
      client_id: clientId,
      code_verifier: verifier,
    })
    await this.save(clientId, reply, undefined)
  }

  private async refresh(tokens: StoredTokens): Promise<StoredTokens> {
    const reply = await this.requestTokens({
      grant_type: 'refresh_token',
      refresh_token: tokens.refreshToken,
      client_id: tokens.clientId,
    })

    return this.save(tokens.clientId, reply, tokens.refreshToken)
  }

  private async requestTokens(form: Record<string, string>): Promise<TokenReply> {
    const reply = await this.http.request(TOKEN_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams(form).toString(),
    })
    if (!reply.ok) throw new PlayerError('not-authorized', `Spotify login failed (${reply.status}): run /coding-tunes --setup`)

    return JSON.parse(reply.text) as TokenReply
  }

  private async save(clientId: string, reply: TokenReply, previousRefresh: string | undefined): Promise<StoredTokens> {
    const tokens: StoredTokens = {
      clientId,
      accessToken: reply.access_token,
      refreshToken: reply.refresh_token ?? previousRefresh ?? '',
      expiresAt: (await this.clock.now()) + reply.expires_in * 1000,
    }
    await this.store.set(TOKENS_KEY, tokens)

    return tokens
  }
}

/** Opens the page with xdg-open and catches the redirect with bin/oauth_callback.py. */
export class XdgLoginBrowser implements LoginBrowser {
  constructor(
    private readonly runner: CommandRunner,
    private readonly callbackHelper: string,
    private readonly announce: (url: string) => void,
  ) {}

  async login(authorizeUrl: string, state: string): Promise<string> {
    this.announce(authorizeUrl)
    void this.runner.run(['xdg-open', authorizeUrl], 10_000).catch(() => undefined)
    const argv = ['python3', '-I', this.callbackHelper, String(SPOTIFY_REDIRECT_PORT), state, String(LOGIN_TIMEOUT_S)]
    const result = await this.runner.run(argv, (LOGIN_TIMEOUT_S + 10) * 1000)
    if (result.exitCode !== 0) throw new PlayerError('not-authorized', 'Spotify login was denied or timed out')

    return result.stdout.trim()
  }
}

const URL_SAFE = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~'

const randomUrlSafe = (length: number): string =>
  Array.from(crypto.getRandomValues(new Uint8Array(length)), byte => URL_SAFE[byte % URL_SAFE.length]).join('')

const codeChallenge = async (verifier: string): Promise<string> => {
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier)))

  return btoa(String.fromCharCode(...digest)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}
