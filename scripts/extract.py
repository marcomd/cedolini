"""Fase 1: Estrazione dati dai PDF e scrittura CSV."""

import argparse
import csv
import os
import sys
from pathlib import Path
from decimal import Decimal

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.models import Cedolino, CertificazioneUnica, ZERO
from scripts.parsers import detect_format, parse_pdf

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
INPUT_DIR = PROJECT_ROOT / "input"


def find_pdfs(input_dir: Path | None = None) -> list[Path]:
    """Find all PDF files in input_dir root and subdirectories.

    Scans both the root directory and subdirectories (e.g. 2023/, 2024/, CUD/).
    """
    base = input_dir or INPUT_DIR
    pdfs = []
    if not base.exists():
        return pdfs
    # Scan root directory for PDFs
    for f in sorted(base.iterdir()):
        if f.is_file() and f.suffix.lower() == ".pdf":
            pdfs.append(f)
    # Scan subdirectories
    for sub in sorted(base.iterdir()):
        if not sub.is_dir():
            continue
        for f in sorted(sub.iterdir()):
            if f.suffix.lower() == ".pdf":
                pdfs.append(f)
    return pdfs


def extract_all(input_dir: Path | None = None, output_dir: Path | None = None):
    """Extract data from all PDFs and write CSVs."""
    in_dir = input_dir or INPUT_DIR
    out_dir = output_dir or OUTPUT_DIR
    out_dir.mkdir(exist_ok=True)

    pdfs = find_pdfs(in_dir)
    print(f"Found {len(pdfs)} PDF files")

    cedolini: list[Cedolino] = []
    cuds: list[CertificazioneUnica] = []
    errors: list[tuple[str, str]] = []

    for pdf_path in pdfs:
        rel_path = pdf_path.relative_to(in_dir)
        fmt = detect_format(str(pdf_path))
        print(f"  {rel_path}: {fmt}")

        try:
            result = parse_pdf(str(pdf_path))
            if isinstance(result, list):
                cedolini.extend(result)
            elif isinstance(result, Cedolino):
                cedolini.append(result)
            elif isinstance(result, CertificazioneUnica):
                cuds.append(result)
            elif result is None:
                errors.append((str(rel_path), "Unknown format"))
        except Exception as e:
            print(f"    ERROR: {e}")
            errors.append((str(rel_path), str(e)))

    # Sort cedolini by year/month
    cedolini.sort(key=lambda c: (c.anno, c.mese))

    print(f"\nParsed: {len(cedolini)} cedolini, {len(cuds)} CUDs, {len(errors)} errors")

    # Write CSVs
    _write_summary_csv(cedolini, in_dir, out_dir)
    _write_voci_csv(cedolini, out_dir)
    _write_cud_csv(cuds, in_dir, out_dir)

    if errors:
        print("\nErrors:")
        for path, err in errors:
            print(f"  {path}: {err}")


def _fmt(val: Decimal) -> str:
    """Format decimal for CSV."""
    if val == ZERO:
        return ""
    return str(val)


