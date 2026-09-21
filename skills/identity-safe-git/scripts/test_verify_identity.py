#!/usr/bin/env python3

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import verify_identity as vi

GOOD = {
    "os_user": "worker",
    "home": "/agents/worker",
    "host_login": "worker-bot",
    "git_name": "Worker Bot",
    "git_email": "worker@example.invalid",
    "repo_prefix": "/work/project",
}


class FakeHost(vi.Host):
    """Answers every probe from a table so no real git, gh or OS state is read."""

    is_windows = False

    def __init__(self, **overrides):
        self.facts = {
            "user": "worker",
            "home": "/agents/worker",
            "tools": {"git", "gh"},
            "toplevel": "/work/project/repo",
            "login": "worker-bot",
            "local_name": "",
            "local_email": "",
            "global_name": "Worker Bot",
            "global_email": "worker@example.invalid",
            "effective_name": "Worker Bot",
            "effective_email": "worker@example.invalid",
            "branch": "feature/x",
            "head": "a" * 40,
        }
        self.facts.update(overrides)

    def os_user(self):
        return self.facts["user"]

    def home(self):
        return self.facts["home"]

    def which(self, name):
        return name if name in self.facts["tools"] else None

    def realpath(self, path):
        return path

    def run(self, argv, cwd=None):
        f = self.facts
        argv = list(argv)
        if argv[:3] == ["git", "rev-parse", "--show-toplevel"]:
            return (0, f["toplevel"]) if f["toplevel"] else (128, "")
        if argv[:2] == ["gh", "api"]:
            return (0, f["login"]) if f["login"] else (1, "")
        if argv[:2] == ["git", "config"]:
            scope = "effective"
            if "--local" in argv:
                scope = "local"
            elif "--global" in argv:
                scope = "global"
            field = "name" if "user.name" in argv else "email"
            value = f[f"{scope}_{field}"]
            return (0, value) if value else (1, "")
        if argv[:3] == ["git", "branch", "--show-current"]:
            return 0, f["branch"]
        if argv[:2] == ["git", "rev-parse"]:
            return 0, f["head"]
        raise AssertionError(f"unexpected probe: {argv}")


class VerifyTest(unittest.TestCase):
    def check(self, host, **expected_overrides):
        return vi.verify(vi.Expected(**{**GOOD, **expected_overrides}), host)

    def test_matching_identity_passes_and_reports_facts(self):
        facts = self.check(FakeHost())
        self.assertEqual(facts["head"], "a" * 40)
        self.assertEqual(facts["repo_root"], "/work/project/repo")
        self.assertEqual(facts["branch"], "feature/x")

    def test_every_single_mismatch_is_a_no_write_stop(self):
        cases = (
            ({"user": "intruder"}, "OS user"),
            ({"home": "/agents/other"}, "HOME"),
            ({"tools": {"git"}}, "gh is unavailable"),
            ({"tools": {"gh"}}, "git is unavailable"),
            ({"toplevel": ""}, "not inside a Git worktree"),
            ({"toplevel": "/elsewhere/repo"}, "outside"),
            ({"toplevel": "/work/project-evil"}, "outside"),
            ({"login": ""}, "cannot read authenticated"),
            ({"login": "someone-else"}, "Git host login"),
            ({"local_name": "Override"}, "repository-local"),
            ({"local_email": "o@example.invalid"}, "repository-local"),
            ({"global_name": "Other"}, "global Git author name"),
            ({"global_email": "other@example.invalid"}, "global Git author email"),
        )
        for overrides, message in cases:
            with self.subTest(overrides=overrides), self.assertRaisesRegex(vi.GateFailed, message):
                self.check(FakeHost(**overrides))

    def test_repo_prefix_itself_is_inside(self):
        self.assertEqual(self.check(FakeHost(toplevel="/work/project"))["repo_root"], "/work/project")

    def test_local_identity_flag_switches_to_effective_identity(self):
        host = FakeHost(local_name="Worker Bot", local_email="worker@example.invalid",
                        global_name="", global_email="")
        with self.assertRaisesRegex(vi.GateFailed, "repository-local"):
            self.check(host)
        facts = self.check(host, allow_local_git_identity=True)
        self.assertEqual(facts["git_name"], "Worker Bot")
        with self.assertRaisesRegex(vi.GateFailed, "effective Git author name"):
            self.check(FakeHost(effective_name="Wrong"), allow_local_git_identity=True)

    def test_windows_comparisons_ignore_case_and_separators(self):
        class WindowsHost(FakeHost):
            is_windows = True

            def realpath(self, path):
                return path.replace("/", "\\")

        host = WindowsHost(user="Worker", home="C:/Agents/Worker", toplevel="c:/Work/Project/Repo")
        facts = self.check(
            host, os_user="worker", home="c:/agents/worker", repo_prefix="C:/work/project"
        )
        self.assertEqual(facts["os_user"], "Worker")
        with self.assertRaisesRegex(vi.GateFailed, "outside"):
            self.check(
                WindowsHost(toplevel="C:/Work/Project-Evil/Repo", home="/agents/worker"),
                repo_prefix="C:/work/project",
            )


class ProfileTest(unittest.TestCase):
    def test_profile_loads_and_flags_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(
                json.dumps({**GOOD, "permissions": {"merge": False}, "protected_branches": ["main"]}),
                encoding="utf-8",
            )
            values = vi.load_profile(path, {"os_user": "override", "home": None})
            self.assertEqual(values["os_user"], "override")
            self.assertEqual(values["home"], GOOD["home"])

    def test_bad_profiles_are_usage_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for content in ("{bad", json.dumps([]), json.dumps({**GOOD, "typo_key": 1}),
                            json.dumps({"os_user": "x"})):
                path = root / "p.json"
                path.write_text(content, encoding="utf-8")
                with self.subTest(content=content), self.assertRaises(ValueError):
                    vi.load_profile(path, {})
            with self.assertRaises(ValueError):
                vi.load_profile(root / "absent.json", {})

    def test_main_exit_codes(self):
        flags = [item for key, value in GOOD.items() for item in (f"--{key.replace('_', '-')}", value)]
        self.assertEqual(vi.main(flags, FakeHost()), 0)
        self.assertEqual(vi.main(flags, FakeHost(user="intruder")), 1)
        self.assertEqual(vi.main(["--os-user", "only"], FakeHost()), 64)


class ScriptSmokeTest(unittest.TestCase):
    """Runs the real script as a subprocess: proves it starts on this platform."""

    def test_help_runs_without_a_shell(self):
        script = Path(vi.__file__)
        result = subprocess.run(
            [sys.executable, str(script), "--help"], capture_output=True, text=True, encoding="utf-8"
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--profile", result.stdout)

    def test_missing_fields_exit_64_on_the_real_script(self):
        script = Path(vi.__file__)
        result = subprocess.run(
            [sys.executable, str(script)], capture_output=True, text=True, encoding="utf-8"
        )
        self.assertEqual(result.returncode, 64)


if __name__ == "__main__":
    unittest.main()
