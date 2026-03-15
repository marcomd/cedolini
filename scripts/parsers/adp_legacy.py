"""Parser per cedolini ADP legacy."""

import re
import pdfplumber
from decimal import Decimal
from scripts.models import (
    Cedolino, VoceItem, ContributionItem, INPSSection, IRPEFSection,
    TFRSection, RateiRow, TotaliSection, parse_italian_decimal, parse_periodo, ZERO,
    MESI_IT,
)
from scripts.parsers.base import register_parser

RE_NUM = re.compile(r'-?\d[\d.]*,\d+')
# Italian codice fiscale: 6 letters + 2 digits + 1 letter + 2 digits + 1 letter + 3 digits + 1 letter
RE_CF = re.compile(r'[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]')


def _pdn(s: str) -> Decimal:
    return parse_italian_decimal(s)


def detect_adp_legacy(pdf_path: str, full_text: str) -> bool:
    """Detect ADP legacy format."""
    if "www.it-adp.com" in full_text:
        return True
    # Backup: "CEDOLINO" header + 4-digit voce codes like 1000
    if "CEDOLINO" in full_text and re.search(r'\b1000\b.*RETRIBUZIONE BASE', full_text):
        return True
    return False


register_parser("adp_legacy", detect_adp_legacy, lambda path: parse_adp_legacy(path))


def parse_adp_legacy(pdf_path: str) -> list[Cedolino]:
    """Parse an ADP legacy multi-cedolino PDF.

    Each cedolino spans 2 pages:
    - Odd page (1, 3, 5...): voci, contributions, totals
    - Even page (2, 4, 6...): fiscal/previdenziale/TFR info
    Returns a list of Cedolino objects.
    """
    with pdfplumber.open(pdf_path) as pdf:
        num_pages = len(pdf.pages)
        page_texts = []
        for page in pdf.pages:
            text = page.extract_text() or ""
            page_texts.append(text)

    cedolini = []
    # Process in pairs
    for i in range(0, num_pages, 2):
        page1_text = page_texts[i] if i < num_pages else ""
        page2_text = page_texts[i + 1] if i + 1 < num_pages else ""

        if "CEDOLINO" not in page1_text:
            continue

        ced = Cedolino(file_path=pdf_path, formato="adp_legacy", num_pagine=2)
        lines1 = page1_text.split("\n")
        lines2 = page2_text.split("\n")

        _parse_header(ced, lines1)
        _parse_voci(ced, lines1)
        _parse_totali(ced, lines1)
        _parse_fiscal(ced, lines2)
        _parse_previdenziale(ced, lines2)
        _parse_tfr(ced, lines2)
        _parse_ratei(ced, lines2)
        _parse_ferie_page2(ced, lines2)

        cedolini.append(ced)

    # Infer missing years from other cedolini in the same PDF
    known_years = [c.anno for c in cedolini if c.anno > 0]
    if known_years:
        infer_year = max(set(known_years), key=known_years.count)
        for ced in cedolini:
            if ced.anno == 0:
                ced.anno = infer_year
                if ced.mese_retribuzione and str(infer_year) not in ced.mese_retribuzione:
                    ced.mese_retribuzione = f"{ced.mese_retribuzione} {infer_year}"

    return cedolini


