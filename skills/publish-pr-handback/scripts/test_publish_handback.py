from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).with_name("publish_handback.py")
SPEC = importlib.util.spec_from_file_location("publish_handback", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

HEAD = "a" * 40
BASE = "b" * 40


def pr_state() -> dict:
    return {
        "state": "open",
        "user": {"login": "author"},
        "head": {"sha": HEAD, "ref": "feature/branch"},
        "base": {"sha": BASE},
    }


def packet() -> dict:
    return {
        "schema_version": "author-handback.v1",
        "task": "Task 1 — Exact behavior",
        "repository": "owner/repo",
        "pr": 123,
        "head": HEAD,
        "base": BASE,
        "changed_paths": ["src/a.py", "tests/test_a.py"],
        "validation_runs": [
            {
                "command": "python -m pytest",
                "status": "PASS",
                "exit_code": 0,
                "passed": 10,
                "failed": 0,
                "errors": 0,
                "skipped": 0,
                "xfailed": 0,
                "deselected": 0,
            }
        ],
        "acceptance": [
            {
                "criterion": "Produces exactly 43 measures",
                "status": "PASS",
                "command": "pytest tests/test_real.py",
                "observed": "43 measures; no partial-grouping warning",
                "oracle": "reference score semantic comparator",
            }
        ],
        "review_findings": [],
        "remaining_risks": [],
    }


def validate(value: dict) -> None:
    MODULE.validate_packet(
        value,
        repo="owner/repo",
        pr=123,
        head=HEAD,
        base=BASE,
        changed_paths=["src/a.py", "tests/test_a.py"],
    )


def test_valid_live_context_and_packet() -> None:
    assert MODULE.validate_live_context(
        actor="author",
        pr_state=pr_state(),
        expected_head=HEAD,
        local_head=HEAD,
        local_branch="feature/branch",
        worktree_status="",
    ) == (HEAD, BASE)
    validate(packet())


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"expected_head": "c" * 40}, "exactly equal"),
        ({"actor": "reviewer"}, "must be the pull-request author"),
        ({"local_branch": "other"}, "local branch"),
        ({"worktree_status": " M file"}, "must be clean"),
    ],
)
def test_live_context_fails_closed(override: dict, message: str) -> None:
    args = {
        "actor": "author",
        "pr_state": pr_state(),
        "expected_head": HEAD,
        "local_head": HEAD,
        "local_branch": "feature/branch",
        "worktree_status": "",
    }
    args.update(override)
    with pytest.raises(MODULE.HandbackError, match=message):
        MODULE.validate_live_context(**args)


def test_packet_rejects_changed_path_mismatch() -> None:
    value = packet()
    value["changed_paths"] = ["src/a.py"]
    with pytest.raises(MODULE.HandbackError, match="changed paths"):
        validate(value)


@pytest.mark.parametrize("status", ["FAIL", "NOT_RUN"])
def test_packet_rejects_unmet_acceptance(status: str) -> None:
    value = packet()
    value["acceptance"][0]["status"] = status
    with pytest.raises(MODULE.HandbackError, match="is not PASS"):
        validate(value)


def test_packet_rejects_exit_code_without_observed_semantics() -> None:
    value = packet()
    value["acceptance"][0]["observed"] = ""
    with pytest.raises(MODULE.HandbackError, match="non-empty observed"):
        validate(value)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("status", "NOT_RUN", "did not complete"),
        ("exit_code", 1, "did not complete"),
        ("failed", 1, "failures or errors"),
        ("errors", 1, "failures or errors"),
    ],
)
def test_packet_rejects_incomplete_or_failing_validation(
    field: str, value: object, message: str
) -> None:
    evidence = packet()
    evidence["validation_runs"][0][field] = value
    with pytest.raises(MODULE.HandbackError, match=message):
        validate(evidence)


def test_packet_requires_validation_run() -> None:
    evidence = packet()
    evidence["validation_runs"] = []
    with pytest.raises(MODULE.HandbackError, match="at least one completed"):
        validate(evidence)


