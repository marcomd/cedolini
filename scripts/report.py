"""Fase 3: Generazione report Markdown dai risultati di validazione."""

import argparse
import csv
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.models import Cedolino, CertificazioneUnica, ValidationResult, ZERO
from scripts.parsers import parse_pdf
from scripts.extract import find_pdfs, INPUT_DIR, OUTPUT_DIR
from scripts.explain import (
    get_disclaimer,
    get_intro,
    get_section_explanation,
    build_gross_to_net,
    build_gross_to_net_yearly,
    get_relevant_glossary,
    get_validation_note,
)

# Module-level flags, set from CLI args in main()
_explain = True
_monthly_explain = True


def _load_data(input_dir: Path = INPUT_DIR):
    """Parse all PDFs and return cedolini + cuds."""
    pdfs = find_pdfs(input_dir)
    cedolini = []
    cuds = []
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
    return cedolini, cuds


def _load_validation_results(output_dir: Path = OUTPUT_DIR):
    """Load validation results from CSV."""
    path = output_dir / "validation_results.csv"
    results = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            results.append(row)
    return results


def _fmt(val) -> str:
    """Format a Decimal or number for display."""
    if isinstance(val, Decimal):
        if val == ZERO:
            return "-"
        return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if isinstance(val, (int, float)):
        if val == 0:
            return "-"
        return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return str(val) if val else "-"


def _fmt_signed(val: Decimal) -> str:
    """Format a Decimal with explicit +/- sign."""
    if val == ZERO:
        return "-"
    s = f"{abs(val):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"+{s}" if val > ZERO else f"-{s}"


def _blockquote(text: str) -> str:
    """Wrap text in Markdown blockquote."""
    if not text:
        return ""
    return "\n".join(f"> {line}" for line in text.splitlines()) + "\n"


def _gross_to_net_table(rows: list[tuple[str, Decimal, str]]) -> str:
    """Format gross-to-net breakdown as a Markdown table."""
    lines = []
    lines.append("| Voce | Importo | Tipo |")
    lines.append("|------|---------|------|")
    for label, amount, explanation in rows:
        lines.append(f"| {label} | {_fmt_signed(amount)} | {explanation} |")
    lines.append("")
    return "\n".join(lines)


def _glossary_section(cedolini: list[Cedolino]) -> str:
    """Format filtered glossary as a Markdown table."""
    glossary = get_relevant_glossary(cedolini)
    if not glossary:
        return ""
    lines = []
    lines.append("## Glossario\n")
    lines.append("| Termine | Significato |")
    lines.append("|---------|-------------|")
    for term, meaning in glossary.items():
        lines.append(f"| {term} | {meaning} |")
    lines.append("")
    return "\n".join(lines)


def generate_report(input_dir: Path | None = None, output_dir: Path | None = None):
    """Generate Markdown reports."""
    in_dir = input_dir or INPUT_DIR
    out_dir = output_dir or OUTPUT_DIR
    out_dir.mkdir(exist_ok=True)

    print("Loading data...")
    cedolini, cuds = _load_data(in_dir)
    results = _load_validation_results(out_dir)

    print(f"Loaded: {len(cedolini)} cedolini, {len(cuds)} CUDs, {len(results)} validation results")

    # Group cedolini by year
    by_year: dict[int, list[Cedolino]] = defaultdict(list)
    for c in cedolini:
        by_year[c.anno].append(c)

    # Generate per-year reports
    for anno in sorted(by_year.keys()):
        ceds = sorted(by_year[anno], key=lambda c: c.mese)
        year_results = [r for r in results if int(r["anno"]) == anno]
        report = _generate_year_report(anno, ceds, cuds, year_results)
        path = out_dir / f"report_{anno}.md"
        with open(path, "w") as f:
            f.write(report)
        print(f"  Written: {path}")

    # Generate combined report
    report_all = _generate_combined_report(cedolini, cuds, results, by_year)
    path = out_dir / "report_all.md"
    with open(path, "w") as f:
        f.write(report_all)
    print(f"  Written: {path}")


