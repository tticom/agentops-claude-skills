#!/usr/bin/env python3
"""Safely prune stale review worktrees and record what was kept and why.

Scans the Git checkouts that are direct children of a workspace directory, prunes
dead worktree metadata, and removes only review worktrees that are *provably*
stale (clean, and their branch is merged or its pull request is merged/closed).
Everything else is preserved: dirty, locked, detached, unclassified, or merely
unverified. A JSON receipt of every decision and a human-readable checkout index
are written outside the scanned repositories. Uses only Python and ``git`` (and
optionally ``gh``); it runs unchanged on Windows, macOS and Linux.

Nothing is deleted on a dry run (``--dry-run``).
"""

from __future__ import annotations

import argparse
import datetime
import getpass
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

WORKSPACE_ENV = "AGENTOPS_WORKSPACE"
DEFAULT_REVIEW_PATTERN = r"-review-pr-|-review$"
UNSAFE_MESSAGE = "Workspace path invalid or unsafe"


def run_cmd(cmd: Sequence[str], cwd: Path | str | None = None, check: bool = True):
    """Run a command with UTF-8 text I/O. A missing executable is a failed command."""
    try:
        res = subprocess.run(
            list(cmd), cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except OSError as error:
        res = subprocess.CompletedProcess(list(cmd), 127, stdout="", stderr=str(error))
    if check and res.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{res.stderr}")
    return res


def same_path(a: Path | str, b: Path | str) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def within_workspace(path: Path | str, workspace: Path | str) -> bool:
    """True only if ``path`` *resolves* to the workspace or somewhere below it.

    Symlinks and Windows junctions are resolved first, so a link inside the workspace
    that points elsewhere is outside; comparison is by path components, so a sibling
    such as ``<workspace>-other`` is outside; and it is case-insensitive on Windows.
    """
    real = os.path.normcase(os.path.realpath(path))
    root = os.path.normcase(os.path.realpath(workspace))
    try:
        return os.path.commonpath([real, root]) == root
    except ValueError:  # different drives on Windows
        return False


def is_dirty(path: Path | str) -> bool:
    return bool(run_cmd(["git", "status", "--porcelain"], cwd=path).stdout.strip())


def get_worktrees(repo_path: Path) -> list[dict[str, Any]]:
    res = run_cmd(["git", "worktree", "list", "--porcelain"], cwd=repo_path)
    worktrees: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for line in res.stdout.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line.split(" ", 1)[1]}
        elif line.startswith("branch "):
            current["branch"] = line.split(" ", 1)[1].replace("refs/heads/", "")
        elif line.startswith("locked"):
            current["locked"] = line.split(" ", 1)[1] if " " in line else "locked"
        elif line.startswith("prunable"):
            current["prunable"] = line.split(" ", 1)[1] if " " in line else "prunable"
        elif line == "detached":
            current["detached"] = True
    if current:
        worktrees.append(current)
    return worktrees


def discover_repos(workspace: Path) -> list[Path]:
    return sorted(d for d in workspace.iterdir() if d.is_dir() and (d / ".git").exists())


def scoped_repos(workspace: Path) -> tuple[list[Path], list[Path]]:
    """Split the workspace's checkouts into (inside, resolves-outside)."""
    inside: list[Path] = []
    outside: list[Path] = []
    for repo in discover_repos(workspace):
        (inside if within_workspace(repo, workspace) else outside).append(repo)
    return inside, outside


def group_repos(repos: list[Path]) -> list[list[Path]]:
    """Group checkouts by the repository they belong to (their git common directory).

    Each repository is scanned once. Which checkout issues the git commands, and which
    worktrees are eligible for cleanup, are separate questions: no checkout is exempt
    merely for being listed first.
    """
    groups: dict[str, list[Path]] = {}
    for repo in repos:
        common = run_cmd(["git", "rev-parse", "--git-common-dir"], cwd=repo, check=False).stdout.strip()
        key = os.path.normcase(os.path.realpath(repo / common)) if common else str(repo)
        groups.setdefault(key, []).append(repo)
    return list(groups.values())


def choose_anchor(anchors: list[Path], target: Path) -> Path | None:
    """A checkout to run git from that is not the worktree being removed."""
    return next((anchor for anchor in anchors if not same_path(anchor, target)), None)


def default_base_branch(repo: Path) -> str:
    res = run_cmd(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=repo, check=False)
    if res.returncode == 0 and res.stdout.strip():
        return res.stdout.strip().split("/", 1)[-1]
    return "main"


