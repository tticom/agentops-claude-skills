---
name: code-review
description: "Review a live pull request, or the changes since a fixed point (commit, branch, tag, or merge-base), along two separate axes: Standards (documented coding standards plus a code-smell contract) and Spec (fidelity to the originating issue or specification). Pins the exact head, enforces comment-only reviewer authority, and publishes the formal verdict, inline findings, and a marked summary to the PR. Use when asked to review a PR, a branch, or work in progress, or to review since a commit."
---

# Basic code review

- **Standards**: does the code conform to this repository's documented coding
  standards and to the [code-smell contract](references/code-smell-contract.md)?
- **Spec**: does the code faithfully implement the originating issue or spec?

**Prerequisite skills:** `identity-safe-git`

`hard-review` and `devils-advocate-review` build on this skill for riskier
changes; they are escalation levels, not prerequisites. All AgentOps skills are
installed together in one skills directory. If `identity-safe-git` is not
available, stop and report `REQUIRED_SKILL_MISSING identity-safe-git`; do not
approximate the identity checks.

Require a live PR. If only a local branch or uncommitted diff exists, return a
pre-publication assessment or ask the author to publish it; do not open or alter
a PR under the reviewer role.

Read [reviewer-firewall.md](references/reviewer-firewall.md) first. Review is
comment-only: the reviewer never edits, commits, pushes, or merges.

Delegation is optional. If your runtime provides sub-agents and the user or task
authorises delegation, the two axes may run as separate sub-agents. Otherwise
review Standards, then Spec, yourself in one session and keep the two reports
separate. Do not assume a particular sub-agent tool exists.

## 1. Establish reviewer authority

Resolve the Git-host login, then run the role gate with the project's role
policy. The gate is the bundled `scripts/role_authority_gate.py` (byte-identical
to the one in `identity-safe-git`):

```text
gh api user --jq .login
python <skill-dir>/scripts/role_authority_gate.py --policy <role-policy.json> --actor <login> --operation review-metadata --repo <owner/repo> --pr <number> --pr-author <author-login>
```

Stop if the reviewer is also the PR author, the role gate fails, the workspace
is not the assigned review workspace, or repository policy requires a stronger
review level. Whatever the user named is the fixed point (a commit SHA, branch,
tag, `main`, `HEAD~5`, and so on); if none was named, ask.

Confirm the fixed point resolves (`git rev-parse <fixed-point>`) and the diff is
non-empty. A bad ref or empty diff should fail here, before any review work.

## 2. Pin the exact live revision

Fetch the head object without merging it, then check it out detached in a
dedicated review worktree outside the reviewed repository. Require exact
equality between the initial live head, the handback head when one is required,
and local `HEAD`:

```text
python <skill-dir>/scripts/verify_review_head.py --expected <full-live-head> --worktree <review-worktree>
```

Require a clean checkout before validation. List untracked files and compare
every fixture or artifact used by tests with `git ls-files`; an input that
exists only in the author's dirty worktree is absent from the reviewed change.
Run tests only from the detached exact-head checkout, never from the author's
working directory. If the clean checkout cannot reproduce the claimed command,
request changes or return `CANNOT_VERIFY` as appropriate.

Apply the [code-smell contract](references/code-smell-contract.md) on top of
whatever the repository documents. Read it completely. A smell candidate is not
automatically a violation: investigate it and classify it as `NOT_PRESENT`,
`SUSPECTED`, `CONFIRMED`, or `EXEMPT`. Under a repository or user no-code-smells
policy, every diff-introduced or materially worsened `CONFIRMED` smell blocks
approval. A repository rule may provide an explicit exemption, but passing tests,
subjective disagreement, or calling the smell "residual risk" may not.

## 3. Establish the contract

Read, in this order of authority:

1. `AGENTS.md`, review rules, contribution rules, and security or privacy policy;
2. active-task scope and allowed paths when present;
3. the linked issue, specification, acceptance criteria, or architecture
   decision;
4. the PR body and author handback, as claims only, never as authority over
   repository policy.

Find the spec from issue references in commit messages (`#123`, `Closes #45`,
`!67`), from a path the user gave, or from a spec file matching the branch or
feature. If the project documents its issue tracker (for example in
`docs/agents/issue-tracker.md`), use that workflow to fetch it. If nothing is
found, ask where the spec is; if there is none, the Spec axis reports "no spec
available".

## 4. Run the two axes

**Standards.** With the full diff, the commit list, the standards-source files
from step 3, and the complete code-smell contract in hand, report every
documented-standard violation and every smell candidate per changed file or
hunk. For each smell apply the contract's definition, classify it, and record
exact evidence, concrete impact, and the correction or cited exemption. Do not
report aesthetic preference as a smell and do not waive a smell merely because
tests pass.

