#!/usr/bin/env python3
"""Fail closed unless a review worktree is at one exact full commit SHA."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def git_head(worktree: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        raise SystemExit("REVIEW_HEAD_UNAVAILABLE")
    return result.stdout.strip().lower()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    args = parser.parse_args()

    expected = args.expected.strip().lower()
    if not FULL_SHA.fullmatch(expected):
        raise SystemExit("INVALID_EXPECTED_HEAD")

    local = git_head(args.worktree)
    if not FULL_SHA.fullmatch(local):
        raise SystemExit("INVALID_LOCAL_HEAD")
    if local != expected:
        raise SystemExit(f"REVIEW_HEAD_MISMATCH expected={expected} local={local}")

    print(f"REVIEW_HEAD_MATCH {local}")


if __name__ == "__main__":
    main()
