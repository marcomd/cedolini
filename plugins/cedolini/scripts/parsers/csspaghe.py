"""Parser per cedolini CSSPaghe (Libro Unico del Lavoro)."""

import re
import pdfplumber
from decimal import Decimal
from scripts.models import (
    Cedolino, VoceItem, RateiRow,
    parse_italian_decimal, parse_periodo, ZERO
)
from scripts.parsers.base import register_parser

RE_NUM = re.compile(r'-?\d[\d.]*,\d+')


def _pdn(s: str) -> Decimal:
    return parse_italian_decimal(s)


def _cell_val(cell) -> Decimal:
    """Extract the last decimal value from a 'label\\nvalue' cell."""
    if not cell:
        return ZERO
    for part in reversed(str(cell).split('\n')):
        m = RE_NUM.search(part.strip())
        if m:
            return _pdn(m.group())
    return ZERO


def _clean_spaced(s: str) -> str:
    """Remove spaces within a number: '160 7 , 1 4' -> '1607,14'."""
    return s.replace(" ", "") if s else ""


def detect_csspaghe(pdf_path: str, full_text: str) -> bool:
    """Detect CSSPaghe format: LIBRO UNICO + TOTALE ELEMENTI RETRIBUTIVI."""
    return ("LIBRO UNICO DEL LAVORO" in full_text
            and "TOTALE ELEMENTI RETRIBUTIVI" in full_text)


register_parser("csspaghe", detect_csspaghe, lambda path: parse_csspaghe(path))


def parse_csspaghe(pdf_path: str) -> Cedolino:
    """Parse a CSSPaghe cedolino PDF (single page, 3 tables)."""
    ced = Cedolino(file_path=pdf_path, formato="csspaghe")

    with pdfplumber.open(pdf_path) as pdf:
        ced.num_pagine = len(pdf.pages)
        tables = pdf.pages[0].extract_tables()

    if len(tables) < 3:
        return ced

    _parse_header(ced, tables[0])
    _parse_salary(ced, tables[0])
    voci_ritenute = _parse_voci(ced, tables[1])
    _parse_bottom(ced, tables[2], voci_ritenute)

    return ced


def _parse_header(ced: Cedolino, t: list):
    """Parse header/employee data from Table 0."""
    if not t:
        return

    # Row 0: period (left cell) and company info (right cell)
    r0 = t[0]
    left = str(r0[0] or "")
    for line in left.split('\n'):
        m = re.search(
            r'(GENNAIO|FEBBRAIO|MARZO|APRILE|MAGGIO|GIUGNO|LUGLIO|AGOSTO|'
            r'SETTEMBRE|OTTOBRE|NOVEMBRE|DICEMBRE|TREDICESIMA)\s+(\d{4})',
            line, re.IGNORECASE
        )
        if m:
            ced.mese_retribuzione = f"{m.group(1)} {m.group(2)}"
            ced.anno, ced.mese, ced.is_tredicesima = parse_periodo(
                ced.mese_retribuzione)

    # Company cell (contains "Cod.Inps")
    for cell in r0:
        if cell and "Cod.Inps" in str(cell):
            lines = str(cell).split('\n')
            ced.ragione_sociale = re.sub(r'\s+\d+\s*$', '', lines[0]).strip()
            for ln in lines:
                m = re.search(r'Cod\.Inps\s+(\d+)', ln)
                if m:
                    ced.pos_inps = m.group(1)
            break

    # Row 1: codice dipendente
    if len(t) > 1 and t[1][0] and 'CODICE DIP' in str(t[1][0]):
        m = re.search(r'\n(\d+)', str(t[1][0]))
        if m:
            ced.cod_dipendente = m.group(1)

    # Row 2: codice fiscale and cognome/nome
    if len(t) > 2:
        for cell in t[2]:
            s = str(cell or "")
            cf = re.search(r'[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]', s)
            if cf:
                ced.codice_fiscale = cf.group()
                break
        for cell in t[2]:
            s = str(cell or "")
            if '\n' in s and len(s) > 15:
                name = re.sub(r'\s+\d+\s*$', '', s.split('\n')[0].strip())
                if len(name) > 5:
                    ced.cognome_nome = name
                    break

    # Row 3: qualifica, livello
    if len(t) > 3:
        for cell in t[3]:
            s = str(cell or "")
            if 'QUALIFICA' in s and '\n' in s:
                ced.qualifica = s.split('\n')[-1].strip()
            elif 'LIVELLO' in s and '\n' in s:
                ced.livello = s.split('\n')[-1].strip()

    # Row 4: data assunzione
    if len(t) > 4:
        for cell in t[4]:
            s = str(cell or "")
            if 'DATA INIZIO' in s and '\n' in s:
                d = s.split('\n')[-1].strip()
                if len(d) == 8 and d.isdigit():
                    ced.data_assunzione = f"{d[:2]}/{d[2:4]}/{d[4:]}"
                break

    # Row 7: POS INAIL, GG INPS, ore
    if len(t) > 7:
        for cell in t[7]:
            s = str(cell or "")
            if 'INAIL' in s and '\n' in s:
                m = re.search(r'(\d+)\s+(\d+)', s.split('\n')[-1])
                if m:
                    ced.pos_inail = f"{m.group(1)}/{m.group(2)}"
            elif 'GG INPS' in s:
                v = _cell_val(s)
                if v:
                    ced.inps.gg_retribuiti = int(v)
            elif 'GG DETRAZIONI' in s:
                v = _cell_val(s)
                if v:
                    ced.irpef.gg_detrazione = int(v)
            elif 'ORE LAVORATE' in s:
                ced.inps.ore_lavorate = _cell_val(s)


