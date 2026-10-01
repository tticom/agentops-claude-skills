# SLIM-PROPOSAL: slimming the skills

Status: the maintainer (tticom) has answered the open questions (see the
companion file, sections 6 and 7). The six consolidated skills are now implemented
under `lean/skills/` on this branch, beside the old twelve, which are untouched.
**The cutover has not been executed**; `main` and the skills the live framework
pins (`c51d446`) are unchanged. `slim-governance` is the long-running trunk of the
lean experiment, standing in for `main` until the maintainer decides; the draft PR
is the review surface, not something to merge now.

Companion document (same branch name, other repo):
[`score2gp-agentops` `SLIM-PROPOSAL.md`](https://github.com/tticom/score2gp-agentops/blob/slim-governance/SLIM-PROPOSAL.md).
That one holds the full inventory of rules, gates, roles, artefacts and
scripts, the proposed minimal framework, and the migration plan. Read it first;
this file covers what is specific to the skills repo (item 4 of the brief) and
how the skills map onto the slim framework.

Basis: `origin/main` of `agentops-claude-skills` at `c51d446` (PR #6), read on
2026-10-01. The live framework pins `c51d446` (agentops PR #744).

## 1. What is here

12 skills, 82 KB of SKILL.md text, about 7,300 lines of helper scripts and
their tests, plus about 1,800 lines of repo-level validator and tests, plus
migration paperwork (`MIGRATION_INVENTORY.md`, a Stage 1 decision record,
`PROVENANCE.md`, `COMPATIBILITY.md`). Three helpers are vendored as byte-identical
copies (`gh_publication.py` in `code-review` and `publish-pr-handback`;
`role_authority_gate.py` in `code-review` and `identity-safe-git`), kept in sync
by a byte-identity test. The repo itself is small (6 PRs); its history shows
the same pattern as the other repo: PR #2 needed two Codex CHANGES_REQUESTED
rounds before merge, and #4 and #6 are fixes to the review publisher and
thread gate.

## 2. Each skill: what it prevents, evidence, and class

Evidence IDs refer to `score2gp-agentops` (PR numbers there, reports under
`projects/score2gp/reports/`), see the companion file. "P" is real protection,
"C" is ceremony or machinery tied to the old state machine.

| Skill (SKILL.md / scripts+tests lines) | Prevents | Evidence it happened | Type | Class |
|---|---|---|---|---|
| `code-review` (13.5 KB / 2,674) | Review of the wrong head; reviews only in chat; unverified standards and spec fidelity | Raw `gh pr review` bypassing head binding was banned in `pr_standards` 6; skills #4 and #6 fix the publisher and thread gate; 152 CHANGES_REQUESTED reviews in the product repo show reviews catch things | P (pin head, two axes) with C (marker summary, readback, thread gate) | MERGE into `review`, SIMPLIFY the publisher |
| `devils-advocate-review` (7.6 KB / none) | Approvals on claims no one tested | score2gp#396 approval overturned; CRP-10/11/12 shipped silent fallbacks past a review (`reports/2026-08-13-review-skills-failure-assessment.md`, agentops #550, #551) | P | MERGE into `review` as an adversarial mode |
| `hard-review` (10.3 KB / 253) | Mock-only tests, skipped private tests, fixture-coupled production code | Same CRP-10/11/12 report; skipped private integration tests counted green. No concrete fixture-coupling incident found | P | MERGE into `review` as the same adversarial mode; keep `fixture_coupling_scan.py` and the falsification protocol |
| `changes-requested` (7.4 KB / 991) | Fixing the wrong finding, stale review, fixes that regress | 152 CHANGES_REQUESTED reviews and 50 DISMISSED in the product repo; PR #636 rework record | P | KEEP, rename `address-review`, drop the handback prerequisite |
| `verified-implementation` (7.4 KB / none) | Completion claimed without executed evidence; false green; invented inputs | `REJECTED_CLAIMS` 2-5; #396; CRP-12 | P | KEEP as `implement`; absorb the useful parts of `governed-development-loop` (refactor before handback, scale probes to the change) |
| `identity-safe-git` (5.2 KB / 817) | Agent mutating main, wrong branch, wrong account | Incidents 2026-07-20 (#333 admin merge), 2026-07-21 (#341), 2026-09-24 | P (branch safety) with C (identity profiles, role gate) | SIMPLIFY to `safe-git`: verify branch and remote, no push to main, no force, no admin, no merge; drop role policy file and `role_authority_gate.py` |
| `publish-pr-handback` (5.5 KB / 1,104) | Reviewer given stale or missing author claims | agentops #525, #537 (stale or missing handbacks) | C (CI and the PR body now carry this) | RETIRE |
| `governed-development-loop` (6.6 KB / none) | Work outside an authorised task; author and reviewer collapsed | Drift before the authority existed; but it requires an active-task pointer and the old identities | C | RETIRE (residue merged into `implement`) |
| `dispatch-task` (6.7 KB / 574) | Agent running the wrong or unauthorised next task | Dispatcher repair PRs (about 30 in agentops) | C | RETIRE (the slim flow has a task list, not a dispatcher) |
| `governance-author` (4.9 KB / none) | Self-promotion, stale state, repository-ownership drift | The 458 promotion and reconciliation PRs; 2026-09-24 stale-authority stall | C | RETIRE |
| `durable-handoff` (2.4 KB / none) | Work lost when a conversation ends or crosses agents | Run and handoff records (#636 rework record, 16 handoffs) | P (small, cheap) | KEEP as is; make it optional |
| `workspace-cleanup` (5.0 KB / 916) | Stale review worktrees piling up; deleting dirty work | agentops #616 added it; this workspace's own worktree list shows the problem | P (utility) | KEEP as is |

Counts: 12 skills become 6.

| After | From |
|---|---|
| `implement` | `verified-implementation` + residue of `governed-development-loop` |
| `review` (normal and `--adversarial`) | `code-review` + `devils-advocate-review` + `hard-review` |
| `address-review` | `changes-requested` |
| `safe-git` | `identity-safe-git` (trimmed) |
| `workspace-cleanup` | unchanged |
| `durable-handoff` | unchanged |
| retired | `publish-pr-handback`, `dispatch-task`, `governance-author`, `governed-development-loop` |

Of the 12: 4 keep as they are or nearly (`verified-implementation`,
`changes-requested`, `durable-handoff`, `workspace-cleanup`), 4 merge or trim
into 2 (`code-review`/`devils-advocate-review`/`hard-review`, and
`identity-safe-git`), 4 retire. Roughly 30% of the text and 25% of the
code is pure old-framework machinery (the four retirees plus role policy and
handback code).

## 3. What stays in each kept skill

- `review`: exact-head verification (`verify_review_head.py`, 47 lines); the
  two axes (Standards, Spec); the code-smell contract and `assertion_smells.py`;
  "claims are untrusted, start at cannot-verify, falsify first"; adversarial
  mode brings the evidence falsification protocol, skip detection, and
  `fixture_coupling_scan.py`; the evidence gate (`review_evidence_gate.py`)
  runs only on PRs labelled risky. Publication becomes a PR comment that
  begins with the full head SHA. The thread-resolution gate is kept only if
  the repo cannot enforce thread resolution through a ruleset (see open
  question 2 in the companion file).
- `implement`: evidence-gated completion, provenance classification, clean
  head pre-flight, no false green.
- `address-review`: `fetch_review_findings.py`, reproduce then fix then verify.
- `safe-git`: a short checklist, plus a pre-push hook sample if rulesets are
  unavailable; no accounts or roles.

## 4. Repo-level changes

| Item | Class |
|---|---|
| `scripts/validate_skills.py` and `.github/workflows/validate.yml` (Ubuntu + Windows) | KEEP, shrink the validator to: frontmatter valid, index matches directories, prerequisites exist |
| `tests/test_migration_inventory.py`, `docs/MIGRATION_INVENTORY.md`, Stage 1 decision record | ARCHIVE (move to `docs/history/`), drop the test |
| Byte-identity tests for vendored copies | DROP once duplicates are removed (one `gh_publication.py` in a shared `scripts/`, or none) |
| `PROVENANCE.md`, per-skill `NOTICE.md` | KEEP (licence obligation for derived material) |
| `docs/COMPATIBILITY.md` | KEEP, shorten |
| README "Prerequisites between skills" and skill-installation text | SIMPLIFY (no prerequisite web: 6 skills, one directory) |

## 5. Migration (side by side)

1. The live framework keeps pinning `c51d446`. Do not rewrite or force-push
   `main`.
2. Slim skills are built on this branch (additive first: new `review`,
   `implement`, `address-review`, `safe-git` directories alongside the old
   ones). Old skills stay until the cutover.
3. During the trial (companion file, section 4, step 3) the slim worktree
   installs the slim branch into its own skills location, never into
   `~/.agents/skills` used by the live agents.
4. At cutover, tag the slim state (for example `v2.0.0`), have the product
   cutover PR pin that tag, and move the retired skills to an `archive/` tag
   rather than deleting history.
5. Later, for going private: check each `NOTICE.md` (upstream MIT notice must
   stay with the derived material), and decide whether this repo should be
   folded into the product repo as a `.claude/skills/` directory, since six
   small skills may not need their own repository.

## 6. Questions specific to the skills

1. Fold the six skills into the new private repo (recommended) or keep a separate
   repo: STILL OPEN (companion file, section 7, item 3).
2. Adversarial review default: DECIDED by judgement: on for `risky`, off for
   `normal`.
3. `workspace-cleanup` and `durable-handoff`: kept; `durable-handoff` is optional
   and never per-task.
4. Codex as a runtime: the lean skills are plain markdown plus Python and run under
   both; no extra compatibility work is planned. STILL OPEN if you want to drop it.
5. Rewrite the upstream-derived parts independently: STILL OPEN; notices kept.

The broader decisions are in the companion file, section 6.

## 7. Implemented on this branch (`lean/skills/`)

| Skill | Built from | Scripts (tested) |
|---|---|---|
| `implement` | `verified-implementation` + residue of `governed-development-loop`; smell contract | none |
| `review` (normal and `--adversarial`) | `code-review` + `devils-advocate-review` + `hard-review` | `verify_review_head.py`, `assertion_smells.py`, `fixture_coupling_scan.py` (+ tests) |
| `address-review` | `changes-requested`, handback prerequisite removed | `fetch_review_findings.py` (+ tests) |
| `safe-git` | `identity-safe-git` trimmed: no identity profiles or role policy | new `safe_git_check.py` (+ tests) |
| `workspace-cleanup` | unchanged copy | `workspace_cleanup.py` (+ tests) |
| `durable-handoff` | trimmed: optional, no authority fields | none |

Choices made on the maintainer's decisions: review is advisory, published as one PR
comment that begins with `Review @ <full head SHA> | mode | verdict`, with no
formal-review publisher, marker summary, readback or thread gate (nothing blocks on
review; the maintainer merges). The role policy, identity gate and handback
publisher are gone. `review` keeps the exact-head pin, the two axes, the smell
contract, and the adversarial evidence protocol. Upstream-derived `review` and
`implement` keep their MIT `NOTICE.md`.

Run the lean tests per skill directory (basenames collide across skills, so do not
collect them in one pytest session): `cd lean/skills/<skill>/scripts && python -m pytest`.
The existing `scripts/validate_skills.py` validates the lean tree when pointed at a
root that has `skills/` and a README index (used during development).
