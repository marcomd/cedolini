"""Parser per cedolini Zucchetti - 2025 set-dic / 2026."""

import re
import pdfplumber
from decimal import Decimal
from scripts.models import (
    Cedolino, VoceItem, ContributionItem, INPSSection, IRPEFSection,
    TFRSection, RateiRow, TotaliSection, parse_italian_decimal, parse_periodo, ZERO
)
from scripts.parsers.base import register_parser


def detect_zucchetti(pdf_path: str, full_text: str) -> bool:
    """Detect Zucchetti format."""
    if "Zucchetti" in full_text or "ZUCCHETTI" in full_text:
        return True
    if "CodicesAzienda" in full_text or "TOTALEsCOMPETENZE" in full_text:
        return True
    return False


register_parser("zucchetti", detect_zucchetti, lambda path: parse_zucchetti(path))

RE_NUM = re.compile(r'-?\d[\d.]*,\d+')
# Match Z/F/ZP codes at the start of a word
RE_VOCE_CODE = re.compile(r'^([ZF]\d{5}|ZP\d{4})')
# Italian codice fiscale pattern
RE_CF = re.compile(r'[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]')


def _pdn(s: str) -> Decimal:
    return parse_italian_decimal(s)


def _extract_nums(text: str) -> list[str]:
    return RE_NUM.findall(text)


def parse_zucchetti(pdf_path: str) -> Cedolino:
    """Parse a Zucchetti cedolino PDF."""
    ced = Cedolino(file_path=pdf_path, formato="zucchetti")

    with pdfplumber.open(pdf_path) as pdf:
        ced.num_pagine = len(pdf.pages)
        # Extract words from all pages
        all_words = []
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=True)
            all_words.append(words)

        # Also get full text for fallback
        all_text = []
        for page in pdf.pages:
            text = page.extract_text() or ""
            all_text.append(text)

    # Build structured lines from word positions
    lines_p1 = _build_lines(all_words[0])
    lines_p2 = _build_lines(all_words[1]) if len(all_words) > 1 else []

    # Parse header
    _parse_header(ced, lines_p1)

    # Parse salary components
    _parse_salary(ced, lines_p1)

    # Parse voci from all pages
    _parse_voci(ced, lines_p1)
    if lines_p2:
        _parse_voci(ced, lines_p2, is_continuation=True)

    # Parse bottom sections from last page
    last_lines = lines_p2 if lines_p2 else lines_p1
    last_text = all_text[-1]
    _parse_progressivi(ced, last_lines, last_text)
    _parse_tfr(ced, last_lines, last_text)
    _parse_ratei(ced, last_lines, last_text)
    _parse_totali(ced, last_lines, last_text)
    _parse_conguaglio(ced, last_lines, last_text)

    # Extract addizionali and IRPEF from voci
    _extract_fiscal_data(ced)

    # Detect tredicesima from voci (Z50000 = 13ma Mensilita')
    if not ced.is_tredicesima:
        for v in ced.voci:
            if v.codice == "Z50000" and "13" in v.descrizione:
                ced.is_tredicesima = True
                ced.mese = 13
                break

    return ced


def _build_lines(words: list[dict]) -> list[dict]:
    """Build structured lines from word positions, grouped by Y coordinate.

    Returns list of dicts with 'y', 'text', and 'words' keys.
    Filters out the garbled sidebar text (x < 25).
    Reconstructs fragmented characters into proper words.
    """
    if not words:
        return []

    # Filter out sidebar text (x < 25)
    filtered = [w for w in words if w["x0"] >= 25]

    # Group by approximate Y coordinate
    raw_lines = []
    current_y = None
    current_words = []

    for w in sorted(filtered, key=lambda w: (round(w["top"], 0), w["x0"])):
        y = round(w["top"], 0)
        if current_y is None or abs(y - current_y) > 4:
            if current_words:
                raw_lines.append((current_y, list(current_words)))
            current_y = y
            current_words = [w]
        else:
            current_words.append(w)

    if current_words:
        raw_lines.append((current_y, list(current_words)))

    # Post-process: merge adjacent single-character fragments into words
    lines = []
    for y, words_in_line in raw_lines:
        merged = _merge_fragments(sorted(words_in_line, key=lambda x: x["x0"]))
        text = " ".join(w["text"] for w in merged)
        # Fix split decimal numbers: "405 ,37" -> "405,37"
        text = re.sub(r'(\d+)\s+,(\d+)', r'\1,\2', text)
        # Fix split thousands: "4.411 ,00" -> "4.411,00"
        text = re.sub(r'([\d.]+)\s+,(\d+)', r'\1,\2', text)
        lines.append({"y": y, "text": text, "words": merged})

    return lines


