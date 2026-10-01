# MERGE-READINESS (skills repository): what `main` must look like for `slim-governance` to merge

Status: **investigation record and plan for later. Nothing here is to be actioned now.**
Short companion to the main document in `score2gp-agentops`
([`MERGE-READINESS.md` on `slim-governance`](https://github.com/tticom/score2gp-agentops/blob/slim-governance/MERGE-READINESS.md)),
which holds the full plan, the rules this plan follows and the risks. Written 2026-10-01
against `origin/main` at `c51d446` (PR #6) and `slim-governance` at `364f8e7`.

The decided approach is the same as there: same repository, same history; cut a branch
from `main`, chop it, merge `slim-governance` in, prove it, then merge to `main`. The
old framework keeps running on `main` meanwhile; no drain is assumed. No decision is asked
of the maintainer here.

## 1. Verified facts

Rehearsed in a throwaway clone outside every repository (nothing pushed, `main` untouched).

| Fact | Result |
|---|---|
| Suite and validator on `origin/main` | 613 passed, 1 skipped, 201 subtests; `validate_skills.py` OK for 12 skills |
| `slim-governance` merged with current `main` | clean, no conflicts (slim only adds `SLIM-PROPOSAL.md` and `lean/`; it touches no file `main` has) |
| Chopped tree, Windows, Python 3.14 | 196 passed, 1 skipped; `validate_skills.py` OK for 6 skills |
| Chopped tree, Linux, Python 3.11 (the CI version, container) | 197 passed, 24 subtests; `validate_skills.py` OK for 6 skills |
| Open pull requests | only #7 (this slim draft). No other skills PR to finish or re-home. |
| Pin the live framework uses | `c51d446` = current `main` head (`SKILLS_LOCK.md` in agentops) |

Running the tests on this machine needs `-s` and standard input redirected from a real
file; otherwise subprocess tests fail with `WinError 6` for reasons unrelated to the code.

## 2. Classification of everything on `origin/main` (64 files)

| Path | Files | Disposition | Superseded by / note |
|---|---:|---|---|
| `LICENSE`, `.gitignore`, `pytest.ini`, `.github/workflows/validate.yml` | 4 | keep as-is | `pytest.ini` `testpaths = tests skills` still collects the promoted skills' bundled tests (verified); the workflow runs `pytest` and `validate_skills.py` on Ubuntu and Windows unchanged |
| `scripts/validate_skills.py`, `tests/test_validate_skills.py` | 2 | keep as-is | verified green against the six lean skills |
| `README.md` | 1 | needs rewrite | the `skills:start`/`skills:end` index must list exactly the skill directories (the validator and a test enforce it) |
| `PROVENANCE.md` | 1 | keep, update its migration record | MIT lineage and `NOTICE.md` rules must stay |
| `docs/COMPATIBILITY.md` | 1 | needs rewrite | names the old skills |
| `docs/decisions/2026-09-21-stage1-migration-completion.md` | 1 | keep (history) | |
| `docs/MIGRATION_INVENTORY.md`, `tests/test_migration_inventory.py` | 2 | delete | inventory of the 12; its test requires the nine named skills to exist |
| `tests/test_skill_distribution.py` | 1 | delete | vendored-copy and prerequisite contracts of the 12 |
| `tests/test_reviewer_skill_contracts.py` | 1 | delete | contracts of the old review skills |
| `skills/.gitkeep` | 1 | delete | |
| `skills/code-review/` (16), `hard-review/` (4), `devils-advocate-review/` (1) | 21 | delete | `review` (with an adversarial mode) |
| `skills/verified-implementation/` (2) | 2 | delete | `implement` |
| `skills/changes-requested/` (3) | 3 | delete | `address-review` |
| `skills/identity-safe-git/` (6) | 6 | delete | `safe-git` |
| `skills/workspace-cleanup/` (3), `skills/durable-handoff/` (2) | 5 | delete, replaced by same-named lean skills | name collision, see section 4 |
| `skills/dispatch-task/` (5), `governance-author/` (1), `governed-development-loop/` (2), `publish-pr-handback/` (4) | 12 | delete, retired | no lean equivalent: the dispatcher, promotion PRs, handbacks and the development-loop state machine are gone |

Promotion: `git mv lean/skills skills` after removing the old `skills/` (a plain
`git mv` into an existing `skills/` nests it as `skills/skills`; verified). Final tree:
six skills (`address-review`, `durable-handoff`, `implement`, `review`, `safe-git`,
`workspace-cleanup`), `lean/README.md` can go or be folded into `README.md`.

## 3. Cross-dependencies

| Dependency | Finding | Resolution |
|---|---|---|
| Live control plane (`score2gp_control_plane.py` in agentops) | Reads the pin from `SKILLS_LOCK.md`, requires it to be an ancestor of skills `origin/main`, materialises it by SHA | Holds after any chop that keeps history (merge commit, never a history-replacing squash). Skills can be chopped before the agentops chop: the old framework still resolves its six required skills at the pinned commit. |
| Launchers | `claude_reviews.sh`, `codex_reviews2.sh`, `gov_claude_review.sh` fetch this repo and `git worktree add --detach` the pin; `codex_author.sh` and `gov_open_pr.sh` run `~/.claude/skills/publish-pr-handback/scripts/publish_handback.py` | Pin by SHA: unaffected by the chop. The installed `publish-pr-handback` copy is what breaks if it is removed from `~/.claude/skills` after the agentops cut. Launchers were not touched. |
| Installed skills | `~/.claude/skills` holds 12 real directories (copies, not links), older than the pin; `~/.agents/skills` does not exist on this machine | Independent of repository branches. After the cut, copy the six lean skills in; move the retired ones aside, not delete. `dispatch-task` fails closed without a dispatch config. |
| Agentops | `safe-git` names `lean/hooks/pre-push` and the installer in the agentops repo; the `review` skill expects the Score2GP overlay to be supplied by the consuming project | Those agentops paths survive the chop (tooling stays under `lean/`). The overlay (`REVIEW_RULES.md`) is gap G1 in the agentops document. |
| Licence | `code-review` and `verified-implementation` derive from MIT material; the lean `review` and `implement` skills carry `NOTICE.md` | Keep `PROVENANCE.md` and every `NOTICE.md`; `validate_skills.py` exempts only provenance files at a skill's root |
| CI | `validate.yml` has no required-check dependency (ruleset `Main_Protect`: PR with 1 approval, thread resolution, no required status checks; Admin bypass) | none |

## 4. Conflicts a merge of `slim-governance` into a chopped branch would hit

Verified: the clean merge above, then the chop (`git rm -r skills`, `git mv lean/skills skills`).

| Case | Result | Resolution |
|---|---|---|
| Slim vs a chopped branch that only deleted/rewrote old files | none: slim touches no file `main` has | none |
| A slim edit to a `lean/skills/<x>/` file after promotion, where `skills/<x>/` already existed on `main` (`workspace-cleanup`, `durable-handoff`) | modify/delete: git cannot pair the rename onto an existing path | do not edit lean skills on slim once promotion starts, or promote after the last slim merge, or apply by hand |
| A slim edit after promotion to a lean skill with a new name (`implement`, `review`, `address-review`, `safe-git`) | follows the move (rename onto a new path) | none |
| Changes landing on `main` while the chop branch lives (old skills edited, a new skill added) | edits to deleted old skills: modify/delete, delete wins; a **new** file under a deleted path returns silently | delete-wins sync: `git merge origin/main`, then `git rm -rqf --ignore-unmatch skills/<old names> tests/test_skill_distribution.py tests/test_migration_inventory.py tests/test_reviewer_skill_contracts.py docs/MIGRATION_INVENTORY.md`, keep the chop side of `README.md`; resurrection guard: `skills/` must list exactly the six lean names, and `validate_skills.py` fails otherwise (it also checks the README index) |

## 5. Ordered chop plan, with a gate after each step

| Step | Change | Gate | Rehearsal |
|---|---|---|---|
| S0 | Tag `pre-lean-merge` on `main` (a write; not run here) | tag resolves to `c51d446` or the then-head | not run |
| S1 | Merge `slim-governance` into the branch cut from `main` | clean merge; 613+ passed | clean |
| S2 | `git rm -r skills`, remove stray untracked files, `git mv lean/skills skills`, delete the three tests and `docs/MIGRATION_INVENTORY.md` | `validate_skills.py` fails only on the README index (14 index problems, all README) | as predicted |
| S3 | Rewrite the README index; rewrite `docs/COMPATIBILITY.md`; update `PROVENANCE.md` | `validate_skills.py` OK for 6 skills; full suite green on Windows and Linux 3.11 | 196 passed (Windows), 197 passed (Linux), validate OK |
| S4 | Final delete-wins sync with `main`, then the gates again | resurrection guard; suite; validator | recipe verified on the agentops side; same mechanics here |

"It works" for this repository: the suite and validator pass on both operating systems,
every lean skill's bundled tests ran in the one `pytest` run, the six skills are installed
into a scratch skills directory and each `SKILL.md` loads, and the agentops-side one-task
run in a scratch repository (see the main document, acceptance item 4) uses them. The last
two are **not run here**.

Rollback: before the PR merges, close it and delete the branch. After it merges,
`git revert -m 1 <merge>` on a branch and PR it (the ruleset forbids force-push and
deletion); the `pre-lean-merge` tag marks the old state. The installed copies in
`~/.claude/skills` are independent and are rolled back by moving the retired folders back.

## 6. What could not be determined

- GitHub Actions on Ubuntu and Windows (passes locally on Windows and in a Linux container;
  not run on Actions: needs a push).
- Whether the lean skills load and behave in a live Claude Code or Codex session (the
  compatibility page already says no runtime smoke test was performed).
- Whether anything outside the three repositories and the launchers reads this repository's
  `main` (searched the workspace launchers and the agentops tree only).