def _parse_salary(ced: Cedolino, t: list):
    """Parse salary components from Table 0 rows 8-10."""
    if len(t) <= 8:
        return

    for cell in t[8]:
        s = str(cell or "")
        if 'Paga Base' in s:
            ced.paga_base = _cell_val(s)
        elif 'Contingenza' in s:
            ced.contingenza = _cell_val(s)
        elif 'Ass. Suppl' in s:
            ced.superminimo = _cell_val(s)

    # TOTALE ELEMENTI RETRIBUTIVI from row 10
    if len(t) > 10:
        for cell in t[10]:
            if cell:
                m = RE_NUM.search(str(cell))
                if m:
                    ced.retribuzione_mensile = _pdn(m.group())
                    break


def _parse_voci(ced: Cedolino, t: list) -> Decimal:
    """Parse voci from Table 1. Returns voci total ritenute."""
    if len(t) < 4:
        return ZERO

    # Row 1: multi-line voci data
    r1 = t[1]
    codes = str(r1[0] or "").split('\n')
    descs = str(r1[1] or "").split('\n')

    for i, code in enumerate(codes):
        code = code.strip()
        if not code:
            continue
        voce = VoceItem(
            codice=code,
            descrizione=descs[i].strip() if i < len(descs) else ""
        )
        ced.voci.append(voce)

    # Totals from Row 3 (numbers may be spaced: "160 7 , 1 4")
    r3 = t[3]
    tot_comp = ZERO
    tot_rit = ZERO
    if len(r3) > 15 and r3[15]:
        m = RE_NUM.search(_clean_spaced(str(r3[15])))
        if m:
            tot_comp = _pdn(m.group())
    if len(r3) > 18 and r3[18]:
        m = RE_NUM.search(_clean_spaced(str(r3[18])))
        if m:
            tot_rit = _pdn(m.group())

    ced.totali.totale_competenze = tot_comp
    return tot_rit


