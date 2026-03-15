"""Validatore IRPEF (scaglioni, detrazioni, addizionali)."""

from decimal import Decimal, ROUND_HALF_UP
from scripts.models import Cedolino, ValidationResult, ZERO


# Scaglioni IRPEF by period
# 2007-2021: 5 brackets
SCAGLIONI_2007 = [
    (Decimal("15000"), Decimal("0.23")),
    (Decimal("28000"), Decimal("0.27")),
    (Decimal("55000"), Decimal("0.38")),
    (Decimal("75000"), Decimal("0.41")),
    (Decimal("999999999"), Decimal("0.43")),
]

# 2022: 4 brackets (riforma)
SCAGLIONI_2022 = [
    (Decimal("15000"), Decimal("0.23")),
    (Decimal("28000"), Decimal("0.25")),
    (Decimal("50000"), Decimal("0.35")),
    (Decimal("999999999"), Decimal("0.43")),
]

# 2023: same as 2022
SCAGLIONI_2023 = SCAGLIONI_2022

# 2024+: 3 brackets
SCAGLIONI_2024 = [
    (Decimal("28000"), Decimal("0.23")),
    (Decimal("50000"), Decimal("0.35")),
    (Decimal("999999999"), Decimal("0.43")),
]


def _get_scaglioni(anno: int):
    """Get IRPEF brackets for a given year."""
    if anno <= 2021:
        return SCAGLIONI_2007
    if anno == 2022:
        return SCAGLIONI_2022
    if anno == 2023:
        return SCAGLIONI_2023
    return SCAGLIONI_2024


