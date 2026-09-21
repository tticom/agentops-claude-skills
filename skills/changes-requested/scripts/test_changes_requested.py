#!/usr/bin/env python3
"""Unit tests for fetch_review_findings in changes-requested skill."""

from __future__ import annotations

import unittest
import unittest.mock
from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import fetch_review_findings as frf


class TestFetchReviewFindings(unittest.TestCase):
    def setUp(self) -> None:
        self.sample_pr = {
            "number": 123,
            "base": {"repo": {"full_name": "example-org/test-repo"}},
            "head": {"ref": "feature/my-fix", "sha": "1111111111111111111111111111111111111111"},
            "user": {"login": "author-user"},
        }
        self.sample_reviews = [
            {
                "id": 1,
                "state": "CHANGES_REQUESTED",
                "commit_id": "1111111111111111111111111111111111111111",
                "user": {"login": "reviewer-user"},
                "body": "Please fix boundary conditions.",
            }
        ]
        self.sample_inline_comments = [
            {
                "id": 101,
                "path": "src/module.py",
                "line": 42,
                "user": {"login": "reviewer-user"},
                "body": "Off by one error here.",
                "commit_id": "1111111111111111111111111111111111111111",
                "pull_request_review_id": 1,
            }
        ]
        self.sample_issue_comments = [
            {
                "id": 201,
                "user": {"login": "reviewer-user"},
                "body": "<!-- reviewer-summary:devils-advocate:1111111111111111111111111111111111111111 -->\nReview level: DEVILS_ADVOCATE\nVerdict: CHANGES_REQUESTED",
                "created_at": "2026-09-18T00:00:00Z",
            }
        ]

    def test_parse_summary_comment(self) -> None:
        summary = frf.parse_summary_comment(self.sample_issue_comments)
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary["level"], "devils-advocate")
        self.assertEqual(summary["reviewed_head"], "1111111111111111111111111111111111111111")
        self.assertEqual(summary["author"], "reviewer-user")

    def test_parse_summary_comment_missing(self) -> None:
        comments = [{"id": 1, "body": "regular comment", "user": {"login": "someone"}}]
        self.assertIsNone(frf.parse_summary_comment(comments))

    def test_extract_inline_findings(self) -> None:
        findings = frf.extract_inline_findings(self.sample_inline_comments)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["id"], 101)
        self.assertEqual(findings[0]["path"], "src/module.py")
        self.assertEqual(findings[0]["line"], 42)
        self.assertEqual(findings[0]["body"], "Off by one error here.")

    def test_build_remediation_ledger(self) -> None:
        ledger = frf.build_remediation_ledger(
            self.sample_pr,
            self.sample_reviews,
            self.sample_inline_comments,
            self.sample_issue_comments,
        )
        self.assertEqual(ledger["repository"], "example-org/test-repo")
        self.assertEqual(ledger["pr"], 123)
        self.assertEqual(ledger["pr_branch"], "feature/my-fix")
        self.assertEqual(ledger["reviewed_head"], "1111111111111111111111111111111111111111")
        self.assertEqual(ledger["review_state"], "CHANGES_REQUESTED")
        self.assertEqual(ledger["reviewer"], "reviewer-user")

        # Two items: 1 review body + 1 inline thread
        self.assertEqual(len(ledger["findings"]), 2)
        self.assertEqual(ledger["findings"][0]["source"], "review_body")
        self.assertEqual(ledger["findings"][1]["source"], "inline_thread")
        self.assertEqual(ledger["findings"][1]["location"], "src/module.py:42")

    def test_extract_inline_findings_rest_groups_replies_under_root(self) -> None:
        raw_rest_comments = [
            {
                "id": 101,
                "path": "src/module.py",
                "line": 42,
                "user": {"login": "reviewer"},
                "body": "Root comment.",
                "in_reply_to_id": None,
            },
            {
                "id": 102,
                "path": "src/module.py",
                "line": 42,
                "user": {"login": "developer"},
                "body": "Reply comment.",
                "in_reply_to_id": 101,
            },
        ]
        findings = frf.extract_inline_findings(raw_rest_comments)
        # Should only emit 1 root finding, with reply grouped inside
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["id"], 101)
        self.assertEqual(findings[0]["body"], "Root comment.")
        self.assertEqual(len(findings[0]["replies"]), 1)
        self.assertEqual(findings[0]["replies"][0]["id"], 102)
        self.assertEqual(findings[0]["replies"][0]["body"], "Reply comment.")

    def test_render_markdown_ledger(self) -> None:
        ledger = frf.build_remediation_ledger(
            self.sample_pr,
            self.sample_reviews,
            self.sample_inline_comments,
            self.sample_issue_comments,
        )
        md = frf.render_markdown_ledger(ledger)
        self.assertIn("# Review Remediation Ledger: example-org/test-repo PR #123", md)
        self.assertIn("Off by one error here.", md)
        self.assertIn("Please fix boundary conditions.", md)
        self.assertIn("src/module.py:42", md)

    def test_latest_review_reduced_correctly_with_subsequent_approval(self) -> None:
        reviews = [
            {
                "id": 1,
                "state": "CHANGES_REQUESTED",
                "commit_id": "1111111111111111111111111111111111111111",
                "user": {"login": "reviewer-user"},
                "body": "Fix issues.",
                "submitted_at": "2026-09-18T05:00:00Z",
            },
            {
                "id": 2,
                "state": "APPROVED",
                "commit_id": "2222222222222222222222222222222222222222",
                "user": {"login": "reviewer-user"},
                "body": "Looks great now!",
                "submitted_at": "2026-09-18T06:00:00Z",
            },
        ]
        pr = dict(self.sample_pr, head={"ref": "feature/my-fix", "sha": "2222222222222222222222222222222222222222"})
        ledger = frf.build_remediation_ledger(pr, reviews, [], [])
        self.assertEqual(ledger["review_state"], "APPROVED")
        self.assertEqual(ledger["reviewed_head"], "2222222222222222222222222222222222222222")

    def test_stale_summary_head_rejected_or_flagged(self) -> None:
        pr = dict(self.sample_pr, head={"ref": "feature/my-fix", "sha": "2222222222222222222222222222222222222222"})
        reviews = [
            {
                "id": 2,
                "state": "CHANGES_REQUESTED",
                "commit_id": "2222222222222222222222222222222222222222",
                "user": {"login": "reviewer-user"},
                "body": "Still issues on new head.",
                "submitted_at": "2026-09-18T06:00:00Z",
            }
        ]
        # Issue comment has stale head 1111...
        issue_comments = [
            {
                "id": 201,
                "user": {"login": "reviewer-user"},
                "body": "<!-- reviewer-summary:devils-advocate:1111111111111111111111111111111111111111 -->\nReview level: DEVILS_ADVOCATE\nVerdict: CHANGES_REQUESTED",
                "created_at": "2026-09-18T05:00:00Z",
            }
        ]
        ledger = frf.build_remediation_ledger(pr, reviews, [], issue_comments)
        # Should bind to the current review commit or live head, NOT the stale summary
        self.assertEqual(ledger["reviewed_head"], "2222222222222222222222222222222222222222")
        self.assertTrue(ledger["summary"]["is_stale"])

    def test_unresolved_primary_threads_filters_replies_and_resolved(self) -> None:
        raw_threads = [
            {
                "id": "thread-resolved",
                "isResolved": True,
                "path": "src/resolved.py",
                "line": 10,
                "comments": {
                    "nodes": [
                        {"id": "c1", "body": "Already fixed.", "author": {"login": "rev"}}
                    ]
                },
            },
            {
                "id": "thread-unresolved",
                "isResolved": False,
                "path": "src/bug.py",
                "line": 20,
                "comments": {
                    "nodes": [
                        {"id": "c2", "body": "Primary finding.", "author": {"login": "rev"}},
                        {"id": "c3", "body": "Reply discussion.", "author": {"login": "dev"}},
                    ]
                },
            },
        ]
        findings = frf.extract_thread_findings(raw_threads)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["id"], "c2")
        self.assertEqual(findings[0]["path"], "src/bug.py")
        self.assertEqual(findings[0]["line"], 20)
        self.assertEqual(findings[0]["body"], "Primary finding.")
        self.assertEqual(len(findings[0]["replies"]), 1)
        self.assertEqual(findings[0]["replies"][0]["id"], "c3")


