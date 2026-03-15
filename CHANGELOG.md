# Changelog

## [0.6.0] - 2026-03-15

### Added
- Suite di regression test con pytest e snapshot golden CSV
- Test a 3 livelli: strutturali, numerici (tolleranza 0.02), diff completo
- Test parametrizzato di format detection su tutti i PDF di input
- Script `update_snapshots.py` per rigenerare i golden file dopo modifiche intenzionali
- Flag `--update-snapshots` in pytest per aggiornamento inline

## [0.5.0] - 2026-03-15

### Changed
- Convert project from standalone skill to Claude Code plugin (`cedolini`)
- Skill moved from root `SKILL.md` to `skills/verifica/SKILL.md`
- Plugin manifest added at `.claude-plugin/plugin.json`
- Script paths in SKILL.md now use `${CLAUDE_PLUGIN_ROOT}/` prefix
- Invocation changed from `/verificacedolino` to `/cedolini:verifica`

## [0.4.0] - 2026-03-15

### Changed
- Transforming the project into a skill that in itself contains everything needed to function

## [0.3.0] - 2026-03-01

### Added
- Explanation layer: disclaimer, intro, section explanations in Italian
- "Da lordo a netto" breakdown (yearly aggregate + monthly detail)
- Voce categorization via regex patterns (`config/explanations.yaml`)
- Filtered glossary of payroll terms (only terms present in data)
- Validation notes replacing raw formulas in anomaly tables
- CLI flags `--no-explain` (backward compat) and `--no-monthly-explain`

### Changed
- Report sections renamed with descriptive titles (e.g. "Contributi INPS (previdenziali)")
- Anomaly table column "Formula" replaced with "Nota" (human-readable explanation)

## [0.2.0] - 2026-03-01

### Added
- Architettura parser registry (auto-registrazione, nessun dispatch hardcoded)
- Configurazione CCNL via file YAML (`config/ccnl/`)
- Supporto CCNL Assicurativo (contributi: IVS, Fondo Solidarieta')
- Parser ADP legacy (formato 2007, multi-cedolino in un PDF)
- Parser Hornet/HCM (formato 2016)
- Scaglioni IRPEF storici (2007-2022)
- Campo `ccnl` nel modello Cedolino
- Scansione PDF anche nella root della cartella input (non solo sottodirectory)
- Versioning semver, CLAUDE.md, CHANGELOG.md

### Changed
- Validatore INPS ora guidato da config CCNL (non piu' aliquote hardcoded)
- Report e CSV con colonne contributi dinamiche
- `parse_pdf()` puo' restituire `list[Cedolino]` per PDF multi-cedolino

## [0.1.0] - 2026-02-16

### Added
- Estrazione dati da cedolini PDF (Sistemi S.p.A., Zucchetti)
- Estrazione dati da CUD
- Validazione netto in busta, INPS, IRPEF, TFR, ratei, cross-check CUD
- Report Markdown per anno e complessivo
- Skill Claude Code `/verificacedolino`
