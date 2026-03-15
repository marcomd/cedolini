"""Parser per cedolini Hornet/HCM."""

import re
import pdfplumber
from decimal import Decimal
from scripts.models import (
    Cedolino, VoceItem, ContributionItem, INPSSection, IRPEFSection,
    TFRSection, RateiRow, TotaliSection, parse_italian_decimal, parse_periodo, ZERO
)
from scripts.parsers.base import register_parser

RE_NUM = re.compile(r'-?\d[\d.]*,\d+')
# Italian codice fiscale: 6 letters + 2 digits + 1 letter + 2 digits + 1 letter + 3 digits + 1 letter
RE_CF = re.compile(r'[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]')


def _pdn(s: str) -> Decimal:
    return parse_italian_decimal(s)


def _is_spaced_out(text: str) -> bool:
    """Check if text is spaced out (e.g., 'A B C D E F G')."""
    parts = text.strip().split()
    if len(parts) < 4:
        return False
    single_chars = sum(1 for p in parts if len(p) <= 2)
    return single_chars > len(parts) * 0.5


def _collapse_spaced(text: str) -> str:
    """Collapse spaced-out text: 'A C M E  S P A' -> 'ACME SPA'.

    Groups single characters into words, preserving multi-char tokens.
    Then separates known Italian business form suffixes (SPA, SRL, etc.).
    """
    parts = text.strip().split()
    result = []
    current_word = []
    for p in parts:
        if len(p) <= 2 and p.isalpha():
            current_word.append(p)
        else:
            if current_word:
                result.append("".join(current_word))
                current_word = []
            result.append(p)
    if current_word:
        result.append("".join(current_word))
    name = " ".join(result)

    # Separate common business form suffixes at the end
    upper = name.upper()
    for suffix in ("SPA", "SRL", "SRLS", "SAS", "SNC", "SCRL", "SAP", "SCARL"):
        if upper.endswith(suffix) and len(name) > len(suffix) + 1:
            name = name[:-len(suffix)].rstrip() + " " + name[-len(suffix):]
            break

    return name


def detect_hornet(pdf_path: str, full_text: str) -> bool:
    """Detect Hornet/HCM format by HRZ_MODEL marker."""
    return "HRZ_MODEL" in full_text


register_parser("hornet", detect_hornet, lambda path: parse_hornet(path))


def parse_hornet(pdf_path: str) -> Cedolino:
    """Parse a Hornet/HCM cedolino PDF."""
    ced = Cedolino(file_path=pdf_path, formato="hornet")

    with pdfplumber.open(pdf_path) as pdf:
        ced.num_pagine = len(pdf.pages)
        all_lines = []
        for page in pdf.pages:
            text = page.extract_text() or ""
            all_lines.extend(text.split("\n"))

    _parse_header(ced, all_lines)
    _parse_salary(ced, all_lines)
    _parse_voci(ced, all_lines)
    _parse_contributions(ced, all_lines)
    _parse_addizionali(ced, all_lines)
    _parse_ratei(ced, all_lines)
    _parse_fiscal(ced, all_lines)
    _parse_totali(ced, all_lines)

    return ced


