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
