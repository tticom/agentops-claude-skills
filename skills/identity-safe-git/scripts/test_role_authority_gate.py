#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import role_authority_gate as gate
from role_authority_gate import AuthorityDenied, load_policy, parse_policy, validate

POLICY = parse_policy(
    {
        "reviewers": ["gov-bot", "author-bot", "delegate-bot", "maintainer"],
        "never_merge": ["gov-bot", "author-bot"],
        "maintainers": ["maintainer"],
        "delegated_mergers": ["delegate-bot"],
    }
)
COMMON = {"repo": "example-org/example", "pr": 514, "policy": POLICY}
HEAD = "a" * 40


class RoleAuthorityGateTest(unittest.TestCase):
    def test_governance_identity_can_review_another_author(self):
        result = validate(
            actor="gov-bot", operation="review-metadata", pr_author="author-bot", **COMMON
        )
        self.assertEqual(result, "review metadata allowed")

    def test_identity_comparison_is_case_insensitive(self):
        result = validate(
            actor="Gov-Bot", operation="review-metadata", pr_author="AUTHOR-BOT", **COMMON
        )
        self.assertEqual(result, "review metadata allowed")

    def test_self_review_is_denied(self):
        with self.assertRaisesRegex(AuthorityDenied, "self-review"):
            validate(
                actor="author-bot", operation="review-metadata", pr_author="author-bot", **COMMON
            )

    def test_unlisted_identity_cannot_review(self):
        with self.assertRaisesRegex(AuthorityDenied, "not an authorized reviewer"):
            validate(actor="stranger", operation="review-metadata", pr_author="author-bot", **COMMON)

    def test_review_requires_the_pr_author(self):
        with self.assertRaisesRegex(AuthorityDenied, "pr_author is required"):
            validate(actor="gov-bot", operation="review-metadata", **COMMON)

    def test_reviewed_repository_write_is_always_denied(self):
        for actor in ("gov-bot", "author-bot", "delegate-bot", "maintainer"):
            with self.subTest(actor=actor), self.assertRaisesRegex(AuthorityDenied, "comment-only"):
                validate(actor=actor, operation="reviewed-repo-write", **COMMON)

    def test_no_merge_identities_can_never_merge(self):
        for actor in ("gov-bot", "author-bot"):
            with self.subTest(actor=actor), self.assertRaisesRegex(
                AuthorityDenied, "unconditional no-merge"
            ):
                validate(
                    actor=actor,
                    operation="merge",
                    authorization_actor="maintainer",
                    authorization_repo=COMMON["repo"],
                    authorization_pr=COMMON["pr"],
                    expected_head=HEAD,
                    authorization_head=HEAD,
                    current_turn_explicit=True,
                    **COMMON,
                )

    def test_delegated_merger_requires_current_exact_maintainer_authorization(self):
        denied_cases = (
            {},
            {"authorization_actor": "maintainer"},
            {
                "authorization_actor": "maintainer",
                "authorization_repo": COMMON["repo"],
                "authorization_pr": COMMON["pr"],
                "expected_head": HEAD,
                "authorization_head": HEAD,
            },
            {
                "authorization_actor": "maintainer",
                "authorization_repo": "example-org/other",
                "authorization_pr": COMMON["pr"],
                "expected_head": HEAD,
                "authorization_head": HEAD,
                "current_turn_explicit": True,
            },
            {
                "authorization_actor": "maintainer",
                "authorization_repo": COMMON["repo"],
                "authorization_pr": COMMON["pr"] + 1,
                "expected_head": HEAD,
                "authorization_head": HEAD,
                "current_turn_explicit": True,
            },
            {
                "authorization_actor": "maintainer",
                "authorization_repo": COMMON["repo"],
                "authorization_pr": COMMON["pr"],
                "expected_head": HEAD,
                "authorization_head": "b" * 40,
                "current_turn_explicit": True,
            },
            {
                "authorization_actor": "maintainer",
                "authorization_repo": COMMON["repo"],
                "authorization_pr": COMMON["pr"],
                "expected_head": "abc123",
                "authorization_head": "abc123",
                "current_turn_explicit": True,
            },
            {
                "authorization_actor": "author-bot",
                "authorization_repo": COMMON["repo"],
                "authorization_pr": COMMON["pr"],
                "expected_head": HEAD,
                "authorization_head": HEAD,
                "current_turn_explicit": True,
            },
        )
        for extra in denied_cases:
            with self.subTest(extra=extra), self.assertRaises(AuthorityDenied):
                validate(actor="delegate-bot", operation="merge", **COMMON, **extra)

        result = validate(
            actor="delegate-bot",
            operation="merge",
            authorization_actor="maintainer",
            authorization_repo=COMMON["repo"],
            authorization_pr=COMMON["pr"],
            expected_head=HEAD,
            authorization_head=HEAD,
            current_turn_explicit=True,
            **COMMON,
        )
        self.assertIn("exact PR", result)

    def test_maintainer_and_unknown_identity(self):
        self.assertEqual(
            validate(actor="maintainer", operation="merge", **COMMON),
            "maintainer merge allowed",
        )
        with self.assertRaisesRegex(AuthorityDenied, "no merge authority"):
            validate(actor="unknown-agent", operation="merge", **COMMON)

    def test_malformed_targets_and_operations_are_denied(self):
        with self.assertRaisesRegex(AuthorityDenied, "owner/name"):
            validate(actor="maintainer", operation="merge", **{**COMMON, "repo": "no-slash"})
        with self.assertRaisesRegex(AuthorityDenied, "positive"):
            validate(actor="maintainer", operation="merge", **{**COMMON, "pr": 0})
        with self.assertRaisesRegex(AuthorityDenied, "unsupported operation"):
            validate(actor="maintainer", operation="force-push", **COMMON)


