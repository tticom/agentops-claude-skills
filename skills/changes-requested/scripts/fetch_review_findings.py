#!/usr/bin/env python3
"""Fetch and parse review findings from GitHub for an open PR with CHANGES_REQUESTED."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REVIEWER_SUMMARY_PATTERN = re.compile(
    r"<!--\s*reviewer-summary:(?P<level>[a-zA-Z0-9_-]+):(?P<head>[0-9a-fA-F]{40})\s*-->"
)


def run_json(*args: str) -> Any:
    completed = subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


def run_json_paginated(base_endpoint: str) -> list[dict[str, Any]]:
    """Fetch all pages from a GitHub REST endpoint supporting pagination."""
    items: list[dict[str, Any]] = []
    page = 1
    delimiter = "&" if "?" in base_endpoint else "?"
    while True:
        url = f"{base_endpoint}{delimiter}per_page=100&page={page}"
        page_items = run_json("gh", "api", url)
        if not isinstance(page_items, list):
            break
        items.extend(page_items)
        if len(page_items) < 100:
            break
        page += 1
    return items


def fetch_review_threads_graphql(repo: str, pr: int) -> list[dict[str, Any]]:
    """Fetch review threads via GraphQL with thread resolution and pagination."""
    if "/" not in repo:
        raise ValueError(f"invalid repository format: {repo}")
    owner, repo_name = repo.split("/", 1)
    threads: list[dict[str, Any]] = []
    cursor: str | None = None

    query = """
    query($owner: String!, $repo: String!, $pr: Int!, $cursor: String) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $pr) {
          reviewThreads(first: 100, after: $cursor) {
            pageInfo {
              hasNextPage
              endCursor
            }
            nodes {
              id
              isResolved
              path
              line
              comments(first: 50) {
                nodes {
                  id
                  body
                  author { login }
                  createdAt
                }
              }
            }
          }
        }
      }
    }
    """
    while True:
        cmd = ["gh", "api", "graphql", "-f", f"query={query}",
               "-F", f"owner={owner}", "-F", f"repo={repo_name}", "-F", f"pr={pr}"]
        if cursor:
            cmd.extend(["-F", f"cursor={cursor}"])
        result = run_json(*cmd)
        pr_node = result.get("data", {}).get("repository", {}).get("pullRequest", {})
        threads_conn = pr_node.get("reviewThreads", {})
        nodes = threads_conn.get("nodes", [])
        threads.extend(nodes)

        page_info = threads_conn.get("pageInfo", {})
        if page_info.get("hasNextPage") and page_info.get("endCursor"):
            cursor = page_info["endCursor"]
        else:
            break

    return threads


def parse_summary_comment(comments: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find and parse the latest marked reviewer summary comment."""
    for comment in reversed(comments):
        body = comment.get("body", "")
        match = REVIEWER_SUMMARY_PATTERN.search(body)
        if match:
            return {
                "id": comment.get("id"),
                "author": comment.get("user", {}).get("login"),
                "level": match.group("level"),
                "reviewed_head": match.group("head"),
                "body": body,
                "created_at": comment.get("created_at"),
                "is_stale": False,
            }
    return None


VERDICT_STATES = {"APPROVED", "CHANGES_REQUESTED"}
DISCUSSION_STATE = "COMMENTED"


def _login(review: dict[str, Any]) -> str:
    return str((review.get("user") or {}).get("login", "")).lower()


def _order(review: dict[str, Any]) -> tuple[str, int]:
    """Server timestamp, then stable review id."""
    return (str(review.get("submitted_at") or review.get("created_at") or ""), review.get("id") or 0)


def verdict_reviews(reviews: list[dict[str, Any]], pr_author: str | None = None) -> list[dict[str, Any]]:
    """Reviews that can carry a verdict.

    Only a formal APPROVED or CHANGES_REQUESTED counts. A comment-only review is
    discussion, a dismissed or pending review is not a verdict, and the pull request
    author is not an independent reviewer, so their reviews never carry one.
    """
    author = (pr_author or "").lower()
    return [
        review for review in reviews
        if review.get("state") in VERDICT_STATES and not (author and _login(review) == author)
    ]


