"""Fixtures for regression tests."""

import shutil
import tempfile
from pathlib import Path

import pytest

# Project layout
PLUGIN_ROOT = Path(__file__).parent.parent          # plugins/cedolini/
PROJECT_ROOT = PLUGIN_ROOT.parent.parent            # repo root
INPUT_DIR = PROJECT_ROOT / "input"
SNAPSHOT_DIR = Path(__file__).parent / "snapshots"

# CSV files produced by the pipeline
SNAPSHOT_FILES = [
    "cedolini_summary.csv",
    "cedolini_voci.csv",
    "cud_summary.csv",
    "validation_results.csv",
]


def pytest_addoption(parser):
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Regenerate golden snapshot files from current pipeline output",
    )


@pytest.fixture(scope="session")
def project_root():
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def input_dir():
    return INPUT_DIR


@pytest.fixture(scope="session")
def snapshot_dir():
    return SNAPSHOT_DIR


@pytest.fixture(scope="session")
def pipeline_output(request, input_dir):
    """Run extract + validate in a temp directory and return the output path.

    Session-scoped so the pipeline runs only once per test session.
    If --update-snapshots is passed, also copies output to snapshots/.
    """
    import sys
    sys.path.insert(0, str(PLUGIN_ROOT))

    from scripts.extract import extract_all
    from scripts.validate import validate_all

    tmp_dir = Path(tempfile.mkdtemp(prefix="cedolini_test_"))
    out_dir = tmp_dir / "output"
    out_dir.mkdir()

    extract_all(input_dir, out_dir)
    validate_all(input_dir, out_dir)

    # Optionally update snapshots
    if request.config.getoption("--update-snapshots"):
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        for name in SNAPSHOT_FILES:
            src = out_dir / name
            if src.exists():
                shutil.copy2(src, SNAPSHOT_DIR / name)
        print(f"\nSnapshots updated in {SNAPSHOT_DIR}")

    yield out_dir

    # Cleanup
    shutil.rmtree(tmp_dir, ignore_errors=True)
