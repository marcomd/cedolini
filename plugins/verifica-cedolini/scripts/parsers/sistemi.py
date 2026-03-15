"""Parser per cedolini Sistemi S.p.A. (JOB) - 2023/2024/2025 gen-ago."""

import re
import pdfplumber
from decimal import Decimal
from scripts.models import (
    Cedolino, VoceItem, ContributionItem, INPSSection, IRPEFSection,
    TFRSection, RateiRow, TotaliSection, parse_italian_decimal, parse_periodo, ZERO
)
from scripts.parsers.base import register_parser


def detect_sistemi(pdf_path: str, full_text: str) -> bool:
    """Detect Sistemi S.p.A. format."""
    return "Sistemi S.p.A" in full_text or "JOB - Copyright" in full_text


register_parser("sistemi", detect_sistemi, lambda path: parse_sistemi(path))

# Regex for Italian decimals in text
RE_NUM = re.compile(r'-?\d[\d.]*,\d+|\d[\d.]*')
# Italian codice fiscale pattern
RE_CF = re.compile(r'[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]')


def _extract_nums(text: str) -> list[str]:
    """Extract all number tokens (Italian format) from a string."""
    return RE_NUM.findall(text)


def _pdn(s: str) -> Decimal:
    """Shorthand for parse_italian_decimal."""
    return parse_italian_decimal(s)


def parse_sistemi(pdf_path: str) -> Cedolino:
    """Parse a Sistemi S.p.A. cedolino PDF."""
    ced = Cedolino(file_path=pdf_path, formato="sistemi")

    with pdfplumber.open(pdf_path) as pdf:
        ced.num_pagine = len(pdf.pages)
        all_lines = []
        for page in pdf.pages:
            text = page.extract_text() or ""
            all_lines.append(text.split("\n"))

    # For multi-page cedolini: find the page with "TOTALE COMPETENZE"
    # Page 2 might be attendance record (not cedolino continuation) or
    # it might be the continuation with netto (2023 format)
    sections_page_lines = all_lines[0]  # Default to first page
    for page_lines in reversed(all_lines):
        page_text = "\n".join(page_lines)
        if "TOTALE COMPETENZE" in page_text and "NETTO IN BUSTA" in page_text:
            sections_page_lines = page_lines
            break
    last_page_lines = sections_page_lines

    # Parse header from first page
    page1 = all_lines[0]
    _parse_header(ced, page1)

    # Parse salary components from first page
    _parse_salary_components(ced, page1)

    # Parse ratei (ferie/permessi) from first page
    _parse_ratei_header(ced, page1)

    # Parse voci from first page
    _parse_voci(ced, page1)

    # Parse contributions from all pages (2-page cedolini split them)
    for page_lines in all_lines:
        _parse_contributions(ced, page_lines)

    # Parse QTA/INPS section from last page
    _parse_inps_section(ced, last_page_lines)

    # Parse IRPEF section from last page
    _parse_irpef_section(ced, last_page_lines)

    # Parse TFR section from last page
    _parse_tfr_section(ced, last_page_lines)

    # Parse totali from last page
    _parse_totali(ced, last_page_lines)

    # Extract addizionali from voci
    _extract_addizionali(ced)

    return ced


