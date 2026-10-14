# Project_LR_Neoload_Conversion

The **lr2nl** toolkit converts LoadRunner Web (HTTP/HTML) scripts into NeoLoad as-code projects from their source, without re-recording. The projects can be used in the NeoLoad GUI and on NeoLoad Web.

- Converts 25-100 scripts in one batch, with a desktop UI or a command line
- Covers transactions, requests, headers, cookies, correlations, checks, parameters, think time, pacing, control flow and custom C code
- Gives every script a status (SUCCESS / PARTIAL / FAILED), a success percentage and a list of items to review. Unsupported items are flagged, never dropped silently.
- Needs no Python packages: only the standard library

## Quick start

```powershell
cd Project_LR_Neoload_Conversion
.\run_tests.cmd                                   # check that the toolkit works
.\run_ui.cmd                                      # UI: pick the source and output folders, click Convert
python -m lr2nl convert -s sample_data\lr_scripts -o ..\sample_output   # CLI on the sample dataset
```

## Documents

| Document | Contents |
|----------|----------|
| [docs/MIGRATION_PLAN.md](docs/MIGRATION_PLAN.md) | Scope, phases, mapping table, validation, risks, timeline, acceptance criteria |
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | Step-by-step usage: UI, CLI, NeoLoad GUI, NeoLoad Web, reports, troubleshooting |
| [PREREQUISITES.md](PREREQUISITES.md) | Software, versions, licenses, access rights, GitHub permissions |

## Layout

```
lr2nl/            converter package
  cparse.py         LoadRunner C parser
  lrproject.py      script folder loader (.c/.h, .prm, default.cfg/.usp)
  mapper.py         mapping engine LoadRunner -> NeoLoad (scoring and review items)
  jstranslate.py    C -> JavaScript translation and LoadRunner shim
  generator.py      NeoLoad as-code project writer and NeoLoad CLI scripts
  yamlout.py        dependency-free YAML writer
  report.py         CSV / HTML / JSON reports
  converter.py      batch orchestration
  ui.py             desktop UI (tkinter)
  cli.py            command line
tests/            unit tests and a 100-script batch test
sample_data/      sample LoadRunner scripts (success with review items, control flow, broken)
docs/             migration plan and user guide
```