def outstanding_blockers(reviews: list[dict[str, Any]], pr_author: str | None = None) -> list[dict[str, Any]]:
    """Each independent reviewer's standing verdict, kept only where it is CHANGES_REQUESTED.

    A reviewer's own later APPROVED clears their blocker; another reviewer's approval,
    or anyone's comment, does not. Oldest first.
    """
    standing: dict[str, dict[str, Any]] = {}
    for review in sorted(verdict_reviews(reviews, pr_author), key=_order):
        standing[_login(review)] = review
    return sorted(
        (review for review in standing.values() if review.get("state") == "CHANGES_REQUESTED"),
        key=_order,
    )


def select_latest_review(reviews: list[dict[str, Any]], pr_author: str | None = None) -> dict[str, Any]:
    """The review that governs: the latest outstanding blocker, else the latest verdict.

    Ordered by server timestamp then review ID. A later comment-only review never
    supersedes a verdict.
    """
    blockers = outstanding_blockers(reviews, pr_author)
    if blockers:
        return blockers[-1]
    verdicts = verdict_reviews(reviews, pr_author)
    return max(verdicts, key=_order) if verdicts else {}


def discussion_reviews(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Comment-only reviews that say something, oldest first. Context, never findings."""
    return sorted(
        (
            review for review in reviews
            if review.get("state") == DISCUSSION_STATE and str(review.get("body") or "").strip()
        ),
        key=_order,
    )


def extract_thread_findings(threads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract open findings from GraphQL review threads, filtering out resolved threads."""
    findings = []
    for thread in threads:
        if thread.get("isResolved") is True:
            continue
        comments_nodes = thread.get("comments", {}).get("nodes", [])
        if not comments_nodes:
            continue
        primary_comment = comments_nodes[0]
        replies = [
            {
                "id": c.get("id"),
                "author": c.get("author", {}).get("login"),
                "body": c.get("body", "").strip(),
                "created_at": c.get("createdAt"),
            }
            for c in comments_nodes[1:]
        ]
        findings.append({
            "id": primary_comment.get("id"),
            "thread_id": thread.get("id"),
            "path": thread.get("path"),
            "line": thread.get("line"),
            "author": primary_comment.get("author", {}).get("login"),
            "body": primary_comment.get("body", "").strip(),
            "replies": replies,
        })
    return findings


def extract_inline_findings(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract primary review comments from REST API, grouping replies under root."""
    roots: dict[int, dict[str, Any]] = {}
    replies_by_root: dict[int, list[dict[str, Any]]] = {}

    for comment in comments:
        cid = comment.get("id")
        reply_to = comment.get("in_reply_to_id")
        if not reply_to:
            roots[cid] = {
                "id": cid,
                "path": comment.get("path"),
                "line": comment.get("line") or comment.get("original_line"),
                "author": comment.get("user", {}).get("login"),
                "body": comment.get("body", "").strip(),
                "commit_id": comment.get("commit_id"),
                "pull_request_review_id": comment.get("pull_request_review_id"),
                "replies": [],
            }
        else:
            replies_by_root.setdefault(reply_to, []).append({
                "id": cid,
                "author": comment.get("user", {}).get("login"),
                "body": comment.get("body", "").strip(),
            })

    for root_id, replies in replies_by_root.items():
        if root_id in roots:
            roots[root_id]["replies"].extend(replies)

    return sorted(roots.values(), key=lambda f: str(f.get("path", "")) + str(f.get("line", "")))


def _body_finding(index: int | str, review: dict[str, Any], location: str) -> dict[str, Any]:
    return {
        "index": index,
        "source": "review_body",
        "id": review.get("id"),
        "location": location,
        "author": (review.get("user") or {}).get("login"),
        "finding": str(review.get("body") or "").strip(),
        "defect_class": "review_summary",
        "reviewed_head_test": "TODO: verify against review summary requirements",
        "remediation_status": "OPEN",
        "disposition": "",
        "evidence": "",
    }


def build_remediation_ledger(
    pr_data: dict[str, Any],
    reviews: list[dict[str, Any]],
    inline_findings_or_comments: list[dict[str, Any]],
    issue_comments: list[dict[str, Any]],
    *,
    is_thread_nodes: bool = False,
) -> dict[str, Any]:
    """Assemble structured review findings and remediation ledger.

    Verdicts and discussion are kept apart. An independent reviewer's outstanding
    CHANGES_REQUESTED stays in the ledger, with its formal body, until that reviewer
    supersedes it; comment-only reviews (including the author's replies) are recorded
    as discussion and never displace a blocker.
    """
    pr_author = (pr_data.get("user") or {}).get("login")
    summary_data = parse_summary_comment(issue_comments)
    blockers = outstanding_blockers(reviews, pr_author)
    latest_review = select_latest_review(reviews, pr_author)
    discussion = discussion_reviews(reviews)
    if latest_review:
        review_state = latest_review["state"]
    elif discussion:
        review_state = "NO_VERDICT"
    else:
        review_state = "NO_REVIEW"

    pr_head = pr_data.get("head", {}).get("sha", "")
    review_commit = latest_review.get("commit_id")

    # Binding reviewed head: prefer the governing review's commit_id if present, else PR head
    reviewed_head = review_commit or pr_head
    review_is_stale = bool(review_commit and review_commit != pr_head)

    # Validate summary comment head against binding reviewed head
    if summary_data:
        summary_head = summary_data.get("reviewed_head")
        if summary_head and summary_head != reviewed_head:
            summary_data["is_stale"] = True

    if is_thread_nodes:
        inline_findings = extract_thread_findings(inline_findings_or_comments)
    else:
        # Check if items look like raw comments or already processed thread findings
        if inline_findings_or_comments and "replies" in inline_findings_or_comments[0]:
            inline_findings = inline_findings_or_comments
        else:
            inline_findings = extract_inline_findings(inline_findings_or_comments)

    ledger_items = []
    # Add inline comments
    for index, finding in enumerate(inline_findings, start=1):
        item: dict[str, Any] = {
            "index": index,
            "source": "inline_thread",
            "id": finding["id"],
            "location": f"{finding['path']}:{finding['line']}",
            "author": finding["author"],
            "finding": finding["body"],
            "defect_class": "unclassified",
            "reviewed_head_test": "TODO: add failing reproduction test on reviewed head",
            "remediation_status": "OPEN",
            "disposition": "",
            "evidence": "",
        }
        if finding.get("replies"):
            item["replies"] = finding["replies"]
        ledger_items.append(item)

    # Formal review bodies: the governing review first, then every other outstanding
    # blocker. A blocker recorded only in a formal body must not vanish from the ledger.
    body_sources = [latest_review] if latest_review else []
    body_sources += [blocker for blocker in reversed(blockers) if blocker is not latest_review]
    body_findings = []
    for review in body_sources:
        if not str(review.get("body") or "").strip():
            continue
        first = not body_findings
        body_findings.append(_body_finding(
            0 if first else f"0.{len(body_findings)}",
            review,
            "PR Review Body" if first else f"PR Review Body ({(review.get('user') or {}).get('login')})",
        ))
    ledger_items = body_findings + ledger_items

    return {
        "repository": pr_data.get("base", {}).get("repo", {}).get("full_name"),
        "pr": pr_data.get("number"),
        "pr_branch": pr_data.get("head", {}).get("ref"),
        "live_head": pr_head,
        "reviewed_head": reviewed_head,
        "review_is_stale": review_is_stale,
        "review_state": review_state,
        "reviewer": (latest_review.get("user") or {}).get("login"),
        "blocking_reviews": [
            {
                "id": blocker.get("id"),
                "reviewer": (blocker.get("user") or {}).get("login"),
                "commit_id": blocker.get("commit_id"),
                "submitted_at": blocker.get("submitted_at"),
                "stale": bool(blocker.get("commit_id") and blocker.get("commit_id") != pr_head),
            }
            for blocker in blockers
        ],
        "discussion": [
            {
                "id": review.get("id"),
                "author": (review.get("user") or {}).get("login"),
                "submitted_at": review.get("submitted_at"),
                "commit_id": review.get("commit_id"),
                "body": str(review.get("body")).strip(),
            }
            for review in discussion
        ],
        "summary": summary_data,
        "findings": ledger_items,
    }


def render_markdown_ledger(data: dict[str, Any]) -> str:
    lines = [
        f"# Review Remediation Ledger: {data.get('repository')} PR #{data.get('pr')}",
        "",
        f"- **PR Branch**: `{data.get('pr_branch')}`",
        f"- **Live PR Head**: `{data.get('live_head')}`",
        f"- **Reviewed Head**: `{data.get('reviewed_head')}`",
        f"- **Review State**: `{data.get('review_state')}`",
        f"- **Reviewer**: `{data.get('reviewer')}`",
    ]
    for blocker in data.get("blocking_reviews") or []:
        stale = " (STALE: older than the live head)" if blocker.get("stale") else ""
        lines.append(f"- **Blocking review**: `{blocker.get('reviewer')}` review {blocker.get('id')}{stale}")
    if data.get("review_is_stale"):
        lines.append("- **WARNING**: Review is STALE (evaluated on older commit than current PR head).")
    if data.get("summary") and data["summary"].get("is_stale"):
        lines.append(f"- **WARNING**: Reviewer summary comment is STALE (pinned to {data['summary']['reviewed_head']}).")

    lines.extend(["", "## Review Findings to Address", ""])
    if not data.get("findings"):
        lines.append("No unresolved review findings recorded.\n")
    for item in data.get("findings") or []:
        lines.extend([
            f"### Finding {item['index']} ({item['location']})",
            f"- **Source**: `{item['source']}` (ID: {item['id']})",
            f"- **Author**: `{item['author']}`",
            f"- **Finding**: {item['finding']}",
        ])
        if item.get("replies"):
            lines.append("- **Replies Context**:")
            for r in item["replies"]:
                lines.append(f"  - `@{r['author']}`: {r['body']}")
        lines.extend([
            f"- **Status**: `{item['remediation_status']}`",
            f"- **Reproduction Test**: `{item['reviewed_head_test']}`",
            "- **Disposition**: (fill in how this is addressed)",
            "- **Exact-Head Evidence**: (fill in pass/fail command output)",
            "",
        ])

    if data.get("discussion"):
        lines.extend(["", "## Discussion (not verdicts)", "",
                      "Comment-only reviews. They are context, not findings, and never supersede a blocking verdict.", ""])
        for note in data["discussion"]:
            lines.append(f"- `@{note.get('author')}` (review {note.get('id')}): {note.get('body')}")
        lines.append("")

    return "\n".join(lines)


def fetch_remote_data(repo: str, pr: int) -> dict[str, Any]:
    pr_data = run_json("gh", "api", f"repos/{repo}/pulls/{pr}")
    reviews = run_json_paginated(f"repos/{repo}/pulls/{pr}/reviews")
    issue_comments = run_json_paginated(f"repos/{repo}/issues/{pr}/comments")

    # Attempt GraphQL reviewThreads query first for exact resolution status
    try:
        threads = fetch_review_threads_graphql(repo, pr)
        return build_remediation_ledger(pr_data, reviews, threads, issue_comments, is_thread_nodes=True)
    except Exception:
        # Fallback to paginated REST comments
        inline_comments = run_json_paginated(f"repos/{repo}/pulls/{pr}/comments")
        return build_remediation_ledger(pr_data, reviews, inline_comments, issue_comments, is_thread_nodes=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch and format review findings for an open PR with changes requested."
    )
    parser.add_argument("--repo", required=True, help="Repository owner/name (e.g. example-org/example)")
    parser.add_argument("--pr", required=True, type=int, help="Pull request number")
    parser.add_argument("--json", action="store_true", help="Output raw JSON ledger")
    parser.add_argument("--output", type=Path, help="Write output to specified file path")
    args = parser.parse_args(argv)

    try:
        data = fetch_remote_data(args.repo, args.pr)
    except Exception as error:
        print(f"ERROR: failed to fetch review data: {error}", file=sys.stderr)
        return 1

    content = json.dumps(data, indent=2) if args.json else render_markdown_ledger(data)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content + "\n", encoding="utf-8")
        print(f"Review findings written to {args.output}")
    else:
        print(content)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
