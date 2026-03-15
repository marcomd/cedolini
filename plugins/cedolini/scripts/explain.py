"""Explanation layer: categorization, texts, and glossary for reports."""

import re
import yaml
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from scripts.models import Cedolino, ZERO

CONFIG_PATH = Path(__file__).parent.parent / "config" / "explanations.yaml"

# Compiled regex cache (populated on first load)
_voce_patterns: list[tuple[str, re.Pattern, str]] = []


@lru_cache(maxsize=1)
def load_config() -> dict:
    """Load and cache config/explanations.yaml."""
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _ensure_patterns():
    """Compile voce category patterns once."""
    global _voce_patterns
    if _voce_patterns:
        return
    cfg = load_config()
    for cat_id, cat_data in cfg.get("voce_categories", {}).items():
        label = cat_data.get("label", cat_id)
        for pat in cat_data.get("patterns", []):
            _voce_patterns.append((label, re.compile(pat, re.IGNORECASE), cat_id))


def get_disclaimer() -> str:
    return load_config().get("disclaimer", "").strip()


def get_intro() -> str:
    return load_config().get("intro", "").strip()


def get_section_explanation(key: str) -> str:
    return load_config().get("sections", {}).get(key, "").strip()


def categorize_voce(descrizione: str) -> tuple[str, str]:
    """Return (category_label, category_id) for a voce description.

    Matches against voce_categories patterns. Falls back to ("Altro", "altro").
    """
    _ensure_patterns()
    if not descrizione:
        return ("Altro", "altro")
    for label, pattern, cat_id in _voce_patterns:
        if pattern.search(descrizione):
            return (label, cat_id)
    return ("Altro", "altro")


def build_gross_to_net(ced: Cedolino) -> list[tuple[str, Decimal, str]]:
    """Build ordered gross-to-net breakdown for a single cedolino.

    Returns list of (label, amount, explanation) tuples.
    Positive = competenze, negative = trattenute.
    """
    rows: list[tuple[str, Decimal, str]] = []

    # Only include voci that are actual payroll items (have at least one flag set)
    # Info lines (Imponibile IRPEF, IRPEF lorda, contribution details) have all flags False
    # and are represented by structured sections below.
    for v in ced.voci:
        is_payroll_voce = v.flag_c or v.flag_i or v.flag_t or v.flag_n
        if not is_payroll_voce:
            continue
        if v.competenze and v.competenze != ZERO:
            label, _ = categorize_voce(v.descrizione)
            rows.append((v.descrizione, v.competenze, label))
        elif v.trattenute and v.trattenute != ZERO:
            label, cat_id = categorize_voce(v.descrizione)
            rows.append((v.descrizione, -v.trattenute, label))

    # Subtotal competenze
    rows.append(("**Totale competenze**", ced.totali.totale_competenze, ""))

    # Contributions from structured data
    for ct in ced.contributi:
        pct = f" ({_fmt_pct(ct.percentuale)})" if ct.percentuale != ZERO else ""
        rows.append((f"{ct.descrizione}{pct}", -ct.importo_dipendente, "Contributi previdenziali"))

    # IRPEF
    if ced.irpef.irpef_piu_imp_sost != ZERO:
        rows.append(("IRPEF", -ced.irpef.irpef_piu_imp_sost, "Tasse sul reddito"))
    elif ced.irpef.irpef_netta_mese != ZERO:
        rows.append(("IRPEF", -ced.irpef.irpef_netta_mese, "Tasse sul reddito"))

    # Addizionali
    if ced.addizionale_regionale != ZERO:
        rows.append(("Addizionale regionale", -ced.addizionale_regionale, "Tasse sul reddito"))
    if ced.addizionale_comunale_saldo != ZERO:
        rows.append(("Addizionale comunale (saldo)", -ced.addizionale_comunale_saldo, "Tasse sul reddito"))
    if ced.addizionale_comunale_acconto != ZERO:
        rows.append(("Addizionale comunale (acconto)", -ced.addizionale_comunale_acconto, "Tasse sul reddito"))

    # Trattenute from voci not yet included (sindacale, polizza, etc. already added above)

    # Subtotal trattenute
    rows.append(("**Totale trattenute**", -ced.totali.totale_trattenute, ""))

    # Arrotondamento
    arr = ced.totali.arrotondamento
    if arr != ZERO:
        rows.append(("Arrotondamento", arr, ""))

    # Netto
    rows.append(("**Netto in busta**", ced.totali.netto_in_busta, ""))

    return rows


