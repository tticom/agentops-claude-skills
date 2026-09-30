#!/usr/bin/env python3
"""Refuse an APPROVE while the publishing reviewer's own review threads are unresolved.

The reviewer owns its own threads: before approving, it re-checks each of its earlier
unresolved threads at the new head, replies, and resolves the verified-fixed ones. The
author never resolves a reviewer's threads, so an approval published over the reviewer's
own open threads leaves the merge blocked on an unresolved-thread check.

The gate fails closed: a thread query that errors, is paged past its bound, or returns a
malformed shape refuses the approval rather than assuming there are no threads. There is
deliberately no override flag. Only the publishing login's own threads are considered,
and only an APPROVE is gated; nothing here ever resolves, replies to, or edits a thread.

Every function takes the caller's ``run_json`` so the caller's own GitHub client (and its
tests) stay in control, as in ``gh_publication``.
"""

from __future__ import annotations

import subprocess
from typing import Any, Callable

RunJson = Callable[..., Any]

# Safety bound on pagination (100 pages x 100 threads); reaching it is a failure.
MAX_PAGES = 100

THREADS_QUERY = """
query($owner: String!, $name: String!, $pr: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $pr) {
      reviewThreads(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          isResolved
          path
          line
          comments(first: 1) { nodes { author { login } } }
        }
      }
    }
  }
}
""".strip()


class ThreadGateError(RuntimeError):
    """The approval is refused, or the thread state could not be established."""


def _fetch_page(run_json: RunJson, owner: str, name: str, pr: int, cursor: str | None) -> dict[str, Any]:
    args = ["gh", "api", "graphql", "-f", f"query={THREADS_QUERY}", "-f", f"owner={owner}",
            "-f", f"name={name}", "-F", f"pr={pr}"]
    if cursor:
        args += ["-f", f"cursor={cursor}"]
    try:
        response = run_json(*args)
    except (subprocess.CalledProcessError, OSError, ValueError) as error:  # ValueError: bad JSON
        raise ThreadGateError(f"cannot read the pull request's review threads: {error}") from error
    if not isinstance(response, dict) or response.get("errors"):
        raise ThreadGateError(f"the review-thread query failed: {str(response)[:200]!r}")
    try:
        threads = response["data"]["repository"]["pullRequest"]["reviewThreads"]
        nodes, info = threads["nodes"], threads["pageInfo"]
    except (KeyError, TypeError) as error:
        raise ThreadGateError("the review-thread query returned an unexpected shape") from error
    if not isinstance(nodes, list) or not isinstance(info, dict):
        raise ThreadGateError("the review-thread query returned an unexpected shape")
    # Only an explicit False ends paging and only an explicit True continues it; a missing,
    # null or non-Boolean value is an unexpected shape, never "the last page".
    if not isinstance(info.get("hasNextPage"), bool):
        raise ThreadGateError(
            f"the review-thread query returned an unexpected shape: hasNextPage is {info.get('hasNextPage')!r}"
        )
    return {"nodes": nodes, "hasNextPage": info["hasNextPage"], "endCursor": info.get("endCursor")}


def _opening_author(node: dict[str, Any]) -> str | None:
    """The lower-cased login that opened the thread, or None when it cannot be established."""
    comments = (node.get("comments") or {}).get("nodes")
    if not isinstance(comments, list) or not comments or not isinstance(comments[0], dict):
        return None
    login = (comments[0].get("author") or {}).get("login")
    return login.lower() if isinstance(login, str) and login.strip() else None


def own_unresolved_threads(run_json: RunJson, repo: str, pr: int, actor: str) -> list[dict[str, Any]]:
    """Every unresolved review thread opened by ``actor`` (case-insensitive), all pages read."""
    owner, _, name = repo.partition("/")
    if not owner or not name or "/" in name:
        raise ThreadGateError(f"repository must be owner/name, not {repo!r}")
    found: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(MAX_PAGES):
        page = _fetch_page(run_json, owner, name, pr, cursor)
        for node in page["nodes"]:
            if not isinstance(node, dict) or not isinstance(node.get("isResolved"), bool) \
                    or not isinstance(node.get("id"), str):
                raise ThreadGateError(f"a review thread is malformed: {str(node)[:120]!r}")
            if node["isResolved"]:
                continue
            author = _opening_author(node)
            if author is None:
                # Ownership is unknown (a deleted account, or no opening comment): refuse
                # rather than assume the thread is someone else's.
                raise ThreadGateError(
                    f"the author of unresolved review thread {describe(node)} cannot be established "
                    "(deleted account or no opening comment); refusing to guess its ownership"
                )
            if author == actor.lower():
                found.append(node)
        if page["hasNextPage"] is not True:
            return found
        cursor = page["endCursor"]
        if not isinstance(cursor, str) or not cursor:
            raise ThreadGateError("the review-thread query is paged but returned no cursor")
    raise ThreadGateError(f"review threads exceeded {MAX_PAGES} pages; refusing to guess")


def describe(thread: dict[str, Any]) -> str:
    where = f" ({thread['path']}:{thread['line']})" if thread.get("path") and thread.get("line") else ""
    return f"{thread['id']}{where}"


def require_no_own_unresolved_threads(run_json: RunJson, repo: str, pr: int, actor: str, verdict: str) -> None:
    """Raise ``ThreadGateError`` for an APPROVE over the actor's own unresolved threads.

    REQUEST_CHANGES-class verdicts (CHANGES_REQUESTED, CANNOT_VERIFY) are never gated.
    """
    if verdict != "APPROVE":
        return
    threads = own_unresolved_threads(run_json, repo, pr, actor)
    if threads:
        raise ThreadGateError(
            f"APPROVE refused: {len(threads)} unresolved review thread(s) authored by {actor} remain on "
            f"#{pr}: {', '.join(describe(t) for t in threads)}. Re-check each at the exact head; reply "
            "'Verified fixed at <short-sha>: <evidence>' and resolve the verified-fixed ones, or publish "
            "CHANGES_REQUESTED if any is not fixed"
        )
