"""Validatore netto in busta: netto = competenze - trattenute + arrotondamento."""

from decimal import Decimal
from scripts.models import Cedolino, ValidationResult, ZERO


def validate_net_pay(cedolini: list[Cedolino]) -> list[ValidationResult]:
    """Validate net pay calculation for each cedolino."""
    results = []

    for ced in cedolini:
        comp = ced.totali.totale_competenze
        tratt = ced.totali.totale_trattenute
        netto = ced.totali.netto_in_busta

        if not netto or netto == ZERO:
            continue

        if ced.formato == "sistemi":
            # Sistemi: arr_preced is recovered (subtracted), arr_attuale is added
            arr = ced.totali.arrotondamento_attuale - ced.totali.arrotondamento_precedente
        else:
            arr = ced.totali.arrotondamento

        expected = comp - tratt + arr
        diff = abs(expected - netto)
        tolerance = Decimal("0.02")

        status = "PASS" if diff <= tolerance else "FAIL"

        results.append(ValidationResult(
            nome="Netto in busta",
            anno=ced.anno,
            mese=ced.mese,
            mese_label=ced.mese_retribuzione,
            status=status,
            atteso=str(expected),
            effettivo=str(netto),
            differenza=str(diff),
            tolleranza=str(tolerance),
            formula=f"comp({comp}) - tratt({tratt}) + arr({arr}) = {expected}",
        ))

    return results
