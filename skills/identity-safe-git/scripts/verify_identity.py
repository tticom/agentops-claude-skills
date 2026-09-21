#!/usr/bin/env python3
"""Cross-platform identity gate: prove who is acting before any repository mutation.

Checks the operating-system user, home directory, Git-host login, Git author
identity, repository location and worktree state against an expected profile.
Any mismatch is a no-write stop. Works on Windows, macOS and Linux with only
the Python standard library, ``git`` and the GitHub CLI (``gh``).

Exit status: 0 gate passed, 1 gate failed, 64 usage error.
"""

from __future__ import annotations

import argparse
import getpass
import json
import ntpath
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

PROFILE_FIELDS = ("os_user", "home", "host_login", "git_name", "git_email", "repo_prefix")
# Descriptive profile keys that document policy but are not checked by this gate.
PROFILE_INFORMATIONAL = ("protected_branches", "allowed_working_branches", "permissions")


class GateFailed(Exception):
    """A required identity fact did not match the profile."""


@dataclass(frozen=True)
class Expected:
    os_user: str
    home: str
    host_login: str
    git_name: str
    git_email: str
    repo_prefix: str
    # Accept the effective Git identity (local or global) instead of requiring the
    # global one and rejecting repository-local overrides. Off by default.
    allow_local_git_identity: bool = False


class Host:
    """Everything the gate observes. Tests substitute a fake."""

    is_windows = os.name == "nt"

    def os_user(self) -> str:
        return getpass.getuser()

    def home(self) -> str:
        return str(Path.home())

    def which(self, name: str) -> str | None:
        return shutil.which(name)

    def realpath(self, path: str) -> str:
        return os.path.realpath(path)

    def run(self, argv: Sequence[str], cwd: str | None = None) -> tuple[int, str]:
        try:
            completed = subprocess.run(
                list(argv),
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as error:
            return 127, str(error)
        return completed.returncode, completed.stdout.strip()


def _key(host: Host, value: str) -> str:
    """Path key that is case-insensitive on Windows and separator-normalised."""
    real = host.realpath(value)
    # ntpath (not os.path) so Windows semantics apply identically on every OS.
    return ntpath.normcase(real) if host.is_windows else real


def _within(host: Host, root: str, prefix: str) -> bool:
    root_key, prefix_key = _key(host, root), _key(host, prefix)
    sep = "\\" if host.is_windows else "/"
    return root_key == prefix_key or root_key.startswith(prefix_key.rstrip(sep) + sep)


def _names_equal(host: Host, actual: str, expected: str) -> bool:
    return actual.lower() == expected.lower() if host.is_windows else actual == expected


def _git_config(host: Host, scope: str | None, name: str, cwd: str) -> str:
    argv = ["git", "config"] + ([f"--{scope}"] if scope else []) + ["--get", name]
    code, out = host.run(argv, cwd=cwd)
    return out if code == 0 else ""


def verify(expected: Expected, host: Host | None = None, cwd: str | None = None) -> dict[str, str]:
    """Return the verified facts, or raise ``GateFailed`` naming the first mismatch."""
    host = host or Host()
    cwd = cwd or os.getcwd()

    actual_user = host.os_user()
    if not _names_equal(host, actual_user, expected.os_user):
        raise GateFailed(f"OS user is '{actual_user}', expected '{expected.os_user}'")

    home = host.home()
    if _key(host, home) != _key(host, expected.home):
        raise GateFailed(f"HOME is '{home}', expected '{expected.home}'")

    for tool in ("git", "gh"):
        if not host.which(tool):
            raise GateFailed(f"{tool} is unavailable")

    code, top = host.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd)
    if code != 0 or not top:
        raise GateFailed("current directory is not inside a Git worktree")
    if not _within(host, top, expected.repo_prefix):
        raise GateFailed(f"repository '{top}' is outside '{expected.repo_prefix}'")

    code, remote_login = host.run(["gh", "api", "user", "--jq", ".login"], cwd=cwd)
    if code != 0 or not remote_login:
        raise GateFailed("cannot read authenticated Git host identity")
    if remote_login.lower() != expected.host_login.lower():
        raise GateFailed(f"Git host login is '{remote_login}', expected '{expected.host_login}'")

    if expected.allow_local_git_identity:
        scope = None
        label = "effective"
    else:
        for field in ("user.name", "user.email"):
            if _git_config(host, "local", field, cwd):
                raise GateFailed(f"repository-local Git {field} override is set")
        scope = "global"
        label = "global"
    name = _git_config(host, scope, "user.name", cwd)
    if name != expected.git_name:
        raise GateFailed(f"{label} Git author name is '{name}', expected '{expected.git_name}'")
    email = _git_config(host, scope, "user.email", cwd)
    if email != expected.git_email:
        raise GateFailed(f"{label} Git author email is '{email}', expected '{expected.git_email}'")

    _, branch = host.run(["git", "branch", "--show-current"], cwd=cwd)
    _, head = host.run(["git", "rev-parse", "HEAD"], cwd=cwd)
    return {
        "os_user": actual_user,
        "home": home,
        "host_login": remote_login,
        "git_name": name,
        "git_email": email,
        "repo_root": top,
        "branch": branch,
        "head": head,
    }


def load_profile(path: Path | None, overrides: Mapping[str, Any]) -> dict[str, Any]:
    """Merge a JSON profile with command-line overrides; the command line wins."""
    values: dict[str, Any] = {}
    if path is not None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"cannot read profile {path}: {error}") from error
        if not isinstance(data, dict):
            raise ValueError("profile root must be an object")
        unknown = sorted(set(data) - set(PROFILE_FIELDS) - set(PROFILE_INFORMATIONAL))
        if unknown:
            raise ValueError(f"profile has unknown keys: {unknown}")
        values.update({key: data[key] for key in PROFILE_FIELDS if key in data})
    values.update({key: value for key, value in overrides.items() if value is not None})
    missing = [key for key in PROFILE_FIELDS if not isinstance(values.get(key), str) or not values[key]]
    if missing:
        raise ValueError(f"missing required identity fields: {missing}")
    return values


def main(argv: Sequence[str] | None = None, host: Host | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", type=Path, help="JSON identity profile (flags override it)")
    parser.add_argument("--os-user")
    parser.add_argument("--home")
    parser.add_argument("--host-login")
    parser.add_argument("--git-name")
    parser.add_argument("--git-email")
    parser.add_argument("--repo-prefix")
    parser.add_argument(
        "--allow-local-git-identity",
        action="store_true",
        help="compare the effective Git identity instead of requiring the global one",
    )
    args = parser.parse_args(argv)
    try:
        profile = load_profile(
            args.profile,
            {
                "os_user": args.os_user,
                "home": args.home,
                "host_login": args.host_login,
                "git_name": args.git_name,
                "git_email": args.git_email,
                "repo_prefix": args.repo_prefix,
            },
        )
    except ValueError as error:
        print(f"identity gate usage error: {error}", file=sys.stderr)
        return 64
    expected = Expected(**profile, allow_local_git_identity=args.allow_local_git_identity)
    try:
        facts = verify(expected, host)
    except GateFailed as error:
        print(f"identity gate failed: {error}", file=sys.stderr)
        return 1
    print("identity gate passed")
    for key, value in facts.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
