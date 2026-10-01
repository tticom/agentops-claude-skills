import subprocess
import tempfile
import unittest
from pathlib import Path

import safe_git_check as sgc


def run(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def make_repo(directory: str, branch: str = "main") -> Path:
    repo = Path(directory)
    run(repo, "init", "-q", "-b", branch)
    run(repo, "config", "user.email", "t@example.invalid")
    run(repo, "config", "user.name", "t")
    (repo / "f").write_text("x", encoding="utf-8")
    run(repo, "add", "f")
    run(repo, "commit", "-q", "-m", "init")
    return repo


class SafeGitCheckTest(unittest.TestCase):
    def test_protected_branch_is_unsafe(self):
        with tempfile.TemporaryDirectory() as d:
            repo = make_repo(d)
            self.assertEqual(sgc.check(repo), ["PROTECTED_BRANCH main"])
            self.assertEqual(sgc.main(["--repo", str(repo)]), 1)

    def test_feature_branch_is_safe(self):
        with tempfile.TemporaryDirectory() as d:
            repo = make_repo(d)
            run(repo, "checkout", "-q", "-b", "task/x")
            self.assertEqual(sgc.check(repo, expect_branch="task/x"), [])
            self.assertEqual(sgc.main(["--repo", str(repo)]), 0)

    def test_wrong_expected_branch(self):
        with tempfile.TemporaryDirectory() as d:
            repo = make_repo(d)
            run(repo, "checkout", "-q", "-b", "task/x")
            self.assertTrue(sgc.check(repo, expect_branch="task/y")[0].startswith("UNEXPECTED_BRANCH"))

    def test_detached_head(self):
        with tempfile.TemporaryDirectory() as d:
            repo = make_repo(d)
            run(repo, "checkout", "-q", "--detach")
            self.assertIn("DETACHED_HEAD", sgc.check(repo))

    def test_remote_mismatch_and_match(self):
        with tempfile.TemporaryDirectory() as d:
            repo = make_repo(d)
            run(repo, "checkout", "-q", "-b", "task/x")
            run(repo, "remote", "add", "origin", "https://github.com/tticom/other.git")
            self.assertTrue(sgc.check(repo, expect_remote="tticom/score2gp")[0].startswith("UNEXPECTED_REMOTE"))
            self.assertEqual(sgc.check(repo, expect_remote="TTicom/other"), [])

    def test_not_a_repo(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(sgc.check(Path(d)), ["NOT_A_GIT_REPOSITORY"])

    def test_remote_slug_forms(self):
        self.assertEqual(sgc.remote_slug("git@github.com:a/b.git"), "a/b")
        self.assertEqual(sgc.remote_slug("https://github.com/a/b"), "a/b")


if __name__ == "__main__":
    unittest.main()