def _merge_fragments(words: list[dict]) -> list[dict]:
    """Merge adjacent single-character fragments into proper words.

    Handles cases where PDF renders codes like Z00000 as individual glyphs
    and amounts like 405,37 as separate characters.
    """
    if not words:
        return []

    result = []
    i = 0
    while i < len(words):
        w = words[i]
        # Check if this starts a sequence of close single-character fragments
        if len(w["text"]) <= 2 and i + 1 < len(words):
            # Look ahead for adjacent fragments
            merged_text = w["text"]
            merged_x0 = w["x0"]
            merged_x1 = w.get("x1", w["x0"] + 6)
            merged_top = w["top"]
            j = i + 1
            while j < len(words):
                nw = words[j]
                gap = nw["x0"] - merged_x1
                # Merge if fragments are close (< 8px gap) and individually short
                if gap < 8 and len(nw["text"]) <= 2:
                    merged_text += nw["text"]
                    merged_x1 = nw.get("x1", nw["x0"] + 6)
                    j += 1
                elif gap < 3 and len(nw["text"]) <= 6:
                    # Also merge slightly longer fragments if very close
                    merged_text += nw["text"]
                    merged_x1 = nw.get("x1", nw["x0"] + 6)
                    j += 1
                else:
                    break

            if j > i + 1:
                # Created a merged word
                result.append({
                    "text": merged_text,
                    "x0": merged_x0,
                    "x1": merged_x1,
                    "top": merged_top,
                })
                i = j
                continue

        result.append(w)
        i += 1

    return result


