# Handoff-only dispatch

Use this shape when the project has no runtime dispatcher (`HANDOFF_ONLY`). It is
a handoff for a person or another runtime, not an instruction you carry out.

```markdown
# Dispatch handoff: <project>

**Execution status: NOT EXECUTED. This is a handoff only.**

## Authority
- Task authority: <path and revision>
- Task: <identifier and title, or "none approved">
- Responsible role: <role the project assigns>
- Required identity: <login the role requires>

## Live state (read at <UTC time>)
- <repository> PR #<n>: author <login>, head <full SHA>, state <open|merged|closed>
- Latest non-dismissed review on the live head: <reviewer, verdict, review ID, time>
- Author handback on the live head: <present | absent>
- Conflicts between the above: <none | describe>

## Next authorised action
- Action: <exactly one bounded action>
- Commands or steps: <what to run, from where>
- Stop condition: <what ends this action>

## Not authorised
- Merging, protected-branch pushes, force pushes, branch deletion, bypassing checks,
  and starting another task.
```

Every SHA must be the full 40-character value read from live state. If any fact
could not be read, say so rather than filling it in.
