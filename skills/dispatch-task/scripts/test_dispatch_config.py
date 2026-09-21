#!/usr/bin/env python3
"""Dispatch configuration: valid, missing, invalid and conflicting cases."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import dispatch_config as dc

BASE = {
    "schema": dc.SCHEMA,
    "project": "example",
    "authority": {
        "active_task": "governance/ACTIVE_TASK.md",
        "control_documents": ["governance/AGENT_CONTROL.md"],
        "no_task_markers": ["NO_ACTIVE_TASK_APPROVED"],
    },
    "repositories": ["example-org/product", "example-org/governance"],
    "identity": {"profile": "identity.json", "role_policy": "roles.json"},
    "dispatch": {"command": ["python", "scripts/dispatch.py", "--json"], "cwd": "governance"},
}


def project(tmp: Path, config=BASE, name="agentops-dispatch.json", task="Task: T-1\nStatus: ACTIVE\n"):
    (tmp / "governance").mkdir(exist_ok=True)
    (tmp / "governance/ACTIVE_TASK.md").write_text(task, encoding="utf-8")
    (tmp / "governance/AGENT_CONTROL.md").write_text("rules\n", encoding="utf-8")
    target = tmp / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config), encoding="utf-8")
    return target


def without(config, *path):
    clone = json.loads(json.dumps(config))
    node = clone
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    return clone


class DispatchConfigTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def resolve(self, **kwargs):
        return dc.resolve(self.tmp, env=kwargs.pop("env", {}), **kwargs)

    # --- valid -----------------------------------------------------------
    def test_valid_configuration_with_a_command_is_ready_to_execute(self):
        project(self.tmp)
        result = self.resolve()
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["mode"], "execute")
        self.assertFalse(result["executed"])
        self.assertEqual(result["command"]["argv"], ["python", "scripts/dispatch.py", "--json"])
        self.assertEqual(Path(result["command"]["cwd"]), (self.tmp / "governance").resolve())
        self.assertFalse(result["authority"]["no_active_task"])
        self.assertEqual(result["repositories"], ["example-org/product", "example-org/governance"])
        self.assertEqual(set(result["identity"]), {"profile", "role_policy"})
        # regression: the project name must not be overwritten by a repository name
        self.assertEqual(result["project"], "example")

    def test_valid_configuration_without_a_command_is_handoff_only(self):
        project(self.tmp, without(BASE, "dispatch"))
        result = self.resolve()
        self.assertEqual((result["status"], result["mode"]), ("HANDOFF_ONLY", "handoff"))
        self.assertIsNone(result["command"])
        self.assertIn("no execution occurred", result["notice"])

    def test_alternate_location_is_found(self):
        project(self.tmp, name=".agentops/dispatch.json")
        (self.tmp / ".agentops").mkdir(exist_ok=True)
        # relative paths resolve against the project root, not the file's directory
        config = json.loads(json.dumps(BASE))
        config["authority"] = {"active_task": "governance/ACTIVE_TASK.md"}
        config.pop("dispatch")
        config.pop("identity")
        (self.tmp / ".agentops/dispatch.json").write_text(json.dumps(config), encoding="utf-8")
        self.assertEqual(self.resolve()["status"], "HANDOFF_ONLY")

    def test_explicit_config_and_matching_environment_agree(self):
        target = project(self.tmp)
        result = self.resolve(explicit=target, env={dc.ENV_CONFIG: str(target)})
        self.assertEqual(result["status"], "READY")

    def test_minimal_configuration_is_valid(self):
        project(self.tmp, {"schema": dc.SCHEMA, "project": "p",
                           "authority": {"active_task": "governance/ACTIVE_TASK.md"}})
        self.assertEqual(self.resolve()["status"], "HANDOFF_ONLY")

    # --- missing ---------------------------------------------------------
    def test_missing_configuration_stops(self):
        result = self.resolve()
        self.assertEqual(result["status"], "STOP_NO_CONFIG")
        self.assertIn("must supply one", result["errors"][0])
        self.assertIn("backlog", result["notice"])

    def test_explicit_path_that_does_not_exist_stops(self):
        result = self.resolve(explicit=self.tmp / "absent.json")
        self.assertEqual(result["status"], "STOP_NO_CONFIG")

    def test_missing_authority_documents_stop(self):
        target = project(self.tmp)
        (self.tmp / "governance/ACTIVE_TASK.md").unlink()
        self.assertEqual(self.resolve()["status"], "STOP_AUTHORITY_MISSING")
        (self.tmp / "governance/ACTIVE_TASK.md").write_text("x", encoding="utf-8")
        (self.tmp / "governance/AGENT_CONTROL.md").unlink()
        result = self.resolve()
        self.assertEqual(result["status"], "STOP_AUTHORITY_MISSING")
        self.assertIn("AGENT_CONTROL.md", result["errors"][0])
        self.assertTrue(target.exists())

    def test_no_active_task_marker_stops_even_with_a_dispatch_command(self):
        project(self.tmp, task="Status: NO_ACTIVE_TASK_APPROVED\n")
        result = self.resolve()
        self.assertEqual(result["status"], "STOP_NO_ACTIVE_TASK")
        self.assertIsNone(result["mode"])
        self.assertIn("not permission", result["notice"])

    # --- invalid ---------------------------------------------------------
    def test_invalid_configurations_stop(self):
        cases = {
            "not json": "{oops",
            "root not object": "[]",
            "wrong schema": json.dumps({**BASE, "schema": "other"}),
            "unknown top key": json.dumps({**BASE, "extra": 1}),
            "no project": json.dumps(without(BASE, "project")),
            "no authority": json.dumps(without(BASE, "authority")),
            "active_task list is ambiguous": json.dumps(
                {**BASE, "authority": {**BASE["authority"], "active_task": ["a.md", "b.md"]}}),
            "unknown authority key": json.dumps(
                {**BASE, "authority": {**BASE["authority"], "queue": "x"}}),
            "bad repo": json.dumps({**BASE, "repositories": ["no-slash"]}),
            "duplicate repo": json.dumps({**BASE, "repositories": ["o/r", "o/r"]}),
            "empty command": json.dumps({**BASE, "dispatch": {"command": []}}),
            "command not strings": json.dumps({**BASE, "dispatch": {"command": ["ok", 1]}}),
            "unknown dispatch key": json.dumps({**BASE, "dispatch": {"command": ["x"], "shell": True}}),
            "unknown identity key": json.dumps({**BASE, "identity": {"token": "x"}}),
            "absolute authority path": json.dumps(
                {**BASE, "authority": {"active_task": str(Path(sys.executable).resolve())}}),
            "authority escapes project": json.dumps(
                {**BASE, "authority": {"active_task": "../../outside.md"}}),
            "cwd escapes project": json.dumps({**BASE, "dispatch": {"command": ["x"], "cwd": "../.."}}),
        }
        for label, text in cases.items():
            with self.subTest(label=label):
                project(self.tmp)
                (self.tmp / "agentops-dispatch.json").write_text(text, encoding="utf-8")
                result = self.resolve()
                self.assertEqual(result["status"], "STOP_INVALID_CONFIG", result)
                self.assertTrue(result["errors"])

    # --- conflicting -----------------------------------------------------
    def test_two_configuration_files_conflict(self):
        project(self.tmp)
        project(self.tmp, name=".agentops/dispatch.json")
        result = self.resolve()
        self.assertEqual(result["status"], "STOP_CONFLICT")
        self.assertIn("multiple configuration files", result["errors"][0])

    def test_explicit_config_and_environment_that_differ_conflict(self):
        first = project(self.tmp)
        second = project(self.tmp, name="other.json")
        result = self.resolve(explicit=first, env={dc.ENV_CONFIG: str(second)})
        self.assertEqual(result["status"], "STOP_CONFLICT")

    def test_environment_alone_selects_the_file(self):
        project(self.tmp)
        other = project(self.tmp, name="elsewhere/custom.json")
        # a second discoverable file would conflict; the environment removes the ambiguity
        result = self.resolve(env={dc.ENV_CONFIG: str(other)})
        self.assertIn(result["status"], {"READY", "STOP_AUTHORITY_MISSING"})
        self.assertNotEqual(result["status"], "STOP_CONFLICT")

    # --- command line ----------------------------------------------------
    def test_exit_codes_distinguish_go_from_stop(self):
        project(self.tmp)
        self.assertEqual(dc.main(["--project", str(self.tmp)]), 0)
        (self.tmp / "agentops-dispatch.json").unlink()
        self.assertEqual(dc.main(["--project", str(self.tmp)]), 3)

    def test_output_is_machine_readable_and_the_resolver_never_runs_the_command(self):
        marker = self.tmp / "ran.txt"
        config = {**BASE, "dispatch": {"command": [sys.executable, "-c",
                  f"open({str(marker)!r}, 'w').write('x')"]}}
        project(self.tmp, config)
        script = Path(dc.__file__)
        out = subprocess.run([sys.executable, str(script), "--project", str(self.tmp)],
                             capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(out.returncode, 0)
        data = json.loads(out.stdout)
        self.assertEqual(data["status"], "READY")
        self.assertFalse(marker.exists())

    def test_the_resolver_is_read_only(self):
        project(self.tmp)
        before = sorted(str(p.relative_to(self.tmp)) for p in self.tmp.rglob("*"))
        self.resolve()
        self.assertEqual(before, sorted(str(p.relative_to(self.tmp)) for p in self.tmp.rglob("*")))

    def test_no_project_specific_identifiers_are_built_in(self):
        source = Path(dc.__file__).read_text(encoding="utf-8").lower()
        for banned in ("score2gp", "tticom", "orca", "/home/"):
            self.assertNotIn(banned, source)


if __name__ == "__main__":
    unittest.main()
