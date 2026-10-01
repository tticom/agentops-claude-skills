#!/usr/bin/env python3
"""Pre-mutation safety check for an agent about to commit or push.

Prints repository, branch, remote and status. Exits 1 when the state is unsafe:
protected branch, detached HEAD, unexpected branch or remote. Exit 64 on usage
errors. Standard library and git only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

PROTECTED = ("main", "master")


def git(repo: Path, *args: str) -> tuple[int, str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.returncode, result.stdout.strip()


def remote_slug(url: str) -> str:
    """Return owner/repo from an https or ssh GitHub URL, else the URL itself."""
    match = re.search(r"github\.com[:/]+([^/]+/[^/]+?)(?:\.git)?/?$", url)
    return match.group(1) if match else url


def check(
    repo: Path,
    expect_branch: str | None = None,
    expect_remote: str | None = None,
    protected: tuple[str, ...] = PROTECTED,
) -> list[str]:
    """Return a list of problems; empty means safe."""
    problems: list[str] = []
    code, top = git(repo, "rev-parse", "--show-toplevel")
    if code:
        return ["NOT_A_GIT_REPOSITORY"]
    code, branch = git(repo, "symbolic-ref", "--short", "-q", "HEAD")
    if code or not branch:
        problems.append("DETACHED_HEAD")
    elif branch in protected:
        problems.append(f"PROTECTED_BRANCH {branch}")
    if expect_branch and branch != expect_branch:
        problems.append(f"UNEXPECTED_BRANCH expected={expect_branch} actual={branch or 'detached'}")
    if expect_remote:
        code, url = git(repo, "remote", "get-url", "origin")
        slug = remote_slug(url) if not code else ""
        if slug.lower() != expect_remote.lower():
            problems.append(f"UNEXPECTED_REMOTE expected={expect_remote} actual={slug or 'none'}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--expect-branch")
    parser.add_argument("--expect-remote", help="owner/repo the origin must point at")
    parser.add_argument("--protected", action="append", help="protected branch name (repeatable)")
    args = parser.parse_args(argv)

    protected = tuple(args.protected) if args.protected else PROTECTED
    problems = check(args.repo, args.expect_branch, args.expect_remote, protected)

    _, top = git(args.repo, "rev-parse", "--show-toplevel")
    _, branch = git(args.repo, "symbolic-ref", "--short", "-q", "HEAD")
    _, remote = git(args.repo, "remote", "get-url", "origin")
    _, status = git(args.repo, "status", "--porcelain=v1")
    print(f"repository: {top}")
    print(f"branch: {branch or 'DETACHED'}")
    print(f"origin: {remote_slug(remote) if remote else 'none'}")
    print(f"changed paths: {len(status.splitlines()) if status else 0}")
    for problem in problems:
        print(f"UNSAFE {problem}")
    if problems:
        return 1
    print("SAFE_GIT_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