def _parse_header(ced: Cedolino, lines: list[str]):
    """Parse header from page 1."""
    for i, line in enumerate(lines):
        # Period line: "P E R I O D O GENNAIO 2007 ** EURO **"
        m = re.search(r'P\s*E\s*R\s*I\s*O\s*D\s*O\s+(\w+(?:\s+\d{4})?)', line)
        if m:
            periodo_raw = m.group(1).strip()
            # Handle text after period name (e.g. "EURO")
            if "EURO" in periodo_raw:
                periodo_raw = periodo_raw.split("**")[0].strip()
            ced.mese_retribuzione = periodo_raw
            ced.anno, ced.mese, ced.is_tredicesima = parse_periodo(periodo_raw)
            # Try to find year from the line if not in periodo text
            if ced.anno == 0:
                year_m = re.search(r'\b(19\d{2}|20\d{2})\b', line)
                if year_m:
                    ced.anno = int(year_m.group(1))
            continue

        # Company: extract from "D I T T A" marker
        # Line format: "COMPANY_NAME D I T T A COMPANY_NAME N .D IT T A NNN"
        if "D I T T A" in line:
            idx = line.index("D I T T A")
            company = line[:idx].strip()
            if company:
                ced.ragione_sociale = company
            continue

        # POS INPS
        if "P O S . IN P S" in line:
            m = re.search(r'P\s*O\s*S\s*\.\s*IN\s*P\s*S\s+(\d+)', line)
            if m:
                ced.pos_inps = m.group(1)
            continue

        # POS INAIL
        if "P O S . IN A I L" in line:
            m = re.search(r'(\d+/\d+)', line)
            if m:
                ced.pos_inail = m.group(1)
            continue

        # Employee: line with "COD.FISC" label + codice fiscale + "S E SS O" + name
        if "COD.FISC" in line:
            cf = RE_CF.search(line)
            if cf:
                ced.codice_fiscale = cf.group()
                # Name follows "S E SS O X" pattern (gender indicator)
                m = re.search(r'S\s*E\s*SS\s*O\s+\w\s+(.+)', line)
                if m:
                    ced.cognome_nome = m.group(1).strip()
            continue

        # Matricola (spaced-out label)
        if "M A T R IC O L A" in line:
            m = re.search(r'M\s*A\s*T\s*R\s*IC\s*O\s*L\s*A\s+(\d+)', line)
            if m:
                ced.cod_dipendente = m.group(1)
            continue

        # Assunzione
        if "ASSUNZIONE" in line:
            m = re.search(r'ASSUNZIONE\s+(\d{2}/\d{2}/\d{4})', line)
            if m:
                ced.data_assunzione = m.group(1)
            continue

        # Level
        if "LIVELLO" in line and "CATEGORIA" in line:
            m = re.search(r'LIVELLO\s+(\d+)', line)
            if m:
                ced.livello = m.group(1)
            continue


def _parse_voci(ced: Cedolino, lines: list[str]):
    """Parse voci and contributions from page 1."""
    in_voci = False
    for line in lines:
        stripped = line.strip()

        # Start after "RF" line
        if stripped == "RF":
            in_voci = True
            continue

        if "Totali" in stripped and RE_NUM.search(stripped):
            in_voci = False
            continue

        if not in_voci:
            continue

        if not stripped:
            continue

        # Voce line: "1000 RETRIBUZIONE BASE 1.639,07"
        m = re.match(r'^(\d+)\s+(.+)', stripped)
        if not m:
            continue

        code = m.group(1)
        rest = m.group(2)

        voce = VoceItem()
        voce.codice = code

        # Parse flags
        if rest.startswith("++"):
            rest = rest[2:].strip()
            voce.flag_c = voce.flag_i = voce.flag_t = voce.flag_n = True
        elif rest.startswith("+"):
            rest = rest[1:].strip()
            voce.flag_n = True

        nums = RE_NUM.findall(rest)
        vals = [_pdn(n) for n in nums]

        # Description is text before first number
        desc = re.split(r'\s+\d', rest)[0].strip() if nums else rest.strip()
        voce.descrizione = desc

        # Known contribution codes - extract as ContributionItem
        if code == "5154":
            # INPS IVS
            contrib = ContributionItem(descrizione="IVS")
            if len(vals) >= 3:
                contrib.imponibile = vals[0]
                contrib.percentuale = vals[1]
                contrib.importo_dipendente = vals[2]
            elif len(vals) >= 2:
                contrib.imponibile = vals[0]
                contrib.importo_dipendente = vals[1]
            ced.contributi.append(contrib)
            ced.inps.imponibile_contrib_arrot_mese = contrib.imponibile
            continue

        if code == "5483":
            # Fondo solidarieta'
            contrib = ContributionItem(descrizione="FDO_SOLID")
            if len(vals) >= 3:
                contrib.imponibile = vals[0]
                contrib.percentuale = vals[1]
                contrib.importo_dipendente = vals[2]
            ced.contributi.append(contrib)
            continue

        if code == "5244":
            # Contributo aggiuntivo INPS 1%
            contrib = ContributionItem(descrizione="ADD_IVS")
            if len(vals) >= 3:
                contrib.imponibile = vals[0]
                contrib.percentuale = vals[1]
                contrib.importo_dipendente = vals[2]
            ced.contributi.append(contrib)
            continue

        if code == "5248":
            # Conguaglio contributo aggiuntivo 1%
            contrib = ContributionItem(descrizione="ADD_IVS_CNG")
            if len(vals) >= 3:
                contrib.imponibile = vals[0]
                contrib.percentuale = vals[1]
                contrib.importo_dipendente = vals[2]
            ced.contributi.append(contrib)
            continue

        if code == "9753":
            # Tredicesima INPS
            contrib = ContributionItem(descrizione="IVS")
            if len(vals) >= 3:
                contrib.imponibile = vals[0]
                contrib.percentuale = vals[1]
                contrib.importo_dipendente = vals[2]
            ced.contributi.append(contrib)
            ced.inps.imponibile_contrib_arrot_mese = contrib.imponibile
            continue

        if code == "7833":
            # IRPEF netta mese
            if vals:
                ced.irpef.irpef_netta_mese = vals[0]
                ced.irpef.irpef_piu_imp_sost = vals[0]
            continue

        if code == "9803":
            # Tredicesima IRPEF
            if vals:
                ced.irpef.irpef_netta_mese = vals[0]
                ced.irpef.irpef_piu_imp_sost = vals[0]
            continue

        if code == "7139":
            # TFR quota
            if vals:
                ced.tfr.tfr_mese = vals[0]
            continue

        if code == "7855":
            # Addizionale comunale
            if vals:
                ced.addizionale_comunale_saldo += vals[-1]
            continue

        if code == "7858":
            # Addizionale regionale
            if vals:
                ced.addizionale_regionale += vals[-1]
            continue

        if code in ("8853", "8833"):
            # Arrotondamento
            if code == "8833" and vals:
                ced.totali.arrotondamento_precedente = vals[0]
            elif code == "8853" and vals:
                ced.totali.arrotondamento_attuale = vals[0]
            continue

        if code == "8503":
            # Acconto (anticipo on tredicesima)
            continue

        if code == "8446":
            # Sindacale
            if vals:
                voce.trattenute = vals[-1]
            ced.voci.append(voce)
            continue

        # Extract paga_base from voce 1000
        if code == "1000" and vals:
            ced.paga_base = vals[0]

        # Regular voci
        if len(vals) >= 3:
            voce.quantita = vals[0]
            voce.base = vals[1]
            voce.competenze = vals[2]
        elif len(vals) == 2:
            voce.quantita = vals[0]
            voce.competenze = vals[1]
        elif len(vals) == 1:
            voce.competenze = vals[0]

        ced.voci.append(voce)


