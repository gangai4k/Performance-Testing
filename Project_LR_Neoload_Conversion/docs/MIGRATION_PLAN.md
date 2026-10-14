# LoadRunner to NeoLoad Migration Plan

Project: **Project_LR_Neoload_Conversion**
Scope: 25-100 LoadRunner Web (HTTP/HTML) scripts, converted from source (no re-recording) with the `lr2nl` toolkit in this folder.

## 1. Scope

**In scope**

- LoadRunner VuGen Web (HTTP/HTML) scripts: `vuser_init.c`, `Action.c` (and any extra action files), `vuser_end.c`, helper `.c`/`.h` files, parameter files (`.prm` + `.dat`), run-time settings (`default.cfg`, `default.usp`).
- Output: one NeoLoad as-code project per script (`<script>/default.yaml`), its data files and translated JavaScript, plus batch reports.
- Execution from the NeoLoad GUI and NeoLoad Web.

**Out of scope**

- Other LoadRunner protocols (TruClient, Citrix, SAP GUI, Web Services/SOAP-only, Java, .NET). The converter flags their API calls as unsupported.
- LoadRunner Controller scenarios (`.lrs`), SLAs and Analysis templates. These are rebuilt by hand as NeoLoad scenarios and SLA profiles.
- Monitoring configuration (SiteScope etc.).

## 2. Phases

| # | Phase | Activities | Exit criteria |
|---|-------|-----------|---------------|
| 0 | Preparation | Install the prerequisites ([PREREQUISITES.md](../PREREQUISITES.md)). Collect all scripts in one source folder. Freeze LoadRunner script changes. | Toolkit runs `run_tests.cmd` green. Source inventory list exists. |
| 1 | Pilot (3-5 scripts) | Convert a mix of simple and complex scripts. Run `neoload validate` on each `default.yaml`. Import into the NeoLoad GUI and replay with 1 VU. Adjust the schema in `generator.py` / `mapper.py` if your NeoLoad version needs it. | Pilot scripts replay with 1 VU without errors. Mapping decisions are signed off. |
| 2 | Batch conversion | Convert all 25-100 scripts in one run (UI or CLI). Publish `reports/conversion_report.html`. | Every script has a status and a manual review list. |
| 3 | Remediation | Work through `manual_review.csv` script by script. Rebuild If/Loop/While containers, add JavaScript actions from `custom_js`, and fix any FAILED script. | No open REVIEW item without an owner. All scripts replay with 1 VU. |
| 4 | Functional validation | For each script, compare LoadRunner and NeoLoad single-user runs (see section 5). | Validation checklist passed per script. |
| 5 | Performance baseline | Run the same load profile in both tools on 3-5 key scripts. | Response times within ±10% and throughput within ±5% of LoadRunner, or the difference is explained. |
| 6 | Rollout and handover | Commit the final projects to Git, run them from NeoLoad Web, train the team ([USER_GUIDE.md](USER_GUIDE.md)). | Sign-off by the performance test lead. |

## 3. Indicative timeline (for about 60 scripts)

| Week | Activities |
|------|------------|
| 1 | Phase 0 and phase 1 (pilot) |
| 2 | Phase 2 (batch run, 1 day), start of phase 3 |
| 3-4 | Phase 3 remediation (about 1-3 hours per PARTIAL script, 0.5-1 day per FAILED script) |
| 5 | Phase 4 functional validation |
| 6 | Phase 5 baseline and phase 6 handover |

For 25 scripts, plan about 3-4 weeks. For 100 scripts, plan about 8 weeks, or add a second engineer during phases 3-4.

## 4. Mapping table (LoadRunner to NeoLoad)

