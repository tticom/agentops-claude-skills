# Stage 1 architect decision: completing the migration

**Status:** PROPOSED, with the three Supervisor decisions in section 7 recorded as RESOLVED. Awaiting independent architecture verification. **No implementation is authorised by this document until that verification is complete and this record is merged.** This PR stays docs-only.
**Author role:** Architect (`tticom-automation`). This record contains no reviewer verdict and none may be inferred from it.
**Baseline:** `main` at `3d131ec6873af60df9418e11c1c1e76124e89de2` (PR #2 merge commit; final PR head `70f35af208dc473981c590d90e523026efd14e5b`).

## 1. Verified baseline

Each row was checked on 2026-09-21, not carried over from the programme brief.

| Claim | Result | How verified |
|---|---|---|
| `tticom/agy-skills` `main` equals the inventory pin | `8366e98413974f18f8ddf4e7e20b35d2e39f45a4` on both | `git fetch` then `rev-parse origin/main`; pin read from `docs/MIGRATION_INVENTORY.md`. **No source drift.** |
| Target `main` | `3d131ec6873af60df9418e11c1c1e76124e89de2`; PR #2 head `70f35af` is an ancestor | `git fetch`, `merge-base --is-ancestor` |
| Post-merge CI | run `35579439108` on the merge commit: success on Ubuntu (586 passed) and Windows (586 passed); validator OK on both | `gh run view` and its logs |
| Formal review record for PR #2 | Codex: `CHANGES_REQUESTED` on `ae0fb66` and `5131c1b`; **no formal review on `82bcc78` or the final head `70f35af`** | `gh api pulls/2/reviews` grouped by commit |
| Open PRs and issues in the target | none | `gh pr list`, `gh issue list` |
| Vendored helpers on the merged tree | `gh_publication.py` and `role_authority_gate.py` copies byte-identical | `cmp` on an exported copy of the merge commit |
| Round-4 defect (non-object elements dropped by `paginate`) | reproduced on the pre-fix `82bcc78` helper (`[null]` and `[valid, null]` both pass an exact-cardinality check); both rejected on the merged helper | scratch export of both trees, same probe |
| Merged tree's own suite | 585 passed, 1 skipped (symlink privilege, local); validator OK | full suite run on the exported merge commit |

The last three rows are **author-side evidence for the Stage 0 reviewer**, not a Stage 0 verdict.

## 2. Reassessed dispositions

Every one of the 46 source commands and the supporting files keeps its inventory disposition **except two**, whose stated reason has expired.

| Item | Inventory said | Now | Why |
|---|---|---|---|
| `git-guardrails` | blocked: hook contracts for Claude Code and Codex unverified | **Outcome A: still requires migration; a viable design exists** | Both runtimes now document `PreToolUse` interception with deny semantics (section 3). The old script is also unfit to port (section 4). |
| `scripts/workspace-startup.sh` | blocked: bash-only, not ported | **Outcome A: still requires migration** | Its behaviour is unique in this ecosystem (section 5); Bash was never the reason to retire it. |

Unchanged and not reopened: 11 migrated, 1 consolidated (`go` into `dispatch-task`), 30 `upstream-provided` (recorded, **not** copied), 3 obsolete. No AgentOps skill was found to depend on an upstream-provided skill, so none is duplicated. After Stages 2 and 3 there is no `blocked` source item left.

## 3. Hook contracts: what is known

Sources: the official Claude Code hooks page and the official Codex hooks page, fetched 2026-09-21 through a summarising fetcher. **Treat every FACT as "documented, to be confirmed by the Stage 2 runtime smoke on the installed versions" (Claude Code 2.1.278, Codex CLI 0.155.1).**

### FACT

| Topic | Claude Code | Codex |
|---|---|---|
| Config locations | `~/.claude/settings.json`, `.claude/settings.json`, `.claude/settings.local.json`, managed policy, plugins | `~/.codex/hooks.json`, `~/.codex/config.toml` (`[hooks]`), `<repo>/.codex/hooks.json`, `<repo>/.codex/config.toml`; higher layers do not replace lower-layer hooks |
| Entry shape | `hooks.PreToolUse[]` of `{matcher, hooks:[{type:"command", command, args, timeout, shell}]}` | same nesting, `type: "command"`, `command`, `timeout`, plus `commandWindows` (JSON) / `command_windows` (TOML) |
| Stdin for a shell tool | `hook_event_name`, `tool_name` (`Bash`, and a separate `PowerShell`), `tool_input.command`, `cwd`, `session_id`, `permission_mode` | `hook_event_name`, `tool_name` (canonical `Bash`, `apply_patch`, MCP), `tool_input.command`, `cwd`, `session_id`, `turn_id`, `model` |
| Deny | exit code `2` (stderr is the reason), **or** stdout JSON `hookSpecificOutput.permissionDecision: "deny"` + `permissionDecisionReason`; exit 2 blocks regardless of JSON; other non-zero codes do not block | exit code `2` with the reason on stderr, **or** the same JSON; legacy `{"decision":"block","reason":...}` also accepted |
| No decision | exit 0 and empty stdout continues the normal permission flow | same |
| Tools matchable | `Bash`, `PowerShell`, `Edit`, `Write`, MCP `mcp__<server>__<tool>`; matcher is exact, `\|`-list or regex | shell/`Bash`, `apply_patch`, MCP and local function tools; **hosted tools such as WebSearch are not intercepted** |
| Windows | `shell: "powershell"` per hook; PowerShell is its own matchable tool | `commandWindows` / `command_windows` override |
| Trust | not stated for `.claude/settings.json` hooks; subagent frontmatter hooks require the workspace trust dialog | project-local hooks load only when the project `.codex/` layer is trusted; `/hooks` reviews and approves; hooks are enabled by default (`[features] hooks = false` disables) |
| Limits | "Use the permission system rather than a hook to enforce a hard allow or deny"; the `if` filter is best-effort; `bypassPermissions` mode may bypass hooks | not stated beyond hosted tools |

### INFERENCE

- A guard must inspect `tool_input.command` for **both** POSIX shell and PowerShell syntax, because on Windows Claude Code exposes both a `Bash` and a `PowerShell` tool.
- Exit code 2 plus a stderr reason is the one deny form documented identically for both runtimes, so it is the least risky default. (Confirm whether JSON on stdout is also needed or harmful.)
- Because hooks are documented as not a hard boundary, the guard is **defence in depth** beside the role gate and server-side branch protection, and must be documented as such.

### HYPOTHESIS (to test in Stage 2)

- On Windows Codex reports shell commands under `tool_name: "Bash"` even when the underlying shell is PowerShell.
- A project-scope hook file is enough for a disposable test repository once trusted.

### UNKNOWN

- The `tool_name` and `tool_input` shape Codex uses on native Windows.
- Whether Codex hooks fire inside sub-agents and in non-interactive `codex exec`.
- How `commandWindows` interacts with `command` when both are set, and how `python` is resolved from a hook on each OS.
- Whether Claude Code applies a trust prompt to project `.claude/settings.json` hooks.

## 4. Decision: `git-guardrails` (Outcome A)

### Evidence the old script is not portable

I ran the old hook's exact patterns (`block-dangerous-git.sh`) against 14 commands. It was **wrong on 7 of 14**:

- **Missed dangerous:** `git -c core.x=1 clean -fdx`, `git clean -xf`, `git checkout -- .`, `git branch --delete --force topic`.
- **Blocked safe:** `git push origin feature/x` (a bounded feature push that AgentOps policy permits), and `git push` merely *mentioned* in `echo "run git push later"` and `git log --grep='git push'`.

It also needs `jq` and Bash, and its install paths and prompts are for a retired harness. So this is a new implementation from AgentOps requirements, not a port. Nothing is copied from it.

### Design

**Shape.** Skill `git-guardrails` with one cross-platform Python entrypoint, `scripts/git_guard.py`, that both runtimes invoke as a `PreToolUse` command. It reads the hook JSON on stdin, extracts `tool_input.command`, decides, and exits 0 (no decision) or 2 with a reason on stderr. A second helper, `scripts/print_hook_config.py`, **prints** ready-to-paste configuration for either runtime and OS; the skill never edits a user's settings itself.

**One authority model, not two (Supervisor Decision 1, RESOLVED).** The identity profile that `identity-safe-git` already defines is the **single authority for ordinary working-branch pushes**. Its `protected_branches`, `allowed_working_branches` and `permissions.push_working_branch` fields exist today but only document policy; the guard is where they become enforced. No second push-policy file is introduced.

An ordinary push is permitted only when **all five** hold:

1. a valid identity profile is available;
2. `permissions.push_working_branch` is `true`;
3. every destination branch matches `allowed_working_branches`;
4. no destination is protected (`protected_branches`);
5. the operation is not inherently destructive.

A missing, unreadable or malformed profile denies **the push**. It never denies other Git commands: `git status` and `git log` still work without a profile.

Inherently destructive operations are denied **regardless of any profile**, and profile permission to push a working branch never authorises them (table below). Permission to push a feature branch is never merge authority.

*What "valid" means.* The guard applies the same validity rules as `identity-safe-git`'s profile loader (required identity fields present, unknown keys rejected) plus type checks on the three policy fields. To avoid a second implementation of those rules, the loader would be extracted from `verify_identity.py` into a small `identity_profile.py` and carried as a byte-identical vendored copy, with `identity-safe-git`'s existing tests passing unchanged. This is an Architect recommendation that follows from Decision 1 and is bounded in the same way as the approved `workspace_git.py` extraction; **the reviewer is asked to disposition it explicitly.**

**Decision procedure.**
1. Tokenise the command with a real shell-aware splitter (POSIX rules for `Bash`, PowerShell rules for `PowerShell`), split on `;`, `&&`, `||`, `|`, `&` and newlines, and recurse into `bash -c`, `pwsh -Command` and `$(...)` where the argument is a literal.
2. For each segment whose program is `git`, skip global options (`-C <path>`, `-c k=v`, `--git-dir`, `--work-tree`, `--no-pager`) to find the real subcommand, then classify subcommand and flags **structurally**. The text `git push` inside an argument to another program is not a git invocation.
3. **Fail closed only after an actual Git invocation has been identified (Supervisor Decision 2, RESOLVED).** If a segment's program is structurally `git` and the guard cannot safely classify the operation or determine that it is authorised (`git $SUBCOMMAND`, a push whose destination is an unresolved variable, a refspec that cannot be classified, a push with no explicit destination whose repository configuration cannot be established), **that Git invocation is denied** with an explicit reason. A command that merely *contains the text* `git` is not a Git invocation and is **allowed**: `echo "run git push later"` and `git log --grep="git push"` must pass.

   The guard does not become a shell sandbox. Dynamic constructs it cannot prove invoke Git (`eval`, aliases, a script the agent writes and runs, a program name built from variables) are a **documented limitation** of this defence-in-depth control, not grounds to block arbitrary shell execution. Literal nested shell text (`bash -c '...'`, `pwsh -Command '...'`) is parsed recursively where the nested command is available as literal text.

**Deny set (all structural).** The first row depends on the identity profile; **every other row is inherently destructive and denied regardless of the profile.**

| Operation | Denied when |
|---|---|
| ordinary push | any of the five conditions above fails: no valid profile, `push_working_branch` not `true`, a destination outside `allowed_working_branches`, or a protected destination. Includes `HEAD:refs/heads/x`, `:x` deletes, `--all`, `--mirror`, and a push whose destination cannot be established |
| force push | `--force`, `-f`, `--force-with-lease`, `+refspec` |
| `reset --hard` | always |
| `clean` | any of `-f`, `--force` (with `-d`, `-x`, `-X` in any order or grouping) |
| `branch` delete | `-D`, or `-d` with `--force`, `--delete --force` |
| repository-wide discard | `checkout .`, `checkout -- .`, `restore .`, `restore --source ... .`, `checkout -f` |

A bounded push of a working branch **is allowed exactly when the five conditions hold**. This preserves the rule that permission to push a feature branch is never permission to merge.

**Windows.** Emitted config uses `commandWindows` / `command_windows` for Codex and `shell: "powershell"` (or a `Bash|PowerShell` matcher pair) for Claude Code, with the script path quoted for spaces, and `py -3` / `python` chosen per OS.

**Stated limits (must appear in the skill).** Not a security boundary (the runtimes say so). Cannot see git run inside another program, an alias, or a script the agent writes and executes. Does not cover hosted Codex tools. Pair it with the role gate and server-side branch protection.

**Acceptance for Stage 2.** Fixture tests built from the documented hook JSON for **both** runtimes, including the `PowerShell` tool; the 14-case table above as allow/deny controls (including `echo "run git push later"` and `git log --grep="git push"` allowed, and `git $SUBCOMMAND` denied); each of the five push conditions failing independently; a missing, unreadable and malformed profile denying pushes while `git status` still passes; every destructive operation denied even under a fully permissive profile; plus flag-order, quoting and chaining variants; Windows command-line quoting tests; a test that the deny path can never exit 0; equivalence between profile fields and behaviour; and an actual disposable-repo hook smoke on both installed runtimes before approval. Any UNKNOWN in section 3 that the smoke cannot resolve stays documented as UNKNOWN.

## 5. Decision: `workspace-startup.sh` (Outcome A)

### Is the capability covered elsewhere?

No. Checked:

- `Check-WorkspaceGitStatus.ps1` (workspace launcher tooling) runs `git fetch --prune` and reports status. It **never fast-forwards**.
- No launcher script uses `--ff-only`.
- `score2gp_control_plane.sync_main` fast-forwards, but only the two repositories that one project's dispatcher manages, and it *switches* branches (`git switch main`), which the startup script never does.
- `workspace-cleanup` prunes stale review worktrees and writes an index; it neither fetches nor updates checkouts.

Its unique behaviour: enumerate immediate checkouts; fetch; fast-forward only clean checkouts already on the target branch; leave everything else untouched; write per-checkout state evidence. That is a reusable, project-independent capability. This is **not** Outcome B or C.

### Design

**Name and placement (Supervisor Decision 3, RESOLVED).** New skill **`workspace-sync`**, kept separate from `workspace-cleanup`. It is not merged into `workspace-cleanup`: cleanup *removes* things and sync *updates* things, and one skill should not hold both mutations. I considered consolidating and rejected it.

**Behaviour (each preserved-case has a real-Git test).**

| Checkout state | Action |
|---|---|
| resolves outside the workspace | preserved, recorded |
| dirty (tracked changes or untracked files) | preserved |
| detached HEAD | preserved |
| on a branch other than the target | preserved |
| target branch, no remote | preserved |
| fetch fails | recorded, checkout untouched |
| no remote-tracking ref for the target | preserved |
| diverged or not a fast-forward | preserved |
| target branch, clean, strictly behind | `merge --ff-only` and record `updated` |
| already current | record `current` |

The old script reported both of the last two as `updated-or-current`; the new one compares HEAD before and after so the receipt is truthful. No reset, rebase, checkout, switch, stash or force operation is ever issued.

**Design decisions.** Items 1 to 4 are Architect recommendations for the reviewer to confirm. Item 5 and the skill name are Supervisor-approved (Decision 3).
1. Target branch defaults to the remote's default branch, falling back to `main`; overridable.
2. Read-only inspection first. `--dry-run` computes what *would* be fast-forwarded from existing remote-tracking refs **without fetching**, because fetch itself updates refs.
3. `fetch --prune` is off by default (it deletes remote-tracking refs) and available as an option.
4. The receipt goes outside every scanned repository, as in `workspace-cleanup`.
5. **Shared helper `workspace_git.py` (approved).** One canonical copy plus a byte-identical vendored copy in the sibling skill, with a byte-identity contract test, exactly as for `role_authority_gate.py` and `gh_publication.py`. Scope is limited to the proven primitives both skills need: `same_path`, `within_workspace`, repository discovery, workspace scoping and repository grouping (plus the `run_cmd` subprocess wrapper, which both need; it decodes as UTF-8 with `errors="replace"`, which is acceptable for Git output that is only inspected, and the reviewer may disposition its inclusion). It is **not** licence to redesign `workspace-cleanup`: cleanup behaviour is preserved and **all 43 of its existing tests must pass unchanged**. The extraction is an implementation detail of delivering `workspace-sync`; on its own it is not progress, and the implementing PR's deliverable is the new capability.

## 6. Sequencing and boundaries

- **Stage 0** (independent post-merge hard verification) is required and is **not** performed here. Only the author-side evidence in section 1 is.
- **Stage 0 does not block this architecture verification.** They are separate questions and the independent reviewer may verify them separately. Stage 0 blocks *declaring the migration complete*, and a `CORRECTIVE_PR_REQUIRED` result would take priority before that. A successful post-merge verification would not make PR #2's merge retroactively correctly reviewed.
- **Stage 1** is this document. **Implementation of Stages 2 and 3 is not authorised until an independent reviewer verifies this decision.**
- Stage 2 (`git-guardrails`) and Stage 3 (`workspace-sync`) are separate PRs. They must not be combined with each other or with installer work.
- Stages 4 to 8 are unchanged by this document. In particular the installer defaults to copied snapshots and does not silently exclude `test_*.py`.
- Out of scope here: Score2GP governance, the installer, and any live GitHub artifact.

## 7. Supervisor decisions (RESOLVED)

**Decision 1: push authority. RESOLVED (approved with precise semantics).** The existing identity profile is the single authority for ordinary working-branch pushes; no second push-policy model is introduced. A push is permitted only if a valid profile exists, `permissions.push_working_branch` is true, every destination matches `allowed_working_branches`, none is protected, and the operation is not otherwise destructive. A missing, unreadable or malformed profile denies the push, **not every Git command**. Force push (including `--force-with-lease` and forced refspecs), `reset --hard`, forced `clean`, forced branch deletion and repository-wide destructive checkout/restore are denied regardless of the profile. Permission to push a feature branch is never merge authority.

**Decision 2: unparseable Git. RESOLVED (approved with narrower fail-closed semantics).** The rule is **not** "a command that mentions `git` but cannot be parsed is denied", which would reproduce the old hook's false positives (`echo "run git push later"`, `git log --grep="git push"`). First establish structurally that an actual Git invocation exists. Then, if the guard cannot safely classify that invocation or determine that it is authorised (`git $SUBCOMMAND`, `git push origin "$UNRESOLVED"`), deny **that Git invocation**. A non-Git command that merely contains the text `git` is never denied. The guard is not a shell sandbox: dynamic constructs it cannot prove invoke Git are a documented limitation, and literal nested shell text may be parsed recursively. The record retains the statement that hooks are **defence in depth** alongside `identity-safe-git`, role authority and repository/server-side protections.

**Decision 3: workspace sync. RESOLVED (approved).** The skill is `workspace-sync`, separate from `workspace-cleanup` (sync safely updates eligible checkouts; cleanup removes provably disposable review worktrees; the mutation classes are not combined). The shared helper is `workspace_git.py`, limited to the proven common primitives, delivered as one canonical copy plus a byte-identical vendored copy with a byte-identity test. It must not become a general rewrite of `workspace-cleanup`, all existing cleanup tests must pass unchanged, and the extraction alone does not count as progress.

**Stage 0 clarification.** Post-merge verification of PR #2 remains required, must return exactly one of `POST_MERGE_VERIFIED`, `CORRECTIVE_PR_REQUIRED` or `CANNOT_VERIFY`, and does not block the architecture verification of this PR. Corrective work, if required, takes priority before the migration can be declared complete.

## 8. What the independent reviewer should verify

- Section 1's rows against `main` and the run logs, and Stage 0 separately.
- That the two reassessed dispositions follow from the evidence, and that no other item should change.
- Section 3's FACT rows against the raw official pages (I used a summarising fetcher), and that each UNKNOWN is honestly unresolved.
- That the design integrates with `identity-safe-git` rather than adding a contradictory authority model, and that the stated limits are not overclaimed.
- That `workspace-sync` is genuinely not covered by existing tooling, and that no design step can delete or rewrite user work.

### Dispositions requested from the reviewer

Please give an explicit disposition (approve, or a bounded finding) on each of:

1. **`git-guardrails` architecture** as a whole (Outcome A, independent implementation).
2. **Push authority** (Decision 1): the five conditions, the destructive-always-denied set, and the recommended shared profile loader (`identity_profile.py`) as the way to keep "valid profile" single-sourced.
3. **Unparseable-Git semantics** (Decision 2): that the guard can deny an *identified Git invocation* it cannot classify, cannot deny an unrelated command merely because its text contains `git`, and is not presented as a sandbox.
4. **`workspace-sync`** (Decision 3): the capability, the state table, and that it is not covered by existing tooling.
5. **Shared helper extraction**: that `workspace_git.py` is bounded to the named primitives, does not redesign `workspace-cleanup`, and does not by itself count as progress.
6. That runtime **UNKNOWN** items in section 3 are not represented as verified FACT.

Success is an architecture approval. Anything else should be a bounded, specific finding.