def _parse_totali(ced: Cedolino, lines: list[str]):
    """Parse totals from page 1."""
    for line in lines:
        stripped = line.strip()

        # "Totali 2.481,48 766,48"
        if stripped.startswith("Totali"):
            nums = RE_NUM.findall(stripped)
            vals = [_pdn(n) for n in nums]
            if len(vals) >= 2:
                ced.totali.totale_competenze = vals[0]
                ced.totali.totale_trattenute = vals[1]
            continue

        # "Netto a Pagare EURO 1.715,00"
        m = re.search(r'Netto a Pagare\s+EURO\s+([\d.,]+)', stripped)
        if m:
            ced.totali.netto_in_busta = _pdn(m.group(1))
            continue

    # Compute arrotondamento: netto = comp - tratt + arrot
    if ced.totali.netto_in_busta > ZERO and ced.totali.totale_competenze > ZERO:
        ced.totali.arrotondamento = (
            ced.totali.netto_in_busta - ced.totali.totale_competenze + ced.totali.totale_trattenute
        )


def _parse_fiscal(ced: Cedolino, lines: list[str]):
    """Parse fiscal info from page 2."""
    for line in lines:
        stripped = line.strip()

        # "REDDITO FISC. MESE 2.277,57 ..."
        if "REDDITO FISC. MESE" in stripped:
            m = re.search(r'REDDITO FISC\. MESE\s+([\d.,]+)', stripped)
            if m:
                ced.irpef.imponibile_fiscale_mese = _pdn(m.group(1))
            m = re.search(r'REDDITO FISC\.PROG\.\s+([\d.,]+)', stripped)
            if m:
                ced.irpef.imponibile_fiscale_anno = _pdn(m.group(1))
                ced.progressivo_imp_irpef = _pdn(m.group(1))
            continue

        # "IRPEF LORDA MESE 602,62"
        if "IRPEF LORDA MESE" in stripped:
            m = re.search(r'IRPEF LORDA MESE\s+([\d.,]+)', stripped)
            if m:
                ced.irpef.irpef_lorda_mese = _pdn(m.group(1))
            continue

        # "IRPEF ANNUA DOVUTA 10.356,91"
        if "IRPEF ANNUA DOVUTA" in stripped:
            m = re.search(r'IRPEF ANNUA DOVUTA\s+([\d.,]+)', stripped)
            if m:
                ced.irpef.irpef_lorda_anno = _pdn(m.group(1))
            continue

        # Detrazioni
        if "GG ALTRE DET.SPET." in stripped:
            m = re.search(r'GG ALTRE DET\.SPET\.\s+(\d+)', stripped)
            if m:
                ced.irpef.gg_detrazione_anno = int(m.group(1))
            continue

        if "GG ALTRE DETRAZ." in stripped:
            m = re.search(r'GG ALTRE DETRAZ\.\s+(\d+)', stripped)
            if m:
                ced.irpef.gg_detrazione = int(m.group(1))
            continue

        if "ALTRE DETRAZIONI" in stripped and "ALTRE DETRAZ.SPET." not in stripped:
            nums = RE_NUM.findall(stripped)
            if nums:
                val = _pdn(nums[-1])
                if "-" in stripped.split("DETRAZIONI")[-1]:
                    val = -abs(val)
                ced.irpef.detrazione_lavoro_dip = abs(val)
            continue

        # "IRPEF PAGATA 532,58" (progressive)
        if "IRPEF PAGATA" in stripped:
            m = re.search(r'IRPEF PAGATA\s+([\d.,]+)', stripped)
            if m:
                ced.irpef.irpef_trattenuta_anno = _pdn(m.group(1))
                ced.progressivo_irpef_pagata = _pdn(m.group(1))
            continue

        # "CONGUAGLIO 1.378,56"
        if "CONGUAGLIO" in stripped and "CREDITO" not in stripped and "DEBITO" not in stripped:
            m = re.search(r'CONGUAGLIO\s+([\d.,]+)', stripped)
            if m:
                ced.irpef.irpef_conguaglio = _pdn(m.group(1))
            continue

        # "IRPEF NETTA MESE 532,58"
        if "IRPEF NETTA MESE" in stripped:
            # Already set from voce 7833
            continue

        # "TOT.DETRAZ.SPET. 70,04"
        if "TOT.DETRAZ.SPET." in stripped:
            m = re.search(r'TOT\.DETRAZ\.SPET\.\s+([\d.,]+)', stripped)
            if m:
                val = _pdn(m.group(1))
                if val > ced.irpef.detrazione_lavoro_dip:
                    ced.irpef.detrazione_lavoro_dip = val
            continue

        # "DETRAZ.APPLIC. 605,94" (December conguaglio)
        if "DETRAZ.APPLIC." in stripped:
            m = re.search(r'DETRAZ\.APPLIC\.\s+([\d.,]+)', stripped)
            if m:
                ced.irpef.detrazione_lavoro_dip_anno = _pdn(m.group(1))
            continue