def build_gross_to_net_yearly(cedolini: list[Cedolino]) -> list[tuple[str, Decimal, str]]:
    """Aggregate gross-to-net breakdown by category over a full year.

    Returns list of (category_label, total_amount, explanation) tuples.
    """
    comp_by_cat: dict[str, Decimal] = {}
    comp_order: list[str] = []
    tratt_by_cat: dict[str, Decimal] = {}
    tratt_order: list[str] = []

    tot_competenze = ZERO
    tot_trattenute = ZERO
    tot_arrotondamento = ZERO
    tot_netto = ZERO

    for ced in cedolini:
        # Only include voci with at least one flag set (real payroll items)
        for v in ced.voci:
            is_payroll_voce = v.flag_c or v.flag_i or v.flag_t or v.flag_n
            if not is_payroll_voce:
                continue
            if v.competenze and v.competenze != ZERO:
                label, _ = categorize_voce(v.descrizione)
                comp_by_cat[label] = comp_by_cat.get(label, ZERO) + v.competenze
                if label not in comp_order:
                    comp_order.append(label)
            elif v.trattenute and v.trattenute != ZERO:
                label, cat_id = categorize_voce(v.descrizione)
                tratt_by_cat[label] = tratt_by_cat.get(label, ZERO) + v.trattenute
                if label not in tratt_order:
                    tratt_order.append(label)

        # Contributions
        for ct in ced.contributi:
            key = ct.descrizione
            tratt_by_cat[key] = tratt_by_cat.get(key, ZERO) + ct.importo_dipendente
            if key not in tratt_order:
                tratt_order.append(key)

        # IRPEF
        irpef = ced.irpef.irpef_piu_imp_sost if ced.irpef.irpef_piu_imp_sost != ZERO else ced.irpef.irpef_netta_mese
        if irpef != ZERO:
            tratt_by_cat["IRPEF"] = tratt_by_cat.get("IRPEF", ZERO) + irpef
            if "IRPEF" not in tratt_order:
                tratt_order.append("IRPEF")

        # Addizionali
        for name, val in [
            ("Addizionale regionale", ced.addizionale_regionale),
            ("Addizionale comunale", ced.addizionale_comunale_saldo + ced.addizionale_comunale_acconto),
        ]:
            if val != ZERO:
                tratt_by_cat[name] = tratt_by_cat.get(name, ZERO) + val
                if name not in tratt_order:
                    tratt_order.append(name)

        tot_competenze += ced.totali.totale_competenze
        tot_trattenute += ced.totali.totale_trattenute
        tot_arrotondamento += ced.totali.arrotondamento
        tot_netto += ced.totali.netto_in_busta

    rows: list[tuple[str, Decimal, str]] = []

    for label in comp_order:
        rows.append((label, comp_by_cat[label], ""))
    rows.append(("**Totale competenze**", tot_competenze, ""))

    for label in tratt_order:
        rows.append((label, -tratt_by_cat[label], ""))
    rows.append(("**Totale trattenute**", -tot_trattenute, ""))

    if tot_arrotondamento != ZERO:
        rows.append(("Arrotondamento", tot_arrotondamento, ""))

    rows.append(("**Netto in busta**", tot_netto, ""))

    return rows


def get_relevant_glossary(cedolini: list[Cedolino]) -> dict[str, str]:
    """Return only glossary terms that appear in the cedolini data.

    Checks voce descriptions, contribution names, and structural field names.
    """
    cfg = load_config()
    full_glossary = cfg.get("glossary", {})

    # Build text corpus from cedolini
    texts: list[str] = []
    for ced in cedolini:
        for v in ced.voci:
            texts.append(v.descrizione)
        for ct in ced.contributi:
            texts.append(ct.descrizione)
        if ced.irpef.irpef_piu_imp_sost != ZERO or ced.irpef.irpef_netta_mese != ZERO:
            texts.append("IRPEF")
        if ced.irpef.detrazione_lavoro_dip != ZERO:
            texts.append("Detrazioni")
        if ced.irpef.imponibile_fiscale_mese != ZERO:
            texts.append("Imponibile fiscale")
            texts.append("Scaglioni IRPEF")
        if ced.inps.imponibile_contributivo_mese != ZERO:
            texts.append("Imponibile contributivo")
        if ced.tfr.retribuzione_utile_tfr != ZERO:
            texts.append("TFR")
            texts.append("Retribuzione utile TFR")
        if ced.addizionale_regionale != ZERO:
            texts.append("Addizionale regionale")
        if ced.addizionale_comunale_saldo != ZERO or ced.addizionale_comunale_acconto != ZERO:
            texts.append("Addizionale comunale")
        if ced.irpef.irpef_conguaglio != ZERO:
            texts.append("Conguaglio")
        for r in ced.ratei:
            if "rol" in r.tipo.lower():
                texts.append("R.O.L.")
        for ct in ced.contributi:
            desc_upper = ct.descrizione.upper()
            if "FONTE" in desc_upper:
                texts.append("Previdenza complementare")

    corpus = " ".join(texts).upper()

    relevant = {}
    for term, meaning in full_glossary.items():
        # Match term (or key parts) against corpus
        term_upper = term.upper()
        # Direct match or partial match for compound terms
        if term_upper in corpus:
            relevant[term] = meaning
        elif "." in term and term_upper.replace(".", "") in corpus:
            relevant[term] = meaning

    return relevant


def get_validation_note(result_nome: str) -> str:
    """Return an explanatory note for a validation result type."""
    cfg = load_config()
    notes = cfg.get("validation_notes", {})
    for pattern, note in notes.items():
        if pattern.lower() in result_nome.lower():
            return note
    return ""


def _fmt_pct(val: Decimal) -> str:
    """Format a percentage value for display, e.g. 9.19 -> '9,19%'."""
    if val == ZERO:
        return ""
    s = f"{val}".replace(".", ",")
    # Remove trailing zeros after comma
    if "," in s:
        s = s.rstrip("0").rstrip(",")
    return f"{s}%"
