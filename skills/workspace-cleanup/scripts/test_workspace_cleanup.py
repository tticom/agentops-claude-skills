#!/usr/bin/env python3
"""Workspace cleanup against real temporary Git repositories (no GitHub, no network)."""

import contextlib
import getpass
import io
import json
import os
import subprocess
import tempfile
import unittest
import unittest.mock
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


def rmtree_force(path):
    """Delete a Git repository even where read-only object files block shutil.rmtree (Windows)."""
    import shutil
    import stat
    for root, dirs, files in os.walk(path):
        for name in files + dirs:
            try:
                os.chmod(os.path.join(root, name), stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
            except OSError:
                pass
    shutil.rmtree(path)


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


class WorkspaceContainmentTest(unittest.TestCase):
    """Git's worktree list is repository-wide; the requested workspace is the boundary."""

    def setUp(self):
        self.ws = Workspace(self)
        self.outside_root = self.ws.root.parent  # a sibling of the workspace directory

    def _outside(self, suffix, *, merged=True, missing=False):
        path = self.outside_root / f"outside-review-pr-{suffix}"
        git(self.ws.repo, "worktree", "add", "-q", "-b", f"outside/{suffix}", str(path))
        if not merged:
            commit(path, f"work-{suffix}.txt")
        if missing:
            import shutil
            shutil.rmtree(path)
        return path

    def test_a_clean_merged_review_worktree_outside_the_workspace_is_never_removed(self):
        """Reviewer reproduction: recorded as dry_run_remove, and removed without --dry-run."""
        outside = self._outside(9)
        inside = self.ws.review(1)
        code, out = self.ws.run()
        self.assertEqual(code, 0)
        self.assertNotIn(f"Removing disposable worktree: {outside}", out)
        self.assertTrue(outside.exists(), "an out-of-workspace worktree was deleted")
        self.assertFalse(inside.exists(), "the in-workspace stale worktree should still be removed")
        self.assertIn(("preserved", "outside the requested workspace"), self.ws.actions(outside))
        self.assertNotIn("removed_worktree", [a for a, _ in self.ws.actions(outside)])

    def test_a_dry_run_does_not_select_an_outside_worktree_either(self):
        outside = self._outside(9)
        self.ws.run("--dry-run")
        actions = [a for a, _ in self.ws.actions(outside)]
        self.assertNotIn("dry_run_remove", actions)
        self.assertIn("preserved", actions)
        self.assertTrue(outside.exists())

    def test_the_internal_positive_control_still_removes(self):
        inside = self.ws.review(2)
        self._outside(3)
        self.ws.run()
        self.assertFalse(inside.exists())
        self.assertIn(("removed_worktree", "clean stale review worktree"), self.ws.actions(inside))

    def test_an_outside_worktree_is_preserved_even_when_it_would_otherwise_qualify_in_every_way(self):
        outside = self._outside(4)
        for extra in ((), ("--dry-run",), ("--base-branch", "main"), ("--review-worktree-pattern=.*",)):
            with self.subTest(extra=extra):
                self.ws.run(*extra)
                self.assertTrue(outside.exists())

    def test_a_sibling_directory_sharing_the_workspace_prefix_is_outside(self):
        sibling = self.outside_root / (self.ws.root.name + "-evil")
        sibling.mkdir()
        path = sibling / "project-review-pr-5"
        git(self.ws.repo, "worktree", "add", "-q", "-b", "outside/5", str(path))
        self.ws.run()
        self.assertTrue(path.exists())
        self.assertIn(("preserved", "outside the requested workspace"), self.ws.actions(path))

    def test_metadata_for_a_missing_outside_worktree_is_not_pruned(self):
        """git worktree prune is repository-wide, so it must not run while an outside entry is prunable."""
        outside = self._outside(6, missing=True)
        self.assertIn("prunable", git(self.ws.repo, "worktree", "list", "--porcelain"))
        code, _ = self.ws.run()
        self.assertEqual(code, 0)
        listing = git(self.ws.repo, "worktree", "list", "--porcelain")
        self.assertIn(outside.name, listing, "outside worktree metadata was pruned")
        self.assertTrue(any(a == "preserved" and "not pruned" in r for a, r in self.ws.actions()))
        self.assertNotIn("pruned_metadata", [a for a, _ in self.ws.actions()])

    def test_one_outside_prunable_entry_blocks_pruning_of_inside_ones_too(self):
        outside = self._outside(7, missing=True)
        inside = self.ws.review(8)
        import shutil
        shutil.rmtree(inside)
        self.ws.run()
        listing = git(self.ws.repo, "worktree", "list", "--porcelain")
        self.assertIn(outside.name, listing)
        self.assertIn(inside.name, listing, "prune cannot be scoped, so it must be skipped entirely")

    def test_metadata_for_a_missing_inside_worktree_is_still_pruned(self):
        inside = self.ws.review(10)
        import shutil
        shutil.rmtree(inside)
        self.assertIn(inside.name, git(self.ws.repo, "worktree", "list", "--porcelain"))
        self.ws.run()
        self.assertNotIn(inside.name, git(self.ws.repo, "worktree", "list", "--porcelain"))
        self.assertIn("pruned_metadata", [a for a, _ in self.ws.actions()])

    def test_a_dry_run_reports_but_does_not_prune(self):
        inside = self.ws.review(11)
        import shutil
        shutil.rmtree(inside)
        self.ws.run("--dry-run")
        self.assertIn(inside.name, git(self.ws.repo, "worktree", "list", "--porcelain"))
        self.assertIn("dry_run_prune", [a for a, _ in self.ws.actions()])

    def test_a_checkout_that_resolves_outside_the_workspace_is_not_scanned(self):
        elsewhere = self.outside_root / "elsewhere-repo"
        elsewhere.mkdir()
        git(elsewhere, "init", "-q")
        git(elsewhere, "checkout", "-q", "-b", "main")
        commit(elsewhere, "x.txt")
        stale = self.outside_root / "elsewhere-review-pr-1"
        git(elsewhere, "worktree", "add", "-q", "-b", "r/1", str(stale))
        link = self.ws.root / "linked-repo"
        try:
            if os.name == "nt":
                subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(elsewhere)],
                               check=True, capture_output=True)
            else:
                os.symlink(elsewhere, link, target_is_directory=True)
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("cannot create a link or junction on this platform or account")
        out = self.ws.run()[1]
        self.assertTrue(stale.exists(), "a repository outside the workspace was cleaned through a link")
        self.assertIn("outside the requested workspace", json.dumps(self.ws.receipt()))
        self.assertNotIn("Scanning linked-repo", out)

    def test_a_link_inside_the_workspace_that_points_outside_is_not_within_it(self):
        target = self.outside_root / "link-target"
        target.mkdir()
        link = self.ws.root / "a-link"
        try:
            if os.name == "nt":
                subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                               check=True, capture_output=True)
            else:
                os.symlink(target, link, target_is_directory=True)
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("cannot create a link or junction on this platform or account")
        self.assertFalse(wc.within_workspace(link, self.ws.root))
        self.assertFalse(wc.within_workspace(link / "child", self.ws.root))

    def test_within_workspace_boundaries(self):
        root = self.ws.root
        self.assertTrue(wc.within_workspace(root, root))
        self.assertTrue(wc.within_workspace(root / "a" / "b", root))
        self.assertTrue(wc.within_workspace(root / "a" / ".." / "b", root))
        self.assertFalse(wc.within_workspace(root.parent, root))
        self.assertFalse(wc.within_workspace(root.parent / (root.name + "-evil"), root))
        self.assertFalse(wc.within_workspace(root / ".." / "elsewhere", root))

    def test_the_documented_scope_is_the_only_thing_cleaned(self):
        stale_in = self.ws.review(20)
        stale_out = self._outside(21)
        dirty_out = self._outside(22)
        (dirty_out / "scratch.txt").write_text("uncommitted", encoding="utf-8")
        self.ws.run()
        self.assertFalse(stale_in.exists())
        self.assertTrue(stale_out.exists())
        self.assertTrue((dirty_out / "scratch.txt").exists())


