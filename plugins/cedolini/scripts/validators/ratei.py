"""Validatore continuita' ratei ferie/permessi tra mesi.

Sistemi and Zucchetti both show cumulative YTD values:
  - residuo_ap: carry-over from end of previous year (constant all year)
  - maturato: cumulative year-to-date maturated
  - goduto: cumulative year-to-date used
  - saldo: residuo_ap + maturato - goduto

Checks performed:
  1. Saldo formula: saldo == residuo_ap + maturato - goduto
  2. Year-end continuity: December saldo == next January residuo_ap
  3. Within-year consistency: residuo_ap is constant throughout the year
"""

from decimal import Decimal
from scripts.models import Cedolino, ValidationResult, ZERO


def validate_ratei(cedolini: list[Cedolino]) -> list[ValidationResult]:
    """Validate ratei consistency."""
    results = []

    sorted_ceds = sorted(cedolini, key=lambda c: (c.anno, c.mese))

    # 1. Check saldo formula for each month
    for ced in sorted_ceds:
        if ced.is_tredicesima:
            continue
        for r in ced.ratei:
            expected_saldo = r.residuo_ap + r.maturato - r.goduto
            diff = abs(expected_saldo - r.saldo)

            results.append(ValidationResult(
                nome=f"Calcolo saldo {r.tipo}",
                anno=ced.anno, mese=ced.mese,
                mese_label=ced.mese_retribuzione,
                status="PASS" if diff <= Decimal("0.01") else "FAIL",
                atteso=str(expected_saldo),
                effettivo=str(r.saldo),
                differenza=str(diff),
                tolleranza="0.01",
                formula=f"residuo_ap({r.residuo_ap}) + maturato({r.maturato}) - goduto({r.goduto})",
            ))

    # 2. Year-end continuity: Dec saldo == next Jan residuo_ap
    by_year: dict[int, list[Cedolino]] = {}
    for c in sorted_ceds:
        if not c.is_tredicesima:
            by_year.setdefault(c.anno, []).append(c)

    years = sorted(by_year.keys())
    for i in range(len(years) - 1):
        curr_year = years[i]
        next_year = years[i + 1]

        # Get December (or last month) of current year
        curr_ceds = sorted(by_year[curr_year], key=lambda c: c.mese)
        next_ceds = sorted(by_year[next_year], key=lambda c: c.mese)

        last = curr_ceds[-1]
        first_next = next_ceds[0]

        for r_last in last.ratei:
            for r_next in first_next.ratei:
                if _match_rateo_type(r_last.tipo, r_next.tipo):
                    diff = abs(r_last.saldo - r_next.residuo_ap)
                    results.append(ValidationResult(
                        nome=f"Continuita' annuale {r_last.tipo}",
                        anno=curr_year, mese=last.mese,
                        mese_label=f"{last.mese_retribuzione} -> {first_next.mese_retribuzione}",
                        status="PASS" if diff <= Decimal("0.01") else "FAIL",
                        atteso=str(r_last.saldo),
                        effettivo=str(r_next.residuo_ap),
                        differenza=str(diff),
                        tolleranza="0.01",
                        formula=f"saldo dic {curr_year} = residuo_ap gen {next_year}",
                    ))
                    break

    # 3. Within-year consistency: residuo_ap should be constant
    for anno, ceds in by_year.items():
        ceds_sorted = sorted(ceds, key=lambda c: c.mese)
        if len(ceds_sorted) < 2:
            continue

        # Use first month's residuo_ap as reference
        first = ceds_sorted[0]
        for r_ref in first.ratei:
            for ced in ceds_sorted[1:]:
                for r in ced.ratei:
                    if _match_rateo_type(r_ref.tipo, r.tipo):
                        diff = abs(r_ref.residuo_ap - r.residuo_ap)
                        if diff > Decimal("0.01"):
                            results.append(ValidationResult(
                                nome=f"Residuo AP costante {r.tipo}",
                                anno=anno, mese=ced.mese,
                                mese_label=ced.mese_retribuzione,
                                status="FAIL",
                                atteso=str(r_ref.residuo_ap),
                                effettivo=str(r.residuo_ap),
                                differenza=str(diff),
                                tolleranza="0.01",
                                formula=f"residuo_ap deve essere costante nell'anno (rif. mese {first.mese})",
                            ))
                        break

    return results


def _match_rateo_type(tipo1: str, tipo2: str) -> bool:
    """Match rateo types between different format naming conventions."""
    t1 = tipo1.lower().replace(".", "").replace("'", "")
    t2 = tipo2.lower().replace(".", "").replace("'", "")

    if "ferie" in t1 and "ferie" in t2:
        return True
    if ("rol" in t1 or "permessi" in t1) and ("rol" in t2 or "permessi" in t2):
        return True
    if ("festivita" in t1 or "ex-fs" in t1 or "perm" in t1 and "fs" in t1) and \
       ("festivita" in t2 or "ex-fs" in t2 or "perm" in t2 and "fs" in t2):
        return True
    return t1 == t2