def _calcola_irpef(imponibile: Decimal, anno: int) -> Decimal:
    """Calcola IRPEF lorda su imponibile annuo."""
    scaglioni = _get_scaglioni(anno)
    imposta = ZERO
    prev_limit = ZERO

    for limit, rate in scaglioni:
        if imponibile <= prev_limit:
            break
        taxable = min(imponibile, limit) - prev_limit
        imposta += (taxable * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        prev_limit = limit

    return imposta


def _detrazione_lavoro_dip(reddito: Decimal, giorni: int, anno: int) -> Decimal:
    """Calcola detrazione lavoro dipendente."""
    if reddito <= ZERO:
        return ZERO

    gg = Decimal(str(giorni))

    if anno <= 2012:
        # Pre-2013 formula (DL 201/2011)
        if reddito <= Decimal("8000"):
            det = Decimal("1840")
            det = max(det, Decimal("690"))
        elif reddito <= Decimal("15000"):
            det = Decimal("1338") + Decimal("502") * (Decimal("15000") - reddito) / Decimal("7000")
        elif reddito <= Decimal("55000"):
            det = Decimal("1338") * (Decimal("55000") - reddito) / Decimal("40000")
        else:
            det = ZERO
    elif anno <= 2021:
        # 2013-2021 formula
        if reddito <= Decimal("8000"):
            det = Decimal("1880")
            det = max(det, Decimal("690"))
        elif reddito <= Decimal("28000"):
            det = Decimal("978") + Decimal("902") * (Decimal("28000") - reddito) / Decimal("20000")
        elif reddito <= Decimal("55000"):
            det = Decimal("978") * (Decimal("55000") - reddito) / Decimal("27000")
        else:
            det = ZERO
    elif anno <= 2023:
        # 2022-2023 formula
        if reddito <= Decimal("15000"):
            det = Decimal("1880")
            det = max(det, Decimal("690"))
        elif reddito <= Decimal("28000"):
            det = Decimal("1910") + Decimal("1190") * (Decimal("28000") - reddito) / Decimal("13000")
        elif reddito <= Decimal("50000"):
            det = Decimal("1910") * (Decimal("50000") - reddito) / Decimal("22000")
        else:
            det = ZERO
    else:
        # 2024+: detrazioni semplificate
        if reddito <= Decimal("15000"):
            det = Decimal("1955")
            det = max(det, Decimal("690"))
        elif reddito <= Decimal("28000"):
            det = Decimal("1910") + Decimal("1190") * (Decimal("28000") - reddito) / Decimal("13000")
        elif reddito <= Decimal("50000"):
            det = Decimal("1910") * (Decimal("50000") - reddito) / Decimal("22000")
        else:
            det = ZERO

    # Rapportare ai giorni
    det = (det * gg / Decimal("365")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return max(det, ZERO)


def validate_irpef(cedolini: list[Cedolino]) -> list[ValidationResult]:
    """Validate monthly IRPEF calculations."""
    results = []

    for ced in cedolini:
        imp_mese = ced.irpef.imponibile_fiscale_mese
        irpef_lorda = ced.irpef.irpef_lorda_mese
        irpef_netta = ced.irpef.irpef_netta_mese

        if imp_mese == ZERO or irpef_lorda == ZERO:
            continue

        # For monthly IRPEF, the payroll projects annual income:
        # imponibile_annuo = imponibile_mese * 12 (approx) for tredicesima
        # But the actual method is: cumulative imponibile * 12/months_elapsed
        # We validate the annual projection at year-end (December/conguaglio)
        # For monthly, just check that irpef_netta = irpef_lorda - detrazioni

        if ced.is_tredicesima:
            # Tredicesima: no detrazioni
            diff = abs(irpef_lorda - irpef_netta)
            results.append(ValidationResult(
                nome="IRPEF netta tredicesima",
                anno=ced.anno, mese=ced.mese,
                mese_label=ced.mese_retribuzione,
                status="PASS" if diff <= Decimal("0.02") else "FAIL",
                atteso=str(irpef_lorda),
                effettivo=str(irpef_netta),
                differenza=str(diff),
                tolleranza="0.02",
                formula=f"irpef_lorda({irpef_lorda}) = irpef_netta({irpef_netta}) [no detrazioni]",
            ))
        elif ced.mese != 12:
            # Regular month: check irpef_lorda
            # Project annual imponibile
            imp_annuo = imp_mese * 12
            expected_lorda = _calcola_irpef(imp_annuo, ced.anno) / 12
            expected_lorda = expected_lorda.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            diff = abs(expected_lorda - irpef_lorda)
            tolerance = Decimal("5.00")  # Wide tolerance for projection method differences

            results.append(ValidationResult(
                nome="IRPEF lorda mensile (stima)",
                anno=ced.anno, mese=ced.mese,
                mese_label=ced.mese_retribuzione,
                status="PASS" if diff <= tolerance else "WARNING",
                atteso=str(expected_lorda),
                effettivo=str(irpef_lorda),
                differenza=str(diff),
                tolleranza=str(tolerance),
                formula=f"IRPEF_annua({imp_annuo}) / 12",
                note="Stima basata su proiezione lineare, differenze attese per metodo cumulativo",
            ))

    return results


def validate_irpef_annual(cedolini: list[Cedolino]) -> list[ValidationResult]:
    """Validate annual IRPEF at conguaglio (December)."""
    results = []

    # Group by year
    by_year: dict[int, list[Cedolino]] = {}
    for c in cedolini:
        by_year.setdefault(c.anno, []).append(c)

    for anno, ceds in by_year.items():
        # Find December or last month with conguaglio
        dec = None
        for c in ceds:
            if c.mese == 12 and c.irpef.imponibile_fiscale_anno > ZERO:
                dec = c
                break

        if not dec:
            continue

        imp_annuo = dec.irpef.imponibile_fiscale_anno
        irpef_lorda_anno = dec.irpef.irpef_lorda_anno

        if imp_annuo == ZERO:
            continue

        # Calculate expected IRPEF lorda
        expected = _calcola_irpef(imp_annuo, anno)
        diff = abs(expected - irpef_lorda_anno)
        tolerance = Decimal("1.00")

        results.append(ValidationResult(
            nome="IRPEF lorda annuale",
            anno=anno, mese=12,
            mese_label=f"Conguaglio {anno}",
            status="PASS" if diff <= tolerance else "FAIL",
            atteso=str(expected),
            effettivo=str(irpef_lorda_anno),
            differenza=str(diff),
            tolleranza=str(tolerance),
            formula=f"Scaglioni su imponibile {imp_annuo}",
        ))

        # Check detrazioni
        if dec.irpef.gg_detrazione_anno > 0:
            gg = dec.irpef.gg_detrazione_anno
            det_expected = _detrazione_lavoro_dip(imp_annuo, gg, anno)
            det_actual = irpef_lorda_anno - dec.irpef.irpef_netta_anno if dec.irpef.irpef_netta_anno else ZERO

            if det_actual > ZERO:
                diff = abs(det_expected - det_actual)
                results.append(ValidationResult(
                    nome="Detrazione lavoro dip. annuale",
                    anno=anno, mese=12,
                    mese_label=f"Conguaglio {anno}",
                    status="PASS" if diff <= Decimal("5.00") else "WARNING",
                    atteso=str(det_expected),
                    effettivo=str(det_actual),
                    differenza=str(diff),
                    tolleranza="5.00",
                    formula=f"Detrazione per reddito {imp_annuo}, gg={gg}",
                ))

    return results
