#!/usr/bin/env python3
"""Contract tests for publish_review.py.

GitHub is faked by a *stateful* remote: writes mutate a store and reads are served
from it, so publication is verified by a genuine second read, not by echoing the
write response. Tamper hooks change only what a later GET returns, which is how a
write that "succeeded" but did not persist faithfully is modelled.
"""

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
FIRST_REVIEW_ID = 1001  # FakeGh numbers objects from 1001 in creation order
ISSUE_URL = f"https://api.github.com/repos/{REPO}/issues/{PR}"
POLICY = {"reviewers": ["review-bot", "author-bot"], "never_merge": ["author-bot"]}


def gh_error(*args):
    return subprocess.CalledProcessError(1, list(args), stderr="HTTP 404")


class FakeGh:
    """A stateful remote. Attribute hooks alter only what later reads return."""

    def __init__(self, *, actor="review-bot", author="author-bot", heads=(HEAD,), comments=None,
                 page_size=100):
        self.actor, self.author = actor, author
        self.heads = list(heads)
        self.issue_comments = [dict(c) for c in (comments or [])]
        self.reviews, self.review_comments = {}, {}
        self.next_id = 1000
        self.calls = []
        self.tamper = {}      # name -> function(obj) applied to GET results only
        self.get_fails = set()  # names of GETs that raise like a missing object
        self.page_size = page_size

    # --- request parsing ---------------------------------------------------
    @staticmethod
    def _split(args):
        method = args[args.index("--method") + 1] if "--method" in args else "GET"
        endpoint = args[args.index("--method") + 2] if "--method" in args else args[-1]
        return method, endpoint

    def __call__(self, *args, stdin=None):
        self.calls.append((args, stdin))
        if args == ("gh", "api", "user"):
            return {"login": self.actor}
        method, endpoint = self._split(args)
        path, _, query = endpoint.partition("?")
        params = dict(item.split("=") for item in query.split("&")) if query else {}
        page = int(params.get("page", 1))

        def sliced(items):
            return items[(page - 1) * self.page_size: page * self.page_size]

        def read(name, value):
            if name in self.get_fails:
                raise gh_error(*args)
            return self.tamper.get(name, lambda v: v)(json.loads(json.dumps(value)))

        if method == "GET":
            if path == PULL:
                head = self.heads.pop(0) if len(self.heads) > 1 else self.heads[0]
                return {"head": {"sha": head}, "user": {"login": self.author}}
            if path == f"repos/{REPO}/issues/{PR}/comments":
                return sliced(self.issue_comments)
            if path == f"{PULL}/comments":
                persisted = [c for review_id in sorted(self.review_comments)
                             for c in self.review_comments[review_id]]
                return read("review_comments", sliced(persisted))
            if path.startswith(f"{PULL}/reviews/") and path.endswith("/comments"):
                # GitHub's per-review endpoint omits the location: line,
                # original_line and side come back null (only the legacy position).
                review_id = int(path.split("/")[-2])
                legacy = [{**c, "line": None, "original_line": None, "side": None}
                          for c in self.review_comments.get(review_id, [])]
                return sliced(legacy)
            if path.startswith(f"{PULL}/reviews/"):
                return read("review", self.reviews[int(path.rsplit("/", 1)[1])])
            if path.startswith(f"repos/{REPO}/issues/comments/"):
                comment_id = int(path.rsplit("/", 1)[1])
                found = next(c for c in self.issue_comments if c["id"] == comment_id)
                return read("summary", found)
        if method == "POST" and path == f"{PULL}/reviews":
            self.next_id += 1
            state = "APPROVED" if stdin["event"] == "APPROVE" else "CHANGES_REQUESTED"
            self.reviews[self.next_id] = {
                "id": self.next_id, "commit_id": stdin["commit_id"], "state": state,
                "body": stdin["body"], "user": {"login": self.actor},
            }
            self.review_comments[self.next_id] = [
                {**c, "commit_id": stdin["commit_id"], "original_line": c.get("line"),
                 "pull_request_review_id": self.next_id}
                for c in stdin.get("comments", [])
            ]
            return dict(self.reviews[self.next_id])
        if method == "POST" and path == f"repos/{REPO}/issues/{PR}/comments":
            self.next_id += 1
            comment = {"id": self.next_id, "user": {"login": self.actor}, "body": stdin["body"],
                       "issue_url": ISSUE_URL}
            self.issue_comments.append(comment)
            return dict(comment)
        if method == "PATCH" and path.startswith(f"repos/{REPO}/issues/comments/"):
            comment_id = int(path.rsplit("/", 1)[1])
            found = next(c for c in self.issue_comments if c["id"] == comment_id)
            found["body"] = stdin["body"]
            return dict(found)
        raise AssertionError(f"unexpected gh call: {args}")

    def writes(self, method):
        return [c for c in self.calls if "--method" in c[0] and c[0][c[0].index("--method") + 1] == method]

    def reads(self, needle):
        return [c for c in self.calls if "--method" not in c[0] and needle in c[0][-1]]

    def marked(self, marker_head=HEAD, level="basic", user=None):
        marker = f"<!-- reviewer-summary:{level}:{marker_head} -->"
        return [c for c in self.issue_comments if marker in c["body"]
                and (user is None or c["user"]["login"] == user)]