class TestRemoteFetchContract(unittest.TestCase):
    """Drives fetch_remote_data and main() over a fake gh layer; nothing hits the network."""

    HEAD = "a" * 40
    OLD = "b" * 40

    def pull(self, head=None):
        return {"number": 7, "head": {"sha": head or self.HEAD, "ref": "feature"},
                "base": {"repo": {"full_name": "example-org/example"}}}

    def review(self, rid, state, commit=None, when="2026-01-01T00:00:00Z", body=""):
        return {"id": rid, "state": state, "commit_id": commit or self.HEAD,
                "submitted_at": when, "body": body, "user": {"login": "reviewer"}}

    def fake(self, *, reviews, threads=None, rest=None, graphql_fails=False, head=None):
        calls = []

        def run_json(*args):
            calls.append(args)
            endpoint = args[-1]
            if "graphql" in args:
                if graphql_fails:
                    raise RuntimeError("graphql unavailable")
                nodes = threads or []
                return {"data": {"repository": {"pullRequest": {"reviewThreads": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}}}}}
            if endpoint == "repos/example-org/example/pulls/7":
                return self.pull(head)
            if "/pulls/7/reviews" in endpoint:
                return reviews if "page=1" in endpoint else []
            if "/issues/7/comments" in endpoint:
                return []
            if "/pulls/7/comments" in endpoint:
                return rest if (rest and "page=1" in endpoint) else []
            raise AssertionError(f"unexpected call {args}")

        return run_json, calls

    def test_dismissed_and_pending_reviews_never_govern(self) -> None:
        reviews = [self.review(1, "CHANGES_REQUESTED", when="2026-01-01T00:00:00Z"),
                   self.review(2, "DISMISSED", when="2026-01-02T00:00:00Z"),
                   self.review(3, "PENDING", when="2026-01-03T00:00:00Z")]
        self.assertEqual(frf.select_latest_review(reviews)["id"], 1)
        self.assertEqual(frf.select_latest_review([self.review(4, "DISMISSED")]), {})
        self.assertEqual(frf.select_latest_review([]), {})

    def test_ties_break_on_review_id(self) -> None:
        reviews = [self.review(5, "APPROVED"), self.review(9, "CHANGES_REQUESTED")]
        self.assertEqual(frf.select_latest_review(reviews)["id"], 9)

    def test_review_on_an_older_head_is_flagged_stale(self) -> None:
        run_json, _ = self.fake(reviews=[self.review(1, "CHANGES_REQUESTED", commit=self.OLD)])
        with unittest.mock.patch.object(frf, "run_json", run_json):
            data = frf.fetch_remote_data("example-org/example", 7)
        self.assertTrue(data["review_is_stale"])
        self.assertEqual(data["reviewed_head"], self.OLD)
        self.assertEqual(data["live_head"], self.HEAD)
        self.assertIn("STALE", frf.render_markdown_ledger(data))

    def test_review_on_the_live_head_is_not_stale(self) -> None:
        run_json, _ = self.fake(reviews=[self.review(1, "CHANGES_REQUESTED")])
        with unittest.mock.patch.object(frf, "run_json", run_json):
            data = frf.fetch_remote_data("example-org/example", 7)
        self.assertFalse(data["review_is_stale"])
        self.assertEqual(data["review_state"], "CHANGES_REQUESTED")

    def test_graphql_failure_falls_back_to_rest_comments(self) -> None:
        rest = [{"id": 11, "path": "a.py", "line": 3, "user": {"login": "reviewer"},
                 "body": "fix this", "commit_id": self.HEAD, "pull_request_review_id": 1}]
        run_json, calls = self.fake(reviews=[self.review(1, "CHANGES_REQUESTED")],
                                    rest=rest, graphql_fails=True)
        with unittest.mock.patch.object(frf, "run_json", run_json):
            data = frf.fetch_remote_data("example-org/example", 7)
        self.assertEqual([f["finding"] for f in data["findings"]], ["fix this"])
        self.assertTrue(any("graphql" in c for c in calls))

    def test_resolved_threads_are_excluded_and_open_ones_kept(self) -> None:
        def thread(tid, resolved, body):
            return {"id": tid, "isResolved": resolved, "path": "a.py", "line": 1,
                    "comments": {"nodes": [{"id": tid + "-c", "body": body,
                                            "author": {"login": "reviewer"}, "createdAt": "t"}]}}
        run_json, _ = self.fake(reviews=[self.review(1, "CHANGES_REQUESTED")],
                                threads=[thread("t1", True, "done"), thread("t2", False, "open")])
        with unittest.mock.patch.object(frf, "run_json", run_json):
            data = frf.fetch_remote_data("example-org/example", 7)
        self.assertEqual([f["finding"] for f in data["findings"]], ["open"])

    def test_rest_pagination_walks_every_page(self) -> None:
        pages = {1: [{"id": i} for i in range(100)], 2: [{"id": 100}]}
        seen = []

        def run_json(*args):
            seen.append(args[-1])
            return pages.get(int(args[-1].rsplit("page=", 1)[1]), [])

        with unittest.mock.patch.object(frf, "run_json", run_json):
            items = frf.run_json_paginated("repos/o/r/pulls/1/reviews")
        self.assertEqual(len(items), 101)
        self.assertEqual(len(seen), 2)

    def test_invalid_repository_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid repository"):
            frf.fetch_review_threads_graphql("no-slash", 1)

    def test_main_writes_the_ledger_and_reports_failures_with_status_one(self) -> None:
        import tempfile
        run_json, _ = self.fake(reviews=[self.review(1, "CHANGES_REQUESTED", body="Fix all")])
        with tempfile.TemporaryDirectory() as directory,                 unittest.mock.patch.object(frf, "run_json", run_json):
            out = Path(directory) / "nested" / "ledger.md"
            self.assertEqual(frf.main(["--repo", "example-org/example", "--pr", "7",
                                       "--output", str(out)]), 0)
            self.assertIn("Fix all", out.read_text(encoding="utf-8"))

        def boom(*args):
            raise RuntimeError("no network")

        with unittest.mock.patch.object(frf, "run_json", boom):
            self.assertEqual(frf.main(["--repo", "example-org/example", "--pr", "7"]), 1)

    def test_subprocess_output_is_decoded_as_utf8_on_every_platform(self) -> None:
        import json
        import subprocess
        captured = {}

        def fake_run(args, **kwargs):
            captured.update(kwargs)
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps({"t": "café"}))

        with unittest.mock.patch.object(frf.subprocess, "run", fake_run):
            self.assertEqual(frf.run_json("gh", "api", "x"), {"t": "café"})
        self.assertEqual(captured["encoding"], "utf-8")

    def test_no_project_specific_identifiers_remain_in_the_script(self) -> None:
        source = Path(frf.__file__).read_text(encoding="utf-8").lower()
        for banned in ("score2gp", "tticom", "/home/"):
            self.assertNotIn(banned, source)