def _parse_header(ced: Cedolino, lines: list[dict]):
    """Parse header information using label rows as anchors.

    Zucchetti PDFs have a structured header with label rows followed by value rows:
      Label: "CodicesAzienda RagionesSociale"  ->  Value: "NNNNNN COMPANY S.R.L"
      Label: "CodicesFiscale PosizionesInps..."  ->  Value: "XXXXXXXXXXX POS/00 PAT/XX"
      Label: "Codicesdipendente COGNOMEsEsNOME CodicesFiscale"  ->  Value: "0000046 NAME CF"
      Label: "DatasdisNascita DatasAssunzione"  ->  Value: "DD-MM-YYYY DD-MM-YYYY"
    """
    # Phase 1: identify label rows and their indices
    company_label_idx = None
    fiscal_label_idx = None
    employee_label_idx = None
    dates_label_idx = None

    for i, line in enumerate(lines):
        text = line["text"]
        collapsed = text.replace("s", "").replace(" ", "")
        if "CodiceAzienda" in collapsed and "RagioneSociale" in collapsed:
            company_label_idx = i
        elif "CodiceFicale" in collapsed and "PoizioneInp" in collapsed:
            fiscal_label_idx = i
        elif "Codicedipendente" in collapsed and "COGNOME" in text:
            employee_label_idx = i
        elif "DatadiNacita" in collapsed and "DataAunzione" in collapsed:
            dates_label_idx = i

    # Phase 2: parse value rows following labels
    for i, line in enumerate(lines):
        text = line["text"]

        # Company: first data line after company label (numeric code + name)
        if company_label_idx is not None and i == company_label_idx + 1:
            m = re.match(r'(\d+)\s+(.+)', text)
            if m:
                ced.cod_azienda = m.group(1)
                ced.ragione_sociale = m.group(2).strip()
            continue

        # Fiscal: CF azienda + POS INPS + POS INAIL
        if fiscal_label_idx is not None and i == fiscal_label_idx + 1:
            parts = text.split()
            if len(parts) >= 2:
                for part in parts[1:]:
                    if re.match(r'\d{10}/\d+$', part):
                        ced.pos_inps = part
                    elif re.match(r'\d{6,}/\d+$', part):
                        ced.pos_inail = part
            continue

        # Period: "Ottobre 2025" or "Dicembre 2025 AGG." or embedded in longer line
        periodo_match = re.search(
            r'(Gennaio|Febbraio|Marzo|Aprile|Maggio|Giugno|Luglio|'
            r'Agosto|Settembre|Ottobre|Novembre|Dicembre)\s+(\d{4})(\s+AGG\.?)?',
            text
        )
        if periodo_match and not ced.mese_retribuzione:
            periodo_str = periodo_match.group(0).strip()
            ced.mese_retribuzione = periodo_str
            ced.anno, ced.mese, ced.is_tredicesima = parse_periodo(periodo_str)
            continue

        # Employee: data line after employee label, contains codice fiscale
        if employee_label_idx is not None and i == employee_label_idx + 1:
            cf_match = RE_CF.search(text)
            if cf_match:
                ced.codice_fiscale = cf_match.group()
                before_cf = text[:cf_match.start()].strip()
                m = re.match(r'(\d+)\s+(.*)', before_cf)
                if m:
                    ced.cod_dipendente = m.group(1)
                    ced.cognome_nome = m.group(2).strip()
            continue

        # Livello: "IMP 1 Livello" or "Impiegato 1 Livello"
        if "Livello" in text:
            m = re.search(r'(\d+)\s+Livello', text)
            if m:
                ced.livello = m.group(1)
            # Qualifica may be part of same text (e.g. "Impiegato")
            qual_m = re.match(r'(\w+)\s+\d+\s+Livello', text)
            if qual_m:
                ced.qualifica = qual_m.group(1)
            continue

        # Dates + qualifica: line after dates label has "DD-MM-YYYY DD-MM-YYYY [qualifica]"
        if (dates_label_idx is not None
                and i == dates_label_idx + 1
                and not ced.data_assunzione):
            date_matches = re.findall(r'\d{2}-\d{2}-\d{4}', text)
            if len(date_matches) >= 2:
                ced.data_assunzione = date_matches[1].replace("-", "/")
            # Qualifica: text after the last date on the same line
            if date_matches:
                last_date = date_matches[-1]
                after_dates = text[text.rfind(last_date) + len(last_date):].strip()
                if after_dates and not re.match(r'^\d', after_dates):
                    ced.qualifica = after_dates
            continue

        # Contratto: generic match for CCNL name in metadata lines
        if not ced.contratto and re.search(r'(?:Commercio|Terziario|CCNL|Assicurativo)', text, re.IGNORECASE):
            ccnl_m = re.search(r'((?:Commercio\s+e\s+terziario|CCNL\s+\w+|Assicurativo)[^\d]*)', text, re.IGNORECASE)
            if ccnl_m:
                ced.contratto = ccnl_m.group(1).strip()
            continue

        # INPS data line: "4 26 26 20 160,00 31"
        if re.match(r'^\d+\s+\d+\s+\d+\s+\d+\s+\d', text):
            nums = text.split()
            if len(nums) >= 4:
                try:
                    sett = int(nums[0])
                    gg_r = int(nums[1])
                    if sett <= 5 and gg_r <= 31:
                        ced.inps.settimane = sett
                        ced.inps.gg_retribuiti = gg_r
                        ced.inps.gg_lavorati = int(nums[2]) if len(nums) > 2 else 0
                        if len(nums) > 3:
                            ced.inps.ore_lavorate = _pdn(nums[4]) if len(nums) > 4 else ZERO
                            ced.inps.gg_lavorati = int(nums[3])
                        if len(nums) > 5:
                            ced.irpef.gg_detrazione = int(nums[-1])
                except (ValueError, IndexError):
                    pass


