from scripts.ccnl import detect_ccnl, load_all_ccnl
from scripts.models import Cedolino
from pathlib import Path

def test_detect_ccnl_from_qualifica_or_contratto():
    configs = load_all_ccnl(Path(__file__).parent.parent / "config" / "ccnl")
    ced = Cedolino(
        # contratto="CCNL Metalmeccanico",
        qualifica="IMP C3",
        ragione_sociale="Nome Azienda",
    )
    detected = detect_ccnl(ced, configs)
    assert detected is not None
    assert detected.id == "metalmeccanico"