def test_changed_path_query_paginates_without_new_gh_flags(monkeypatch) -> None:
    pages = [
        [{"filename": f"path/{index}.py"} for index in range(100)],
        [{"filename": "path/final.py"}],
    ]
    calls = []

    def fake_run_json(*args, **kwargs):
        calls.append(args)
        return pages[len(calls) - 1]

    monkeypatch.setattr(MODULE, "run_json", fake_run_json)
    paths = MODULE.query_changed_paths("owner/repo", 123)
    assert len(paths) == 101
    assert calls[0][-1].endswith("page=1")
    assert calls[1][-1].endswith("page=2")


def test_rendered_handback_is_exact_head_and_complete() -> None:
    body = MODULE.render_handback(
        packet(), state="AWAITING_INDEPENDENT_REVIEW", packet_sha="d" * 64
    )
    assert f"<!-- author-handback:{HEAD} -->" in body
    assert f"- Head: `{HEAD}`" in body
    assert "## Acceptance evidence" in body
    assert "## Validation runs" in body
    assert "pass=10 fail=0 error=0" in body
    assert "43 measures; no partial-grouping warning" in body
    assert body.endswith("AWAITING_INDEPENDENT_REVIEW")


# --- end-to-end publication over a fake GitHub layer -------------------------

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

STATE = "AWAITING_INDEPENDENT_REVIEW"
MARKER = f"<!-- author-handback:{HEAD} -->"
PATHS = ["src/a.py", "tests/test_a.py"]


ISSUE_URL = "https://api.github.com/repos/owner/repo/issues/123"


class FakeGh:
    """A stateful remote replacing run_json/run_text.

    Writes mutate a store and reads are served from it, so a publication is verified
    by a genuine second read. ``tamper`` changes only what a later GET returns, which
    models a write that "succeeded" without persisting faithfully.
    """

    def __init__(self, *, actor="author", heads=(HEAD,), comments=None, status="",
                 local_head=HEAD, branch="feature/branch", paths=PATHS, page_size=100):
        self.actor, self.heads = actor, list(heads)
        self.status, self.local_head, self.branch, self.paths = status, local_head, branch, paths
        self.page_size = page_size
        self.store = [{"issue_url": ISSUE_URL, **dict(item)} for item in (comments or [])]
        self.next_id = 1000
        self.tamper, self.get_fails = {}, set()
        self.calls, self.writes = [], []

    def run_json(self, *args, stdin=None):
        self.calls.append(args)
        if args == ("gh", "api", "user"):
            return {"login": self.actor}
        method = args[args.index("--method") + 1] if "--method" in args else "GET"
        endpoint = args[args.index("--method") + 2] if "--method" in args else args[-1]
        path, _, query = endpoint.partition("?")
        params = dict(part.split("=") for part in query.split("&")) if query else {}
        page = int(params.get("page", 1))
        if method == "GET":
            if path == "repos/owner/repo/pulls/123":
                head = self.heads.pop(0) if len(self.heads) > 1 else self.heads[0]
                state = pr_state()
                state["head"]["sha"] = head
                return state
            if path == "repos/owner/repo/pulls/123/files":
                return [{"filename": name} for name in self.paths] if page == 1 else []
            if path == "repos/owner/repo/issues/123/comments":
                return self.store[(page - 1) * self.page_size: page * self.page_size]
            if path.startswith("repos/owner/repo/issues/comments/"):
                if "comment" in self.get_fails:
                    raise subprocess.CalledProcessError(1, list(args), stderr="HTTP 404")
                found = next(c for c in self.store if c["id"] == int(path.rsplit("/", 1)[1]))
                return self.tamper.get("comment", lambda value: value)(json.loads(json.dumps(found)))
        if method == "POST" and path == "repos/owner/repo/issues/123/comments":
            self.writes.append((args, stdin))
            self.next_id += 1
            comment = {"id": self.next_id, "user": {"login": self.actor}, "body": stdin["body"],
                       "issue_url": ISSUE_URL}
            self.store.append(comment)
            return dict(comment)
        if method == "PATCH" and path.startswith("repos/owner/repo/issues/comments/"):
            self.writes.append((args, stdin))
            found = next(c for c in self.store if c["id"] == int(path.rsplit("/", 1)[1]))
            found["body"] = stdin["body"]
            return dict(found)
        raise AssertionError(f"unexpected gh call: {args}")

    def run_text(self, *args, cwd=None):
        if args[:3] == ("git", "rev-parse", "HEAD"):
            return self.local_head
        if args[:3] == ("git", "branch", "--show-current"):
            return self.branch
        if args[:3] == ("git", "status", "--porcelain"):
            return self.status
        raise AssertionError(f"unexpected command: {args}")

    def marked(self, user=None):
        return [c for c in self.store if MARKER in c["body"]
                and (user is None or c["user"]["login"].lower() == user.lower())]