def _parse_header(ced: Cedolino, lines: list[str]):
    """Parse header using labeled header rows as anchors.

    The Hornet format has header-label rows followed by value rows:
    - "DENOMINAZIONE" header -> company name (spaced out) on next line
    - "PERIODO DI RETRIBUZIONE" -> period on next line
    - "POSIZIONE PREVIDENZIALE" header -> INPS/INAIL on next line
    - "CODICE DIPENDENTE" header -> employee data on next line
    - "MATRICOLA" header -> dates/qualifica on next line
    - "FERIE SPETTANTI" header -> ferie values on next line
    """
    for i, line in enumerate(lines):
        # Use collapsed line to match garbled headers
        collapsed = line.replace(" ", "")

        # Company: header row contains "DENOMINAZIONE" (garbled as "DENOMINAZION")
        if "DENOMINAZION" in collapsed and not ced.ragione_sociale:
            if i + 1 < len(lines) and _is_spaced_out(lines[i + 1]):
                name = _collapse_spaced(lines[i + 1])
                # Strip leading digits (section number, e.g., "2 COMPANY" -> "COMPANY")
                name = re.sub(r'^\d+\s+', '', name)
                if len(name) > 3:
                    ced.ragione_sociale = name
            continue

        # Period
        if "PERIODO DI RETRIBUZIONE" in line:
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                m = re.search(r'(Gennaio|Febbraio|Marzo|Aprile|Maggio|Giugno|'
                              r'Luglio|Agosto|Settembre|Ottobre|Novembre|Dicembre|'
                              r'TREDICESIMA)\s+(\d{4})', next_line, re.IGNORECASE)
                if m:
                    periodo = f"{m.group(1)} {m.group(2)}"
                    ced.mese_retribuzione = periodo
                    ced.anno, ced.mese, ced.is_tredicesima = parse_periodo(periodo)
            continue

        # POS INPS/INAIL: header row contains "POSIZIONE PREVIDENZIALE" (garbled)
        if "PREVIDENZIAL" in collapsed and not ced.pos_inps:
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                m = re.search(r'(\d{10,})\s+(\d+)\s+(\d+/\d+)', next_line)
                if m:
                    ced.pos_inps = m.group(1) + m.group(2)
                    ced.pos_inail = m.group(3)
            continue

        # Employee: header row "CODICE DIPENDENTE ... CODICE FISCALE ... LIVELLO"
        if "CODICE DIPENDENTE" in line and not ced.codice_fiscale:
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                cf = RE_CF.search(next_line)
                if cf:
                    ced.codice_fiscale = cf.group()
                    # Before CF: "cod_dip NAME"
                    before_cf = next_line[:cf.start()].strip()
                    m = re.match(r'(\d+)\s+(.*)', before_cf)
                    if m:
                        ced.cod_dipendente = m.group(1)
                        ced.cognome_nome = m.group(2).strip()
                    # After CF: "livello cost_center"
                    after_cf = next_line[cf.end():].strip()
                    m2 = re.match(r'(\d+)', after_cf)
                    if m2:
                        ced.livello = m2.group(1)
            continue

        # Matricola, dates, qualifica: header row "MATRICOLA DATA NASCITA DATA ASSUNZIONE..."
        if "MATRICOLA" in line and "DATA" in line and not ced.data_assunzione:
            if i + 1 < len(lines):
                m = re.match(r'\s*(\d+)\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+(\S+)',
                             lines[i + 1])
                if m:
                    ced.data_assunzione = m.group(3)
                    ced.qualifica = m.group(4)
            continue

        # FERIE/hours/days info
        if "FERIE SPETTANTI" in line:
            if i + 1 < len(lines):
                nums = lines[i + 1].strip().split()
                if len(nums) >= 5:
                    ced.inps.gg_retribuiti = int(nums[-3]) if nums[-3].isdigit() else 0
                    ced.inps.gg_lavorati = int(nums[-3]) if nums[-3].isdigit() else 0
                    ced.inps.settimane = int(nums[-1]) if nums[-1].isdigit() else 0
            continue


def _parse_salary(ced: Cedolino, lines: list[str]):
    """Parse salary components."""
    for i, line in enumerate(lines):
        if "RETRIBUZIONE BASE" in line:
            nums = RE_NUM.findall(line)
            vals = [_pdn(n) for n in nums]
            if len(vals) >= 1:
                ced.paga_base = vals[0]
            if len(vals) >= 2:
                ced.superminimo = vals[1]
            continue

        if line.strip() == "TOTALE":
            if i + 1 < len(lines):
                nums = RE_NUM.findall(lines[i + 1])
                if nums:
                    ced.retribuzione_mensile = _pdn(nums[0])
            continue