def _generate_combined_report(cedolini, cuds, results, by_year):
    """Generate the combined report."""
    lines = []
    lines.append("# VerificaCedolino - Report Completo\n")

    if _explain:
        lines.append(_blockquote(get_disclaimer()))

    lines.append(f"Dipendente: **{cedolini[0].cognome_nome}** ({cedolini[0].codice_fiscale})\n")
    lines.append(f"Datore: **{cedolini[0].ragione_sociale}**\n")
    lines.append(f"Contratto: {cedolini[0].contratto}\n")
    lines.append(f"Cedolini analizzati: **{len(cedolini)}** ({min(c.anno for c in cedolini)}-{max(c.anno for c in cedolini)})\n")
    lines.append("")

    if _explain:
        lines.append("## Come leggere questo report\n")
        lines.append(get_intro())
        lines.append("")

    # Summary of validation
    total_pass = sum(1 for r in results if r["status"] == "PASS")
    total_fail = sum(1 for r in results if r["status"] == "FAIL")
    total_warn = sum(1 for r in results if r["status"] == "WARNING")
    total_info = sum(1 for r in results if r["status"] == "INFO")

    lines.append("## Riepilogo Validazioni\n")
    lines.append(f"| Stato | Conteggio |")
    lines.append(f"|-------|-----------|")
    lines.append(f"| PASS | {total_pass} |")
    if total_fail:
        lines.append(f"| FAIL | {total_fail} |")
    if total_warn:
        lines.append(f"| WARNING | {total_warn} |")
    if total_info:
        lines.append(f"| INFO | {total_info} |")
    lines.append(f"| **Totale** | **{len(results)}** |")
    lines.append("")

    # Group results by validator name
    by_validator = defaultdict(lambda: {"PASS": 0, "FAIL": 0, "WARNING": 0, "INFO": 0})
    for r in results:
        # Extract validator category from nome
        nome = r["nome"]
        cat = _categorize_result(nome)
        by_validator[cat][r["status"]] += 1

    lines.append("### Dettaglio per Categoria\n")
    lines.append("| Categoria | PASS | FAIL | WARNING | INFO |")
    lines.append("|-----------|------|------|---------|------|")
    for cat in ["Netto in busta", "Contributi INPS", "IRPEF", "TFR", "Ratei", "Cross-check CUD"]:
        counts = by_validator.get(cat, {"PASS": 0, "FAIL": 0, "WARNING": 0, "INFO": 0})
        lines.append(f"| {cat} | {counts['PASS']} | {counts['FAIL']} | {counts['WARNING']} | {counts['INFO']} |")
    lines.append("")

    # Warnings/Fails detail
    problems = [r for r in results if r["status"] in ("FAIL", "WARNING")]
    if problems:
        lines.append("### Anomalie Rilevate\n")
        if _explain:
            exp = get_section_explanation("anomalie")
            if exp:
                lines.append(_blockquote(exp))
        if _explain:
            lines.append("| Anno | Mese | Controllo | Stato | Atteso | Effettivo | Diff | Nota |")
            lines.append("|------|------|-----------|-------|--------|-----------|------|------|")
            for r in problems:
                nota = get_validation_note(r["nome"])
                lines.append(
                    f"| {r['anno']} | {r['mese_label']} | {r['nome']} | {r['status']} "
                    f"| {r['atteso']} | {r['effettivo']} | {r['differenza']} | {nota} |"
                )
        else:
            lines.append("| Anno | Mese | Controllo | Stato | Atteso | Effettivo | Diff |")
            lines.append("|------|------|-----------|-------|--------|-----------|------|")
            for r in problems:
                lines.append(
                    f"| {r['anno']} | {r['mese_label']} | {r['nome']} | {r['status']} "
                    f"| {r['atteso']} | {r['effettivo']} | {r['differenza']} |"
                )
        lines.append("")

    # Per-year summaries
    for anno in sorted(by_year.keys()):
        ceds = sorted(by_year[anno], key=lambda c: c.mese)
        lines.append(f"## Anno {anno}\n")
        lines.append(_year_summary_table(anno, ceds))

        # Gross-to-net breakdowns
        if _explain:
            yearly_rows = build_gross_to_net_yearly(ceds)
            lines.append(f"### Da lordo a netto - {anno} (riepilogo annuale)\n")
            lines.append(_gross_to_net_table(yearly_rows))

            if _monthly_explain:
                for ced in ceds:
                    label = ced.mese_retribuzione or f"Mese {ced.mese}"
                    monthly_rows = build_gross_to_net(ced)
                    lines.append(f"### Da lordo a netto - {label}\n")
                    lines.append(_gross_to_net_table(monthly_rows))

        if _explain:
            exp = get_section_explanation("inps")
            if exp:
                lines.append(_blockquote(exp))
        lines.append(_year_inps_table(anno, ceds))

        if _explain:
            exp = get_section_explanation("irpef")
            if exp:
                lines.append(_blockquote(exp))
        lines.append(_year_irpef_table(anno, ceds))

    # CUD cross-check
    if cuds:
        lines.append("## Cross-check CUD\n")
        for cu in sorted(cuds, key=lambda c: c.anno_riferimento):
            lines.append(f"### CU{cu.anno_cu} (rif. {cu.anno_riferimento})\n")
            cud_results = [r for r in results if int(r["anno"]) == cu.anno_riferimento and "CUD" in r["nome"]]
            if cud_results:
                lines.append("| Controllo | Stato | CUD | Cedolini | Differenza |")
                lines.append("|-----------|-------|-----|----------|------------|")
                for r in cud_results:
                    lines.append(
                        f"| {r['nome']} | {r['status']} | {r['atteso']} | {r['effettivo']} | {r['differenza']} |"
                    )
                lines.append("")

    # Glossary
    if _explain:
        glossary = _glossary_section(cedolini)
        if glossary:
            lines.append(glossary)

    return "\n".join(lines)


