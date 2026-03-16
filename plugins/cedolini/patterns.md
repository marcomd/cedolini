# VerificaCedolino - Parser & Validator Patterns

## Parser Quirks

### Sistemi S.p.A.
- Multi-page: page with "TOTALE COMPETENZE" + "NETTO IN BUSTA" has the sections (not always last page)
- 2023 had 2-page cedolini with SEGUE marker; page 2 may be attendance record
- Contribution lines are two-column (INPS left, FON.TE right); split at keyword offset >= 15
- CIGS description contains "L.234/2021" - must use Italian decimal regex (not generic number regex)
- Same-description contributions accumulate (e.g. IVS on base + una tantum)
- Totali line: 5 values (comp, tratt, arr_prec, arr_att, netto) or 4 values (comp, tratt, single_arr, netto)
- Trailing minus sign: "8,00-" means -8.00

### Zucchetti
- PDF renders some voce codes as individual character glyphs -> `_merge_fragments()` reconstructs them
- "s" separator in labels: `TOTALEsCOMPETENZE` -> strip/replace
- Split decimals: "405 ,37" -> fix with regex before parsing
- Period embedded in longer line -> use `re.search` not `re.match`
- Tredicesima detected from Z50000 voce content (filenames may be misleading)

### ADP Legacy
- Multi-cedolino: N pages = N/2 cedolini x 2 pages (odd=voci/totals, even=fiscal/previdenziale/TFR)
- Returns `list[Cedolino]` from `parse_pdf()`
- Detection: "www.it-adp.com" in footer or CEDOLINO + 4-digit voce codes
- Key voce codes: 1000=paga_base, 5154=IVS, 5483=FDO_SOLID, 5244=ADD_IVS, 7833=IRPEF, 7139=TFR, 8853/8833=arrotondamento
- Company name extracted from "D I T T A" marker (text before it)
- Employee data via codice fiscale regex + "COD.FISC" / "S E SS O" labels
- TREDICESIMA/QUATTORDICESIMA: period line has no year -> infer from other cedolini in same PDF
- Ferie layout: (Spettanti, Maturati, Goduti, Saldo) where Spettanti=annual entitlement (not residuo_ap)
- CCNL detected automatically via `detect_ccnl()` in validate phase

### Hornet/HCM
- Detection: "HRZ_MODEL" in header text
- 2 pages per cedolino (single cedolino per PDF)
- Company name: spaced-out text before "PERIODO DI RETRIBUZIONE", auto-collapsed
- Employee data via codice fiscale regex on employee info line
- Voce format: `CODE **|Description` or `CODE Description`
- Contribution codes: 005=IVS, 043=FDO_SOLID
- Addizionali: only count trattenute when line has >= 3 decimal numbers (avoid fiscal reference values)
- Arrotondamento already embedded in comp/tratt via TNARR voce -> set arrotondamento=ZERO
- Netto: look for `****AMOUNT` pattern
- Fiscal grid on page 2 with labeled fields (IMPOSTA LORDA, DETR. LAV. DIP, etc.)
- CCNL detected automatically via `detect_ccnl()` in validate phase

### CSSPaghe
- Detection: "LIBRO UNICO DEL LAVORO" AND "TOTALE ELEMENTI RETRIBUTIVI" in text
- Single page per cedolino, 3 pdfplumber-extractable tables
- Table 0 (11 rows x 33 cols): header/company/employee data with "label\nvalue" cells
- Table 1 (4 rows x 20 cols): voci retributive (multi-line cells, one row for all voci)
- Table 2 (9 rows x 8 cols): TFR, INPS, IRPEF, arrotondamento, netto, progressivi, ferie/permessi
- TOTALE COMPETENZE in Table 1 Row 3 may have spaced digits: "160 7 , 1 4" -> clean spaces before parsing
- EST/ES0 voci: EST (quota ditta) shows parenthesized informational amount, ES0 (quota dip) has ritenute
- IRPEF-TOTAL = monthly IRPEF retained/refunded (does NOT include year-end addizionali)
- BONUS DL6614: positive = tax credit (reduces trattenute), negative = recovery (increases trattenute)
- Netto: `comp - (voci_rit + INPS + IRPEF_TOTAL - BONUS) + (arrot_corr - arrot_prec)`
- Addizionali regionali/comunali shown in December are year-end calculations, deducted next year
- CCNL detected automatically via `detect_ccnl()` in validate phase

### CUD
- Multi-page modulistic format
- Key points: 1 (reddito), 21 (ritenute), 22 (add. regionale), 412 (prev. complementare)
- INPS section: matricola, imponibile, contributi

## Validator Formulas

### Netto
- Sistemi: `comp - tratt + arr_attuale - arr_preced`
- Zucchetti: `comp - tratt + arr`
- ADP Legacy: `comp - tratt + arr_attuale - arr_preced` (same as Sistemi)
- Hornet: `comp - tratt` (arrotondamento=ZERO, embedded in voci)
- CSSPaghe: `comp - (voci_rit + INPS + IRPEF_TOTAL - BONUS) + (arr_corr - arr_prec)`

### INPS
- Contributions now CCNL-driven via `config/ccnl/*.yaml`
- Validator prefers cedolino's own printed rate (percentuale) for internal consistency
- Falls back to config rate only when no rate is printed
- FON.TE: use contribution's own `imponibile` (not `retrib_utile_tfr` - differs in December)
- EST: fixed 2.00 (Commercio only)

### TFR
- `tfr_mese + contributo_agg = retrib_utile / 13.5` (tight tolerance 0.02)
- contributo_agg varies monthly due to daily-rate calculation (~0.5% reference)
- New layout (Zucchetti): only net quota shown, check implied contr. against 0.5%

### CUD Cross-check
- Ritenute IRPEF: use `irpef_netta_anno` (includes conguaglio)
- Previdenza complementare: `FONTE c/dip * 2 + EST + contr_agg_tfr` (approx c/ditta)

### Ratei
- Values are **cumulative YTD**, not monthly deltas
- `saldo = residuo_ap + maturato_ytd - goduto_ytd`
- residuo_ap is constant within a year (end-of-previous-year carryover)
- Continuity check: Dec saldo = next Jan residuo_ap