def is_stale_review(repo: Path, branch: str | None, base: str, use_gh: bool = True) -> bool:
    """True only with strong evidence. Anything uncertain is preserved."""
    if not branch:
        return False  # a detached HEAD is not proof of staleness
    merged = run_cmd(["git", "branch", "--merged", base], cwd=repo, check=False)
    if merged.returncode == 0:
        names = [line.strip().lstrip("*+ ").strip() for line in merged.stdout.splitlines()]
        if branch in names:
            return True
    if use_gh:
        pr = run_cmd(["gh", "pr", "view", branch, "--json", "state"], cwd=repo, check=False)
        if pr.returncode == 0:
            try:
                state = json.loads(pr.stdout).get("state")
            except (json.JSONDecodeError, AttributeError):
                state = None
            if state in {"MERGED", "CLOSED"}:
                return True
    return False


def write_workspace_index(workspace: Path, repos: list[Path], index_file: Path, task_pointer: str | None) -> Path:
    lines = [
        "# Workspace index",
        "",
        "Generated by the workspace-cleanup skill. Canonical source remains each checkout's Git state.",
        "",
        "| Checkout | Branch | HEAD | State |",
        "|---|---|---|---|",
    ]
    for repo in sorted(repos, key=lambda path: path.name):
        branch = run_cmd(["git", "branch", "--show-current"], cwd=repo, check=False).stdout.strip() or "detached"
        head = run_cmd(["git", "rev-parse", "--short", "HEAD"], cwd=repo, check=False).stdout.strip() or "unborn"
        try:
            state = "dirty" if is_dirty(repo) else "clean"
        except RuntimeError:
            state = "unreadable"
        lines.append(f"| `{repo.name}` | `{branch}` | `{head}` | {state} |")
    if task_pointer:
        lines.extend(["", f"Active task pointer: `{task_pointer}`"])
    lines.append("")
    index_file.parent.mkdir(parents=True, exist_ok=True)
    index_file.write_text("\n".join(lines), encoding="utf-8")
    return index_file


