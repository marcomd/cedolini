"""Parser base: registry-based format detection and dispatch."""

import pdfplumber
from pathlib import Path
from scripts.models import Cedolino, CertificazioneUnica

# Registry: list of (name, detector_fn, parser_fn)
# detector_fn(pdf_path: str, full_text: str) -> bool
# parser_fn(pdf_path: str) -> Cedolino | CertificazioneUnica | list[Cedolino] | None
_REGISTRY: list[tuple[str, callable, callable]] = []


def register_parser(name: str, detector, parser):
    """Register a parser with its detector function."""
    _REGISTRY.append((name, detector, parser))


def detect_format(pdf_path: str) -> str:
    """Detect PDF format from content using registered detectors.

    Returns the name of the first matching parser, or 'unknown'.
    """
    path = Path(pdf_path)
    name_lower = path.stem.lower()

    # Build full_text once for all detectors
    full_text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                full_text += text + "\n"
    except Exception:
        return "unknown"

    for parser_name, detector, _ in _REGISTRY:
        try:
            if detector(pdf_path, full_text):
                return parser_name
        except Exception:
            continue

    return "unknown"


def parse_pdf(pdf_path: str) -> Cedolino | CertificazioneUnica | list[Cedolino] | None:
    """Parse a PDF file, auto-detecting its format."""
    path = Path(pdf_path)

    # Build full_text once
    full_text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                full_text += text + "\n"
    except Exception:
        print(f"  WARNING: Cannot open {pdf_path}")
        return None

    # Find matching parser
    for parser_name, detector, parser_fn in _REGISTRY:
        try:
            if detector(pdf_path, full_text):
                return parser_fn(pdf_path)
        except Exception:
            continue

    print(f"  WARNING: Unknown format for {pdf_path}")
    return None
