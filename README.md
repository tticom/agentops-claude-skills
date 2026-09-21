# agentops-claude-skills

Reusable AgentOps skills for governed, multi-agent software work, usable by
both Claude Code and Codex. One skill per directory:

```
skills/<skill-name>/SKILL.md      required
skills/<skill-name>/scripts/      only where the skill needs executable helpers
skills/<skill-name>/references/   only where the skill needs supporting documents
```

Each skill is self-contained: it may reference only files inside its own
directory, so it works when copied under a user's skills directory
(`~/.claude/skills`, `~/.agents/skills`). Project-specific policy (identities,
authority, evidence rules) belongs in the consuming project's governance
repository, not here.

## Skills

The index below is machine-checked: it must list exactly the directories under
`skills/`.

<!-- skills:start -->
_No skills have been migrated yet._
<!-- skills:end -->

## Validation

```bash
python -m pip install pytest
python -m pytest
python scripts/validate_skills.py
```

`scripts/validate_skills.py` uses only the Python standard library and fails
when a skill:

- lacks a `SKILL.md`, or has invalid frontmatter (`name` must equal the
  directory name; `description` is required; plain scalars must not contain an
  unquoted `: `);
- links to, or names, a bundled `scripts/`, `references/` or `assets/` path
  that does not exist, or reaches outside its own directory;
- contains a file that is not valid UTF-8 (undecodable files are errors, never
  skipped; only image files under `assets/` may be binary), a symlink, or a
  Python script that does not parse;
- mentions the retired upstream lineage, retired harnesses, machine-specific
  absolute paths or the legacy bucketed layout. Provenance files
  (`NOTICE.md`, `PROVENANCE.md`, `LICENSE*`) are exempt only when they sit
  directly in the skill's root directory.

Do not write consumer-side file names with a `scripts/`, `references/` or
`assets/` prefix in a skill body unless the file is bundled in the skill.

## Provenance

See [PROVENANCE.md](PROVENANCE.md). Licensed under the [MIT License](LICENSE).
