---
name: safe-git
description: Branch-safe Git and PR operations for agents. Verify repository, branch and remote before mutating, never push to main, never force-push, never merge or use admin bypass, and use the pre-push guard. Use before any commit, push, branch or PR operation, and when setting up a clone or worktree.
---

# Safe git

Part of the lean skill set; no prerequisite skills. Enforcement is convention plus
a local hook, not server enforcement (the repositories are on a plan without
branch protection). The hook stops mistakes. It does not stop a determined bypass
(`git push --no-verify`). The stronger control is that agents hold a token that
cannot push to `main`, where that is practical.

## Checklist before any mutation

Run the bundled checker from the repository you are about to change:

```text
python <skill-dir>/scripts/safe_git_check.py [--expect-branch task/<id>] [--expect-remote <owner/repo>]
```

It prints the repository, branch, remote and status, and exits non-zero when you
are on a protected branch (`main`, `master`), on a detached HEAD, when the remote
is not the expected repository, or when the expected branch differs. Fix the
situation; do not talk yourself past it.

Then:

- One agent per worktree. Own worktree, branch `task/<id>` created from the
  current default branch. Off-task changes go on a new branch.
- Check you are on the branch you think you are before every commit.
- `git status` and `git diff` before commit: stage named files, not `git add -A`
  over unknown files. Never commit private fixtures, raw logs, credentials, or
  generated conversion output.
- Commit messages end with the agent attribution line the task requires.

## Never, without the maintainer's explicit instruction for the exact action

- push to `main`, force-push anything, delete remote branches or tags;
- merge, squash, enable auto-merge, run `gh pr merge`, use `--admin`, or alter
  branch rules;
- approve your own PR or resolve a thread you did not author;
- hard reset, `git clean -f`, destructive checkout or restore, recursive removal;
- use the maintainer's credential when an agent credential is available, or
  switch accounts to get around a refusal.

Permission to push a feature branch is never permission to merge.

## Hook and token

- The pre-push guard ships in the agentops repo (`lean/hooks/pre-push` and
  `lean/scripts/install_hooks.py`). Install it in each clone with
  `python lean/scripts/install_hooks.py` and confirm with `--check`. It blocks
  pushes to `main` or `master`, deletion of them, and non-fast-forward pushes.
- Prefer an agent token that can push feature branches and open PRs but not push
  `main` or merge. State in the PR if you could not use such a token.
- If the hook or the server refuses an operation, report it. Do not retry with
  `--no-verify` or another identity.