def _parse_salary(ced: Cedolino, lines: list[dict]):
    """Parse salary components."""
    for i, line in enumerate(lines):
        text = line["text"]

        # Salary component values line (with 5-decimal values)
        # "1.911,80000 537,52000 11,36000 7,35000 1.603,40000"
        if re.search(r'\d+,\d{5}.*\d+,\d{5}', text):
            nums = _extract_nums(text)
            vals = [n for n in nums if len(n.split(",")[1]) == 5]

            # Check if this follows a PAGA BASE header
            has_scatti = False
            for j in range(max(0, i - 3), i):
                if "SCATTI" in lines[j]["text"] and "PAGA BASE" in lines[j]["text"]:
                    has_scatti = True
                elif "PAGA BASE" in lines[j]["text"]:
                    has_scatti = "SCATTI" in lines[j]["text"]

            if has_scatti and len(vals) >= 6:
                ced.paga_base = _pdn(vals[0])
                ced.scatti = _pdn(vals[1])
                ced.contingenza = _pdn(vals[2])
                ced.terzo_elemento = _pdn(vals[3])
                ced.edr = _pdn(vals[4])
                if "EBT" in lines[max(0, i - 2)]["text"]:
                    ced.ebt = _pdn(vals[4])
                ced.superminimo = _pdn(vals[5])
            elif len(vals) >= 5:
                ced.paga_base = _pdn(vals[0])
                ced.contingenza = _pdn(vals[1])
                ced.terzo_elemento = _pdn(vals[2])
                ced.edr = _pdn(vals[3])
                ced.superminimo = _pdn(vals[4])
            continue

        # TOTALE line: "12-2025 4.071,43000"
        if "TOTALE" in text:
            continue
        m = re.match(r'\d{2}-\d{4}\s+(\d[\d.]*,\d{5})', text)
        if m:
            ced.retribuzione_mensile = _pdn(m.group(1))


def _parse_voci(ced: Cedolino, lines: list[dict], is_continuation: bool = False):
    """Parse voci variabili from structured lines."""
    in_voci = False

    for line in lines:
        text = line["text"]
        words = line["words"]

        # Detect start of voci section
        if "VOCIsVARIABILI" in text or "VOCI VARIABILI" in text.replace("s", " "):
            in_voci = True
            continue

        # On continuation page, start from the beginning
        if is_continuation and not in_voci:
            # Check if we see voce-like patterns
            for w in words:
                if RE_VOCE_CODE.match(w["text"]):
                    in_voci = True
                    break

        if not in_voci:
            continue

        # End of voci section
        if "CONGUAGLIO" in text or "PROGRESSIVI" in text:
            in_voci = False
            continue

        # Find voce codes in the words
        for w in words:
            wtext = w["text"]
            m = RE_VOCE_CODE.match(wtext)
            if m:
                voce = _parse_voce_line(m.group(1), wtext[len(m.group(1)):], text, words, w)
                if voce:
                    # Check for duplicates
                    is_dup = False
                    for existing in ced.voci:
                        if (existing.codice == voce.codice and
                                existing.competenze == voce.competenze and
                                existing.trattenute == voce.trattenute and
                                existing.descrizione == voce.descrizione):
                            is_dup = True
                            break
                    if not is_dup:
                        ced.voci.append(voce)
                break  # One voce per line


