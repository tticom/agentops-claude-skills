#!/usr/bin/env python3
"""Contract tests for publish_review.py. GitHub is faked; nothing touches the network."""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import publish_review
from publish_review import load_inline_comments, main, validate_publication_text

HEAD = "a" * 40
OTHER = "b" * 40
REPO = "example-org/example"
PR = 514
PULL = f"repos/{REPO}/pulls/{PR}"
POLICY = {"reviewers": ["review-bot", "author-bot"], "never_merge": ["author-bot"]}


class FakeGh:
    """Stands in for publish_review.run_json and records every gh call."""

    def __init__(self, *, actor="review-bot", author="author-bot", heads=(HEAD,),
                 comments=None, review_commit=HEAD, summary_text=""):
        self.actor, self.author = actor, author
        self.heads, self.comments = list(heads), comments or []
        self.review_commit, self.summary_text = review_commit, summary_text
        self.calls = []

    def __call__(self, *args, stdin=None):
        self.calls.append((args, stdin))
        if args == ("gh", "api", "user"):
            return {"login": self.actor}
        endpoint = args[-1]
        if endpoint == PULL:
            head = self.heads.pop(0) if len(self.heads) > 1 else self.heads[0]
            return {"head": {"sha": head}, "user": {"login": self.author}}
        if endpoint.endswith("comments?per_page=100"):
            return self.comments
        if "POST" in args and any("/reviews" in item for item in args):
            return {"id": 10, "commit_id": self.review_commit}
        if "PATCH" in args:
            return {"id": 99, "body": self.summary_text}
        if "POST" in args and any("issues/" in item for item in args):
            return {"id": 20, "body": self.summary_text}
        raise AssertionError(f"unexpected gh call: {args}")

    def posted(self, needle):
        return [c for c in self.calls if any(needle in str(part) for part in c[0])]


def body(verdict, head=HEAD):
    return f"Reviewed head: {head}\nVerdict: {verdict}\n"


def summary(verdict, level="basic", head=HEAD):
    return f"<!-- reviewer-summary:{level}:{head} -->\nReviewed head: {head}\nVerdict: {verdict}\n"