def marker_comment(comment_id, user="author", text=" old"):
    return {"id": comment_id, "user": {"login": user}, "body": MARKER + text}


def noise(count, start=1):
    return [{"id": start + i, "user": {"login": "someone"}, "body": f"chatter {i}"} for i in range(count)]


def run_main(monkeypatch, tmp_path, gh, *extra, state=STATE, head=HEAD, value=None, env=None):
    packet_path = tmp_path / "handback.json"
    packet_path.write_text(json.dumps(value if value is not None else packet()), encoding="utf-8")
    monkeypatch.setattr(MODULE, "run_json", gh.run_json)
    monkeypatch.setattr(MODULE, "run_text", gh.run_text)
    monkeypatch.delenv(MODULE.STATES_ENV, raising=False)
    for key, item in (env or {}).items():
        monkeypatch.setenv(key, item)
    argv = ["publish_handback.py", "--repo", "owner/repo", "--pr", "123", "--expected-head", head,
            "--worktree", str(tmp_path), "--packet", str(packet_path), "--state", state, *extra]
    monkeypatch.setattr("sys.argv", argv)
    MODULE.main()


def test_publishes_a_new_marked_comment_and_reads_it_back(monkeypatch, tmp_path, capsys) -> None:
    gh = FakeGh()
    run_main(monkeypatch, tmp_path, gh)
    out = capsys.readouterr().out
    assert "AUTHOR_HANDBACK_PUBLICATION=PASS" in out and f"head={HEAD}" in out
    assert len(gh.writes) == 1 and "POST" in gh.writes[0][0]
    assert MARKER in gh.writes[0][1]["body"]


def test_repeat_on_an_unchanged_head_updates_the_same_comment(monkeypatch, tmp_path) -> None:
    existing = [{"id": 55, "user": {"login": "Author"}, "body": MARKER + " old"}]
    gh = FakeGh(comments=existing)
    run_main(monkeypatch, tmp_path, gh)
    assert len(gh.writes) == 1
    assert "PATCH" in gh.writes[0][0] and "issues/comments/55" in gh.writes[0][0][-3]


def test_a_marker_from_another_user_is_never_updated(monkeypatch, tmp_path) -> None:
    gh = FakeGh(comments=[{"id": 55, "user": {"login": "someone"}, "body": MARKER}])
    run_main(monkeypatch, tmp_path, gh)
    assert "POST" in gh.writes[0][0]


def test_dry_run_publishes_nothing(monkeypatch, tmp_path, capsys) -> None:
    gh = FakeGh()
    run_main(monkeypatch, tmp_path, gh, "--dry-run")
    assert "DRY_RUN_PASS" in capsys.readouterr().out
    assert gh.writes == []


@pytest.mark.parametrize(
    ("gh_kwargs", "message"),
    [
        ({"actor": "reviewer"}, "must be the pull-request author"),
        ({"status": " M src/a.py"}, "must be clean"),
        ({"local_head": "c" * 40}, "exactly equal"),
        ({"branch": "other"}, "local branch"),
        ({"paths": ["src/a.py"]}, "changed paths"),
    ],
)
def test_publication_refuses_without_writing(monkeypatch, tmp_path, gh_kwargs, message) -> None:
    gh = FakeGh(**gh_kwargs)
    with pytest.raises(MODULE.HandbackError, match=message):
        run_main(monkeypatch, tmp_path, gh)
    assert gh.writes == []