def _parse_voce_line(code: str, desc_start: str, full_text: str,
                     words: list[dict], code_word: dict) -> VoceItem | None:
    """Parse a single voce line using the cleaned line text."""
    voce = VoceItem(codice=code)

    # Extract the portion of the line text after the voce code
    code_pattern = re.escape(code)
    m = re.search(code_pattern + r'(.+)', full_text)
    if not m:
        return None
    rest = m.group(1).strip()

    # Remove leading/trailing stars
    rest = re.sub(r'^\*\s*', '', rest).strip()

    # Extract description (text before first number)
    desc_match = re.match(r'^([A-Za-z][A-Za-z0-9 ./\'-]+?)(?:\s+(?:MP\s+)?(?=\d)|\s*$)', rest)
    if desc_match:
        voce.descrizione = desc_match.group(1).strip()
        rest = rest[desc_match.end():].strip()
    else:
        voce.descrizione = desc_start.strip()

    # Extract all numeric tokens from rest
    # Pattern: base(5dec) qty+unit imponibile pct% amount or similar
    all_nums = re.findall(r'-?\d[\d.]*,\d+', rest)
    has_pct = re.search(r'(\d[\d.]*,\d+)%', rest)
    has_unit = re.search(r'(\d[\d.]*,\d+)(GG|ORE)', rest)

    # Contribution codes
    contrib_codes = {"Z00000", "Z00055", "Z00087", "Z20000", "Z20003", "Z31000"}

    if code in contrib_codes:
        # Format: imponibile pct% amount
        if has_pct:
            pct_val = _pdn(has_pct.group(1))
            # Find imponibile (number before %) and amount (after %)
            before_pct = rest[:has_pct.start()]
            after_pct = rest[has_pct.end():]
            imp_nums = re.findall(r'-?\d[\d.]*,\d+', before_pct)
            amt_nums = re.findall(r'-?\d[\d.]*,\d+', after_pct)

            if imp_nums:
                voce.base = pct_val  # Store percentage in base for contribution
                voce.trattenute = _pdn(amt_nums[-1]) if amt_nums else ZERO
                # Store imponibile as an attribute
                voce.__dict__['_imponibile'] = _pdn(imp_nums[-1])
            else:
                voce.trattenute = _pdn(all_nums[-1]) if all_nums else ZERO
        elif all_nums:
            voce.trattenute = _pdn(all_nums[-1])

        if "C/Ditta" in rest:
            # Skip c/ditta entries from trattenute
            voce.trattenute = ZERO

    elif code == "Z20008":
        # TFR trasferito
        if all_nums:
            voce.trattenute = _pdn(all_nums[0])

    elif code == "ZP9960":
        # Arrotondamento: can be negative
        neg_match = re.search(r'(-\d[\d.]*,\d+)', full_text)
        pos_match = re.search(r'(\d[\d.]*,\d+)', rest)
        if neg_match:
            voce.competenze = _pdn(neg_match.group(1))
        elif pos_match:
            voce.competenze = _pdn(pos_match.group(1))

    elif code.startswith("F"):
        # Fiscal codes
        if code == "F03020":  # Ritenute IRPEF
            voce.trattenute = _pdn(all_nums[-1]) if all_nums else ZERO
        elif code in ("F09110", "F09130", "F09140"):
            # Addizionali: last number is the amount
            voce.trattenute = _pdn(all_nums[-1]) if all_nums else ZERO
            # Also capture "Residuo" amount
            if "Residuo" in rest and len(all_nums) >= 2:
                voce.trattenute = _pdn(all_nums[-1])
        elif code == "F01998":
            voce.trattenute = _pdn(all_nums[-1]) if all_nums else ZERO
        elif code in ("F02000", "F02010", "F08993", "F09100"):
            voce.competenze = _pdn(all_nums[-1]) if all_nums else ZERO
        else:
            voce.competenze = _pdn(all_nums[-1]) if all_nums else ZERO
    else:
        # Regular voce: base qty+unit competenze
        if has_unit:
            voce.quantita = _pdn(has_unit.group(1))
            voce.unita_misura = "GIORNI" if has_unit.group(2) == "GG" else has_unit.group(2)

        # Find base (5 decimal places)
        base_match = re.search(r'(\d[\d.]*,\d{5})(?!%|GG|ORE)', rest)
        if base_match:
            voce.base = _pdn(base_match.group(1))

        # Competenze is the last 2-decimal number
        comp_nums = [n for n in all_nums if len(n.split(',')[1]) == 2]
        if comp_nums:
            voce.competenze = _pdn(comp_nums[-1])

        # For recovery/deduction voci (Recupero, Rimborso)
        if code in ("Z00015", "Z00016") and voce.competenze:
            voce.trattenute = voce.competenze
            voce.competenze = ZERO

    # Set flags for regular voci
    regular_codes = {"Z00020", "Z00251", "Z00010", "Z00015", "Z00016",
                     "Z00019", "Z00256", "Z00261", "Z01139", "Z01146",
                     "Z50022", "Z50000", "Z00101"}
    if code in regular_codes:
        voce.flag_c = voce.flag_i = voce.flag_t = voce.flag_n = True

    return voce


def _parse_progressivi(ced: Cedolino, lines: list[dict], full_text: str):
    """Parse PROGRESSIVI section."""
    for i, line in enumerate(lines):
        if "PROGRESSIVI" in line["text"] and "Imp. INPS" in line["text"]:
            # Next line has the values
            if i + 1 < len(lines):
                nums = _extract_nums(lines[i + 1]["text"])
                vals = [_pdn(n) for n in nums]
                if len(vals) >= 4:
                    ced.progressivo_imp_inps = vals[0]
                    ced.progressivo_imp_inail = vals[1]
                    ced.progressivo_imp_irpef = vals[2]
                    ced.progressivo_irpef_pagata = vals[3]
            return

    # Fallback: look in full text
    m = re.search(
        r'PROGRESSIVI\s+Imp\.\s*INPS\s+Imp\.\s*INAIL\s+Imp\.\s*IRPEF\s+IRPEF\s+pagata\s*\n'
        r'\s*([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)',
        full_text
    )
    if m:
        ced.progressivo_imp_inps = _pdn(m.group(1))
        ced.progressivo_imp_inail = _pdn(m.group(2))
        ced.progressivo_imp_irpef = _pdn(m.group(3))
        ced.progressivo_irpef_pagata = _pdn(m.group(4))