| LoadRunner | NeoLoad (as generated) | Automatic? |
|-----------|------------------------|-----------|
| `vuser_init` / `Action` / `vuser_end` | User path `init` / `actions` / `end` containers | Yes |
| Extra action files and Run Logic order | Steps concatenated in `actions`, in Run Logic order (INFO note) | Yes, verify the order |
| `lr_start_transaction` / `lr_end_transaction` (LR_AUTO, LR_PASS) | `transaction` container, nested | Yes |
| `lr_end_transaction(..., LR_FAIL)`, `lr_set_transaction_status` | Transaction plus a REVIEW item: add an assertion or JavaScript | Partial |
| `web_url`, `web_custom_request` | `request` with method, URL/query, headers and body | Yes |
| `web_submit_data` (ITEMDATA) | POST request with a URL-encoded form body | Yes (multipart and file upload: Partial) |
| `web_submit_form`, `web_link`, `web_image` | Flagged: no URL in the source | Partial / No |
| `EXTRARES` resources | Separate GET requests | Yes |
| `web_add_header` / `web_add_auto_header` / `web_revert_auto_header` | Request headers (one request, or persistent) | Yes |
| `web_add_cookie` | `Cookie` header on the following requests. Server cookies are handled automatically by NeoLoad. | Yes (INFO) |
| `web_cleanup_cookies` | REVIEW: new VU / JavaScript reset | Partial |
| `web_set_user` | Basic `Authorization` header plus REVIEW (NTLM/Negotiate: server auth) | Partial |
| `web_reg_save_param` (LB/RB, Ord, Search, NotFound) | Regexp extractor `(?s)LB(.*?)RB`, `match_number`, `from`, `default` | Yes |
| `web_reg_save_param_ex` / `_regexp` / `_json` / `_xpath` | Regexp / JSONPath / XPath extractor | Yes |
| SaveOffset, SaveLen, Convert, Ord=All | Extractor plus REVIEW note | Partial |
| `web_reg_find` (Text, Fail=Found/NotFound, /IC) | `contains` / `not_contains` / `regexp` assertion on the next request | Yes |
| `web_global_verification` | Assertion added to every following request | Yes |
| `{Param}` references | `${Param}`. File parameters become `${file.Column}`. | Yes |
| Table parameters (.prm/.dat): Sequential, Random, Unique, Same line as; Each iteration, occurrence or once | File variable with `order`, `change_policy`, `scope`, `out_of_value`; shared tables become one variable | Yes |
| Unique number / Random number | `counter` / `random_number` variable | Yes |
| Date/Time, Group name, Custom (DLL) parameters | REVIEW: NeoLoad JavaScript or built-in variable | No |
| `lr_save_string` (literal) | Constant variable | Yes |
| `lr_save_string` (dynamic), `lr_save_int`, C expressions | JavaScript in `custom_js` plus a REVIEW marker | Translated |
| `lr_think_time` with run-time settings (recorded, ignore, multiply, limit) | `delay` step, adjusted to the settings | Yes (random %: Partial) |
| Pacing (run-time settings) | End-of-iteration `delay` plus REVIEW for start-to-start pacing | Partial |
| `if` / `else`, `switch` with requests | First branch inline. Other branches are kept as YAML comments. REVIEW: rebuild as an If action. | Partial |
| `for` / `while` / `do` with requests | Body emitted once plus REVIEW (iteration count given when literal) | Partial |
| Logic-only blocks (`if` without requests, error checks) | Translated JavaScript plus REVIEW marker | Translated |
| `lr_error_message`, `lr_output_message`, `lr_log_message` | JavaScript `logger.error/info/debug` (shim) | Translated |
| `lr_exit`, `lr_abort`, `return -1` | REVIEW: Stop VU / Go to next iteration action | Partial |
| Custom C functions (helpers) | JavaScript functions in `custom_js/<script>.js` with the `lr2nl` shim | Translated |
| `lr_rendezvous` | REVIEW: NeoLoad Rendezvous action | Partial |
| `web_set_max_html_param_len`, `web_set_sockets_option`, `web_set_timeout`, `web_cache_cleanup` | INFO note (NeoLoad project/runtime setting) | Yes (INFO) |
| Any other `lr_*` / `web_*` API | REVIEW: unsupported, rebuild manually | No |

## 5. Validation approach

1. **Static**: run `neoload validate default.yaml` for every project (`neoload_commands.ps1` does this for the whole batch).
2. **Structural**: for each script, compare the number of requests, transactions, extractors and assertions in `conversion_summary.csv` with the LoadRunner script (VuGen *Step Navigator*).
3. **Functional (1 VU, 1 iteration)** in the NeoLoad GUI *Check User Path*:
   - every request returns the same HTTP status as in the LoadRunner replay log;
   - every extractor finds a value (no `NOT_FOUND` defaults where LoadRunner succeeded);
   - every assertion passes;
   - transaction names match the LoadRunner transaction names exactly.
4. **Data**: run 3 VUs × 2 iterations and confirm the unique/sequential data is consumed as in LoadRunner.
5. **Performance**: run the same load profile in both tools for the key scripts. Compare average and 90th percentile response times per transaction, throughput and error rate.

## 6. Risk register

| ID | Risk | Likelihood | Impact | Mitigation | Owner |
|----|------|-----------|--------|-----------|-------|
| R1 | NeoLoad as-code schema differs slightly by NeoLoad version (key names for extractors, variables, assertions) | Medium | High | Pilot with `neoload validate`. All schema keys are generated in one place (`generator.py`, `mapper.py`) and can be adjusted once for the whole batch. | Toolkit owner |
| R2 | Control flow (if/loop/switch) needs NeoLoad logical actions | High | Medium | Converter marks every block with `[LR ...]` comments and REVIEW items. Budget remediation time in phase 3. | Script owners |
| R3 | Custom C code (pointers, memory functions, DLLs) cannot be translated automatically | Medium | Medium | `custom_js` shows the leftovers. Rewrite in JavaScript or replace with NeoLoad built-ins. | Script owners |
| R4 | Correlation boundaries behave differently (regex engine, HTML decoding) | Medium | High | 1-VU check of every extractor (validation step 3). Fix with a NeoLoad regexp/JSON/XPath extractor. | Script owners |
| R5 | Different think-time/pacing semantics change the load model | Medium | Medium | Report notes per script. Configure NeoLoad pacing on the user path. Baseline comparison in phase 5. | Test lead |
| R6 | Application changed since the scripts were recorded | Medium | High | Run the LoadRunner script once before conversion. Fix stale scripts first, or mark them as re-record candidates. | Test lead |
| R7 | Credentials or tokens embedded in scripts are copied into YAML | Medium | High | Search the review list for `authentication`. Move secrets to NeoLoad Web secrets / protected variables. Do not commit them to Git. | Everyone |
| R8 | NeoLoad license (VU count, Web zones, load generators) is not ready in time | Low | High | Confirm licenses in phase 0 ([PREREQUISITES.md](../PREREQUISITES.md)). | Test lead |

## 7. Acceptance criteria

1. 100% of in-scope scripts have been converted and have a status in `conversion_summary.csv`.
2. At least 80% of scripts are SUCCESS or PARTIAL with an automatic match of 85% or more, before remediation.
3. After remediation, every script passes `neoload validate` and a 1-VU, 1-iteration check with no errors.
4. Every transaction name, request, correlation, check and parameter from the LoadRunner source is present in NeoLoad or documented as a deliberate change in `manual_review.csv`.
5. The key scripts' baseline results are within ±10% of LoadRunner response times, or the deviation is explained and accepted.
6. Final NeoLoad projects are committed to `Project_LR_Neoload_Conversion` in GitHub and runnable from NeoLoad Web.
