// Judges one shell command line (Bash or PowerShell). Pure.

import { type Context, normalizePath, isInside, isInsideAny, isCriticalPath, NEVER_WRITE, SENSITIVE, SCRATCH } from './paths'
import { splitShell, baseName, SUB, type Flavor, type Segment } from './shell'
import * as R from './rules'
import { type Decision, allow, ask, classify, worse, NEVER_FIX, ADD_DIR_FIX, CLASSIFIER_FIX } from './decision'

const set = (names: string): ReadonlySet<string> => new Set(names.split(/\s+/).filter(Boolean))
const PACKAGE_MANAGERS = set('npm pnpm yarn bun npx bunx pip pip3 pipx uv poetry pipenv conda cargo go dotnet mvn mvnw gradle gradlew make cmake ninja just task rake composer bundle bundler gem mix swift stack cabal flutter dart')
const CLIS = set('docker podman docker-compose kubectl oc gh aws gcloud az terraform tofu')
const SQL = set('psql mysql mysqlsh sqlite3 mongosh mongo redis-cli mycli pgcli usql duckdb sqlcmd')
const SYSTEM_PKG = set('brew apt apt-get yum dnf pacman choco winget scoop snap port zypper apk')
const KILLERS = set('kill pkill killall taskkill stop-process spps')
const OPENERS = set('open start xdg-open explorer start-process saps invoke-item ii')
const REMOTE = set('ssh scp rsync sftp')

const nonFlags = (args: readonly string[]): string[] => args.filter(a => !a.startsWith('-') || a === '-')

/**
 * Variables that only tune output, locale or logging. Any other assignment
 * (PAGER, GIT_*, LD_PRELOAD, BASH_ENV, NODE_OPTIONS, PATH, ...) can change
 * which program a command runs, so it goes to the classifier.
 */
const INERT_ENV = /^(NODE_ENV|CI|DEBUG|RUST_LOG|RUST_BACKTRACE|LANG|LANGUAGE|LC_[A-Z_]+|TZ|NO_COLOR|FORCE_COLOR|CLICOLOR(_FORCE)?|TERM|COLUMNS|LINES)$/
const ASSIGNMENT = /^([A-Za-z_][A-Za-z0-9_]*)\+?=/
const DECLARERS = set('export declare typeset readonly local')

/** What a declaring builtin (export, declare, ...) sets: NAME=value, or NAME alone, which exports a value set elsewhere. */
function judgeDeclaration(cmd: string, rest: readonly string[]): Decision {
  const names = rest.filter(a => !a.startsWith('-') && !a.startsWith('+'))
  if (names.some(a => a.includes(SUB) || /^\$|^[^=]*\$/.test(a))) return classify(`${cmd} with a variable named at run time`)
  return worse(allow(`the shell builtin ${cmd}`), judgeAssignments(names.map(a => (a.includes('=') ? a : `${a}=`))))
}

function judgeAssignments(assignments: readonly string[]): Decision {
  for (const a of assignments) {
    const name = ASSIGNMENT.exec(a)?.[1]
    if (name !== undefined && !INERT_ENV.test(name)) return classify(`sets ${name}, which can change what a command runs`)
  }
  return allow('sets only output, locale or logging variables')
}

/** PowerShell's `$env:NAME = ...`, as a `NAME=` assignment. */
function powershellEnvAssignments(seg: Segment, flavor: Flavor): string[] {
  const name = flavor === 'powershell' ? /^\$env:(\w+)/i.exec(seg.argv[0] ?? '')?.[1] : undefined
  return name === undefined ? [] : [`${name}=`]
}

/** Judges one shell command line. */
export function judgeShell(command: string, flavor: Flavor, ctx: Context): Decision {
  const text = command.trim()
  if (text === '') return allow('an empty command')
  const { segments, plain } = splitShell(text, flavor)

  for (const [re, why] of R.HARD) if (re.test(plain)) return ask(why)
  if (segments.some(s => s.argv[0] !== undefined && SQL.has(baseName(s.argv[0]))) && R.SQL_DESTRUCTIVE.test(text)) {
    return ask('drops, truncates or mass-deletes database data')
  }
  const pipe = plain.search(R.PIPE_TO_INTERPRETER)
  if (pipe !== -1 && R.DOWNLOADER.test(plain.slice(0, pipe))) return ask('downloads or decodes text and executes it')

  let worst = allow('read-only, or a project command')
  let here: string | undefined = ctx.cwd
  for (const seg of segments) {
    const at: Context = { ...ctx, cwd: here ?? '' }
    for (const sub of seg.subs) {
      worst = worse(worst, judgeShell(sub, flavor, at))
      if (worst.kind === 'ask') return worst
    }
    worst = worse(worst, judgeSegment(seg, flavor, at))
    if (worst.kind === 'ask') return worst
    here = nextCwd(seg, here)
  }
  for (const [re, why] of R.SOFT) if (re.test(plain)) worst = worse(worst, classify(why, CLASSIFIER_FIX))
  if (pipe !== -1) worst = worse(worst, classify('a pipeline that feeds an interpreter', CLASSIFIER_FIX))
  if (worst.kind !== 'allow' && R.CLAUDE_INTERNAL.test(plain)) return ask("touches Claude Code's own settings, plugins or transcripts")
  if (worst.kind === 'classify' && worst.fix === undefined) worst = { ...worst, fix: CLASSIFIER_FIX }
  return worst
}

function nextCwd(seg: Segment, here: string | undefined): string | undefined {
  const cmd = seg.argv[0] === undefined ? '' : baseName(seg.argv[0])
  if (!/^(cd|chdir|pushd|set-location|sl|push-location)$/.test(cmd)) return cmd === 'popd' || cmd === 'pop-location' ? undefined : here
  const target = nonFlags(seg.argv.slice(1))[0]
  if (target === undefined || target === '-' || here === undefined) return undefined
  return normalizePath(target, here)
}

function judgeSegment(seg: Segment, flavor: Flavor, ctx: Context): Decision {
  const assigned = judgeAssignments([...seg.env, ...powershellEnvAssignments(seg, flavor)])
  return worse(assigned, judgeSegmentCommand(seg, flavor, ctx))
}

