---
name: dispatch-task
description: "Determine and dispatch the next authorised action in a governed project. Locates the project's configured task authority, inspects live task, PR, and review state, identifies the responsible role, and either runs the project's configured dispatcher or produces a concrete handoff. Stops when configuration or authority is missing, conflicting, or records that no task is approved. Use only when the user explicitly asks to continue, advance, dispatch, or run the next governed task."
---

# Dispatch task

Find out what the project has authorised next, and route it, without inventing
authority. This skill is a generic front door: everything specific to a project
(where its task authority lives, which repositories and roles exist, which
identities may act, how its runtime dispatches) is read from the **project's own
configuration**. Nothing project-specific is built into this skill.

**Prerequisite skills:** `identity-safe-git`, `durable-handoff`

All AgentOps skills are installed together in one skills directory. If a
prerequisite is unavailable, stop and report `REQUIRED_SKILL_MISSING <name>`.

This skill is not a task-state system and does not compete with one. The project's
runtime owns task state; this skill only reads it and follows what it returns. Do
not create queues, task files, status logs, or any state of your own.

## 1. Resolve the project configuration

Run the bundled resolver from (or pointed at) the consuming project. It is
read-only and never runs anything it reports:

```text
python <skill-dir>/scripts/dispatch_config.py --project <project-root>
```

It looks for `agentops-dispatch.json` (or `.agentops/dispatch.json`) at the project
root, or a file named by `--config` or `AGENTOPS_DISPATCH_CONFIG`. Read
[config-schema.md](references/config-schema.md) for the format. Act on `status`:

| Status | Meaning | What to do |
|---|---|---|
| `READY` | valid configuration with a dispatch command | continue to step 2, then run it in step 4 |
| `HANDOFF_ONLY` | valid, but the project has no runtime command | continue to step 2, then hand off in step 4 |
| `STOP_NO_CONFIG` | no configuration found | stop and report; ask the project for one |
| `STOP_CONFLICT` | more than one differing configuration | stop and report which; never pick one |
| `STOP_INVALID_CONFIG` | unreadable or malformed | stop and report the exact error |
| `STOP_AUTHORITY_MISSING` | a declared authority document is absent | stop and report the path |
| `STOP_NO_ACTIVE_TASK` | the task authority says no task is approved | stop and report; do not invent one |

Any `STOP_*` status is terminal. Report the status and its message exactly and do
nothing further. A recorded backlog item, plan, report, or suggested candidate is
never permission to start work. Never reuse an earlier prompt or earlier result:
resolve and read state fresh on every invocation.

## 2. Verify identity and role

If the configuration names an `identity` profile or role policy, apply
`identity-safe-git` before any write: run its identity gate against the profile and
keep its role gate for later review or merge operations. An identity mismatch is a
no-write stop; never switch accounts or borrow another identity's checkout.

The responsible role comes from the project's authority and dispatcher, never from
the wording of the request. If the acting identity is not authorised for the role
the project assigns, stop and report the mismatch.

## 3. Inspect live state

Read, do not assume:

- the task authority documents listed in the configuration, at their current
  revision;
- for each configured repository, the open pull requests: number, author, head
  branch, full head SHA, and state (use the GitHub CLI or the host's API);
- for each open PR, the formal reviews and the latest **non-dismissed** review on
  the **exact live head**, ordered by server timestamp then review ID; a later
  changes-requested review supersedes an earlier approval on the same head;
- author handbacks, kept separate from formal verdicts: a handback comment is never
  proof that review is pending when a current-head changes-requested verdict exists.

A new author head makes any earlier-head verdict historical. If the authority, the
PRs, and the reviews disagree about what is current (for example an open PR for a
task the authority no longer names), report the conflict and stop.

## 4. Dispatch

**`READY`: dispatch through the configured runtime.** Run the resolver's
`command.argv` exactly as given, in `command.cwd`, without a shell and without
adding or removing arguments. Its output is authoritative: treat its reported state
and next action as the answer, and do not reconstruct state in prose or from memory.
Only the states the runtime marks as action-authorising permit work, and then only
the single bounded action it returns. Any other state is terminal: report it and
stop. Repeating the command with unchanged output is idempotent: do not create
another task, review, or handback.

**`HANDOFF_ONLY`: provide a concrete handoff, and say execution did not occur.**
Using `durable-handoff` and [handoff.md](references/handoff.md), state the live
facts gathered in step 3, the responsible role, and the exact next action with the
commands or steps a person or another runtime should run. Then say plainly:
**"No action was executed; this is a handoff only."** Do not perform the action
yourself unless the user separately and explicitly asks you to, within the role you
are authorised for.

## 5. Boundaries

- Permission to dispatch never authorises a merge, a push to a protected branch, a
  force push, deleting a branch, a credential change, or bypassing a check.
- Never merge, self-approve, or promote a candidate into an active task.
- Do one bounded action, then stop. Do not chain into the next task.
- Delegation to sub-agents is optional: use it only if your runtime provides it and
  the task authorises it. Do not assume a particular sub-agent tool exists.

## Invocation

- **Claude Code:** invoke as `/dispatch-task`, or let Claude select it from its
  description.
- **Codex:** mention it as `$dispatch-task`, or let Codex select it from its
  description.

This skill has no `go` alias. The helper needs only Python 3.11+ and runs natively
on Windows, macOS, and Linux; use `python`, or `py -3` where that name is missing.