def _parse_voci(ced: Cedolino, lines: list[str]):
    """Parse voci (line items)."""
    in_voci = False
    for line in lines:
        stripped = line.strip()

        # Start of voci section
        if "--- PF|" in stripped:
            in_voci = True
            continue

        # End markers
        if in_voci and ("------" in stripped and "------" in stripped and "Imponibili" not in stripped
                        and len(stripped) < 40):
            in_voci = False
            continue

        if not in_voci:
            continue

        if not stripped or stripped.startswith("---"):
            continue

        # Parse voce line: "AA245 **|Retrib. ordinaria 30,000 118,70267 3561,08"
        m = re.match(r'^(\w+)\s*(\**)?\|(.+)', stripped)
        if not m:
            continue

        voce = VoceItem()
        voce.codice = m.group(1)
        flags = m.group(2) or ""
        rest = m.group(3).strip()

        # Flags
        if "**" in flags:
            voce.flag_c = voce.flag_i = True
        elif "*" in flags:
            voce.flag_c = True

        # Extract numbers from the end
        nums = RE_NUM.findall(rest)
        vals = [_pdn(n) for n in nums]

        # Description is text before the first number
        desc = re.split(r'\s+\d', rest)[0].strip()
        voce.descrizione = desc

        # Assign values based on count
        if len(vals) >= 3:
            voce.quantita = vals[0]
            voce.base = vals[1]
            voce.competenze = vals[2]
        elif len(vals) == 2:
            voce.quantita = vals[0]
            voce.competenze = vals[1]
        elif len(vals) == 1:
            # Single value: competenze or trattenute
            if voce.codice.startswith("008") or "Tratt" in desc:
                voce.trattenute = vals[0]
            else:
                voce.competenze = vals[0]

        ced.voci.append(voce)


def _parse_contributions(ced: Cedolino, lines: list[str]):
    """Parse INPS contributions section."""
    in_contrib = False
    for line in lines:
        stripped = line.strip()

        if "Imponibili" in stripped and "Aliquote" in stripped and "Competenze" in stripped:
            in_contrib = True
            continue

        if in_contrib and ("Ctb. ded." in stripped or "Addizionali" in stripped):
            in_contrib = False
            continue

        if not in_contrib:
            continue

        # "005 Contributo IVS -c/DIP 3813,00 9,190 350,41"
        m = re.match(r'^(\w+)\s+(.+)', stripped)
        if not m:
            continue

        code = m.group(1)
        rest = m.group(2)
        nums = RE_NUM.findall(rest)
        vals = [_pdn(n) for n in nums]

        if code == "PR5":
            # Progressive imponibile INPS
            if vals:
                ced.progressivo_imp_inps = vals[0]
            continue

        if "Imponibile Inail" in stripped:
            continue

        if "S010" in code:
            # Sgravio line, skip
            continue

        contrib = ContributionItem()

        if "IVS" in rest:
            contrib.descrizione = "IVS"
        elif "solid" in rest.lower():
            contrib.descrizione = "FDO_SOLID"
        else:
            contrib.descrizione = code

        if len(vals) >= 3:
            contrib.imponibile = vals[0]
            contrib.percentuale = vals[1]
            contrib.importo_dipendente = vals[2]
        elif len(vals) >= 2:
            contrib.imponibile = vals[0]
            contrib.importo_dipendente = vals[1]

        # Avoid duplicates
        for existing in ced.contributi:
            if existing.descrizione == contrib.descrizione:
                return
        ced.contributi.append(contrib)

    # Set INPS section from contributions
    ivs = next((c for c in ced.contributi if c.descrizione == "IVS"), None)
    if ivs:
        ced.inps.imponibile_contrib_arrot_mese = ivs.imponibile
        total = sum(c.importo_dipendente for c in ced.contributi)
        ced.inps.totale_contributi = total


def _parse_addizionali(ced: Cedolino, lines: list[str]):
    """Parse addizionali regionali/comunali.

    The trattenute is the LAST number only when there are >= 3 decimal
    numbers after the year (impon/rata, figurative, trattenute). Lines with
    only 2 numbers have no trattenute.
    """
    in_add = False
    for line in lines:
        stripped = line.strip()

        if "Addizionali" in stripped and "-----" in stripped:
            in_add = True
            continue

        if in_add and ("Ratei" in stripped or "NOTE" in stripped):
            in_add = False
            continue

        if not in_add:
            continue

        if "Addizionale" not in stripped:
            continue

        nums = RE_NUM.findall(stripped)
        if len(nums) < 3:
            # Need at least impon/rata + figurative + trattenute
            continue

        # Last value is trattenute only when there are 3+ decimals
        trattenute = _pdn(nums[-1])

        if "regionale" in stripped:
            ced.addizionale_regionale += trattenute
        elif "comunale" in stripped:
            ced.addizionale_comunale_saldo += trattenute