def _parse_previdenziale(ced: Cedolino, lines: list[str]):
    """Parse previdenziale section from page 2."""
    for line in lines:
        stripped = line.strip()

        # "IMP.PREV. 2.511,00 IMP.PREV. 2.511,00"
        if "IMP.PREV." in stripped:
            matches = re.findall(r'IMP\.PREV\.\s+([\d.,]+)', stripped)
            if len(matches) >= 2:
                ced.inps.imponibile_contributivo_mese = _pdn(matches[0])
                ced.inps.imponibile_contributivo_anno = _pdn(matches[1])
            elif len(matches) >= 1:
                ced.inps.imponibile_contributivo_mese = _pdn(matches[0])
            continue

        # "GIORNI INPS 25"
        if "GIORNI INPS" in stripped:
            m = re.search(r'GIORNI INPS\s+(\d+)', stripped)
            if m:
                ced.inps.gg_retribuiti = int(m.group(1))
                ced.inps.gg_lavorati = int(m.group(1))
            continue

        # "SETTIMANE INPS 4 ORE RETRIBUITE 232,00"
        if "SETTIMANE INPS" in stripped:
            m = re.search(r'SETTIMANE INPS\s+(\d+)', stripped)
            if m:
                ced.inps.settimane = int(m.group(1))
            m = re.search(r'ORE RETRIBUITE\s+([\d.,]+)', stripped)
            if m:
                ced.inps.ore_lavorate = _pdn(m.group(1))
            continue

        # "CTR.INPS DIP.CUD 230,76 CTR.INPS DIP.CUD 230,76"
        if "CTR.INPS DIP.CUD" in stripped:
            matches = re.findall(r'CTR\.INPS DIP\.CUD\s+([\d.,]+)', stripped)
            if len(matches) >= 2:
                ced.inps.totale_contributi = _pdn(matches[0])
                ced.inps.contributi_anno = _pdn(matches[1])
            elif len(matches) >= 1:
                ced.inps.totale_contributi = _pdn(matches[0])
            continue

    # Set imponibile_contrib_arrot_mese from IMP.PREV if not already set from contributions
    if ced.inps.imponibile_contrib_arrot_mese == ZERO and ced.inps.imponibile_contributivo_mese > ZERO:
        ced.inps.imponibile_contrib_arrot_mese = ced.inps.imponibile_contributivo_mese


