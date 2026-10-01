---
name: implement
description: Implement a task with evidence-gated completion, meaning captured test results, no false green, provenance-classified inputs, a traced final effect, and a clean-head pre-flight before opening or updating a PR. Use when implementing specified work, a TASKS.md entry, or whenever a completion claim must be backed by executed evidence.
---

# Implement

Implement the task you were given, and refuse to call it done until executed
evidence says so. This skill governs how completion is claimed. It does not choose
the design or widen the scope.

Part of the lean skill set. It has no prerequisite skills. Read the bundled
[code-smell contract](references/code-smell-contract.md) and apply it to your own
changes. Do not review or approve your own work, and never merge.

## Before you start

1. Read the task entry (`TASKS.md`) or the issue: outcome, allowed paths, risk
   (`normal` or `risky`). Work inside the allowed paths. If the work needs a path
   outside them, stop and ask rather than widening scope.
2. Use the `safe-git` checklist: own worktree, a `task/<id>` branch, never `main`.
3. If the task is `risky` (conversion logic, parsers, geometry, fallbacks, private
   fixtures, CI or governance files), plan the real-source check now.

## While you work

Work test-first at agreed seams where practical. Run type checks and single test
files often, and the full mandated suite once at the end. A command counts as run
only after it finishes and its exit code and pass/fail/error/skip/xfail totals are
captured. Starting it, collecting tests, running a subset, relying on CI, or
citing an earlier head does not count.

Do not claim completion, green status, or readiness when a required command was
not run, did not finish, exited non-zero, or shows an unexpected failure. Report
`FAILED`, `NOT_RUN`, `BLOCKED` or `TIMED_OUT` literally and stop. Never add or
widen skips or xfails to turn a failing run green. A skipped test is
`NOT_EVALUATED`, never a pass.

Classify acceptance inputs as real-source, real-source extract, synthetic or
mocked, or data-free. Where the claim depends on real-world data, synthetic input
and generator-authored expected output are not substitutes. If the genuine source
or an independent oracle is unavailable, report `BLOCKED`; do not manufacture
one. Where the change does not depend on real data (tooling, docs, refactoring),
controlled fixtures are fine: do not demand evidence the change cannot use.

No silent fallbacks: if input is missing or invalid, fail closed with a named
error. Never invent data to make a test or a conversion succeed.

## Prove external data assumptions first

Before coding a heuristic that depends on a library, file format, API or parser,
inspect representative real data at the production boundary with a disposable
probe outside tracked source. Record the version, input provenance, command, and
observed values and types, including absent or degenerate cases. Do not promote
one observation into a universal rule: use several sources or a domain invariant
and test both sides of each boundary. If live data contradicts the design, stop
and return the evidence.

## Trace the final effect

A passing helper test does not complete a user-facing feature. Trace the changed
value through each production handoff to the final output and check the output
carries the exact required result. Include a nearest negative control that must
not produce it. For conversion work, run at least one real-source end-to-end check
(see the repository's real-fixture script) unless the task says otherwise; if it
cannot run, the result is `BLOCKED`, never complete.

## Mechanical checks and smells

Run the repository's declared linters and analysers. Apply the smell contract to
every changed path and record each candidate as `NOT_PRESENT`, `SUSPECTED`,
`CONFIRMED` or `EXEMPT`. Do not hand back with a diff-introduced `CONFIRMED`
smell. Do not invent tools the repository does not declare.

## Clean-head pre-flight (before marking the PR ready)

1. `git status --porcelain=v1 --untracked-files=all`: every needed file is
   intentionally tracked, and no stray local file contributes to a pass.
2. `git diff --check` against the base.
3. Declared format, lint and type checks.
4. Focused production-path tests, then the complete suite.
5. For `risky` tasks, the local real-fixture check passes (counts recorded).
6. Re-run the final-output assertion from the clean committed head.

Any failure returns you to implementation.

## Hand back

Open a draft PR (never push to `main`, never force-push, never `--admin`). The PR
body states: task id, what changed, tests run with exit codes and counts,
real-fixture result as counts only, limits, and risk. No raw logs, private paths
or fixture content. Mark ready when CI is green. Then stop: the maintainer merges,
and independent review for `risky` tasks is requested through the `review` skill.
