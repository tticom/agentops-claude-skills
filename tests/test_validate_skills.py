from __future__ import annotations

import os
from pathlib import Path

import pytest

import validate_skills
from validate_skills import validate_repository

REPO_ROOT = Path(__file__).resolve().parents[1]

GOOD_SKILL = """---
name: {name}
description: Use when validating a fixture skill.
---

# {name}
"""


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_repo(tmp_path: Path, skills: tuple[str, ...] = ("alpha",), index: tuple[str, ...] | None = None) -> Path:
    listed = skills if index is None else index
    entries = "\n".join(f"- `{name}` - fixture" for name in listed)
    write(
        tmp_path / "README.md",
        f"# fixture\n\n{validate_skills.README_START}\n{entries}\n{validate_skills.README_END}\n",
    )
    (tmp_path / "skills").mkdir()
    for name in skills:
        write(tmp_path / "skills" / name / "SKILL.md", GOOD_SKILL.format(name=name))
    return tmp_path


def codes(root: Path) -> list[str]:
    issues, _ = validate_repository(root)
    return [issue.code for issue in issues]


def test_repository_itself_is_valid() -> None:
    issues, _ = validate_repository(REPO_ROOT)
    assert [issue.render() for issue in issues] == []


def test_empty_scaffold_is_valid(tmp_path: Path) -> None:
    make_repo(tmp_path, skills=())
    assert codes(tmp_path) == []


def test_valid_skill_passes(tmp_path: Path) -> None:
    make_repo(tmp_path)
    assert codes(tmp_path) == []