def test_stale_expected_head_is_rejected(monkeypatch, tmp_path) -> None:
    gh = FakeGh()
    with pytest.raises(MODULE.HandbackError, match="exactly equal"):
        run_main(monkeypatch, tmp_path, gh, head="c" * 40)
    assert gh.writes == []


def test_a_head_that_moves_during_publication_fails(monkeypatch, tmp_path) -> None:
    gh = FakeGh(heads=(HEAD, "c" * 40))  # read once before, once after publication
    with pytest.raises(MODULE.HandbackError, match="changed during handback publication"):
        run_main(monkeypatch, tmp_path, gh)


# --- a write response is not evidence: the persisted comment must be read back -----


def test_publication_reads_the_persisted_comment_back_after_writing(monkeypatch, tmp_path, capsys) -> None:
    gh = FakeGh()
    run_main(monkeypatch, tmp_path, gh)
    assert "AUTHOR_HANDBACK_PUBLICATION=PASS" in capsys.readouterr().out
    write_at = next(i for i, call in enumerate(gh.calls) if "--method" in call)
    later_reads = [call[-1] for call in gh.calls[write_at + 1:] if "--method" not in call]
    assert any(path.startswith("repos/owner/repo/issues/comments/1001") for path in later_reads), later_reads


@pytest.mark.parametrize(
    ("label", "tamper", "message"),
    [
        ("altered body", lambda c: {**c, "body": c["body"] + "\nextra claim"}, "body differs"),
        ("lost marker", lambda c: {**c, "body": "no marker here"}, "lost its marker"),
        ("other author", lambda c: {**c, "user": {"login": "impostor"}}, "author"),
        ("other pull request", lambda c: {**c, "issue_url": ISSUE_URL.replace("123", "999")}, "pull request"),
        ("different id", lambda c: {**c, "id": 424242}, "id"),
    ],
)
def test_a_comment_that_persisted_differently_fails(monkeypatch, tmp_path, capsys, label, tamper, message) -> None:
    gh = FakeGh()
    gh.tamper["comment"] = tamper
    with pytest.raises(MODULE.HandbackError, match=message):
        run_main(monkeypatch, tmp_path, gh)
    assert "AUTHOR_HANDBACK_PUBLICATION=PASS" not in capsys.readouterr().out


def test_a_comment_that_cannot_be_retrieved_after_writing_fails(monkeypatch, tmp_path, capsys) -> None:
    gh = FakeGh()
    gh.get_fails.add("comment")
    with pytest.raises(MODULE.HandbackError, match="cannot re-read"):
        run_main(monkeypatch, tmp_path, gh)
    assert "AUTHOR_HANDBACK_PUBLICATION=PASS" not in capsys.readouterr().out


def test_line_endings_and_trailing_whitespace_do_not_cause_false_failures(monkeypatch, tmp_path, capsys) -> None:
    gh = FakeGh()
    gh.tamper["comment"] = lambda c: {**c, "body": c["body"].replace("\n", "\r\n") + "\n  "}
    run_main(monkeypatch, tmp_path, gh)
    assert "AUTHOR_HANDBACK_PUBLICATION=PASS" in capsys.readouterr().out


def test_two_marked_handbacks_after_publication_are_reported(monkeypatch, tmp_path) -> None:
    gh = FakeGh(comments=[marker_comment(1)])
    original = gh.run_json

    def duplicating(*args, stdin=None):
        result = original(*args, stdin=stdin)
        if "PATCH" in args:  # a second marked comment appears concurrently
            gh.store.append({**marker_comment(9999, text=" dup"), "issue_url": ISSUE_URL})
        return result

    gh.run_json = duplicating
    with pytest.raises(MODULE.HandbackError, match="more than one"):
        run_main(monkeypatch, tmp_path, gh)


# --- idempotence must hold however long the comment thread is ----------------------