def _write_summary_csv(cedolini: list[Cedolino], input_dir: Path = INPUT_DIR, output_dir: Path = OUTPUT_DIR):
    """Write cedolini_summary.csv with dynamic contribution columns."""
    path = output_dir / "cedolini_summary.csv"

    # Collect all contribution types across all cedolini
    all_contrib_types = []
    seen = set()
    for c in cedolini:
        for ct in c.contributi:
            if ct.descrizione not in seen:
                seen.add(ct.descrizione)
                all_contrib_types.append(ct.descrizione)

    # Build dynamic contribution fields
    contrib_fields = []
    for ct_name in all_contrib_types:
        contrib_fields.extend([f"{ct_name}_imp", f"{ct_name}_pct", f"{ct_name}_dip"])

    fields = [
        "file", "formato", "ccnl", "anno", "mese", "mese_retribuzione", "is_tredicesima",
        "paga_base", "contingenza", "superminimo", "terzo_elemento", "edr", "scatti",
        "retribuzione_mensile",
        # INPS
        "settimane", "gg_retribuiti", "gg_lavorati", "ore_lavorate",
        "imp_contrib_mese", "imp_contrib_arrot", "totale_contributi",
        "imp_contrib_anno", "contributi_anno",
    ] + contrib_fields + [
        # IRPEF
        "imp_fiscale_mese", "irpef_lorda_mese", "detr_lav_dip", "gg_detrazione",
        "irpef_netta_mese", "irpef_piu_imp_sost",
        "imp_fiscale_anno", "irpef_lorda_anno", "irpef_netta_anno",
        "irpef_trattenuta_anno", "irpef_conguaglio",
        # Addizionali
        "addizionale_regionale", "addizionale_comunale_saldo", "addizionale_comunale_acconto",
        # TFR
        "retrib_utile_tfr", "contr_agg_tfr", "tfr_mese", "tfr_annuo",
        "fondo_tfr_31_12_ap",
        # Totali
        "totale_competenze", "totale_trattenute",
        "arr_precedente", "arr_attuale", "arrotondamento",
        "netto_in_busta",
        # Progressivi
        "progr_imp_inps", "progr_imp_irpef", "progr_irpef_pagata",
    ]

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for c in cedolini:
            contrib_map = {ct.descrizione: ct for ct in c.contributi}

            row = {
                "file": Path(c.file_path).relative_to(input_dir),
                "formato": c.formato,
                "ccnl": c.ccnl,
                "anno": c.anno,
                "mese": c.mese,
                "mese_retribuzione": c.mese_retribuzione,
                "is_tredicesima": c.is_tredicesima,
                "paga_base": _fmt(c.paga_base),
                "contingenza": _fmt(c.contingenza),
                "superminimo": _fmt(c.superminimo),
                "terzo_elemento": _fmt(c.terzo_elemento),
                "edr": _fmt(c.edr),
                "scatti": _fmt(c.scatti),
                "retribuzione_mensile": _fmt(c.retribuzione_mensile),
                # INPS
                "settimane": c.inps.settimane or "",
                "gg_retribuiti": c.inps.gg_retribuiti or "",
                "gg_lavorati": c.inps.gg_lavorati or "",
                "ore_lavorate": _fmt(c.inps.ore_lavorate),
                "imp_contrib_mese": _fmt(c.inps.imponibile_contributivo_mese),
                "imp_contrib_arrot": _fmt(c.inps.imponibile_contrib_arrot_mese),
                "totale_contributi": _fmt(c.inps.totale_contributi),
                "imp_contrib_anno": _fmt(c.inps.imponibile_contributivo_anno),
                "contributi_anno": _fmt(c.inps.contributi_anno),
                # IRPEF
                "imp_fiscale_mese": _fmt(c.irpef.imponibile_fiscale_mese),
                "irpef_lorda_mese": _fmt(c.irpef.irpef_lorda_mese),
                "detr_lav_dip": _fmt(c.irpef.detrazione_lavoro_dip),
                "gg_detrazione": c.irpef.gg_detrazione or "",
                "irpef_netta_mese": _fmt(c.irpef.irpef_netta_mese),
                "irpef_piu_imp_sost": _fmt(c.irpef.irpef_piu_imp_sost),
                "imp_fiscale_anno": _fmt(c.irpef.imponibile_fiscale_anno),
                "irpef_lorda_anno": _fmt(c.irpef.irpef_lorda_anno),
                "irpef_netta_anno": _fmt(c.irpef.irpef_netta_anno),
                "irpef_trattenuta_anno": _fmt(c.irpef.irpef_trattenuta_anno),
                "irpef_conguaglio": _fmt(c.irpef.irpef_conguaglio),
                # Addizionali
                "addizionale_regionale": _fmt(c.addizionale_regionale),
                "addizionale_comunale_saldo": _fmt(c.addizionale_comunale_saldo),
                "addizionale_comunale_acconto": _fmt(c.addizionale_comunale_acconto),
                # TFR
                "retrib_utile_tfr": _fmt(c.tfr.retribuzione_utile_tfr),
                "contr_agg_tfr": _fmt(c.tfr.contributo_agg_tfr),
                "tfr_mese": _fmt(c.tfr.tfr_mese),
                "tfr_annuo": _fmt(c.tfr.tfr_annuo),
                "fondo_tfr_31_12_ap": _fmt(c.tfr.fondo_tfr_31_12_ap),
                # Totali
                "totale_competenze": _fmt(c.totali.totale_competenze),
                "totale_trattenute": _fmt(c.totali.totale_trattenute),
                "arr_precedente": _fmt(c.totali.arrotondamento_precedente),
                "arr_attuale": _fmt(c.totali.arrotondamento_attuale),
                "arrotondamento": _fmt(c.totali.arrotondamento),
                "netto_in_busta": _fmt(c.totali.netto_in_busta),
                # Progressivi
                "progr_imp_inps": _fmt(c.progressivo_imp_inps),
                "progr_imp_irpef": _fmt(c.progressivo_imp_irpef),
                "progr_irpef_pagata": _fmt(c.progressivo_irpef_pagata),
            }

            # Add dynamic contribution details
            for ct_name in all_contrib_types:
                ct = contrib_map.get(ct_name)
                if ct:
                    row[f"{ct_name}_imp"] = _fmt(ct.imponibile)
                    row[f"{ct_name}_pct"] = _fmt(ct.percentuale)
                    row[f"{ct_name}_dip"] = _fmt(ct.importo_dipendente)

            writer.writerow(row)

    print(f"  Written: {path}")


