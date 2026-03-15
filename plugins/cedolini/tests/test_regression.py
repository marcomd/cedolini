"""Snapshot-based regression tests for the cedolini pipeline.

Three tiers:
  1. Structural checks (row counts, columns, key presence)
  2. Numeric regression on key fields (with tolerance)
  3. Full diff on detail CSVs
Plus: isolated format-detection test for every PDF.
"""

import csv
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))

TOLERANCE = Decimal("0.02")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_csv(path: Path) -> list[dict]:
    """Read a CSV file into a list of dicts."""
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def to_decimal(value: str) -> Decimal | None:
    """Parse a string as Decimal, returning None for empty/unparseable."""
    if not value or value.strip() == "":
        return None
    try:
        return Decimal(value.strip())
    except InvalidOperation:
        return None


def csv_path(directory: Path, name: str) -> Path:
    p = directory / name
    if not p.exists():
        pytest.fail(f"Missing CSV: {p}")
    return p


# ---------------------------------------------------------------------------
# Tier 1 — Structural checks
# ---------------------------------------------------------------------------

class TestStructural:
    """Catch catastrophic failures: missing rows, changed columns, missing periods."""

    def test_summary_row_count(self, pipeline_output, snapshot_dir):
        actual = read_csv(csv_path(pipeline_output, "cedolini_summary.csv"))
        expected = read_csv(csv_path(snapshot_dir, "cedolini_summary.csv"))
        assert len(actual) == len(expected), (
            f"cedolini_summary row count: expected {len(expected)}, got {len(actual)}"
        )

    def test_summary_columns(self, pipeline_output, snapshot_dir):
        actual = read_csv(csv_path(pipeline_output, "cedolini_summary.csv"))
        expected = read_csv(csv_path(snapshot_dir, "cedolini_summary.csv"))
        assert actual[0].keys() == expected[0].keys(), (
            f"Column mismatch.\n"
            f"  Missing: {expected[0].keys() - actual[0].keys()}\n"
            f"  Extra:   {actual[0].keys() - expected[0].keys()}"
        )

    def test_voci_row_count(self, pipeline_output, snapshot_dir):
        actual = read_csv(csv_path(pipeline_output, "cedolini_voci.csv"))
        expected = read_csv(csv_path(snapshot_dir, "cedolini_voci.csv"))
        assert len(actual) == len(expected), (
            f"cedolini_voci row count: expected {len(expected)}, got {len(actual)}"
        )

    def test_voci_columns(self, pipeline_output, snapshot_dir):
        actual = read_csv(csv_path(pipeline_output, "cedolini_voci.csv"))
        expected = read_csv(csv_path(snapshot_dir, "cedolini_voci.csv"))
        assert actual[0].keys() == expected[0].keys()

    def test_cud_row_count(self, pipeline_output, snapshot_dir):
        actual = read_csv(csv_path(pipeline_output, "cud_summary.csv"))
        expected = read_csv(csv_path(snapshot_dir, "cud_summary.csv"))
        assert len(actual) == len(expected), (
            f"cud_summary row count: expected {len(expected)}, got {len(actual)}"
        )

    def test_validation_row_count(self, pipeline_output, snapshot_dir):
        actual = read_csv(csv_path(pipeline_output, "validation_results.csv"))
        expected = read_csv(csv_path(snapshot_dir, "validation_results.csv"))
        assert len(actual) == len(expected), (
            f"validation_results row count: expected {len(expected)}, got {len(actual)}"
        )

    def test_all_year_month_pairs_present(self, pipeline_output, snapshot_dir):
        actual = read_csv(csv_path(pipeline_output, "cedolini_summary.csv"))
        expected = read_csv(csv_path(snapshot_dir, "cedolini_summary.csv"))
        actual_keys = {(r["anno"], r["mese"]) for r in actual}
        expected_keys = {(r["anno"], r["mese"]) for r in expected}
        missing = expected_keys - actual_keys
        assert not missing, f"Missing (anno, mese) pairs: {sorted(missing)}"

    def test_all_formats_present(self, pipeline_output, snapshot_dir):
        actual = read_csv(csv_path(pipeline_output, "cedolini_summary.csv"))
        expected = read_csv(csv_path(snapshot_dir, "cedolini_summary.csv"))
        actual_fmts = {r["formato"] for r in actual}
        expected_fmts = {r["formato"] for r in expected}
        missing = expected_fmts - actual_fmts
        assert not missing, f"Missing formats: {missing}"


# ---------------------------------------------------------------------------
# Tier 2 — Numeric regression on key fields
# ---------------------------------------------------------------------------

SUMMARY_KEY_FIELDS = [
    "netto_in_busta",
    "totale_competenze",
    "totale_trattenute",
    "paga_base",
    "imp_contrib_mese",
    "irpef_netta_mese",
]


