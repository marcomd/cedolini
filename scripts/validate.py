"""Fase 2: Validazione calcoli cedolini."""

import argparse
import csv
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.models import Cedolino, CertificazioneUnica, ValidationResult
from scripts.parsers import parse_pdf
from scripts.extract import find_pdfs, INPUT_DIR, OUTPUT_DIR
from scripts.ccnl import load_all_ccnl, detect_ccnl
from scripts.validators.net_pay import validate_net_pay
from scripts.validators.inps import validate_inps
from scripts.validators.irpef import validate_irpef, validate_irpef_annual
from scripts.validators.tfr import validate_tfr, validate_tfr_annual
from scripts.validators.ratei import validate_ratei
from scripts.validators.cud import validate_cud


def validate_all(input_dir: Path | None = None, output_dir: Path | None = None):
    """Run all validators and write results."""
    in_dir = input_dir or INPUT_DIR
    out_dir = output_dir or OUTPUT_DIR
    out_dir.mkdir(exist_ok=True)

    # Parse all PDFs
    print("Parsing PDFs...")
    pdfs = find_pdfs(in_dir)
    cedolini: list[Cedolino] = []
    cuds: list[CertificazioneUnica] = []

    for pdf_path in pdfs:
        try:
            result = parse_pdf(str(pdf_path))
            if isinstance(result, list):
                cedolini.extend(result)
            elif isinstance(result, Cedolino):
                cedolini.append(result)
            elif isinstance(result, CertificazioneUnica):
                cuds.append(result)
        except Exception as e:
            print(f"  ERROR parsing {pdf_path}: {e}")

    cedolini.sort(key=lambda c: (c.anno, c.mese))
    print(f"Parsed: {len(cedolini)} cedolini, {len(cuds)} CUDs")

    # Detect CCNL for each cedolino
    ccnl_configs = load_all_ccnl()
    for ced in cedolini:
        if not ced.ccnl:
            detected = detect_ccnl(ced, ccnl_configs)
            if detected:
                ced.ccnl = detected.id
    ccnl_summary = {}
    for ced in cedolini:
        ccnl_summary[ced.ccnl or "(non rilevato)"] = ccnl_summary.get(ced.ccnl or "(non rilevato)", 0) + 1
    for ccnl_id, count in ccnl_summary.items():
        print(f"  CCNL: {ccnl_id} ({count} cedolini)")

    # Run validators
    print("\nRunning validators...")
    all_results: list[ValidationResult] = []

    validators = [
        ("Netto in busta", lambda: validate_net_pay(cedolini)),
        ("Contributi INPS", lambda: validate_inps(cedolini, ccnl_configs)),
        ("IRPEF mensile", lambda: validate_irpef(cedolini)),
        ("IRPEF annuale", lambda: validate_irpef_annual(cedolini)),
        ("TFR mensile", lambda: validate_tfr(cedolini)),
        ("TFR annuale", lambda: validate_tfr_annual(cedolini)),
        ("Ratei", lambda: validate_ratei(cedolini)),
        ("Cross-check CUD", lambda: validate_cud(cedolini, cuds)),
    ]

    for name, validator in validators:
        try:
            results = validator()
            all_results.extend(results)
            passed = sum(1 for r in results if r.status == "PASS")
            failed = sum(1 for r in results if r.status == "FAIL")
            warnings = sum(1 for r in results if r.status == "WARNING")
            info = sum(1 for r in results if r.status == "INFO")
            print(f"  {name}: {passed} PASS, {failed} FAIL, {warnings} WARNING, {info} INFO")
        except Exception as e:
            print(f"  ERROR in {name}: {e}")
            import traceback
            traceback.print_exc()

    # Write results CSV
    _write_results_csv(all_results, out_dir)

    # Print summary
    total_pass = sum(1 for r in all_results if r.status == "PASS")
    total_fail = sum(1 for r in all_results if r.status == "FAIL")
    total_warn = sum(1 for r in all_results if r.status == "WARNING")

    print(f"\n{'='*60}")
    print(f"TOTALE: {total_pass} PASS, {total_fail} FAIL, {total_warn} WARNING")
    print(f"{'='*60}")

    if total_fail > 0:
        print("\nFAIL details:")
        for r in all_results:
            if r.status == "FAIL":
                print(f"  [{r.anno}/{r.mese}] {r.nome}: atteso={r.atteso} effettivo={r.effettivo} diff={r.differenza}")


def _write_results_csv(results: list[ValidationResult], output_dir: Path = OUTPUT_DIR):
    """Write validation_results.csv."""
    path = output_dir / "validation_results.csv"
    fields = [
        "nome", "anno", "mese", "mese_label", "status",
        "atteso", "effettivo", "differenza", "tolleranza", "formula", "note",
    ]

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in results:
            writer.writerow({
                "nome": r.nome,
                "anno": r.anno,
                "mese": r.mese,
                "mese_label": r.mese_label,
                "status": r.status,
                "atteso": r.atteso,
                "effettivo": r.effettivo,
                "differenza": r.differenza,
                "tolleranza": r.tolleranza,
                "formula": r.formula,
                "note": r.note,
            })

    print(f"  Written: {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VerificaCedolino - Validazione calcoli cedolini")
    parser.add_argument("--input-dir", type=Path, default=INPUT_DIR, help="Cartella con sottodirectory anno contenenti PDF")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="Cartella output per CSV e report")
    args = parser.parse_args()
    validate_all(args.input_dir, args.output_dir)
