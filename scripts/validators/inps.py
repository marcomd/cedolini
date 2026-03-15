"""Validatore contributi INPS - CCNL-aware."""

from decimal import Decimal, ROUND_HALF_UP
from scripts.models import Cedolino, ValidationResult, ZERO
from scripts.ccnl import CCNLConfig


def validate_inps(cedolini: list[Cedolino],
                  ccnl_configs: dict[str, CCNLConfig] | None = None) -> list[ValidationResult]:
    """Validate INPS contributions for each cedolino, using CCNL config."""
    results = []

    for ced in cedolini:
        contrib_map = {c.descrizione: c for c in ced.contributi}

        # Get imponibile arrotondato
        imp_arrot = ced.inps.imponibile_contrib_arrot_mese
        if imp_arrot == ZERO:
            ivs = contrib_map.get("IVS")
            if ivs and ivs.imponibile:
                imp_arrot = ivs.imponibile

        if imp_arrot == ZERO:
            continue

        # Try to find CCNL config
        ccnl_config = None
        if ccnl_configs and ced.ccnl:
            ccnl_config = ccnl_configs.get(ced.ccnl)

        if ccnl_config:
            _validate_with_ccnl(results, ced, contrib_map, imp_arrot, ccnl_config)
        else:
            # No CCNL config: emit INFO and skip CCNL-specific validation
            if ced.ccnl:
                results.append(ValidationResult(
                    nome="CCNL config",
                    anno=ced.anno, mese=ced.mese,
                    mese_label=ced.mese_retribuzione,
                    status="INFO",
                    note=f"CCNL '{ced.ccnl}' non trovato in config, skip contributi",
                ))
            # Fall back to legacy hardcoded check (commercio default)
            _validate_legacy(results, ced, contrib_map, imp_arrot)

        # Addizionale IVS 1% (universal, not CCNL-dependent)
        add_ivs = contrib_map.get("ADD_IVS")
        if add_ivs:
            results.append(ValidationResult(
                nome="Addizionale IVS 1%",
                anno=ced.anno, mese=ced.mese,
                mese_label=ced.mese_retribuzione,
                status="INFO",
                atteso="",
                effettivo=str(add_ivs.importo_dipendente),
                differenza="",
                formula=f"imp={add_ivs.imponibile} * 1%",
            ))

    return results


def _validate_with_ccnl(results, ced, contrib_map, imp_arrot, ccnl_config: CCNLConfig):
    """Validate contributions using CCNL config rules."""
    for rule in ccnl_config.contributions:
        # Find matching contribution in cedolino by name or aliases
        contrib = _find_contrib(contrib_map, rule.name, rule.aliases)

        if not contrib:
            continue

        if rule.type == "fixed":
            expected = rule.amount
            diff = abs(contrib.importo_dipendente - expected)
            results.append(ValidationResult(
                nome=f"Contributo {rule.name}",
                anno=ced.anno, mese=ced.mese,
                mese_label=ced.mese_retribuzione,
                status="PASS" if diff <= rule.tolerance else "FAIL",
                atteso=str(expected),
                effettivo=str(contrib.importo_dipendente),
                differenza=str(diff),
                tolleranza=str(rule.tolerance),
                formula=f"fisso {expected}",
            ))
        else:
            # Rate-based contribution
            base = contrib.imponibile if rule.use_own_imponibile and contrib.imponibile > ZERO else imp_arrot
            # Prefer cedolino's own printed rate for internal consistency check,
            # fall back to config rate (handles historical rate changes)
            rate = rule.rate
            if contrib.percentuale > ZERO:
                rate = contrib.percentuale / Decimal("100")
            expected = (base * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            actual = contrib.importo_dipendente
            diff = abs(expected - actual)
            results.append(ValidationResult(
                nome=f"Contributo {rule.name}",
                anno=ced.anno, mese=ced.mese,
                mese_label=ced.mese_retribuzione,
                status="PASS" if diff <= rule.tolerance else "FAIL",
                atteso=str(expected),
                effettivo=str(actual),
                differenza=str(diff),
                tolleranza=str(rule.tolerance),
                formula=f"{base} * {rate} = {expected}",
            ))


def _validate_legacy(results, ced, contrib_map, imp_arrot):
    """Legacy hardcoded validation for when no CCNL config is available."""
    _check_contrib(results, ced, contrib_map, "IVS",
                   imp_arrot, Decimal("0.0919"), Decimal("0.02"))
    _check_contrib(results, ced, contrib_map, "CIGS",
                   imp_arrot, Decimal("0.003"), Decimal("0.02"))
    _check_contrib(results, ced, contrib_map, "FIS",
                   imp_arrot, Decimal("0.0026667"), Decimal("0.02"))

    est = contrib_map.get("EST")
    if est:
        expected = Decimal("2.00")
        diff = abs(est.importo_dipendente - expected)
        results.append(ValidationResult(
            nome="Contributo EST",
            anno=ced.anno, mese=ced.mese,
            mese_label=ced.mese_retribuzione,
            status="PASS" if diff <= Decimal("0.01") else "FAIL",
            atteso=str(expected),
            effettivo=str(est.importo_dipendente),
            differenza=str(diff),
            tolleranza="0.01",
            formula="fisso 2,00",
        ))

    fonte_base = contrib_map.get("FONTE_BASE")
    if fonte_base and fonte_base.imponibile > ZERO:
        _check_contrib(results, ced, contrib_map, "FONTE_BASE",
                       fonte_base.imponibile, Decimal("0.0055"), Decimal("0.02"),
                       label="FON.TE base")
        fonte_vol = contrib_map.get("FONTE_VOL")
        if fonte_vol and fonte_vol.imponibile > ZERO:
            _check_contrib(results, ced, contrib_map, "FONTE_VOL",
                           fonte_vol.imponibile, Decimal("0.0045"), Decimal("0.02"),
                           label="FON.TE vol.")


def _find_contrib(contrib_map, name, aliases=None):
    """Find a contribution by name or aliases."""
    if name in contrib_map:
        return contrib_map[name]
    for alias in (aliases or []):
        if alias in contrib_map:
            return contrib_map[alias]
    return None


def _check_contrib(results: list, ced: Cedolino, contrib_map: dict,
                   key: str, imponibile: Decimal, rate: Decimal,
                   tolerance: Decimal, label: str = ""):
    """Check a single contribution calculation."""
    contrib = contrib_map.get(key)
    if not contrib:
        return

    expected = (imponibile * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    actual = contrib.importo_dipendente
    diff = abs(expected - actual)

    name = label or key
    status = "PASS" if diff <= tolerance else "FAIL"

    results.append(ValidationResult(
        nome=f"Contributo {name}",
        anno=ced.anno, mese=ced.mese,
        mese_label=ced.mese_retribuzione,
        status=status,
        atteso=str(expected),
        effettivo=str(actual),
        differenza=str(diff),
        tolleranza=str(tolerance),
        formula=f"{imponibile} * {rate} = {expected}",
    ))
