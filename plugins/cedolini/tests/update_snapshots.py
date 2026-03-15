#!/usr/bin/env python3
"""Regenerate golden snapshot CSVs from the current pipeline output.

Usage:
    python3 plugins/cedolini/tests/update_snapshots.py
"""

import csv
import shutil
import sys
import tempfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).parent.parent
PROJECT_ROOT = PLUGIN_ROOT.parent.parent
INPUT_DIR = PROJECT_ROOT / "input"
SNAPSHOT_DIR = Path(__file__).parent / "snapshots"

SNAPSHOT_FILES = [
    "cedolini_summary.csv",
    "cedolini_voci.csv",
    "cud_summary.csv",
    "validation_results.csv",
]

sys.path.insert(0, str(PLUGIN_ROOT))


def count_rows(path: Path) -> int:
    """Count data rows in a CSV file."""
    if not path.exists():
        return 0
    with open(path) as f:
        return sum(1 for _ in csv.reader(f)) - 1  # subtract header


def main():
    from scripts.extract import extract_all
    from scripts.validate import validate_all

    tmp_dir = Path(tempfile.mkdtemp(prefix="cedolini_snap_"))
    out_dir = tmp_dir / "output"
    out_dir.mkdir()

    print("Running pipeline...")
    extract_all(INPUT_DIR, out_dir)
    validate_all(INPUT_DIR, out_dir)

    print(f"\nUpdating snapshots in {SNAPSHOT_DIR}")
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    for name in SNAPSHOT_FILES:
        src = out_dir / name
        dst = SNAPSHOT_DIR / name
        if not src.exists():
            print(f"  SKIP {name} (not produced)")
            continue

        old_rows = count_rows(dst)
        new_rows = count_rows(src)
        shutil.copy2(src, dst)
        delta = new_rows - old_rows
        sign = "+" if delta > 0 else ""
        print(f"  {name}: {new_rows} rows ({sign}{delta})" if old_rows else f"  {name}: {new_rows} rows (new)")

    shutil.rmtree(tmp_dir, ignore_errors=True)
    print("\nDone. Review changes with: git diff plugins/cedolini/tests/snapshots/")


if __name__ == "__main__":
    main()
