"""Modello dati normalizzato per cedolini italiani."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional
import re

ZERO = Decimal("0")


def parse_italian_decimal(text: str) -> Decimal:
    """Parse Italian number format: '1.234,56' -> Decimal('1234.56').

    Handles:
    - '1.234,56' -> 1234.56
    - '1.234,56-' -> -1234.56
    - '-1.234,56' -> -1234.56
    - '1234,56' -> 1234.56
    - '1234' -> 1234
    """
    if not text or not text.strip():
        return ZERO
    text = text.strip()
    negative = False
    if text.endswith("-"):
        negative = True
        text = text[:-1].strip()
    if text.startswith("-"):
        negative = True
        text = text[1:].strip()
    # Remove thousand separators (dots), replace decimal comma with dot
    text = text.replace(".", "").replace(",", ".")
    try:
        val = Decimal(text)
    except Exception:
        return ZERO
    return -val if negative else val


@dataclass
class VoceItem:
    """Singola riga voce del cedolino."""
    codice: str = ""
    descrizione: str = ""
    unita_misura: str = ""  # GIORNI, ORE, RATEI, MP, %
    quantita: Decimal = ZERO
    base: Decimal = ZERO
    competenze: Decimal = ZERO
    trattenute: Decimal = ZERO
    flag_c: bool = False  # Imponibile contributivo
    flag_i: bool = False  # Imponibile IRPEF
    flag_t: bool = False  # Imponibile TFR
    flag_n: bool = False  # Considerato nel netto


@dataclass
class ContributionItem:
    """Singolo contributo (INPS, FON.TE, etc.)."""
    descrizione: str = ""
    imponibile: Decimal = ZERO
    percentuale: Decimal = ZERO
    importo_dipendente: Decimal = ZERO
    importo_ditta: Decimal = ZERO


@dataclass
class INPSSection:
    """Sezione QTA/INPS del cedolino."""
    settimane: int = 0
    gg_retribuiti: int = 0
    gg_lavorati: int = 0
    ore_lavorate: Decimal = ZERO
    imponibile_contributivo_anno: Decimal = ZERO
    contributi_anno: Decimal = ZERO
    imponibile_contributivo_mese: Decimal = ZERO
    imponibile_contrib_arrot_mese: Decimal = ZERO
    totale_contributi: Decimal = ZERO


@dataclass
class IRPEFSection:
    """Sezione IRPEF (MESE e ANNO) del cedolino."""
    # Mese
    imponibile_fiscale_mese: Decimal = ZERO
    irpef_lorda_mese: Decimal = ZERO
    detrazione_lavoro_dip: Decimal = ZERO
    gg_detrazione: int = 0
    irpef_netta_mese: Decimal = ZERO
    imposta_sostitutiva: Decimal = ZERO
    irpef_piu_imp_sost: Decimal = ZERO
    # Anno
    imponibile_fiscale_anno: Decimal = ZERO
    irpef_lorda_anno: Decimal = ZERO
    detrazione_lavoro_dip_anno: Decimal = ZERO
    gg_detrazione_anno: int = 0
    irpef_netta_anno: Decimal = ZERO
    irpef_trattenuta_anno: Decimal = ZERO
    irpef_conguaglio: Decimal = ZERO


@dataclass
class TFRSection:
    """Sezione TFR del cedolino."""
    retribuzione_utile_tfr: Decimal = ZERO
    contributo_agg_tfr: Decimal = ZERO
    tfr_mese: Decimal = ZERO
    tfr_annuo: Decimal = ZERO
    fondo_tfr_31_12_ap: Decimal = ZERO
    anticipazioni: Decimal = ZERO
    tfr_spettante_azienda: Decimal = ZERO
    tfr_a_fondo_pensione: Decimal = ZERO
    # TFR IRPEF
    imponibile_lordo: Decimal = ZERO
    riduzione: Decimal = ZERO
    imponibile_netto: Decimal = ZERO
    perc_irpef: Decimal = ZERO
    irpef_tfr: Decimal = ZERO


@dataclass
class RateiRow:
    """Singola riga ratei (ferie/permessi)."""
    tipo: str = ""  # Ferie, Permessi R.O.L., Ex Festivita', Perm.Ex-Fs
    residuo_ap: Decimal = ZERO
    maturato: Decimal = ZERO
    goduto: Decimal = ZERO
    saldo: Decimal = ZERO
    unita: str = "ORE"


@dataclass
class TotaliSection:
    """Sezione totali del cedolino."""
    totale_competenze: Decimal = ZERO
    totale_trattenute: Decimal = ZERO
    arrotondamento_precedente: Decimal = ZERO
    arrotondamento_attuale: Decimal = ZERO
    arrotondamento: Decimal = ZERO  # Zucchetti: valore unico
    netto_in_busta: Decimal = ZERO


@dataclass
class Cedolino:
    """Contenitore principale per un cedolino."""
    # Metadata
    file_path: str = ""
    formato: str = ""  # "sistemi", "zucchetti", "adp_legacy", "hornet", "csspaghe"
    num_pagine: int = 1
    ccnl: str = ""  # CCNL id, e.g. "commercio", "assicurativo"

    # Header
    cod_azienda: str = ""
    ragione_sociale: str = ""
    pos_inps: str = ""
    pos_inail: str = ""
    cod_dipendente: str = ""
    cognome_nome: str = ""
    codice_fiscale: str = ""
    qualifica: str = ""
    contratto: str = ""
    livello: str = ""
    data_assunzione: str = ""

    # Periodo
    mese_retribuzione: str = ""  # "GENNAIO 2024", "TREDICESIMA 2024"
    anno: int = 0
    mese: int = 0  # 1-12, 13 per tredicesima, 14 per quattordicesima
    is_tredicesima: bool = False

    # Elementi retributivi
    paga_base: Decimal = ZERO
    contingenza: Decimal = ZERO
    superminimo: Decimal = ZERO
    terzo_elemento: Decimal = ZERO
    edr: Decimal = ZERO  # Elemento Distinto della Retribuzione
    ebt: Decimal = ZERO
    scatti: Decimal = ZERO
    retribuzione_mensile: Decimal = ZERO
    retribuzione_oraria: Decimal = ZERO
    retribuzione_giornaliera: Decimal = ZERO

    # Voci
    voci: list = field(default_factory=list)  # list[VoceItem]

    # Contributi
    contributi: list = field(default_factory=list)  # list[ContributionItem]

    # Sezioni
    inps: INPSSection = field(default_factory=INPSSection)
    irpef: IRPEFSection = field(default_factory=IRPEFSection)
    tfr: TFRSection = field(default_factory=TFRSection)
    ratei: list = field(default_factory=list)  # list[RateiRow]
    totali: TotaliSection = field(default_factory=TotaliSection)

    # Addizionali (estratte dalle voci)
    addizionale_regionale: Decimal = ZERO
    addizionale_comunale_saldo: Decimal = ZERO
    addizionale_comunale_acconto: Decimal = ZERO

    # Progressivi (Zucchetti)
    progressivo_imp_inps: Decimal = ZERO
    progressivo_imp_inail: Decimal = ZERO
    progressivo_imp_irpef: Decimal = ZERO
    progressivo_irpef_pagata: Decimal = ZERO


@dataclass
class CertificazioneUnica:
    """Dati estratti dalla Certificazione Unica (CUD)."""
    file_path: str = ""
    anno_riferimento: int = 0  # Anno a cui si riferisce (CU2024 -> 2023)
    anno_cu: int = 0  # Anno della CU

    # Dati fiscali
    reddito_lavoro_dipendente: Decimal = ZERO  # Punto 1
    giorni_lavoro_dipendente: int = 0  # Punto 6
    ritenute_irpef: Decimal = ZERO  # Punto 21
    addizionale_regionale: Decimal = ZERO  # Punto 22
    acconto_add_comunale: Decimal = ZERO  # Punto 26
    saldo_add_comunale: Decimal = ZERO  # Punto 27
    acconto_add_comunale_succ: Decimal = ZERO  # Punto 29

    # Previdenza complementare
    previdenza_complementare: Decimal = ZERO  # Punto 412

    # Dati INPS
    matricola_inps: str = ""  # Punto 1 sez. previdenziale
    imponibile_previdenziale: Decimal = ZERO  # Punto 3/4
    contributi_lavoratore: Decimal = ZERO  # Punto 6

    # TFR
    tfr_a_fondo: Decimal = ZERO  # Punto 813 (se presente)


@dataclass
class ValidationResult:
    """Risultato di una validazione."""
    nome: str = ""
    anno: int = 0
    mese: int = 0
    mese_label: str = ""
    status: str = ""  # PASS, FAIL, WARNING
    atteso: str = ""
    effettivo: str = ""
    differenza: str = ""
    tolleranza: str = ""
    formula: str = ""
    note: str = ""


# Mapping mesi italiani
MESI_IT = {
    "GENNAIO": 1, "FEBBRAIO": 2, "MARZO": 3, "APRILE": 4,
    "MAGGIO": 5, "GIUGNO": 6, "LUGLIO": 7, "AGOSTO": 8,
    "SETTEMBRE": 9, "OTTOBRE": 10, "NOVEMBRE": 11, "DICEMBRE": 12,
    "TREDICESIMA": 13, "QUATTORDICESIMA": 14,
    "Gennaio": 1, "Febbraio": 2, "Marzo": 3,
    "Aprile": 4, "Maggio": 5, "Giugno": 6, "Luglio": 7,
    "Agosto": 8, "Settembre": 9, "Ottobre": 10, "Novembre": 11,
    "Dicembre": 12,
}


def parse_periodo(text: str) -> tuple[int, int, bool]:
    """Parse periodo retribuzione -> (anno, mese, is_tredicesima).

    Examples:
        'GENNAIO 2024' -> (2024, 1, False)
        'TREDICESIMA 2024' -> (2024, 13, True)
        'Ottobre 2025' -> (2025, 10, False)
        'Dicembre 2025 AGG.' -> (2025, 12, False)
    """
    text = text.strip()
    # Remove suffixes like "AGG."
    text = re.sub(r'\s+AGG\.?\s*$', '', text)

    parts = text.split()
    if len(parts) >= 2:
        mese_str = parts[0].upper()
        anno = int(parts[-1])
        if "TREDICESIMA" in mese_str or "13" in mese_str:
            return anno, 13, True
        if "QUATTORDICESIMA" in mese_str or "14" in mese_str:
            return anno, 14, False
        mese = MESI_IT.get(parts[0], MESI_IT.get(mese_str, 0))
        return anno, mese, False
    # Single word without year (e.g. "TREDICESIMA")
    if len(parts) == 1:
        mese_str = parts[0].upper()
        if "TREDICESIMA" in mese_str:
            return 0, 13, True
        if "QUATTORDICESIMA" in mese_str:
            return 0, 14, False
        mese = MESI_IT.get(parts[0], MESI_IT.get(mese_str, 0))
        return 0, mese, False
    return 0, 0, False
