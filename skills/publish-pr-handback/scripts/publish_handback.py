#!/usr/bin/env python3
"""Publish an exact-head author handback from a validated evidence packet."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import gh_publication


FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
# The hand-off state is project vocabulary. The default is neutral; a project that
# names its own review-ready states lists them with --allowed-state (repeatable)
# or AGENTOPS_HANDBACK_STATES (comma-separated).
DEFAULT_STATES = ("AWAITING_INDEPENDENT_REVIEW",)
STATES_ENV = "AGENTOPS_HANDBACK_STATES"
STATE_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
REQUIRED_PACKET_KEYS = {
    "schema_version",
    "task",
    "repository",
    "pr",
    "head",
    "base",
    "changed_paths",
    "validation_runs",
    "acceptance",
    "review_findings",
    "remaining_risks",
}


class HandbackError(RuntimeError):
    """Raised when a review-ready handback cannot be proved."""


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


def run_text(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        args,
        cwd=None if cwd is None else str(cwd),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def allowed_states(extra: list[str] | None = None) -> list[str]:
    """Resolve the accepted hand-off states: neutral default plus configured extras."""
    configured = [item.strip() for item in os.environ.get(STATES_ENV, "").split(",") if item.strip()]
    states = list(dict.fromkeys([*DEFAULT_STATES, *configured, *(extra or [])]))
    bad = [state for state in states if not STATE_NAME.fullmatch(state)]
    if bad:
        raise HandbackError(f"invalid hand-off state name(s): {bad}")
    return states


def require_full_sha(value: Any, label: str) -> str:
    rendered = str(value)
    if not FULL_SHA.fullmatch(rendered):
        raise HandbackError(f"{label} must be a full lowercase SHA")
    return rendered


def query_changed_paths(repo: str, pr: int) -> list[str]:
    files: list[dict[str, Any]] = []
    page_number = 1
    while True:
        page = run_json(
            "gh",
            "api",
            f"repos/{repo}/pulls/{pr}/files?per_page=100&page={page_number}",
        )
        if not isinstance(page, list):
            raise HandbackError("changed-path query returned an invalid page")
        files.extend(item for item in page if isinstance(item, dict))
        if len(page) < 100:
            break
        page_number += 1
    paths = [str(item.get("filename", "")) for item in files]
    if any(not path for path in paths):
        raise HandbackError("changed-path query returned an empty filename")
    return sorted(paths)


def validate_live_context(
    *,
    actor: str,
    pr_state: dict[str, Any],
    expected_head: str,
    local_head: str,
    local_branch: str,
    worktree_status: str,
) -> tuple[str, str]:
    expected = require_full_sha(expected_head, "expected head")
    live_head = require_full_sha((pr_state.get("head") or {}).get("sha"), "live head")
    base = require_full_sha((pr_state.get("base") or {}).get("sha"), "live base")
    author = str((pr_state.get("user") or {}).get("login", ""))
    branch = str((pr_state.get("head") or {}).get("ref", ""))
    if str(pr_state.get("state", "")).lower() != "open":
        raise HandbackError("pull request must be open")
    if not actor or actor.lower() != author.lower():
        raise HandbackError("authenticated actor must be the pull-request author")
    if live_head != expected or local_head != expected:
        raise HandbackError("local, expected, and live head SHAs must be exactly equal")
    if local_branch != branch:
        raise HandbackError("local branch must equal the live pull-request head branch")
    if worktree_status:
        raise HandbackError("author worktree must be clean before handback")
    return live_head, base


def _require_nonempty_text(item: dict[str, Any], key: str, label: str) -> None:
    if not isinstance(item.get(key), str) or not item[key].strip():
        raise HandbackError(f"{label} requires non-empty {key}")


def validate_packet(
    packet: dict[str, Any],
    *,
    repo: str,
    pr: int,
    head: str,
    base: str,
    changed_paths: list[str],
) -> None:
    missing = REQUIRED_PACKET_KEYS - set(packet)
    if missing:
        raise HandbackError(f"packet lacks required keys: {sorted(missing)}")
    if packet["schema_version"] != "author-handback.v1":
        raise HandbackError("unsupported handback packet schema")
    if packet["repository"] != repo or packet["pr"] != pr:
        raise HandbackError("packet repository or PR does not match publication target")
    if packet["head"] != head or packet["base"] != base:
        raise HandbackError("packet base/head does not match live pull request")
    if sorted(packet["changed_paths"]) != sorted(changed_paths):
        raise HandbackError("packet changed paths do not exactly match the live pull request")
    _require_nonempty_text(packet, "task", "packet")

    validation_runs = packet["validation_runs"]
    if not isinstance(validation_runs, list) or not validation_runs:
        raise HandbackError("packet requires at least one completed validation run")
    for index, item in enumerate(validation_runs, start=1):
        if not isinstance(item, dict):
            raise HandbackError(f"validation run {index} must be an object")
        _require_nonempty_text(item, "command", f"validation run {index}")
        if item.get("status") != "PASS" or item.get("exit_code") != 0:
            raise HandbackError(f"validation run {index} did not complete successfully")
        for key in ("passed", "failed", "errors", "skipped", "xfailed", "deselected"):
            value = item.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise HandbackError(
                    f"validation run {index} requires non-negative integer {key}"
                )
        if item["failed"] or item["errors"]:
            raise HandbackError(f"validation run {index} contains failures or errors")

    acceptance = packet["acceptance"]
    if not isinstance(acceptance, list) or not acceptance:
        raise HandbackError("packet requires at least one acceptance item")
    for index, item in enumerate(acceptance, start=1):
        if not isinstance(item, dict):
            raise HandbackError(f"acceptance item {index} must be an object")
        for key in ("criterion", "command", "observed", "oracle"):
            _require_nonempty_text(item, key, f"acceptance item {index}")
        if item.get("status") != "PASS":
            raise HandbackError(f"acceptance item {index} is not PASS")

    findings = packet["review_findings"]
    if not isinstance(findings, list):
        raise HandbackError("review_findings must be a list")
    for index, item in enumerate(findings, start=1):
        if not isinstance(item, dict):
            raise HandbackError(f"review finding {index} must be an object")
        for key in ("finding", "disposition", "evidence"):
            _require_nonempty_text(item, key, f"review finding {index}")

    risks = packet["remaining_risks"]
    if not isinstance(risks, list) or any(
        not isinstance(item, str) or not item.strip() for item in risks
    ):
        raise HandbackError("remaining_risks must be a list of non-empty strings")


def render_handback(packet: dict[str, Any], *, state: str, packet_sha: str) -> str:
    head = packet["head"]
    changed = "\n".join(f"- `{path}`" for path in packet["changed_paths"])
    acceptance = "\n\n".join(
        "\n".join(
            (
                f"### {index}. {item['criterion']}",
                f"- Status: `{item['status']}`",
                f"- Command: `{item['command']}`",
                f"- Observed: {item['observed']}",
                f"- Oracle: {item['oracle']}",
            )
        )
        for index, item in enumerate(packet["acceptance"], start=1)
    )
    validation = "\n".join(
        f"- `{item['command']}`: {item['status']} (exit {item['exit_code']}; "
        f"pass={item['passed']} fail={item['failed']} error={item['errors']} "
        f"skip={item['skipped']} xfail={item['xfailed']} "
        f"deselected={item['deselected']})"
        for item in packet["validation_runs"]
    )
    findings = packet["review_findings"]
    finding_text = "None (initial handback)." if not findings else "\n\n".join(
        "\n".join(
            (
                f"### {index}. {item['finding']}",
                f"- Disposition: {item['disposition']}",
                f"- Evidence: {item['evidence']}",
            )
        )
        for index, item in enumerate(findings, start=1)
    )
    risks = packet["remaining_risks"]
    risk_text = "None declared." if not risks else "\n".join(f"- {risk}" for risk in risks)
    return "\n".join(
        (
            f"<!-- author-handback:{head} -->",
            "## Exact-head author handback",
            "",
            f"- Task: {packet['task']}",
            f"- Repository: `{packet['repository']}`",
            f"- Pull request: `#{packet['pr']}`",
            f"- Base: `{packet['base']}`",
            f"- Head: `{head}`",
            f"- Evidence-Packet-SHA256: `{packet_sha}`",
            f"- State: `{state}`",
            "",
            "## Changed paths",
            "",
            changed,
            "",
            "## Acceptance evidence",
            "",
            acceptance,
            "",
            "## Validation runs",
            "",
            validation,
            "",
            "## Review finding dispositions",
            "",
            finding_text,
            "",
            "## Remaining risks",
            "",
            risk_text,
            "",
            state,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--worktree", required=True, type=Path)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--state", required=True)
    parser.add_argument(
        "--allowed-state",
        action="append",
        default=[],
        help=f"additional accepted hand-off state (or set {STATES_ENV})",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    accepted = allowed_states(args.allowed_state)
    if args.state not in accepted:
        raise SystemExit(f"AUTHOR_HANDBACK_PUBLICATION=FAIL: state must be one of {accepted}")

    expected = require_full_sha(args.expected_head, "expected head")
    packet_bytes = args.packet.read_bytes()
    packet = json.loads(packet_bytes)
    if not isinstance(packet, dict):
        raise HandbackError("handback packet must be a JSON object")

    actor = str(run_json("gh", "api", "user").get("login", ""))
    pr_state = run_json("gh", "api", f"repos/{args.repo}/pulls/{args.pr}")
    local_head = run_text("git", "rev-parse", "HEAD", cwd=args.worktree)
    local_branch = run_text("git", "branch", "--show-current", cwd=args.worktree)
    status = run_text("git", "status", "--porcelain", cwd=args.worktree)
    live_head, base = validate_live_context(
        actor=actor,
        pr_state=pr_state,
        expected_head=expected,
        local_head=local_head,
        local_branch=local_branch,
        worktree_status=status,
    )
    changed_paths = query_changed_paths(args.repo, args.pr)
    validate_packet(
        packet,
        repo=args.repo,
        pr=args.pr,
        head=live_head,
        base=base,
        changed_paths=changed_paths,
    )
    packet_sha = hashlib.sha256(packet_bytes).hexdigest()
    body = render_handback(packet, state=args.state, packet_sha=packet_sha)
    marker = f"<!-- author-handback:{live_head} -->"

    if args.dry_run:
        print(f"AUTHOR_HANDBACK_PUBLICATION=DRY_RUN_PASS head={live_head}")
        return

    try:
        # Search every page: an existing handback beyond the first 100 comments must be
        # updated, never duplicated.
        comments = gh_publication.paginate(
            run_json, f"repos/{args.repo}/issues/{args.pr}/comments", "issue comments"
        )
        actor_marked = gh_publication.marked_comments(comments, actor=actor, marker=marker)
        if actor_marked:
            published = run_json(
                "gh", "api", "--method", "PATCH",
                f"repos/{args.repo}/issues/comments/{actor_marked[0]['id']}", "--input", "-",
                stdin={"body": body},
            )
        else:
            published = run_json(
                "gh", "api", "--method", "POST",
                f"repos/{args.repo}/issues/{args.pr}/comments", "--input", "-",
                stdin={"body": body},
            )
        comment_id = published.get("id") if isinstance(published, dict) else None
        if not isinstance(comment_id, int):
            raise HandbackError("the handback write returned no comment id")

        live_after = require_full_sha(
            (run_json("gh", "api", f"repos/{args.repo}/pulls/{args.pr}").get("head") or {}).get("sha"),
            "post-publication live head",
        )
        if live_after != live_head:
            raise HandbackError("live head changed during handback publication")

        # A write response is not evidence. Re-read the persisted comment and compare it.
        remote = gh_publication.fetch_object(
            run_json, f"repos/{args.repo}/issues/comments/{comment_id}", "handback comment"
        )
        gh_publication.verify_comment(
            remote, comment_id=comment_id, actor=actor, marker=marker, body=body, pr=args.pr,
            label="handback comment",
        )
        gh_publication.verify_single_marked(
            gh_publication.paginate(
                run_json, f"repos/{args.repo}/issues/{args.pr}/comments", "issue comments"
            ),
            actor=actor, marker=marker, comment_id=comment_id, label="handback comment",
        )
    except gh_publication.PublicationError as error:
        raise HandbackError(str(error)) from error
    print(
        "AUTHOR_HANDBACK_PUBLICATION=PASS "
        f"head={live_head} comment_id={comment_id} state={args.state}"
    )


if __name__ == "__main__":
    try:
        main()
    except HandbackError as error:
        raise SystemExit(f"AUTHOR_HANDBACK_PUBLICATION=FAIL: {error}") from error