def _parse_header(ced: Cedolino, lines: list[str]):
    """Parse header info (company, employee, period).

    Sistemi header structure (line-based text extraction):
      "COMPANY SRL NNNNNNNNNN GENNAIO 2024"  -> company + POS INPS (10 digits) + period
      "VIA ..."                               -> address (skip)
      "PAT NNNNNN/NN ..."                     -> POS INAIL (digits/digits)
      "NNN SURNAME NAME CF CITY (PROV) DOB"   -> employee (codice fiscale as anchor)
      "CITY (PROV) qualifica CCNL_name"       -> contratto line
      "DD/MM/YYYY ..."                        -> hire date
      "BONIFICO ... DD/MM/YYYY level"         -> livello
    """
    employee_line_idx = None

    for i, line in enumerate(lines):
        # Company: line with 10-digit POS INPS followed by a month name
        pos_inps_m = re.search(r'(\d{10})\s+(GENNAIO|FEBBRAIO|MARZO|APRILE|MAGGIO|GIUGNO|'
                               r'LUGLIO|AGOSTO|SETTEMBRE|OTTOBRE|NOVEMBRE|DICEMBRE'
                               r'|TREDICESIMA|QUATTORDICESIMA)', line, re.IGNORECASE)
        if pos_inps_m and not ced.ragione_sociale:
            ced.pos_inps = pos_inps_m.group(1)
            # Company name is everything before the POS INPS number
            company = line[:pos_inps_m.start()].strip()
            if company:
                ced.ragione_sociale = company
            # Period is everything from the month onward
            periodo_str = line[pos_inps_m.start(2):].strip()
            if periodo_str:
                ced.mese_retribuzione = periodo_str
                ced.anno, ced.mese, ced.is_tredicesima = parse_periodo(periodo_str)
            continue

        # POS INAIL: line with a PAT-format number (digits/digits), not the company line
        if not ced.pos_inail and re.search(r'\d{5,}/\d+', line):
            m = re.search(r'(\d{5,}/\d+)', line)
            if m:
                ced.pos_inail = m.group(1)
            continue

        # Employee: line with a codice fiscale
        cf_match = RE_CF.search(line)
        if cf_match and not ced.codice_fiscale:
            ced.codice_fiscale = cf_match.group()
            # Before CF: "987 SURNAME NAME"
            before_cf = line[:cf_match.start()].strip()
            m = re.match(r'(\d+)\s+(.*)', before_cf)
            if m:
                ced.cod_dipendente = m.group(1)
                ced.cognome_nome = m.group(2).strip()
            employee_line_idx = i
            continue

        # Contratto: line containing a CCNL-like name (generic pattern)
        ccnl_m = re.search(r'(Commercio\s+e\s+terziario[^)]*|'
                           r'CCNL\s+\w+[^)]*|'
                           r'Assicurativo[^)]*)', line, re.IGNORECASE)
        if ccnl_m and not ced.contratto:
            ced.contratto = ccnl_m.group(1).strip()
            # Qualifica: text between city "(PROV)" pattern and the CCNL name
            qual_m = re.search(r'\([A-Z]{2}\)\s+(.+?)\s+' + re.escape(ccnl_m.group(1)[:10]), line)
            if qual_m:
                ced.qualifica = qual_m.group(1).strip()
            continue

        # Data assunzione: DD/MM/YYYY on a line after employee, before salary components
        if (employee_line_idx is not None and i > employee_line_idx
                and not ced.data_assunzione and "RETR.BASE" not in line):
            date_m = re.search(r'(\d{2}/\d{2}/\d{4})', line)
            if date_m:
                ced.data_assunzione = date_m.group(1)
                continue

        # Livello from BONIFICO line
        if "BONIFICO" in line:
            m = re.search(r'\d+/\d+/\d{4}\s+(\d+)\s*$', line)
            if m:
                ced.livello = m.group(1)
            continue


def _parse_salary_components(ced: Cedolino, lines: list[str]):
    """Parse salary component values."""
    for i, line in enumerate(lines):
        if "RETR.BASE" in line and "CONTINGENZA" in line:
            nums = _extract_nums(line)
            if len(nums) >= 5:
                # Values after the labels
                # Find the decimal values (those with 5 decimal places)
                vals = [n for n in nums if "," in n]
                if len(vals) >= 5:
                    ced.paga_base = _pdn(vals[0])
                    ced.contingenza = _pdn(vals[1])
                    ced.superminimo = _pdn(vals[2])
                    ced.terzo_elemento = _pdn(vals[3])
                    ced.edr = _pdn(vals[4])
            continue

        # Retribuzione oraria/giornaliera/mensile
        # Line just before "misura": "22,95917 148,35154 3.857,14"
        if i + 1 < len(lines) and lines[i + 1].strip() == "misura":
            nums = _extract_nums(line)
            vals = [n for n in nums if "," in n]
            if len(vals) >= 3:
                ced.retribuzione_oraria = _pdn(vals[0])
                ced.retribuzione_giornaliera = _pdn(vals[1])
                ced.retribuzione_mensile = _pdn(vals[2])
            continue

        # PAGA BASE with SCATTI (Zucchetti transition, but check just in case)
        if "PAGA BASE" in line and "SCATTI" in line and "CONTING" in line:
            nums = _extract_nums(line)
            vals = [n for n in nums if "," in n]
            if len(vals) >= 6:
                ced.paga_base = _pdn(vals[0])
                ced.scatti = _pdn(vals[1])
                ced.contingenza = _pdn(vals[2])
                ced.terzo_elemento = _pdn(vals[3])
                ced.edr = _pdn(vals[4])
                ced.superminimo = _pdn(vals[5])