def body(verdict, head=HEAD):
    return f"Reviewed head: {head}\nVerdict: {verdict}\n"


def summary(verdict, level="basic", head=HEAD):
    return f"<!-- reviewer-summary:{level}:{head} -->\nReviewed head: {head}\nVerdict: {verdict}\n"


def marker_comment(comment_id, user="review-bot", level="basic", head=HEAD, text="old"):
    return {"id": comment_id, "user": {"login": user}, "issue_url": ISSUE_URL,
            "body": f"<!-- reviewer-summary:{level}:{head} -->\n{text}"}


def noise(count, start=1):
    return [{"id": start + i, "user": {"login": "someone"}, "body": f"chatter {i}", "issue_url": ISSUE_URL}
            for i in range(count)]


class Run:
    """One invocation of publish_review.main() with files written to a temp dir."""

    def __init__(self, test, *, verdict="CHANGES_REQUESTED", level="basic", gh=None, head=HEAD,
                 policy=POLICY, extra=(), env_policy=False, inline=None):
        self.dir = Path(tempfile.mkdtemp())
        test.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))
        (self.dir / "review.md").write_text(body(verdict), encoding="utf-8")
        (self.dir / "summary.md").write_text(summary(verdict, level), encoding="utf-8")
        self.gh = gh or FakeGh()
        self.verdict, self.level = verdict, level
        argv = ["publish_review.py", "--repo", REPO, "--pr", str(PR), "--expected-head", head,
                "--level", level, "--verdict", verdict,
                "--review-body-file", str(self.dir / "review.md"),
                "--summary-file", str(self.dir / "summary.md"), *extra]
        if inline is not None:
            path = self.dir / "inline.json"
            path.write_text(json.dumps(inline), encoding="utf-8")
            argv += ["--inline-comments-file", str(path)]
        self.env = {}
        if policy is not None:
            (self.dir / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
            if env_policy:
                self.env = {"AGENTOPS_ROLE_POLICY": str(self.dir / "policy.json")}
            else:
                argv += ["--role-policy", str(self.dir / "policy.json")]
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
    def test_publication_writes_then_reads_back_distinct_objects(self):
        run = Run(self).go()
        self.assertIn("REVIEW_PUBLICATION=PASS", run.output)
        self.assertEqual(len(run.gh.writes("POST")), 2)  # formal review + summary comment
        review_payload = run.gh.writes("POST")[0][1]
        self.assertEqual((review_payload["commit_id"], review_payload["event"]), (HEAD, "REQUEST_CHANGES"))
        # a genuine second read of each persisted object, after the writes
        first_write = min(i for i, c in enumerate(run.gh.calls) if "--method" in c[0])
        read_paths = [c[0][-1] for c in run.gh.calls[first_write:] if "--method" not in c[0]]
        self.assertTrue(any(p.startswith(f"{PULL}/reviews/") and not p.endswith("comments") for p in read_paths))
        self.assertTrue(any(p.startswith(f"repos/{REPO}/issues/comments/") for p in read_paths))

    def test_verdicts_map_to_hosting_events_and_states(self):
        for verdict, event, state in (("APPROVE", "APPROVE", "APPROVED"),
                                      ("CHANGES_REQUESTED", "REQUEST_CHANGES", "CHANGES_REQUESTED"),
                                      ("CANNOT_VERIFY", "REQUEST_CHANGES", "CHANGES_REQUESTED")):
            with self.subTest(verdict=verdict):
                run = Run(self, verdict=verdict).go()
                self.assertEqual(run.gh.writes("POST")[0][1]["event"], event)
                self.assertEqual(next(iter(run.gh.reviews.values()))["state"], state)

    def test_inline_comments_are_attached_and_read_back(self):
        comments = [{"path": "a.py", "line": 3, "side": "RIGHT", "body": "finding one"},
                    {"path": "b.py", "line": 9, "side": "LEFT", "body": "finding two"}]
        run = Run(self, inline=comments).go()
        self.assertEqual(run.gh.writes("POST")[0][1]["comments"], comments)
        self.assertTrue(run.gh.reads(f"{PULL}/comments?per_page=100&page=1"))
        self.assertIn("REVIEW_PUBLICATION=PASS", run.output)

    def test_policy_may_come_from_the_environment(self):
        self.assertIn("REVIEW_PUBLICATION=PASS", Run(self, env_policy=True).go().output)

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
        with self.assertRaisesRegex(SystemExit, "REVIEW_PUBLICATION=FAIL.*self-review"):
            Run(self, gh=gh).go()
        self.assertEqual(gh.writes("POST") + gh.writes("PATCH"), [])

    def test_unlisted_actor_is_denied(self):
        gh = FakeGh(actor="stranger")
        with self.assertRaisesRegex(SystemExit, "not an authorized reviewer"):
            Run(self, gh=gh).go()
        self.assertEqual(gh.writes("POST"), [])

    def test_stale_live_head_publishes_nothing(self):
        gh = FakeGh(heads=(OTHER,))
        with self.assertRaisesRegex(SystemExit, "live head changed before publication"):
            Run(self, gh=gh).go()
        self.assertEqual(gh.writes("POST") + gh.writes("PATCH"), [])

    def test_head_that_moves_during_publication_fails(self):
        gh = FakeGh(heads=(HEAD, OTHER))
        with self.assertRaisesRegex(SystemExit, "live head changed during publication"):
            Run(self, gh=gh).go()

    def test_non_basic_approval_requires_an_evidence_packet(self):
        for level in ("hard", "devils-advocate"):
            with self.subTest(level=level):
                gh = FakeGh()
                with self.assertRaisesRegex(SystemExit, "requires --packet"):
                    Run(self, verdict="APPROVE", level=level, gh=gh).go()
                self.assertEqual(gh.writes("POST"), [])

    def test_non_basic_blocking_verdict_needs_no_packet(self):
        self.assertIn("level=hard", Run(self, verdict="CHANGES_REQUESTED", level="hard").go().output)

    def test_bad_packet_blocks_a_non_basic_approval(self):
        run = Run(self, verdict="APPROVE", level="hard")
        packet = run.dir / "packet.json"
        packet.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
        run.argv += ["--packet", str(packet)]
        with self.assertRaisesRegex(Exception, "schema_version"):
            run.go()
        self.assertEqual(run.gh.writes("POST"), [])

    def test_dry_run_writes_nothing(self):
        run = Run(self, extra=("--dry-run",)).go()
        self.assertIn("DRY_RUN_PASS", run.output)
        self.assertEqual(run.gh.writes("POST") + run.gh.writes("PATCH"), [])

    def test_body_without_the_reviewed_head_is_rejected_before_any_call(self):
        run = Run(self)
        (run.dir / "review.md").write_text("Verdict: CHANGES_REQUESTED\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "exact reviewed head"):
            run.go()
        self.assertEqual(run.gh.calls, [])


class PersistedReadBackTest(unittest.TestCase):
    """A write response is not evidence. Only a later read of the persisted object is."""

    def test_review_that_persisted_with_a_different_commit_fails(self):
        gh = FakeGh()
        gh.tamper["review"] = lambda r: {**r, "commit_id": OTHER}
        with self.assertRaisesRegex(SystemExit, "REVIEW_PUBLICATION=FAIL.*commit"):
            Run(self, gh=gh).go()

    def test_review_that_persisted_with_altered_body_fails(self):
        gh = FakeGh()
        gh.tamper["review"] = lambda r: {**r, "body": "something else entirely"}
        with self.assertRaisesRegex(SystemExit, "REVIEW_PUBLICATION=FAIL.*body"):
            Run(self, gh=gh).go()

    def test_review_that_persisted_with_the_wrong_state_fails(self):
        gh = FakeGh()
        gh.tamper["review"] = lambda r: {**r, "state": "APPROVED"}  # CHANGES_REQUESTED was asked
        with self.assertRaisesRegex(SystemExit, "REVIEW_PUBLICATION=FAIL.*state"):
            Run(self, gh=gh).go()

    def test_review_that_reads_back_with_a_different_id_fails(self):
        gh = FakeGh()
        gh.tamper["review"] = lambda r: {**r, "id": 424242}
        with self.assertRaisesRegex(SystemExit, "REVIEW_PUBLICATION=FAIL.*id"):
            Run(self, gh=gh).go()

    def test_review_that_cannot_be_retrieved_after_creation_fails(self):
        gh = FakeGh()
        gh.get_fails.add("review")
        with self.assertRaisesRegex(SystemExit, "REVIEW_PUBLICATION=FAIL.*cannot re-read"):
            Run(self, gh=gh).go()

    def test_the_failure_names_the_review_that_was_created(self):
        gh = FakeGh()
        gh.tamper["review"] = lambda r: {**r, "commit_id": OTHER}
        with self.assertRaisesRegex(SystemExit, r"review_id=1001"):
            Run(self, gh=gh).go()

    def test_inline_comments_that_did_not_persist_fail(self):
        comments = [{"path": "a.py", "line": 3, "side": "RIGHT", "body": "finding"}]
        for label, tamper in (
            ("missing", lambda items: []),
            ("altered", lambda items: [{**items[0], "body": "different"}]),
            ("moved", lambda items: [{**items[0], "path": "other.py"}]),
            ("extra", lambda items: items + [{"path": "z.py", "line": 1, "side": "RIGHT", "body": "surprise",
                                              "pull_request_review_id": FIRST_REVIEW_ID}]),
        ):
            with self.subTest(label=label):
                gh = FakeGh()
                gh.tamper["review_comments"] = tamper
                with self.assertRaisesRegex(SystemExit, "REVIEW_PUBLICATION=FAIL.*inline"):
                    Run(self, gh=gh, inline=comments).go()

    def test_summary_that_persisted_altered_fails(self):
        gh = FakeGh()
        gh.tamper["summary"] = lambda c: {**c, "body": "no marker and no verdict"}
        with self.assertRaisesRegex(SystemExit, "REVIEW_PUBLICATION=FAIL.*summary"):
            Run(self, gh=gh).go()

    def test_summary_that_cannot_be_retrieved_after_creation_fails(self):
        gh = FakeGh()
        gh.get_fails.add("summary")
        with self.assertRaisesRegex(SystemExit, "REVIEW_PUBLICATION=FAIL.*cannot re-read"):
            Run(self, gh=gh).go()

    def test_summary_authored_by_someone_else_fails(self):
        gh = FakeGh()
        gh.tamper["summary"] = lambda c: {**c, "user": {"login": "impostor"}}
        with self.assertRaisesRegex(SystemExit, "REVIEW_PUBLICATION=FAIL.*author"):
            Run(self, gh=gh).go()

    def test_summary_on_a_different_pull_request_fails(self):
        gh = FakeGh()
        gh.tamper["summary"] = lambda c: {**c, "issue_url": ISSUE_URL.replace(str(PR), "999")}
        with self.assertRaisesRegex(SystemExit, "REVIEW_PUBLICATION=FAIL.*pull request"):
            Run(self, gh=gh).go()

    def test_line_endings_and_trailing_whitespace_do_not_cause_false_failures(self):
        gh = FakeGh()
        gh.tamper["review"] = lambda r: {**r, "body": r["body"].replace("\n", "\r\n") + "\n\n"}
        gh.tamper["summary"] = lambda c: {**c, "body": c["body"].replace("\n", "\r\n") + "  "}
        self.assertIn("REVIEW_PUBLICATION=PASS", Run(self, gh=gh).go().output)

    def test_two_marked_summaries_after_publication_are_reported(self):
        gh = FakeGh(comments=[marker_comment(1, text="dup-a")])
        original_call = gh.__call__

        def duplicating(*args, stdin=None):
            result = original_call(*args, stdin=stdin)
            if "PATCH" in args:  # a second marked comment appears concurrently
                gh.issue_comments.append(marker_comment(9999, text="dup-b"))
            return result

        gh_call = duplicating
        run = Run(self, gh=gh)
        with patch.object(publish_review, "run_json", side_effect=gh_call), patch.object(sys, "argv", run.argv), \
                patch.dict(os.environ, {k: v for k, v in os.environ.items() if k != "AGENTOPS_ROLE_POLICY"}), \
                patch("sys.stdout", new_callable=io.StringIO):
            with self.assertRaisesRegex(SystemExit, "REVIEW_PUBLICATION=FAIL.*more than one"):
                main()


class IdempotenceAcrossPagesTest(unittest.TestCase):
    """The existing marked summary must be found wherever it sits in the comment list."""

    def test_marker_beyond_the_first_page_is_updated_not_duplicated(self):
        comments = noise(205) + [marker_comment(50_000)] + noise(10, start=60_000)
        gh = FakeGh(comments=comments)
        run = Run(self, gh=gh).go()
        patches = gh.writes("PATCH")
        self.assertEqual(len(patches), 1)
        self.assertIn("issues/comments/50000", str(patches[0][0]))
        created = [c for c in gh.writes("POST") if any(f"issues/{PR}/comments" in p for p in c[0])]
        self.assertEqual(created, [], "a second marked comment was posted instead of updating")
        self.assertEqual(len(gh.marked(user="review-bot")), 1)
        self.assertIn("comment_id=50000", run.output)

    def test_every_page_is_requested_up_to_the_last(self):
        gh = FakeGh(comments=noise(250) + [marker_comment(50_000)])
        Run(self, gh=gh).go()
        pages = [c[0][-1] for c in gh.calls if "--method" not in c[0] and c[0][-1].startswith(f"repos/{REPO}/issues/{PR}/comments")]
        self.assertTrue(any("page=3" in p for p in pages) and any("page=1" in p for p in pages))

    def test_a_full_last_page_is_followed_by_one_more_request(self):
        """Exactly 100 comments: page 2 must still be asked for and come back empty."""
        gh = FakeGh(comments=noise(99) + [marker_comment(50_000)])
        Run(self, gh=gh).go()
        self.assertEqual(len(gh.writes("PATCH")), 1)
        pages = [c[0][-1] for c in gh.calls if "--method" not in c[0] and "page=" in c[0][-1] and "issues" in c[0][-1] and "comments?" in c[0][-1]]
        self.assertTrue(any("page=2" in p for p in pages))

    def test_a_marker_from_another_user_is_never_reused_even_across_pages(self):
        comments = noise(150) + [marker_comment(50_000, user="someone-else")]
        gh = FakeGh(comments=comments)
        Run(self, gh=gh).go()
        self.assertEqual(gh.writes("PATCH"), [])
        self.assertEqual(len(gh.marked(user="review-bot")), 1)
        self.assertEqual(len(gh.marked(user="someone-else")), 1)

    def test_a_marker_for_a_different_head_or_level_is_not_reused(self):
        comments = [marker_comment(1, head=OTHER), marker_comment(2, level="hard")]
        gh = FakeGh(comments=comments)
        Run(self, gh=gh).go()
        self.assertEqual(gh.writes("PATCH"), [])

    def test_a_malformed_comment_page_fails_closed(self):
        gh = FakeGh()
        original = gh.__call__

        def broken(*args, stdin=None):
            if "--method" not in args and args[-1].startswith(f"repos/{REPO}/issues/{PR}/comments"):
                return {"message": "rate limited"}
            return original(*args, stdin=stdin)

        run = Run(self, gh=gh)
        with patch.object(publish_review, "run_json", side_effect=broken), patch.object(sys, "argv", run.argv), \
                patch.dict(os.environ, {k: v for k, v in os.environ.items() if k != "AGENTOPS_ROLE_POLICY"}), \
                patch("sys.stdout", new_callable=io.StringIO):
            with self.assertRaisesRegex(SystemExit, "REVIEW_PUBLICATION=FAIL"):
                main()


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


class InlineReadBackCompletenessTest(unittest.TestCase):
    """The persisted inline collection is always checked, exactly, with real location data."""

    COMMENT = {"path": "a.py", "line": 3, "side": "RIGHT", "body": "finding"}

    def publish(self, tamper=None, inline=None):
        gh = FakeGh()
        if tamper is not None:
            gh.tamper["review_comments"] = tamper
        return gh, Run(self, gh=gh, inline=[self.COMMENT] if inline is None else inline)

    def test_missing_line_and_original_line_is_not_a_wildcard(self):
        """Reviewer reproduction: a persisted object with only path and body."""
        for label, tamper in (
            ("no location at all", lambda items: [{"path": i["path"], "body": i["body"]} for i in items]),
            ("no line", lambda items: [{k: v for k, v in i.items() if k not in ("line", "original_line")} for i in items]),
            ("null line and original_line", lambda items: [{**i, "line": None, "original_line": None} for i in items]),
            ("no side", lambda items: [{k: v for k, v in i.items() if k != "side"} for i in items]),
            ("null side", lambda items: [{**i, "side": None} for i in items]),
            ("no commit", lambda items: [{k: v for k, v in i.items() if k != "commit_id"} for i in items]),
        ):
            with self.subTest(label=label):
                gh, run = self.publish(tamper)
                with self.assertRaisesRegex(SystemExit, "REVIEW_PUBLICATION=FAIL.*inline"):
                    run.go()

    def test_wrong_location_data_still_fails(self):
        for label, tamper in (
            ("wrong line", lambda items: [{**i, "line": 4} for i in items]),
            ("wrong original_line", lambda items: [{**i, "line": None, "original_line": 4} for i in items]),
            ("wrong side", lambda items: [{**i, "side": "LEFT"} for i in items]),
            ("wrong commit", lambda items: [{**i, "commit_id": OTHER} for i in items]),
            ("wrong path", lambda items: [{**i, "path": "b.py"} for i in items]),
            ("line is not a number", lambda items: [{**i, "line": "3"} for i in items]),
        ):
            with self.subTest(label=label):
                gh, run = self.publish(tamper)
                with self.assertRaisesRegex(SystemExit, "REVIEW_PUBLICATION=FAIL.*inline"):
                    run.go()

    def test_exact_location_is_accepted_including_the_original_line_fallback(self):
        for label, tamper in (
            ("as returned", None),
            ("extra fields", lambda items: [{**i, "id": 9, "start_line": None, "diff_hunk": "@@"} for i in items]),
            ("outdated comment: line null, original_line set",
             lambda items: [{**i, "line": None, "original_line": 3} for i in items]),
        ):
            with self.subTest(label=label):
                gh, run = self.publish(tamper)
                self.assertIn("REVIEW_PUBLICATION=PASS", run.go().output)

    def test_the_collection_is_fetched_even_when_no_inline_comments_were_expected(self):
        gh, run = self.publish(inline=[])
        run.go()
        self.assertTrue(gh.reads(f"{PULL}/comments?"), "the inline endpoint was never queried")

    def test_an_unexpected_persisted_comment_fails_when_none_were_submitted(self):
        """Reviewer reproduction: zero expected, one remote."""
        extra = {"path": "z.py", "line": 1, "side": "RIGHT", "body": "surprise", "commit_id": HEAD,
                 "pull_request_review_id": FIRST_REVIEW_ID}
        gh, run = self.publish(lambda items: items + [extra], inline=[])
        with self.assertRaisesRegex(SystemExit, "REVIEW_PUBLICATION=FAIL.*inline"):
            run.go()

    def test_location_is_read_from_the_pull_request_comment_list(self):
        """Reviewer reproduction: reviews/{id}/comments returns line and side as null."""
        gh, run = self.publish()
        self.assertIn("REVIEW_PUBLICATION=PASS", run.go().output)
        self.assertTrue(gh.reads(f"{PULL}/comments?"))
        self.assertFalse(gh.reads(f"/reviews/{FIRST_REVIEW_ID}/comments"),
                         "the per-review endpoint cannot prove a location")

    def test_comments_from_other_reviews_are_not_counted(self):
        other = {"path": "z.py", "line": 1, "side": "RIGHT", "body": "earlier review", "commit_id": OTHER,
                 "pull_request_review_id": FIRST_REVIEW_ID - 1}
        for inline in ([], [self.COMMENT]):
            with self.subTest(inline=inline):
                gh, run = self.publish(lambda items: [other] + items, inline=inline)
                self.assertIn("REVIEW_PUBLICATION=PASS", run.go().output)

    def test_zero_expected_and_zero_persisted_passes(self):
        gh, run = self.publish(inline=[])
        self.assertIn("REVIEW_PUBLICATION=PASS", run.go().output)

    def test_cardinality_must_match_exactly_in_both_directions(self):
        two = [self.COMMENT, {"path": "b.py", "line": 9, "side": "LEFT", "body": "second"}]
        for label, tamper, inline in (
            ("one missing", lambda items: items[:1], two),
            ("one extra", lambda items: items + [{**items[0], "body": "extra"}], [self.COMMENT]),
            ("duplicate of one, other missing", lambda items: [items[0], items[0]], two),
        ):
            with self.subTest(label=label):
                gh, run = self.publish(tamper, inline)
                with self.assertRaisesRegex(SystemExit, "REVIEW_PUBLICATION=FAIL.*inline"):
                    run.go()

    def test_an_unretrievable_inline_collection_fails_even_with_none_expected(self):
        gh, run = self.publish(inline=[])
        original = gh.__call__

        def failing(*args, stdin=None):
            if "--method" not in args and args[-1].startswith(f"{PULL}/comments?"):
                raise subprocess.CalledProcessError(1, list(args), stderr="HTTP 502")
            return original(*args, stdin=stdin)

        with patch.object(publish_review, "run_json", side_effect=failing), patch.object(sys, "argv", run.argv), \
                patch.dict(os.environ, {k: v for k, v in os.environ.items() if k != "AGENTOPS_ROLE_POLICY"}), \
                patch("sys.stdout", new_callable=io.StringIO):
            with self.assertRaisesRegex(SystemExit, "REVIEW_PUBLICATION=FAIL.*cannot re-read"):
                main()

    def test_paginated_inline_collections_are_read_completely(self):
        many = [{"path": f"f{n}.py", "line": n + 1, "side": "RIGHT", "body": f"finding {n}"} for n in range(105)]
        gh, run = self.publish(inline=many)
        self.assertIn("REVIEW_PUBLICATION=PASS", run.go().output)
        pages = [c[0][-1] for c in gh.calls if "--method" not in c[0] and c[0][-1].startswith(f"{PULL}/comments?")]
        self.assertTrue(any("page=2" in p for p in pages))


class MalformedRemoteElementTest(unittest.TestCase):
    """A null (or any non-object) element inside a valid list is a failure, not noise."""

    COMMENT = {"path": "a.py", "line": 3, "side": "RIGHT", "body": "finding"}

    def run_with(self, tamper, inline):
        gh = FakeGh()
        gh.tamper["review_comments"] = tamper
        return Run(self, gh=gh, inline=inline)

    def test_zero_expected_and_a_null_remote_element_fails(self):
        """Reviewer reproduction: [null] must not become [] and pass."""
        run = self.run_with(lambda items: items + [None], inline=[])
        with self.assertRaisesRegex(SystemExit, "REVIEW_PUBLICATION=FAIL.*not an object"):
            run.go()

    def test_one_valid_expected_plus_a_null_extra_element_fails(self):
        """Reviewer reproduction: [valid, null] must not collapse to one item and pass."""
        run = self.run_with(lambda items: items + [None], inline=[self.COMMENT])
        with self.assertRaisesRegex(SystemExit, "REVIEW_PUBLICATION=FAIL.*not an object"):
            run.go()

    def test_every_kind_of_non_object_element_fails(self):
        for bad in (None, "text", 7, [], True):
            with self.subTest(bad=bad):
                run = self.run_with(lambda items, b=bad: items + [b], inline=[self.COMMENT])
                with self.assertRaisesRegex(SystemExit, "REVIEW_PUBLICATION=FAIL.*not an object"):
                    run.go()

    def test_a_malformed_issue_comment_element_fails_before_any_write_is_trusted(self):
        gh = FakeGh(comments=noise(3))
        original = gh.__call__

        def poisoned(*args, stdin=None):
            result = original(*args, stdin=stdin)
            if "--method" not in args and args[-1].startswith(f"repos/{REPO}/issues/{PR}/comments"):
                return list(result) + [None]
            return result

        run = Run(self, gh=gh)
        with patch.object(publish_review, "run_json", side_effect=poisoned), patch.object(sys, "argv", run.argv), \
                patch.dict(os.environ, {k: v for k, v in os.environ.items() if k != "AGENTOPS_ROLE_POLICY"}), \
                patch("sys.stdout", new_callable=io.StringIO):
            with self.assertRaisesRegex(SystemExit, "REVIEW_PUBLICATION=FAIL.*not an object"):
                main()

    def test_well_formed_collections_still_pass(self):
        for inline in ([], [self.COMMENT]):
            with self.subTest(inline=inline):
                run = self.run_with(lambda items: items, inline=inline)
                self.assertIn("REVIEW_PUBLICATION=PASS", run.go().output)


if __name__ == "__main__":
    unittest.main()
