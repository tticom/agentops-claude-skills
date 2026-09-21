"""The migration inventory must stay consistent with what is actually shipped."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs" / "MIGRATION_INVENTORY.md"
SKILLS = ROOT / "skills"
SKILL_NAMES = sorted(p.name for p in SKILLS.iterdir() if p.is_dir())

DISPOSITIONS = {"migrated", "consolidated", "project-specific", "upstream-provided", "obsolete", "blocked"}
CLASSES = set("ABCDEF")
REQUIRED_NINE = (
    "code-review", "changes-requested", "publish-pr-handback", "identity-safe-git",
    "devils-advocate-review", "durable-handoff", "governed-development-loop",
    "governance-author", "hard-review",
)


def _rows() -> list[dict[str, str]]:
    text = INVENTORY.read_text(encoding="utf-8")
    section = text.split("## Commands", 1)[1].split("## Supporting files", 1)[0]
    rows = []
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split(" | ", 5)]
        assert len(cells) == 6, f"malformed inventory row: {line[:80]}"
        source, path, destination, disposition, klass, notes = cells
        rows.append({
            "source": source.strip("`"), "path": path, "destination": destination.strip("`"),
            "disposition": disposition, "class": klass, "notes": notes,
        })
    return rows


ROWS = _rows()
BY_SOURCE = {row["source"]: row for row in ROWS}


def test_inventory_is_present_and_parsed() -> None:
    assert ROWS, "no inventory rows parsed"
    assert len(BY_SOURCE) == len(ROWS), "a source command appears twice"


@pytest.mark.parametrize("row", ROWS, ids=lambda r: r["source"])
def test_every_row_is_complete_and_uses_the_defined_vocabulary(row: dict[str, str]) -> None:
    assert row["disposition"] in DISPOSITIONS
    assert row["class"] in CLASSES
    assert re.fullmatch(rf"`skills/{re.escape(row['source'])}/SKILL\.md` @ `[0-9a-f]{{10}}`", row["path"]), row["path"]
    assert len(row["notes"]) >= 40, "every row needs a concrete reason"


@pytest.mark.parametrize("row", ROWS, ids=lambda r: r["source"])
def test_destinations_match_dispositions(row: dict[str, str]) -> None:
    if row["disposition"] in {"migrated", "consolidated"}:
        assert row["destination"] != "-"
        assert (SKILLS / row["destination"] / "SKILL.md").is_file(), f"{row['destination']} is not shipped"
    else:
        assert row["destination"] == "-", "a skill that was not migrated must not name a destination"
        assert row["source"] not in SKILL_NAMES or row["source"] in {r["destination"] for r in ROWS}


def test_every_shipped_skill_is_accounted_for_exactly_once() -> None:
    destinations = Counter(
        row["destination"] for row in ROWS if row["disposition"] in {"migrated", "consolidated"}
    )
    assert sorted(destinations) == SKILL_NAMES
    assert all(count == 1 for count in destinations.values()), destinations


def test_the_required_skills_are_migrated_and_go_is_replaced() -> None:
    for name in REQUIRED_NINE:
        assert BY_SOURCE[name]["disposition"] == "migrated", name
        assert BY_SOURCE[name]["destination"] == name
    assert BY_SOURCE["go"]["destination"] == "dispatch-task"
    assert BY_SOURCE["go"]["disposition"] == "consolidated"
    assert "go" not in SKILL_NAMES


def test_matt_setup_and_router_skills_are_not_migrated() -> None:
    for name in ("ask-matt", "setup-matt-pocock-skills"):
        assert BY_SOURCE[name]["disposition"] == "obsolete"
        assert name not in SKILL_NAMES


def test_upstream_provided_rows_record_a_measured_similarity() -> None:
    for row in ROWS:
        if row["disposition"] == "upstream-provided":
            assert re.search(r"(?:similarity|\()\s*\d\.\d\d|\b0\.\d\d\b", row["notes"]), row["source"]


def test_blocked_rows_state_their_blocker() -> None:
    blocked = [row for row in ROWS if row["disposition"] == "blocked"]
    assert blocked, "expected the deliberately blocked command to be recorded"
    for row in blocked:
        assert re.search(r"could not|not attempted|cannot|needs", row["notes"]), row["source"]


def test_derived_skills_carry_the_upstream_notice() -> None:
    """Class B migrations keep attribution; no other skill claims a notice."""
    derived = {row["destination"] for row in ROWS if row["class"] == "B" and row["disposition"] == "migrated"}
    with_notice = {p.parent.name for p in SKILLS.glob("*/NOTICE.md")}
    assert derived == with_notice, (derived, with_notice)
    for name in derived:
        notice = (SKILLS / name / "NOTICE.md").read_text(encoding="utf-8")
        assert "MIT License" in notice and "Copyright (c)" in notice
        assert "Permission is hereby granted" in notice, "the upstream license text must be reproduced"


def test_summary_counts_match_the_rows() -> None:
    text = INVENTORY.read_text(encoding="utf-8")
    stated = dict(re.findall(r"^- (migrated|consolidated|project-specific|upstream-provided|obsolete|blocked): (\d+)$",
                             text, re.MULTILINE))
    actual = Counter(row["disposition"] for row in ROWS)
    for disposition in DISPOSITIONS:
        assert int(stated[disposition]) == actual.get(disposition, 0), disposition
    assert f"## Summary ({len(ROWS)} source commands)" in text


def test_source_revision_is_pinned_identically_in_the_inventory_and_provenance() -> None:
    sha = re.search(r"main` at `([0-9a-f]{40})`", INVENTORY.read_text(encoding="utf-8"))
    assert sha, "the inventory must pin a full source revision"
    assert sha.group(1) in (ROOT / "PROVENANCE.md").read_text(encoding="utf-8")


def test_supporting_files_have_dispositions_and_reasons() -> None:
    text = INVENTORY.read_text(encoding="utf-8")
    section = text.split("## Supporting files", 1)[1].split("## Migration limitations", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("| ") and not line.startswith("| Source")
            and not line.startswith("|---")]
    assert rows
    for line in rows:
        cells = [cell.strip() for cell in line.strip().strip("|").split(" | ", 2)]
        assert cells[1] in DISPOSITIONS, line[:60]
        assert len(cells[2]) >= 20, line[:60]
