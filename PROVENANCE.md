# Provenance

This repository has its own history and is not a fork of any third-party skills
collection.

## Predecessor

The skills were first developed in `tticom/agy-skills`, which is a GitHub fork
of a third-party MIT-licensed skills collection (copyright 2026 Matt Pocock).
That repository is kept as a historical source only. It is not this
distribution and must not be installed alongside it.

## Migration policy

Each candidate skill or support file is classified before it is migrated:

| Class | Meaning | Action |
|---|---|---|
| A | Locally original and reusable | Migrate, removing legacy layout and harness assumptions |
| B | Derived from third-party material | Rewrite independently from AgentOps requirements, or migrate with a `NOTICE.md` that retains the upstream copyright and license text |
| C | Provided by the current third-party collection | Do not migrate |
| D | Specific to a retired harness | Retire unless independently useful |
| E | Specific to Score2GP | Keep in the Score2GP governance repository |
| F | Obsolete | Do not migrate |

Attribution is never removed from material that is still materially derived
from third-party work. A skill that keeps such material carries its own
`NOTICE.md` (exempt from the validator's lineage check).

## Migration record

The first bulk migration took its skills from `tticom/agy-skills` `main` at
`8366e98413974f18f8ddf4e7e20b35d2e39f45a4`. Every source command, its disposition,
and its class are listed in [docs/MIGRATION_INVENTORY.md](docs/MIGRATION_INVENTORY.md).

Derived material and how its attribution is kept:

| Skill | Derived from | Record |
|---|---|---|
| `code-review` | the two-axis Standards and Spec review structure of upstream `code-review` | `skills/code-review/NOTICE.md` |
| `verified-implementation` | the opening passage of upstream `implement`, which the skill extends | `skills/verified-implementation/NOTICE.md` |

Each `NOTICE.md` names the upstream project, states what is derived, and reproduces
the upstream MIT license and copyright notice verbatim. It sits in the skill's root
directory, so it is installed with the skill and is exempt from the validator's
lineage check.

The other migrated skills were first authored by the local identities according to
the git history at the pinned revision, so they carry no upstream notice. That is a
statement about history, not a legal determination. Skills that upstream provides
unchanged were recorded in the inventory as `upstream-provided` and were not
copied. No upstream plugin, marketplace, or setup skill is part of this repository.

## License

This repository's original work is released under the MIT License (see
[LICENSE](LICENSE)). It does not replace the notices of any third-party material:
a skill that includes such material carries a `NOTICE.md` in its root with the
upstream copyright and license text, and that notice continues to apply to the
material it covers.