def test_cli_exit_status(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_repo(tmp_path)
    assert validate_skills.main(["--root", str(tmp_path)]) == 0
    assert "OK: 1 skill(s)" in capsys.readouterr().out
    (tmp_path / "skills" / "alpha" / "SKILL.md").unlink()
    assert validate_skills.main(["--root", str(tmp_path)]) == 1
    assert "SKILL_MD_MISSING" in capsys.readouterr().err


def test_missing_skills_directory(tmp_path: Path) -> None:
    write(tmp_path / "README.md", "# x\n")
    assert codes(tmp_path) == ["SKILLS_DIR_MISSING"]


def test_missing_frontmatter(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write(tmp_path / "skills/alpha/SKILL.md", "# no frontmatter\n")
    assert codes(tmp_path) == ["FRONTMATTER_MISSING"]


def test_unterminated_frontmatter(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write(tmp_path / "skills/alpha/SKILL.md", "---\nname: alpha\ndescription: x\n")
    assert codes(tmp_path) == ["FRONTMATTER_UNTERMINATED"]


def test_name_must_match_directory(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write(tmp_path / "skills/alpha/SKILL.md", GOOD_SKILL.format(name="beta"))
    assert codes(tmp_path) == ["FRONTMATTER_NAME_MISMATCH"]


@pytest.mark.parametrize("name", ["Alpha", "al_pha", "-alpha", "a" * 65])
def test_invalid_names(tmp_path: Path, name: str) -> None:
    make_repo(tmp_path)
    write(tmp_path / "skills/alpha/SKILL.md", f"---\nname: {name}\ndescription: ok\n---\n")
    assert codes(tmp_path) == ["FRONTMATTER_NAME_INVALID"]


def test_description_required_and_bounded(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write(tmp_path / "skills/alpha/SKILL.md", "---\nname: alpha\n---\n")
    assert codes(tmp_path) == ["FRONTMATTER_DESCRIPTION_MISSING"]
    write(
        tmp_path / "skills/alpha/SKILL.md",
        f"---\nname: alpha\ndescription: {'x' * 1025}\n---\n",
    )
    assert codes(tmp_path) == ["FRONTMATTER_DESCRIPTION_TOO_LONG"]


def test_unquoted_colon_in_plain_scalar_is_rejected(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write(
        tmp_path / "skills/alpha/SKILL.md",
        "---\nname: alpha\ndescription: Use when: something happens\n---\n",
    )
    assert codes(tmp_path) == ["FRONTMATTER_SYNTAX"]


def test_quoted_and_block_scalars_are_accepted(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write(
        tmp_path / "skills/alpha/SKILL.md",
        '---\nname: alpha\ndescription: "Use when: quoted"\nnotes: >\n  folded: text\n  more\n---\n',
    )
    assert codes(tmp_path) == []


def test_duplicate_frontmatter_key(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write(
        tmp_path / "skills/alpha/SKILL.md",
        "---\nname: alpha\ndescription: a\ndescription: b\n---\n",
    )
    assert codes(tmp_path) == ["FRONTMATTER_DUPLICATE_KEY"]


def test_directory_without_skill_md(tmp_path: Path) -> None:
    make_repo(tmp_path)
    (tmp_path / "skills/beta").mkdir()
    assert sorted(codes(tmp_path)) == ["SKILL_MD_MISSING", "SKILL_NOT_ADVERTISED"]


def test_stray_file_in_skills_root(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write(tmp_path / "skills/notes.md", "x")
    assert codes(tmp_path) == ["STRAY_FILE"]


def test_readme_index_must_match_directories(tmp_path: Path) -> None:
    make_repo(tmp_path, skills=("alpha",), index=("alpha", "ghost"))
    assert codes(tmp_path) == ["ADVERTISED_SKILL_MISSING"]
    make_repo_dir = tmp_path / "skills" / "beta"
    write(make_repo_dir / "SKILL.md", GOOD_SKILL.format(name="beta"))
    assert sorted(codes(tmp_path)) == ["ADVERTISED_SKILL_MISSING", "SKILL_NOT_ADVERTISED"]


def test_readme_index_markers_required(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write(tmp_path / "README.md", "# no markers\n")
    assert codes(tmp_path) == ["README_INDEX_MISSING"]


def test_bundled_script_and_reference_resolve(tmp_path: Path) -> None:
    make_repo(tmp_path)
    skill = tmp_path / "skills/alpha"
    write(skill / "scripts/run.py", "print('ok')\n")
    write(skill / "references/guide.md", "# guide\n")
    write(
        skill / "SKILL.md",
        GOOD_SKILL.format(name="alpha")
        + "\nRun `python scripts/run.py` and read [guide](references/guide.md).\n"
        + "See references/guide.md and the scripts/ directory.\n",
    )
    assert codes(tmp_path) == []


def test_broken_bundled_path(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write(
        tmp_path / "skills/alpha/SKILL.md",
        GOOD_SKILL.format(name="alpha") + "\nRun `python scripts/missing.py`.\n",
    )
    assert codes(tmp_path) == ["REFERENCE_BROKEN"]


def test_broken_markdown_link(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write(
        tmp_path / "skills/alpha/SKILL.md",
        GOOD_SKILL.format(name="alpha") + "\nSee [more](other.md).\n",
    )
    assert codes(tmp_path) == ["REFERENCE_BROKEN"]


def test_external_links_and_anchors_are_ignored(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write(
        tmp_path / "skills/alpha/SKILL.md",
        GOOD_SKILL.format(name="alpha")
        + "\n[docs](https://example.com/scripts/x) [top](#top) https://example.com/scripts/x.py\n",
    )
    assert codes(tmp_path) == []


def test_placeholders_are_not_paths(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write(
        tmp_path / "skills/alpha/SKILL.md",
        GOOD_SKILL.format(name="alpha")
        + "\nWrite `references/<name>.md` and match scripts/*.py.\n",
    )
    assert codes(tmp_path) == []


def test_bare_directory_reference_must_exist(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write(
        tmp_path / "skills/alpha/SKILL.md",
        GOOD_SKILL.format(name="alpha") + "\nHelpers live in the scripts/ directory.\n",
    )
    assert codes(tmp_path) == ["REFERENCE_BROKEN"]
    (tmp_path / "skills/alpha/scripts").mkdir()
    assert codes(tmp_path) == []


def test_link_escaping_the_skill_is_rejected(tmp_path: Path) -> None:
    make_repo(tmp_path, skills=("alpha", "beta"))
    write(
        tmp_path / "skills/alpha/SKILL.md",
        GOOD_SKILL.format(name="alpha") + "\nSee [b](../beta/SKILL.md).\n",
    )
    assert codes(tmp_path) == ["REFERENCE_ESCAPES_SKILL"]


def test_bundled_path_escaping_the_skill_is_rejected(tmp_path: Path) -> None:
    make_repo(tmp_path, skills=("alpha", "beta"))
    write(tmp_path / "skills/beta/scripts/x.py", "x = 1\n")
    write(
        tmp_path / "skills/alpha/SKILL.md",
        GOOD_SKILL.format(name="alpha") + "\nRun `../scripts/x.py`.\n",
    )
    assert codes(tmp_path) == ["REFERENCE_ESCAPES_SKILL"]


def test_python_syntax_error(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write(tmp_path / "skills/alpha/scripts/bad.py", "def broken(:\n")
    assert codes(tmp_path) == ["PYTHON_SYNTAX"]


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("Ask Matt for help", "FORBIDDEN_UPSTREAM_REFERENCE"),
        ("see mattpocock/skills", "FORBIDDEN_UPSTREAM_REFERENCE"),
        ("Runs under Gemini", "FORBIDDEN_HARNESS_REFERENCE"),
        ("the Antigravity harness", "FORBIDDEN_HARNESS_REFERENCE"),
        ("clone agy-skills", "FORBIDDEN_HARNESS_REFERENCE"),
        ("cd /home/tticom-automation/work", "FORBIDDEN_ABSOLUTE_PATH"),
        ("open C:\\Users\\someone\\x", "FORBIDDEN_ABSOLUTE_PATH"),
        ("under skills/engineering/foo", "FORBIDDEN_LEGACY_LAYOUT"),
        ("under plugins/productivity", "FORBIDDEN_LEGACY_LAYOUT"),
    ],
)
def test_forbidden_strings(tmp_path: Path, text: str, code: str) -> None:
    make_repo(tmp_path)
    write(tmp_path / "skills/alpha/SKILL.md", GOOD_SKILL.format(name="alpha") + f"\n{text}\n")
    assert code in codes(tmp_path)


def test_ordinary_words_are_not_flagged(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write(
        tmp_path / "skills/alpha/SKILL.md",
        GOOD_SKILL.format(name="alpha") + "\nThis matters: formatting, matter, and $HOME\\.claude\\skills.\n",
    )
    assert codes(tmp_path) == []


def test_provenance_files_may_name_the_lineage(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write(tmp_path / "skills/alpha/NOTICE.md", "Derived in part from Matt Pocock's skills (MIT).\n")
    assert codes(tmp_path) == []


def test_symlink_is_rejected(tmp_path: Path) -> None:
    make_repo(tmp_path)
    target = tmp_path / "skills/alpha/real.md"
    write(target, "x")
    link = tmp_path / "skills/alpha/link.md"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform or account")
    assert codes(tmp_path) == ["SYMLINK_FORBIDDEN"]


# --- fail-closed decoding (review of f462886, blocker 1) -------------------


def write_bytes(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_non_utf8_skill_md_is_an_error_not_a_skip(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write_bytes(
        tmp_path / "skills/alpha/SKILL.md",
        b"---\nname: WRONG\ndescription: caf\xe9 Matt\n---\n[x](nope.md)\n",
    )
    assert codes(tmp_path) == ["NON_UTF8_FILE"]


def test_utf16_script_hiding_forbidden_text_is_rejected(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write_bytes(
        tmp_path / "skills/alpha/scripts/x.py",
        "# Gemini /home/someone\n".encode("utf-16"),
    )
    assert codes(tmp_path) == ["NON_UTF8_FILE"]


def test_non_utf8_file_with_unknown_suffix_is_rejected(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write_bytes(tmp_path / "skills/alpha/references/blob.bin", b"\xff\xfe\x00\x01")
    write_bytes(tmp_path / "skills/alpha/references/noext", b"\x80abc")
    assert codes(tmp_path) == ["NON_UTF8_FILE", "NON_UTF8_FILE"]


@pytest.mark.parametrize(
    "name", ["logo.png", "photo.JPG", "icon.ico", "guide.pdf", "font.woff2", "font.ttf"]
)
def test_allowlisted_binary_asset_under_assets_is_accepted(tmp_path: Path, name: str) -> None:
    make_repo(tmp_path)
    write_bytes(tmp_path / f"skills/alpha/assets/{name}", b"\x89\xff\x00\x01binary\x80")
    assert codes(tmp_path) == []


def test_non_decodable_markdown_cannot_bypass_reference_and_forbidden_checks(
    tmp_path: Path,
) -> None:
    make_repo(tmp_path)
    # Would raise REFERENCE_BROKEN and FORBIDDEN_UPSTREAM_REFERENCE if it were read.
    write_bytes(
        tmp_path / "skills/alpha/references/guide.md",
        b"See [missing](nope.md) and ask Matt. caf\xe9\n",
    )
    assert codes(tmp_path) == ["NON_UTF8_FILE"]


@pytest.mark.parametrize("name", ["data.json", "notes.txt", "run.sh", "page.svg", "cfg.yaml"])
def test_inspected_text_types_stay_strict_even_under_assets(tmp_path: Path, name: str) -> None:
    make_repo(tmp_path)
    write_bytes(tmp_path / f"skills/alpha/assets/{name}", b"\xff\xfe\x00bad")
    assert codes(tmp_path) == ["NON_UTF8_FILE"]


def test_image_outside_assets_is_rejected(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write_bytes(tmp_path / "skills/alpha/references/logo.png", b"\x89PNG\r\n\x1a\n")
    write_bytes(tmp_path / "skills/alpha/logo.png", b"\x89PNG\r\n\x1a\n")
    assert codes(tmp_path) == ["NON_UTF8_FILE", "NON_UTF8_FILE"]


def test_non_image_binary_under_assets_is_rejected(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write_bytes(tmp_path / "skills/alpha/assets/tool.exe", b"MZ\x90\x00\xff")
    assert codes(tmp_path) == ["NON_UTF8_FILE"]


def test_forbidden_ascii_inside_binary_asset_is_reported(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write_bytes(
        tmp_path / "skills/alpha/assets/logo.png",
        b"\x89PNG\r\n\x1a\n\xff\x00tEXt Comment: made for Gemini\x00",
    )
    assert codes(tmp_path) == ["FORBIDDEN_HARNESS_REFERENCE"]


def test_non_utf8_readme_is_an_issue_not_a_crash(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write_bytes(tmp_path / "README.md", b"\xff\xfe# readme")
    assert codes(tmp_path) == ["README_UNREADABLE"]


def test_unreadable_file_is_an_error_not_a_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_repo(tmp_path)
    target = write(tmp_path / "skills/alpha/references/a.md", "x")
    original = Path.read_bytes

    def flaky(self: Path) -> bytes:
        if self == target:
            raise PermissionError("denied")
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", flaky)
    assert codes(tmp_path) == ["READ_FAILED"]


def test_provenance_exemption_only_applies_in_skill_root(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write(tmp_path / "skills/alpha/NOTICE.md", "Derived from Matt Pocock's skills.\n")
    assert codes(tmp_path) == []
    write(tmp_path / "skills/alpha/scripts/NOTICE.md", "Derived from Matt Pocock's skills.\n")
    write(tmp_path / "skills/alpha/references/LICENSE", "Gemini\n")
    assert codes(tmp_path) == [
        "FORBIDDEN_HARNESS_REFERENCE",
        "FORBIDDEN_UPSTREAM_REFERENCE",
    ]


def test_provenance_file_must_still_be_utf8(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write_bytes(tmp_path / "skills/alpha/NOTICE.md", "Matt\n".encode("utf-16"))
    assert codes(tmp_path) == ["NON_UTF8_FILE"]


# --- review of 4d4c71b: containment/existence on one candidate (P1) ---------


def test_bundled_path_must_exist_on_a_contained_candidate(tmp_path: Path) -> None:
    """Reviewer reproduction: an external file must not satisfy the reference."""
    make_repo(tmp_path, skills=("alpha", "scripts"))
    write(tmp_path / "skills/scripts/tool.py", "x = 1\n")  # outside alpha
    write(
        tmp_path / "skills/alpha/references/guide.md",
        "# guide\n\nRun `../scripts/tool.py`.\n",
    )
    # skill-root candidate exists but is outside alpha; document-relative
    # candidate is inside alpha but missing.
    assert codes(tmp_path) == ["REFERENCE_BROKEN"]


def test_document_relative_bundled_path_inside_the_skill_is_accepted(tmp_path: Path) -> None:
    make_repo(tmp_path, skills=("alpha", "scripts"))
    write(tmp_path / "skills/scripts/tool.py", "x = 1\n")
    write(tmp_path / "skills/alpha/scripts/tool.py", "x = 1\n")
    write(
        tmp_path / "skills/alpha/references/guide.md",
        "# guide\n\nRun `../scripts/tool.py`.\n",
    )
    assert codes(tmp_path) == []


def test_bundled_path_outside_the_skill_with_no_internal_candidate_escapes(
    tmp_path: Path,
) -> None:
    make_repo(tmp_path, skills=("alpha", "scripts"))
    write(tmp_path / "skills/scripts/tool.py", "x = 1\n")
    write(tmp_path / "skills/alpha/SKILL.md", GOOD_SKILL.format(name="alpha") + "\nRun `../scripts/tool.py`.\n")
    assert codes(tmp_path) == ["REFERENCE_ESCAPES_SKILL"]


# --- review of 4d4c71b: validate quoted frontmatter scalars (P2) ------------


def frontmatter(description: str, name: str = "alpha") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n"


@pytest.mark.parametrize(
    "description",
    [
        r'"Use \q here"',  # invalid escape (reviewer reproduction)
        r'"Use "quoted" text"',  # unescaped embedded quote (reviewer reproduction)
        r'"Use \u12 here"',  # short unicode escape
        r'"Use \xZZ here"',  # non-hex escape
        r'"Use \U0011FFFF here"',  # code point out of range
        '"unterminated',
        '"closed" trailing',
        "'it's'",  # unescaped embedded single quote
        "'unterminated",
        "'closed' trailing",
    ],
)
def test_invalid_quoted_frontmatter_is_rejected(tmp_path: Path, description: str) -> None:
    make_repo(tmp_path)
    write(tmp_path / "skills/alpha/SKILL.md", frontmatter(description))
    assert codes(tmp_path) == ["FRONTMATTER_SYNTAX"]


@pytest.mark.parametrize(
    "description",
    [
        r'"Use \"quoted\" text"',
        r'"tab\there and \\ backslash"',
        r'"caf\u00e9 \x41 \U0001F600"',
        '"colon: inside"',
        "'it''s fine'",
        "'colon: inside'",
        '""',
        "''",
    ],
)
def test_valid_quoted_frontmatter_is_accepted(tmp_path: Path, description: str) -> None:
    make_repo(tmp_path)
    write(tmp_path / "skills/alpha/SKILL.md", frontmatter(description))
    assert "FRONTMATTER_SYNTAX" not in codes(tmp_path)


def test_quoted_name_is_decoded_before_comparison(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write(tmp_path / "skills/alpha/SKILL.md", frontmatter("ok", name='"alpha"'))
    assert codes(tmp_path) == []
    write(tmp_path / "skills/alpha/SKILL.md", frontmatter("ok", name="'alpha'"))
    assert codes(tmp_path) == []


def test_quote_led_continuation_line_is_not_exempt_from_plain_scalar_check(
    tmp_path: Path,
) -> None:
    make_repo(tmp_path)
    write(
        tmp_path / "skills/alpha/SKILL.md",
        '---\nname: alpha\ndescription: first line\n  "second: line\n---\n',
    )
    assert codes(tmp_path) == ["FRONTMATTER_SYNTAX"]


# --- review of b18cb47: dot-slash and repo-prefixed bundled paths (F1) -------


def skill_with_body(tmp_path: Path, body: str) -> None:
    write(tmp_path / "skills/alpha/SKILL.md", GOOD_SKILL.format(name="alpha") + f"\n{body}\n")


@pytest.mark.parametrize(
    "reference",
    [
        "./scripts/nope.py",  # reviewer reproduction
        "./references/nope.md",
        "././scripts/nope.py",
        "./assets/nope.png",
    ],
)
def test_dot_slash_reference_to_missing_target_is_broken(tmp_path: Path, reference: str) -> None:
    make_repo(tmp_path)
    skill_with_body(tmp_path, f"Run `{reference}`.")
    assert codes(tmp_path) == ["REFERENCE_BROKEN"]


def test_dot_slash_reference_to_existing_internal_target_is_accepted(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write(tmp_path / "skills/alpha/scripts/run.py", "print('ok')\n")
    write(tmp_path / "skills/alpha/references/guide.md", "# guide\n")
    skill_with_body(tmp_path, "Run `./scripts/run.py`; read ./references/guide.md and [g](./references/guide.md).")
    assert codes(tmp_path) == []


def test_dot_slash_reference_that_leaves_the_skill_escapes(tmp_path: Path) -> None:
    make_repo(tmp_path, skills=("alpha", "scripts"))
    write(tmp_path / "skills/scripts/tool.py", "x = 1\n")
    skill_with_body(tmp_path, "Run `./../scripts/tool.py`.")
    assert codes(tmp_path) == ["REFERENCE_ESCAPES_SKILL"]


def test_dot_slash_reference_keeps_placeholder_and_glob_guards(tmp_path: Path) -> None:
    make_repo(tmp_path)
    skill_with_body(tmp_path, "Write `./references/<name>.md` and match ./scripts/*.py and ./assets/{a,b}.")
    assert codes(tmp_path) == []


def test_dot_slash_reference_keeps_external_url_guard(tmp_path: Path) -> None:
    make_repo(tmp_path)
    skill_with_body(tmp_path, "See https://example.com/./scripts/x.py and [d](https://example.com/./references/y.md).")
    assert codes(tmp_path) == []


def test_dot_slash_prefix_does_not_hide_a_reference_in_a_document(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write(tmp_path / "skills/alpha/references/guide.md", "# guide\n\nRun ./scripts/nope.py\n")
    assert codes(tmp_path) == ["REFERENCE_BROKEN"]


@pytest.mark.parametrize(
    "reference",
    [
        "skills/alpha/scripts/nope.py",  # reviewer reproduction
        "./skills/alpha/references/nope.md",
        "skills/alpha/assets/",
    ],
)
def test_repo_prefixed_reference_is_rejected_as_not_portable(tmp_path: Path, reference: str) -> None:
    make_repo(tmp_path)
    skill_with_body(tmp_path, f"Run `{reference}`.")
    assert codes(tmp_path) == ["REFERENCE_NOT_PORTABLE"]


def test_repo_prefixed_reference_is_rejected_even_when_the_target_exists(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write(tmp_path / "skills/alpha/scripts/run.py", "print('ok')\n")
    skill_with_body(tmp_path, "Run `skills/alpha/scripts/run.py`.")
    assert codes(tmp_path) == ["REFERENCE_NOT_PORTABLE"]


def test_repo_prefixed_reference_keeps_placeholder_and_prose_guards(tmp_path: Path) -> None:
    make_repo(tmp_path)
    skill_with_body(
        tmp_path,
        "Layout is skills/<name>/scripts/ and the skills/ directory holds skills/alpha itself.",
    )
    assert codes(tmp_path) == []
