# User Guide: LoadRunner to NeoLoad Converter (lr2nl)

This guide covers installing the converter, converting scripts, running the results in the NeoLoad GUI and NeoLoad Web, reading the reports, and troubleshooting.

## 1. Installation

1. Install the items in [PREREQUISITES.md](../PREREQUISITES.md). Python is the only requirement for the converter itself.
2. Get the toolkit:
   ```powershell
   git clone https://github.com/gangai4k/performance-testing.git
   cd performance-testing\Project_LR_Neoload_Conversion
   ```
3. Check that it works:
   ```powershell
   .\run_tests.cmd
   ```
   The output should end with `OK`.

There is nothing else to install: no virtual environment and no `pip install`.

## 2. Prepare the source folder

Put the LoadRunner scripts in one folder, one subfolder per script, exactly as VuGen saves them:

```
C:\LR_Scripts\
  Login_Search\        Action.c  vuser_init.c  vuser_end.c  globals.h  *.prm  *.dat  default.cfg  default.usp  *.usr
  Checkout\            ...
```

A folder counts as a script when it contains `Action.c`, `vuser_init.c` or a `.usr` file. You can also select a single script folder.

## 3. Convert with the UI

1. Start the UI by double-clicking `run_ui.cmd`, or run `python -m lr2nl ui`.
2. **LoadRunner source folder**: click *Browse...* and select the folder from step 2. The status bar shows how many scripts were found.
3. **NeoLoad output folder**: click *Browse...* and select an empty folder outside the source folder. The default is `<source>_neoload`.
4. Optionally, set **Scenario users** and **Duration** for the generated scenario. The defaults are 1 user for 5 minutes.
5. Click **Convert**. The grid fills in as each script finishes:
   - **Script Name**
   - **Conversion Status**: SUCCESS, PARTIAL or FAILED
   - **Success %**
   - **Items to review**

   The log panel shows progress and the report paths.
6. Click **Open HTML report** to see the details.

## 4. Convert with the command line (batch, CI)

```powershell
python -m lr2nl convert --source C:\LR_Scripts --output C:\NL_Projects
python -m lr2nl convert -s C:\LR_Scripts -o C:\NL_Projects --users 10 --duration 15m --workers 8
python -m lr2nl convert -s C:\LR_Scripts -o C:\NL_Projects --fail-under 85   # exit code 2 if any script is FAILED or below 85%
```

`convert.cmd <source> <output>` is a shortcut for the first command.

## 5. What the output contains

```
C:\NL_Projects\
  <Script>\
    default.yaml            NeoLoad as-code project: servers, variables, user path (init/actions/end), population, scenario
    data\*.csv              parameter data files copied from the .dat files
    custom_js\<Script>.js   JavaScript translated from C code, plus the lr2nl shim (only if needed)
  reports\
    conversion_report.html  summary and per-script details
    conversion_summary.csv  one row per script
    manual_review.csv       one row per item to review
    conversion_summary.json machine-readable results
  neoload_commands.ps1 / .sh  validate all projects; run one on NeoLoad Web
```

In `default.yaml`, comment lines that start with `[LR ...]` mark the exact position of a LoadRunner construct that needs manual work, for example `# [LR if (...)] BEGIN - rebuild as NeoLoad 'If' logical action`.

## 6. Interpreting the reports

**Status**

| Status | Meaning | What to do |
|--------|---------|-----------|
| SUCCESS | Every construct was converted with equivalent behaviour. There are no REVIEW items. | Validate and run |
| PARTIAL | The project was generated, but some constructs are approximated or need a NeoLoad action added | Work through the REVIEW items for this script |
| FAILED | Parse error, conversion error, no convertible content, or less than 40% match | Read the error, fix the source or convert manually |

**Success %** is a weighted score over every construct found in the script (requests, transactions, checks, correlations, parameters, think times, logic and so on):

| Weight | Meaning |
|--------|---------|
| 1.0 | Converted 1:1 |
| 0.75 | Auto-translated to JavaScript; verify it |
| 0.5 | Approximated; manual change needed |
| 0 | Not converted; rebuild it |

**manual_review.csv** columns: `Script, Severity, File, Line, Construct, Message`.

- `REVIEW` means an action is needed. The file and line point to the LoadRunner source.
- `INFO` means the behaviour is preserved, but something differs from LoadRunner. Read these once.

Filter by `Construct` to work in bulk. For example, handle every `if-flow` item first, then every `custom-function` item.

## 7. Typical remediation steps

