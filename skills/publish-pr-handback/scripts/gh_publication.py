#!/usr/bin/env python3
"""Shared GitHub publication helpers: pagination, strict re-reads, text comparison.

Both publishers (the review publisher and the author-handback publisher) must prove
a publication by reading the persisted object back from GitHub, and must find an
existing marked comment wherever it sits in a long thread. This module holds that
logic once. It is vendored byte-for-byte into the skills that use it (a test fails
if a copy drifts), so every skill stays self-contained.

Every function takes the caller's ``run_json`` so the caller's own GitHub client (and
its tests) stay in control. A write response is never evidence: verification always
uses a separate read.
"""

from __future__ import annotations

import subprocess
from typing import Any, Callable

PAGE_SIZE = 100
# Safety bound on pagination (100 pages x 100 items); reaching it is a failure, not a pass.
MAX_PAGES = 100

RunJson = Callable[..., Any]


class PublicationError(RuntimeError):
    """A publication could not be proved from the persisted remote state."""


def normalize_text(value: Any) -> str:
    """Line endings and outer whitespace are not meaningful differences."""
    if not isinstance(value, str):
        return ""
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def same_text(left: Any, right: Any) -> bool:
    return isinstance(left, str) and isinstance(right, str) and normalize_text(left) == normalize_text(right)


def fetch(run_json: RunJson, endpoint: str, what: str) -> Any:
    """GET ``endpoint``. Any failure to retrieve or parse it is a PublicationError."""
    try:
        return run_json("gh", "api", endpoint)
    except (subprocess.CalledProcessError, OSError, ValueError) as error:  # ValueError: bad JSON
        raise PublicationError(f"cannot re-read {what} ({endpoint}): {error}") from error


def fetch_object(run_json: RunJson, endpoint: str, what: str) -> dict[str, Any]:
    value = fetch(run_json, endpoint, what)
    if not isinstance(value, dict):
        raise PublicationError(f"{what} ({endpoint}) did not return an object")
    return value


def paginate(run_json: RunJson, endpoint: str, what: str) -> list[dict[str, Any]]:
    """Return every item of a list endpoint, following pages until a short one.

    A page that is exactly full is followed by one more request, so a list whose
    length is a multiple of the page size is still read completely.

    Every element must be an object. A malformed element is an error, never silently
    dropped: filtering would turn a remote ``[null]`` into ``[]`` and let an exact
    cardinality check pass on a collection that actually held something unexpected.
    """
    items: list[dict[str, Any]] = []
    separator = "&" if "?" in endpoint else "?"
    for page in range(1, MAX_PAGES + 1):
        chunk = fetch(run_json, f"{endpoint}{separator}per_page={PAGE_SIZE}&page={page}", what)
        if not isinstance(chunk, list):
            raise PublicationError(f"{what} page {page} was not a list: {str(chunk)[:80]!r}")
        for position, item in enumerate(chunk):
            if not isinstance(item, dict):
                raise PublicationError(
                    f"{what} page {page} item {position} is not an object: {str(item)[:80]!r}"
                )
        items.extend(chunk)
        if len(chunk) < PAGE_SIZE:
            return items
    raise PublicationError(f"{what} exceeded {MAX_PAGES} pages; refusing to guess")


def login_of(item: dict[str, Any]) -> str:
    return str((item.get("user") or {}).get("login", "")).lower()


def marked_comments(comments: list[dict[str, Any]], *, actor: str, marker: str) -> list[dict[str, Any]]:
    """Comments written by ``actor`` (case-insensitive) that carry ``marker``."""
    return [
        comment for comment in comments
        if login_of(comment) == actor.lower() and marker in str(comment.get("body", ""))
    ]


def verify_comment(
    remote: dict[str, Any], *, comment_id: int, actor: str, marker: str, body: str, pr: int,
    label: str = "comment",
) -> None:
    """Prove a persisted issue comment is the one we wrote, on this PR, unaltered."""
    if remote.get("id") != comment_id:
        raise PublicationError(f"re-read {label} id {remote.get('id')!r} is not the published {comment_id}")
    if login_of(remote) != actor.lower():
        raise PublicationError(f"persisted {label} author {login_of(remote)!r} is not {actor.lower()!r}")
    if not str(remote.get("issue_url", "")).endswith(f"/issues/{pr}"):
        raise PublicationError(f"persisted {label} does not belong to pull request #{pr}")
    remote_body = remote.get("body", "")
    if marker not in str(remote_body):
        raise PublicationError(f"persisted {label} lost its marker")
    if not same_text(remote_body, body):
        raise PublicationError(f"persisted {label} body differs from the published body")


def verify_single_marked(
    comments: list[dict[str, Any]], *, actor: str, marker: str, comment_id: int, label: str = "comment"
) -> None:
    """Exactly one marked comment by ``actor`` may exist, and it must be ``comment_id``."""
    found = marked_comments(comments, actor=actor, marker=marker)
    if len(found) != 1:
        ids = [comment.get("id") for comment in found]
        raise PublicationError(f"more than one marked {label} exists for this head: ids {ids}"
                               if found else f"the marked {label} is not present after publication")
    if found[0].get("id") != comment_id:
        raise PublicationError(f"the only marked {label} is {found[0].get('id')}, not the published {comment_id}")
