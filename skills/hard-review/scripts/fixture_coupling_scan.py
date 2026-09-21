#!/usr/bin/env python3
"""Find obvious fixture identities embedded in production source files.

The scanner is lexical and advisory: a finding is a lead, a clean result is not
proof of independence. Project-specific private-path markers and named-artifact
patterns are supplied by the caller (``--marker``, ``--pattern``,
``--markers-file``); only a generic private-fixture path marker is built in.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

# Compared case-insensitively with backslashes normalised to forward slashes.
DEFAULT_MARKERS = ("fixtures/private",)
CHUNK = 1024 * 1024


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    token: str
    kind: str


def _normalize(text: str) -> str:
    # Collapse runs so an escaped Windows path in source ('C:\\Data\\x') still matches.
    return re.sub(r"[\\/]+", "/", text.lower())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fixture_tokens(roots: list[Path]) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for root in roots:
        if not root.is_dir():
            raise ValueError(f"fixture root is not a directory: {root}")
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            name = path.name.lower()
            stem = path.stem.lower()
            if len(name) >= 5:
                tokens[name] = "fixture-name"
            if len(stem) >= 8 and any(character.isdigit() for character in stem):
                tokens[stem] = "fixture-name"
            tokens[sha256_file(path)] = "fixture-sha256"
    return tokens


def load_markers_file(path: Path) -> tuple[list[str], list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read markers file {path}: {error}") from error
    if not isinstance(data, dict) or set(data) - {"markers", "patterns"}:
        raise ValueError("markers file must be an object with only 'markers' and 'patterns'")
    lists = []
    for key in ("markers", "patterns"):
        value = data.get(key, [])
        if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
            raise ValueError(f"markers file '{key}' must be a list of non-empty strings")
        lists.append(value)
    return lists[0], lists[1]


def scan(
    production: list[Path],
    roots: list[Path],
    markers: list[str] | None = None,
    patterns: list[str] | None = None,
) -> list[Finding]:
    tokens = fixture_tokens(roots)
    active_markers = [_normalize(marker) for marker in (*DEFAULT_MARKERS, *(markers or []))]
    try:
        compiled = [re.compile(pattern, re.IGNORECASE) for pattern in (patterns or [])]
    except re.error as error:
        raise ValueError(f"invalid --pattern: {error}") from error
    findings: list[Finding] = []
    for path in production:
        if not path.is_file():
            raise ValueError(f"production path is not a file: {path}")
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line_number, line in enumerate(text.splitlines(), start=1):
            lowered = _normalize(line)
            for marker in active_markers:
                if marker in lowered:
                    findings.append(Finding(path, line_number, marker, "private-path"))
            for token, kind in tokens.items():
                if token in lowered:
                    findings.append(Finding(path, line_number, token, kind))
            for pattern in compiled:
                match = pattern.search(line)
                if match:
                    findings.append(Finding(path, line_number, match.group(0), "named-artifact"))
    return sorted(set(findings), key=lambda item: (str(item.path), item.line, item.kind, item.token))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--production", action="append", required=True, type=Path)
    parser.add_argument("--fixture-root", action="append", required=True, type=Path)
    parser.add_argument("--marker", action="append", default=[], help="literal private-path marker")
    parser.add_argument("--pattern", action="append", default=[], help="regex for named artifacts")
    parser.add_argument("--markers-file", type=Path, help="JSON with 'markers' and 'patterns' lists")
    args = parser.parse_args(argv)
    try:
        markers, patterns = list(args.marker), list(args.pattern)
        if args.markers_file:
            file_markers, file_patterns = load_markers_file(args.markers_file)
            markers += file_markers
            patterns += file_patterns
        findings = scan(args.production, args.fixture_root, markers, patterns)
    except (OSError, ValueError) as error:
        raise SystemExit(f"FIXTURE_COUPLING_SCAN=ERROR: {error}") from error
    if findings:
        rendered = "\n".join(
            f"{item.path}:{item.line}: {item.kind}: {item.token}" for item in findings
        )
        raise SystemExit(f"FIXTURE_COUPLING_SCAN=FAIL\n{rendered}")
    print("FIXTURE_COUPLING_SCAN=PASS")


if __name__ == "__main__":
    main()
