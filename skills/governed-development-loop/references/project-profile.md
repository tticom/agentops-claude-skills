# Project profile contract

Keep project-specific facts outside the reusable skill. A project profile must
define:

## Authority

- canonical active-task pointer;
- documents that are informative but not executable authority;
- role allowed to implement, review, approve, and merge;
- one-task/one-PR concurrency rule.

## Identity and workspace

- expected operating-system user, home, Git host identity, and commit identity;
- canonical repository roots;
- allowed branch patterns and protected branches;
- prohibited fallback identities or workspaces.

## Evidence

- approved inputs and privacy constraints;
- required focused and full validation;
- artifact-coherence and runtime-provenance requirements;
- exact PR-body evidence and residual-risk fields.

## Review

- project review profile path;
- required disconfirmation checks;
- comment/thread disposition rules;
- whether the reviewer may publish an approval or only return review text.

## Stop and continuation

- prohibited actions;
- blocking conditions;
- post-merge continuation rule;
- how a candidate becomes separately authorised.

Profiles may be strict, but must not restate this skill's generic branch,
commit, PR, or handoff sequence. Reference the skill instead.