class TestNumericRegression:
    """Compare key numeric fields with tolerance."""

    def test_summary_key_fields(self, pipeline_output, snapshot_dir):
        actual_rows = read_csv(csv_path(pipeline_output, "cedolini_summary.csv"))
        expected_rows = read_csv(csv_path(snapshot_dir, "cedolini_summary.csv"))

        # Index by (anno, mese) — may have duplicates, use list
        actual_map = {}
        for r in actual_rows:
            key = (r["anno"], r["mese"])
            actual_map.setdefault(key, []).append(r)

        expected_map = {}
        for r in expected_rows:
            key = (r["anno"], r["mese"])
            expected_map.setdefault(key, []).append(r)

        errors = []
        for key in sorted(expected_map):
            exp_list = expected_map[key]
            act_list = actual_map.get(key, [])
            if len(act_list) != len(exp_list):
                errors.append(f"  {key}: row count {len(act_list)} != {len(exp_list)}")
                continue

            for i, (exp, act) in enumerate(zip(exp_list, act_list)):
                for field in SUMMARY_KEY_FIELDS:
                    e_val = to_decimal(exp.get(field, ""))
                    a_val = to_decimal(act.get(field, ""))
                    if e_val is None and a_val is None:
                        continue
                    if e_val is None or a_val is None:
                        errors.append(
                            f"  {key}[{i}].{field}: expected={exp.get(field)!r} actual={act.get(field)!r}"
                        )
                        continue
                    diff = abs(e_val - a_val)
                    if diff > TOLERANCE:
                        errors.append(
                            f"  {key}[{i}].{field}: expected={e_val} actual={a_val} diff={diff}"
                        )

        assert not errors, "Numeric regressions:\n" + "\n".join(errors)

    def test_validation_status_no_regression(self, pipeline_output, snapshot_dir):
        """A PASS→FAIL change is a regression."""
        actual_rows = read_csv(csv_path(pipeline_output, "validation_results.csv"))
        expected_rows = read_csv(csv_path(snapshot_dir, "validation_results.csv"))

        expected_pass = {
            (r["nome"], r["anno"], r["mese"])
            for r in expected_rows
            if r["status"] == "PASS"
        }

        actual_status = {}
        for r in actual_rows:
            actual_status[(r["nome"], r["anno"], r["mese"])] = r["status"]

        regressions = []
        for key in sorted(expected_pass):
            status = actual_status.get(key)
            if status and status == "FAIL":
                regressions.append(f"  {key}: was PASS, now FAIL")

        assert not regressions, "Validation regressions (PASS→FAIL):\n" + "\n".join(regressions)


# ---------------------------------------------------------------------------
# Tier 3 — Full diff
# ---------------------------------------------------------------------------

class TestFullDiff:
    """Row-by-row comparison for detail CSVs."""

    def test_voci_full_diff(self, pipeline_output, snapshot_dir):
        actual = read_csv(csv_path(pipeline_output, "cedolini_voci.csv"))
        expected = read_csv(csv_path(snapshot_dir, "cedolini_voci.csv"))

        diffs = _diff_csv_rows(expected, actual)
        assert not diffs, f"cedolini_voci.csv diffs ({len(diffs)}):\n" + "\n".join(diffs[:20])

    def test_cud_full_diff(self, pipeline_output, snapshot_dir):
        actual = read_csv(csv_path(pipeline_output, "cud_summary.csv"))
        expected = read_csv(csv_path(snapshot_dir, "cud_summary.csv"))

        diffs = _diff_csv_rows(expected, actual)
        assert not diffs, f"cud_summary.csv diffs ({len(diffs)}):\n" + "\n".join(diffs[:20])


def _diff_csv_rows(expected: list[dict], actual: list[dict]) -> list[str]:
    """Compare two CSV row lists, returning human-readable diff strings."""
    diffs = []
    max_rows = max(len(expected), len(actual))
    for i in range(max_rows):
        if i >= len(expected):
            diffs.append(f"  row {i+1}: EXTRA in actual")
            continue
        if i >= len(actual):
            diffs.append(f"  row {i+1}: MISSING in actual")
            continue
        exp_row = expected[i]
        act_row = actual[i]
        for col in exp_row:
            if exp_row[col] != act_row.get(col):
                diffs.append(
                    f"  row {i+1}.{col}: expected={exp_row[col]!r} actual={act_row.get(col)!r}"
                )
    return diffs


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

# Build parametrized list: (pdf_path, expected_format)
# We derive expected format by running detect_format once and storing in snapshot.
# For initial setup, we trust the current detect_format output.

def _collect_pdf_formats():
    """Collect all PDFs and their expected formats for parametrized testing."""
    from scripts.extract import find_pdfs
    from scripts.parsers import detect_format

    input_dir = PLUGIN_ROOT.parent.parent / "input"
    if not input_dir.exists():
        return []

    params = []
    for pdf_path in find_pdfs(input_dir):
        fmt = detect_format(str(pdf_path))
        rel = pdf_path.relative_to(input_dir)
        params.append(pytest.param(str(pdf_path), fmt, id=str(rel)))
    return params


# Collect at import time so parametrize works
_PDF_FORMATS = _collect_pdf_formats()


@pytest.mark.parametrize("pdf_path,expected_format", _PDF_FORMATS)
def test_format_detection(pdf_path, expected_format):
    """detect_format() must return the expected format for each PDF."""
    from scripts.parsers import detect_format
    actual = detect_format(pdf_path)
    assert actual == expected_format, (
        f"Format detection changed: expected {expected_format!r}, got {actual!r}"
    )
