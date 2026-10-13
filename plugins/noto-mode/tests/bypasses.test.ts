import { test, expect } from 'claude-code/testing'
import { judgeShell } from '../hooks/shell-policy'

// Commands that look read-only but can run other programs, write files or send
// data out. None of them may be approved by rule; each goes to the classifier.

const ctx = { cwd: 'C:/proj', workingDirs: ['c:/proj'] }
const sh = (command: string) => judgeShell(command, 'sh', ctx).kind

test('git config overrides and foreign repositories go to the classifier', () => {
  expect(sh(`git -c core.pager='sh -c "touch /tmp/pwn"' log`)).toBe('classify')
  expect(sh(`git -c core.fsmonitor='touch /tmp/pwn' status`)).toBe('classify')
  expect(sh('git -ccore.pager=x log')).toBe('classify')
  expect(sh('git --config-env=core.pager=EVIL log')).toBe('classify')
  expect(sh('git --exec-path=/tmp/evil status')).toBe('classify')
  expect(sh('git -C /tmp/evilrepo status')).toBe('classify')
  expect(sh('git --git-dir=/tmp/evilrepo/.git log')).toBe('classify')
  expect(sh('git --work-tree "$DIR" status')).toBe('classify')
})

test('git inside the working directories stays allowed', () => {
  expect(sh('git log --oneline')).toBe('allow')
  expect(sh('git -C sub status')).toBe('allow')
  expect(sh('git --no-pager diff')).toBe('allow')
  expect(sh('git --exec-path')).toBe('allow')
})

test('environment assignments that can change what runs go to the classifier', () => {
  expect(sh('env LD_PRELOAD=/tmp/evil.so cat README.md')).toBe('classify')
  expect(sh(`env PAGER='touch /tmp/pwn' git log`)).toBe('classify')
  expect(sh(`PAGER='touch /tmp/pwn' git log`)).toBe('classify')
  expect(sh(`GIT_PAGER='touch /tmp/pwn' git log`)).toBe('classify')
  expect(sh(`export PAGER='touch /tmp/pwn'; git log`)).toBe('classify')
  expect(sh('declare -x BASH_ENV=/tmp/evil.sh')).toBe('classify')
  expect(sh(`env -S 'sh -c id' x`)).toBe('classify')
  expect(sh(`env --split-string='sh -c id'`)).toBe('classify')
  expect(sh('FOO=$(git rev-parse HEAD) echo $FOO')).toBe('classify')
  expect(judgeShell(`$env:GIT_PAGER = 'calc'; git log`, 'powershell', ctx).kind).toBe('classify')
})

test('inert assignments stay allowed and never soften a block', () => {
  expect(sh('NODE_ENV=test npm test')).toBe('allow')
  expect(sh('CI=1 LANG=C git log')).toBe('allow')
  expect(sh('export NODE_ENV=test')).toBe('allow')
  expect(sh('env RUST_LOG=debug cargo test')).toBe('allow')
  expect(sh('PAGER=less rm -rf /')).toBe('ask')
})
