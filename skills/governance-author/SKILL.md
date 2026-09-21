---
name: governance-author
description: Author or revise governed task promotions, active-task records, role-specific prompts, and control-plane PRs. Use when a project separates governance from product work, assigns identities or repositories by role, promotes a candidate into executable authority, or needs to prevent stale state, self-promotion, repository-ownership drift, and non-discriminating governance tests.
---

# Governance Author

Turn a maintainer decision into the smallest executable authority packet. Preserve
momentum without inventing history or letting one role authorise its own successor.

**Prerequisite skills:** `identity-safe-git`, `durable-handoff`

All AgentOps skills are installed together in one skills directory. If a
prerequisite is unavailable, stop and report `REQUIRED_SKILL_MISSING <name>`.

## Load authority first

1. Read the project profile, active-task pointer, identity policy,
   repository-ownership rules, and dispatcher contract.
2. Apply `identity-safe-git` before writes.
3. Query live PR and remote-main state. Treat chat summaries and earlier reviews as
   navigation only.
4. Record a present maintainer waiver or authorisation as a present decision. Do
   not rewrite missing historical evidence unless explicitly asked.

Stop if identity, workspace, live head, repository ownership, or current authority
cannot be established.

## Choose the durable owner

Classify every proposed output before selecting a repository:

| Output | Normal owner |
|---|---|
| active-task pointer, role prompt, orchestration policy, promotion record | governance repository |
| product architecture, parser or diagnostics design, fixture/test plan, implementation notes | product repository |
| product source, product tests, fixtures, schemas, product docs | product repository |
| review verdict and exact-head handback | hosting-service review/comment channels plus the project-required durable record |

Project rules override this table when stricter. Never place durable product design
in a governance PR merely because the task was promoted there.

## Build one bounded authority packet

Require explicit fields for:

- task and status;
- assigned identity and authorised role;
- durable-output repository;
- branch and base revision;
- exact allowed files;
- originating prompt;
- goal, acceptance, validation, non-goals, and stop condition.

Use narrow file paths. A directory allowance must state the permitted artifact type
and count.

For research or architecture, require a decision outcome, evidence needed to
continue, evidence needed to stop or pivot, and at most one smallest next
candidate. The candidate is not executable authority.

## Prevent role and promotion collapse

- An Architect may recommend a candidate but must not activate it.
- A Developer may update only the current task branch and PR.
- A Reviewer may publish only formal reviews, inline comments, and PR comments. The
  reviewer must not create or modify repository files, commit, push, update the PR
  branch, implement the fix, or store review evidence on the branch.
- A governance author may promote a reviewed candidate but must not perform the
  authorised product work.
- A recorded candidate requires a separate governance promotion unless the project
  explicitly authorises one-task/one-PR continuation in the same durable-output
  repository.

When repositories differ, always require a separate promotion.

## Prove the control behaviour

Treat a green governance suite as a claim. For changed dispatch or audit logic:

1. Cover each state with distinct exact assertions.
2. Make external-command fakes capture and assert repository, branch, state filter,
   and requested fields.
3. Distinguish confirmed absence from API, authentication, permission, and JSON
   failures.
4. Add a false-success mutation or equivalent negative control proving the intended
   assertion fails when the protected behaviour is disabled.
5. Verify changed paths, exact head, clean diff, and the project audit.

Do not accept an expected nonzero exit when it arose from the wrong exception or a
malformed mock shape.

## Publish once and stop

Apply `durable-handoff` for the project-required record. Publish one branch and PR,
then an exact-head handback containing:

- full head SHA and base revision;
- changed paths;
- validation commands and exact results;
- unresolved risks;
- machine-actionable next state.

Do not merge, force-push, create a successor task, or continue into the authorised
role.

When the governance author later acts as a reviewer, use the appropriate
`code-review`, `hard-review`, or `devils-advocate-review` skill in a separate clean
detached worktree. A login the project's role policy marks no-merge has no merge
authority under any task or prompt.