def _parse_ratei(ced: Cedolino, lines: list[str]):
    """Parse ratei (ferie/permessi)."""
    for line in lines:
        # "FERIE : Res.AP 14,000 Matur. 2,500 GodPag Saldo 16,500"
        m = re.match(r'FERIE\s*:\s*Res\.AP\s+([\d.,]+)\s+Matur\.\s+([\d.,]+)\s+GodPag\s*([\d.,]*)\s*Saldo\s+([\d.,]+)', line.strip())
        if m:
            row = RateiRow(tipo="Ferie")
            row.residuo_ap = _pdn(m.group(1))
            row.maturato = _pdn(m.group(2))
            row.goduto = _pdn(m.group(3)) if m.group(3) else ZERO
            row.saldo = _pdn(m.group(4))
            ced.ratei.append(row)


def _parse_fiscal(ced: Cedolino, lines: list[str]):
    """Parse fiscal section (IRPEF) from page 2 bottom."""
    for i, line in enumerate(lines):
        # IMPOSTA LORDA line followed by values
        if "IMPOSTA LORDA" in line and "DETR. LAV. DIP." in line and "IMPOSTA NETTA" in line:
            if i + 1 < len(lines):
                vals_line = lines[i + 1].strip()
                nums = RE_NUM.findall(vals_line)
                vals = [_pdn(n) for n in nums]
                if len(vals) >= 2:
                    ced.irpef.irpef_lorda_mese = vals[0]
                    ced.irpef.detrazione_lavoro_dip = vals[1]
                if len(vals) >= 3:
                    ced.irpef.irpef_netta_mese = vals[-1]
                    ced.irpef.irpef_piu_imp_sost = vals[-1]
            continue

        # PROGR. IMPON. FISCALE line
        if "PROGR. IMPON. FISCALE" in line and "PROGR. IMP. LORDA" in line:
            if i + 1 < len(lines):
                vals_line = lines[i + 1].strip()
                nums = RE_NUM.findall(vals_line)
                vals = [_pdn(n) for n in nums]
                if len(vals) >= 1:
                    ced.irpef.imponibile_fiscale_anno = vals[0]
                    ced.progressivo_imp_irpef = vals[0]
                if len(vals) >= 2:
                    ced.irpef.irpef_lorda_anno = vals[1]
                if len(vals) >= 4:
                    ced.irpef.irpef_netta_anno = vals[3]
                    ced.progressivo_irpef_pagata = vals[3]
            continue

        # NOTE DESCRIZIONE IMPONIBILE FISCALE line
        if "NOTE" in line and "DESCRIZIONE" in line and "IMPONIBILE FISCALE" in line:
            for j in range(i + 1, min(i + 4, len(lines))):
                next_line = lines[j].strip()
                if "Emolumenti" in next_line:
                    nums = RE_NUM.findall(next_line)
                    vals = [_pdn(n) for n in nums]
                    if len(vals) >= 1:
                        ced.irpef.imponibile_fiscale_mese = vals[0]
                    break
            continue


def _parse_totali(ced: Cedolino, lines: list[str]):
    """Parse totali section."""
    for i, line in enumerate(lines):
        if "TOT TRATTENUTE PREV./FISC." in line and "TOT COMPETENZE" in line:
            if i + 1 < len(lines):
                vals_line = lines[i + 1].strip()
                nums = RE_NUM.findall(vals_line)
                vals = [_pdn(n) for n in nums]
                if len(vals) >= 6:
                    # Arrotondamento is already embedded in comp/tratt via TNARR voce
                    ced.totali.arrotondamento_precedente = vals[2]
                    ced.totali.arrotondamento_attuale = vals[3]
                    ced.totali.arrotondamento = ZERO
                    ced.totali.totale_competenze = vals[4]
                    ced.totali.totale_trattenute = vals[5]
                elif len(vals) >= 4:
                    ced.totali.totale_competenze = vals[-2]
                    ced.totali.totale_trattenute = vals[-1]
            continue

        # NETTO line: "****2377,00"
        if line.strip().startswith("****"):
            m = re.search(r'\*{4}([\d.,]+)', line)
            if m:
                ced.totali.netto_in_busta = _pdn(m.group(1))
            continue

    # Extract TFR from voci
    for v in ced.voci:
        if v.codice == "Z7139":
            ced.tfr.tfr_mese = v.competenze if v.competenze else v.trattenute
        elif v.codice == "TFR100":
            ced.tfr.retribuzione_utile_tfr = v.competenze
        elif v.codice == "TFR200":
            ced.tfr.tfr_mese = v.competenze
