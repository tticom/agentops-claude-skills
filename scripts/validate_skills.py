#!/usr/bin/env python3
"""Validate the AgentOps skills distribution (standard library only).

Checks, for every directory under ``skills/``:

* ``SKILL.md`` exists and starts with strict frontmatter (``name`` matches the
  directory, ``description`` present, no unquoted ``: `` in plain scalars);
* markdown links and bundled ``scripts/``, ``references/`` and ``assets/``
  paths resolve, and never escape the skill directory (each skill must be
  installable on its own);
* Python scripts parse, and no symlinks are present;
* no legacy-lineage, harness-specific or machine-specific strings appear,
  except in explicit provenance files (``NOTICE.md``, ``PROVENANCE.md``,
  ``LICENSE*``).

The README skill index (between the ``skills:start`` and ``skills:end``
markers) must list exactly the skill directories that exist.

Exit status is 0 when the tree is valid and 1 otherwise.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024

README_START = "<!-- skills:start -->"
README_END = "<!-- skills:end -->"
README_ENTRY_RE = re.compile(r"^\s*[-*]\s+`([a-z0-9][a-z0-9-]*)`")

PROVENANCE_FILES = frozenset(
    {"NOTICE.md", "PROVENANCE.md", "LICENSE", "LICENSE.md", "LICENSE.txt"}
)
ALLOWED_TOP_LEVEL_FILES = frozenset({".gitkeep"})

FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "FORBIDDEN_UPSTREAM_REFERENCE",
        re.compile(r"\bmatt\b|pocock", re.IGNORECASE),
        "reference to the legacy upstream lineage",
    ),
    (
        "FORBIDDEN_HARNESS_REFERENCE",
        re.compile(r"\bgemini\b|antigravity|\bagy\b", re.IGNORECASE),
        "reference to a retired harness",
    ),
    (
        "FORBIDDEN_ABSOLUTE_PATH",
        re.compile(r"/home/[A-Za-z]|/Users/|[A-Za-z]:\\Users\\|~/work"),
        "machine-specific absolute path",
    ),
    (
        "FORBIDDEN_LEGACY_LAYOUT",
        re.compile(
            r"skills/(?:engineering|productivity|misc|in-progress)\b"
            r"|plugins/(?:engineering|productivity|misc|in-progress)\b"
        ),
        "legacy bucketed layout assumption",
    ),
)

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
BUNDLED_PATH_RE = re.compile(
    r"(?<![\w./~$\\-])"
    r"((?:\.\./)*(?:scripts|references|assets)/(?:[A-Za-z0-9_.\-/]*[A-Za-z0-9_\-/])?)"
)
PLACEHOLDER_FOLLOWERS = "*<{$["
FRONTMATTER_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:[ \t]+(.*))?$")


@dataclass(frozen=True)
class Issue:
    path: str
    line: int | None
    code: str
    message: str

    def render(self) -> str:
        where = self.path if self.line is None else f"{self.path}:{self.line}"
        return f"{where}: {self.code}: {self.message}"


def _plain_scalar_problem(key: str, value: str) -> str | None:
    if not value:
        return None
    if value[0] == '"':
        if len(value) < 2 or not value.endswith('"') or value.endswith('\\"'):
            return "unterminated double-quoted string"
        return None
    if value[0] == "'":
        if len(value) < 2 or not value.endswith("'"):
            return "unterminated single-quoted string"
        return None
    if ": " in value or value.endswith(":"):
        return "unquoted ': ' in a plain scalar (invalid YAML; quote the value)"
    if value[0] in "&*!%@`":
        return f"plain scalar cannot start with {value[0]!r}"
    if key in ("name", "description") and value[0] in "[{":
        return f"{key} must be a string, not a YAML collection"
    return None


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def parse_frontmatter(
    lines: list[str],
) -> tuple[dict[str, str], list[tuple[int, str, str]]]:
    """Parse the lines between the ``---`` delimiters (line 2 onward)."""
    fields: dict[str, str] = {}
    problems: list[tuple[int, str, str]] = []
    last_plain_key: str | None = None
    index = 0
    while index < len(lines):
        raw = lines[index]
        lineno = index + 2
        if not raw.strip() or raw.lstrip().startswith("#"):
            index += 1
            continue
        if raw[0] in " \t":
            if last_plain_key is None:
                problems.append(
                    (lineno, "FRONTMATTER_SYNTAX", "indented line without a key")
                )
            else:
                continuation = raw.strip()
                problem = _plain_scalar_problem(last_plain_key, continuation)
                if problem and not continuation.startswith(("'", '"')):
                    problems.append((lineno, "FRONTMATTER_SYNTAX", problem))
                fields[last_plain_key] = f"{fields[last_plain_key]} {continuation}".strip()
            index += 1
            continue
        match = FRONTMATTER_KEY_RE.match(raw)
        if not match:
            problems.append(
                (lineno, "FRONTMATTER_SYNTAX", "expected 'key: value' or a comment")
            )
            index += 1
            continue
        key, value = match.group(1), (match.group(2) or "").strip()
        if key in fields:
            problems.append((lineno, "FRONTMATTER_DUPLICATE_KEY", f"duplicate key {key!r}"))
        last_plain_key = key
        if value[:1] in (">", "|"):
            block: list[str] = []
            cursor = index + 1
            while cursor < len(lines) and (
                not lines[cursor].strip() or lines[cursor][0] in " \t"
            ):
                if lines[cursor].strip():
                    block.append(lines[cursor].strip())
                cursor += 1
            fields[key] = (" " if value[0] == ">" else "\n").join(block)
            last_plain_key = None
            index = cursor
            continue
        problem = _plain_scalar_problem(key, value)
        if problem:
            problems.append((lineno, "FRONTMATTER_SYNTAX", problem))
        fields[key] = _unquote(value)
        index += 1
    return fields, problems


def _walk(skill_dir: Path) -> tuple[list[Path], list[Path]]:
    """Return (files, symlinks) below skill_dir without following links."""
    files: list[Path] = []
    links: list[Path] = []
    for current, dirnames, filenames in os.walk(skill_dir, followlinks=False):
        current_path = Path(current)
        for name in list(dirnames):
            candidate = current_path / name
            if candidate.is_symlink():
                links.append(candidate)
                dirnames.remove(name)
        for name in filenames:
            candidate = current_path / name
            if candidate.is_symlink():
                links.append(candidate)
            else:
                files.append(candidate)
    return sorted(files), sorted(links)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return None


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _check_frontmatter(skill_dir: Path, rel: str, text: str, issues: list[Issue]) -> None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        issues.append(Issue(rel, 1, "FRONTMATTER_MISSING", "SKILL.md must start with '---'"))
        return
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        issues.append(Issue(rel, 1, "FRONTMATTER_UNTERMINATED", "no closing '---'"))
        return
    fields, problems = parse_frontmatter(lines[1:end])
    for lineno, code, message in problems:
        issues.append(Issue(rel, lineno, code, message))
    name = fields.get("name", "")
    description = fields.get("description", "")
    if not name:
        issues.append(Issue(rel, None, "FRONTMATTER_NAME_MISSING", "name is required"))
    elif not NAME_RE.fullmatch(name) or len(name) > MAX_NAME_LENGTH:
        issues.append(
            Issue(
                rel,
                None,
                "FRONTMATTER_NAME_INVALID",
                f"name {name!r} must be lowercase-hyphenated, at most {MAX_NAME_LENGTH} chars",
            )
        )
    elif name != skill_dir.name:
        issues.append(
            Issue(
                rel,
                None,
                "FRONTMATTER_NAME_MISMATCH",
                f"name {name!r} must equal directory {skill_dir.name!r}",
            )
        )
    if not description.strip():
        issues.append(
            Issue(rel, None, "FRONTMATTER_DESCRIPTION_MISSING", "description is required")
        )
    elif len(description) > MAX_DESCRIPTION_LENGTH:
        issues.append(
            Issue(
                rel,
                None,
                "FRONTMATTER_DESCRIPTION_TOO_LONG",
                f"description is {len(description)} chars; limit is {MAX_DESCRIPTION_LENGTH}",
            )
        )


def _check_references(
    skill_dir: Path, path: Path, rel: str, text: str, issues: list[Issue]
) -> None:
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in LINK_RE.finditer(line):
            target = match.group(1)
            if target.startswith("#") or SCHEME_RE.match(target):
                continue
            target = re.split(r"[#?]", target, maxsplit=1)[0]
            if not target:
                continue
            resolved = path.parent / target
            if not _is_within(resolved, skill_dir):
                issues.append(
                    Issue(rel, lineno, "REFERENCE_ESCAPES_SKILL", f"link {target!r} leaves the skill")
                )
            elif not resolved.exists():
                issues.append(
                    Issue(rel, lineno, "REFERENCE_BROKEN", f"link {target!r} does not resolve")
                )
        for match in BUNDLED_PATH_RE.finditer(line):
            reference = match.group(1)
            follower = line[match.end() : match.end() + 1]
            if follower and follower in PLACEHOLDER_FOLLOWERS:
                continue
            candidates = (skill_dir / reference, path.parent / reference)
            if not any(_is_within(c, skill_dir) for c in candidates):
                issues.append(
                    Issue(
                        rel,
                        lineno,
                        "REFERENCE_ESCAPES_SKILL",
                        f"path {reference!r} leaves the skill",
                    )
                )
            elif not any(c.exists() for c in candidates):
                issues.append(
                    Issue(
                        rel,
                        lineno,
                        "REFERENCE_BROKEN",
                        f"bundled path {reference!r} does not resolve inside the skill",
                    )
                )


def _check_forbidden(rel: str, text: str, issues: list[Issue]) -> None:
    for lineno, line in enumerate(text.splitlines(), start=1):
        for code, pattern, message in FORBIDDEN_PATTERNS:
            found = pattern.search(line)
            if found:
                issues.append(Issue(rel, lineno, code, f"{message}: {found.group(0)!r}"))


def validate_skill(root: Path, skill_dir: Path, issues: list[Issue]) -> None:
    skill_rel = skill_dir.relative_to(root).as_posix()
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        issues.append(Issue(skill_rel, None, "SKILL_MD_MISSING", "SKILL.md not found"))
        return
    files, links = _walk(skill_dir)
    for link in links:
        issues.append(
            Issue(
                link.relative_to(root).as_posix(),
                None,
                "SYMLINK_FORBIDDEN",
                "symlinks are not allowed; the installer copies snapshots",
            )
        )
    for path in files:
        rel = path.relative_to(root).as_posix()
        text = _read_text(path)
        if text is None:
            continue
        if path == skill_md:
            _check_frontmatter(skill_dir, rel, text, issues)
        if path.name not in PROVENANCE_FILES:
            _check_forbidden(rel, text, issues)
        if path.suffix.lower() == ".md":
            _check_references(skill_dir, path, rel, text, issues)
        if path.suffix == ".py":
            try:
                ast.parse(text, filename=rel)
            except SyntaxError as error:
                issues.append(Issue(rel, error.lineno, "PYTHON_SYNTAX", error.msg))


def _advertised_skills(root: Path, issues: list[Issue]) -> set[str] | None:
    readme = root / "README.md"
    if not readme.is_file():
        issues.append(Issue("README.md", None, "README_MISSING", "README.md not found"))
        return None
    text = readme.read_text(encoding="utf-8-sig")
    start, end = text.find(README_START), text.find(README_END)
    if start < 0 or end < start:
        issues.append(
            Issue(
                "README.md",
                None,
                "README_INDEX_MISSING",
                f"expected {README_START} ... {README_END} skill index",
            )
        )
        return None
    names: set[str] = set()
    for line in text[start + len(README_START) : end].splitlines():
        match = README_ENTRY_RE.match(line)
        if match:
            names.add(match.group(1))
    return names


def validate_repository(root: Path) -> tuple[list[Issue], list[str]]:
    issues: list[Issue] = []
    skills_root = root / "skills"
    if not skills_root.is_dir():
        issues.append(Issue("skills", None, "SKILLS_DIR_MISSING", "skills/ not found"))
        return issues, []
    skill_names: list[str] = []
    for entry in sorted(skills_root.iterdir()):
        if entry.is_symlink():
            issues.append(
                Issue(f"skills/{entry.name}", None, "SYMLINK_FORBIDDEN", "symlinks are not allowed")
            )
        elif entry.is_dir():
            skill_names.append(entry.name)
            validate_skill(root, entry, issues)
        elif entry.name not in ALLOWED_TOP_LEVEL_FILES:
            issues.append(
                Issue(
                    f"skills/{entry.name}",
                    None,
                    "STRAY_FILE",
                    "skills/ may contain only skill directories",
                )
            )
    advertised = _advertised_skills(root, issues)
    if advertised is not None:
        for name in sorted(advertised - set(skill_names)):
            issues.append(
                Issue("README.md", None, "ADVERTISED_SKILL_MISSING", f"{name!r} is listed but has no directory")
            )
        for name in sorted(set(skill_names) - advertised):
            issues.append(
                Issue("README.md", None, "SKILL_NOT_ADVERTISED", f"{name!r} exists but is not in the README index")
            )
    return issues, skill_names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (default: parent of scripts/)",
    )
    args = parser.parse_args(argv)
    issues, skill_names = validate_repository(args.root.resolve())
    for issue in issues:
        print(issue.render(), file=sys.stderr)
    if issues:
        print(f"FAILED: {len(issues)} problem(s) in {len(skill_names)} skill(s)", file=sys.stderr)
        return 1
    print(f"OK: {len(skill_names)} skill(s) validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
