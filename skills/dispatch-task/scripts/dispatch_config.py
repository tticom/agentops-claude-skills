#!/usr/bin/env python3
"""Resolve a consuming project's dispatch configuration. Read-only.

This helper finds and validates the project-owned ``agentops-dispatch.json`` and
reports what the dispatcher skill may do next. It never runs the configured
command, never reads task state, and never writes anything: task state belongs to
the project's own task runtime. It exists so "no configuration",
"broken configuration" and "conflicting configuration" are detected the same way
every time instead of being improvised in prose.

Statuses
  READY                   configuration valid; a dispatch command is configured
  HANDOFF_ONLY            configuration valid; no runtime command, so hand off
  STOP_NO_CONFIG          no configuration found
  STOP_CONFLICT           more than one, differing, configuration was supplied
  STOP_INVALID_CONFIG     configuration unreadable or malformed
  STOP_AUTHORITY_MISSING  a declared authority document does not exist
  STOP_INVALID_AUTHORITY  a declared authority document cannot be read faithfully
  STOP_NO_ACTIVE_TASK     the task authority says no task is approved

Exit status: 0 for READY and HANDOFF_ONLY, 3 for every STOP_* status.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

SCHEMA = "agentops-dispatch.v1"
ENV_CONFIG = "AGENTOPS_DISPATCH_CONFIG"
CANDIDATES = ("agentops-dispatch.json", ".agentops/dispatch.json")
TOP_KEYS = {"schema", "project", "authority", "repositories", "identity", "dispatch"}
AUTHORITY_KEYS = {"active_task", "control_documents", "no_task_markers"}
IDENTITY_KEYS = {"profile", "role_policy"}
DISPATCH_KEYS = {"command", "cwd"}
STOP_STATUSES = {
    "STOP_NO_CONFIG",
    "STOP_CONFLICT",
    "STOP_INVALID_CONFIG",
    "STOP_AUTHORITY_MISSING",
    "STOP_INVALID_AUTHORITY",
    "STOP_NO_ACTIVE_TASK",
}


class ConfigError(Exception):
    """Carries the STOP status that the problem maps to."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ConfigError("STOP_INVALID_CONFIG", f"{field} must be a list of non-empty strings")
    return [item.strip() for item in value]


def _contained(base: Path, relative: str, field: str) -> Path:
    """Resolve ``relative`` under the project root; refuse absolute paths and escapes."""
    candidate = Path(relative)
    if candidate.is_absolute() or candidate.drive:
        raise ConfigError("STOP_INVALID_CONFIG", f"{field} must be a path relative to the project root")
    resolved = (base / candidate).resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError as error:
        raise ConfigError("STOP_INVALID_CONFIG", f"{field} escapes the project directory") from error
    return resolved


def _read_authority(path: Path, field: str) -> str:
    """Read an authority document strictly; anything less than a faithful read is a stop."""
    try:
        return path.read_text(encoding="utf-8-sig")  # a byte-order mark is not corruption
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigError(
            "STOP_INVALID_AUTHORITY",
            f"{field} {path} cannot be read faithfully: {error}",
        ) from error


def discover(project: Path, explicit: Path | None, env: dict[str, str]) -> Path:
    """Find exactly one configuration file, or explain why not."""
    supplied = {}
    if explicit is not None:
        supplied["--config"] = explicit.resolve()
    if env.get(ENV_CONFIG):
        supplied[ENV_CONFIG] = Path(env[ENV_CONFIG]).resolve()
    if len(set(supplied.values())) > 1:
        detail = ", ".join(f"{key}={value}" for key, value in supplied.items())
        raise ConfigError("STOP_CONFLICT", f"explicit and environment configuration differ: {detail}")
    if supplied:
        path = next(iter(supplied.values()))
        if not path.is_file():
            raise ConfigError("STOP_NO_CONFIG", f"configuration file not found: {path}")
        return path
    found = [project / name for name in CANDIDATES if (project / name).is_file()]
    if not found:
        raise ConfigError(
            "STOP_NO_CONFIG",
            f"no {' or '.join(CANDIDATES)} under {project}; the project must supply one",
        )
    if len(found) > 1:
        raise ConfigError(
            "STOP_CONFLICT",
            "multiple configuration files found: " + ", ".join(str(item) for item in found),
        )
    return found[0].resolve()