def _parse_tfr(ced: Cedolino, lines: list[str]):
    """Parse TFR info from page 2."""
    for line in lines:
        stripped = line.strip()

        # "RETR.UTILE TFR 34.030,53"
        if "RETR.UTILE TFR" in stripped:
            m = re.search(r'RETR\.UTILE TFR\s+([\d.,]+)', stripped)
            if m:
                ced.tfr.retribuzione_utile_tfr = _pdn(m.group(1))
            continue

        # "TFR ANNUO 712,48"
        if "TFR ANNUO" in stripped:
            m = re.search(r'TFR ANNUO\s+([\d.,]+)', stripped)
            if m:
                ced.tfr.tfr_annuo = _pdn(m.group(1))
            continue

        # "CONTR.FONDO PENS. 177,05"
        if "CONTR.FONDO PENS." in stripped:
            m = re.search(r'CONTR\.FONDO PENS\.\s+([\d.,]+)', stripped)
            if m:
                ced.tfr.contributo_agg_tfr = _pdn(m.group(1))
            continue

        # "QUOTA TFR 182,62" in Fondi Pensione section
        if "QUOTA TFR" in stripped:
            matches = re.findall(r'QUOTA TFR\s+([\d.,]+)', stripped)
            if matches and ced.tfr.tfr_mese == ZERO:
                ced.tfr.tfr_mese = _pdn(matches[0])
            continue

        # "ALIQUOTA STIMATA 24,92"
        if "ALIQUOTA STIMATA" in stripped:
            m = re.search(r'ALIQUOTA STIMATA\s+([\d.,]+)', stripped)
            if m:
                ced.tfr.perc_irpef = _pdn(m.group(1))
            continue


def _parse_ratei(ced: Cedolino, lines: list[str]):
    """Parse ratei (placeholder - ADP format stores ferie in a different section)."""
    pass


def _parse_ferie_page2(ced: Cedolino, lines: list[str]):
    """Parse ferie from page 2.

    Preceded by header "Anno Prec. Spettanti Maturati Goduti Saldo Sp. Saldo Mat."
    """
    for i, line in enumerate(lines):
        if "FERIE" in line and i > 0 and ("Anno Prec" in lines[i - 1] or "Saldo" in lines[i - 1]):
            nums = RE_NUM.findall(line)
            vals = [_pdn(n) for n in nums]

            if not vals:
                continue

            row = RateiRow(tipo="Ferie", unita="GG")

            # Column mapping depends on count:
            # 4 values: spettanti(AP), maturato, goduto, saldo
            # 3 values: spettanti(AP), maturato, saldo (no goduto)
            # 2 values: maturato, saldo
            if len(vals) == 4:
                row.residuo_ap = vals[0]
                row.maturato = vals[1]
                row.goduto = vals[2]
                row.saldo = vals[3]
            elif len(vals) == 3:
                row.residuo_ap = vals[0]
                row.maturato = vals[1]
                row.saldo = vals[2]
            elif len(vals) == 2:
                row.maturato = vals[0]
                row.saldo = vals[1]

            ced.ratei.append(row)
            break
