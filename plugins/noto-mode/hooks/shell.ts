// A small shell splitter: one command line into its simple commands, with
// quotes, redirections, `VAR=value` prefixes, `$(...)` substitutions and
// heredocs accounted for. Pure, no engine access. It need not be a full
// parser: anything it cannot read lands in the classifier, never in `allow`.

export type Flavor = 'sh' | 'powershell' | 'cmd'

/** The placeholder a command substitution leaves in a token. */
export const SUB = '«sub»'

export type Segment = {
  /** The words, quotes removed, `VAR=value` prefixes and redirections taken out. */
  argv: string[]
  /** The leading `VAR=value` assignments. */
  env: string[]
  /** Targets of output redirections (`>`, `>>`, `&>`); never /dev/null or $null. */
  writes: string[]
  /** Targets of input redirections (`<`, `<<<`). */
  reads: string[]
  /** The commands inside `$(...)`, backticks and `<(...)` found in this segment. */
  subs: string[]
  /** The segment's text with quoted content blanked, for pattern checks. */
  plain: string
}

export type Split = {
  segments: Segment[]
  /** The whole command with quoted content blanked, separators kept. */
  plain: string
}

const isNullTarget = (t: string): boolean => /^(\/dev\/null|\$null|nul)$/i.test(t)

function readBalanced(text: string, from: number): [string, number] {
  let depth = 1
  let i = from
  let quote = ''
  while (i < text.length) {
    const c = text[i] as string
    if (quote !== '') {
      if (c === quote) quote = ''
      i++
      continue
    }
    if (c === "'" || c === '"') quote = c
    else if (c === '(') depth++
    else if (c === ')') {
      depth--
      if (depth === 0) return [text.slice(from, i), i + 1]
    }
    i++
  }
  return [text.slice(from), text.length]
}

function readUntil(text: string, from: number, close: string): [string, number] {
  const at = text.indexOf(close, from)
  if (at === -1) return [text.slice(from), text.length]
  return [text.slice(from, at), at + 1]
}

function makeSegment(tokens: string[], plain: string, subs: string[]): Segment {
  const env: string[] = []
  const argv: string[] = []
  const writes: string[] = []
  const reads: string[] = []
  let i = 0
  while (i < tokens.length) {
    const t = tokens[i] as string
    if (argv.length === 0 && /^[A-Za-z_][A-Za-z0-9_]*=/.test(t)) {
      env.push(t)
      i++
      continue
    }
    const m = /^(\d+|&|\*)?(>>|>\|?|<<<|<)(.*)$/.exec(t)
    if (m !== null) {
      const op = m[2] as string
      let target = m[3] ?? ''
      if (target === '') {
        i++
        target = tokens[i] ?? ''
      }
      i++
      if (target.startsWith('&') || target === '') continue
      if (op.startsWith('>')) {
        if (!isNullTarget(target)) writes.push(target)
      } else reads.push(target)
      continue
    }
    argv.push(t)
    i++
  }
  return { argv, env, writes, reads, subs, plain }
}