def _generate_year_report(anno, ceds, cuds, year_results):
    """Generate a single year's report."""
    lines = []
    lines.append(f"# VerificaCedolino - Report {anno}\n")

    if _explain:
        lines.append(_blockquote(get_disclaimer()))

    # Validation summary for this year
    total_pass = sum(1 for r in year_results if r["status"] == "PASS")
    total_fail = sum(1 for r in year_results if r["status"] == "FAIL")
    total_warn = sum(1 for r in year_results if r["status"] == "WARNING")

    lines.append(f"Cedolini: **{len(ceds)}** | Controlli: {total_pass} PASS, {total_fail} FAIL, {total_warn} WARNING\n")

    if _explain:
        lines.append("## Come leggere questo report\n")
        lines.append(get_intro())
        lines.append("")

    # Monthly summary table
    lines.append(f"## Riepilogo Mensile\n")
    lines.append(_year_summary_table(anno, ceds))

    # Gross-to-net breakdowns
    if _explain:
        yearly_rows = build_gross_to_net_yearly(ceds)
        lines.append(f"### Da lordo a netto - {anno} (riepilogo annuale)\n")
        lines.append(_gross_to_net_table(yearly_rows))

        if _monthly_explain:
            for ced in ceds:
                label = ced.mese_retribuzione or f"Mese {ced.mese}"
                monthly_rows = build_gross_to_net(ced)
                lines.append(f"### Da lordo a netto - {label}\n")
                lines.append(_gross_to_net_table(monthly_rows))

    # INPS detail
    if _explain:
        lines.append(f"## Contributi INPS (previdenziali)\n")
        exp = get_section_explanation("inps")
        if exp:
            lines.append(_blockquote(exp))
    else:
        lines.append(f"## Dettaglio INPS\n")
    lines.append(_year_inps_table(anno, ceds))

    # IRPEF detail
    if _explain:
        lines.append(f"## IRPEF (tasse sul reddito)\n")
        exp = get_section_explanation("irpef")
        if exp:
            lines.append(_blockquote(exp))
    else:
        lines.append(f"## Dettaglio IRPEF\n")
    lines.append(_year_irpef_table(anno, ceds))

    # TFR detail
    if _explain:
        lines.append(f"## TFR (liquidazione)\n")
        exp = get_section_explanation("tfr")
        if exp:
            lines.append(_blockquote(exp))
    else:
        lines.append(f"## Dettaglio TFR\n")
    lines.append(_year_tfr_table(anno, ceds))

    # Anomalies
    problems = [r for r in year_results if r["status"] in ("FAIL", "WARNING")]
    if problems:
        lines.append("## Anomalie\n")
        if _explain:
            exp = get_section_explanation("anomalie")
            if exp:
                lines.append(_blockquote(exp))
            lines.append("| Mese | Controllo | Stato | Atteso | Effettivo | Diff | Nota |")
            lines.append("|------|-----------|-------|--------|-----------|------|------|")
            for r in problems:
                nota = get_validation_note(r["nome"])
                lines.append(
                    f"| {r['mese_label']} | {r['nome']} | {r['status']} "
                    f"| {r['atteso']} | {r['effettivo']} | {r['differenza']} | {nota} |"
                )
        else:
            lines.append("| Mese | Controllo | Stato | Atteso | Effettivo | Diff | Formula |")
            lines.append("|------|-----------|-------|--------|-----------|------|---------|")
            for r in problems:
                lines.append(
                    f"| {r['mese_label']} | {r['nome']} | {r['status']} "
                    f"| {r['atteso']} | {r['effettivo']} | {r['differenza']} | {r['formula']} |"
                )
        lines.append("")

    # Glossary
    if _explain:
        glossary = _glossary_section(ceds)
        if glossary:
            lines.append(glossary)

    return "\n".join(lines)


