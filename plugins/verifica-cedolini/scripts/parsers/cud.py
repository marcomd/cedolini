"""Parser per Certificazione Unica (CUD)."""

import re
import pdfplumber
from decimal import Decimal
from pathlib import Path
from scripts.models import CertificazioneUnica, parse_italian_decimal, ZERO
from scripts.parsers.base import register_parser


def detect_cud(pdf_path: str, full_text: str) -> bool:
    """Detect CUD format."""
    name_lower = Path(pdf_path).stem.lower()
    if "cud" in name_lower:
        return True
    if "CERTIFICAZIONE" in full_text and "UNICA" in full_text and "D.P.R." in full_text:
        return True
    return False


register_parser("cud", detect_cud, lambda path: parse_cud(path))


def _pdn(s: str) -> Decimal:
    return parse_italian_decimal(s)


def parse_cud(pdf_path: str) -> CertificazioneUnica:
    """Parse a CUD PDF."""
    cu = CertificazioneUnica(file_path=pdf_path)

    with pdfplumber.open(pdf_path) as pdf:
        all_text = []
        for page in pdf.pages:
            text = page.extract_text() or ""
            all_text.append(text)

    full_text = "\n".join(all_text)

    # Determine year: "RELATIVA ALL'ANNO 2023" or "UNICA2024"
    m = re.search(r"RELATIVA ALL'ANNO\s+(\d{4})", full_text)
    if m:
        cu.anno_riferimento = int(m.group(1))

    m = re.search(r'UNICA\s*(\d{4})', full_text)
    if m:
        cu.anno_cu = int(m.group(1))

    # Parse page 2: fiscal data
    if len(all_text) >= 2:
        _parse_fiscal(cu, all_text[1])

    # Parse page 3: previdenza complementare
    if len(all_text) >= 3:
        _parse_previdenza(cu, all_text[2])

    # Parse page 5: INPS data
    if len(all_text) >= 5:
        _parse_inps(cu, all_text[4])

    return cu


def _parse_fiscal(cu: CertificazioneUnica, text: str):
    """Parse fiscal data from page 2."""
    lines = text.split("\n")

    for i, line in enumerate(lines):
        # Reddito lavoro dipendente (punto 1)
        # "COMPILAZIONE 1 49.721,20 2 3 4"
        if "COMPILAZIONE" in line and re.search(r'\b1\s+([\d.,]+)\s+2', line):
            m = re.search(r'\b1\s+([\d.,]+)\s+2', line)
            if m:
                cu.reddito_lavoro_dipendente = _pdn(m.group(1))

        # Giorni (punto 6): "365 DD MM YYYY X"
        if re.match(r'\s*(\d{3})\s+\d{2}\s+\d{2}\s+\d{4}', line):
            m = re.match(r'\s*(\d+)', line)
            if m:
                cu.giorni_lavoro_dipendente = int(m.group(1))

        # Ritenute IRPEF (punto 21), Addizionale regionale (22), Addizionali comunali (26, 27, 29)
        # "21 14.042,42 22 763,50 26 116,28 27 281,49 29 119,33"
        if re.search(r'\b21\s+[\d.,]+\s+22\s+[\d.,]+', line):
            m = re.search(r'\b21\s+([\d.,]+)', line)
            if m:
                cu.ritenute_irpef = _pdn(m.group(1))

            m = re.search(r'\b22\s+([\d.,]+)', line)
            if m:
                cu.addizionale_regionale = _pdn(m.group(1))

            m = re.search(r'\b26\s+([\d.,]+)', line)
            if m:
                cu.acconto_add_comunale = _pdn(m.group(1))

            m = re.search(r'\b27\s+([\d.,]+)', line)
            if m:
                cu.saldo_add_comunale = _pdn(m.group(1))

            m = re.search(r'\b29\s+([\d.,]+)', line)
            if m:
                cu.acconto_add_comunale_succ = _pdn(m.group(1))


def _parse_previdenza(cu: CertificazioneUnica, text: str):
    """Parse previdenza complementare from page 3."""
    lines = text.split("\n")

    for line in lines:
        # Punto 412: previdenza complementare
        # "1 1.418,68" (after 411 412 header)
        # or "1 1.384,54"
        if re.match(r'^\s*1\s+([\d.,]+)\s*$', line):
            m = re.match(r'^\s*1\s+([\d.,]+)', line)
            if m:
                val = _pdn(m.group(1))
                if val > Decimal("100"):  # Previdenza is typically > 100
                    cu.previdenza_complementare = val


def _parse_inps(cu: CertificazioneUnica, text: str):
    """Parse INPS data from page 5."""
    lines = text.split("\n")

    for line in lines:
        # Matricola INPS + imponibile previdenziale + contributi
        # "1 NNNNNNNNNN 2 X 3 4 amount 5 6 amount"
        # Field 1 = matricola (10-digit), field 4 = imponibile, field 6 = contributi
        matricola_m = re.search(r'\b1\s+(\d{10})\s+2', line)
        if matricola_m:
            cu.matricola_inps = matricola_m.group(1)

            m = re.search(r'\b4\s+([\d.,]+)\s+5', line)
            if m:
                cu.imponibile_previdenziale = _pdn(m.group(1))

            m = re.search(r'\b6\s+([\d.,]+)', line)
            if m:
                cu.contributi_lavoratore = _pdn(m.group(1))
