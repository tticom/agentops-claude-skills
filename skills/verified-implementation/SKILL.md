---
name: verified-implementation
description: Implement a specification or set of tickets with evidence-gated completion, meaning captured test results, no false green, provenance-classified inputs, a traced final effect, and a clean-head pre-flight before handback. Use when implementing specified work that another identity will review independently, or when completion claims must be backed by executed evidence.
---

# Verified implementation

Implement the work described by the user in the spec or tickets, and refuse to call
it done until executed evidence says so. This skill governs how completion is
claimed; it does not choose the design or widen the scope.

**Prerequisite skills:** `code-review`

Read the code-smell contract bundled with the `code-review` skill (in that skill's
references) and apply it to your own changes. Reading that document is all this
skill takes from `code-review`: do not perform a review, publish a verdict, or
approve your own work. All AgentOps skills are installed together in one skills
directory; if `code-review` is unavailable, stop and report
`REQUIRED_SKILL_MISSING code-review`.

Work test-first at pre-agreed seams where practical. Run type-checking regularly,
single test files regularly, and the repository's mandated full test suite once at
the end. A test command counts as run only after it finishes and its exit code and
complete pass/fail/error/skip/xfail totals are captured. Starting it, collecting
tests, running a smaller subset, relying on CI, or citing an earlier head does not
count.

Do not claim completion, success, green status, or review readiness when a required
command was not run, did not finish, exited non-zero, or contains an unexpected
failure or error. Report `FAILED`, `NOT_RUN`, `BLOCKED`, or `TIMED_OUT` literally
and stop. Never add or widen skips or xfails merely to turn a failing aggregate
green.

Classify acceptance inputs as real-source, real-source extract, synthetic or
mocked, or data-free. If the contract requires genuine-source evidence or forbids
synthetic data, generated files, invented values, reconstructed inputs, and
generator-authored expected output are not permitted substitutes. If the genuine
source or independent oracle is unavailable, report `BLOCKED`; do not manufacture
one. Where the change does not depend on real-world data (ordinary tooling,
documentation, refactoring), controlled fixtures are appropriate: do not demand
real-source evidence the change cannot use.

## Prove external data assumptions first

Before implementing a heuristic that depends on an external library, file format,
API, parser, or downstream schema, inspect representative live data at the exact
production boundary. Use a disposable scratch probe outside tracked source, and
record the library or runtime version, input provenance, command, and observed
field values, types, units, cardinalities, and absent or degenerate cases. Derive
the implementation rule from those observations and the authoritative contract.
Documentation or intuition alone is insufficient when the behaviour is cheaply
observable.

Do not promote one observation into a universal heuristic. Exercise multiple
genuine sources or cite a domain invariant, and test both sides of every chosen
boundary. If live data contradicts the proposed design, stop and return the
evidence rather than coding around the discrepancy.

## Trace the final production effect

A passing helper or unit test does not complete a user-facing feature. Trace the
changed value through each production handoff to its final consumer and
user-visible artifact. Verify that the normal entrypoint consumes the new value, no
later transformation drops or overwrites it, and the final output contains the
exact required semantic result. Include a closest negative control that reaches the
same path but must not produce that result.

For pipeline, parser, conversion, serialization, or integration work whose
behaviour depends on real data, run at least one genuine-source end-to-end
acceptance test unless the contract explicitly says otherwise. When authority or
required private data prevents that run, the result is `BLOCKED` or `NOT_RUN`,
never complete.

Once done, run an author self-check against the specification and the repository
validation contract. Do not invoke a reviewer skill, publish a formal review, or
approve your own work.

## Detect code smells mechanically

Run the repository's declared linters and static analysers, including its
dead-code, unused-variable, and complexity checks, before handback. For example,
where the repository uses `ruff`, run `ruff check` with its configured rules over
the source and test paths it declares; fix trivial findings and evaluate the rest.
Use the output to inform your code-smell ledger. If a tool flags high complexity or
an unused variable, either refactor the code to remove the smell or justify it in
the ledger. Do not invent a tool the repository does not declare, and do not report
a tool that was not run as passing.

Apply the code-smell contract to every changed production and test path. Record
each candidate as `NOT_PRESENT`, `SUSPECTED`, `CONFIRMED`, or `EXEMPT`, with exact
evidence and impact. Under a no-code-smells policy, do not hand back while a
diff-introduced or materially worsened `CONFIRMED` smell remains. Passing tests do
not waive dead code, test theatre, exception-as-fallback, circular evidence, weak
assertions, undefined heuristics, or another confirmed smell. A suspected smell
requires inspection, not speculative refactoring; an exemption requires a cited
repository rule or task requirement.

Build a requirement ledger before handback. For every obligation record the
changed production path, final observable, test node, input provenance, independent
oracle, exact-head command, and observed result. A deviation, missing
production-path test, unexecuted command, synthetic-only evidence where real-source
evidence is required, or non-independent oracle leaves the requirement unmet. Do
not relabel it as a limitation while claiming completion. Attach the smell ledger
to this self-check when any smell candidate was found.

## Clean-head pre-flight

Immediately before publication:

1. `git status --porcelain=v1 --untracked-files=all`: every required source,
   fixture, oracle, and generated input must be intentionally tracked, and no
   unexplained local file may contribute to a passing test.
2. `git diff --check` against the review base.
3. Repository-declared formatting, lint, type, static-analysis, schema, and
   artifact checks.
4. For Python, `python -m compileall` when appropriate as a syntax baseline; do
   not misrepresent it as undefined-name analysis.
5. Focused production-path tests followed by the complete mandated suite.
6. Repeat the final-output acceptance assertion from the clean committed head.

Any failure returns the task to implementation. Do not publish a handback and
promise that CI or the reviewer will discover the remaining defects.

Commit and publish the authorised branch (never a protected branch, never with
force), then stop for independent review by another identity using `code-review`,
`hard-review`, or `devils-advocate-review`. Do not merge.
