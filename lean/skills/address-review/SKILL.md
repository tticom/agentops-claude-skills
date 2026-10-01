---
name: address-review
description: Address review findings on a pull request you authored. Ingest the reviewer's findings, reproduce each defect on the reviewed head, apply minimal fixes, verify regressions, and push follow-up commits with evidence. Use when a PR has CHANGES_REQUESTED, review comments, or an advisory review that found defects.
---

# Address review

Part of the lean skill set; no prerequisite skills. Use `python` for the helper
(or `python3`, or `py -3`).

Applies only to a PR you authored. For someone else's branch, post findings as PR
comments and stop.

## Rules

1. Never amend or force-push a published head; add follow-up commits.
2. Do not resolve or dismiss a reviewer's thread, and do not reply "fixed" in its
   place. The reviewer resolves its own threads.
3. Reproduce before fixing: write a discriminating failing test or probe on the
   reviewed head first.
4. Fix only the cited defects and adjacent regressions. No scope widening.
5. Permission to fix is not permission to merge, push to `main`, bypass a check,
   or delete branches.

## Workflow

1. **Ingest.** Write the ledger outside the repository:

   ```text
   python <skill-dir>/scripts/fetch_review_findings.py --repo <owner/repo> --pr <n> --output <external-dir>/ledger.md
   ```

   Verify the reviewed head matches the head you hold, and understand any STALE
   warning. Every finding gets a ledger line. Advisory reviews posted as comments
   (`Review @ <sha> | ...`) count as findings too: read them on the PR.
2. **Pin.** Clean worktree on the PR branch; `git rev-parse HEAD` equals the
   reviewed head (or inspect extra local commits first).
3. **Plan.** For each finding: root cause, a failing reproduction (RED), the
   minimal fix, and negative controls that must stay rejected.
4. **Red to green.** Confirm the test fails on unmodified code, apply the fix,
   confirm it passes, then check adjacent boundaries (zero/one/many, just inside
   and outside each limit, invalid input not falling through to defaults).
5. **Pre-flight.** Same as `implement`: clean status, `git diff --check`, declared
   lint and type checks, the full suite, and for `risky` tasks the real-fixture
   check. Every mandated command must complete with exit 0.
6. **Push** the branch (never a protected branch, never force) and record the new
   head SHA.
7. **Report** in a PR comment: for each finding, its id or `path:line`, the fix,
   and exact-head evidence (command, exit code, counts). A finding with no entry
   has not been addressed. Then wait for re-review or the maintainer.

A finding you believe is wrong is disputed with a reproducing test and code
evidence in the comment, never by silence.
