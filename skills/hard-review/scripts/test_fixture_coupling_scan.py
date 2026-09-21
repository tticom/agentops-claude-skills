#!/usr/bin/env python3

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import fixture_coupling_scan as fcs
from fixture_coupling_scan import scan


def make(root: Path, production_text: str, fixture_name="sample-6.dat", data=b"fixture-content"):
    fixtures = root / "fixtures"
    fixtures.mkdir(exist_ok=True)
    (fixtures / fixture_name).write_bytes(data)
    production = root / "module.py"
    production.write_text(production_text, encoding="utf-8")
    return production, fixtures


class FixtureCouplingScanTest(unittest.TestCase):
    def test_detects_fixture_name_hash_and_private_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            digest = hashlib.sha256(b"fixture-content").hexdigest()
            production, fixtures = make(
                root,
                "NAME = 'sample-6.dat'\n"
                f"DIGEST = '{digest}'\n"
                "PATH = 'fixtures/private/customer'\n",
            )
            kinds = {finding.kind for finding in scan([production], [fixtures])}
            self.assertEqual(kinds, {"fixture-name", "fixture-sha256", "private-path"})

    def test_generic_domain_code_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            production, fixtures = make(
                Path(directory),
                "def duration_ticks(beats, resolution):\n    return beats * resolution\n",
            )
            self.assertEqual(scan([production], [fixtures]), [])

    def test_windows_separators_and_case_are_normalised(self):
        with tempfile.TemporaryDirectory() as directory:
            production, fixtures = make(
                Path(directory), "PATH = 'C:\\\\Data\\\\Fixtures\\\\Private\\\\file'\n"
            )
            kinds = {finding.kind for finding in scan([production], [fixtures])}
            self.assertEqual(kinds, {"private-path"})

    def test_project_markers_and_patterns_are_supplied_not_built_in(self):
        with tempfile.TemporaryDirectory() as directory:
            production, fixtures = make(
                Path(directory),
                "REPO = 'acme-private-corpus'\nFILE = 'Report-42.pdf'\n",
            )
            self.assertEqual(scan([production], [fixtures]), [])
            findings = scan(
                [production],
                [fixtures],
                markers=["acme-private-corpus"],
                patterns=[r"report[-_ ]?\d+\.pdf"],
            )
            self.assertEqual(
                {(item.kind, item.token.lower()) for item in findings},
                {("private-path", "acme-private-corpus"), ("named-artifact", "report-42.pdf")},
            )

    def test_no_project_specific_identifiers_remain_in_the_script(self):
        source = Path(fcs.__file__).read_text(encoding="utf-8").lower()
        for banned in ("score2gp", "onedrive", "lesson", "guitar"):
            self.assertNotIn(banned, source)

    def test_markers_file_round_trip_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "markers.json"
            path.write_text(json.dumps({"markers": ["a-b"], "patterns": ["x+"]}), encoding="utf-8")
            self.assertEqual(fcs.load_markers_file(path), (["a-b"], ["x+"]))
            for bad in ("{oops", json.dumps([]), json.dumps({"other": []}),
                        json.dumps({"markers": "a"}), json.dumps({"patterns": [""]})):
                path.write_text(bad, encoding="utf-8")
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    fcs.load_markers_file(path)

    def test_errors_are_reported_not_swallowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            production, fixtures = make(root, "x = 1\n")
            with self.assertRaisesRegex(ValueError, "fixture root is not a directory"):
                scan([production], [root / "absent"])
            with self.assertRaisesRegex(ValueError, "production path is not a file"):
                scan([root / "absent.py"], [fixtures])
            with self.assertRaisesRegex(ValueError, "invalid --pattern"):
                scan([production], [fixtures], patterns=["("])

    def test_command_line_fails_on_a_finding_and_passes_when_clean(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            production, fixtures = make(root, "NAME = 'sample-6.dat'\n")
            args = ["--production", str(production), "--fixture-root", str(fixtures)]
            with self.assertRaisesRegex(SystemExit, "FIXTURE_COUPLING_SCAN=FAIL"):
                fcs.main(args)
            production.write_text("x = 1\n", encoding="utf-8")
            fcs.main(args)

    def test_large_fixture_is_hashed_in_chunks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "big.bin"
            data = b"0123456789" * 300_000  # larger than one chunk
            path.write_bytes(data)
            self.assertEqual(fcs.sha256_file(path), hashlib.sha256(data).hexdigest())


if __name__ == "__main__":
    unittest.main()
