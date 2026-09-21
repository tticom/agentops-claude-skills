# Windows, Claude Code and Codex compatibility

This page separates three kinds of evidence, and states plainly which one supports
each claim. It does not claim runtime validation that was not performed.

- **Automated:** exercised by the test suite on Ubuntu and Windows in CI, and on a
  native Windows machine during development.
- **Runtime smoke test:** the skill was actually loaded and used by the runtime.
  **None was performed for this change.**
- **Documentation-only assessment:** based on the runtime's documented conventions
  and the skill format, not exercised here.

## Native Windows

**Automated.** Every helper is standard-library Python (3.11+) and runs without WSL,
a POSIX shell, or Linux paths. No shell script is shipped (a test fails if one
appears). Every command-line helper is started with `--help` as a subprocess by the
test suite. Behaviour that depends on the platform is covered directly:

- user names and paths are compared case-insensitively with normalised separators
  on Windows (`identity-safe-git`), with the Windows rules exercised on every
  operating system through an injectable host object;
- every subprocess that reads or writes text is forced to UTF-8, because Windows
  otherwise decodes `git` and `gh` output with the system code page (a regression
  test pins this for each helper that calls `gh`);
- escaped Windows paths inside source files are matched by the fixture-coupling
  scanner;
- `workspace-cleanup` is tested against real temporary Git repositories and
  worktrees, including removal, dry run, locked, dirty, detached and missing
  worktrees.

**Requirements.** `git` on `PATH`; the GitHub CLI (`gh`) authenticated as the acting
identity for the identity, review, handback and remediation helpers. Use `python`;
where that name is missing use `py -3` (Windows launcher) or `python3`.

**Limits.** The publication and dispatch helpers are tested against faked GitHub
calls. Nothing in the automated suite talks to GitHub, and no live PR, review or
comment was created.

## Claude Code and Codex

Each skill is a directory with a `SKILL.md` whose frontmatter is only `name` and
`description`, so it needs nothing model-specific. The validator enforces this
layout, that `name` equals the directory name, and that each skill is
self-contained.

| Aspect | Claude Code | Codex | Evidence |
|---|---|---|---|
| Skill directory | `~/.claude/skills/<name>/` | `~/.agents/skills/<name>/` | documentation-only |
| Invoke by name | `/<name>` | `$<name>` | documentation-only |
| Selection by description | yes | yes | documentation-only |
| Sub-agents | not assumed | not assumed | skills say delegation is optional and conditional |
| Loading and running a skill | not performed | not performed | none |

Differences that matter for use:

- **Sub-agents and tools differ between runtimes** and are never assumed. The
  review skills run their two axes sequentially yourself unless the runtime
  provides sub-agents *and* the task authorises delegation.
- **Skills refer to each other by name** (see the prerequisites table in the
  README) rather than by path or by a runtime-specific "call the skill" tool. Where a
  skill runs a sibling's helper it says so and requires that sibling. All skills must
  be installed together in one skills directory; a missing prerequisite makes the
  skill stop with `REQUIRED_SKILL_MISSING`.
- **Helper paths** are given as `<skill-dir>/scripts/...`. Resolve `<skill-dir>` to
  the directory that contains the loaded `SKILL.md`. How a runtime exposes that
  location was not verified; if it does not, locate the installed skill directory
  directly.
- **The role gate never assumes an identity.** Which logins may review or merge is a
  project policy file, read at run time, so the same skill works under whichever
  GitHub identities each runtime is launched with. Two agents can run side by side
  under different logins when each process supplies its own `GH_TOKEN`.

## Not verified, and what would verify it

1. Load each skill in Claude Code and in Codex and confirm both discover it from its
   description and run a helper from the loaded location.
2. Confirm the `$<name>` and `/<name>` invocation forms on the installed versions.
3. Run one review-publication cycle against a throw-away repository and pull request
   created for the purpose.

These are separate, deliberate activities: they create live artifacts, which this
change does not do.