def _parse_ratei_header(ced: Cedolino, lines: list[str]):
    """Parse ferie/permessi from header area.

    The ratei data lines sit between the RETR.BASE line and the "misura" line.
    Each ratei row is a line of numbers followed by a "(ORE)" line.
    Order is always: FERIE, then PERMESSI (if present), then EX FESTIVITA'.

    Number count to column mapping:
      5 values: residuo_ap, maturato, goduto_ap, goduto_ac, saldo
      4 values: residuo_ap, maturato, goduto, saldo
      3 values: residuo_ap, maturato, saldo (no goduto)
      2 values: maturato, saldo (no residuo_ap)
    """
    ced.ratei = []

    # Find the block between RETR.BASE line and "misura" line
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if "RETR.BASE" in line and "CONTINGENZA" in line:
            start_idx = i + 1
        elif line.strip() == "misura" and start_idx is not None:
            end_idx = i
            break

    if start_idx is None or end_idx is None:
        return

    # Collect data lines: lines of numbers each followed by "(ORE)"
    data_blocks = []
    i = start_idx
    while i < end_idx:
        stripped = lines[i].strip()
        # Check if next line is "(ORE)" (possibly with extra text appended)
        next_is_ore = (i + 1 < end_idx and "(ORE)" in lines[i + 1])
        if next_is_ore:
            # Extract Italian decimals, handling trailing minus: "8,00-" → -8.00
            nums_raw = re.findall(r'\d[\d.]*,\d+-?', stripped)
            if nums_raw:
                vals = []
                for n in nums_raw:
                    if n.endswith('-'):
                        vals.append(-_pdn(n[:-1]))
                    else:
                        vals.append(_pdn(n))
                data_blocks.append(vals)
            i += 2  # skip the (ORE) line
        else:
            i += 1

    # Map blocks to ratei types: FERIE first, then PERMESSI, then EX FESTIVITA'
    types = ["Ferie", "Ex Festivita'"]
    if len(data_blocks) >= 3:
        types = ["Ferie", "Permessi (R.O.L.)", "Ex Festivita'"]

    for idx, vals in enumerate(data_blocks):
        if idx >= len(types):
            break
        tipo = types[idx]
        row = RateiRow(tipo=tipo)

        if len(vals) == 5:
            row.residuo_ap = vals[0]
            row.maturato = vals[1]
            row.goduto = vals[2] + vals[3]  # goduto_ap + goduto_ac
            row.saldo = vals[4]
        elif len(vals) == 4:
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