class Run:
    """One invocation of publish_review.main() with files written to a temp dir."""

    def __init__(self, test, *, verdict="CHANGES_REQUESTED", level="basic", gh=None,
                 head=HEAD, policy=POLICY, extra=(), env_policy=False):
        self.dir = Path(tempfile.mkdtemp())
        test.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))
        (self.dir / "review.md").write_text(body(verdict), encoding="utf-8")
        (self.dir / "summary.md").write_text(summary(verdict, level), encoding="utf-8")
        self.gh = gh or FakeGh(summary_text=summary(verdict, level))
        argv = ["publish_review.py", "--repo", REPO, "--pr", str(PR), "--expected-head", head,
                "--level", level, "--verdict", verdict,
                "--review-body-file", str(self.dir / "review.md"),
                "--summary-file", str(self.dir / "summary.md"), *extra]
        if policy is not None:
            (self.dir / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
            if env_policy:
                self.env = {"AGENTOPS_ROLE_POLICY": str(self.dir / "policy.json")}
            else:
                argv += ["--role-policy", str(self.dir / "policy.json")]
                self.env = {}
        else:
            self.env = {}
        self.argv = argv
        self.output = ""

    def go(self):
        clean = {k: v for k, v in os.environ.items() if k != "AGENTOPS_ROLE_POLICY"}
        clean.update(self.env)
        with patch.object(publish_review, "run_json", side_effect=self.gh), \
             patch.object(sys, "argv", self.argv), \
             patch.dict(os.environ, clean, clear=True), \
             patch("sys.stdout", new_callable=io.StringIO) as out:
            try:
                main()
            finally:
                self.output = out.getvalue()
        return self


class PublicationTextTest(unittest.TestCase):
    def test_summary_and_review_must_bind_exact_head(self):
        marker = validate_publication_text(
            level="hard", verdict="APPROVE", expected_head=HEAD,
            review_body=body("APPROVE"), summary=summary("APPROVE", "hard"),
        )
        self.assertEqual(marker, f"<!-- reviewer-summary:hard:{HEAD} -->")
        with self.assertRaisesRegex(ValueError, "exact reviewed head"):
            validate_publication_text(
                level="hard", verdict="APPROVE", expected_head=HEAD,
                review_body="stale", summary=summary("APPROVE", "hard"),
            )
        with self.assertRaisesRegex(ValueError, "missing marker"):
            validate_publication_text(
                level="hard", verdict="APPROVE", expected_head=HEAD,
                review_body=body("APPROVE"), summary=summary("APPROVE", "hard", OTHER),
            )

    def test_verdict_must_match_body_and_summary(self):
        with self.assertRaisesRegex(ValueError, "exact verdict"):
            validate_publication_text(
                level="basic", verdict="CHANGES_REQUESTED", expected_head=HEAD,
                review_body=body("APPROVE"), summary=summary("CHANGES_REQUESTED"),
            )
        with self.assertRaisesRegex(ValueError, "summary must contain the exact verdict"):
            validate_publication_text(
                level="basic", verdict="CHANGES_REQUESTED", expected_head=HEAD,
                review_body=body("CHANGES_REQUESTED"), summary=summary("APPROVE"),
            )

    def test_unknown_level_and_verdict_are_rejected(self):
        for level, verdict, message in (
            ("expert", "APPROVE", "unsupported review level"),
            ("basic", "LGTM", "unsupported verdict"),
        ):
            with self.subTest(level=level), self.assertRaisesRegex(ValueError, message):
                validate_publication_text(
                    level=level, verdict=verdict, expected_head=HEAD,
                    review_body=body(verdict), summary=summary(verdict, level),
                )

    def test_inline_comment_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "comments.json"
            path.write_text(json.dumps([
                {"path": "src/x.py", "line": 12, "side": "RIGHT", "body": "finding"}
            ]), encoding="utf-8")
            self.assertEqual(load_inline_comments(path)[0]["line"], 12)
            for bad, message in (
                ([{"path": "src/x.py"}], "lacks"),
                ([{"path": "a", "line": 1, "side": "MIDDLE", "body": "x"}], "invalid side"),
                ({"path": "a"}, "JSON list"),
                (["text"], "must be an object"),
            ):
                with self.subTest(bad=bad):
                    path.write_text(json.dumps(bad), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, message):
                        load_inline_comments(path)
        self.assertEqual(load_inline_comments(None), [])


class PublicationFlowTest(unittest.TestCase):
    def test_publication_posts_formal_review_and_summary_and_reads_back(self):
        run = Run(self).go()
        self.assertIn("REVIEW_PUBLICATION=PASS", run.output)
        self.assertEqual(len(run.gh.posted("/reviews")), 1)
        self.assertEqual(len(run.gh.posted("issues/514/comments")), 2)  # list + create
        review_payload = run.gh.posted("/reviews")[0][1]
        self.assertEqual(review_payload["commit_id"], HEAD)
        self.assertEqual(review_payload["event"], "REQUEST_CHANGES")

    def test_verdicts_map_to_hosting_events(self):
        for verdict, event in (("APPROVE", "APPROVE"), ("CHANGES_REQUESTED", "REQUEST_CHANGES"),
                               ("CANNOT_VERIFY", "REQUEST_CHANGES")):
            with self.subTest(verdict=verdict):
                if verdict == "APPROVE":
                    # basic approval needs no evidence packet
                    run = Run(self, verdict=verdict).go()
                else:
                    run = Run(self, verdict=verdict).go()
                self.assertEqual(run.gh.posted("/reviews")[0][1]["event"], event)

    def test_inline_comments_are_attached_to_the_formal_review(self):
        comments = [{"path": "a.py", "line": 3, "side": "RIGHT", "body": "finding"}]
        run = Run(self)
        path = run.dir / "inline.json"
        path.write_text(json.dumps(comments), encoding="utf-8")
        run.argv += ["--inline-comments-file", str(path)]
        run.go()
        self.assertEqual(run.gh.posted("/reviews")[0][1]["comments"], comments)

    def test_policy_may_come_from_the_environment(self):
        run = Run(self, env_policy=True).go()
        self.assertIn("REVIEW_PUBLICATION=PASS", run.output)

    def test_missing_policy_fails_closed_before_any_network_call(self):
        run = Run(self, policy=None)
        with self.assertRaisesRegex(SystemExit, "REVIEW_PUBLICATION=FAIL.*role policy is required"):
            run.go()
        self.assertEqual(run.gh.calls, [])

    def test_malformed_policy_fails_closed(self):
        run = Run(self, policy={"reviewers": "review-bot"})
        with self.assertRaisesRegex(SystemExit, "invalid policy"):
            run.go()
        self.assertEqual(run.gh.calls, [])

    def test_self_review_is_denied_without_any_write(self):
        gh = FakeGh(actor="author-bot", author="author-bot")
        run = Run(self, gh=gh)
        with self.assertRaisesRegex(SystemExit, "REVIEW_PUBLICATION=FAIL.*self-review"):
            run.go()
        self.assertEqual(gh.posted("/reviews"), [])
        self.assertEqual([c for c in gh.calls if "POST" in c[0] or "PATCH" in c[0]], [])

    def test_unlisted_actor_is_denied(self):
        gh = FakeGh(actor="stranger")
        with self.assertRaisesRegex(SystemExit, "not an authorized reviewer"):
            Run(self, gh=gh).go()
        self.assertEqual([c for c in gh.calls if "POST" in c[0]], [])

    def test_stale_live_head_publishes_nothing(self):
        gh = FakeGh(heads=(OTHER,))
        with self.assertRaisesRegex(SystemExit, "live head changed before publication"):
            Run(self, gh=gh).go()
        self.assertEqual([c for c in gh.calls if "POST" in c[0] or "PATCH" in c[0]], [])

    def test_head_that_moves_during_publication_fails(self):
        gh = FakeGh(heads=(HEAD, OTHER), summary_text=summary("CHANGES_REQUESTED"))
        with self.assertRaisesRegex(SystemExit, "live head changed during publication"):
            Run(self, gh=gh).go()

    def test_readback_commit_mismatch_fails(self):
        gh = FakeGh(review_commit=OTHER, summary_text=summary("CHANGES_REQUESTED"))
        with self.assertRaisesRegex(SystemExit, "remote publication proof mismatch"):
            Run(self, gh=gh).go()

    def test_readback_without_marker_fails(self):
        gh = FakeGh(summary_text="no marker here")
        with self.assertRaisesRegex(SystemExit, "remote publication proof mismatch"):
            Run(self, gh=gh).go()

    def test_existing_marked_summary_is_updated_not_duplicated(self):
        marker = f"<!-- reviewer-summary:basic:{HEAD} -->"
        comments = [{"id": 77, "user": {"login": "Review-Bot"}, "body": marker + " old"}]
        gh = FakeGh(comments=comments, summary_text=summary("CHANGES_REQUESTED"))
        run = Run(self, gh=gh).go()
        self.assertEqual(len(gh.posted("PATCH")), 1)
        self.assertIn("issues/comments/77", str(gh.posted("PATCH")[0][0]))
        creates = [c for c in gh.calls if "POST" in c[0] and any("issues/514/comments" in p for p in c[0])]
        self.assertEqual(creates, [])
        self.assertIn("comment_id=99", run.output)

    def test_a_marker_from_another_user_is_not_reused(self):
        marker = f"<!-- reviewer-summary:basic:{HEAD} -->"
        comments = [{"id": 77, "user": {"login": "someone-else"}, "body": marker}]
        gh = FakeGh(comments=comments, summary_text=summary("CHANGES_REQUESTED"))
        Run(self, gh=gh).go()
        self.assertEqual(gh.posted("PATCH"), [])

    def test_non_basic_approval_requires_an_evidence_packet(self):
        for level in ("hard", "devils-advocate"):
            with self.subTest(level=level):
                gh = FakeGh(summary_text=summary("APPROVE", level))
                with self.assertRaisesRegex(SystemExit, "requires --packet"):
                    Run(self, verdict="APPROVE", level=level, gh=gh).go()
                self.assertEqual(gh.posted("/reviews"), [])

    def test_non_basic_blocking_verdict_needs_no_packet(self):
        run = Run(self, verdict="CHANGES_REQUESTED", level="hard").go()
        self.assertIn("level=hard", run.output)

    def test_bad_packet_blocks_a_non_basic_approval(self):
        run = Run(self, verdict="APPROVE", level="hard")
        packet = run.dir / "packet.json"
        packet.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
        run.argv += ["--packet", str(packet)]
        with self.assertRaisesRegex(Exception, "schema_version"):
            run.go()
        self.assertEqual(run.gh.posted("/reviews"), [])

    def test_dry_run_writes_nothing(self):
        run = Run(self, extra=("--dry-run",)).go()
        self.assertIn("DRY_RUN_PASS", run.output)
        self.assertEqual([c for c in run.gh.calls if "POST" in c[0] or "PATCH" in c[0]], [])

    def test_body_without_the_reviewed_head_is_rejected_before_any_call(self):
        run = Run(self)
        (run.dir / "review.md").write_text("Verdict: CHANGES_REQUESTED\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "exact reviewed head"):
            run.go()
        self.assertEqual(run.gh.calls, [])


class SubprocessEncodingTest(unittest.TestCase):
    def test_gh_output_and_input_are_decoded_as_utf8_on_every_platform(self):
        captured = {}

        def fake_run(args, **kwargs):
            captured.update(kwargs)
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps({"text": "café ✓"}))

        with patch.object(publish_review.subprocess, "run", side_effect=fake_run):
            result = publish_review.run_json("gh", "api", "x", stdin={"body": "café"})
        self.assertEqual(result, {"text": "café ✓"})
        self.assertEqual(captured["encoding"], "utf-8")
        self.assertTrue(captured["text"])


if __name__ == "__main__":
    unittest.main()
