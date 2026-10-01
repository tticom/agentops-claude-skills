#!/usr/bin/env python3
"""Report assertion shapes that deserve semantic review.

This is intentionally advisory. It finds syntax patterns correlated with
false-success tests; it does not decide whether an assertion is correct.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import sys


def _render(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return node.__class__.__name__


def _find_smells(path: Path) -> list[tuple[int, str, str]]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        return [(0, "scan-error", str(exc))]

    findings: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue

        test = node.test
        rendered = _render(test)

        if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
            findings.append(
                (
                    node.lineno,
                    "disjunctive-assertion",
                    f"Confirm every accepted branch is semantically equivalent: {rendered}",
                )
            )

        if isinstance(test, (ast.Name, ast.Attribute, ast.Subscript, ast.Call)):
            findings.append(
                (
                    node.lineno,
                    "truthiness-only",
                    f"Confirm truthiness proves the claimed behavior: {rendered}",
                )
            )

        if (
            isinstance(test, ast.Compare)
            and len(test.ops) == 1
            and isinstance(test.ops[0], (ast.Is, ast.IsNot))
            and any(isinstance(item, ast.Constant) and item.value is None for item in [test.left, *test.comparators])
        ):
            findings.append(
                (
                    node.lineno,
                    "none-only",
                    f"Confirm presence/absence is sufficient for the semantic claim: {rendered}",
                )
            )

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report assertion syntax that requires semantic falsification review."
    )
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()

    count = 0
    for path in args.paths:
        for line, category, message in _find_smells(path):
            count += 1
            print(f"{path}:{line}: {category}: {message}")

    print(f"assertion-smell candidates: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
