---
name: review
description: Review a pull request or branch diff along two separate axes, Standards (documented rules plus the code-smell contract) and Spec (fidelity to the task or issue), pinned to one exact head. Has a normal mode and an --adversarial mode that presumes every claim is wrong and checks test-data provenance, oracle independence and fixture coupling. Use for an independent review of a risky change, or when asked to review a PR, a branch, or changes since a commit.
---

# Review

An independent review is optional and advisory. It exists to catch what the
author and CI cannot, and is requested for `risky` tasks: conversion fidelity,
parsers, geometry, fallbacks, anything touching private fixtures, CI or
governance files, or a disputed PR. The maintainer decides whether to merge.
A review is a PR comment, not an approval that lets anything merge.

Two axes, kept separate and never re-ranked against each other:

- **Standards**: documented repository rules plus the
  [code-smell contract](references/code-smell-contract.md).
- **Spec**: does the code do what the task or issue says?

Modes: **normal** (default) and **adversarial** (`--adversarial`, section 4). Use
adversarial for risky conversion, parser, geometry or fixture work, when a
previous review was wrong, or when asked for a real or final review.

## Reviewer rules

Review is comment-only. A reviewer fetches, inspects, runs tests in a clean
detached checkout and writes probes outside the repository. It never edits,
commits, pushes, merges, or enables auto-merge, and never implements a suggested
fix during the review. Review from a fresh session: do not reuse the author's
context. Never approve your own work.

## 1. Pin the head

Resolve the live head SHA (`gh pr view <n> --json headRefOid`). Create a detached
review worktree outside the reviewed repository at that head and verify:

```text
python <skill-dir>/scripts/verify_review_head.py --expected <full-head-sha> --worktree <review-worktree>
```

Require a clean checkout. Compare every fixture or artifact used by tests with
`git ls-files`: an input that exists only in the author's dirty worktree is not
part of the reviewed change. Run everything from the detached checkout.

## 2. Establish the contract

Read, in order: `CLAUDE.md`/`AGENTS.md` and privacy rules; the task entry (scope,
allowed paths, risk); the linked issue or spec; the PR body as claims only.
Flag changed files outside the task's allowed paths. If no spec exists, the Spec
axis says "no spec available".

## 3. Run the axes

**Standards.** Over the full diff, report documented-standard violations and
smell candidates per file or hunk, classified `NOT_PRESENT`, `SUSPECTED`,
`CONFIRMED` or `EXEMPT`, with exact evidence, impact, and the smallest correction.
Aesthetic preference is not a smell, and passing tests do not waive one.

**Spec.** Run the smallest relevant checks, then the mandated suite. Record each
mandated command as `COMPLETED`, `FAILED`, `NOT_RUN` or `TIMED_OUT` with exit code
and pass/fail/error/skip/xfail totals. A partial run, collect-only output or a
skipped module is never success. Run `git diff --check` and the declared lint and
type checks. Map every obligation to the diff, a final observable and executed
evidence. A clean implementation that deviates from the contract is a finding.

## 4. Adversarial mode

Begin from the provisional verdict `CHANGES_REQUESTED`; the change must earn its
way out one claim at a time. Do this in addition to sections 1 to 3.

1. **Claims are hostile evidence.** The PR body, test names, green summaries, and
   words like "end-to-end", "real-world", "no leak", "resolved" or "100%" are
   unverified until you reproduce them. Prior reviewers' approvals carry no weight.
2. **Provenance.** Classify every changed or cited test as `REAL_SOURCE_END_TO_END`,
   `REAL_SOURCE_EXTRACT`, `SYNTHETIC_OR_MOCKED` or `DATA_FREE`, by how the input
   was built rather than by its filename. For behaviour that depends on real data,
   synthetic and data-free tests carry no acceptance weight. Skips, xfails and
   deleted tests in the diff must be inventoried: a skipped test is not evidence.
3. **Oracle independence.** Trace real source, production transformation, output,
   independent oracle, exact assertion. The oracle must not feed the conversion
   path. Output-exists, count-only and pass-count assertions are not fidelity proof.
4. **Fixture coupling.** Production code must not mention fixture names, hashes,
   paths, page numbers, coordinates or expected counts:

   ```text
   python <skill-dir>/scripts/fixture_coupling_scan.py --production <file> [...] --fixture-root <root> [...]
   ```

   Treat output as leads, not proof. For heuristics, require examples on both sides
   of each boundary from more than one real source.
5. **Falsify.** For each material claim, name the smallest broken implementation
   that would still pass and verify the assertion would fail under it. Run at
   least three independent probes you wrote yourself (four for parser, timing,
   conversion-fidelity, privacy or fail-closed claims), against the pinned head,
   and record input, command, observed output and exit code. Run
   `python <skill-dir>/scripts/assertion_smells.py <changed tests>` as a lead only.
6. **Real source.** Where fixtures are available to you, run the real-fixture check
   yourself rather than trusting the author's counts. If private data is not
   available to you, say `CANNOT_VERIFY` for that claim.

The full protocol is in
[evidence-falsification-protocol.md](references/evidence-falsification-protocol.md);
read it before evaluating test evidence in adversarial mode.

## 5. Verdict and publication

Present `## Standards` and `## Spec` separately, then one line with counts and the
worst issue per axis. Each blocking finding names the path and line, the observed
failure, the governing requirement and the smallest correction. Choose one verdict:
`APPROVE` (no blocking finding, advice only), `CHANGES_REQUESTED`, or
`CANNOT_VERIFY`. These are advisory.

Re-query the head immediately before publishing; if it moved, restart. Publish as
a single PR comment (`gh pr comment <n> --body-file <file>`, file kept outside the
repository), whose first line is:

```text
Review @ <full-head-sha> | mode: <normal|adversarial> | verdict: <APPROVE|CHANGES_REQUESTED|CANNOT_VERIFY>
```

followed by the two axes, the commands run with results, and specific residual
risk. Sanitise: counts and statuses only, no raw logs, private paths or fixture
content. A re-run on a new head produces a new comment; do not edit old ones.
Finally confirm local `HEAD` is still the reviewed head and the checkout is clean.