def _parse_tfr(ced: Cedolino, lines: list[dict], full_text: str):
    """Parse TFR section."""
    for line in lines:
        text = line["text"]
        if "Retribuzione utile T.F.R." in text:
            nums = _extract_nums(text)
            if nums:
                ced.tfr.retribuzione_utile_tfr = _pdn(nums[-1])

        if "Quota T.F.R." in text:
            nums = _extract_nums(text)
            if nums:
                ced.tfr.tfr_mese = _pdn(nums[-1])

    # TFR progressivi: "T.F.R. F.do 31/12 Rivalutaz. Imp.rival. Quota anno TFR a fondi Anticipi"
    for i, line in enumerate(lines):
        text = line["text"]
        if "T.F.R." in text and "F.do 31/12" in text:
            if i + 1 < len(lines):
                nums = _extract_nums(lines[i + 1]["text"])
                vals = [_pdn(n) for n in nums]
                if len(vals) >= 2:
                    ced.tfr.tfr_annuo = vals[0]
                    ced.tfr.tfr_a_fondo_pensione = vals[1]
                elif len(vals) == 1:
                    ced.tfr.tfr_annuo = vals[0]
            return

    # TFR from voci (Z20008)
    for v in ced.voci:
        if v.codice == "Z20008":
            ced.tfr.tfr_a_fondo_pensione = v.trattenute
            break


def _parse_ratei(ced: Cedolino, lines: list[dict], full_text: str):
    """Parse RATEI section."""
    in_ratei = False
    for i, line in enumerate(lines):
        text = line["text"]

        if "RATEI" in text and "TOTALE" in text:
            in_ratei = True
            continue

        if not in_ratei:
            continue

        # End markers
        if "COMUNICAZIONI" in text or "NETTOsDELsMESE" in text or "NETTO" in text:
            break

        # Parse ratei lines: "Ferie 58,67000 146,66666 144,00000 61,33666 ORE"
        ratei_match = re.match(
            r'(Ferie|Perm\.Ex-Fs|Perm\.R\.O\.L|Permessi|Perm\.ROL)\s+'
            r'([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s+(ORE)?',
            text
        )
        if ratei_match:
            ced.ratei.append(RateiRow(
                tipo=ratei_match.group(1),
                residuo_ap=_pdn(ratei_match.group(2)),
                maturato=_pdn(ratei_match.group(3)),
                goduto=_pdn(ratei_match.group(4)),
                saldo=_pdn(ratei_match.group(5)),
            ))
            continue

        # Alternative: just numbers with label
        m = re.match(r'(\w[\w.]+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)', text)
        if m:
            tipo = m.group(1)
            if tipo in ("Ferie", "Permessi"):
                ced.ratei.append(RateiRow(
                    tipo=tipo,
                    residuo_ap=_pdn(m.group(2)),
                    maturato=_pdn(m.group(3)),
                    goduto=_pdn(m.group(4)),
                    saldo=_pdn(m.group(5)),
                ))


def _parse_totali(ced: Cedolino, lines: list[dict], full_text: str):
    """Parse totali section."""
    for i, line in enumerate(lines):
        text = line["text"]

        if "TOTALEsCOMPETENZE" in text or "TOTALE COMPETENZE" in text.replace("s", " "):
            nums = _extract_nums(text)
            if nums:
                ced.totali.totale_competenze = _pdn(nums[-1])

        if "TOTALEsTRATTENUTE" in text or "TOTALE TRATTENUTE" in text.replace("s", " "):
            nums = _extract_nums(text)
            if nums:
                ced.totali.totale_trattenute = _pdn(nums[-1])

        if "ARROTONDAMENTO" in text:
            nums = _extract_nums(text)
            if nums:
                ced.totali.arrotondamento = _pdn(nums[-1])

        if "NETTOsDELsMESE" in text or "NETTO DEL MESE" in text.replace("s", " "):
            continue

        # Net amount: "2.729,00€" or just amount after NETTO line
        if "€" in text:
            m = re.search(r'([\d.,]+)€', text)
            if m:
                ced.totali.netto_in_busta = _pdn(m.group(1))


