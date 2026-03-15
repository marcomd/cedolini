# VerificaCedolino - Regole di Validazione

## Tolleranze

| Validatore | Tolleranza | Motivo |
|-----------|-----------|--------|
| Netto in busta | 0.01 | Arrotondamento centesimi |
| Contributi INPS (%) | 0.01 | Arrotondamento su imponibile arrotondato |
| EST | 0.00 | Importo fisso 2.00 |
| FON.TE | 0.01 | Base imponibile propria della contribuzione |
| IRPEF mensile | 0.01 | Calcolo su scaglioni |
| IRPEF annuale | 1.00 | Accumulo arrotondamenti 12 mesi |
| TFR invariante | 0.02 | contributo_agg calcolato su base giornaliera |
| TFR annuale | 0.50 | Somma 12 quote mensili |
| Ratei saldo | 0.01 | Cumulativi YTD |
| CUD reddito | 1.00 | Arrotondamento annuale su somma 12/13 mesi |
| CUD ritenute IRPEF | 1.00 | Conguaglio incluso |
| CUD previdenza | 5.00 | c/ditta stimato come 2x c/dipendente |

## Formule Chiave

### Netto in busta
```
Sistemi:  netto = competenze - trattenute + arr_attuale - arr_precedente
Zucchetti: netto = competenze - trattenute + arrotondamento
```

### INPS - Contributi dipendente (CCNL-driven)
```
Contributo = imponibile * aliquota%  (da config/ccnl/*.yaml)
Se il cedolino stampa la propria aliquota, si usa quella per coerenza interna.
```

Esempio Commercio: IVS 9.19%, CIGS 0.30%, FIS 0.26667%, EST 2.00 (fisso), FON.TE su imponibile proprio.
Esempio Assicurativo: IVS 9.19%, Fondo Solidarieta' 0.125%.

### IRPEF mensile
```
irpef_lorda = somma scaglioni su imponibile_fiscale_mese
irpef_netta = irpef_lorda - detrazione_lavoro_dipendente
```

Scaglioni storici:
- 2007-2021: 23% fino 15k, 27% fino 28k, 38% fino 55k, 41% fino 75k, 43% oltre
- 2022-2023: 23% fino 15k, 25% fino 28k, 35% fino 50k, 43% oltre
- 2024+: 23% fino 28k, 35% fino 50k, 43% oltre

### TFR
```
quota_lorda_mese = retrib_utile_tfr / 13.5
tfr_mese + contributo_agg = quota_lorda_mese
```

### Ratei (cumulativi YTD)
```
saldo = residuo_anno_precedente + maturato_ytd - goduto_ytd
```
Continuita' anno: saldo dicembre = residuo_ap gennaio anno successivo.

### CUD Cross-check
```
reddito_CUD = somma(imponibile_fiscale_mese) per l'anno
ritenute_CUD = irpef_netta_anno dell'ultimo cedolino dell'anno
previdenza_CUD = FONTE_c/dip * 2 + EST_annuo + contr_agg_tfr_annuo
```