def _parse_bottom(ced: Cedolino, t: list, voci_ritenute: Decimal):
    """Parse bottom section (Table 2): TFR, INPS, IRPEF, arrotondamento, netto."""
    if len(t) < 6:
        return

    # Row 0: TFR + imponibili
    for cell in t[0]:
        s = str(cell or "")
        if 'TFR DISPONIBILE' in s:
            ced.tfr.tfr_spettante_azienda = _cell_val(s)
        elif 'TFR IMPONIBILE' in s:
            ced.tfr.retribuzione_utile_tfr = _cell_val(s)
        elif 'TFR ACC. MESE' in s:
            ced.tfr.tfr_mese = _cell_val(s)
        elif 'INPS - IMPONIBILE' in s:
            ced.inps.imponibile_contrib_arrot_mese = _cell_val(s)

    # Row 1: INPS contributions
    for cell in t[1]:
        s = str(cell or "")
        if 'INPS - CONTRIBUTI' in s:
            ced.inps.totale_contributi = _cell_val(s)
        elif 'TOT CTR PRE' in s:
            v = _cell_val(s)
            if v:
                ced.inps.totale_contributi = v

    # Row 2: IRPEF line 1
    for cell in t[2]:
        s = str(cell or "")
        if 'IRPEF-REDDITO' in s:
            ced.irpef.imponibile_fiscale_mese = _cell_val(s)
        elif 'RIT. LORDA' in s:
            ced.irpef.irpef_lorda_mese = _cell_val(s)
        elif 'Lav. Dipend' in s:
            ced.irpef.detrazione_lavoro_dip = _cell_val(s)
        elif 'RIT. NETTA' in s:
            ced.irpef.irpef_netta_mese = _cell_val(s)

    # Row 3: IRPEF line 2 (conguaglio, addizionali, TOTAL)
    irpef_total = ZERO
    for cell in t[3]:
        s = str(cell or "")
        if 'IRPEF-CONGUAGLIO' in s:
            ced.irpef.irpef_conguaglio = _cell_val(s)
        elif 'ADD.LE REG' in s:
            ced.addizionale_regionale = _cell_val(s)
        elif 'ADD.LE COM' in s:
            ced.addizionale_comunale_saldo = _cell_val(s)
        elif 'IRPEF-TOTAL' in s:
            irpef_total = _cell_val(s)

    ced.irpef.irpef_piu_imp_sost = irpef_total
    if not ced.irpef.irpef_netta_mese:
        ced.irpef.irpef_netta_mese = irpef_total

    # Row 4: Bonus DL6614
    bonus = ZERO
    for cell in t[4]:
        s = str(cell or "")
        if 'BONUS DL6614' in s:
            bonus = _cell_val(s)

    # Row 5: arrotondamento + netto
    arrot_prec = ZERO
    arrot_corr = ZERO
    for cell in t[5]:
        s = str(cell or "")
        if 'ARROT. PREC' in s:
            arrot_prec = _cell_val(s)
        elif 'ARROT. CORR' in s:
            arrot_corr = _cell_val(s)
        elif 'N E T T O' in s:
            ced.totali.netto_in_busta = _cell_val(s)

    ced.totali.arrotondamento_precedente = arrot_prec
    ced.totali.arrotondamento_attuale = arrot_corr
    ced.totali.arrotondamento = arrot_corr - arrot_prec

    # Compute totale_trattenute: voci ritenute + INPS + IRPEF - bonus
    ced.totali.totale_trattenute = (
        voci_ritenute + ced.inps.totale_contributi + irpef_total - bonus
    )

    # Rows 6-7: Progressivi and ratei
    if len(t) > 6:
        for cell in t[6]:
            s = str(cell or "")
            if 'PR. IMP. PREV' in s:
                ced.progressivo_imp_inps = _cell_val(s)
            elif 'PR. RED. FISC' in s:
                ced.progressivo_imp_irpef = _cell_val(s)
        _parse_ratei_row(ced, t[6], "Ferie")

    if len(t) > 7:
        _parse_ratei_row(ced, t[7], "Permessi R.O.L.")

    if len(t) > 8:
        for cell in t[8]:
            s = str(cell or "")
            if 'PR. RIT. FISCALI' in s:
                ced.progressivo_irpef_pagata = _cell_val(s)


def _parse_ratei_row(ced: Cedolino, row: list, tipo: str):
    """Parse ferie/permessi from a bottom-section row."""
    maturate = godute = residue = ZERO
    for cell in row:
        s = str(cell or "")
        if 'AC - Maturat' in s:
            maturate = _cell_val(s)
        elif 'AC - Godut' in s:
            godute = _cell_val(s)
        elif 'RESIDU' in s:
            residue = _cell_val(s)

    if maturate or godute or residue:
        ced.ratei.append(RateiRow(
            tipo=tipo, maturato=maturate, goduto=godute, saldo=residue
        ))
