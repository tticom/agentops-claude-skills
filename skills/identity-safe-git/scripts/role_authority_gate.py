#!/usr/bin/env python3
"""Fail-closed authority gate for reviewer metadata, repository writes, and merges.

Identities come from a project-owned policy file, never from this script. The
gate answers one question: may this actor perform this operation on this pull
request? Anything not explicitly permitted is denied.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, NamedTuple

REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
POLICY_ENV = "AGENTOPS_ROLE_POLICY"
POLICY_KEYS = ("reviewers", "never_merge", "maintainers", "delegated_mergers")


class AuthorityDenied(ValueError):
    """Raised when the requested operation is outside the actor's authority."""


class Policy(NamedTuple):
    reviewers: frozenset[str]
    never_merge: frozenset[str]
    maintainers: frozenset[str]
    delegated_mergers: frozenset[str]


def normalize_login(value: str | None, field: str) -> str:
    if value is None or not value.strip():
        raise AuthorityDenied(f"{field} is required")
    return value.strip().lower()


def parse_policy(data: Any) -> Policy:
    """Validate a policy mapping. Every problem is a denial, never a default."""
    if not isinstance(data, dict):
        raise AuthorityDenied("invalid policy: root must be an object")
    unknown = sorted(set(data) - set(POLICY_KEYS))
    if unknown:
        raise AuthorityDenied(f"invalid policy: unknown keys {unknown}")
    groups: dict[str, frozenset[str]] = {}
    for key in POLICY_KEYS:
        values = data.get(key, [])
        if not isinstance(values, list) or any(
            not isinstance(item, str) or not item.strip() for item in values
        ):
            raise AuthorityDenied(f"invalid policy: {key} must be a list of non-empty logins")
        groups[key] = frozenset(item.strip().lower() for item in values)
    policy = Policy(**groups)
    if policy.never_merge & (policy.maintainers | policy.delegated_mergers):
        raise AuthorityDenied("invalid policy: an identity is both no-merge and a merger")
    if policy.maintainers & policy.delegated_mergers:
        raise AuthorityDenied("invalid policy: an identity is both maintainer and delegated merger")
    return policy


def load_policy(path: str | os.PathLike[str] | None = None) -> Policy:
    """Load the policy from ``path`` or the ``AGENTOPS_ROLE_POLICY`` variable."""
    location = path or os.environ.get(POLICY_ENV)
    if not location:
        raise AuthorityDenied(
            f"a role policy is required (--policy or {POLICY_ENV}); refusing to guess identities"
        )
    try:
        data = json.loads(Path(location).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuthorityDenied(f"invalid policy: cannot read {location}: {error}") from error
    return parse_policy(data)


def validate(
    *,
    actor: str,
    operation: str,
    repo: str,
    pr: int,
    policy: Policy,
    pr_author: str | None = None,
    authorization_actor: str | None = None,
    authorization_repo: str | None = None,
    authorization_pr: int | None = None,
    expected_head: str | None = None,
    authorization_head: str | None = None,
    current_turn_explicit: bool = False,
) -> str:
    actor = normalize_login(actor, "actor")
    if not REPO.fullmatch(repo):
        raise AuthorityDenied("repo must be owner/name")
    if pr <= 0:
        raise AuthorityDenied("pr must be positive")

    if operation == "review-metadata":
        if actor not in policy.reviewers:
            raise AuthorityDenied(f"{actor} is not an authorized reviewer")
        author = normalize_login(pr_author, "pr_author")
        if actor == author:
            raise AuthorityDenied("self-review is forbidden")
        return "review metadata allowed"

    if operation == "reviewed-repo-write":
        raise AuthorityDenied("review sessions are comment-only; repository writes are forbidden")

    if operation != "merge":
        raise AuthorityDenied(f"unsupported operation: {operation}")

    if actor in policy.never_merge:
        raise AuthorityDenied(f"{actor} has an unconditional no-merge role")
    if actor in policy.maintainers:
        return "maintainer merge allowed"
    if actor not in policy.delegated_mergers:
        raise AuthorityDenied(f"{actor} has no merge authority")

    authorizer = normalize_login(authorization_actor, "authorization_actor")
    if authorizer not in policy.maintainers:
        raise AuthorityDenied(f"{actor} requires authorization from a maintainer")
    if not current_turn_explicit:
        raise AuthorityDenied(f"{actor} requires current-turn explicit authorization")
    if authorization_repo != repo or authorization_pr != pr:
        raise AuthorityDenied("authorization must name this exact repository and PR")
    if expected_head is None or not FULL_SHA.fullmatch(expected_head):
        raise AuthorityDenied("merge requires the exact current full head SHA")
    if authorization_head != expected_head:
        raise AuthorityDenied("authorization does not match the exact current head")
    return "delegated merge allowed for this exact PR only"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--policy", type=Path, help=f"role policy JSON (or set {POLICY_ENV})")
    parser.add_argument("--actor", required=True)
    parser.add_argument(
        "--operation",
        required=True,
        choices=("review-metadata", "reviewed-repo-write", "merge"),
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--pr-author")
    parser.add_argument("--authorization-actor")
    parser.add_argument("--authorization-repo")
    parser.add_argument("--authorization-pr", type=int)
    parser.add_argument("--expected-head")
    parser.add_argument("--authorization-head")
    parser.add_argument("--current-turn-explicit", action="store_true")
    args = parser.parse_args()

    try:
        reason = validate(
            actor=args.actor,
            operation=args.operation,
            repo=args.repo,
            pr=args.pr,
            policy=load_policy(args.policy),
            pr_author=args.pr_author,
            authorization_actor=args.authorization_actor,
            authorization_repo=args.authorization_repo,
            authorization_pr=args.authorization_pr,
            expected_head=args.expected_head,
            authorization_head=args.authorization_head,
            current_turn_explicit=args.current_turn_explicit,
        )
    except AuthorityDenied as error:
        raise SystemExit(f"ROLE_AUTHORITY_GATE=DENY: {error}") from error
    print(f"ROLE_AUTHORITY_GATE=PASS: {reason}")


if __name__ == "__main__":
    main()
