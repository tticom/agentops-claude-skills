---
name: durable-handoff
description: Write a short handoff tied to exact revisions and evidence, for work that must survive conversation loss or cross from one agent session to another. Optional. Use when a task is paused or transferred; not for every task and not as per-task paperwork.
---

# Durable handoff

Optional and rare. A finished task needs no handoff: its PR and git history are the
record. Write one only when work is paused mid-task or transferred, and only to
help make the next decision. Do not commit it to the repository unless the
maintainer asks; a PR comment or a file in a scratch area is usually right.
Nothing here is archived for posterity.

No prerequisite skills.

## Verify live state first

Read live state rather than copying a summary: repository, branch, base SHA, local
HEAD and remote HEAD; worktree status and changed paths; PR state, checks and
unresolved threads; the exact validation commands and their results. If local and
remote heads differ, label the work unpublished.

## Write a compact record

Use [template.md](references/template.md). Cover purpose and outcome, exact
revisions, verified versus author-reported evidence, changed and excluded paths,
unresolved risks, and the single next action. Reference specs, PRs and commits by
path or URL; do not paste them. Redact credentials, private paths and private
input details.

## Check it

Reread it as a fresh agent: every next action executable or explicitly blocked,
every SHA full and matching live remote state.
