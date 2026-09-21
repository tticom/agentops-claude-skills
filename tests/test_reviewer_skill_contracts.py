"""Contracts that the reviewer, author and dispatch skills must keep.

Ported from the source suite. These pin safeguards that must survive any future
edit: exact-head review, comment-only reviewers, direct GitHub publication, honest
handling of unexecuted evidence, and proportional (not domain-forced) depth.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[1] / "skills"


def raw(relative: str) -> str:
    """The file exactly as written; use for line-anchored checks."""
    return (SKILLS / relative).read_text(encoding="utf-8")


def read(relative: str) -> str:
    """The file with whitespace collapsed, so a phrase wrapped across lines still matches."""
    return " ".join(raw(relative).split())


BASIC = "code-review/SKILL.md"
HARD = "hard-review/SKILL.md"
DEVIL = "devils-advocate-review/SKILL.md"
FIREWALL = "code-review/references/reviewer-firewall.md"
REVIEWERS = (BASIC, HARD, DEVIL)


def test_all_levels_are_comment_only_and_publish_a_marked_summary() -> None:
    basic, hard, devil, firewall = read(BASIC), read(HARD), read(DEVIL), read(FIREWALL)
    assert "publish_review.py" in basic
    assert "reviewer-summary:basic" in basic
    assert "reviewer-summary:hard" in hard
    assert "reviewer-summary:devils-advocate" in devil
    assert "reviewed repository" in firewall.lower()
    assert "must not" in firewall.lower()
    forbidden = re.compile(r"^\s*(?:git\s+(?:add|commit|push)|gh\s+pr\s+merge|apply_patch)\b", re.MULTILINE)
    for name, path in (("basic", BASIC), ("hard", HARD), ("devil", DEVIL), ("firewall", FIREWALL)):
        assert forbidden.search(raw(path)) is None, f"{name} contains a repository-mutating command"


@pytest.mark.parametrize("path", REVIEWERS)
def test_reviews_must_be_published_to_the_pull_request_not_only_chat(path: str) -> None:
    text = read(path).lower()
    assert "pull request" in text or "pr thread" in text or "pr comment" in text
    assert "chat" in text, "each reviewer skill must forbid chat-only output"


def test_hard_and_devil_contracts_cannot_collapse_to_basic() -> None:
    hard, devil = read(HARD), read(DEVIL)
    for phrase in ("SYNTHETIC_OR_MOCKED", "DATA_FREE", "REAL_SOURCE_END_TO_END", "fixture_coupling_scan.py",
                   "independent semantic oracle"):
        assert phrase in hard
    assert "contradiction ledger" in devil.lower()
    assert "prior reviewer" in devil
    assert "provisional verdict `CHANGES_REQUESTED`" in devil


def test_review_depth_is_proportional_not_domain_forced() -> None:
    """Infrastructure changes must not be forced into real-source evidence."""
    basic, hard, devil = read(BASIC), read(HARD), read(DEVIL)
    protocol = read("hard-review/references/evidence-falsification-protocol.md")
    assert "proportionally" in basic
    for text in (hard, protocol):
        assert "infrastructure" in text and "evidence_scope" in text
    assert "Do not demand real-source acceptance tests" in hard
    assert "Never pick a narrower scope to avoid available real-source evidence" in hard
    assert "infrastructure" in devil


def test_exact_head_verification_and_clean_checkout_are_required() -> None:
    basic = read(BASIC)
    for phrase in ("verify_review_head.py", "detached exact-head checkout", "<full-live-head>",
                   "git ls-files", "`CANNOT_VERIFY`"):
        assert phrase in basic
    assert "Re-query the live head immediately before publication" in basic
    assert "publish nothing and restart" in basic


def test_publication_is_read_back_and_leaves_the_reviewed_repository_clean() -> None:
    basic = read(BASIC)
    assert "Read the published state back" in basic
    assert "git status --porcelain=v1 --untracked-files=all" in basic
    assert "no commit, push, ref update, merge" in basic


def test_merge_authority_comes_from_policy_not_from_the_documents() -> None:
    firewall = read(FIREWALL)
    for phrase in ("`never_merge`", "`maintainers`", "`delegated_mergers`", "must refuse every merge instruction",
                   "current, explicit instruction from a maintainer", "role policy"):
        assert phrase in firewall
    loop = read("governed-development-loop/SKILL.md")
    assert "never" in loop and "role policy" in loop
    assert "Never force-push" in loop


def test_false_success_regressions_are_explicitly_blocked() -> None:
    basic, hard, devil, implement = read(BASIC), read(HARD), read(DEVIL), read("verified-implementation/SKILL.md")
    assert "detached exact-head checkout" in basic
    assert "`NOT_RUN`" in basic
    assert "`git diff --check`" in basic
    assert "generator" in hard.lower()
    assert "constant-output implementation" in hard
    assert "input is untracked" in devil
    assert "Prove external data assumptions first" in implement
    assert "Trace the final production effect" in implement
    assert "git status --porcelain=v1 --untracked-files=all" in implement
    assert "do not misrepresent it as undefined-name analysis" in implement


def test_code_smells_have_operational_definitions_and_blocking_policy() -> None:
    basic, implement = read(BASIC), read("verified-implementation/SKILL.md")
    smells = read("code-review/references/code-smell-contract.md")
    for phrase in ("Dead code", "Test theatre", "Exception-as-fallback",
                   "Stringly typed classification / substring trap", "Magic number or threshold",
                   "Over-broad exception oracle", "Weak or non-discriminating assertion"):
        assert phrase in smells
    for status in ("`NOT_PRESENT`", "`SUSPECTED`", "`CONFIRMED`", "`EXEMPT`"):
        assert status in smells
    assert "blocks developer handback and reviewer approval" in smells
    assert "code-smell contract" in basic
    assert "`APPROVE` is forbidden" in basic
    assert "do not hand back" in implement


def test_changes_requested_contract_enforces_remediation_rules() -> None:
    text = read("changes-requested/SKILL.md")
    for phrase in ("Never amend or force-push", "Reproduce before fixing", "publish-pr-handback",
                   "fetch_review_findings.py", "do not push to its branch"):
        assert phrase in text


def test_handback_contract_refuses_unproven_states() -> None:
    text = read("publish-pr-handback/SKILL.md")
    for phrase in ("AUTHOR_HANDBACK_PUBLICATION=PASS", "outside the worktree", "`NOT_RUN`",
                   "Repeated execution on an unchanged head", "author-handback.v1"):
        assert phrase in text


def test_dispatch_contract_never_invents_authority_or_state() -> None:
    text = read("dispatch-task/SKILL.md")
    for phrase in ("No action was executed; this is a handoff only.", "is not a task-state system",
                   "never permission", "without a shell", "STOP_NO_CONFIG", "STOP_CONFLICT",
                   "STOP_NO_ACTIVE_TASK", "Do one bounded action, then stop"):
        assert phrase in text
    assert "`go`" not in text.replace("no `go` alias", "")


@pytest.mark.parametrize("path", [p.relative_to(SKILLS).as_posix() for p in SKILLS.glob("*/SKILL.md")])
def test_no_skill_grants_merge_or_protected_branch_authority(path: str) -> None:
    text = raw(path)
    merge_command = re.compile(r"^\s*gh\s+pr\s+merge\b", re.MULTILINE)
    assert merge_command.search(text) is None
    assert not re.search(r"^\s*git\s+push\b[^\n]*(--force|-f\b)", text, re.MULTILINE)