def load(path: Path, project: Path) -> dict[str, Any]:
    """Validate the configuration and return the resolved facts.

    Relative paths inside the configuration resolve against ``project`` (the
    project root), not against the directory that happens to hold the file, so
    ``.agentops/dispatch.json`` and ``agentops-dispatch.json`` mean the same thing.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ConfigError("STOP_INVALID_CONFIG", f"cannot read {path}: {error}") from error
    if not isinstance(data, dict):
        raise ConfigError("STOP_INVALID_CONFIG", "configuration root must be an object")
    if data.get("schema") != SCHEMA:
        raise ConfigError("STOP_INVALID_CONFIG", f"schema must be {SCHEMA!r}")
    unknown = sorted(set(data) - TOP_KEYS)
    if unknown:
        raise ConfigError("STOP_INVALID_CONFIG", f"unknown keys: {unknown}")
    base = project

    name = data.get("project")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError("STOP_INVALID_CONFIG", "project must be a non-empty string")

    authority = data.get("authority")
    if not isinstance(authority, dict):
        raise ConfigError("STOP_INVALID_CONFIG", "authority must be an object")
    unknown = sorted(set(authority) - AUTHORITY_KEYS)
    if unknown:
        raise ConfigError("STOP_INVALID_CONFIG", f"unknown authority keys: {unknown}")
    active = authority.get("active_task")
    if not isinstance(active, str) or not active.strip():
        raise ConfigError(
            "STOP_INVALID_CONFIG",
            "authority.active_task must be exactly one path (a list is ambiguous)",
        )
    active_path = _contained(base, active, "authority.active_task")
    controls = [
        _contained(base, item, "authority.control_documents")
        for item in _string_list(authority.get("control_documents", []), "authority.control_documents")
    ]
    markers = _string_list(authority.get("no_task_markers", []), "authority.no_task_markers")

    repositories = _string_list(data.get("repositories", []), "repositories")
    if len(set(repositories)) != len(repositories):
        raise ConfigError("STOP_INVALID_CONFIG", "repositories contains duplicates")
    for repo in repositories:
        owner, _, repo_name = repo.partition("/")
        if not owner or not repo_name or "/" in repo_name:
            raise ConfigError("STOP_INVALID_CONFIG", f"repository {repo!r} must be owner/name")

    identity = data.get("identity", {})
    if not isinstance(identity, dict) or set(identity) - IDENTITY_KEYS:
        raise ConfigError("STOP_INVALID_CONFIG", "identity may only contain profile and role_policy")
    identity_paths = {
        key: str(_contained(base, value, f"identity.{key}"))
        for key, value in identity.items()
        if isinstance(value, str) and value.strip()
    }
    if len(identity_paths) != len(identity):
        raise ConfigError("STOP_INVALID_CONFIG", "identity values must be non-empty paths")

    command = None
    dispatch = data.get("dispatch")
    if dispatch is not None:
        if not isinstance(dispatch, dict) or set(dispatch) - DISPATCH_KEYS:
            raise ConfigError("STOP_INVALID_CONFIG", "dispatch may only contain command and cwd")
        argv = _string_list(dispatch.get("command"), "dispatch.command")
        if not argv:
            raise ConfigError("STOP_INVALID_CONFIG", "dispatch.command must not be empty")
        cwd = _contained(base, dispatch.get("cwd", "."), "dispatch.cwd")
        command = {"argv": argv, "cwd": str(cwd)}

    missing = [str(item) for item in [active_path, *controls] if not item.is_file()]
    if missing:
        raise ConfigError("STOP_AUTHORITY_MISSING", "authority document(s) not found: " + ", ".join(missing))

    # Authority is read strictly. Decoding with replacement characters would let a
    # corrupted file quietly stop matching a no-task marker and dispatch anyway.
    text = _read_authority(active_path, "authority.active_task")
    for control in controls:
        _read_authority(control, "authority.control_documents")
    no_active = any(marker in text for marker in markers)

    return {
        "project": name.strip(),
        "authority": {
            "active_task": str(active_path),
            "control_documents": [str(item) for item in controls],
            "no_active_task": no_active,
        },
        "repositories": repositories,
        "identity": identity_paths,
        "command": command,
    }


def resolve(project: Path, explicit: Path | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    env = dict(os.environ) if env is None else env
    result: dict[str, Any] = {
        "status": "",
        "mode": None,
        "config_path": None,
        "executed": False,
        "notice": "",
        "errors": [],
    }
    try:
        path = discover(project, explicit, env)
        result["config_path"] = str(path)
        facts = load(path, project.resolve())
    except ConfigError as error:
        result.update(status=error.status, errors=[str(error)])
        result["notice"] = "Stop. Do not infer a task, replay an earlier prompt, or treat a backlog as authority."
        return result
    result.update(facts)
    if facts["authority"]["no_active_task"]:
        result["status"] = "STOP_NO_ACTIVE_TASK"
        result["errors"] = ["the task authority records that no task is approved"]
        result["notice"] = "Report this and stop. A backlog item or recorded candidate is not permission."
    elif facts["command"]:
        result.update(status="READY", mode="execute")
        result["notice"] = (
            "Run the configured command exactly as given, without a shell; its output is authoritative. "
            "This resolver did not run it."
        )
    else:
        result.update(status="HANDOFF_ONLY", mode="handoff")
        result["notice"] = (
            "No runtime command is configured. Provide a concrete handoff and state plainly that "
            "no execution occurred."
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="project root (default: cwd)")
    parser.add_argument("--config", type=Path, help=f"explicit configuration file (or set {ENV_CONFIG})")
    args = parser.parse_args(argv)
    result = resolve(args.project.resolve(), args.config)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 3 if result["status"] in STOP_STATUSES else 0


if __name__ == "__main__":
    sys.exit(main())