/** Splits a command line into simple commands. */
export function splitShell(command: string, flavor: Flavor): Split {
  const segments: Segment[] = []
  let tokens: string[] = []
  let cur = ''
  let has = false
  let plain = ''
  let plainAll = ''
  let subs: string[] = []
  let quote: '' | "'" | '"' = ''
  let heredoc: string | undefined
  const esc = flavor === 'powershell' ? '`' : flavor === 'sh' ? '\\' : ''

  const pushTok = (): void => {
    if (has) tokens.push(cur)
    cur = ''
    has = false
  }
  const endSeg = (sep: string): void => {
    pushTok()
    if (tokens.length > 0) segments.push(makeSegment(tokens, plain.trim(), subs))
    tokens = []
    plain = ''
    subs = []
    plainAll += sep
  }
  const takeSub = (inner: string): void => {
    subs.push(inner)
    cur += SUB
    has = true
    plain += SUB
    plainAll += SUB
  }
  const lit = (text: string): void => {
    cur += text
    has = true
    plain += text
    plainAll += text
  }

  const n = command.length
  let i = 0
  while (i < n) {
    const c = command[i] as string
    const d = command[i + 1]

    if (quote === "'") {
      if (c === "'") {
        quote = ''
        plain += c
        plainAll += c
      } else cur += c
      has = true
      i++
      continue
    }
    if (quote === '"') {
      if (c === '"') {
        quote = ''
        plain += c
        plainAll += c
      } else if (esc !== '' && c === esc && d !== undefined) {
        cur += d
        i++
      } else if (flavor !== 'cmd' && c === '$' && d === '(') {
        const [inner, j] = readBalanced(command, i + 2)
        subs.push(inner)
        cur += SUB
        i = j
        has = true
        continue
      } else if (flavor === 'sh' && c === '`') {
        const [inner, j] = readUntil(command, i + 1, '`')
        subs.push(inner)
        cur += SUB
        i = j
        has = true
        continue
      } else cur += c
      has = true
      i++
      continue
    }

    // unquoted
    if (c === "'" || c === '"') {
      quote = c
      has = true
      plain += c
      plainAll += c
      i++
      continue
    }
    if (esc !== '' && c === esc) {
      if (d !== undefined && d !== '\n') lit(d)
      i += 2
      continue
    }
    if (flavor !== 'cmd' && c === '$' && d === '(') {
      const [inner, j] = readBalanced(command, i + 2)
      takeSub(inner)
      i = j
      continue
    }
    if (flavor === 'sh' && c === '<' && d === '(') {
      const [inner, j] = readBalanced(command, i + 2)
      takeSub(inner)
      i = j
      continue
    }
    if (flavor === 'sh' && c === '`') {
      const [inner, j] = readUntil(command, i + 1, '`')
      takeSub(inner)
      i = j
      continue
    }
    if (flavor === 'sh' && c === '$' && d === '{') {
      const [inner, j] = readUntil(command, i + 2, '}')
      lit(`\${${inner}}`)
      i = j
      continue
    }
    if (flavor === 'sh' && c === '<' && d === '<' && command[i + 2] !== '<') {
      // a heredoc: the delimiter word now, the body skipped after this line
      let j = i + 2
      if (command[j] === '-') j++
      while (command[j] === ' ' || command[j] === '\t') j++
      let delim = ''
      let q = ''
      for (; j < n; j++) {
        const ch = command[j] as string
        if (q !== '') {
          if (ch === q) q = ''
          else delim += ch
        } else if (ch === "'" || ch === '"') q = ch
        else if (/[\s;&|<>]/.test(ch)) break
        else delim += ch
      }
      heredoc = delim
      pushTok()
      i = j
      continue
    }
    if (c === '#' && !has && flavor === 'sh') {
      const nl = command.indexOf('\n', i)
      i = nl === -1 ? n : nl
      continue
    }
    if (c === '\n') {
      if (heredoc !== undefined) {
        const delim = heredoc
        heredoc = undefined
        let j = i + 1
        while (j < n) {
          let eol = command.indexOf('\n', j)
          if (eol === -1) eol = n
          if (command.slice(j, eol).trim() === delim) {
            j = eol
            break
          }
          j = eol + 1
        }
        i = Math.min(j, n)
        endSeg('\n')
        i++
        continue
      }
      endSeg('\n')
      i++
      continue
    }
    if (c === ';') {
      endSeg(' ; ')
      i++
      continue
    }
    if (c === '&' && d === '&') {
      endSeg(' && ')
      i += 2
      continue
    }
    if (c === '|' && d === '|') {
      endSeg(' || ')
      i += 2
      continue
    }
    if (c === '|') {
      endSeg(' | ')
      i += d === '&' ? 2 : 1
      continue
    }
    if (c === '&') {
      if (d === '>' || cur.endsWith('>')) {
        lit(c)
        i++
        continue
      }
      endSeg(' & ')
      i++
      continue
    }
    if (c === '(' || c === ')') {
      pushTok()
      plain += ' '
      plainAll += ' '
      i++
      continue
    }
    if (c === '{' || c === '}') {
      if (flavor === 'powershell') {
        endSeg(' ; ')
        i++
        continue
      }
      if (!has) {
        pushTok()
        plain += ' '
        plainAll += ' '
        i++
        continue
      }
      lit(c)
      i++
      continue
    }
    if (/\s/.test(c)) {
      pushTok()
      plain += ' '
      plainAll += ' '
      i++
      continue
    }
    lit(c)
    i++
  }
  endSeg('')
  return { segments, plain: plainAll.replace(/\s+/g, ' ').trim() }
}

/** The command's base name, lowercased, `.exe`/`.cmd`/`.bat` dropped. */
export function baseName(head: string): string {
  const last = head.replace(/\\/g, '/').split('/').pop() ?? head
  return last.toLowerCase().replace(/\.(exe|cmd|bat|com)$/, '')
}