def _write_voci_csv(cedolini: list[Cedolino], output_dir: Path = OUTPUT_DIR):
    """Write cedolini_voci.csv."""
    path = output_dir / "cedolini_voci.csv"
    fields = [
        "anno", "mese", "formato", "codice", "descrizione",
        "unita_misura", "quantita", "base", "competenze", "trattenute",
        "flag_c", "flag_i", "flag_t", "flag_n",
    ]

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for c in cedolini:
            for v in c.voci:
                writer.writerow({
                    "anno": c.anno,
                    "mese": c.mese,
                    "formato": c.formato,
                    "codice": v.codice,
                    "descrizione": v.descrizione,
                    "unita_misura": v.unita_misura,
                    "quantita": _fmt(v.quantita),
                    "base": _fmt(v.base),
                    "competenze": _fmt(v.competenze),
                    "trattenute": _fmt(v.trattenute),
                    "flag_c": v.flag_c,
                    "flag_i": v.flag_i,
                    "flag_t": v.flag_t,
                    "flag_n": v.flag_n,
                })

    print(f"  Written: {path}")


def _write_cud_csv(cuds: list[CertificazioneUnica], input_dir: Path = INPUT_DIR, output_dir: Path = OUTPUT_DIR):
    """Write cud_summary.csv."""
    path = output_dir / "cud_summary.csv"
    fields = [
        "file", "anno_riferimento", "anno_cu",
        "reddito_lavoro_dipendente", "giorni_lavoro_dipendente",
        "ritenute_irpef", "addizionale_regionale",
        "acconto_add_comunale", "saldo_add_comunale", "acconto_add_comunale_succ",
        "previdenza_complementare",
        "matricola_inps", "imponibile_previdenziale", "contributi_lavoratore",
    ]

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for cu in cuds:
            writer.writerow({
                "file": Path(cu.file_path).relative_to(input_dir),
                "anno_riferimento": cu.anno_riferimento,
                "anno_cu": cu.anno_cu,
                "reddito_lavoro_dipendente": _fmt(cu.reddito_lavoro_dipendente),
                "giorni_lavoro_dipendente": cu.giorni_lavoro_dipendente or "",
                "ritenute_irpef": _fmt(cu.ritenute_irpef),
                "addizionale_regionale": _fmt(cu.addizionale_regionale),
                "acconto_add_comunale": _fmt(cu.acconto_add_comunale),
                "saldo_add_comunale": _fmt(cu.saldo_add_comunale),
                "acconto_add_comunale_succ": _fmt(cu.acconto_add_comunale_succ),
                "previdenza_complementare": _fmt(cu.previdenza_complementare),
                "matricola_inps": cu.matricola_inps,
                "imponibile_previdenziale": _fmt(cu.imponibile_previdenziale),
                "contributi_lavoratore": _fmt(cu.contributi_lavoratore),
            })

    print(f"  Written: {path}")


def parse_args():
    parser = argparse.ArgumentParser(description="VerificaCedolino - Estrazione dati da cedolini PDF")
    parser.add_argument("--input-dir", type=Path, default=INPUT_DIR, help="Cartella con sottodirectory anno contenenti PDF")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="Cartella output per CSV e report")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    extract_all(args.input_dir, args.output_dir)
