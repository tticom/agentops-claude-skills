"""Cross-skill distribution contracts: vendoring, prerequisites, portability."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
SKILL_NAMES = sorted(p.name for p in SKILLS.iterdir() if p.is_dir())

PREREQ_LINE = re.compile(r"^\*\*Prerequisite skills:\*\*\s*(.+)$", re.MULTILINE)
NO_PREREQ = "has no prerequisite skills"


def skill_text(name: str) -> str:
    return (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")


def normalised(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


# --- vendored copies must not drift ------------------------------------------

# Canonical source -> the skills that carry a byte-identical copy so that each
# skill stays self-contained. Editing a copy without the source fails this test.
VENDORED = {
    "identity-safe-git/scripts/role_authority_gate.py": ["code-review/scripts/role_authority_gate.py"],
    "code-review/scripts/gh_publication.py": ["publish-pr-handback/scripts/gh_publication.py"],
}


@pytest.mark.parametrize("canonical", sorted(VENDORED))
def test_vendored_copies_are_byte_identical(canonical: str) -> None:
    source = SKILLS / canonical
    assert source.is_file()
    for copy in VENDORED[canonical]:
        assert normalised(SKILLS / copy) == normalised(source), (
            f"{copy} drifted from {canonical}; edit the canonical file and re-copy it"
        )


def test_every_script_that_imports_a_sibling_module_finds_it_in_its_own_skill() -> None:
    """Self-containment: a script's local imports must resolve inside its own directory."""
    for script in SKILLS.rglob("*.py"):
        if script.name.startswith("test_"):
            continue
        local = {p.stem for p in script.parent.glob("*.py")}
        for line in script.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^(?:from|import)\s+([a-z_][a-z0-9_]*)", line)
            if not match:
                continue
            module = match.group(1)
            if module in local or module in sys.stdlib_module_names or module == "__future__":
                continue
            raise AssertionError(f"{script.relative_to(ROOT)} imports {module!r}, which is not in its own skill")


# --- prerequisites must be declared and real --------------------------------


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_every_skill_declares_its_prerequisites_truthfully(name: str) -> None:
    text = skill_text(name)
    match = PREREQ_LINE.search(text)
    if match is None:
        assert NO_PREREQ in text, f"{name} must declare '**Prerequisite skills:**' or say it {NO_PREREQ}"
        return
    declared = re.findall(r"`([a-z0-9-]+)`", match.group(1))
    assert declared, f"{name} has an empty prerequisite line"
    for prerequisite in declared:
        assert prerequisite != name, f"{name} lists itself as a prerequisite"
        assert prerequisite in SKILL_NAMES, f"{name} requires {prerequisite!r}, which is not shipped here"
    assert "REQUIRED_SKILL_MISSING" in text, f"{name} must say what to do when a prerequisite is absent"


def test_prerequisites_are_acyclic() -> None:
    graph = {}
    for name in SKILL_NAMES:
        match = PREREQ_LINE.search(skill_text(name))
        graph[name] = re.findall(r"`([a-z0-9-]+)`", match.group(1)) if match else []
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(node: str, trail: tuple[str, ...]) -> None:
        assert node not in visiting, f"prerequisite cycle: {' -> '.join((*trail, node))}"
        if node in done:
            return
        visiting.add(node)
        for child in graph[node]:
            visit(child, (*trail, node))
        visiting.discard(node)
        done.add(node)

    for name in SKILL_NAMES:
        visit(name, ())


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_a_skill_that_names_a_sibling_script_declares_it_as_a_prerequisite(name: str) -> None:
    """A skill that runs another skill's helper must require that skill."""
    text = skill_text(name)
    match = PREREQ_LINE.search(text)
    declared = set(re.findall(r"`([a-z0-9-]+)`", match.group(1))) if match else set()
    for other in SKILL_NAMES:
        if other == name:
            continue
        if re.search(rf"`{re.escape(other)}`[^\n]*`?scripts/", text) or f"<{other}-skill-dir>" in text:
            assert other in declared, f"{name} uses {other}'s scripts but does not declare it a prerequisite"


# --- native Windows: no shell scripts, helpers start cleanly ------------------


def test_no_shell_scripts_are_shipped() -> None:
    shells = [p for p in SKILLS.rglob("*") if p.suffix.lower() in {".sh", ".bash", ".zsh"}]
    assert shells == [], f"shell scripts break native Windows use: {[str(p) for p in shells]}"


def test_no_script_hardcodes_a_posix_only_interpreter_or_path() -> None:
    for script in SKILLS.rglob("*.py"):
        text = script.read_text(encoding="utf-8")
        assert "/bin/bash" not in text and "/usr/bin/python3" not in text, script
        if not script.name.startswith("test_"):
            assert "/tmp/" not in text.replace("reviewer://", ""), f"{script} hardcodes /tmp"


def _cli_helpers() -> list[Path]:
    helpers = []
    for script in SKILLS.rglob("scripts/*.py"):
        if script.name.startswith("test_") or script.name == "role_authority_gate.py" and "code-review" in script.parts:
            continue
        if "ArgumentParser" in script.read_text(encoding="utf-8"):
            helpers.append(script)
    return sorted(helpers)


@pytest.mark.parametrize("script", _cli_helpers(), ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_every_cli_helper_starts_and_prints_help_without_a_shell(script: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(script), "--help"], capture_output=True, text=True, encoding="utf-8", timeout=60
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()


# --- documentation must not overclaim -----------------------------------------


def test_documented_skill_index_matches_directories() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    block = readme.split("<!-- skills:start -->")[1].split("<!-- skills:end -->")[0]
    assert sorted(re.findall(r"^\s*[-*]\s+`([a-z0-9-]+)`", block, re.MULTILINE)) == SKILL_NAMES


def test_no_go_alias_is_introduced() -> None:
    assert "go" not in SKILL_NAMES
    assert "dispatch-task" in SKILL_NAMES


# --- Windows decodes subprocess text with the system code page unless told otherwise ---

import ast  # noqa: E402

SUBPROCESS_CALLS = {"run", "Popen", "check_output", "check_call", "call"}


def _text_mode_calls_without_encoding(script: Path) -> list[int]:
    tree = ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        if not (isinstance(owner, ast.Name) and owner.id == "subprocess" and node.func.attr in SUBPROCESS_CALLS):
            continue
        keywords = {k.arg: k.value for k in node.keywords if k.arg}
        text_mode = any(
            isinstance(keywords.get(flag), ast.Constant) and keywords[flag].value is True
            for flag in ("text", "universal_newlines")
        )
        if text_mode and "encoding" not in keywords:
            offenders.append(node.lineno)
    return offenders


PRODUCTION_SCRIPTS = sorted(p for p in SKILLS.rglob("scripts/*.py") if not p.name.startswith("test_"))


@pytest.mark.parametrize("script", PRODUCTION_SCRIPTS, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_text_mode_subprocess_calls_set_an_explicit_encoding(script: Path) -> None:
    assert _text_mode_calls_without_encoding(script) == [], (
        f"{script.name}: subprocess text=True without encoding= decodes with the Windows code page"
    )


def test_the_encoding_check_itself_detects_a_violation(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("import subprocess\nsubprocess.run(['x'], capture_output=True, text=True)\n", encoding="utf-8")
    good = tmp_path / "good.py"
    good.write_text(
        "import subprocess\nsubprocess.run(['x'], capture_output=True, text=True, encoding='utf-8')\n",
        encoding="utf-8",
    )
    assert _text_mode_calls_without_encoding(bad) == [2]
    assert _text_mode_calls_without_encoding(good) == []