def _parse_voci(ced: Cedolino, lines: list[str]):
    """Parse voci variabili (lines starting with voce code)."""
    in_voci = False
    for line in lines:
        stripped = line.strip()

        # Start of voci section: after "misura" line
        if stripped == "misura":
            in_voci = True
            continue

        # End of voci section: "DESCRIZIONE CONTRIBUTO" line
        if "DESCRIZIONE CONTRIBUTO" in stripped:
            in_voci = False
            continue

        if not in_voci:
            continue

        # Skip empty lines
        if not stripped:
            continue

        # Parse voce line: "0 Retribuzione ordinaria GIORNI 24,000 148,35154 3.560,44 * * * *"
        # or "81 Quota TFR F.do Pensione 288,62"
        # or "826 Rata addiz. Comunale aggiunt. 2023 35,24 *"
        m = re.match(r'^(\d+)\s+(.+)', stripped)
        if not m:
            # Check for text-only lines (like "Recupero ore 24 ferie godute 12/2023")
            continue

        voce = VoceItem()
        voce.codice = m.group(1)
        rest = m.group(2)

        # Extract flags from end
        flags_str = ""
        while rest.endswith(" *"):
            flags_str = "* " + flags_str
            rest = rest[:-2]
        if rest.endswith("*"):
            flags_str = "* " + flags_str
            rest = rest[:-1]

        flag_count = flags_str.count("*")
        # Flags are CITN from right to left (N, T, I, C)
        if flag_count >= 4:
            voce.flag_c = voce.flag_i = voce.flag_t = voce.flag_n = True
        elif flag_count == 3:
            voce.flag_c = voce.flag_i = voce.flag_t = True
        elif flag_count == 1:
            voce.flag_n = True

        # Parse remaining: description [unit qty] [base] amount
        # Try to extract unit of measure
        unit_match = re.search(r'\b(GIORNI|ORE|RATEI|MESI)\b', rest)
        if unit_match:
            voce.unita_misura = unit_match.group(1)
            desc_part = rest[:unit_match.start()].strip()
            nums_part = rest[unit_match.end():].strip()
        else:
            # No unit - find where numbers start
            # Look for the first Italian decimal number
            num_match = re.search(r'\s(\d[\d.]*,\d+)', rest)
            if num_match:
                desc_part = rest[:num_match.start()].strip()
                nums_part = rest[num_match.start():].strip()
            else:
                desc_part = rest.strip()
                nums_part = ""

        voce.descrizione = desc_part

        # Extract numbers from the remaining part
        nums = _extract_nums(nums_part)
        vals = [_pdn(n) for n in nums]

        if voce.unita_misura and len(vals) >= 1:
            voce.quantita = vals[0]
            if len(vals) >= 3:
                voce.base = vals[1]
                voce.competenze = vals[2]
            elif len(vals) >= 2:
                # Could be base+competenze or just competenze
                if vals[1] > Decimal("1000"):
                    voce.competenze = vals[1]
                else:
                    voce.base = vals[1]
        elif len(vals) >= 1:
            # No unit: the value is either competenze or trattenute
            # Check if the line had flags suggesting it's a trattenuta
            last_val = vals[-1]
            # Detect if it's a trattenuta by looking at common voce codes
            if voce.codice in ("81",):  # TFR is a special voce
                voce.competenze = ZERO
                voce.trattenute = ZERO
                # Voce 81 amount is TFR to fund, not competenze/trattenute
                if vals:
                    voce.competenze = vals[0]
            elif voce.codice in ("826", "827", "828", "829", "821", "823"):
                # Addizionali are trattenute
                voce.trattenute = vals[-1]
                if len(vals) >= 2:
                    voce.base = vals[0]
            else:
                voce.competenze = vals[-1]

        ced.voci.append(voce)


def _parse_contributions(ced: Cedolino, lines: list[str]):
    """Parse contributions section (INPS, CIGS, FIS, FON.TE, EST)."""
    in_contrib = False
    for line in lines:
        stripped = line.strip()

        if "DESCRIZIONE CONTRIBUTO" in stripped and "IMPONIBILE" in stripped:
            in_contrib = True
            continue

        if in_contrib and ("Q SETT" in stripped or "RETRIBUZIONE UTILE" in stripped):
            in_contrib = False
            continue

        if not in_contrib:
            continue

        if not stripped:
            continue

        # The contribution lines have two columns (left and right)
        # Split at the midpoint or look for known patterns
        # Each half: "DESC IMPONIBILE %C/DIP IMPORTO"
        _parse_contrib_line(ced, stripped)


def _parse_contrib_line(ced: Cedolino, line: str):
    """Parse a single contribution line (may have two columns)."""
    # Known left-side patterns
    left_patterns = [
        (r'INPS\b(?:\s+CONTR\.CIGS[^)]*\))?', "INPS"),
        (r'INPS\s+CONTR\.CIGS\s+L\.\d+/\d+', "CIGS"),
        (r'INPS\s+(\d[\d.]*,\d+)', "INPS"),
        (r'ADDIZIONALE IVS', "ADD_IVS"),
        (r'FONDO INTEGR\. SALARIALE\s*-\s*FIS', "FIS"),
        (r'EST:\s*CONTRIBUTO', "EST"),
    ]

    # Known right-side patterns
    right_patterns = [
        (r'CONTRIBUTO FON\.TE', "FONTE"),
        (r'EST:\s*CONTRIBUTO', "EST"),
        (r'FONDO INTEGR\. SALARIALE\s*-\s*FIS', "FIS"),
    ]

    # Try to split the line into two halves at "CONTRIBUTO FON.TE" or "EST:" or "FONDO"
    # The right half starts at the second set of contribution keywords
    split_keywords = [
        "CONTRIBUTO FON.TE",
        "EST: CONTRIBUTO",
        "FONDO INTEGR. SALARIALE",
    ]

    halves = [line]
    for kw in split_keywords:
        # Find the keyword after the first contribution entry (min 15 chars in)
        idx = line.find(kw, 15)
        if idx > 0:
            halves = [line[:idx].strip(), line[idx:].strip()]
            break

    for half in halves:
        if not half.strip():
            continue
        _parse_single_contrib(ced, half.strip())