function judgeSegmentCommand(seg: Segment, flavor: Flavor, ctx: Context): Decision {
  let argv = seg.argv
  if (flavor === 'powershell' && argv[0] !== undefined && argv[0].startsWith('$')) {
    const head = argv[0]
    const eq = /^\$[\w:.]+([-+*/]?=)(.*)$/.exec(head)
    if (eq !== null) argv = [...(eq[2] === '' ? [] : [eq[2] as string]), ...argv.slice(1)]
    else if (argv[1] !== undefined && /^[-+*/]?=$/.test(argv[1])) argv = argv.slice(2)
    else if (/[(]/.test(argv.join(' '))) return classify('a method call on an object')
    else return allow('an expression')
    if (argv.length === 0) return allow('a variable assignment')
  }
  for (const w of seg.writes) {
    const d = judgeWritePath(w, ctx, 'a redirection')
    if (d.kind !== 'allow') return d
  }
  const head = argv[0]
  if (head === undefined) return allow(seg.env.length > 0 ? 'a variable assignment' : 'nothing runs')
  return judgeArgv(baseName(head), argv.slice(1), seg, flavor, ctx)
}

function judgeArgv(cmd: string, rest: string[], seg: Segment, flavor: Flavor, ctx: Context): Decision {
  const again = (next: string[]): Decision => {
    const h = next[0]
    if (h === undefined) return allow('nothing runs')
    return judgeArgv(baseName(h), next.slice(1), seg, flavor, ctx)
  }
  if (R.WRAPPERS.has(cmd)) return judgeWrapped(cmd, rest, again)
  if (DECLARERS.has(cmd)) return judgeDeclaration(cmd, rest)
  if (cmd === 'alias') return rest.length === 0 ? allow('lists aliases') : classify('defines an alias, which can replace a command')
  if (cmd === 'printf') {
    const v = rest.findIndex(a => a === '-v')
    if (v !== -1) return judgeDeclaration('printf -v', [rest[v + 1] ?? '$'])
  }
  if (R.BUILTINS.has(cmd)) return allow(`the shell builtin ${cmd}`)
  if (cmd === 'source' || cmd === '.') return classify('sources a script into the shell')
  if (cmd === 'eval' || cmd === 'invoke-expression' || cmd === 'iex') {
    if (rest.some(a => a.includes(SUB) || a.includes('$'))) return ask('evaluates text computed at run time')
    return judgeShell(rest.join(' '), flavor, ctx)
  }
  if (R.SHELLS.has(cmd)) return judgeSubshell(cmd, rest, ctx)
  if (PACKAGE_MANAGERS.has(cmd)) return judgePackage(cmd, rest, again)
  if (R.INTERPRETERS.has(cmd)) return judgeInterpreter(cmd, rest, again)
  if (cmd === 'git') return judgeGit(rest, ctx)
  if (R.DELETERS.has(cmd)) return judgeRemove(rest, ctx)
  if (R.FILE_OPS.has(cmd)) return judgePaths(nonFlags(rest), ctx, cmd)
  if (R.HTTP.has(cmd)) return judgeHttp(cmd, rest, ctx)
  if (R.PERMS.has(cmd)) {
    if (cmd === 'chmod' || cmd === 'attrib') return judgePaths(nonFlags(rest).filter(a => !/^[ugoa]*[+\-=][rwxstXugo]*$|^[0-7]{3,4}$|^[+\-][rash]+$/i.test(a)), ctx, cmd)
    return classify(`${cmd} changes ownership or access control`)
  }
  if (cmd === 'find') {
    return rest.some(a => /^-(delete|exec|execdir|ok|okdir|fprint|fls|fprintf)$/.test(a)) ? classify('a find that deletes or executes') : allow('find is read-only')
  }
  if (cmd === 'sed' || cmd === 'yq') {
    if (rest.some(a => /^-[a-zA-Z]*i|^--in-place/.test(a))) return classify(`an in-place ${cmd} edit`)
    if (cmd === 'sed' && sedRunsOrWrites(rest)) return classify('a sed script that runs commands or writes files')
    return allow(`${cmd} prints`)
  }
  if (cmd === 'awk' || cmd === 'gawk' || cmd === 'mawk') {
    return awkRunsOrWrites(rest) ? classify('an awk program that runs commands, reads their output or writes files') : allow('awk prints')
  }
  if (cmd === 'sort') {
    if (rest.some(a => /^--compress-program/.test(a))) return classify('sort runs a compression program')
    const o = rest.findIndex(a => a === '-o' || a === '--output')
    if (o !== -1) return judgeWritePath(rest[o + 1] ?? '', ctx, 'sort -o')
    return allow('sort prints')
  }
  if (cmd === 'tee-object' || cmd === 'tee') return judgePaths(nonFlags(rest), ctx, cmd)
  if (R.CONTENT_READERS.has(cmd)) {
    for (const a of nonFlags(rest)) {
      if (a === '-' || a === SUB) continue
      if (a.includes(SUB) || /\$|%[^%]+%/.test(a)) return classify('reads a file the shell names at run time')
      const p = normalizePath(a, ctx.cwd)
      if (p === undefined) return classify('reads a path only the shell expands')
      if (SENSITIVE.test(p)) return classify('reads a credentials, startup or instructions file')
      if (!isInsideAny(p, ctx.workingDirs)) return classify('reads a file outside the working directories', ADD_DIR_FIX)
    }
    return allow(`${cmd} prints a project file`)
  }
  if (R.READ_ONLY.has(cmd)) return allow(`${cmd} is read-only`)
  if (R.PROJECT_TOOLS.has(cmd)) return allow(`${cmd} is a project tool`)
  if (CLIS.has(cmd)) return judgeCli(cmd, rest)
  if (SQL.has(cmd)) return classify('a database client')
  if (SYSTEM_PKG.has(cmd)) {
    const sub = nonFlags(rest)[0] ?? ''
    return /^(list|info|search|show|outdated|doctor|which|cat|deps|leaves|--prefix|--version|-v|help|policy|status|config)$/.test(sub) || rest.includes('--version')
      ? allow(`${cmd} ${sub} is read-only`)
      : classify(`${cmd} installs or removes system software`)
  }
  if (KILLERS.has(cmd)) return classify('kills a process')
  if (OPENERS.has(cmd)) return classify('opens an application or URL')
  if (REMOTE.has(cmd)) return classify('talks to a remote host')
  if (cmd === 'claude') return classify('starts a nested Claude Code session')
  if (cmd === 'code' || cmd === 'cursor' || cmd === 'subl') {
    return rest.some(a => a.startsWith('--')) ? classify(`${cmd} with options`) : allow(`opens the editor`)
  }
  return classify(`${cmd} is not in the read-only or project command set`)
}

/** The scripts sed will run: each -e value, else the first operand. */
function sedScripts(rest: readonly string[]): string[] {
  const scripts: string[] = []
  let operand: string | undefined
  for (let i = 0; i < rest.length; i++) {
    const a = rest[i] as string
    if (a.startsWith('--expression=')) scripts.push(a.slice('--expression='.length))
    else if (a === '--expression' || /^-[a-zA-Z]*e$/.test(a)) scripts.push(rest[++i] ?? '')
    else if (/^-[a-zA-Z]*e./.test(a)) scripts.push(a.slice(a.indexOf('e') + 1))
    else if (a === '-l' || a === '--line-length') i++
    else if (operand === undefined && (!a.startsWith('-') || a === '-')) operand = a
  }
  return scripts.length > 0 ? scripts : operand === undefined ? [] : [operand]
}

/**
 * Whether sed may run a command (`e`, the `s///e` flag) or write a file (`w`,
 * `W`, the `s///w` flag). Patterns and replacements are blanked first so a `w`
 * inside `s/word/x/` does not count; text after `a`, `i` or `c` still does,
 * which errs toward the classifier. `--sandbox` disables all of them.
 */
function sedRunsOrWrites(rest: readonly string[]): boolean {
  if (rest.includes('--sandbox')) return false
  if (rest.some(a => /^(-[a-zA-Z]*f|--file)/.test(a))) return true
  return sedScripts(rest).some(script => {
    const commands = script
      .replace(/s(.)(?:\\.|(?!\1)[^\\])*\1(?:\\.|(?!\1)[^\\])*\1/g, 's')
      .replace(/y(.)(?:\\.|(?!\1)[^\\])*\1(?:\\.|(?!\1)[^\\])*\1/g, 'y')
      .replace(/\/(?:\\.|[^\\/])*\//g, '')
      .replace(/\\(.)(?:\\.|(?!\1)[^\\])*\1/g, '')
    return /[ewW]/.test(commands)
  })
}

/** Whether an awk program may run a command, read its output or write a file. `--sandbox` (gawk) forbids all three. */
function awkRunsOrWrites(rest: readonly string[]): boolean {
  if (rest.includes('--sandbox')) return false
  if (rest.some(a => /^(-[a-zA-Z]*[fEil]|--file|--exec|--include|--load)/.test(a) && !/^-[vF]/.test(a))) return true
  return nonFlags(rest).some(a => /\||getline|system\s*\(|close\s*\(|>/.test(a))
}

function judgeWrapped(cmd: string, rest: string[], again: (argv: string[]) => Decision): Decision {
  let i = 0
  const takesArg = new Set(
    cmd === 'xargs' ? ['-I', '-n', '-P', '-L', '-s', '-d', '-a', '-E', '--max-args', '--max-procs', '--delimiter', '--arg-file']
      : cmd === 'nice' || cmd === 'ionice' ? ['-n', '-c']
        : cmd === 'watch' ? ['-n', '--interval']
          : cmd === 'env' ? ['-u', '-C', '-S', '--unset', '--chdir']
            : cmd === 'timeout' ? ['-s', '--signal', '-k', '--kill-after']
              : cmd === 'stdbuf' ? ['-i', '-o', '-e']
                : [],
  )
  const assignments: string[] = []
  while (i < rest.length) {
    const a = rest[i] as string
    if (cmd === 'env' && /^(-[a-zA-Z0-9]*S|--split-string)/.test(a)) return classify('env -S splits a string into a command')
    if (cmd === 'env' && /^(-[a-zA-Z0-9]*C|--chdir)/.test(a)) return classify('env -C runs the command in another directory')
    if (cmd === 'env' && ASSIGNMENT.test(a)) {
      assignments.push(a)
      i++
      continue
    }
    if (a.startsWith('-') && a !== '-') {
      i += takesArg.has(a) ? 2 : 1
      continue
    }
    break
  }
  if (cmd === 'timeout') i++ // the duration
  const inner = rest.slice(i)
  if (inner.length === 0) {
    if (cmd === 'env') return classify('prints the environment, which may hold secrets')
    if (cmd === 'xargs') return allow('xargs echoes')
    return allow(`${cmd} with nothing to run`)
  }
  return worse(judgeAssignments(assignments), again(inner))
}

function judgeSubshell(cmd: string, rest: string[], ctx: Context): Decision {
  const inner: Flavor = cmd === 'pwsh' || cmd === 'powershell' ? 'powershell' : cmd === 'cmd' ? 'cmd' : 'sh'
  if (rest.some(a => a.includes(SUB))) return ask('runs text or a script computed at run time')
  for (let i = 0; i < rest.length; i++) {
    const a = rest[i] as string
    const isCode = inner === 'sh' ? /^-[a-zA-Z]*c$/.test(a) : inner === 'cmd' ? /^\/[ck]$/i.test(a) : /^-(c|command|nop?)$/i.test(a) && !/^-nop?$/i.test(a)
    if (isCode) {
      const code = rest.slice(i + 1)
      if (code.some(c => c.includes(SUB))) return ask('runs text computed at run time')
      return judgeShell(code.join(' '), inner, ctx)
    }
    if (inner === 'powershell' && /^-(f|file)$/i.test(a)) return classify('runs a PowerShell script file')
    if (inner === 'powershell' && /^-(e|ec|enc|encodedcommand)$/i.test(a)) return ask('an encoded PowerShell command')
    if (!a.startsWith('-')) return classify('runs a shell script file')
  }
  return classify('an interactive shell')
}

function judgeInterpreter(cmd: string, rest: string[], again: (argv: string[]) => Decision): Decision {
  if (rest.length === 0) return classify('an interactive interpreter')
  if (rest.some(a => a.includes(SUB))) return ask('runs code or a script computed at run time')
  if (rest.some(a => /^(--version|-v|-V|version)$/.test(a)) && rest.length === 1) return allow(`${cmd} prints its version`)
  if (cmd === 'python' || cmd === 'python3' || cmd === 'py') {
    const m = rest.indexOf('-m')
    if (m !== -1) {
      const mod = rest[m + 1] ?? ''
      if (mod === 'pip') return judgePackage('pip', rest.slice(m + 2), again)
      if (R.PYTHON_MODULES_OK.has(mod)) return allow(`python -m ${mod} is a project tool`)
      return classify(`runs the ${mod} module`)
    }
  }
  if (cmd === 'deno' && /^(test|lint|fmt|check|doc|info)$/.test(rest[0] ?? '')) return allow(`deno ${rest[0] as string} is a project tool`)
  if (rest.some(a => /^(-c|-e|--eval|-p|--print|-E)$/.test(a) || /^-[a-zA-Z]*[ce][a-zA-Z]*$/.test(a))) {
    return rest.some(a => a.includes(SUB)) ? ask('runs text computed at run time') : classify(`inline ${cmd} code`)
  }
  return classify(`runs a ${cmd} script`)
}

const GIT_READ = set('status log diff show blame shortlog ls-files ls-tree ls-remote cat-file rev-parse rev-list describe name-rev grep count-objects merge-base cherry whatchanged var version --version help check-ignore check-attr for-each-ref show-ref diff-tree diff-index diff-files fsck verify-commit verify-tag range-diff')
const GIT_SAFE = set('add commit fetch pull merge cherry-pick revert init clone submodule am apply format-patch archive mv switch restore reset')
const GIT_BRANCH_FLAGS = /^(-a|-r|-v|-vv|--list|--show-current|--contains|--no-contains|--merged|--no-merged|--format(=.*)?|--sort(=.*)?|-l|--all|--remotes|--verbose|--points-at|--color|--no-color|--column|--no-column)$/

/**
 * Where a -C, --git-dir or --work-tree lands, resolved against `base` (each -C
 * is relative to the one before it), or the classify decision when it leaves
 * the working directories: another repository brings its own config, whose
 * hooks and helpers run commands.
 */
function resolveGitRepoPath(spelling: string | undefined, base: string, ctx: Context): string | Decision {
  if (spelling === undefined || spelling.includes(SUB) || /\$|%[^%]+%/.test(spelling)) return classify('git on a repository the shell names at run time')
  const p = normalizePath(spelling, base)
  if (p === undefined || !isInsideAny(p, ctx.workingDirs)) return classify(`git on a repository outside the working directories (${spelling}), whose config can run commands`, ADD_DIR_FIX)
  return p
}

/** Subcommand options that run a program of the caller's choosing or install hooks. */
const GIT_PROGRAM_OPTIONS: Readonly<Record<string, RegExp>> = {
  grep: /^(-[a-zA-Z]*O|--open-files-in-pager)/,
  'ls-remote': /^--upload-pack/,
  fetch: /^--upload-pack/,
  pull: /^--upload-pack/,
  clone: /^(-[a-zA-Z]*[uc]|--upload-pack|--config|--template)/,
  init: /^--template/,
  archive: /^--exec/,
}

/** What a subcommand's options add on top of the subcommand itself, if anything. */
function judgeGitOptions(sub: string, rest: string[], ctx: Context): Decision | undefined {
  const runs = GIT_PROGRAM_OPTIONS[sub]
  if (runs !== undefined && rest.some(a => runs.test(a))) return classify(`git ${sub} with an option that runs a program or installs hooks`)
  if (sub === 'submodule' && nonFlags(rest)[0] === 'foreach') return classify('git submodule foreach runs a command in every submodule')
  const o = rest.findIndex(a => a === '--output' || a.startsWith('--output='))
  if (o === -1) return undefined
  const target = rest[o]?.startsWith('--output=') === true ? rest[o]?.slice('--output='.length) : rest[o + 1]
  const written = judgeWritePath(target ?? '', ctx, `git ${sub} --output`)
  return written.kind === 'allow' ? undefined : written
}

function judgeGit(args: string[], ctx: Context): Decision {
  let i = 0
  let base = ctx.cwd
  while (i < args.length) {
    const a = args[i] as string
    // -c and --config-env set any key, including the ones that run programs (core.pager, core.fsmonitor, alias.*, *.sshCommand).
    if (a === '-c' || /^-c\S/.test(a) || /^--config-env(=.*)?$/.test(a)) return classify('git with a config override, which can run commands')
    if (/^--exec-path=/.test(a)) return classify('git with its helper programs taken from another directory')
    if (a === '-C' || /^(--git-dir|--work-tree)(=.*)?$/.test(a)) {
      const value = a.includes('=') ? a.slice(a.indexOf('=') + 1) : args[i + 1]
      const landed = resolveGitRepoPath(value, base, ctx)
      if (typeof landed !== 'string') return landed
      if (a === '-C') base = landed
      i += a.includes('=') ? 1 : 2
    } else if (/^--namespace(=.*)?$/.test(a)) i += a.includes('=') ? 1 : 2
    else if (/^(--no-pager|-P|-p|--paginate|--no-optional-locks|--literal-pathspecs|--no-replace-objects|--bare|--exec-path)$/.test(a)) i++
    else break
  }
  const sub = args[i]
  const rest = args.slice(i + 1)
  const positional = nonFlags(rest)
  if (sub === undefined) return allow('git prints its help')
  const options = judgeGitOptions(sub, rest, { ...ctx, cwd: base })
  if (options !== undefined) return options
  if (GIT_READ.has(sub)) return allow(`git ${sub} is read-only`)
  switch (sub) {
    case 'branch':
      return positional.length === 0 && rest.every(a => GIT_BRANCH_FLAGS.test(a)) ? allow('lists branches') : classify('creates, renames or deletes a branch')
    case 'stash':
      return /^(push|save|pop|apply|list|show|branch|create|store)?$/.test(positional[0] ?? '') ? allow('stashes or restores work') : classify(`git stash ${positional[0] as string}`)
    case 'tag':
      return rest.some(a => a === '-d' || a === '--delete') ? classify('deletes a tag') : allow('creates or lists tags')
    case 'remote':
      return rest.length === 0 || /^(-v|--verbose|show|get-url)$/.test(rest[0] as string) ? allow('lists remotes') : classify('changes remotes')
    case 'config':
      if (rest.some(a => /^(--get|--get-all|--get-regexp|--list|-l|--show-origin|--show-scope|--name-only)$/.test(a)) || (positional.length === 1 && !rest.some(a => /^--(unset|add|replace-all|unset-all|remove-section|rename-section|edit)/.test(a)))) {
        return allow('reads git config')
      }
      return classify(rest.some(a => a === '--global' || a === '--system') ? 'writes global git config' : 'writes repository config')
    case 'reflog':
      return /^(show)?$/.test(positional[0] ?? '') ? allow('shows the reflog') : classify(`git reflog ${positional[0] as string}`)
    case 'worktree':
      return positional[0] === 'list' ? allow('lists worktrees') : classify(`git worktree ${positional[0] ?? ''}`)
    case 'checkout':
      if (rest.some(a => /^(-b|-B|--orphan|-t|--track)$/.test(a))) return allow('creates a branch')
      return positional.some(p => /[.]|^\.\/|\/$/.test(p) && !/^origin\//.test(p)) ? classify('a checkout that may discard changes to a file') : allow('switches branches')
    case 'rebase':
      return classify('rewrites local history')
    case 'push':
      return classify('pushes to a remote; the classifier reads your intent for that')
    case 'rm':
      return classify('removes tracked files')
    case 'bisect':
      return /^(log|visualize|view|start|good|bad|skip|reset)$/.test(positional[0] ?? '') ? allow('git bisect') : classify('git bisect')
    default:
      return GIT_SAFE.has(sub) ? allow(`git ${sub} is recoverable`) : classify(`git ${sub}`)
  }
}

function judgePackage(cmd: string, rest: string[], again: (argv: string[]) => Decision): Decision {
  const pos = nonFlags(rest)
  const sub = pos[0] ?? ''
  const after = (n: number): string[] => {
    const at = rest.indexOf(pos[n - 1] as string)
    return at === -1 ? [] : rest.slice(at + 1)
  }
  const version = rest.length === 1 && /^(--version|-v|-V|version)$/.test(rest[0] as string)
  if (version) return allow(`${cmd} prints its version`)
  const global = rest.some(a => /^(-g|--global|--location=global)$/.test(a))

  switch (cmd) {
    case 'npx':
    case 'bunx':
      return judgeNpx(rest, again)
    case 'npm':
    case 'pnpm':
    case 'yarn':
    case 'bun': {
      if (sub === '' ) return allow(cmd === 'yarn' ? 'installs declared dependencies' : `${cmd} prints its help`)
      if (/^(ls|list|ll|la|view|info|show|outdated|why|explain|search|ping|root|prefix|bin|help|docs|pack|licenses|audit|doctor|env|exec-nothing)$/.test(sub)) {
        return sub === 'audit' && pos.includes('fix') ? classify('npm audit fix changes dependencies') : allow(`${cmd} ${sub} is read-only`)
      }
      if (sub === 'config' || sub === 'c') return /^(get|list|ls)$/.test(pos[1] ?? '') ? allow('reads package config') : classify('writes package config')
      if (/^(install|i|isntall|ci|add|install-test|it|install-ci-test|cit)$/.test(sub)) {
        if (global) return classify('a global install')
        const packages = pos.slice(1)
        return packages.length === 0 ? allow('installs declared dependencies') : classify(`adds ${packages.join(' ')}`)
      }
      if (/^(test|t|tst)$/.test(sub)) return allow(`${cmd} test`)
      if (sub === 'run' || sub === 'run-script') {
        const script = pos[1]
        if (script === undefined) return allow('lists scripts')
        if (cmd === 'bun' && /\.[cm]?[jt]sx?$/.test(script)) return classify(`runs ${script}`)
        return R.SAFE_SCRIPTS.has(script) ? allow(`the ${script} script`) : classify(`runs the ${script} script`, `add an allow rule like Bash(${cmd} run ${script}:*)`)
      }
      if (sub === 'exec' || sub === 'x') return judgeNpx(after(1), again)
      if (sub === 'dlx') return judgeNpx(after(1), again)
      if (cmd === 'bun' && sub === 'build') return allow('bun build')
      if (cmd === 'bun' && sub === 'pm') return /^(ls|cache|bin|hash)$/.test(pos[1] ?? '') ? allow('bun pm is read-only') : classify('bun pm')
      if (cmd === 'yarn' && R.SAFE_SCRIPTS.has(sub)) return allow(`the ${sub} script`)
      if (/^(create|init)$/.test(sub)) return classify('scaffolds a project')
      return classify(`${cmd} ${sub} changes dependencies or configuration`)
    }
    case 'pip':
    case 'pip3': {
      if (/^(list|show|freeze|check|debug|index|hash|help)$/.test(sub)) return allow(`pip ${sub} is read-only`)
      if (sub === 'config') return pos[1] === 'list' || pos[1] === 'get' ? allow('reads pip config') : classify('writes pip config')
      if (sub === 'cache') return pos[1] === 'list' || pos[1] === 'info' || pos[1] === 'dir' ? allow('pip cache is read-only') : classify('clears the pip cache')
      if (sub === 'install') {
        const declared = rest.some(a => /^(-r|--requirement|-e|--editable|-c|--constraint)$/.test(a) || /^(-r|-e)\S/.test(a))
        const packages = pos.slice(1).filter(p => !/\.(txt|in|cfg|toml)$|^\.$|^\.\/|\//.test(p))
        const afterR = new Set<string>()
        rest.forEach((a, i) => { if (/^(-r|--requirement|-c|--constraint|-e|--editable)$/.test(a) && rest[i + 1] !== undefined) afterR.add(rest[i + 1] as string) })
        const bare = packages.filter(p => !afterR.has(p))
        if (bare.length > 0) return classify(`installs ${bare.join(' ')}`)
        if (declared || pos[1] === '.') return allow('installs declared dependencies')
        return classify('pip install with nothing declared')
      }
      return classify(`pip ${sub}`)
    }
    case 'uv': {
      if (/^(sync|lock|tree|venv|build|version|self)$/.test(sub)) return allow(`uv ${sub}`)
      if (sub === 'python') return /^(list|find|dir)$/.test(pos[1] ?? '') ? allow('uv python is read-only') : classify(`uv python ${pos[1] ?? ''}`)
      if (sub === 'pip') return judgePackage('pip', after(1), again)
      if (sub === 'run') return again(after(1))
      return classify(`uv ${sub}`)
    }
    case 'poetry':
      if (/^(install|lock|check|show|build|env|about|list)$/.test(sub)) return allow(`poetry ${sub}`)
      if (sub === 'run') return again(after(1))
      return classify(`poetry ${sub}`)
    case 'pipenv':
      if (sub === 'install' && pos.length === 1) return allow('installs declared dependencies')
      if (/^(graph|check|lock|verify|requirements)$/.test(sub)) return allow(`pipenv ${sub}`)
      if (sub === 'run') return again(after(1))
      return classify(`pipenv ${sub}`)
    case 'pipx':
      return /^(list|environment)$/.test(sub) ? allow(`pipx ${sub}`) : classify(`pipx ${sub}`)
    case 'conda':
      return /^(list|info|search|env)$/.test(sub) && (sub !== 'env' || pos[1] === 'list') ? allow(`conda ${sub}`) : classify(`conda ${sub}`)
    case 'cargo':
      if (/^(build|b|check|c|test|t|clippy|fmt|doc|d|metadata|tree|bench|fetch|generate-lockfile|verify-project|locate-project|search|version|pkgid|rustc|vendor|audit|deny|outdated|nextest)$/.test(sub)) return allow(`cargo ${sub}`)
      return classify(`cargo ${sub}`)
    case 'go':
      if (/^(build|test|vet|fmt|list|env|version|doc|tool)$/.test(sub)) return allow(`go ${sub}`)
      if (sub === 'mod') return /^(tidy|download|verify|graph|why|vendor)$/.test(pos[1] ?? '') ? allow(`go mod ${pos[1] as string}`) : classify(`go mod ${pos[1] ?? ''}`)
      return classify(`go ${sub}`)
    case 'dotnet':
      if (/^(build|test|restore|--info|--version|--list-sdks|--list-runtimes|format|clean|pack|sln|list)$/.test(sub)) return allow(`dotnet ${sub}`)
      return classify(`dotnet ${sub}`)
    case 'mvn':
    case 'mvnw':
      return pos.every(p => /^(compile|test|test-compile|verify|package|validate|clean|install|dependency:(tree|list|analyze)|help:\w+|versions:display-\w+|site|javadoc:\w+|checkstyle:check|spotless:check|-\w)$/.test(p)) ? allow('a maven build') : classify(`mvn ${pos.join(' ')}`)
    case 'gradle':
    case 'gradlew':
      return pos.every(p => /^(build|test|check|assemble|compile\w*|clean|dependencies|tasks|help|lint\w*|ktlintCheck|spotlessCheck|jar|classes|testClasses|javadoc|:?[\w-]+:(build|test|check|assemble|compile\w*|lint\w*))$/.test(p)) ? allow('a gradle build') : classify(`gradle ${pos.join(' ')}`)
    case 'make': {
      if (rest.some(a => a === '-n' || a === '--dry-run' || a === '--just-print')) return allow('a make dry run')
      const targets = pos.filter(p => !p.includes('='))
      return targets.every(t => /^(test|tests|check|build|all|lint|fmt|format|compile|default|help)$/.test(t)) ? allow(`make ${targets.join(' ') || 'default'}`) : classify(`make ${targets.join(' ')}`)
    }
    case 'cmake':
      if (rest.includes('--install')) return classify('cmake --install')
      return allow(rest.includes('--build') ? 'a cmake build' : 'a cmake configure')
    case 'ninja':
      return rest.includes('-t') ? classify('a ninja tool') : allow('a ninja build')
    case 'just':
    case 'task':
      if (rest.some(a => /^(--list|-l|--summary|--show|--dump|--evaluate)$/.test(a))) return allow(`${cmd} lists recipes`)
      return R.SAFE_SCRIPTS.has(sub) ? allow(`the ${sub} recipe`) : classify(`the ${sub} recipe`)
    case 'rake':
      if (rest.some(a => a === '-T' || a === '--tasks' || a === '-P')) return allow('rake lists tasks')
      return /^(test|spec|build|default|lint)$/.test(sub) ? allow(`rake ${sub}`) : classify(`rake ${sub}`)
    case 'composer':
      if (/^(install|show|validate|validate|diagnose|outdated|why|licenses|check-platform-reqs|dump-autoload|dumpautoload|test|audit|about|browse|depends|prohibits|suggests|status)$/.test(sub)) return allow(`composer ${sub}`)
      if (sub === 'run-script' || sub === 'run') return R.SAFE_SCRIPTS.has(pos[1] ?? '') ? allow(`the ${pos[1] as string} script`) : classify(`composer run ${pos[1] ?? ''}`)
      return classify(`composer ${sub}`)
    case 'bundle':
    case 'bundler':
      if (/^(install|list|show|outdated|check|platform|info|viz|licenses|env)$/.test(sub)) return allow(`bundle ${sub}`)
      if (sub === 'exec' || sub === 'exe') return again(after(1))
      return classify(`bundle ${sub}`)
    case 'gem':
      return /^(list|env|search|contents|which|specification|dependency|help)$/.test(sub) ? allow(`gem ${sub}`) : classify(`gem ${sub}`)
    case 'mix':
      return /^(deps\.get|deps\.tree|compile|test|format|credo|dialyzer|help|hex\.outdated|hex\.info|xref)$/.test(sub) ? allow(`mix ${sub}`) : classify(`mix ${sub}`)
    case 'swift':
      return /^(build|test|package)$/.test(sub) && !(sub === 'package' && /^(init|clean|reset|edit|update)$/.test(pos[1] ?? '')) ? allow(`swift ${sub}`) : classify(`swift ${sub}`)
    case 'stack':
    case 'cabal':
      return /^(build|test|bench|check|haddock|freeze|list|info)$/.test(sub) ? allow(`${cmd} ${sub}`) : classify(`${cmd} ${sub}`)
    case 'flutter':
    case 'dart':
      if (/^(analyze|test|format|doctor|devices|config)$/.test(sub)) return allow(`${cmd} ${sub}`)
      if (sub === 'pub') return /^(get|outdated|deps|downgrade)$/.test(pos[1] ?? '') ? allow(`${cmd} pub ${pos[1] as string}`) : classify(`${cmd} pub ${pos[1] ?? ''}`)
      return classify(`${cmd} ${sub}`)
    default:
      return classify(`${cmd} ${sub}`)
  }
}

/** npx options that only answer prompts or quiet output. */
const NPX_SWITCHES = /^(-y|--yes|--no|--no-install|-q|--quiet|--silent|--ignore-existing)$/

function judgeNpx(rest: string[], again: (argv: string[]) => Decision): Decision {
  let i = 0
  while (i < rest.length) {
    const a = rest[i] as string
    if (a === '--') {
      i++
      break
    }
    // -p installs a package other than the tool named; -c runs a shell string.
    if (/^(-p|--package|-c|--call)(=.*)?$/.test(a)) return classify(`npx ${a.replace(/=.*$/, '')} installs another package or runs a shell string`)
    // Anything else that takes a value (--registry, --prefix, --userconfig, ...) can point npx at another copy of the tool.
    if (a.startsWith('-') && !NPX_SWITCHES.test(a)) return classify(`npx ${a.replace(/=.*$/, '')} changes where the tool comes from`)
    if (a.startsWith('-')) {
      i++
      continue
    }
    break
  }
  const tool = rest[i]
  if (tool === undefined) return classify('npx with no tool')
  // Only a registry name, optionally scoped and pinned to a version range; a URL, git+, npm:, file: or path spec fetches arbitrary code.
  const spec = /^(@[\w.-]+\/)?([\w.-]+)(?:@([\w.^~<>=*| -]+))?$/.exec(tool)
  if (spec === null) return classify(`npx ${tool} runs a package from outside the registry name`)
  if (spec[1] !== undefined) return classify(`npx ${tool} runs a scoped package`, `add an allow rule like Bash(npx ${tool}:*)`)
  const name = spec[2] as string
  if (R.PROJECT_TOOLS.has(name) || R.READ_ONLY.has(name)) return again([name, ...rest.slice(i + 1)])
  return classify(`npx ${name} fetches and runs a package`, `add an allow rule like Bash(npx ${name}:*)`)
}

function judgeRemove(rest: string[], ctx: Context): Decision {
  const flags = rest.filter(a => a.startsWith('-') && a !== '-')
  const targets = rest.filter(a => !a.startsWith('-') || a === '-')
  const recursive = flags.some(f => /^-[a-zA-Z]*[rR]|^--recursive$|^-Recurse$|^\/s$/i.test(f))
  if (targets.length === 0) return classify('deletes with no literal target')
  for (const t of targets) {
    const raw = t.replace(/\\/g, '/')
    if (/^(\*|\.|\.\.|\/|~|[a-zA-Z]:\/?|\$HOME|\$\{HOME\}|%USERPROFILE%|\$env:USERPROFILE|~\/\*?|\/\*|\.\/\*|\*\/|\.\.\/.*)$/i.test(raw)) return ask(`deletes a critical path (${t})`)
    if (raw.includes(SUB) || /\$|%[^%]+%/.test(raw)) {
      return recursive ? ask('a recursive delete on a path resolved at run time') : classify('deletes a path the shell expands')
    }
    const p = normalizePath(raw, ctx.cwd)
    if (p === undefined) return recursive ? ask(`a recursive delete on ${t}`) : classify(`deletes ${t}`)
    const bare = p.replace(/\/\*+$/, '')
    if (isCriticalPath(bare)) return ask(`deletes a critical path (${t})`)
    if (ctx.workingDirs.some(w => isInside(w, bare))) return ask(`deletes the working directory or an ancestor of it (${t})`)
    if (/\/\.git$/.test(bare)) return ask('deletes the git repository')
    if (SCRATCH.test(bare) && /[*?]/.test(raw)) return ask('wildcard deletion in a shared scratch directory')
  }
  return classify(`deletes ${targets.join(' ')}; whether that predates the session is for the classifier`)
}

function judgePaths(args: readonly string[], ctx: Context, what: string): Decision {
  let worst = allow(`${what} inside the working directories`)
  for (const a of args) {
    if (a === '-' || /^[a-zA-Z]{1,5}$/.test(a)) continue // `tar xzf`, modes, short words
    worst = worse(worst, judgeWritePath(a, ctx, what))
    if (worst.kind === 'ask') return worst
  }
  return worst
}

export function judgeWritePath(spelling: string, ctx: Context, what: string): Decision {
  if (/^(env|variable|function|alias|registry|hk(lm|cu|cr|u|cc)|cert|wsman):/i.test(spelling)) {
    return classify(`${what} to a PowerShell drive (${spelling}), not a file`)
  }
  if (spelling.includes(SUB) || /\$|%[^%]+%/.test(spelling)) return classify(`${what} to a path the shell names at run time`)
  const p = normalizePath(spelling, ctx.cwd)
  if (p === undefined) return classify(`${what} to a path only the shell expands`)
  if (NEVER_WRITE.test(p)) return ask(`${what} into Claude Code's own settings, hooks or plugins`, NEVER_FIX)
  if (SENSITIVE.test(p)) return classify(`${what} to a credentials, startup or instructions file`)
  if (!isInsideAny(p, ctx.workingDirs)) return classify(`${what} outside the working directories (${spelling})`, ADD_DIR_FIX)
  return allow(`${what} inside the working directories`)
}

function judgeHttp(cmd: string, rest: string[], ctx: Context): Decision {
  if (rest.some(a => a.includes(SUB) || /\$|%[^%]+%/.test(a))) return classify('interpolates a variable into a request')
  const out = (flag: RegExp): Decision | undefined => {
    const i = rest.findIndex(a => flag.test(a))
    if (i === -1) return undefined
    const target = rest[i + 1]
    return target === undefined || target.startsWith('-') ? undefined : judgeWritePath(target, ctx, `${cmd} download`)
  }
  // A GET can still carry data out in its URL, and the mod keeps no list of trusted hosts: the classifier reads where it goes.
  const get = (written: Decision | undefined): Decision =>
    worse(classify(`a ${cmd} request, which can carry data out in its URL`), written ?? allow(`${cmd} prints`))
  switch (cmd) {
    case 'curl': {
      const x = rest.findIndex(a => a === '-X' || a === '--request')
      const method = x === -1 ? (rest.find(a => /^-X./.test(a))?.slice(2) ?? 'GET') : (rest[x + 1] ?? 'GET')
      if (!/^(GET|HEAD)$/i.test(method)) return classify(`an HTTP ${method.toUpperCase()}`)
      if (rest.some(a => /^(-d|--data|--data-\w+|-F|--form|--form-string|-T|--upload-file|--json|-K|--config|-I-never)$/.test(a) || /^(-d|-F|-T)\S/.test(a))) return classify('an HTTP request that sends data')
      return get(out(/^(-o|--output|--output-dir)$/))
    }
    case 'wget':
      if (rest.some(a => /^(--post-data|--post-file|--body-data|--body-file|--user|--password|--http-user|--http-password|--header)/.test(a) || (/^--method=/.test(a) && !/^--method=(GET|HEAD)$/i.test(a)))) return classify('an HTTP request that sends data or credentials')
      return get(out(/^(-O|--output-document|-P|--directory-prefix)$/))
    case 'iwr':
    case 'irm':
    case 'invoke-webrequest':
    case 'invoke-restmethod': {
      const m = rest.findIndex(a => /^-method$/i.test(a))
      if (m !== -1 && !/^(get|head)$/i.test(rest[m + 1] ?? 'get')) return classify(`an HTTP ${(rest[m + 1] ?? '').toUpperCase()}`)
      if (rest.some(a => /^-(body|infile|form|contenttype)$/i.test(a))) return classify('an HTTP request that sends data')
      return get(out(/^-outfile$/i))
    }
    case 'http':
    case 'https':
    case 'xh': {
      const first = nonFlags(rest)[0] ?? ''
      if (/^[A-Z]+$/.test(first) && !/^(GET|HEAD)$/.test(first)) return classify(`an HTTP ${first}`)
      if (rest.some(a => /^[\w-]+(:=|=|@)/.test(a) && !/^https?:/.test(a))) return classify('an HTTP request that sends data')
      return get(out(/^(-o|--output)$/))
    }
    default:
      return get(out(/^(-d|--dir|-o|--out)$/))
  }
}

function judgeCli(cmd: string, rest: string[]): Decision {
  const pos = nonFlags(rest)
  const sub = pos[0] ?? ''
  const second = pos[1] ?? ''
  switch (cmd) {
    case 'docker':
    case 'podman':
    case 'docker-compose':
      if (/^(ps|images|logs|inspect|version|info|stats|port|top|history|diff|search|events|config)$/.test(sub)) return sub === 'stats' && !rest.includes('--no-stream') ? classify('docker stats streams') : allow(`${cmd} ${sub} is read-only`)
      if (/^(image|container|volume|network|context|node|service|stack|system)$/.test(sub)) return /^(ls|list|inspect|df|events|history|logs)$/.test(second) ? allow(`${cmd} ${sub} ${second} is read-only`) : classify(`${cmd} ${sub} ${second}`)
      if (sub === 'compose' || cmd === 'docker-compose') {
        const c = cmd === 'docker-compose' ? sub : second
        return /^(ps|logs|config|images|version|ls|top|port|events)$/.test(c) ? allow(`compose ${c} is read-only`) : classify(`compose ${c}`)
      }
      if (sub === 'build') return allow('builds an image from the project')
      return classify(`${cmd} ${sub}`)
    case 'kubectl':
    case 'oc':
      if (/^(get|describe|logs|version|explain|api-resources|api-versions|cluster-info|top|diff|auth|events|options)$/.test(sub)) return allow(`${cmd} ${sub} is read-only`)
      if (sub === 'config') return /^(view|current-context|get-contexts|get-clusters|get-users)$/.test(second) ? allow('reads kube config') : classify(`kubectl config ${second}`)
      return classify(`${cmd} ${sub}`)
    case 'gh':
      if (sub === 'pr') return /^(view|list|diff|checks|status|checkout)$/.test(second) ? allow(`gh pr ${second}`) : classify(`gh pr ${second}`)
      if (sub === 'issue') return /^(view|list|status)$/.test(second) ? allow(`gh issue ${second}`) : classify(`gh issue ${second}`)
      if (sub === 'repo') return /^(view|list|clone)$/.test(second) ? allow(`gh repo ${second}`) : classify(`gh repo ${second}`)
      if (sub === 'run') return /^(list|view|watch|download)$/.test(second) ? allow(`gh run ${second}`) : classify(`gh run ${second}`)
      if (sub === 'release') return /^(list|view|download)$/.test(second) ? allow(`gh release ${second}`) : classify(`gh release ${second}`)
      if (sub === 'workflow') return /^(list|view)$/.test(second) ? allow(`gh workflow ${second}`) : classify(`gh workflow ${second}`)
      if (sub === 'api') {
        const x = rest.findIndex(a => a === '-X' || a === '--method')
        const method = x === -1 ? 'GET' : (rest[x + 1] ?? 'GET')
        if (!/^GET$/i.test(method) || rest.some(a => /^(-f|-F|--field|--raw-field|--input)$/.test(a))) return classify('a gh api call that writes')
        return allow('a read-only gh api call')
      }
      if (/^(search|status|browse-never|label|cache)$/.test(sub)) return sub === 'search' || sub === 'status' || second === 'list' ? allow(`gh ${sub}`) : classify(`gh ${sub} ${second}`)
      if (sub === 'auth' && second === 'status') return allow('gh auth status')
      if (sub === 'extension' && second === 'list') return allow('gh extension list')
      return classify(`gh ${sub} ${second}`)
    case 'aws':
    case 'gcloud':
    case 'az': {
      const verb = pos.find((p, i) => i > 0 && /^(describe|list|get|ls|show|search|head|explain|version|help|lookup)/.test(p))
      if (rest.includes('--version') || sub === 'version' || sub === 'help') return allow(`${cmd} prints`)
      if (cmd === 'aws' && sub === 'sts' && second === 'get-caller-identity') return allow('aws identity check')
      if (cmd === 'gcloud' && sub === 'auth' && second === 'list') return allow('gcloud auth list')
      if (cmd === 'az' && sub === 'account' && second === 'show') return allow('az account show')
      return verb !== undefined ? allow(`${cmd} ${verb} is read-only`) : classify(`${cmd} ${sub} ${second}`)
    }
    case 'terraform':
    case 'tofu':
      return /^(plan|validate|fmt|show|output|providers|version|init|graph|console-never|test)$/.test(sub) || (sub === 'state' && /^(list|show|pull)$/.test(second)) || (sub === 'workspace' && /^(list|show)$/.test(second))
        ? allow(`${cmd} ${sub} is read-only`)
        : classify(`${cmd} ${sub}`)
    default:
      return classify(`${cmd} ${sub}`)
  }
}