def _year_summary_table(anno, ceds):
    """Generate monthly summary table."""
    lines = []
    lines.append("| Mese | Competenze | Trattenute | Arr. | Netto | Formato |")
    lines.append("|------|-----------|------------|------|-------|---------|")
    for c in ceds:
        label = c.mese_retribuzione or f"Mese {c.mese}"
        lines.append(
            f"| {label} | {_fmt(c.totali.totale_competenze)} | {_fmt(c.totali.totale_trattenute)} "
            f"| {_fmt(c.totali.arrotondamento)} | {_fmt(c.totali.netto_in_busta)} | {c.formato} |"
        )

    # Totals
    tot_comp = sum(c.totali.totale_competenze for c in ceds)
    tot_tratt = sum(c.totali.totale_trattenute for c in ceds)
    tot_netto = sum(c.totali.netto_in_busta for c in ceds)
    lines.append(
        f"| **TOTALE** | **{_fmt(tot_comp)}** | **{_fmt(tot_tratt)}** "
        f"| | **{_fmt(tot_netto)}** | |"
    )
    lines.append("")
    return "\n".join(lines)


def _year_inps_table(anno, ceds):
    """Generate INPS contributions table with dynamic columns."""
    # Collect all contribution types present in this year's cedolini
    contrib_types = []
    seen = set()
    for c in ceds:
        for ct in c.contributi:
            if ct.descrizione not in seen:
                seen.add(ct.descrizione)
                contrib_types.append(ct.descrizione)

    if not contrib_types:
        return ""

    # Build header
    lines = []
    header = "| Mese | Imponibile |"
    separator = "|------|-----------|"
    for ct_name in contrib_types:
        header += f" {ct_name} |"
        separator += "------|"
    lines.append(header)
    lines.append(separator)

    tot = defaultdict(lambda: ZERO)
    for c in ceds:
        cmap = {ct.descrizione: ct for ct in c.contributi}
        imp = c.inps.imponibile_contrib_arrot_mese

        label = c.mese_retribuzione or f"Mese {c.mese}"
        row = f"| {label} | {_fmt(imp)} |"
        for ct_name in contrib_types:
            ct = cmap.get(ct_name)
            val = ct.importo_dipendente if ct else ZERO
            row += f" {_fmt(val)} |"
            tot[ct_name] += val
        lines.append(row)
        tot["imp"] += imp

    # Total row
    total_row = f"| **TOTALE** | **{_fmt(tot['imp'])}** |"
    for ct_name in contrib_types:
        total_row += f" **{_fmt(tot[ct_name])}** |"
    lines.append(total_row)
    lines.append("")
    return "\n".join(lines)


