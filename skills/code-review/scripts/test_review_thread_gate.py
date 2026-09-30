#!/usr/bin/env python3
"""The own-thread gate, exercised directly against a mocked GraphQL client."""

import subprocess
import unittest

import review_thread_gate as gate


def node(thread_id, author="bot", resolved=False, path="a.py", line=3):
    return {"id": thread_id, "isResolved": resolved, "path": path, "line": line,
            "comments": {"nodes": [{"author": {"login": author} if author else None}]}}


def reply(nodes, more=False, cursor="c1"):
    return {"data": {"repository": {"pullRequest": {"reviewThreads": {
        "pageInfo": {"hasNextPage": more, "endCursor": cursor}, "nodes": nodes}}}}}


class OwnUnresolvedThreadsTest(unittest.TestCase):
    def test_only_the_actors_unresolved_threads_are_returned(self):
        run_json = lambda *args: reply([node("T1"), node("T2", resolved=True), node("T3", author="other"),
                                        node("T4", author=None, resolved=True)])
        self.assertEqual([t["id"] for t in gate.own_unresolved_threads(run_json, "o/r", 5, "BOT")], ["T1"])

    def test_the_query_names_the_repository_pull_request_and_cursor(self):
        calls = []

        def run_json(*args):
            calls.append(args)
            return reply([node("T1")], more=len(calls) == 1)

        gate.own_unresolved_threads(run_json, "o/r", 5, "bot")
        self.assertEqual(len(calls), 2)
        self.assertIn("owner=o", calls[0])
        self.assertIn("name=r", calls[0])
        self.assertIn("pr=5", calls[0])
        self.assertNotIn("cursor=c1", calls[0])
        self.assertIn("cursor=c1", calls[1])

    def test_unreadable_or_malformed_state_fails_closed(self):
        def boom(*args):
            raise subprocess.CalledProcessError(1, list(args))

        paged_without_cursor = lambda *args: reply([], more=True, cursor=None)
        forever = lambda *args: reply([], more=True)
        for label, run_json in (("error", boom), ("invalid json", lambda *a: (_ for _ in ()).throw(ValueError("x"))),
                                ("no cursor", paged_without_cursor), ("unbounded paging", forever),
                                ("missing id", lambda *a: reply([{"isResolved": False}]))):
            with self.subTest(label=label), self.assertRaises(gate.ThreadGateError):
                gate.own_unresolved_threads(run_json, "o/r", 5, "bot")

    def test_an_unresolved_thread_with_an_unknown_opening_author_fails_closed(self):
        no_comments = {"id": "T9", "isResolved": False, "path": "a.py", "line": 3, "comments": {"nodes": []}}
        no_connection = {"id": "T9", "isResolved": False, "path": "a.py", "line": 3}
        for label, bad in (("null author", node("T9", author=None)), ("no comments", no_comments),
                           ("no comments field", no_connection),
                           ("blank login", {**node("T9"), "comments": {"nodes": [{"author": {"login": ""}}]}})):
            with self.subTest(label=label):
                run_json = lambda *a, bad=bad: reply([node("T1", author="other"), bad])
                with self.assertRaisesRegex(gate.ThreadGateError, "T9.*cannot be established"):
                    gate.own_unresolved_threads(run_json, "o/r", 5, "bot")

    def test_a_resolved_thread_with_an_unknown_author_is_irrelevant(self):
        run_json = lambda *a: reply([node("T1", author=None, resolved=True), node("T2", author="other")])
        self.assertEqual(gate.own_unresolved_threads(run_json, "o/r", 5, "bot"), [])
        gate.require_no_own_unresolved_threads(run_json, "o/r", 5, "bot", "APPROVE")

    def test_has_next_page_must_be_an_explicit_boolean(self):
        def page(**info):
            return lambda *a: {"data": {"repository": {"pullRequest": {"reviewThreads": {
                "pageInfo": info, "nodes": [node("T1", author="other")]}}}}}

        for label, info in (("missing", {"endCursor": "c"}), ("null", {"hasNextPage": None}),
                            ("string", {"hasNextPage": "false"}), ("number", {"hasNextPage": 0})):
            with self.subTest(label=label), self.assertRaisesRegex(gate.ThreadGateError, "hasNextPage"):
                gate.own_unresolved_threads(page(**info), "o/r", 5, "bot")
        self.assertEqual(gate.own_unresolved_threads(page(hasNextPage=False), "o/r", 5, "bot"), [])

    def test_a_repository_that_is_not_owner_name_is_rejected(self):
        for repo in ("", "noslash", "a/b/c"):
            with self.subTest(repo=repo), self.assertRaises(gate.ThreadGateError):
                gate.own_unresolved_threads(lambda *a: reply([]), repo, 5, "bot")


class RequireTest(unittest.TestCase):
    def test_only_approve_is_gated(self):
        def never(*args):
            raise AssertionError("no query expected")

        for verdict in ("CHANGES_REQUESTED", "CANNOT_VERIFY"):
            gate.require_no_own_unresolved_threads(never, "o/r", 5, "bot", verdict)

    def test_approve_refusal_names_each_thread(self):
        run_json = lambda *a: reply([node("T1"), node("T2", path=None, line=None)])
        with self.assertRaisesRegex(gate.ThreadGateError, r"APPROVE refused.*T1 \(a\.py:3\), T2\."):
            gate.require_no_own_unresolved_threads(run_json, "o/r", 5, "bot", "APPROVE")

    def test_approve_passes_with_no_own_unresolved_threads(self):
        gate.require_no_own_unresolved_threads(lambda *a: reply([node("T1", author="other")]),
                                               "o/r", 5, "bot", "APPROVE")


if __name__ == "__main__":
    unittest.main()