| Construct in the report | How to fix it in the NeoLoad GUI |
|-------------------------|----------------------------------|
| `if-flow` / `switch-flow` | Insert an **If** logical action at the `[LR if]` marker. Move the inline steps into *Then*. Uncomment or rebuild the steps of the commented `else` branch into *Else*. Use the JavaScript condition given in the message. |
| `for-flow` / `while-flow` | Wrap the steps between the BEGIN and END markers in a **Loop** (fixed count) or **While** action |
| `custom-logic`, `error-handling`, `*-logic` | Add a **JavaScript** action at the marker. Paste the shim (top of `custom_js/<Script>.js`) and the block for that line. |
| `custom-function` / `custom-function-call` | Put the translated function into a shared JavaScript library (or the JavaScript action), and call it where marked |
| `lr_exit`, `return` | Add **Stop virtual user** or **Go to next iteration** |
| `transaction-end` (LR_FAIL) | Add an assertion, or `context.fail(...)` in JavaScript, where the script forced the failure |
| `pacing` | Set pacing on the user path's Actions container, and remove the generated end-of-iteration delay |
| `parameter` (Date/Time etc.) | Create the NeoLoad variable (JavaScript or built-in) with the same name |
| `correlation` notes | Open the extractor in the GUI and test it on the recorded response |

## 8. Running in the NeoLoad GUI

1. Open the NeoLoad GUI and open the converted project: **File > Open project** and select the script's `default.yaml` (as-code project). If your NeoLoad version cannot open YAML directly, create an empty project and include the YAML file in it (as-code include), or use NeoLoad Web (section 9).
2. Check that **Variables** shows the file variables and that their data files resolve to `data\*.csv`.
3. Select the user path and click **Check User Path** (1 VU, 1 iteration). Compare each request with the LoadRunner replay (Migration Plan, section 5).
4. Apply the remediation steps from section 7. Save the project. GUI-only changes are stored in the NeoLoad project, so commit that as well.
5. Run the scenario `<Script>_scenario` from the **Runtime** tab.

## 9. Running on NeoLoad Web

The output folder contains `neoload_commands.ps1` (Windows) and `neoload_commands.sh` (Linux/macOS). Both use the official NeoLoad CLI.

```powershell
pip install neoload                     # once
$env:NLW_TOKEN = "<your NeoLoad Web API token>"         # never commit this
$env:NLW_URL   = "https://neoload-api.saas.neotys.com"  # only for on-premise or another region

cd C:\NL_Projects
.\neoload_commands.ps1                                    # validates every default.yaml
.\neoload_commands.ps1 -Project .\Checkout_REST\default.yaml -Zone <zoneId> -Lgs 1   # upload and run one script
```

The script runs `neoload login`, `neoload test-settings ... createorpatch LR2NL_<Script>`, `neoload project --path <Script> upload` and `neoload run`. Results appear in NeoLoad Web under the test `LR2NL_<Script>`.

## 10. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Found 0 LoadRunner script(s)` | Wrong folder level, or scripts without `Action.c`/`vuser_init.c`/`.usr` | Select the parent folder of the script folders |
| `python` is not recognized | Python is not on PATH | Reinstall Python with "Add to PATH", or use `py -m lr2nl ...` |
| UI does not start: `No module named tkinter` | Python was installed without Tcl/Tk | Re-run the Python installer > Modify > enable "tcl/tk and IDLE" (Linux: `sudo apt install python3-tk`) |
| FAILED with `Parse error ... unbalanced '{'` | The source has a syntax error or an unusual macro | Open the file and line from the report, fix the source, and convert again (VuGen compiles cleanly before conversion) |
| `neoload validate` reports an unknown key | Your NeoLoad version uses a different as-code key name | Adjust the key once in `lr2nl/generator.py` or `lr2nl/mapper.py`, re-run the batch, and report it to the toolkit owner |
| Extractor returns `NOT_FOUND` | Boundary changed, or HTML encoding differs | Test the regexp on the response in the NeoLoad GUI. Switch to a JSONPath or XPath extractor where possible. |
| Data file columns are wrong | `.dat` file has no header line, or uses a different delimiter | Add a header line to the `.dat` file (LoadRunner shows column names) or fix `Delimiter` in the `.prm` file |
| Garbled characters | Script saved in a legacy code page | The converter tries UTF-8, then cp1252 and latin-1. Re-save the file as UTF-8 if needed. |
| Credentials appear in YAML (`authentication` item) | `web_set_user` or a hard-coded token | Move the value to a NeoLoad Web secret or protected variable, and keep it out of Git |

## 11. Extending the converter

- **New LoadRunner API**: add a `h_<function_name>(self, st)` method to `Mapper` in `lr2nl/mapper.py`. It receives the parsed statement with `st.args`.
- **NeoLoad schema change**: edit `build_project` in `lr2nl/generator.py`. Variable references are produced by `neoload_ref` in `lr2nl/model.py`.
- **Tests**: add a case to `tests/test_mapper.py`, then run `run_tests.cmd`.
