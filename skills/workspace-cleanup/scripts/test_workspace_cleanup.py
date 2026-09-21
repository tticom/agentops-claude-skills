#!/usr/bin/env python3
"""Workspace cleanup against real temporary Git repositories (no GitHub, no network)."""

import contextlib
import getpass
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import workspace_cleanup as wc

IDENT = ["-c", "user.name=Test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false"]


def git(cwd, *args):
    result = subprocess.run(["git", *IDENT, *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


def commit(cwd, name):
    (Path(cwd) / name).write_text(name, encoding="utf-8")
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", name)


class Workspace:
    def __init__(self, test):
        self.dir = tempfile.TemporaryDirectory()
        test.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name).resolve() / "workspace"
        self.root.mkdir()
        self.repo = self.root / "project"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        git(self.repo, "checkout", "-q", "-b", "main")
        commit(self.repo, "base.txt")

    def review(self, suffix, *, merged=True, dirty=False, detach=False, lock=False, name=None):
        path = self.root / (name or f"project-review-pr-{suffix}")
        if detach:
            git(self.repo, "worktree", "add", "-q", "--detach", str(path))
        else:
            git(self.repo, "worktree", "add", "-q", "-b", f"review/{suffix}", str(path))
        if not merged:
            commit(path, f"work-{suffix}.txt")
        if dirty:
            (path / "scratch.txt").write_text("uncommitted", encoding="utf-8")
        if lock:
            git(self.repo, "worktree", "lock", str(path))
        return path

    def run(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = wc.main(["--workspace", str(self.root), "--no-gh", *extra])
        return code, out.getvalue()

    def receipt(self):
        files = sorted((self.root / "agentops-logs" / "cleanup-receipts").glob("*.json"))
        return json.loads(files[-1].read_text(encoding="utf-8"))

    def actions(self, path=None):
        return [(e["action"], e["reason"]) for e in self.receipt() if path is None or Path(e["path"]) == Path(path)]


class RemovalPolicyTest(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace(self)

    def test_clean_merged_review_worktree_is_removed_with_a_receipt(self):
        wt = self.ws.review(1)
        code, _ = self.ws.run()
        self.assertEqual(code, 0)
        self.assertFalse(wt.exists())
        self.assertIn(("removed_worktree", "clean stale review worktree"), self.ws.actions(wt))

    def test_dry_run_deletes_nothing_but_reports_the_removal(self):
        wt = self.ws.review(1)
        code, out = self.ws.run("--dry-run")
        self.assertEqual(code, 0)
        self.assertTrue(wt.exists())
        self.assertIn("Would remove", out)
        self.assertIn(("dry_run_remove", "clean stale review worktree"), self.ws.actions(wt))

    def test_unmerged_review_is_preserved_as_active(self):
        wt = self.ws.review(2, merged=False)
        self.ws.run()
        self.assertTrue(wt.exists())
        self.assertIn(("preserved", "active/unverified review"), self.ws.actions(wt))

    def test_dirty_review_worktree_is_never_removed(self):
        wt = self.ws.review(3, dirty=True)
        self.ws.run()
        self.assertTrue((wt / "scratch.txt").exists())
        self.assertIn(("preserved", "dirty worktree"), self.ws.actions(wt))

    def test_unclassified_worktree_is_preserved_even_when_merged(self):
        wt = self.ws.review(4, name="project-feature")
        self.ws.run()
        self.assertTrue(wt.exists())
        self.assertIn(("preserved", "unknown/unclassified worktree"), self.ws.actions(wt))

    def test_locked_worktree_is_preserved(self):
        wt = self.ws.review(5, lock=True)
        self.ws.run()
        self.assertTrue(wt.exists())
        self.assertTrue(any(a == "preserved" and r.startswith("locked worktree") for a, r in self.ws.actions(wt)))

    def test_detached_head_is_not_proof_of_staleness(self):
        wt = self.ws.review(6, detach=True)
        self.ws.run()
        self.assertTrue(wt.exists())
        self.assertIn(("preserved", "active/unverified review"), self.ws.actions(wt))

    def test_only_the_stale_one_is_removed_among_several(self):
        stale = self.ws.review(7)
        active = self.ws.review(8, merged=False)
        dirty = self.ws.review(9, dirty=True)
        self.ws.run()
        self.assertFalse(stale.exists())
        self.assertTrue(active.exists() and dirty.exists())

    def test_missing_worktree_directory_never_causes_a_removal_or_a_crash(self):
        wt = self.ws.review(10)
        import shutil
        shutil.rmtree(wt)
        code, _ = self.ws.run()
        self.assertEqual(code, 0)
        self.assertNotIn("removed_worktree", [a for a, _ in self.ws.actions(wt)])

    def test_custom_review_pattern_and_base_branch(self):
        wt = self.ws.review(11, name="project-rv-11")
        self.ws.run()
        self.assertTrue(wt.exists())  # default pattern does not classify it as a review
        self.ws.run("--review-worktree-pattern=-rv-")  # "=" form: value starts with a dash
        self.assertFalse(wt.exists())
        stale = self.ws.review(12)
        code, _ = self.ws.run("--base-branch", "no-such-branch")
        self.assertEqual(code, 0)
        self.assertTrue(stale.exists())  # cannot prove it merged into a branch that does not exist

    def test_invalid_pattern_is_a_usage_error(self):
        self.assertEqual(self.ws.run("--review-worktree-pattern=(")[0], 64)

    def test_a_repository_shared_by_several_checkouts_is_scanned_once(self):
        self.ws.review(13, name="project-second")
        _, out = self.ws.run()
        self.assertEqual(out.count("Scanning"), 1)


class OutputAndSafetyTest(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace(self)

    def test_receipt_and_index_live_outside_every_scanned_repository(self):
        self.ws.run("--active-task-pointer", "governance/ACTIVE_TASK.md")
        index = self.ws.root / "agentops-logs" / "workspace-state" / "latest.md"
        text = index.read_text(encoding="utf-8")
        self.assertIn("| `project` | `main` |", text)
        self.assertIn("Active task pointer: `governance/ACTIVE_TASK.md`", text)
        self.assertEqual(git(self.ws.repo, "status", "--porcelain"), "")
        self.assertIn(("workspace_index", "human-readable checkout map"), self.ws.actions())

    def test_receipt_and_index_locations_are_configurable(self):
        target = self.ws.root.parent / "elsewhere"
        self.ws.run("--receipt-dir", str(target / "r"), "--index-file", str(target / "i.md"))
        self.assertTrue(list((target / "r").glob("*.json")))
        self.assertTrue((target / "i.md").is_file())

    def test_unsafe_workspaces_are_refused_without_touching_anything(self):
        for label, workspace in (
            ("missing", self.ws.root / "absent"),
            ("root", Path(self.ws.root.anchor)),
            ("a file", self.ws.repo / "base.txt"),
        ):
            with self.subTest(label=label):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = wc.main(["--workspace", str(workspace), "--no-gh"])
                self.assertEqual(code, 1)
                self.assertIn("invalid or unsafe", out.getvalue())
        with patch.object(Path, "home", return_value=self.ws.root):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(wc.main(["--workspace", str(self.ws.root), "--no-gh"]), 1)

    def test_optional_user_restriction(self):
        self.assertEqual(self.ws.run("--allowed-user", "nobody-at-all")[0], 1)
        self.assertEqual(self.ws.run("--allowed-user", getpass.getuser())[0], 0)

    def test_workspace_may_come_from_the_environment(self):
        out = io.StringIO()
        with patch.dict("os.environ", {wc.WORKSPACE_ENV: str(self.ws.root)}), contextlib.redirect_stdout(out):
            self.assertEqual(wc.main(["--no-gh"]), 0)
        self.assertIn("Scanning project", out.getvalue())


class UnitTest(unittest.TestCase):
    def test_porcelain_worktree_output_is_parsed(self):
        sample = (
            "worktree /w/repo\nHEAD abc\nbranch refs/heads/main\n\n"
            "worktree /w/repo-review-pr-1\nHEAD def\nbranch refs/heads/review/1\nlocked in use\n\n"
            "worktree /w/gone\nHEAD 000\ndetached\nprunable gitdir missing\n"
        )
        fake = subprocess_result(sample)
        with patch.object(wc, "run_cmd", return_value=fake):
            parsed = wc.get_worktrees(Path("/w/repo"))
        self.assertEqual(parsed[1]["branch"], "review/1")
        self.assertEqual(parsed[1]["locked"], "in use")
        self.assertTrue(parsed[2]["detached"])
        self.assertEqual(parsed[2]["prunable"], "gitdir missing")

    def test_pull_request_state_decides_only_when_gh_is_allowed_and_conclusive(self):
        def fake(output, code=0):
            def run(cmd, cwd=None, check=True):
                if cmd[:2] == ["git", "branch"]:
                    return subprocess_result("  other\n")
                return subprocess_result(output, code)
            return run

        repo = Path(".")
        for output, code, expected in (
            ('{"state": "MERGED"}', 0, True),
            ('{"state": "CLOSED"}', 0, True),
            ('{"state": "OPEN"}', 0, False),
            ("not json", 0, False),
            ("", 127, False),  # gh missing or failing: preserve
        ):
            with self.subTest(output=output), patch.object(wc, "run_cmd", side_effect=fake(output, code)):
                self.assertIs(wc.is_stale_review(repo, "feature", "main", use_gh=True), expected)
        with patch.object(wc, "run_cmd", side_effect=fake('{"state": "MERGED"}')):
            self.assertFalse(wc.is_stale_review(repo, "feature", "main", use_gh=False))
            self.assertFalse(wc.is_stale_review(repo, None, "main", use_gh=True))

    def test_a_missing_executable_is_a_failed_command_not_a_crash(self):
        result = wc.run_cmd(["definitely-not-a-real-executable-xyz"], check=False)
        self.assertEqual(result.returncode, 127)
        with self.assertRaises(RuntimeError):
            wc.run_cmd(["definitely-not-a-real-executable-xyz"])

    def test_no_project_specific_identifiers_remain_in_the_script(self):
        source = Path(wc.__file__).read_text(encoding="utf-8").lower()
        for banned in ("score2gp", "tticom", "/mnt/c", "active_task.md"):
            self.assertNotIn(banned, source)


def subprocess_result(stdout, code=0):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr="")


if __name__ == "__main__":
    unittest.main()