def resolve_workspace(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.resolve()
    if os.environ.get(WORKSPACE_ENV):
        return Path(os.environ[WORKSPACE_ENV]).resolve()
    top = run_cmd(["git", "rev-parse", "--show-toplevel"], check=False)
    if top.returncode == 0 and top.stdout.strip():
        return Path(top.stdout.strip()).resolve().parent
    return Path.cwd().resolve()


def workspace_is_safe(workspace: Path) -> bool:
    """A workspace must be a real directory that is neither a filesystem root nor a home directory."""
    if not workspace.is_dir():
        return False
    if workspace == workspace.parent:
        return False
    return not same_path(workspace, Path.home())


def cleanup(
    workspace: Path,
    *,
    dry_run: bool,
    receipt_dir: Path,
    index_file: Path,
    review_pattern: str,
    base_branch: str | None,
    use_gh: bool,
    task_pointer: str | None,
) -> Path:
    pattern = re.compile(review_pattern)
    repos, linked_outside = scoped_repos(workspace)
    receipt: list[dict[str, str]] = []

    def note(action: str, path: Path | str, reason: str) -> None:
        receipt.append({"action": action, "path": str(path), "reason": reason})

    # Git's worktree list is repository-wide, so the requested workspace, not git, is the
    # boundary: nothing that resolves outside it is ever selected, removed or pruned.
    for repo in linked_outside:
        print(f"Skipping {repo.name}: it resolves outside the requested workspace")
        note("preserved", repo, "repository resolves outside the requested workspace")

    for group in group_repos(repos):
        label = group[0].name
        print(f"Scanning {label}...")
        try:
            worktrees = get_worktrees(group[0])
        except RuntimeError as error:
            print(f"Cannot list worktrees for {label}: {error}")
            note("error", group[0], f"cannot list worktrees: {error}")
            continue
        # Git lists the primary worktree first. It is preserved, never removed.
        primary = Path(worktrees[0]["path"]) if worktrees else group[0]
        # Checkouts git can be run from, primary first. Which one issues commands never
        # decides what is cleaned: any worktree other than the primary is judged on its
        # own merits, wherever it sorts.
        anchors: list[Path] = []
        for candidate in [primary, *(Path(wt["path"]) for wt in worktrees[1:]), *group]:
            if candidate.is_dir() and not any(same_path(candidate, kept) for kept in anchors):
                anchors.append(candidate)
        if not anchors:
            note("error", group[0], "no existing checkout to run git from")
            continue
        base = base_branch or default_base_branch(anchors[0])

        prunable = [wt for wt in worktrees if "prunable" in wt]
        stray = [wt["path"] for wt in prunable if not within_workspace(wt["path"], workspace)]
        if stray:
            # `git worktree prune` cannot be limited to a path, so one out-of-scope entry
            # means it must not run at all.
            note(
                "preserved",
                anchors[0],
                "metadata not pruned: git worktree prune is repository-wide and these prunable "
                "worktrees are outside the requested workspace: " + ", ".join(stray),
            )
        elif prunable:
            prune_cmd = ["git", "worktree", "prune"] + (["--dry-run"] if dry_run else [])
            pruned = run_cmd(prune_cmd, cwd=anchors[0], check=False)
            if pruned.returncode != 0:
                note("error", anchors[0], f"git worktree prune failed: {pruned.stderr.strip()}")
            else:
                for wt in prunable:
                    note("dry_run_prune" if dry_run else "pruned_metadata", wt["path"], wt["prunable"])
                if not dry_run:
                    worktrees = get_worktrees(anchors[0])

        for wt in worktrees:
            wt_path = Path(wt["path"])
            if same_path(wt_path, primary):
                note("preserved", wt_path, "primary checkout (never removed)")
                continue
            if not within_workspace(wt_path, workspace):
                print(f"Preserving worktree outside the workspace: {wt_path}")
                note("preserved", wt_path, "outside the requested workspace")
                continue
            if not pattern.search(wt_path.name):
                print(f"Skipping unclassified worktree: {wt_path}")
                note("preserved", wt_path, "unknown/unclassified worktree")
                continue
            if "locked" in wt:
                print(f"Preserving locked worktree: {wt_path} ({wt['locked']})")
                note("preserved", wt_path, f"locked worktree: {wt['locked']}")
                continue
            try:
                if not wt_path.exists():
                    note("preserved", wt_path, "prunable worktree directory missing")
                    continue
                dirty = is_dirty(wt_path)
            except Exception as error:  # a receipt must survive one bad worktree
                print(f"Error checking {wt_path}: {error}")
                note("error", wt_path, str(error))
                continue
            if dirty:
                print(f"Preserving dirty worktree: {wt_path}")
                note("preserved", wt_path, "dirty worktree")
                continue
            anchor = choose_anchor(anchors, wt_path)
            if anchor is None:
                note("preserved", wt_path, "no other checkout of this repository to run git from")
                continue
            if not is_stale_review(anchor, wt.get("branch"), base, use_gh):
                print(f"Preserving active or unverified review worktree: {wt_path}")
                note("preserved", wt_path, "active/unverified review")
                continue
            print(f"{'Would remove' if dry_run else 'Removing'} disposable worktree: {wt_path}")
            if dry_run:
                note("dry_run_remove", wt_path, "clean stale review worktree")
                continue
            try:
                run_cmd(["git", "worktree", "remove", str(wt_path)], cwd=anchor)
                note("removed_worktree", wt_path, "clean stale review worktree")
            except Exception as error:
                print(f"Failed to remove {wt_path}: {error}")
                note("error", wt_path, str(error))

    # Re-discover: worktrees removed above no longer exist and must not be indexed.
    index = write_workspace_index(workspace, scoped_repos(workspace)[0], index_file, task_pointer)
    note("workspace_index", index, "human-readable checkout map")
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    receipt_file = receipt_dir / f"{stamp}-cleanup-receipt.json"
    receipt_file.parent.mkdir(parents=True, exist_ok=True)
    receipt_file.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(f"Cleanup receipt written to {receipt_file}")
    return receipt_file


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", type=Path, help=f"workspace directory (or set {WORKSPACE_ENV})")
    parser.add_argument("--dry-run", action="store_true", help="report only; delete nothing")
    parser.add_argument("--allowed-user", action="append", default=[],
                        help="restrict to these OS users (repeatable); no restriction if omitted")
    parser.add_argument("--receipt-dir", type=Path, help="default: <workspace>/agentops-logs/cleanup-receipts")
    parser.add_argument("--index-file", type=Path, help="default: <workspace>/agentops-logs/workspace-state/latest.md")
    parser.add_argument("--review-worktree-pattern", default=DEFAULT_REVIEW_PATTERN,
                        help="regex naming disposable review worktree directories")
    parser.add_argument("--base-branch", help="branch a stale review must be merged into (default: origin's HEAD, else main)")
    parser.add_argument("--no-gh", action="store_true", help="do not consult the GitHub CLI for PR state")
    parser.add_argument("--active-task-pointer", help="path shown in the index; informational only")
    args = parser.parse_args(argv)

    if args.allowed_user and getpass.getuser() not in set(args.allowed_user):
        print(f"{UNSAFE_MESSAGE}. Identity {getpass.getuser()} not allowed.")
        return 1
    try:
        re.compile(args.review_worktree_pattern)
    except re.error as error:
        print(f"invalid --review-worktree-pattern: {error}")
        return 64

    workspace = resolve_workspace(args.workspace)
    if not workspace_is_safe(workspace):
        print(f"{UNSAFE_MESSAGE}: {workspace}")
        return 1
    logs = workspace / "agentops-logs"
    cleanup(
        workspace,
        dry_run=args.dry_run,
        receipt_dir=(args.receipt_dir or logs / "cleanup-receipts").resolve(),
        index_file=(args.index_file or logs / "workspace-state" / "latest.md").resolve(),
        review_pattern=args.review_worktree_pattern,
        base_branch=args.base_branch,
        use_gh=not args.no_gh,
        task_pointer=args.active_task_pointer,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
