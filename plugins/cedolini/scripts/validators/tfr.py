"""Validatore TFR e previdenza complementare."""

from decimal import Decimal, ROUND_HALF_UP
from scripts.models import Cedolino, ValidationResult, ZERO


def validate_tfr(cedolini: list[Cedolino]) -> list[ValidationResult]:
    """Validate TFR calculations for each cedolino.

    The payroll system computes TFR as follows:
      quota_lorda = retrib_utile / 13.5
      contr_agg   = computed internally (approx 0.50% of retrib, but varies
                    month-to-month due to daily-rate calculation)
      tfr_mese    = quota_lorda - contr_agg

    The invariant is:  tfr_mese + contr_agg == retrib_utile / 13.5

    We validate this identity rather than trying to independently compute
    contr_agg, which the payroll system calculates using a daily-rate method
    that produces slightly different values each month.
    """
    results = []

    for ced in cedolini:
        retrib_utile = ced.tfr.retribuzione_utile_tfr
        tfr_mese = ced.tfr.tfr_mese

        if retrib_utile == ZERO or tfr_mese == ZERO:
            continue

        # Quota lorda TFR = retrib_utile / 13.5
        quota_lorda = (retrib_utile / Decimal("13.5")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        contr_agg_actual = ced.tfr.contributo_agg_tfr

        if contr_agg_actual > ZERO:
            # Old layout: both TFR mese and contributo agg. are shown separately.
            # Primary check: tfr_mese + contr_agg == quota_lorda (retrib/13.5)
            actual_sum = tfr_mese + contr_agg_actual
            diff = abs(actual_sum - quota_lorda)
            tolerance = Decimal("0.02")

            results.append(ValidationResult(
                nome="Quota TFR mensile",
                anno=ced.anno, mese=ced.mese,
                mese_label=ced.mese_retribuzione,
                status="PASS" if diff <= tolerance else "FAIL",
                atteso=str(quota_lorda),
                effettivo=str(actual_sum),
                differenza=str(diff),
                tolleranza=str(tolerance),
                formula=(
                    f"TFR mese ({tfr_mese}) + contr. agg. ({contr_agg_actual})"
                    f" = {actual_sum} vs {retrib_utile}/13.5 = {quota_lorda}"
                ),
            ))

            # Contributo aggiuntivo TFR: reasonableness check against 0.50%
            # The payroll system uses a daily-rate method, so the actual value
            # can deviate from the simple retrib*0.005 by up to ~1 EUR.
            reference_agg = (retrib_utile * Decimal("0.005")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            diff_agg = abs(reference_agg - contr_agg_actual)

            results.append(ValidationResult(
                nome="Contributo agg. TFR",
                anno=ced.anno, mese=ced.mese,
                mese_label=ced.mese_retribuzione,
                status="PASS" if diff_agg <= Decimal("1.00") else "WARNING",
                atteso=str(reference_agg),
                effettivo=str(contr_agg_actual),
                differenza=str(diff_agg),
                tolleranza="1.00",
                formula=f"{retrib_utile} * 0.005 = {reference_agg} (riferimento; calcolo effettivo su base giornaliera)",
            ))
        else:
            # New layout: only the net "Quota T.F.R." is shown (contr. agg.
            # is not broken out separately).  tfr_mese is the net quota, i.e.
            # quota_lorda minus the contributo aggiuntivo.
            # We check that the implied contr. agg. is reasonable (~0.5% of retrib).
            implied_contr = quota_lorda - tfr_mese
            reference_agg = (retrib_utile * Decimal("0.005")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            diff = abs(implied_contr - reference_agg)
            tolerance = Decimal("1.50")

            results.append(ValidationResult(
                nome="Quota TFR mensile",
                anno=ced.anno, mese=ced.mese,
                mese_label=ced.mese_retribuzione,
                status="PASS" if diff <= tolerance else "FAIL",
                atteso=str(quota_lorda - reference_agg),
                effettivo=str(tfr_mese),
                differenza=str(diff),
                tolleranza=str(tolerance),
                formula=(
                    f"{retrib_utile}/13.5 = {quota_lorda}; TFR netto {tfr_mese}"
                    f" => contr. agg. implicito = {implied_contr}"
                    f" vs rif. 0.5% = {reference_agg}"
                ),
            ))

    return results


def validate_tfr_annual(cedolini: list[Cedolino]) -> list[ValidationResult]:
    """Validate annual TFR accumulation."""
    results = []

    # Group by year
    by_year: dict[int, list[Cedolino]] = {}
    for c in cedolini:
        by_year.setdefault(c.anno, []).append(c)

    for anno, ceds in by_year.items():
        ceds_sorted = sorted(ceds, key=lambda c: c.mese)

        # Sum monthly TFR
        total_tfr = sum(c.tfr.tfr_mese for c in ceds_sorted)

        # Compare with TFR annuo from last cedolino of the year
        last = ceds_sorted[-1]
        tfr_annuo = last.tfr.tfr_annuo

        if tfr_annuo > ZERO and total_tfr > ZERO:
            diff = abs(total_tfr - tfr_annuo)
            results.append(ValidationResult(
                nome="TFR annuo progressivo",
                anno=anno, mese=last.mese,
                mese_label=f"Anno {anno}",
                status="PASS" if diff <= Decimal("1.00") else "WARNING",
                atteso=str(total_tfr),
                effettivo=str(tfr_annuo),
                differenza=str(diff),
                tolleranza="1.00",
                formula=f"Somma TFR mensili = {total_tfr}",
            ))

    return results