def test_marker_beyond_the_first_page_is_updated_not_duplicated(monkeypatch, tmp_path, capsys) -> None:
    gh = FakeGh(comments=noise(205) + [marker_comment(50_000)] + noise(10, start=60_000))
    run_main(monkeypatch, tmp_path, gh)
    assert len(gh.writes) == 1
    assert "PATCH" in gh.writes[0][0] and "issues/comments/50000" in gh.writes[0][0][-3]
    assert len(gh.marked("author")) == 1
    assert "comment_id=50000" in capsys.readouterr().out


def test_every_comment_page_is_requested(monkeypatch, tmp_path) -> None:
    gh = FakeGh(comments=noise(250) + [marker_comment(50_000)])
    run_main(monkeypatch, tmp_path, gh)
    pages = [c[-1] for c in gh.calls if c[-1].startswith("repos/owner/repo/issues/123/comments?")]
    assert any("page=1" in p for p in pages) and any("page=3" in p for p in pages)


def test_a_full_page_is_followed_by_one_more_request(monkeypatch, tmp_path) -> None:
    gh = FakeGh(comments=noise(99) + [marker_comment(50_000)])  # exactly one full page
    run_main(monkeypatch, tmp_path, gh)
    assert len(gh.writes) == 1 and "PATCH" in gh.writes[0][0]
    pages = [c[-1] for c in gh.calls if c[-1].startswith("repos/owner/repo/issues/123/comments?")]
    assert any("page=2" in p for p in pages)


def test_a_marker_from_another_user_is_not_reused_even_across_pages(monkeypatch, tmp_path) -> None:
    gh = FakeGh(comments=noise(150) + [marker_comment(50_000, user="someone-else")])
    run_main(monkeypatch, tmp_path, gh)
    assert len(gh.writes) == 1 and "POST" in gh.writes[0][0]
    assert len(gh.marked("author")) == 1 and len(gh.marked("someone-else")) == 1


def test_a_marker_for_a_different_head_is_not_reused(monkeypatch, tmp_path) -> None:
    other = {"id": 5, "user": {"login": "author"}, "body": f"<!-- author-handback:{'c' * 40} -->"}
    gh = FakeGh(comments=[other])
    run_main(monkeypatch, tmp_path, gh)
    assert "POST" in gh.writes[0][0]


def test_a_malformed_comment_page_fails_closed(monkeypatch, tmp_path) -> None:
    gh = FakeGh()
    original = gh.run_json

    def broken(*args, stdin=None):
        if "--method" not in args and args[-1].startswith("repos/owner/repo/issues/123/comments"):
            return {"message": "rate limited"}
        return original(*args, stdin=stdin)

    gh.run_json = broken
    with pytest.raises(MODULE.HandbackError, match="was not a list"):
        run_main(monkeypatch, tmp_path, gh)
    assert gh.writes == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda v: v.pop("task"),
        lambda v: v.update(schema_version="author-handback.v2"),
        lambda v: v.update(pr=999),
        lambda v: v.update(head="c" * 40),
        lambda v: v["acceptance"][0].update(oracle=" "),
    ],
)
def test_incomplete_or_mismatched_packets_are_refused(monkeypatch, tmp_path, mutate) -> None:
    value = packet()
    mutate(value)
    gh = FakeGh()
    with pytest.raises(MODULE.HandbackError):
        run_main(monkeypatch, tmp_path, gh, value=value)
    assert gh.writes == []


def test_non_object_packet_is_refused(monkeypatch, tmp_path) -> None:
    with pytest.raises(MODULE.HandbackError, match="JSON object"):
        run_main(monkeypatch, tmp_path, FakeGh(), value=[])


@pytest.mark.parametrize("bad", [None, "text", 7, [], True])
def test_a_non_object_comment_element_fails_closed(monkeypatch, tmp_path, capsys, bad) -> None:
    """A null inside a valid comment list is a failure, never silently filtered out."""
    gh = FakeGh(comments=noise(3))
    original = gh.run_json

    def poisoned(*args, stdin=None):
        result = original(*args, stdin=stdin)
        if "--method" not in args and args[-1].startswith("repos/owner/repo/issues/123/comments"):
            return list(result) + [bad]
        return result

    gh.run_json = poisoned
    with pytest.raises(MODULE.HandbackError, match="not an object"):
        run_main(monkeypatch, tmp_path, gh)
    assert gh.writes == []
    assert "AUTHOR_HANDBACK_PUBLICATION=PASS" not in capsys.readouterr().out