def _year_irpef_table(anno, ceds):
    """Generate IRPEF table."""
    lines = []
    lines.append("| Mese | Imponibile | IRPEF lorda | Detrazione | IRPEF netta |")
    lines.append("|------|-----------|-------------|-----------|-------------|")

    for c in ceds:
        label = c.mese_retribuzione or f"Mese {c.mese}"
        lines.append(
            f"| {label} | {_fmt(c.irpef.imponibile_fiscale_mese)} "
            f"| {_fmt(c.irpef.irpef_lorda_mese)} "
            f"| {_fmt(c.irpef.detrazione_lavoro_dip)} "
            f"| {_fmt(c.irpef.irpef_piu_imp_sost)} |"
        )

    # Annual from last cedolino
    regular = [c for c in ceds if not c.is_tredicesima]
    if regular:
        last = max(regular, key=lambda c: c.mese)
        if last.irpef.imponibile_fiscale_anno > ZERO:
            lines.append(
                f"| **Progressivo annuo** | **{_fmt(last.irpef.imponibile_fiscale_anno)}** "
                f"| **{_fmt(last.irpef.irpef_lorda_anno)}** | "
                f"| **{_fmt(last.irpef.irpef_netta_anno)}** |"
            )

    lines.append("")
    return "\n".join(lines)


def _year_tfr_table(anno, ceds):
    """Generate TFR table."""
    lines = []
    lines.append("| Mese | Retrib. utile | Quota TFR | Contr. agg. | TFR annuo prog. |")
    lines.append("|------|-------------|-----------|------------|----------------|")

    for c in ceds:
        if c.tfr.retribuzione_utile_tfr == ZERO:
            continue
        label = c.mese_retribuzione or f"Mese {c.mese}"
        lines.append(
            f"| {label} | {_fmt(c.tfr.retribuzione_utile_tfr)} "
            f"| {_fmt(c.tfr.tfr_mese)} "
            f"| {_fmt(c.tfr.contributo_agg_tfr)} "
            f"| {_fmt(c.tfr.tfr_annuo)} |"
        )

    lines.append("")
    return "\n".join(lines)


def _categorize_result(nome):
    """Categorize a validation result by its nome."""
    if "Netto" in nome:
        return "Netto in busta"
    # Check TFR before INPS (avoid "Contributo agg. TFR" matching "Contributo")
    if any(x in nome for x in ["TFR", "Contributo agg"]):
        return "TFR"
    if any(x in nome for x in ["IVS", "CIGS", "FIS", "EST", "FON.TE", "INPS", "Addizionale IVS",
                                "FDO_SOLID", "CCNL", "Contributo"]):
        return "Contributi INPS"
    if any(x in nome for x in ["IRPEF", "Addizionale"]):
        return "IRPEF"
    if any(x in nome for x in ["ratei", "saldo", "Residuo", "Continuita"]):
        return "Ratei"
    if "CUD" in nome:
        return "Cross-check CUD"
    return nome


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VerificaCedolino - Generazione report Markdown")
    parser.add_argument("--input-dir", type=Path, default=INPUT_DIR, help="Cartella con sottodirectory anno contenenti PDF")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="Cartella output per CSV e report")
    parser.add_argument("--no-explain", action="store_true", help="Disabilita spiegazioni (output compatibile con v0.2)")
    parser.add_argument("--no-monthly-explain", action="store_true", help="Esclude i breakdown mensili da lordo a netto")
    args = parser.parse_args()
    _explain = not args.no_explain
    _monthly_explain = not args.no_monthly_explain
    generate_report(args.input_dir, args.output_dir)
