---
name: changes-requested
description: Address CHANGES_REQUESTED review verdicts on open pull requests. Ingest reviewer findings, reproduce defects on the reviewed head, apply minimal safe fixes, verify regressions, and hand back with evidence.
---

# Changes-Requested Remediation

Execute a disciplined remediation loop for an open pull request that received a
`CHANGES_REQUESTED` verdict from `code-review`, `hard-review`,
`devils-advocate-review`, or a human maintainer.

**Prerequisite skills:** `publish-pr-handback`

All AgentOps skills are installed together in one skills directory. If
`publish-pr-handback` is unavailable, stop and report
`REQUIRED_SKILL_MISSING publish-pr-handback`; do not publish a free-form handback.
Use `python` for the helpers; where that name is missing use `python3` or `py -3`.
They run natively on Windows, macOS, and Linux.

This skill applies only to a PR **you authored**. If the PR was authored by
another identity, do not push to its branch: post findings or suggestions as PR
comments and stop, so authorship and independent review stay separate.

## Core Rules

1. **Never amend or force-push** published review heads. Follow-up commits must be
   added on top of the branch.
2. **Never dismiss or self-resolve** a reviewer finding without a reproducing test
   and code evidence.
3. **Reproduce before fixing**: write a discriminating negative test or minimal
   probe proving the defect on the reviewed head before modifying production code.
4. **Preserve task boundaries**: fix only the cited defects and adjacent
   regressions. Do not widen task scope or invent architecture.
5. **Publish via handback**: return the PR to its review-ready state atomically
   using `publish-pr-handback`.
6. Permission to remediate never authorises a merge, a push to a protected
   branch, deleting a branch, a credential change, or bypassing a required check.

---

## Remediation Workflow

```text
Fetch Findings → Pin Reviewed Head → Reproduce Red → Fix Green → Pre-Flight → Handback
```

### 1. Ingest Review Findings

Query GitHub for the latest review and unresolved threads. Write the ledger
**outside the repository** so it does not dirty the worktree the pre-flight
requires to be clean:

```text
python <skill-dir>/scripts/fetch_review_findings.py --repo <owner/repo> --pr <number> --output <external-dir>/review-remediation-ledger.md
```

`scripts/fetch_review_findings.py` selects the latest non-dismissed formal review
by server timestamp then review ID, reads unresolved review threads (GraphQL,
falling back to REST comments), and flags a review or summary comment pinned to a
head older than the live PR head as STALE. Add `--json` for machine-readable output.

Verify:

- the PR is open and the branch matches;
- `Reviewed Head` equals the commit SHA evaluated in the latest review, and any
  STALE warning is understood;
- every inline comment and contradiction-ledger item is accounted for.

### 2. Pin the Author Worktree

Ensure the local worktree is clean and on the exact PR branch:

```text
git checkout <pr-branch>
git pull --ff-only
git rev-parse HEAD
git status --porcelain=v1
```

The printed `HEAD` must equal the reviewed head SHA. If local commits exist beyond
the reviewed head, inspect them before proceeding. Do not build fixes on
uncoordinated branch state.

### 3. Build the Remediation Plan

For each unresolved finding, identify:

1. **Root cause**: the exact condition causing failure (for example an empty
   collection passing `all()`, a dropped status filter, or branch contamination).
2. **Reproduction**: a focused test that fails at the current reviewed head (`RED`).
3. **Minimal fix**: the smallest safe change satisfying the requirement and
   preserving fail-closed behaviour.
4. **Negative controls**: values that must remain rejected.

### 4. Execute Red-to-Green Remediation

For each finding:

1. **Write the reproduction test** at the public interface or production seam. Run
   it against the unmodified code and confirm it **fails** as expected (`RED`).
2. **Apply the minimal correction** to authorised files inside task scope. Run the
   test again and confirm it **passes** (`GREEN`).
3. **Check adjacent boundaries**: test zero, one, many; test boundary values
   (`t - ε`, `t`, `t + ε`); check that valid inputs are not broken and invalid
   inputs do not fall through to defaults.

### 5. Clean-Head Pre-Flight

Before committing, run and record each of these:

1. `git status --porcelain=v1 --untracked-files=all` shows no untracked junk;
2. `git diff --check <base>...HEAD` reports no whitespace or formatting errors;
3. the repository-mandated linters and type checks;
4. the repository-mandated full test suite.

Every mandated test command must complete with exit code 0, with 0 failures and 0
unexpected errors. Skips or xfails must be explicitly justified.

### 6. Commit and Push

Stage and commit follow-up changes with a message that traces to the review
findings, then push the PR branch (never a protected branch, never with force):

```text
git add <modified-files>
git commit -m "fix: address review findings on <finding-summary>"
git push origin <pr-branch>
```

Record the new branch head SHA (`git rev-parse HEAD`).

### 7. Publish PR Handback

Construct an `author-handback.v1` packet (see `publish-pr-handback`), outside the
worktree, populating `review_findings` with one entry per finding:

```json
{
  "schema_version": "author-handback.v1",
  "task": "<task-id>",
  "repository": "<owner/repo>",
  "pr": 123,
  "head": "<new-head-sha>",
  "base": "<base-sha>",
  "changed_paths": ["<live PR changed paths>"],
  "validation_runs": [],
  "acceptance": [],
  "review_findings": [
    {
      "finding": "Inline comment <id>: empty allowed_paths list accepted",
      "disposition": "Enforced a non-empty list and stripped-string validation",
      "evidence": "tests/test_contracts.py::test_empty_contracts_rejected PASS at <new-head-sha>"
    }
  ],
  "remaining_risks": []
}
```

Populate `validation_runs` and `acceptance` exactly as `publish-pr-handback`
requires; the empty lists above only show the shape. Publish with that skill's
handback publisher, then confirm `AUTHOR_HANDBACK_PUBLICATION=PASS` is
printed. Stop and wait for independent re-review.
