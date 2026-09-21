# Identity profile and role policy examples

Both files are project-owned JSON. Store policy only. Never store tokens,
credential paths, passwords, or private keys. The logins below are placeholders.

## Identity profile

Passed to `scripts/verify_identity.py --profile`. Use paths written for the
operating system the agent runs on; forward slashes are accepted on Windows.

```json
{
  "os_user": "automation",
  "home": "C:/agents/automation",
  "host_login": "automation-bot",
  "git_name": "automation-bot",
  "git_email": "automation@example.invalid",
  "repo_prefix": "C:/work/example",
  "protected_branches": ["main"],
  "allowed_working_branches": ["automation/*"],
  "permissions": {
    "push_working_branch": true,
    "submit_review": false,
    "approve": false,
    "merge": false
  }
}
```

Only the six identity fields (`os_user` through `repo_prefix`) are checked by the
gate. `protected_branches`, `allowed_working_branches` and `permissions` are
accepted so the profile can document policy in one place; unknown keys are
rejected so a misspelt field cannot silently disable a check.

## Role policy

Passed to `scripts/role_authority_gate.py --policy` (or `AGENTOPS_ROLE_POLICY`).
Logins are compared case-insensitively.

```json
{
  "reviewers": ["governance-bot", "automation-bot", "review-bot", "maintainer"],
  "never_merge": ["governance-bot", "automation-bot"],
  "maintainers": ["maintainer"],
  "delegated_mergers": ["review-bot"]
}
```

- `reviewers`: may publish review metadata on a PR they did not author.
- `never_merge`: may never merge, under any authorization.
- `maintainers`: may merge.
- `delegated_mergers`: may merge only with a current, explicit, exact-PR,
  exact-head authorization from a maintainer.

A login may not be in `never_merge` and also be a merger, or be both a
maintainer and a delegated merger; such a policy is rejected. A key that is
absent grants nothing.
