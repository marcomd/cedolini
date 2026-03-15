---
name: verifica
description: >
  Valida cedolini italiani (buste paga) da PDF. Estrae dati, valida calcoli
  (INPS, IRPEF, TFR, netto, ratei), cross-check CUD, genera report Markdown.
  Formati: Sistemi S.p.A., Zucchetti, ADP Legacy, Hornet/HCM, CUD.
  CCNL: Commercio e Terziario, Assicurativo.
allowed-tools: Bash(python3:*)
argument-hint: "[cartella-pdf]"
---

# Verifica Cedolini - Validazione Cedolini Italiani

## Prerequisiti

- Python 3.12+
- Dipendenze: `pip install -r ${CLAUDE_PLUGIN_ROOT}/requirements.txt` (pdfplumber, pandas, pyyaml)

## Workflow

### 1. Determina la cartella input

Se `$ARGUMENTS` è fornito, usalo come cartella input PDF.
Altrimenti chiedi all'utente la cartella contenente i PDF dei cedolini.

La cartella puo' contenere PDF nella root e/o in sottodirectory (es. `2023/`, `2024/`, `CUD/`).

### 2. Esegui le tre fasi

```bash
# Fase 1: Estrazione dati da PDF → CSV
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/extract.py --input-dir "$INPUT_DIR" --output-dir output/

# Fase 2: Validazione calcoli
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/validate.py --input-dir "$INPUT_DIR" --output-dir output/

# Fase 3: Generazione report Markdown
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/report.py --input-dir "$INPUT_DIR" --output-dir output/
```

Se `--input-dir` non viene specificato, il default è `input/` nella root del progetto.

### 3. Presenta i risultati

Dopo l'esecuzione:
1. Mostra il riepilogo validazione (PASS/FAIL/WARNING)
2. Se ci sono FAIL o WARNING, leggi `output/report_all.md` e mostra i dettagli
3. Indica dove trovare il report completo (`output/report_all.md`) e quelli per anno

## Output generato

| File | Contenuto |
|------|-----------|
| `output/cedolini_summary.csv` | Dati estratti da ogni cedolino |
| `output/cedolini_voci.csv` | Dettaglio voci retributive |
| `output/cud_summary.csv` | Dati estratti dalle CUD |
| `output/validation_results.csv` | Risultati di ogni singola validazione |
| `output/report_ANNO.md` | Report Markdown per anno |
| `output/report_all.md` | Report Markdown completo |

## Struttura input attesa

```
cartella-pdf/
  2023/          # Cedolini anno 2023 (PDF)
  2024/          # Cedolini anno 2024 (PDF)
  2025/          # ...
  CUD/           # Certificazioni Uniche (PDF)
```

Le sottodirectory possono avere qualsiasi nome (vengono tutte scansionate).
I file PDF vengono auto-rilevati in base al contenuto.

## Formati supportati

- **Sistemi S.p.A. (JOB)**: footer "JOB - Copyright Sistemi S.p.A."
- **Zucchetti**: footer "Zucchetti"
- **ADP Legacy**: footer "www.it-adp.com" (multi-cedolino, 2 pagine per cedolino)
- **Hornet/HCM**: marker "HRZ_MODEL" nell'header
- **CUD**: Certificazione Unica Agenzia Entrate

## CCNL supportati

- **Commercio e Terziario**: IVS, CIGS, FIS, FON.TE, EST
- **Assicurativo**: IVS, Fondo Solidarieta'

Il CCNL viene auto-rilevato. Le aliquote sono configurate in `${CLAUDE_PLUGIN_ROOT}/config/ccnl/` (YAML).

## Validazioni eseguite

- **Netto in busta**: competenze - trattenute + arrotondamento
- **Contributi INPS**: guidati da config CCNL (aliquote e tolleranze per contributo)
- **IRPEF**: scaglioni mensili (storici 2007-2024+), detrazioni lavoro dipendente, progressivo annuale
- **TFR**: invariante `tfr_mese + contr_agg = retrib_utile / 13.5`
- **Ratei**: continuita' ferie/permessi/ROL (cumulativi YTD)
- **Cross-check CUD**: reddito, ritenute IRPEF, INPS, previdenza complementare

Per dettagli su formule, toleranze e quirks dei parser, vedi:
- [patterns.md](${CLAUDE_PLUGIN_ROOT}/patterns.md) - Quirks parser e formule validatori
- [validation-rules.md](${CLAUDE_PLUGIN_ROOT}/validation-rules.md) - Regole di validazione dettagliate
