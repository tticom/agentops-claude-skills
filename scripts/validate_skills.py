#!/usr/bin/env python3
"""Validate the AgentOps skills distribution (standard library only).

Checks, for every directory under ``skills/``:

* ``SKILL.md`` exists and starts with strict frontmatter (``name`` matches the
  directory, ``description`` present, no unquoted ``: `` in plain scalars);
* markdown links and bundled ``scripts/``, ``references/`` and ``assets/``
  paths (including ``./`` and ``../`` forms, normalised before checking)
  resolve, and never escape the skill directory (each skill must be
  installable on its own); repository-prefixed paths such as
  ``skills/<name>/scripts/x`` are rejected as not portable;
* every file is valid UTF-8 (fail closed: an undecodable file is an error, never
  skipped), except image, PDF and font files under ``assets/``, which are
  scanned as bytes for forbidden ASCII strings;
* Python scripts parse, and no symlinks are present;
* no legacy-lineage, harness-specific or machine-specific strings appear,
  except in provenance files (``NOTICE.md``, ``PROVENANCE.md``, ``LICENSE*``)
  located directly in the skill's root directory.

The README skill index (between the ``skills:start`` and ``skills:end``
markers) must list exactly the skill directories that exist.

Exit status is 0 when the tree is valid and 1 otherwise.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import string
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
# Interpreter bytecode is a build artifact, never distributed source. Only compiled
# files directly inside a ``__pycache__`` directory are skipped; any other file
# there, and any bytecode elsewhere, is still validated.
BYTECODE_SUFFIXES = frozenset({".pyc", ".pyo"})
BYTECODE_DIR = "__pycache__"
# Non-inspected, non-executable asset formats. Anything else must decode as UTF-8.
BINARY_ASSET_SUFFIXES = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp",
        ".pdf",
        ".ttf", ".otf", ".woff", ".woff2",
    }
)

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
# A bundled path may be written with any run of ``./`` and ``../`` prefixes; they
# are normalised (via resolution) before the containment and existence checks.
_PATH_TAIL = r"(?:[A-Za-z0-9_.\-/]*[A-Za-z0-9_\-/])?"
BUNDLED_PATH_RE = re.compile(
    r"(?<![\w./~$\\-])"
    rf"((?:\.{{1,2}}/)*(?:scripts|references|assets)/{_PATH_TAIL})"
)
# ``skills/<name>/scripts/...`` only resolves inside this repository's checkout,
# so it breaks once the skill is installed on its own. Such references are
# rejected as non-portable rather than validated.
REPO_PREFIXED_PATH_RE = re.compile(
    r"(?<![\w./~$\\-])"
    rf"((?:\.{{1,2}}/)*skills/[A-Za-z0-9][A-Za-z0-9-]*/(?:scripts|references|assets)/{_PATH_TAIL})"
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


_DOUBLE_QUOTE_ESCAPES = {
    "0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v",
    "f": "\f", "r": "\r", "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\",
    "N": "\x85", "_": "\xa0", "L": " ", "P": " ",
}
_HEX_ESCAPE_WIDTHS = {"x": 2, "u": 4, "U": 8}


def _parse_double_quoted(value: str) -> tuple[str | None, str | None]:
    """Decode a one-line double-quoted YAML scalar: (text, None) or (None, problem)."""
    out: list[str] = []
    index, length = 1, len(value)
    while index < length:
        char = value[index]
        if char == '"':
            if index != length - 1:
                return None, 'unescaped " inside a double-quoted string (write it as \\")'
            return "".join(out), None
        if char == "\\":
            index += 1
            if index >= length:
                break
            escape = value[index]
            if escape in _DOUBLE_QUOTE_ESCAPES:
                out.append(_DOUBLE_QUOTE_ESCAPES[escape])
                index += 1
                continue
            width = _HEX_ESCAPE_WIDTHS.get(escape)
            if width is None:
                return None, f"invalid escape '\\{escape}' in a double-quoted string"
            digits = value[index + 1 : index + 1 + width]
            if len(digits) != width or any(c not in string.hexdigits for c in digits):
                return None, f"'\\{escape}' needs exactly {width} hex digits"
            try:
                out.append(chr(int(digits, 16)))
            except (ValueError, OverflowError):
                return None, f"'\\{escape}{digits}' is not a valid code point"
            index += 1 + width
            continue
        out.append(char)
        index += 1
    return None, "unterminated double-quoted string"


def _parse_single_quoted(value: str) -> tuple[str | None, str | None]:
    """Decode a one-line single-quoted YAML scalar: (text, None) or (None, problem)."""
    out: list[str] = []
    index, length = 1, len(value)
    while index < length:
        char = value[index]
        if char == "'":
            if index + 1 < length and value[index + 1] == "'":
                out.append("'")
                index += 2
                continue
            if index != length - 1:
                return None, "unescaped ' inside a single-quoted string (write it as '')"
            return "".join(out), None
        out.append(char)
        index += 1
    return None, "unterminated single-quoted string"


def _plain_scalar_problem(key: str, value: str) -> str | None:
    if not value:
        return None
    if ": " in value or value.endswith(":"):
        return "unquoted ': ' in a plain scalar (invalid YAML; quote the value)"
    if value[0] in "&*!%@`":
        return f"plain scalar cannot start with {value[0]!r}"
    if key in ("name", "description") and value[0] in "[{":
        return f"{key} must be a string, not a YAML collection"
    return None


def _decode_scalar(key: str, value: str) -> tuple[str, str | None]:
    """Return (decoded value, problem). On a problem the raw value is kept."""
    if value[:1] == '"':
        decoded, problem = _parse_double_quoted(value)
    elif value[:1] == "'":
        decoded, problem = _parse_single_quoted(value)
    else:
        return value, _plain_scalar_problem(key, value)
    return (value if decoded is None else decoded), problem


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
                if ": " in continuation or continuation.endswith(":"):
                    problems.append(
                        (
                            lineno,
                            "FRONTMATTER_SYNTAX",
                            "unquoted ': ' in a plain scalar (invalid YAML; quote the value)",
                        )
                    )
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
        decoded, problem = _decode_scalar(key, value)
        if problem:
            problems.append((lineno, "FRONTMATTER_SYNTAX", problem))
        fields[key] = decoded
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


def _is_binary_asset(skill_dir: Path, path: Path) -> bool:
    """Only allowlisted image/PDF/font files under ``assets/`` may be non-UTF-8."""
    parts = path.relative_to(skill_dir).parts
    return (
        len(parts) >= 2
        and parts[0] == "assets"
        and path.suffix.lower() in BINARY_ASSET_SUFFIXES
    )


def _is_provenance_file(skill_dir: Path, path: Path) -> bool:
    """Provenance files are exempt only when they sit in the skill root."""
    return path.parent == skill_dir and path.name in PROVENANCE_FILES


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
        for match in REPO_PREFIXED_PATH_RE.finditer(line):
            follower = line[match.end() : match.end() + 1]
            if follower and follower in PLACEHOLDER_FOLLOWERS:
                continue
            issues.append(
                Issue(
                    rel,
                    lineno,
                    "REFERENCE_NOT_PORTABLE",
                    f"repository-prefixed path {match.group(1)!r} breaks when the skill "
                    "is installed alone; use a skill-relative path such as 'scripts/...'",
                )
            )
        for match in BUNDLED_PATH_RE.finditer(line):
            reference = match.group(1)
            follower = line[match.end() : match.end() + 1]
            if follower and follower in PLACEHOLDER_FOLLOWERS:
                continue
            candidates = (skill_dir / reference, path.parent / reference)
            contained = [c for c in candidates if _is_within(c, skill_dir)]
            # One candidate must be both inside the skill and present: an
            # existing file elsewhere must not satisfy the reference.
            if any(c.exists() for c in contained):
                continue
            if contained:
                issues.append(
                    Issue(
                        rel,
                        lineno,
                        "REFERENCE_BROKEN",
                        f"bundled path {reference!r} does not resolve inside the skill",
                    )
                )
            else:
                issues.append(
                    Issue(
                        rel,
                        lineno,
                        "REFERENCE_ESCAPES_SKILL",
                        f"path {reference!r} leaves the skill",
                    )
                )


def _check_forbidden(
    rel: str, text: str, issues: list[Issue], *, binary: bool = False
) -> None:
    if binary:
        for code, pattern, message in FORBIDDEN_PATTERNS:
            found = pattern.search(text)
            if found:
                issues.append(Issue(rel, None, code, f"{message}: {found.group(0)!r} (in binary)"))
        return
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
        if path.suffix in BYTECODE_SUFFIXES and path.parent.name == BYTECODE_DIR:
            continue
        rel = path.relative_to(root).as_posix()
        try:
            data = path.read_bytes()
        except OSError as error:
            issues.append(Issue(rel, None, "READ_FAILED", str(error)))
            continue
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            if _is_binary_asset(skill_dir, path):
                # Best effort: catch embedded ASCII strings in image metadata.
                if not _is_provenance_file(skill_dir, path):
                    _check_forbidden(rel, data.decode("latin-1"), issues, binary=True)
            else:
                issues.append(
                    Issue(
                        rel,
                        None,
                        "NON_UTF8_FILE",
                        f"not valid UTF-8 ({error.reason} at byte {error.start}); "
                        "only image, PDF and font files under assets/ may be binary",
                    )
                )
            continue
        if path == skill_md:
            _check_frontmatter(skill_dir, rel, text, issues)
        if not _is_provenance_file(skill_dir, path):
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
    try:
        text = readme.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        issues.append(Issue("README.md", None, "README_UNREADABLE", f"cannot read as UTF-8: {error}"))
        return None
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