class AnchorIndependenceTest(unittest.TestCase):
    """Which checkout issues the git commands must never decide which worktrees are cleaned."""

    def test_alphabetical_order_does_not_decide_whether_a_review_worktree_is_cleaned(self):
        """Reviewer reproduction: the same qualifying worktree, differing only in its name."""
        results = {}
        for name in ("internal-review-pr-8", "zz-internal-review-pr-8"):
            with self.subTest(name=name):
                ws = Workspace(self)  # primary checkout is workspace/project
                worktree = ws.review(8, name=name)
                ws.run()
                results[name] = (worktree.exists(), ("removed_worktree", "clean stale review worktree") in ws.actions(worktree))
        self.assertEqual(results["internal-review-pr-8"], results["zz-internal-review-pr-8"])
        self.assertEqual(results["internal-review-pr-8"], (False, True))

    def test_the_dry_run_agrees_for_both_orderings(self):
        for name in ("internal-review-pr-8", "zz-internal-review-pr-8"):
            with self.subTest(name=name):
                ws = Workspace(self)
                worktree = ws.review(8, name=name)
                ws.run("--dry-run")
                self.assertIn(("dry_run_remove", "clean stale review worktree"), ws.actions(worktree))
                self.assertTrue(worktree.exists())

    def test_every_non_primary_worktree_gets_a_decision_wherever_it_sorts(self):
        ws = Workspace(self)
        stale = [ws.review(1, name="a-review-pr-1"), ws.review(2, name="m-review-pr-2"),
                 ws.review(3, name="zz-review-pr-3")]
        dirty = ws.review(4, name="b-review-pr-4", dirty=True)
        active = ws.review(5, name="c-review-pr-5", merged=False)
        listed = [Path(line.split(" ", 1)[1]).resolve() for line in
                  git(ws.repo, "worktree", "list", "--porcelain").splitlines() if line.startswith("worktree ")]
        ws.run()
        self.assertTrue(all(not path.exists() for path in stale))
        self.assertTrue(dirty.exists() and active.exists())
        decided = {Path(e["path"]).resolve() for e in ws.receipt()}
        missing = [str(path) for path in listed if path not in decided]
        self.assertEqual(missing, [], "a worktree was silently skipped")

    def test_the_primary_checkout_is_preserved_and_recorded_not_silently_skipped(self):
        ws = Workspace(self)
        ws.run()
        self.assertTrue(any(a == "preserved" and "primary checkout" in r for a, r in ws.actions(ws.repo)))
        self.assertTrue(ws.repo.exists())

    def test_a_primary_whose_name_matches_the_review_pattern_is_never_removed(self):
        ws = Workspace(self)
        renamed = ws.root / "project-review"
        ws.repo.rename(renamed)  # a primary that matches -review$
        ws.repo = renamed
        worktree = ws.review(9, name="project-review-pr-9")
        ws.run()
        self.assertTrue(renamed.exists() and (renamed / ".git").exists())
        self.assertFalse(worktree.exists())
        self.assertNotIn("removed_worktree", [a for a, _ in ws.actions(renamed)])

    def test_a_workspace_holding_only_linked_worktrees_is_cleaned_explicitly(self):
        """The primary checkout lives outside the workspace; every checkout inside is linked."""
        ws = Workspace(self)
        primary = ws.root.parent / "primary-elsewhere"
        ws.repo.rename(primary)
        ws.repo = primary
        first = ws.review(1, name="w1-review-pr-1")
        second = ws.review(2, name="w2-review-pr-2")
        keep = ws.review(3, name="w3-review-pr-3", merged=False)
        code, _ = ws.run()
        self.assertEqual(code, 0)
        self.assertFalse(first.exists() or second.exists())
        self.assertTrue(keep.exists())
        self.assertTrue(primary.exists() and (primary / "base.txt").exists(), "the primary was touched")
        self.assertEqual(git(primary, "branch", "--list", "review/3").strip() != "", True)

    def test_a_missing_primary_checkout_is_an_explicit_error_not_a_crash_or_a_removal(self):
        ws = Workspace(self)
        primary = ws.root.parent / "vanished-primary"
        ws.repo.rename(primary)
        ws.repo = primary
        worktree = ws.review(1, name="w1-review-pr-1")
        rmtree_force(primary)
        code, _ = ws.run()
        self.assertEqual(code, 0)
        self.assertTrue(worktree.exists())
        self.assertTrue(any(a == "error" for a, _ in ws.actions()), ws.actions())

    def test_several_repositories_are_each_cleaned_whatever_their_sort_order(self):
        ws = Workspace(self)  # workspace/project
        other = ws.root / "zeta"
        other.mkdir()
        git(other, "init", "-q")
        git(other, "checkout", "-q", "-b", "main")
        commit(other, "z.txt")
        early = ws.root / "a-review-pr-1"          # sorts before its own primary (project)
        git(ws.repo, "worktree", "add", "-q", "-b", "review/a", str(early))
        late = ws.root / "zz-review-pr-2"          # sorts after both primaries
        git(other, "worktree", "add", "-q", "-b", "review/z", str(late))
        _, out = ws.run()
        self.assertFalse(early.exists() or late.exists(), out)
        self.assertTrue(ws.repo.exists() and other.exists())

    def test_a_worktree_is_never_removed_by_git_running_inside_it(self):
        """Removing a directory that is the command's own working directory fails on Windows."""
        ws = Workspace(self)
        target = ws.review(1, name="a-review-pr-1")
        calls = []
        real = wc.run_cmd

        def spy(cmd, cwd=None, check=True):
            if list(cmd)[:3] == ["git", "worktree", "remove"]:
                calls.append((str(cmd[-1]), str(cwd)))
            return real(cmd, cwd=cwd, check=check)

        with unittest.mock.patch.object(wc, "run_cmd", spy):
            ws.run()
        self.assertEqual(len(calls), 1)
        removed, cwd = calls[0]
        self.assertFalse(wc.same_path(removed, cwd), "git ran from inside the worktree it removed")
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