def test_a_malformed_element_seen_only_after_publication_still_fails(monkeypatch, tmp_path, capsys) -> None:
    """The post-write uniqueness listing is held to the same standard as the first one."""
    gh = FakeGh()
    original = gh.run_json
    seen = {"listings": 0}

    def poisoned_second_listing(*args, stdin=None):
        result = original(*args, stdin=stdin)
        if "--method" not in args and args[-1].startswith("repos/owner/repo/issues/123/comments"):
            seen["listings"] += 1
            if seen["listings"] == 2:
                return list(result) + [None]
        return result

    gh.run_json = poisoned_second_listing
    with pytest.raises(MODULE.HandbackError, match="not an object"):
        run_main(monkeypatch, tmp_path, gh)
    assert "AUTHOR_HANDBACK_PUBLICATION=PASS" not in capsys.readouterr().out


# --- hand-off state is project vocabulary, not built in ---------------------


def test_default_state_is_neutral_and_project_states_are_rejected_unless_configured(
    monkeypatch, tmp_path
) -> None:
    assert MODULE.allowed_states() == ["AWAITING_INDEPENDENT_REVIEW"]
    gh = FakeGh()
    with pytest.raises(SystemExit, match="AUTHOR_HANDBACK_PUBLICATION=FAIL.*state must be one of"):
        run_main(monkeypatch, tmp_path, gh, state="PROJECT_SPECIFIC_STATE")
    assert gh.calls == [] and gh.writes == []


def test_project_states_come_from_a_flag_or_the_environment(monkeypatch, tmp_path) -> None:
    gh = FakeGh()
    run_main(monkeypatch, tmp_path, gh, "--allowed-state", "PROJECT_STATE", state="PROJECT_STATE")
    assert gh.writes[0][1]["body"].endswith("PROJECT_STATE")
    gh = FakeGh()
    run_main(monkeypatch, tmp_path, gh, state="ENV_STATE",
             env={MODULE.STATES_ENV: "ENV_STATE, OTHER_STATE"})
    assert gh.writes[0][1]["body"].endswith("ENV_STATE")


@pytest.mark.parametrize("bad", ["lower_case", "HAS SPACE", "X", "1START", "A" * 70])
def test_invalid_state_names_are_rejected(monkeypatch, bad) -> None:
    monkeypatch.delenv(MODULE.STATES_ENV, raising=False)
    with pytest.raises(MODULE.HandbackError, match="invalid hand-off state"):
        MODULE.allowed_states([bad])


def test_no_project_specific_identifiers_remain_in_the_script() -> None:
    source = SCRIPT.read_text(encoding="utf-8").lower()
    for banned in ("score2gp", "tticom", "governance_review", "codex_review"):
        assert banned not in source


def test_subprocess_output_is_decoded_as_utf8_on_every_platform(monkeypatch) -> None:
    seen = []

    def fake_run(args, **kwargs):
        seen.append(kwargs)
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps({"t": "café"}))

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    assert MODULE.run_json("gh", "api", "x", stdin={"body": "café"}) == {"t": "café"}
    MODULE.run_text("git", "status")
    assert all(item["encoding"] == "utf-8" and item["text"] for item in seen)


def test_command_line_failure_is_a_clean_exit_not_a_traceback(monkeypatch, tmp_path) -> None:
    script = str(SCRIPT)
    result = subprocess.run(
        [os.sys.executable, script, "--repo", "o/r", "--pr", "1", "--expected-head", "x" * 3,
         "--worktree", str(tmp_path), "--packet", str(tmp_path / "none.json"), "--state", STATE],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode != 0
    assert "Traceback" not in result.stderr or "AUTHOR_HANDBACK_PUBLICATION=FAIL" in result.stderr
