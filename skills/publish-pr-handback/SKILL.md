---
name: publish-pr-handback
description: Validate and atomically publish a complete exact-head pull-request author handback. Use after an author pushes a new or revised PR head in a review-gated workflow, before claiming a review-ready state, or when repeated stale or malformed handback comments leave a dispatcher waiting.
---

# Publish PR Handback

Publish through the bundled script. Never type or paste the head SHA into a
free-form PR comment and call that a handback.

This skill has no prerequisite skills. It needs `git`, the GitHub CLI (`gh`)
authenticated as the PR author, and Python. It runs natively on Windows, macOS,
and Linux. Use `python`; where that name is missing use `python3` or `py -3`.

## Prepare the evidence packet

Create a JSON file **outside the worktree** (a packet inside it makes the
worktree dirty and the publisher refuses to run) with this shape:

```json
{
  "schema_version": "author-handback.v1",
  "task": "Task identifier and title",
  "repository": "owner/repo",
  "pr": 123,
  "head": "40-character SHA",
  "base": "40-character SHA",
  "changed_paths": ["path/from/live/pr"],
  "validation_runs": [
    {
      "command": "Repository-mandated command actually completed",
      "status": "PASS",
      "exit_code": 0,
      "passed": 10,
      "failed": 0,
      "errors": 0,
      "skipped": 0,
      "xfailed": 0,
      "deselected": 0
    }
  ],
  "acceptance": [
    {
      "criterion": "Exact required observable",
      "status": "PASS",
      "command": "Command actually executed",
      "observed": "Exact observed result",
      "oracle": "Independent source of the expected result"
    }
  ],
  "review_findings": [
    {
      "finding": "Prior finding identifier or summary",
      "disposition": "What changed",
      "evidence": "Fresh exact-head evidence"
    }
  ],
  "remaining_risks": []
}
```

Derive `head`, `base`, and `changed_paths` from the live PR. Copy neither a chat
summary nor an earlier handback. Every acceptance item must identify the final
observable and an independent oracle. An exit code alone is not an observable
when the command is diagnostic or can succeed after partial work.

Use `FAIL` or `NOT_RUN` while diagnosing locally, but the publisher refuses
either status for a review-ready handback. Resolve the criterion or report a
blocked state without publishing a review-ready state.

`validation_runs` must enumerate every command mandated by the repository or
task. Do not omit a failing command, replace the full suite with a focused
selection, or call collection or launch evidence a completed run. A run is `PASS`
only when it finished at the packet head with exit code zero and zero recorded
failures or errors. Record skips, xfails, and deselections literally and explain
their authority in `remaining_risks` whenever they are non-zero.

## Choose the hand-off state

The state names the review the author is now waiting for. It is project
vocabulary, so the script's built-in default is the neutral
`AWAITING_INDEPENDENT_REVIEW`. A project that uses its own states supplies them:
repeat `--allowed-state <NAME>` or set `AGENTOPS_HANDBACK_STATES` to a
comma-separated list. Names are upper-case letters, digits, and underscores. A
state that is not accepted is refused before any network call.

## Publish atomically

Run from the clean author worktree. Read the head with `git rev-parse HEAD` and
pass it literally, so the command is identical in PowerShell, cmd, and bash:

```text
python <skill-dir>/scripts/publish_handback.py --repo <owner/repo> --pr <number> --expected-head <full-head-sha> --worktree . --packet <absolute-path-to-handback.json> --state AWAITING_INDEPENDENT_REVIEW
```

Add `--dry-run` to run every check and print `DRY_RUN_PASS` without writing.

The script fails closed unless:

- the authenticated actor is the PR author;
- the PR is open and local branch and head equal the live branch and head;
- the worktree is clean;
- the packet repository, PR, base, head, and changed paths equal live GitHub state;
- every declared validation run completed successfully with explicit totals;
- every acceptance entry is complete and `PASS`;
- the head remains unchanged through publication; and
- a separate read of the persisted comment (its id, author, pull request, marker, and
  full body) matches what was published, and exactly one marked handback exists for
  the head. The response to the write is never treated as proof, and a non-object element in a
  fetched comment list is a failure, never filtered out.

The script generates the comment. Repeated execution on an unchanged head updates
the same marked comment (only one authored by the same actor) rather than creating
duplicates, and it searches every page of the comment thread, so an existing handback
is found however long the thread is. Report review readiness only after it prints
`AUTHOR_HANDBACK_PUBLICATION=PASS`; any failure prints
`AUTHOR_HANDBACK_PUBLICATION=FAIL` with the reason and exits non-zero.

## Boundaries

This receipt proves publication integrity and packet completeness. It does not
prove that an acceptance claim is true. Independent reviewers must still run
their own probes and may overturn every author claim. Running this skill never
authorises a merge, a push to a protected branch, a force push, or bypassing a
required check.
