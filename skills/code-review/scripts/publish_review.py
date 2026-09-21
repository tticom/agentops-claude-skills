#!/usr/bin/env python3
"""Publish an exact-head formal review and mandatory PR summary comment."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import gh_publication
import review_evidence_gate as evidence_gate
import role_authority_gate as role_gate


LEVELS = {"basic", "hard", "devils-advocate"}
VERDICTS = {"APPROVE", "CHANGES_REQUESTED", "CANNOT_VERIFY"}


def run_json(*args: str, stdin: dict[str, Any] | None = None) -> Any:
    completed = subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        input=None if stdin is None else json.dumps(stdin),
    )
    return json.loads(completed.stdout)


def validate_publication_text(
    *, level: str, verdict: str, expected_head: str, review_body: str, summary: str
) -> str:
    if level not in LEVELS:
        raise ValueError(f"unsupported review level: {level}")
    if expected_head not in review_body:
        raise ValueError("formal review body must contain the exact reviewed head")
    if verdict not in VERDICTS:
        raise ValueError(f"unsupported verdict: {verdict}")
    if f"Verdict: {verdict}" not in review_body:
        raise ValueError("formal review body must contain the exact verdict")
    marker = f"<!-- reviewer-summary:{level}:{expected_head} -->"
    if marker not in summary:
        raise ValueError(f"summary is missing marker {marker}")
    if expected_head not in summary:
        raise ValueError("summary must contain the exact reviewed head")
    if f"Verdict: {verdict}" not in summary:
        raise ValueError("summary must contain the exact verdict")
    return marker


def load_inline_comments(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("inline comments file must contain a JSON list")
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"inline comment {index} must be an object")
        required = {"path", "line", "side", "body"}
        if not required.issubset(item):
            raise ValueError(f"inline comment {index} lacks {sorted(required - set(item))}")
        if item["side"] not in {"LEFT", "RIGHT"}:
            raise ValueError(f"inline comment {index} has invalid side")
    return value


def publish_summary(repo: str, pr: int, *, actor: str, marker: str, summary: str) -> int:
    """Create or update the one marked summary comment; return its id.

    The whole comment list is searched, page by page, so an existing summary is
    updated wherever it sits and is never duplicated on a long thread.
    """
    comments = gh_publication.paginate(run_json, f"repos/{repo}/issues/{pr}/comments", "issue comments")
    existing = next(iter(gh_publication.marked_comments(comments, actor=actor, marker=marker)), None)
    if existing:
        written = run_json(
            "gh", "api", "--method", "PATCH",
            f"repos/{repo}/issues/comments/{existing['id']}", "--input", "-",
            stdin={"body": summary},
        )
    else:
        written = run_json(
            "gh", "api", "--method", "POST",
            f"repos/{repo}/issues/{pr}/comments", "--input", "-",
            stdin={"body": summary},
        )
    comment_id = written.get("id") if isinstance(written, dict) else None
    if not isinstance(comment_id, int):
        raise gh_publication.PublicationError("the summary write returned no comment id")
    return comment_id


def _location_matches(expected: dict[str, Any], remote: dict[str, Any], expected_head: str) -> bool:
    """True only when the persisted comment *proves* the requested location.

    Unknown is not equal: a missing or null line, side or commit never matches. GitHub
    reports ``line`` for a comment on the current diff and ``original_line`` for one
    that has since become outdated; either may supply the line, but one must.
    """
    line = remote.get("line") if remote.get("line") is not None else remote.get("original_line")
    return (
        remote.get("path") == expected["path"]
        and gh_publication.same_text(remote.get("body"), expected["body"])
        and isinstance(line, int)
        and not isinstance(line, bool)
        and line == expected["line"]
        and remote.get("side") == expected["side"]
        and remote.get("commit_id") == expected_head
    )


def verify_persisted_review(
    repo: str, pr: int, *, review_id: int, expected_head: str, event: str, body: str,
    inline_comments: list[dict[str, Any]],
) -> None:
    """Re-read the formal review and its inline comments and compare them to the intent."""
    remote = gh_publication.fetch_object(
        run_json, f"repos/{repo}/pulls/{pr}/reviews/{review_id}", "formal review"
    )
    if remote.get("id") != review_id:
        raise gh_publication.PublicationError(
            f"re-read review id {remote.get('id')!r} is not the created {review_id}"
        )
    if remote.get("commit_id") != expected_head:
        raise gh_publication.PublicationError(
            f"persisted review is on commit {remote.get('commit_id')!r}, not the expected head"
        )
    wanted_state = "APPROVED" if event == "APPROVE" else "CHANGES_REQUESTED"
    if remote.get("state") != wanted_state:
        raise gh_publication.PublicationError(
            f"persisted review state is {remote.get('state')!r}, expected {wanted_state}"
        )
    if not gh_publication.same_text(remote.get("body"), body):
        raise gh_publication.PublicationError("persisted review body differs from the published body")

    # Always read the persisted inline collection, even when none was published: an
    # unexpected comment is exactly what a zero-item check would otherwise never see.
    persisted = gh_publication.paginate(
        run_json, f"repos/{repo}/pulls/{pr}/reviews/{review_id}/comments", "inline review comments"
    )
    if len(persisted) != len(inline_comments):
        raise gh_publication.PublicationError(
            f"the review persisted {len(persisted)} inline comment(s) but "
            f"{len(inline_comments)} were published"
        )
    unmatched = list(persisted)
    for expected in inline_comments:
        hit = next((item for item in unmatched if _location_matches(expected, item, expected_head)), None)
        if hit is None:
            raise gh_publication.PublicationError(
                f"inline comment on {expected['path']}:{expected['line']} did not persist "
                "faithfully (its location, side, commit or body differ or are missing)"
            )
        unmatched.remove(hit)


def verify_persisted_summary(
    repo: str, pr: int, *, comment_id: int, actor: str, marker: str, summary: str
) -> None:
    """Re-read the summary comment, and prove it is the only marked one for this head."""
    remote = gh_publication.fetch_object(
        run_json, f"repos/{repo}/issues/comments/{comment_id}", "summary comment"
    )
    gh_publication.verify_comment(
        remote, comment_id=comment_id, actor=actor, marker=marker, body=summary, pr=pr,
        label="summary comment",
    )
    comments = gh_publication.paginate(run_json, f"repos/{repo}/issues/{pr}/comments", "issue comments")
    gh_publication.verify_single_marked(
        comments, actor=actor, marker=marker, comment_id=comment_id, label="summary comment"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--level", required=True, choices=sorted(LEVELS))
    parser.add_argument("--verdict", required=True, choices=sorted(VERDICTS))
    parser.add_argument("--review-body-file", required=True, type=Path)
    parser.add_argument("--summary-file", required=True, type=Path)
    parser.add_argument("--inline-comments-file", type=Path)
    parser.add_argument(
        "--role-policy",
        type=Path,
        help="role policy JSON (or set AGENTOPS_ROLE_POLICY); required, fails closed",
    )
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--prior-packet", type=Path)
    parser.add_argument("--prior-overturns", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        policy = role_gate.load_policy(args.role_policy)
    except role_gate.AuthorityDenied as error:
        raise SystemExit(f"REVIEW_PUBLICATION=FAIL: {error}") from error

    expected = evidence_gate.full_sha(args.expected_head, "--expected-head")
    review_body = args.review_body_file.read_text(encoding="utf-8")
    summary = args.summary_file.read_text(encoding="utf-8")
    marker = validate_publication_text(
        level=args.level,
        verdict=args.verdict,
        expected_head=expected,
        review_body=review_body,
        summary=summary,
    )
    inline_comments = load_inline_comments(args.inline_comments_file)

    actor = run_json("gh", "api", "user")["login"]
    pr_state = run_json("gh", "api", f"repos/{args.repo}/pulls/{args.pr}")
    live_before = pr_state["head"]["sha"]
    if live_before != expected:
        raise SystemExit("REVIEW_PUBLICATION=FAIL: live head changed before publication")
    try:
        role_gate.validate(
            actor=actor,
            operation="review-metadata",
            repo=args.repo,
            pr=args.pr,
            pr_author=pr_state["user"]["login"],
            policy=policy,
        )
    except role_gate.AuthorityDenied as error:
        raise SystemExit(f"REVIEW_PUBLICATION=FAIL: {error}") from error

    if args.verdict == "APPROVE" and args.level != "basic":
        if args.packet is None:
            raise SystemExit("REVIEW_PUBLICATION=FAIL: hard approval requires --packet")
        packet = json.loads(args.packet.read_text(encoding="utf-8"))
        prior = (
            json.loads(args.prior_packet.read_text(encoding="utf-8"))
            if args.prior_packet else None
        )
        evidence_gate.validate(
            packet,
            prior_overturns=args.prior_overturns,
            high_risk=True,
            expected_head=expected,
            prior_packet=prior,
            devils_advocate=args.level == "devils-advocate",
        )

    if args.dry_run:
        print(f"REVIEW_PUBLICATION=DRY_RUN_PASS level={args.level} head={expected}")
        return

    event = "APPROVE" if args.verdict == "APPROVE" else "REQUEST_CHANGES"
    review = run_json(
        "gh", "api", "--method", "POST",
        f"repos/{args.repo}/pulls/{args.pr}/reviews", "--input", "-",
        stdin={
            "commit_id": expected,
            "body": review_body,
            "event": event,
            "comments": inline_comments,
        },
    )
    review_id = review.get("id")
    if not isinstance(review_id, int):
        raise SystemExit("REVIEW_PUBLICATION=FAIL: the created review returned no id")

    try:
        summary_id = publish_summary(args.repo, args.pr, actor=actor, marker=marker, summary=summary)
        live_after = run_json("gh", "api", f"repos/{args.repo}/pulls/{args.pr}")["head"]["sha"]
        if live_after != expected:
            raise SystemExit("REVIEW_PUBLICATION=FAIL: live head changed during publication")
        # A write response is not evidence. Re-read every persisted object and compare.
        verify_persisted_review(
            args.repo, args.pr, review_id=review_id, expected_head=expected, event=event,
            body=review_body, inline_comments=inline_comments,
        )
        verify_persisted_summary(
            args.repo, args.pr, comment_id=summary_id, actor=actor, marker=marker, summary=summary
        )
    except gh_publication.PublicationError as error:
        raise SystemExit(
            f"REVIEW_PUBLICATION=FAIL: {error} (review_id={review_id}; inspect the pull request)"
        ) from error
    print(
        f"REVIEW_PUBLICATION=PASS level={args.level} verdict={args.verdict} "
        f"head={expected} review_id={review_id} comment_id={summary_id}"
    )


if __name__ == "__main__":
    main()
