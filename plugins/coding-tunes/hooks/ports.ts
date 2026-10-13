import type { TunesSnapshot } from '../types'
import type { LocalFiles } from './browser-cookies'

/** Runs a host command by argv. Rejects when it cannot start or times out. */
export interface CommandRunner {
  run(argv: readonly string[], timeoutMs?: number): Promise<{ exitCode: number; stdout: string; stderr: string }>
}

export type HttpReply = { status: number; ok: boolean; text: string }

/** Plain HTTP(S) requests. Rejects only when the request cannot be made. */
export interface HttpClient {
  request(url: string, init: { method: string; headers?: Record<string, string>; body?: string }): Promise<HttpReply>
}

/** Files shared between every Claude session on this machine. */
export interface SharedFiles {
  /** Resolves undefined when the file is missing or unreadable. */
  read(path: string): Promise<string | undefined>
  write(path: string, text: string): Promise<void>
  /** Resolves the file names in `dir`, empty when it is missing. */
  list(dir: string): Promise<string[]>
  remove(path: string): Promise<void>
}

/** This plugin's JSON store, kept across sessions. */
export interface KeyValueStore {
  get(key: string): Promise<unknown>
  set(key: string, value: unknown): Promise<void>
}

export interface Clock {
  now(): Promise<number>
}

/** Where the latest view of the player goes (the pane's `$.state`). */
export interface SnapshotSink {
  show(snapshot: TunesSnapshot): Promise<void>
}

/** Messages to the person outside the pane. */
export interface Notifier {
  /** A short toast. */
  notify(text: string): void
  /** A dim transcript line, for text they may need to copy. */
  log(text: string): void
}

/** Asks the person a multiple-choice question; "Other" answers free text. Rejects when dismissed. */
export interface Prompter {
  ask(question: string, options: readonly string[]): Promise<string>
}

/** Everything the mod needs from the engine, as plain collaborators. */
export type HostPorts = {
  runner: CommandRunner
  http: HttpClient
  files: SharedFiles
  /** The person's own files, for finding browser profiles. */
  localFiles: LocalFiles
  store: KeyValueStore
  clock: Clock
  snapshots: SnapshotSink
  notifier: Notifier
  prompter: Prompter
  /** The plugin's own folder, holding bin/. */
  pluginRoot: string
  /** Per-user runtime folder ($XDG_RUNTIME_DIR), shared by every session. */
  runtimeDir: string
  /** $HOME, where browser profiles live. */
  homeDir: string
  sessionId: string
}
