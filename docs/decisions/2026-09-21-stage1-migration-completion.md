# Stage 1 architect decision: completing the migration

**Status:** PROPOSED. Awaiting independent architecture verification. **No implementation is authorised by this document.**
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

**One authority model, not two.** The guard reads the same **identity profile** that `identity-safe-git` already defines. Its `protected_branches`, `allowed_working_branches` and `permissions.push_working_branch` fields exist today but are only documentation. The guard is where they become enforced. Without a profile it applies the built-in deny set below and treats every push as unauthorised, and it says so.

**Decision procedure.**
1. Tokenise the command with a real shell-aware splitter (POSIX rules for `Bash`, PowerShell rules for `PowerShell`), split on `;`, `&&`, `||`, `|`, `&` and newlines, and recurse into `bash -c`, `pwsh -Command` and `$(...)` where the argument is a literal.
2. For each segment whose program is `git`, skip global options (`-C <path>`, `-c k=v`, `--git-dir`, `--work-tree`, `--no-pager`) to find the real subcommand, then classify subcommand and flags **structurally**. The text `git push` inside an argument to another program is not a git invocation.
3. A command that mentions `git` but cannot be parsed (unresolved variables, unbalanced quotes, `eval`) is **denied with an explicit reason**. A command with no `git` program is allowed.

**Deny set (minimum, all structural).**

| Operation | Denied when |
|---|---|
| push to a protected or unlisted branch | destination (including `HEAD:refs/heads/x`, `:x` deletes, `--all`, `--mirror`, `--tags` to protected) is not permitted by the profile, or there is no profile |
| force push | `--force`, `-f`, `--force-with-lease`, `+refspec` |
| `reset --hard` | always |
| `clean` | any of `-f`, `--force` (with `-d`, `-x`, `-X` in any order or grouping) |
| `branch` delete | `-D`, or `-d` with `--force`, `--delete --force` |
| repository-wide discard | `checkout .`, `checkout -- .`, `restore .`, `restore --source ... .`, `checkout -f` |

A bounded push of a feature branch **is allowed** when the profile permits it (`permissions.push_working_branch` and a matching `allowed_working_branches` pattern). This preserves the rule that permission to push a feature branch is never permission to merge.

**Windows.** Emitted config uses `commandWindows` / `command_windows` for Codex and `shell: "powershell"` (or a `Bash|PowerShell` matcher pair) for Claude Code, with the script path quoted for spaces, and `py -3` / `python` chosen per OS.

**Stated limits (must appear in the skill).** Not a security boundary (the runtimes say so). Cannot see git run inside another program, an alias, or a script the agent writes and executes. Does not cover hosted Codex tools. Pair it with the role gate and server-side branch protection.

**Acceptance for Stage 2.** Fixture tests built from the documented hook JSON for **both** runtimes, including the `PowerShell` tool; the 14-case table above as allow/deny controls, plus flag-order, quoting and chaining variants; Windows command-line quoting tests; a test that the deny path can never exit 0; equivalence between profile fields and behaviour; and an actual disposable-repo hook smoke on both installed runtimes before approval. Any UNKNOWN in section 3 that the smoke cannot resolve stays documented as UNKNOWN.

## 5. Decision: `workspace-startup.sh` (Outcome A)

### Is the capability covered elsewhere?

No. Checked:

- `Check-WorkspaceGitStatus.ps1` (workspace launcher tooling) runs `git fetch --prune` and reports status. It **never fast-forwards**.
- No launcher script uses `--ff-only`.
- `score2gp_control_plane.sync_main` fast-forwards, but only the two repositories that one project's dispatcher manages, and it *switches* branches (`git switch main`), which the startup script never does.
- `workspace-cleanup` prunes stale review worktrees and writes an index; it neither fetches nor updates checkouts.

Its unique behaviour: enumerate immediate checkouts; fetch; fast-forward only clean checkouts already on the target branch; leave everything else untouched; write per-checkout state evidence. That is a reusable, project-independent capability. This is **not** Outcome B or C.

### Design

**Name and placement.** New skill **`workspace-sync`**. It is not merged into `workspace-cleanup`: cleanup *removes* things and sync *updates* things, and one skill should not hold both mutations. I considered consolidating and rejected it.

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

**Decisions I am recommending (open to the Supervisor).**
1. Target branch defaults to the remote's default branch, falling back to `main`; overridable.
2. Read-only inspection first. `--dry-run` computes what *would* be fast-forwarded from existing remote-tracking refs **without fetching**, because fetch itself updates refs.
3. `fetch --prune` is off by default (it deletes remote-tracking refs) and available as an option.
4. The receipt goes outside every scanned repository, as in `workspace-cleanup`.
5. Containment and repository grouping reuse the logic already proven in `workspace-cleanup`. To avoid a second copy that can drift, extract it once into a vendored `workspace_git.py` with a byte-identity test, and re-run `workspace-cleanup`'s existing 43 tests as the safety net. The alternative (a duplicated implementation plus an equivalence test) is cheaper but risks divergence; I recommend the vendored module.

## 6. Sequencing and boundaries

- **Stage 0** (independent post-merge hard verification) is required and is **not** performed here. Only the author-side evidence in section 1 is.
- **Stage 1** is this document. **Implementation of Stages 2 and 3 is not authorised until an independent reviewer verifies this decision.**
- Stage 2 (`git-guardrails`) and Stage 3 (`workspace-sync`) are separate PRs. They must not be combined with each other or with installer work.
- Stages 4 to 8 are unchanged by this document. In particular the installer defaults to copied snapshots and does not silently exclude `test_*.py`.
- Out of scope here: Score2GP governance, the installer, and any live GitHub artifact.

## 7. Questions for the Supervisor

1. Confirm `git-guardrails` should enforce the **identity profile's** branch fields (the single-authority design above), including denying pushes when no profile is present.
2. Confirm deny-on-unparseable-git as the default, given it can block legitimate but unusual commands.
3. Confirm the name `workspace-sync` and the vendored `workspace_git.py` refactor.

## 8. What the independent reviewer should verify

- Section 1's rows against `main` and the run logs, and Stage 0 separately.
- That the two reassessed dispositions follow from the evidence, and that no other item should change.
- Section 3's FACT rows against the raw official pages (I used a summarising fetcher), and that each UNKNOWN is honestly unresolved.
- That the design integrates with `identity-safe-git` rather than adding a contradictory authority model, and that the stated limits are not overclaimed.
- That `workspace-sync` is genuinely not covered by existing tooling, and that no design step can delete or rewrite user work.
