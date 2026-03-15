# Analisi Cedolini

> v0.5.0

Toolkit per validare cedolini italiani (buste paga) da PDF.

Estrae dati, valida calcoli (INPS, IRPEF, TFR, netto, ratei), cross-check con CUD e genera report Markdown con spiegazioni in italiano semplice.

## Installazione

### Da sorgente (sviluppo locale)

```bash
git clone https://github.com/marcomd/cedolini
claude --plugin-dir ./cedolini
```

### Da marketplace custom

Se il plugin viene pubblicato in un marketplace, installalo con:

```bash
/plugin marketplace add https://github.com/marcomd/cedolini.git
/plugin install cedolini@marcomd-cedolini
```

## Formati supportati

- **Sistemi S.p.A. (JOB)** — rilevato dal footer "JOB - Copyright Sistemi S.p.A."
- **Zucchetti** — rilevato dal footer "Zucchetti"
- **ADP Legacy** — rilevato dal footer "www.it-adp.com" (multi-cedolino, 2 pagine per cedolino)
- **Hornet/HCM** — rilevato dal marker "HRZ_MODEL" nell'header
- **CUD** — Certificazione Unica Agenzia Entrate

## CCNL supportati

- **Commercio e Terziario** — IVS, CIGS, FIS, FON.TE, EST
- **Assicurativo** — IVS, Fondo Solidarieta'

Il CCNL viene auto-rilevato dal contratto o dalla ragione sociale. Le aliquote contributive sono configurate in `config/ccnl/` (file YAML).

## Quick start con Claude Code

Posiziona i PDF dei cedolini in una cartella organizzata per anno:

```
i-miei-cedolini/
  2023/          # PDF cedolini 2023
  2024/          # PDF cedolini 2024
  CUD/           # Certificazioni Uniche
```

Poi lancia la skill:

```
/cedolini:verifica i-miei-cedolini/
```

Analisi Cedolini esegue estrazione, validazione e report in automatico.

## Uso standalone (senza Claude Code)

```bash
pip install -r requirements.txt

# Fase 1: Estrazione dati da PDF → CSV
python3 scripts/extract.py --input-dir cartella-pdf/

# Fase 2: Validazione calcoli
python3 scripts/validate.py --input-dir cartella-pdf/

# Fase 3: Generazione report Markdown (con spiegazioni)
python3 scripts/report.py --input-dir cartella-pdf/

# Report senza spiegazioni (output compatibile con v0.2)
python3 scripts/report.py --input-dir cartella-pdf/ --no-explain

# Report senza breakdown mensili (solo riepilogo annuale, piu' compatto)
python3 scripts/report.py --input-dir cartella-pdf/ --no-monthly-explain
```

L'output viene scritto in `output/` (personalizzabile con `--output-dir`).

## Struttura input

La cartella input puo' contenere PDF nella root e/o in sottodirectory. Tutte le sottodirectory vengono scansionate e i PDF auto-rilevati in base al contenuto.

## Output generato

| File                     | Contenuto                             |
| ------------------------ | ------------------------------------- |
| `cedolini_summary.csv`   | Dati estratti da ogni cedolino        |
| `cedolini_voci.csv`      | Dettaglio voci retributive            |
| `cud_summary.csv`        | Dati estratti dalle CUD               |
| `validation_results.csv` | Risultati di ogni singola validazione |
| `report_ANNO.md`         | Report per anno                       |
| `report_all.md`          | Report completo multi-anno            |

## Report esplicativo (v0.3.0)

I report Markdown includono di default:

- **Disclaimer** — il report verifica la coerenza interna, non costituisce verifica legale
- **Introduzione** — come leggere competenze, trattenute, netto, PASS/FAIL/WARNING
- **Da lordo a netto** — breakdown per categoria (riepilogo annuale + dettaglio mensile) che mostra come si arriva dal lordo al netto
- **Spiegazioni sezioni** — breve introduzione prima di INPS, IRPEF, TFR, anomalie
- **Note anomalie** — spiegazione in italiano al posto della formula tecnica
- **Glossario** — solo i termini effettivamente presenti nei dati (IVS, TFR, scaglioni, ecc.)

Le voci del cedolino vengono categorizzate automaticamente (stipendio base, straordinario, permessi, ferie, mensilita' aggiuntiva, ecc.) tramite pattern configurabili in `config/explanations.yaml`.

## Validazioni

- **Netto in busta** — competenze - trattenute + arrotondamento
- **Contributi INPS** — guidati da config CCNL (IVS, CIGS, FIS, FON.TE, EST, Fondo Solidarieta', etc.)
- **IRPEF** — scaglioni mensili (storici 2007-2024+), detrazioni lavoro dipendente, progressivo annuale
- **TFR** — invariante `tfr_mese + contr_agg = retrib_utile / 13.5`
- **Ratei** — continuita' ferie, permessi, ROL (cumulativi YTD)
- **Cross-check CUD** — reddito, ritenute, INPS, previdenza complementare

## Requisiti

- Python 3.12+
- pdfplumber >= 0.10.0
- pandas >= 2.0.0
- pyyaml >= 6.0