class PolicyTest(unittest.TestCase):
    def test_empty_policy_denies_everything(self):
        empty = parse_policy({})
        with self.assertRaisesRegex(AuthorityDenied, "not an authorized reviewer"):
            validate(
                actor="maintainer",
                operation="review-metadata",
                pr_author="x",
                repo="o/r",
                pr=1,
                policy=empty,
            )
        with self.assertRaisesRegex(AuthorityDenied, "no merge authority"):
            validate(actor="maintainer", operation="merge", repo="o/r", pr=1, policy=empty)

    def test_invalid_policies_are_rejected(self):
        bad = (
            [],
            {"reviewers": "gov-bot"},
            {"reviewers": [""]},
            {"reviewers": [1]},
            {"unknown": []},
            {"never_merge": ["a"], "maintainers": ["a"]},
            {"never_merge": ["a"], "delegated_mergers": ["A"]},
            {"maintainers": ["a"], "delegated_mergers": ["a"]},
        )
        for value in bad:
            with self.subTest(value=value), self.assertRaisesRegex(AuthorityDenied, "invalid policy"):
                parse_policy(value)

    def test_policy_is_required_and_never_defaulted(self):
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop(gate.POLICY_ENV, None)
            with self.assertRaisesRegex(AuthorityDenied, "role policy is required"):
                load_policy(None)

    def test_policy_loads_from_file_and_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps({"reviewers": ["Rev"]}), encoding="utf-8")
            self.assertEqual(load_policy(path).reviewers, frozenset({"rev"}))
            with patch.dict("os.environ", {gate.POLICY_ENV: str(path)}):
                self.assertEqual(load_policy(None).reviewers, frozenset({"rev"}))
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaisesRegex(AuthorityDenied, "invalid policy"):
                load_policy(path)
            with self.assertRaisesRegex(AuthorityDenied, "invalid policy"):
                load_policy(Path(directory) / "missing.json")

    def test_command_line_denies_and_passes_with_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps({"maintainers": ["maintainer"]}), encoding="utf-8")
            base = ["prog", "--policy", str(path), "--repo", "o/r", "--pr", "1"]
            with patch("sys.argv", [*base, "--actor", "maintainer", "--operation", "merge"]):
                gate.main()
            with patch("sys.argv", [*base, "--actor", "other", "--operation", "merge"]):
                with self.assertRaisesRegex(SystemExit, "ROLE_AUTHORITY_GATE=DENY"):
                    gate.main()


if __name__ == "__main__":
    unittest.main()
