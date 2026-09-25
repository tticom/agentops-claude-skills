# agentops-claude-skills

Reusable AgentOps skills for governed, multi-agent software work, usable by both
Claude Code and Codex, on native Windows as well as macOS and Linux. One skill per
directory:

```
skills/<skill-name>/SKILL.md      required
skills/<skill-name>/scripts/      cross-platform Python helpers and their tests
skills/<skill-name>/references/   supporting documents the skill reads
skills/<skill-name>/NOTICE.md     only where a skill contains derived third-party material
```

Each skill is self-contained: it references only files inside its own directory,
so it works when copied under a user's skills directory (`~/.claude/skills`,
`~/.agents/skills`). Project-specific policy (identities, authority, repositories,
routing) belongs in the consuming project's own configuration, not here. This
repository ships no installer yet and installs nothing into any environment.

## Skills

The index below is machine-checked: it must list exactly the directories under
`skills/`.

<!-- skills:start -->
- `changes-requested` - remediate a CHANGES_REQUESTED review: reproduce, fix, verify, hand back
- `code-review` - two-axis (Standards and Spec) exact-head review with guarded publication
- `devils-advocate-review` - adversarial review that presumes every claim and prior approval is wrong
- `dispatch-task` - find and dispatch the next authorised action from a project's own configuration
- `durable-handoff` - repository-owned handoff tied to exact revisions and evidence
- `governance-author` - author task promotions and control-plane changes without role collapse
- `governed-development-loop` - run one authorised, review-gated change to an independently reviewable head
- `hard-review` - review adding provenance, oracle-independence and fixture-coupling gates
- `identity-safe-git` - prove identity and enforce branch-safe, role-safe Git and PR operations
- `publish-pr-handback` - validate and atomically publish an exact-head author handback
- `verified-implementation` - implement with evidence-gated completion and a clean-head pre-flight
- `workspace-cleanup` - remove provably stale review worktrees and record a receipt
<!-- skills:end -->

## Invocation

Skills are model-selected from their descriptions, and can be requested by name.
The name-based forms below follow each runtime's documented convention; see
[docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) for exactly what has and has not
been verified.

| Runtime | By name | Example |
|---|---|---|
| Claude Code | `/<skill-name>` | `/code-review` then the PR number |
| Codex | `$<skill-name>` | `$dispatch-task` |

There is deliberately no `go` command. Use `dispatch-task`.

## Prerequisites between skills

Some skills use another skill's checks or helpers. Every skill states this on its
own `**Prerequisite skills:**` line (or says it has none), and a test verifies each
named prerequisite exists here, that none is circular, and that a skill using a
sibling's scripts declares it. **Install all skills together into one skills
directory.** A skill whose prerequisite is missing stops and reports
`REQUIRED_SKILL_MISSING <name>` rather than approximating the check.

| Skill | Requires |
|---|---|
| `identity-safe-git`, `publish-pr-handback`, `durable-handoff`, `workspace-cleanup` | nothing |
| `code-review` | `identity-safe-git` |
| `hard-review` | `code-review`, `identity-safe-git` |
| `devils-advocate-review` | `code-review`, `hard-review`, `identity-safe-git` |
| `changes-requested` | `publish-pr-handback` |
| `governed-development-loop` | `identity-safe-git`, `publish-pr-handback`, `durable-handoff` |
| `governance-author` | `identity-safe-git`, `durable-handoff` |
| `dispatch-task` | `identity-safe-git`, `durable-handoff` |
| `verified-implementation` | `code-review` (its code-smell contract only) |

### Vendored helpers

To keep skills self-contained, some helpers are carried as byte-identical copies. A
test fails if a copy drifts; edit the canonical file and re-copy it.

| Helper | Canonical location | Copied into |
|---|---|---|
| `role_authority_gate.py` | `identity-safe-git` | `code-review` |
| `gh_publication.py` (pagination and persisted read-back) | `code-review` | `publish-pr-handback` |

## Project configuration lives in the project

Nothing about a particular project is built into these skills. Projects supply:

- an **identity profile** and a **role policy** (see `identity-safe-git`);
- a **dispatch configuration** naming their task authority and runtime (see
  `dispatch-task`);
- optional hand-off state names, fixture-coupling markers, and review-worktree
  patterns, passed as flags, files, or environment variables.

## Validation

```bash
python -m pip install pytest
python -m pytest
python scripts/validate_skills.py
```

`python -m pytest` runs the repository-level checks in `tests/` and every skill's
bundled tests in `skills/*/scripts/`. Their coverage includes: identity and role
gates; stale-head rejection; the review and handback publication contracts against
a faked hosting service; dispatch with valid, missing, invalid and conflicting
configuration; and each skill's rejected cases alongside valid controls. Nothing
in the automated suite creates a live PR, review, or comment.

`scripts/validate_skills.py` uses only the Python standard library and fails
when a skill:

- lacks a `SKILL.md`, or has invalid frontmatter (`name` must equal the
  directory name; `description` is required; plain scalars must not contain an
  unquoted `: `);
- links to, or names, a bundled `scripts/`, `references/` or `assets/` path
  that does not exist, or reaches outside its own directory (`./` and `../`
  prefixes are normalised first), or names a repository-prefixed path such as
  `skills/<name>/scripts/x`, which only resolves in this checkout and breaks
  when the skill is installed alone;
- contains a file that is not valid UTF-8 (undecodable files are errors, never
  skipped; only image, PDF and font files under `assets/` may be binary), a
  symlink, or a Python script that does not parse;
- mentions the retired upstream lineage, retired harnesses, machine-specific
  absolute paths or the legacy bucketed layout. Provenance files
  (`NOTICE.md`, `PROVENANCE.md`, `LICENSE*`) are exempt only when they sit
  directly in the skill's root directory.

The one exception to "every file is checked" is compiled bytecode
(`.pyc`/`.pyo`) directly inside a `__pycache__` directory, which is a build
artifact and never part of a skill.

Do not write consumer-side file names with a `scripts/`, `references/` or
`assets/` prefix in a skill body unless the file is bundled in the skill.

## Provenance

See [PROVENANCE.md](PROVENANCE.md) and the
[migration inventory](docs/MIGRATION_INVENTORY.md). All rights reserved; see
[LICENSE](LICENSE). Third-party notices in skill `NOTICE.md` files still apply.
