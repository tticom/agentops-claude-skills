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

## License

No license file has been added yet. Until the owner selects one, do not
redistribute this repository outside the owner's organisation.
