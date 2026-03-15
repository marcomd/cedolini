"""Cross-check annuale cedolini vs CUD (Certificazione Unica)."""

from decimal import Decimal
from scripts.models import Cedolino, CertificazioneUnica, ValidationResult, ZERO


def validate_cud(cedolini: list[Cedolino], cuds: list[CertificazioneUnica]) -> list[ValidationResult]:
    """Cross-check annual totals from cedolini against CUD data."""
    results = []

    for cu in cuds:
        anno = cu.anno_riferimento
        if not anno:
            continue

        # Get all cedolini for this year
        year_ceds = [c for c in cedolini if c.anno == anno]
        if not year_ceds:
            results.append(ValidationResult(
                nome=f"CUD {anno}: cedolini mancanti",
                anno=anno, mese=0,
                mese_label=f"CU{cu.anno_cu} vs {anno}",
                status="WARNING",
                note=f"Nessun cedolino trovato per anno {anno}",
            ))
            continue

        # Sum monthly imponibili IRPEF
        if cu.reddito_lavoro_dipendente > ZERO:
            # Use December conguaglio value if available
            dec = next((c for c in year_ceds if c.mese == 12 and c.irpef.imponibile_fiscale_anno > ZERO), None)
            if dec:
                imp_irpef_totale = dec.irpef.imponibile_fiscale_anno
            else:
                imp_irpef_totale = sum(c.irpef.imponibile_fiscale_mese for c in year_ceds)

            diff = abs(imp_irpef_totale - cu.reddito_lavoro_dipendente)
            results.append(ValidationResult(
                nome="CUD: Reddito lavoro dipendente",
                anno=anno, mese=0,
                mese_label=f"CU{cu.anno_cu} vs {anno}",
                status="PASS" if diff <= Decimal("1.00") else "FAIL",
                atteso=str(cu.reddito_lavoro_dipendente),
                effettivo=str(imp_irpef_totale),
                differenza=str(diff),
                tolleranza="1.00",
                formula="Somma imponibili IRPEF mensili vs CUD punto 1",
            ))

        # Sum ritenute IRPEF
        if cu.ritenute_irpef > ZERO:
            dec = next((c for c in year_ceds if c.mese == 12 and c.irpef.irpef_netta_anno > ZERO), None)
            if dec:
                # irpef_netta_anno = irpef_trattenuta_anno + conguaglio
                irpef_totale = dec.irpef.irpef_netta_anno
            else:
                irpef_totale = sum(c.irpef.irpef_piu_imp_sost for c in year_ceds)

            diff = abs(irpef_totale - cu.ritenute_irpef)
            results.append(ValidationResult(
                nome="CUD: Ritenute IRPEF",
                anno=anno, mese=0,
                mese_label=f"CU{cu.anno_cu} vs {anno}",
                status="PASS" if diff <= Decimal("1.00") else "FAIL",
                atteso=str(cu.ritenute_irpef),
                effettivo=str(irpef_totale),
                differenza=str(diff),
                tolleranza="1.00",
                formula="Somma ritenute IRPEF mensili vs CUD punto 21",
            ))

        # Imponibile previdenziale (INPS)
        if cu.imponibile_previdenziale > ZERO:
            dec = next((c for c in year_ceds if c.mese == 12 and c.inps.imponibile_contributivo_anno > ZERO), None)
            if dec:
                imp_inps = dec.inps.imponibile_contributivo_anno
            else:
                imp_inps = sum(c.inps.imponibile_contrib_arrot_mese for c in year_ceds)

            diff = abs(imp_inps - cu.imponibile_previdenziale)
            results.append(ValidationResult(
                nome="CUD: Imponibile previdenziale",
                anno=anno, mese=0,
                mese_label=f"CU{cu.anno_cu} vs {anno}",
                status="PASS" if diff <= Decimal("1.00") else "FAIL",
                atteso=str(cu.imponibile_previdenziale),
                effettivo=str(imp_inps),
                differenza=str(diff),
                tolleranza="1.00",
                formula="Somma imponibili INPS vs CUD sez. previdenziale",
            ))

        # Contributi lavoratore
        if cu.contributi_lavoratore > ZERO:
            dec = next((c for c in year_ceds if c.mese == 12 and c.inps.contributi_anno > ZERO), None)
            if dec:
                contr = dec.inps.contributi_anno
            else:
                contr = sum(c.inps.totale_contributi for c in year_ceds)

            diff = abs(contr - cu.contributi_lavoratore)
            results.append(ValidationResult(
                nome="CUD: Contributi lavoratore",
                anno=anno, mese=0,
                mese_label=f"CU{cu.anno_cu} vs {anno}",
                status="PASS" if diff <= Decimal("5.00") else "FAIL",
                atteso=str(cu.contributi_lavoratore),
                effettivo=str(contr),
                differenza=str(diff),
                tolleranza="5.00",
                formula="Somma contributi c/dip vs CUD sez. previdenziale",
            ))

        # Addizionale regionale
        if cu.addizionale_regionale > ZERO:
            # Addizionale regionale is settled in December
            dec = next((c for c in year_ceds if c.mese == 12), None)
            if dec:
                add_reg = dec.addizionale_regionale
                # Also check if there are voce 823 amounts
                for v in dec.voci:
                    if v.codice in ("823",) and "Regionale" in v.descrizione:
                        add_reg = max(add_reg, v.trattenute)

                if add_reg > ZERO:
                    diff = abs(add_reg - cu.addizionale_regionale)
                    results.append(ValidationResult(
                        nome="CUD: Addizionale regionale",
                        anno=anno, mese=0,
                        mese_label=f"CU{cu.anno_cu} vs {anno}",
                        status="PASS" if diff <= Decimal("1.00") else "WARNING",
                        atteso=str(cu.addizionale_regionale),
                        effettivo=str(add_reg),
                        differenza=str(diff),
                        tolleranza="1.00",
                        formula="Addizionale regionale da conguaglio vs CUD punto 22",
                    ))

        # Previdenza complementare
        if cu.previdenza_complementare > ZERO:
            # CUD punto 412 includes complementary pension contributions.
            # For commercio CCNL: FON.TE base + FON.TE vol + EST + contributo agg TFR
            # For other CCNL: collect all pension-related contributions
            fonte_total = ZERO
            for c in year_ceds:
                for ct in c.contributi:
                    if ct.descrizione in ("FONTE_BASE", "FONTE_VOL"):
                        # c/ditta is approx equal to c/dip
                        fonte_total += ct.importo_dipendente * 2
                    elif ct.descrizione == "EST":
                        fonte_total += ct.importo_dipendente
                # Add contributo aggiuntivo TFR (0.50%)
                if c.tfr.contributo_agg_tfr > ZERO:
                    fonte_total += c.tfr.contributo_agg_tfr

            if fonte_total > ZERO:
                diff = abs(fonte_total - cu.previdenza_complementare)
                results.append(ValidationResult(
                    nome="CUD: Previdenza complementare",
                    anno=anno, mese=0,
                    mese_label=f"CU{cu.anno_cu} vs {anno}",
                    status="PASS" if diff <= Decimal("10.00") else "FAIL",
                    atteso=str(cu.previdenza_complementare),
                    effettivo=str(fonte_total),
                    differenza=str(diff),
                    tolleranza="10.00",
                    formula="Somma FON.TE c/dip*2 + EST + contr.agg.TFR vs CUD punto 412",
                ))

    return results