def _parse_single_contrib(ced: Cedolino, text: str):
    """Parse a single contribution entry."""
    # Extract only Italian decimal numbers (with comma) for amounts
    decimal_nums = re.findall(r'\d[\d.]*,\d+', text)
    if not decimal_nums:
        return

    contrib = ContributionItem()

    if text.startswith("INPS CONTR.CIGS") or "CONTR.CIGS" in text:
        contrib.descrizione = "CIGS"
    elif text.startswith("INPS"):
        contrib.descrizione = "IVS"
    elif "ADDIZIONALE IVS" in text:
        contrib.descrizione = "ADD_IVS"
    elif "FIS" in text or "FONDO INTEGR" in text:
        contrib.descrizione = "FIS"
    elif "EST" in text and "CONTRIBUTO" in text:
        contrib.descrizione = "EST"
    elif "FON.TE" in text:
        if "0,550" in text or "0,55" in text:
            contrib.descrizione = "FONTE_BASE"
        elif "0,450" in text or "0,45" in text:
            contrib.descrizione = "FONTE_VOL"
        else:
            contrib.descrizione = "FONTE"
    else:
        contrib.descrizione = text.split()[0] if text.split() else "UNKNOWN"

    vals = [_pdn(n) for n in decimal_nums]

    if contrib.descrizione == "EST":
        contrib.importo_dipendente = vals[0] if vals else ZERO
    elif len(vals) >= 3:
        contrib.imponibile = vals[0]
        contrib.percentuale = vals[1]
        contrib.importo_dipendente = vals[2]
    elif len(vals) == 2:
        contrib.imponibile = vals[0]
        contrib.percentuale = vals[1]
    elif len(vals) == 1:
        contrib.importo_dipendente = vals[0]

    # Check if this contribution is already in the list
    for existing in ced.contributi:
        if existing.descrizione == contrib.descrizione:
            if (existing.imponibile == contrib.imponibile and
                    existing.percentuale == contrib.percentuale):
                # Exact duplicate (from 2-page) - skip
                return
            else:
                # Same type but different imponibile (e.g. INPS on base + una tantum)
                # Accumulate the amounts
                existing.imponibile += contrib.imponibile
                existing.importo_dipendente += contrib.importo_dipendente
                return

    ced.contributi.append(contrib)


def _parse_inps_section(ced: Cedolino, lines: list[str]):
    """Parse the QTA/INPS section."""
    for i, line in enumerate(lines):
        if not line.strip().startswith("A ") or "Q SETT" not in "".join(lines[max(0, i - 3):i]):
            continue

        # "A 4 26 22 176,00 R 4.179,00 407,75 4.178,57 4.179,00 451,53"
        # Remove the leading "A" and "R" markers
        clean = line.strip()[2:]  # Skip "A "
        # Split at "R "
        r_idx = clean.find(" R ")
        if r_idx < 0:
            continue

        left = clean[:r_idx].strip()
        right = clean[r_idx + 3:].strip()

        left_nums = _extract_nums(left)
        right_nums = _extract_nums(right)

        if len(left_nums) >= 3:
            ced.inps.settimane = int(left_nums[0]) if left_nums[0].isdigit() else 0
            ced.inps.gg_retribuiti = int(left_nums[1]) if left_nums[1].isdigit() else 0
            ced.inps.gg_lavorati = int(left_nums[2]) if left_nums[2].isdigit() else 0
            if len(left_nums) >= 4:
                ced.inps.ore_lavorate = _pdn(left_nums[3])

        if len(right_nums) >= 5:
            ced.inps.imponibile_contributivo_anno = _pdn(right_nums[0])
            ced.inps.contributi_anno = _pdn(right_nums[1])
            ced.inps.imponibile_contributivo_mese = _pdn(right_nums[2])
            ced.inps.imponibile_contrib_arrot_mese = _pdn(right_nums[3])
            ced.inps.totale_contributi = _pdn(right_nums[4])
        elif len(right_nums) >= 3:
            ced.inps.imponibile_contributivo_anno = _pdn(right_nums[0])
            ced.inps.contributi_anno = _pdn(right_nums[1])
            ced.inps.imponibile_contributivo_mese = _pdn(right_nums[2])

        break