class TestVerdictSelection(unittest.TestCase):
    """A comment is discussion, not a verdict. Only an independent reviewer's formal
    APPROVED / CHANGES_REQUESTED can change what is outstanding."""

    HEAD = "a" * 40
    OLD = "b" * 40

    def pr(self, head=None):
        return {"number": 7, "head": {"sha": head or self.HEAD, "ref": "feature"},
                "base": {"repo": {"full_name": "example-org/example"}}, "user": {"login": "Author"}}

    def review(self, rid, state, login, when, body="", commit=None):
        return {"id": rid, "state": state, "commit_id": commit or self.HEAD, "submitted_at": when,
                "body": body, "user": {"login": login}}

    def ledger(self, reviews, head=None):
        return frf.build_remediation_ledger(self.pr(head), reviews, [], [])

    def bodies(self, ledger):
        return [f["finding"] for f in ledger["findings"]]

    BLOCKER = "Blocking: the empty-list case is accepted. Fix and add a regression."

    def test_an_author_comment_cannot_erase_a_body_only_blocker(self) -> None:
        """Reviewer reproduction: blocker only in the formal body, then the author comments."""
        ledger = self.ledger([
            self.review(1, "CHANGES_REQUESTED", "reviewer", "2026-01-01T00:00:00Z", self.BLOCKER),
            self.review(2, "COMMENTED", "author", "2026-01-02T00:00:00Z", "Thanks, investigating"),
        ])
        self.assertEqual(ledger["review_state"], "CHANGES_REQUESTED")
        self.assertEqual(ledger["reviewer"], "reviewer")
        self.assertEqual(self.bodies(ledger), [self.BLOCKER])
        self.assertNotIn("Thanks, investigating", self.bodies(ledger))
        self.assertEqual([b["reviewer"] for b in ledger["blocking_reviews"]], ["reviewer"])

    def test_the_discussion_is_kept_but_separate_from_findings(self) -> None:
        ledger = self.ledger([
            self.review(1, "CHANGES_REQUESTED", "reviewer", "2026-01-01T00:00:00Z", self.BLOCKER),
            self.review(2, "COMMENTED", "author", "2026-01-02T00:00:00Z", "Thanks, investigating"),
        ])
        self.assertEqual([d["body"] for d in ledger["discussion"]], ["Thanks, investigating"])
        markdown = frf.render_markdown_ledger(ledger)
        self.assertIn("Discussion", markdown)
        self.assertIn(self.BLOCKER, markdown)
        finding_section = markdown.split("## Discussion")[0]
        self.assertNotIn("Thanks, investigating", finding_section)

    def test_a_comment_only_review_by_anyone_never_supersedes_a_blocker(self) -> None:
        for commenter in ("author", "reviewer", "another-reviewer"):
            with self.subTest(commenter=commenter):
                ledger = self.ledger([
                    self.review(1, "CHANGES_REQUESTED", "reviewer", "2026-01-01T00:00:00Z", self.BLOCKER),
                    self.review(2, "COMMENTED", commenter, "2026-01-02T00:00:00Z", "a note"),
                ])
                self.assertEqual(ledger["review_state"], "CHANGES_REQUESTED")
                self.assertEqual(self.bodies(ledger), [self.BLOCKER])

    def test_a_genuine_later_approval_by_the_same_reviewer_clears_the_blocker(self) -> None:
        ledger = self.ledger([
            self.review(1, "CHANGES_REQUESTED", "reviewer", "2026-01-01T00:00:00Z", self.BLOCKER),
            self.review(2, "COMMENTED", "author", "2026-01-02T00:00:00Z", "fixed"),
            self.review(3, "APPROVED", "Reviewer", "2026-01-03T00:00:00Z", "Looks good"),
        ])
        self.assertEqual(ledger["review_state"], "APPROVED")
        self.assertEqual(ledger["blocking_reviews"], [])
        self.assertNotIn(self.BLOCKER, self.bodies(ledger))

    def test_a_later_changes_requested_supersedes_an_earlier_approval(self) -> None:
        ledger = self.ledger([
            self.review(1, "APPROVED", "reviewer", "2026-01-01T00:00:00Z", "ok"),
            self.review(2, "CHANGES_REQUESTED", "reviewer", "2026-01-02T00:00:00Z", self.BLOCKER),
        ])
        self.assertEqual(ledger["review_state"], "CHANGES_REQUESTED")
        self.assertEqual(self.bodies(ledger), [self.BLOCKER])

    def test_another_reviewers_approval_does_not_clear_a_reviewers_blocker(self) -> None:
        ledger = self.ledger([
            self.review(1, "CHANGES_REQUESTED", "reviewer-a", "2026-01-01T00:00:00Z", self.BLOCKER),
            self.review(2, "APPROVED", "reviewer-b", "2026-01-02T00:00:00Z", "fine by me"),
        ])
        self.assertEqual(ledger["review_state"], "CHANGES_REQUESTED")
        self.assertEqual(ledger["reviewer"], "reviewer-a")
        self.assertEqual(self.bodies(ledger), [self.BLOCKER])

    def test_every_outstanding_blocker_is_preserved(self) -> None:
        ledger = self.ledger([
            self.review(1, "CHANGES_REQUESTED", "reviewer-a", "2026-01-01T00:00:00Z", "Blocker from A"),
            self.review(2, "CHANGES_REQUESTED", "reviewer-b", "2026-01-02T00:00:00Z", "Blocker from B"),
            self.review(3, "COMMENTED", "author", "2026-01-03T00:00:00Z", "on it"),
        ])
        self.assertEqual(sorted(self.bodies(ledger)), ["Blocker from A", "Blocker from B"])
        self.assertEqual(sorted(b["reviewer"] for b in ledger["blocking_reviews"]), ["reviewer-a", "reviewer-b"])
        self.assertEqual(ledger["reviewer"], "reviewer-b")  # the latest blocker governs the headline

    def test_an_authors_own_review_never_carries_a_verdict(self) -> None:
        ledger = self.ledger([
            self.review(1, "CHANGES_REQUESTED", "reviewer", "2026-01-01T00:00:00Z", self.BLOCKER),
            self.review(2, "APPROVED", "AUTHOR", "2026-01-02T00:00:00Z", "self approval"),
        ])
        self.assertEqual(ledger["review_state"], "CHANGES_REQUESTED")
        self.assertEqual(self.bodies(ledger), [self.BLOCKER])

    def test_a_blocker_on_an_older_head_stays_outstanding_and_is_flagged_stale(self) -> None:
        ledger = self.ledger([
            self.review(1, "CHANGES_REQUESTED", "reviewer", "2026-01-01T00:00:00Z", self.BLOCKER, commit=self.OLD),
            self.review(2, "COMMENTED", "author", "2026-01-02T00:00:00Z", "pushed a fix"),
        ])
        self.assertEqual(ledger["review_state"], "CHANGES_REQUESTED")
        self.assertTrue(ledger["review_is_stale"])
        self.assertEqual(ledger["reviewed_head"], self.OLD)
        self.assertEqual(self.bodies(ledger), [self.BLOCKER])
        self.assertTrue(ledger["blocking_reviews"][0]["stale"])

    def test_dismissed_and_pending_reviews_are_not_blockers(self) -> None:
        ledger = self.ledger([
            self.review(1, "DISMISSED", "reviewer", "2026-01-01T00:00:00Z", "was blocking"),
            self.review(2, "PENDING", "reviewer", "2026-01-02T00:00:00Z", "draft"),
        ])
        self.assertEqual(ledger["blocking_reviews"], [])
        self.assertEqual(ledger["review_state"], "NO_REVIEW")

    def test_comment_only_history_has_no_verdict_and_no_findings_from_it(self) -> None:
        ledger = self.ledger([
            self.review(1, "COMMENTED", "reviewer", "2026-01-01T00:00:00Z", "a question"),
            self.review(2, "COMMENTED", "author", "2026-01-02T00:00:00Z", "an answer"),
        ])
        self.assertEqual(ledger["review_state"], "NO_VERDICT")
        self.assertEqual(ledger["blocking_reviews"], [])
        self.assertEqual(self.bodies(ledger), [])
        self.assertEqual(len(ledger["discussion"]), 2)

    def test_empty_comment_bodies_are_not_discussion(self) -> None:
        ledger = self.ledger([self.review(1, "COMMENTED", "reviewer", "2026-01-01T00:00:00Z", "  ")])
        self.assertEqual(ledger["discussion"], [])

    def test_select_latest_review_ignores_comment_only_records(self) -> None:
        reviews = [
            self.review(1, "CHANGES_REQUESTED", "reviewer", "2026-01-01T00:00:00Z"),
            self.review(2, "COMMENTED", "reviewer", "2026-01-02T00:00:00Z"),
        ]
        self.assertEqual(frf.select_latest_review(reviews)["id"], 1)
        self.assertEqual(frf.select_latest_review([self.review(3, "COMMENTED", "x", "2026-01-01T00:00:00Z")]), {})

    def test_the_marker_summary_and_json_output_carry_the_new_fields(self) -> None:
        ledger = self.ledger([
            self.review(1, "CHANGES_REQUESTED", "reviewer", "2026-01-01T00:00:00Z", self.BLOCKER),
        ])
        self.assertEqual(set(ledger) >= {"blocking_reviews", "discussion", "review_state", "reviewer"}, True)
        self.assertEqual(ledger["blocking_reviews"][0]["id"], 1)


if __name__ == "__main__":
    unittest.main()
