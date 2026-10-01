---
name: workspace-cleanup
description: Safely remove stale review worktrees and prune dead worktree metadata across the Git checkouts in an agent workspace, preserving any dirty, locked, unclassified, or unverified work, and record a receipt and checkout index. Use when asked to clean up the workspace, remove stale review worktrees, or produce a map of the workspace checkouts.
---

# Workspace cleanup

Remove disposable review worktrees that are **provably** stale, keep everything
else, and leave a receipt of every decision.

This skill has no prerequisite skills. It needs `git` (and optionally the GitHub
CLI, `gh`) and Python 3.11+, and runs natively on Windows, macOS, and Linux. Use
`python`; where that name is missing use `python3` or `py -3`.

## What it will and will not do

It scans the Git checkouts that are direct children of one workspace directory,
each underlying repository once. It:

- prunes dead worktree metadata (`git worktree prune`);
- removes a worktree **only when** its directory name matches the review pattern,
  it is clean, it is not locked, and its branch is merged into the base branch or
  its pull request is `MERGED` or `CLOSED`;
- **preserves** everything else and records why: dirty, locked, detached-HEAD,
  unclassified (name does not match), missing directory, or merely unverified.

Absence of evidence is never evidence of staleness. It never deletes a branch,
never touches a checkout's working files, never force-removes, and never operates
on a filesystem root or a home directory.

**The requested workspace is the boundary.** Git's worktree list is repository-wide,
so a checkout in the workspace can have linked worktrees anywhere on disk. Every
worktree and checkout is resolved (symlinks and Windows junctions followed, compared
by path components, case-insensitive on Windows) and must lie inside the workspace
before it is considered. Anything that resolves outside is preserved and recorded as
"outside the requested workspace", on a dry run and a real run alike.
`git worktree prune` cannot be limited to a path, so it runs only when every prunable
entry is inside the workspace; if any is outside, pruning is skipped for that
repository and the receipt says so. (Git older than 2.31 does not report prunable
entries, so on such a version metadata is not pruned.)

**Which checkout runs git never decides what is cleaned.** Git lists the primary
checkout first; it is preserved and recorded ("primary checkout"), never removed.
Every other worktree of the repository is judged on its own merits, wherever it sorts
alphabetically, and git commands are issued from a checkout other than the one being
removed (the primary when it exists, otherwise another linked checkout). A workspace
that holds only linked worktrees is cleaned the same way. If the repository cannot be
read at all (for example its primary was deleted), that is reported as an error and
nothing is removed.

## Run it

Always preview first:

```text
python <skill-dir>/scripts/workspace_cleanup.py --workspace <workspace-dir> --dry-run
```

Read the preview. Only when the listed removals are what the user intends, run the
same command without `--dry-run`. Summarise the receipt and give the paths of the
receipt and the index.

Options (all optional):

- `--workspace <dir>`: the workspace; else `AGENTOPS_WORKSPACE`; else the parent
  of the repository you are in.
- `--review-worktree-pattern=<regex>`: which worktree directory names are disposable
  reviews (default `-review-pr-|-review$`). Use the `=` form, because a pattern
  that starts with a dash would otherwise be read as an option.
- `--base-branch <name>`: branch a stale review must be merged into (default:
  origin's default branch, else `main`).
- `--no-gh`: do not consult the GitHub CLI for pull-request state.
- `--allowed-user <name>` (repeatable): refuse to run unless the OS user is listed.
  The script has no built-in list of users.
- `--receipt-dir <dir>` and `--index-file <path>`: where outputs go (defaults live
  under `<workspace>/agentops-logs/`, outside every scanned repository).
- `--active-task-pointer <path>`: shown in the index; informational only.

## Outputs

- a JSON receipt (`<timestamp>-cleanup-receipt.json`) listing every worktree with
  its action (`removed_worktree`, `preserved`, `pruned_metadata`, `dry_run_remove`,
  `dry_run_prune`, `error`) and the reason;
- a human-readable checkout map (branch, short HEAD, clean or dirty) for each
  checkout that remains.

## Boundaries

A cleanup request authorises removing stale review worktrees only. It does not
authorise deleting branches, discarding uncommitted work, changing credentials, or
bypassing a check. If the user wants more removed than the script judges stale,
that is a separate, explicit decision about exact paths: do not widen the pattern
or force removal to satisfy it.
