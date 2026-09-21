#!/usr/bin/env python3
"""The shared publication helpers: pagination, strict reads, comment verification."""

import subprocess
import unittest

import gh_publication as gp

ISSUE = "https://api.github.com/repos/o/r/issues/7"


def comment(comment_id, login="bot", body="", issue_url=ISSUE):
    return {"id": comment_id, "user": {"login": login}, "body": body, "issue_url": issue_url}


class PaginateTest(unittest.TestCase):
    def source(self, total):
        requested = []

        def run_json(*args):
            endpoint = args[-1]
            requested.append(endpoint)
            page = int(endpoint.rsplit("page=", 1)[1])
            items = [{"id": n} for n in range(total)]
            return items[(page - 1) * gp.PAGE_SIZE: page * gp.PAGE_SIZE]

        return run_json, requested

    def test_lengths_around_every_page_boundary_are_read_completely(self):
        for total in (0, 1, 99, 100, 101, 199, 200, 201, 250, 300):
            with self.subTest(total=total):
                run_json, requested = self.source(total)
                self.assertEqual(len(gp.paginate(run_json, "repos/o/r/x", "items")), total)
                expected_requests = total // gp.PAGE_SIZE + 1
                self.assertEqual(len(requested), expected_requests)

    def test_a_full_page_always_triggers_one_more_request(self):
        run_json, requested = self.source(100)
        gp.paginate(run_json, "repos/o/r/x", "items")
        self.assertTrue(requested[-1].endswith("page=2"))

    def test_query_string_is_appended_correctly(self):
        run_json, requested = self.source(1)
        gp.paginate(run_json, "repos/o/r/x", "items")
        gp.paginate(run_json, "repos/o/r/x?state=all", "items")
        self.assertEqual(requested[0], "repos/o/r/x?per_page=100&page=1")
        self.assertEqual(requested[1], "repos/o/r/x?state=all&per_page=100&page=1")

    def test_a_non_list_page_is_an_error_not_an_empty_result(self):
        for bad in ({"message": "rate limited"}, None, "text"):
            with self.subTest(bad=bad), self.assertRaisesRegex(gp.PublicationError, "was not a list"):
                gp.paginate(lambda *a: bad, "repos/o/r/x", "items")

    def test_a_failing_request_is_reported_with_what_was_being_read(self):
        def boom(*args):
            raise subprocess.CalledProcessError(1, list(args), stderr="HTTP 502")

        with self.assertRaisesRegex(gp.PublicationError, "cannot re-read issue comments"):
            gp.paginate(boom, "repos/o/r/x", "issue comments")

    def test_invalid_json_is_a_publication_error(self):
        def bad_json(*args):
            raise ValueError("Expecting value")

        with self.assertRaisesRegex(gp.PublicationError, "cannot re-read"):
            gp.fetch(bad_json, "repos/o/r/x", "thing")

    def test_a_list_that_never_ends_is_refused_not_guessed(self):
        with self.assertRaisesRegex(gp.PublicationError, "exceeded"):
            gp.paginate(lambda *a: [{"id": 1}] * gp.PAGE_SIZE, "repos/o/r/x", "items")

    def test_non_object_items_are_dropped_from_a_page(self):
        pages = {1: [{"id": 1}, "junk", None, 3], 2: []}
        got = gp.paginate(lambda *a: pages[int(a[-1].rsplit("page=", 1)[1])] if len(pages[1]) >= 0 else [],
                          "repos/o/r/x", "items")
        self.assertEqual(got, [{"id": 1}])

    def test_fetch_object_requires_an_object(self):
        self.assertEqual(gp.fetch_object(lambda *a: {"id": 1}, "e", "thing"), {"id": 1})
        with self.assertRaisesRegex(gp.PublicationError, "did not return an object"):
            gp.fetch_object(lambda *a: [1], "e", "thing")


class TextTest(unittest.TestCase):
    def test_only_line_endings_and_outer_whitespace_are_ignored(self):
        self.assertTrue(gp.same_text("a\nb", "a\r\nb\n\n"))
        self.assertTrue(gp.same_text("  a b ", "a b"))
        self.assertFalse(gp.same_text("a b", "a  b"))
        self.assertFalse(gp.same_text("a", "b"))

    def test_non_strings_never_compare_equal(self):
        self.assertFalse(gp.same_text(None, ""))
        self.assertFalse(gp.same_text("", None))
        self.assertFalse(gp.same_text(1, 1))
        self.assertEqual(gp.normalize_text(None), "")


class MarkedCommentTest(unittest.TestCase):
    MARK = "<!-- x:1 -->"

    def test_actor_matching_is_case_insensitive_and_exact(self):
        comments = [comment(1, "Bot", self.MARK), comment(2, "bot-2", self.MARK), comment(3, "bot", "no marker"),
                    {"id": 4, "user": None, "body": self.MARK}, {"id": 5, "body": self.MARK}]
        found = gp.marked_comments(comments, actor="BOT", marker=self.MARK)
        self.assertEqual([c["id"] for c in found], [1])

    def test_verify_comment_accepts_a_faithful_persisted_comment(self):
        remote = comment(9, "Bot", self.MARK + "\r\nbody\r\n")
        gp.verify_comment(remote, comment_id=9, actor="bot", marker=self.MARK, body=self.MARK + "\nbody", pr=7)

    def test_verify_comment_rejects_each_kind_of_difference(self):
        good = dict(comment_id=9, actor="bot", marker=self.MARK, body=self.MARK + " body", pr=7)
        cases = (
            (comment(8, "bot", self.MARK + " body"), "id"),
            (comment(9, "other", self.MARK + " body"), "author"),
            (comment(9, "bot", self.MARK + " body", issue_url=ISSUE.replace("/7", "/8")), "pull request"),
            (comment(9, "bot", "body only"), "marker"),
            (comment(9, "bot", self.MARK + " different"), "body differs"),
            ({"id": 9, "user": {"login": "bot"}, "body": self.MARK + " body"}, "pull request"),
        )
        for remote, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(gp.PublicationError, message):
                gp.verify_comment(remote, label="summary comment", **good)

    def test_exactly_one_marked_comment_must_exist_and_be_the_published_one(self):
        gp.verify_single_marked([comment(1, "bot", self.MARK), comment(2, "x", "y")],
                                actor="bot", marker=self.MARK, comment_id=1)
        with self.assertRaisesRegex(gp.PublicationError, "more than one marked"):
            gp.verify_single_marked([comment(1, "bot", self.MARK), comment(2, "bot", self.MARK)],
                                    actor="bot", marker=self.MARK, comment_id=1)
        with self.assertRaisesRegex(gp.PublicationError, "not present"):
            gp.verify_single_marked([comment(2, "x", "y")], actor="bot", marker=self.MARK, comment_id=1)
        with self.assertRaisesRegex(gp.PublicationError, "not the published 1"):
            gp.verify_single_marked([comment(2, "bot", self.MARK)], actor="bot", marker=self.MARK, comment_id=1)


if __name__ == "__main__":
    unittest.main()