def _parse_irpef_section(ced: Cedolino, lines: list[str]):
    """Parse IRPEF MESE and ANNO sections."""
    # Find the two "IMPONIBILE FISCALE" headers
    fiscal_headers = []
    for i, line in enumerate(lines):
        if "IMPONIBILE FISCALE" in line and "IRPEF LORDA" in line:
            fiscal_headers.append(i)

    if len(fiscal_headers) >= 1:
        # MESE section: line after first header
        mese_idx = fiscal_headers[0]
        if mese_idx + 1 < len(lines):
            mese_line = lines[mese_idx + 1].strip()
            if mese_line.startswith("M "):
                nums = _extract_nums(mese_line[2:])
                vals = [_pdn(n) for n in nums]
                if len(vals) >= 3:
                    ced.irpef.imponibile_fiscale_mese = vals[0]
                    ced.irpef.irpef_lorda_mese = vals[1]
                    ced.irpef.gg_detrazione = int(nums[-1]) if nums[-1].isdigit() else 0
                    if len(vals) >= 4:
                        ced.irpef.detrazione_lavoro_dip = vals[2]
                elif len(vals) == 2:
                    ced.irpef.imponibile_fiscale_mese = vals[0]
                    ced.irpef.gg_detrazione = int(nums[-1]) if nums[-1].isdigit() else 0

        # Find IRPEF NETTA MESE line (after "S IRPEF NETTA")
        for j in range(mese_idx + 2, min(mese_idx + 8, len(lines))):
            line = lines[j].strip()
            nums = _extract_nums(line)
            # The line with just numbers (IRPEF netta values)
            if nums and not any(c.isalpha() for c in line.replace(",", "").replace(".", "").replace(" ", "").replace("-", "")):
                vals = [_pdn(n) for n in nums]
                if len(vals) >= 2:
                    ced.irpef.irpef_netta_mese = vals[0]
                    ced.irpef.irpef_piu_imp_sost = vals[1]
                elif len(vals) == 1:
                    ced.irpef.irpef_netta_mese = vals[0]
                    ced.irpef.irpef_piu_imp_sost = vals[0]
                break

    if len(fiscal_headers) >= 2:
        # ANNO section: line after second header
        anno_idx = fiscal_headers[1]
        if anno_idx + 1 < len(lines):
            anno_line = lines[anno_idx + 1].strip()
            if anno_line.startswith("A "):
                nums = _extract_nums(anno_line[2:])
                vals = [_pdn(n) for n in nums]
                if len(vals) >= 3:
                    ced.irpef.imponibile_fiscale_anno = vals[0]
                    ced.irpef.irpef_lorda_anno = vals[1]
                    ced.irpef.gg_detrazione_anno = int(nums[-1]) if nums[-1].isdigit() else 0
                elif len(vals) == 2:
                    ced.irpef.imponibile_fiscale_anno = vals[0]
                    ced.irpef.gg_detrazione_anno = int(nums[-1]) if nums[-1].isdigit() else 0

        # Find IRPEF ANNO netta/trattenuta/conguaglio
        for j in range(anno_idx + 2, min(anno_idx + 10, len(lines))):
            line = lines[j].strip()
            if "RETRIBUZIONE UTILE" in line:
                break
            nums = _extract_nums(line)
            if nums and not any(c.isalpha() for c in line.replace(",", "").replace(".", "").replace(" ", "").replace("-", "")):
                vals = [_pdn(n) for n in nums]
                if len(vals) >= 4:
                    ced.irpef.irpef_netta_anno = vals[0]
                    ced.irpef.irpef_trattenuta_anno = vals[1]
                    ced.irpef.irpef_conguaglio = vals[2]
                elif len(vals) >= 2:
                    ced.irpef.irpef_netta_anno = vals[0]
                    ced.irpef.irpef_trattenuta_anno = vals[1]
                break


