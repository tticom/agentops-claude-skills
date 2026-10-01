# lean/skills: the six consolidated skills (inert until cutover)

Built beside the existing twelve in `skills/`, which the live framework pins and
which are untouched. Same layout rules (one directory per skill, self-contained,
`scripts/` and `references/` inside it).

- `implement`: evidence-gated implementation and clean-head pre-flight
- `review`: two-axis exact-head review, normal and `--adversarial`; advisory PR comment
- `address-review`: fix review findings red-to-green
- `safe-git`: branch and push safety checklist, `safe_git_check.py`
- `workspace-cleanup`: remove provably stale review worktrees
- `durable-handoff`: optional short handoff for paused or transferred work

Install by copying the directories into a skills location (`~/.claude/skills` or
`~/.agents/skills`). Never into the location the live agents use before cutover.

Tests, one skill at a time (test file basenames collide across skills):

```text
cd lean/skills/<skill>/scripts && python -m pytest
```
