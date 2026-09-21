---
name: governed-development-loop
description: Execute a versioned, review-gated development task without conflating project policy with reusable workflow mechanics. Use when a repository has an active-task pointer or approved prompt, fixed scope, validation contract, separate author/reviewer identities, or a one-PR-at-a-time development loop.
---

# Governed development loop

Run one authorised change from verified starting state to an independently
reviewable remote head. Treat the project profile as policy and this skill as the
reusable execution engine.

**Prerequisite skills:** `identity-safe-git`, `publish-pr-handback`, `durable-handoff`

All AgentOps skills are installed together in one skills directory. If a
prerequisite is unavailable, stop and report `REQUIRED_SKILL_MISSING <name>`; do
not improvise its checks. Independent review uses `code-review`, `hard-review`, or
`devils-advocate-review` under a different identity; those are the reviewer's
skills, not steps of this loop.

## Inputs

Locate or request the active-task pointer, project profile, base branch,
authorised paths, validation commands, and permitted delivery action. Read
[project-profile.md](references/project-profile.md) when creating or reviewing a
project profile.

Do not infer execution authority from a backlog, plan, report, unchecked item, or
suggested follow-up.

## Pin the run

Before writing:

1. Apply `identity-safe-git` with the project profile.
2. Fetch without mutating the worktree.
3. Record the exact base SHA, the active-task revision, and the revision of the
   installed AgentOps skills when the installation records one.
4. Confirm the worktree is clean or every existing change is understood and
   outside the task.
5. Confirm no predecessor PR or governance gate remains open.

A mismatch is a no-write stop. Do not switch credentials inside a workspace,
repair unrelated state, or use another identity's clone.

## Execute one bounded task

1. Create the authorised branch from the recorded base.
2. Restate the observable goal, non-goals, approved paths, and the strongest
   plausible false-success mode.
3. Implement only the smallest change that satisfies the task.
4. Run focused feedback continuously and full validation once at the end.
5. Refactor after the tests pass and before publication. Refactoring is an author
   activity; a reviewer identifies problems but never edits the reviewed branch.
6. Stop rather than broaden scope when a required edit falls outside the approved
   paths or changes frozen behaviour.

For logic based on an external library, format, API, or schema, require a
versioned scratch-probe receipt from representative live data before accepting the
heuristic. For user-facing pipeline changes, require a trace from the normal
entrypoint through every changed handoff to the final observable; helper output
or an isolated unit test is not completion evidence. Scale this to the change: an
internal refactor or a documentation edit needs neither.

A task may produce one implementation PR or one governance PR, never both
implicitly. Repository changes require their own explicit authority.

## Challenge before publication

Check that every changed path is authorised, every claim is proved at the exact
branch head, tests exercise required behaviour, required artifacts are fresh and
coherent, and untested risks are stated. Use `unproven` instead of filling an
evidence gap with inference.

Run author checks from the committed head with no test-relevant untracked files.
Include `git status --porcelain=v1 --untracked-files=all`, `git diff --check`,
repository-declared compile, lint, type, and static checks, focused tests, the
complete mandated suite, and a final-output acceptance run. A clean aggregate
produced by skips, xfails, missing fixtures, or an author-only dirty worktree fails
this challenge.

## Publish and stop

If publication is authorised:

1. Commit intentionally.
2. Push only the authorised non-protected branch. Never force-push.
3. Open or update one PR.
4. Re-read the remote head and record its full SHA.
5. Build an `author-handback.v1` evidence packet whose changed paths exactly match
   the live PR and whose acceptance entries state the independent oracle, command,
   and observed result. Do not mark an unmet or unexecuted criterion `PASS`.
   Include every mandated validation command, not merely author-selected commands.
   Record completion, exit code, and test totals. Any failed, timed-out, partial,
   or unrun command prevents a review-ready handback. Inventory skips, xfails,
   deselections, deleted tests, and required artifacts; prove every acceptance
   input is tracked at the exact head.
6. Apply `publish-pr-handback` to validate local, remote, and packet equality,
   publish the exact-head receipt, and read it back from the hosting service.
7. Treat only `AUTHOR_HANDBACK_PUBLICATION=PASS` as a completed handback.
8. Create any project-required `durable-handoff`, then stop for independent review.

Do not self-approve, merge, enable auto-merge, bypass protection, begin a second
task, or turn a recorded next candidate into authority.

An author must not switch into a reviewer role, and a reviewer is restricted to
hosting-service review metadata: it never patches or pushes the reviewed PR. Merge
authority comes only from the project's role policy, checked as a separate
integration action through the role gate in `identity-safe-git`; a login the policy
marks no-merge can never merge, and a delegated merger needs a current explicit
maintainer instruction naming the exact repository, PR, and head.

## Continue only from new authority

After a maintainer reports a merge:

1. verify the merge and synchronise the relevant main branches;
2. reread the active-task pointer;
3. continue only when a separately authorised next task exists;
4. otherwise prepare the smallest governance proposal and stop before product
   implementation.

## Consume review state

When a PR is open, query formal reviews as well as issue comments. Resolve the
latest non-dismissed review by the assigned reviewer on the exact live head; that
verdict governs. A later changes-requested review supersedes an earlier approval on
the same head.

Never treat an author handback comment as proof that review is pending when a
current-head changes-requested verdict exists. Repeated execution with unchanged
remote state must be idempotent and must not create another task.