def _parse_conguaglio(ced: Cedolino, lines: list[dict], full_text: str):
    """Parse CONGUAGLIO section (December)."""
    for i, line in enumerate(lines):
        text = line["text"]
        if "CONGUAGLIO" in text and "Annuale" not in text:
            continue
        if "Annuale" in text:
            # "Annuale 51.074,88 14.602,20 14.602,20 786,90 LOM 289,27 H930"
            nums = _extract_nums(text)
            vals = [_pdn(n) for n in nums]
            if len(vals) >= 3:
                ced.irpef.imponibile_fiscale_anno = vals[0]
                ced.irpef.irpef_lorda_anno = vals[1]
                ced.irpef.irpef_trattenuta_anno = vals[2]
                if len(vals) >= 4:
                    ced.addizionale_regionale = vals[3]
                if len(vals) >= 5:
                    ced.addizionale_comunale_saldo = vals[4]


def _extract_fiscal_data(ced: Cedolino):
    """Extract IRPEF and contribution data from parsed voci."""
    for v in ced.voci:
        code = v.codice

        # INPS contributions
        if code == "Z00000":
            _add_contribution(ced, "IVS", v)
        elif code == "Z00055":
            _add_contribution(ced, "FIS", v)
        elif code == "Z00087":
            _add_contribution(ced, "CIGS", v)
        elif code == "Z31000":
            _add_contribution(ced, "EST", v)
        elif code == "Z00010" and "Contributo IVS" in v.descrizione:
            _add_contribution(ced, "ADD_IVS", v)

        # FON.TE
        if code == "Z20000":
            if "vol" in v.descrizione.lower():
                _add_contribution(ced, "FONTE_VOL", v)
            elif "C/Ditta" in v.descrizione:
                pass  # Skip c/ditta entries
            else:
                _add_contribution(ced, "FONTE_BASE", v)
        elif code == "Z20003":
            _add_contribution(ced, "FONTE_VOL", v)

        # IRPEF data
        if code == "F02000":  # Imponibile IRPEF
            ced.irpef.imponibile_fiscale_mese = v.competenze
        elif code == "F02010":  # IRPEF lorda
            ced.irpef.irpef_lorda_mese = v.competenze
        elif code == "F03020":  # Ritenute IRPEF
            ced.irpef.irpef_netta_mese = v.trattenute
            ced.irpef.irpef_piu_imp_sost = v.trattenute

        # Addizionali
        if code == "F09110":
            ced.addizionale_regionale += v.trattenute
        elif code == "F09130":
            ced.addizionale_comunale_saldo += v.trattenute
        elif code == "F09140":
            ced.addizionale_comunale_acconto += v.trattenute

    # Set INPS section from contributions
    for c in ced.contributi:
        if c.descrizione == "IVS":
            ced.inps.imponibile_contrib_arrot_mese = c.imponibile
            ced.inps.imponibile_contributivo_mese = c.imponibile

    # Use progressivi for annual values
    ced.inps.imponibile_contributivo_anno = ced.progressivo_imp_inps
    ced.irpef.imponibile_fiscale_anno = ced.progressivo_imp_irpef
    ced.irpef.irpef_trattenuta_anno = ced.progressivo_irpef_pagata

    # Calculate totale_contributi from all INPS contributions
    total = ZERO
    for c in ced.contributi:
        total += c.importo_dipendente
    ced.inps.totale_contributi = total


def _add_contribution(ced: Cedolino, desc: str, voce: VoceItem):
    """Add a contribution from a parsed voce."""
    # Check for duplicates
    for existing in ced.contributi:
        if existing.descrizione == desc and existing.importo_dipendente == voce.trattenute:
            return

    # Parse the imponibile and percentage from the voce's base field
    # In Zucchetti, the contribution line has: code desc imponibile percentage amount
    contrib = ContributionItem(descrizione=desc)

    if desc == "EST":
        contrib.importo_dipendente = voce.trattenute
    else:
        # The voce parser stores imponibile in _imponibile and percentage in base
        contrib.imponibile = voce.__dict__.get('_imponibile', ZERO)
        contrib.percentuale = voce.base
        contrib.importo_dipendente = voce.trattenute

    ced.contributi.append(contrib)