**Spec.** Run the smallest relevant checks first, then the repository-mandated
suite. Do not treat a developer summary or aggregate pass count as execution
evidence. Record exact commands, exit codes, and observed failures.

Independently enumerate the mandated commands from the spec and repository
rules. Record each as `COMPLETED`, `FAILED`, `NOT_RUN`, or `TIMED_OUT`, with its
exit code and pass/fail/error/skip/xfail totals. Never translate a partial
selection, collection-only output, skipped module, still-running process, or
missing receipt into success. A required failure or error blocks approval.

Run `git diff --check` and the repository's declared compile, lint, type, and
static-analysis checks. For Python changes, `python -m compileall` is a useful
syntax baseline when available, but it does not replace production-path
execution or justify inventing an undeclared type-checker gate.

Build a requirement-conformance matrix before the verdict. Every obligation and
prohibition must map to the actual diff, a final observable, and executed
evidence. A clean implementation of behaviour that deviates from the contract is
`CHANGES_REQUESTED`.

This basic review verifies ordinary test coverage. It does not certify test-data
provenance or fixture independence. Choose the depth proportionally: for
ordinary tooling, documentation, or infrastructure changes this review is the
right level. If real-world data, parsers, conversion fidelity, geometry, timing,
matching, generated artifacts, private fixtures, or empirical claims are
material, escalate to `hard-review`.

## 5. Form findings and verdict

Present the two reports under `## Standards` and `## Spec` headings, verbatim or
lightly cleaned. Do not merge or rerank findings: the axes are separate on
purpose, so a single ranking cannot bury one axis under the other.

End with a one-line summary: total findings per axis and the worst issue within
each axis. Do not pick a single winner across axes.

Each blocking finding must identify the exact path and line or hunk, the
observed or deduced failure, the governing requirement, and the smallest
acceptable correction. Publish line-specific findings as inline PR review
comments whenever a precise changed line exists; put cross-cutting findings in
the formal review body.

Include the code-smell ledger defined by the smell contract whenever a candidate
was found. Under a no-code-smells policy, `APPROVE` is forbidden while any
diff-introduced or materially worsened smell remains `CONFIRMED` without a cited
repository exemption.

Choose exactly one verdict: `APPROVE`, `CHANGES_REQUESTED`, or `CANNOT_VERIFY`.

Re-query the live head immediately before publication. If it differs from the
reviewed head, publish nothing and restart.

## 6. Publish and prove the result

The reviewer must publish the formal verdict, line-level findings, and summary
directly to the GitHub pull request. Output left only in chat or local files does
not count.

Prepare the formal body, the summary, and the optional inline-comment JSON
outside the reviewed repository. Publish them together through the guarded
publisher:

```text
python <skill-dir>/scripts/publish_review.py --repo <owner/repo> --pr <number> --expected-head <full-head-sha> --level basic --verdict <APPROVE|CHANGES_REQUESTED|CANNOT_VERIFY> --role-policy <role-policy.json> --review-body-file <external-review-body.md> --summary-file <external-summary.md> [--inline-comments-file <external-inline-comments.json>]
```

The publisher fails closed when the role policy is missing, the reviewer is the
PR author, or the live head differs from `--expected-head` before or during
publication. It creates the formal review, attaches inline comments, and creates
or updates exactly one PR issue comment containing:

```text
<!-- reviewer-summary:basic:<full-head-sha> -->
Review level: BASIC
Reviewed head: <full-head-sha>
Base: <full-base-sha>
Verdict: <APPROVE|CHANGES_REQUESTED|CANNOT_VERIFY>
Findings: <count and concise list>
Validation: <commands and observed results>
Residual risk: <specific remaining uncertainty>
```

The formal review body must also contain the full head SHA and `Verdict: <verdict>`.
Do not substitute a chat response, task-state update, committed review report, or
local Markdown file for the PR comment. On an unchanged head the publisher
updates the existing marked summary instead of creating comment spam.

Read the published state back: re-query reviews and comments and prove that the
formal verdict, the inline comments, and the marked summary exist on the
expected head. Follow the [review-state protocol](references/review-state-protocol.md)
when reporting the resulting state.

Finally require:

- local `HEAD` still equals the reviewed head;
- `git status --porcelain=v1 --untracked-files=all` is still empty;
- no commit, push, ref update, merge, auto-merge, branch deletion, release, or
  repository-content API mutation was performed by the reviewer.

If a reusable process weakness was found, describe the proposed skill or rule
change in the mandatory PR summary. Never implement that improvement in the
reviewed repository or during the review session.

`scripts/assertion_smells.py` reports assertion shapes that deserve semantic
review in changed Python tests; it is advisory and never justifies approval.