def _parse_tfr_section(ced: Cedolino, lines: list[str]):
    """Parse TFR section."""
    for i, line in enumerate(lines):
        if "RETRIBUZIONE UTILE TFR" in line:
            # Next data line starts with "T "
            for j in range(i + 1, min(i + 3, len(lines))):
                data_line = lines[j].strip()
                if data_line.startswith("T "):
                    nums = _extract_nums(data_line[2:])
                    vals = [_pdn(n) for n in nums]
                    if len(vals) >= 1:
                        ced.tfr.retribuzione_utile_tfr = vals[0]
                    if len(vals) >= 2:
                        ced.tfr.contributo_agg_tfr = vals[1]
                    if len(vals) >= 3:
                        ced.tfr.tfr_mese = vals[2]
                    if len(vals) >= 4:
                        ced.tfr.tfr_annuo = vals[3]
                    if len(vals) >= 5:
                        ced.tfr.fondo_tfr_31_12_ap = vals[4]
                    break

            # TFR IRPEF line starts with "A " after "IMPONIBILE LORDO"
            for j in range(i + 3, min(i + 10, len(lines))):
                data_line = lines[j].strip()
                if data_line.startswith("A ") and "TABELLA" not in lines[max(0, j - 2)]:
                    nums = _extract_nums(data_line[2:])
                    vals = [_pdn(n) for n in nums]
                    if len(vals) >= 3:
                        ced.tfr.imponibile_lordo = vals[0]
                        ced.tfr.perc_irpef = vals[1]
                        ced.tfr.irpef_tfr = vals[2]
                    break
            break


def _parse_totali(ced: Cedolino, lines: list[str]):
    """Parse totali section."""
    for i, line in enumerate(lines):
        if "TOTALE COMPETENZE" in line and "TOTALE TRATTENUTE" in line:
            # Data is on next line starting with "N O"
            for j in range(i + 1, min(i + 3, len(lines))):
                data_line = lines[j].strip()
                if data_line.startswith("N O") or data_line.startswith("N "):
                    # "N O 4.178,57 1.578,65 0,24 0,32 2.600,00"
                    nums = _extract_nums(data_line)
                    vals = [_pdn(n) for n in nums]
                    if len(vals) >= 5:
                        ced.totali.totale_competenze = vals[0]
                        ced.totali.totale_trattenute = vals[1]
                        # Handle negative arrotondamento (e.g. "0,11-")
                        arr_nums = re.findall(r'(\d[\d.]*,\d+-?)', data_line)
                        if len(arr_nums) >= 4:
                            ced.totali.arrotondamento_precedente = _pdn(arr_nums[2])
                            ced.totali.arrotondamento_attuale = _pdn(arr_nums[3])
                        if len(vals) >= 5:
                            ced.totali.netto_in_busta = vals[-1]
                        ced.totali.arrotondamento = (
                            ced.totali.arrotondamento_precedente +
                            ced.totali.arrotondamento_attuale
                        )
                    elif len(vals) == 4:
                        # 4-value: comp, tratt, single arrotondamento, netto
                        ced.totali.totale_competenze = vals[0]
                        ced.totali.totale_trattenute = vals[1]
                        ced.totali.arrotondamento_attuale = vals[2]
                        ced.totali.arrotondamento = vals[2]
                        ced.totali.netto_in_busta = vals[3]
                    elif len(vals) >= 3:
                        ced.totali.totale_competenze = vals[0]
                        ced.totali.totale_trattenute = vals[1]
                        ced.totali.netto_in_busta = vals[-1]
                    break
            break


def _extract_addizionali(ced: Cedolino):
    """Extract addizionali from voci."""
    for v in ced.voci:
        desc_upper = v.descrizione.upper()
        if "ADDIZIONALE REGIONALE" in desc_upper or "ADDIZ.REGIONALE" in desc_upper:
            ced.addizionale_regionale += v.trattenute
        elif "ADDIZ.COMUNALE" in desc_upper or "ADDIZIONALE COMUNALE" in desc_upper:
            if "ACCONTO" in desc_upper or "ACC" in desc_upper:
                ced.addizionale_comunale_acconto += v.trattenute
            else:
                ced.addizionale_comunale_saldo += v.trattenute
        elif v.codice == "828":
            ced.addizionale_regionale += v.trattenute
        elif v.codice in ("826", "827"):
            ced.addizionale_comunale_saldo += v.trattenute
        elif v.codice == "821":
            # Addizionale comunale dovuta (December conguaglio)
            ced.addizionale_comunale_saldo += v.trattenute
        elif v.codice == "823":
            # Addizionale regionale dovuta (December conguaglio)
            ced.addizionale_regionale += v.trattenute
