# Dispatch configuration

A consuming project supplies `agentops-dispatch.json` (or `.agentops/dispatch.json`)
at its root. It is the only place project-specific routing lives. All relative
paths resolve against the project root and may not be absolute or escape it.

```json
{
  "schema": "agentops-dispatch.v1",
  "project": "example",
  "authority": {
    "active_task": "governance/ACTIVE_TASK.md",
    "control_documents": ["governance/AGENT_CONTROL.md"],
    "no_task_markers": ["NO_ACTIVE_TASK_APPROVED"]
  },
  "repositories": ["example-org/product", "example-org/governance"],
  "identity": {
    "profile": "governance/identity-profile.json",
    "role_policy": "governance/role-policy.json"
  },
  "dispatch": {
    "command": ["python", "tools/dispatch.py", "--json"],
    "cwd": "governance"
  }
}
```

| Field | Required | Meaning |
|---|---|---|
| `schema` | yes | must be `agentops-dispatch.v1` |
| `project` | yes | a label for reports |
| `authority.active_task` | yes | exactly one path to the canonical task authority. A list is rejected as ambiguous |
| `authority.control_documents` | no | further authority documents that must exist |
| `authority.no_task_markers` | no | strings that, when present in the task authority, mean no task is approved; the dispatcher then stops |
| `repositories` | no | `owner/name` repositories whose PRs and reviews are inspected |
| `identity.profile` | no | identity profile for `identity-safe-git`'s identity gate |
| `identity.role_policy` | no | role policy for `identity-safe-git`'s role gate |
| `dispatch.command` | no | argv list for the project's runtime dispatcher. Absent means handoff-only |
| `dispatch.cwd` | no | working directory for the command (default: the project root) |

Unknown keys are rejected so a misspelt field cannot silently disable a check.

## Behaviour the resolver guarantees

- No configuration, an unreadable or malformed one, a missing authority document,
  or a "no task approved" marker each produce a distinct `STOP_*` status and a
  non-zero exit.
- Two different configuration files, or `--config` and `AGENTOPS_DISPATCH_CONFIG`
  naming different files, are a `STOP_CONFLICT`: the resolver never chooses one.
- `dispatch.command` is reported, never run, by the resolver. It is an argv list, so
  no shell is involved and nothing is interpolated.
- Authority documents are read strictly. One that is not valid UTF-8, or cannot be
  read, is `STOP_INVALID_AUTHORITY`; the resolver never substitutes replacement
  characters, because a corrupted file could otherwise stop matching a
  `no_task_markers` entry and dispatch anyway. A configuration file that is not
  valid UTF-8 is `STOP_INVALID_CONFIG`.
- The resolver reads files and writes nothing.

## What belongs in the project, not here

Identities and role names, repository names, the location of the task authority,
the runtime's command line, and the states the runtime treats as action-authorising
are all project decisions. Keep them in the project's configuration and its own
governance documents, versioned with the project.
