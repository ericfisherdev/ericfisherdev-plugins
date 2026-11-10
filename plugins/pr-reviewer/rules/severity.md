# Severity and blocking

Two separate decisions. Severity says how bad it is. Blocking says whether the merge should wait. One shared definition, applied by every reviewer, the verifier and the refuter, so that the same defect gets the same weight whoever finds it.

## Severity

| Value | Meaning |
|---|---|
| `critical` | On a reachable path the change loses or corrupts data, exposes data or access it should not, or breaks the build, the deploy, or the feature it exists to deliver for every user of that path. |
| `major` | Wrong behaviour on a realistic path with a real consequence for a user, an operator or another system, but contained: one branch, one failure mode, one class of input. |
| `minor` | Real and worth fixing, with a small consequence: a misleading message, an edge case that degrades instead of failing, an avoidable cost, a gap that will bite a later change. |
| `nit` | Cosmetic or local: naming, a stale comment, duplicated lines, a typo. |

Judge the consequence, not the category. A security-flavoured finding with no reachable exploit is `minor`. A one-character typo in a config key that stops a job from running is `critical`.

## Blocking

A finding is **blocking** only when all three hold:

1. It has a **runtime consequence** on shipped behaviour: wrong result, lost or corrupted data, exposure, an outage, a broken build or deploy.
2. The path is **reachable** in normal operation or by an input the system must expect. You can name the trigger.
3. Merging as-is makes things **worse than not merging**, and the fix belongs in this PR.

Never blocking, whatever its severity:

- Documentation, comments and docblocks, including ones that are wrong.
- Naming, structure, layering, duplication and other maintainability points.
- Missing or weak tests.
- Error messages that mislead but do not change behaviour.
- Performance that is slow but correct, unless the diff makes a realistic request time out or exhaust a limit.
- A question. If you need the author to tell you something before you can call it a defect, it is not yet a defect.

The finalizer enforces the first three mechanically: a finding in the `docs`, `style`, `maintainability` or `test-coverage` category is never blocking, and every `critical` finding in another category is.

## Calibrate both ways

The commonest error, by a wide margin, is inflation: calling a real but small finding blocking. In the benchmark this plugin was tuned on, roughly one finding in six was marked blocking when it should not have been, and almost all of those were documentation, maintainability, test or wording points. An inflated review gets ignored, and then the one true blocker in it gets ignored too.

The opposite error is rarer and worse: a path that fails every time, called `minor` because nothing has broken yet. If the code cannot work as written, say `critical`.

Do not grade to the middle. A list where everything is `major` has ranked nothing.

## Confidence

Reviewers attach a confidence from 0 to 100 that the finding is real as stated.

| Range | Use |
|---|---|
| 90 to 100 | You read every line the claim depends on and can state the trigger. |
| 70 to 89 | The code supports it, and one link (a caller, a config value, a remote response) is inferred. Say which. |
| 50 to 69 | Plausible and worth the verifier's time; you could not close it. Say what is missing. |
| below 50 | Do not report it. |
