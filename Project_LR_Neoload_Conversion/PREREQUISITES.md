# Prerequisites

## 1. Converter toolkit (lr2nl)

| Item | Version | Notes |
|------|---------|-------|
| Operating system | Windows 10/11, Linux or macOS | Developed and tested on Windows 10 |
| Python | 3.9 or later (tested with 3.15) | On Windows, select "Add python.exe to PATH" and keep the default "tcl/tk and IDLE" option, which the UI needs |
| Python packages | **None** | The toolkit uses only the standard library (`tkinter`, `csv`, `json`, `unittest`, ...). There is no `pip install` step for the converter. |
| Disk space | About 5 MB per 100 converted scripts, plus data files | |
| Access | Read access to the LoadRunner script folders and write access to the output folder | |

Check:

```powershell
python --version
python -c "import tkinter; print('tkinter OK')"
```

## 2. NeoLoad

| Item | Version | Notes |
|------|---------|-------|
| NeoLoad GUI (Controller) | A NeoLoad release with as-code (YAML) support; a current 2024.x/2025.x release is recommended | Used for checking user paths, adding If/Loop/JavaScript actions, and local runs |
| NeoLoad Web | SaaS or on-premise, same generation as the GUI | Used for team runs and results |
| NeoLoad CLI | Latest `neoload` package from PyPI (`pip install neoload`) | Needed for `neoload validate` and NeoLoad Web runs (`neoload_commands.ps1`/`.sh`) |
| Load generators | At least one NeoLoad Load Generator, local or in a NeoLoad Web zone | |
| Java | Bundled with the NeoLoad installer | |

**Licenses**

- A NeoLoad license with enough virtual users (Web VUs) for the target scenarios.
- A NeoLoad Web account with permission to create tests in the target workspace, and access to at least one zone with load generators.
- A NeoLoad Web **API token**. Store it in the `NLW_TOKEN` environment variable. Never write it in scripts or commit it to Git.
- A LoadRunner/VuGen license is **not** needed for conversion. It is only needed to replay the original scripts for comparison (Migration Plan, phase 4).

## 3. Source material

- A complete copy of every LoadRunner script folder: `*.c`, `*.h`, `*.prm`, `*.dat`, `default.cfg`, `default.usp`, `*.usr`.
- Scripts recorded with the Web (HTTP/HTML) protocol. Other protocols are flagged as unsupported.
- If possible, a recent successful VuGen replay log per script, for functional comparison.

## 4. GitHub

| Item | Requirement |
|------|-------------|
| Git | Git for Windows 2.40 or later (`git --version`) |
| Repository | `https://github.com/gangai4k/performance-testing` |
| Permission | **Write** (push) access to the repository for anyone who commits converted projects |
| Authentication | Git Credential Manager (browser sign-in), or a personal access token with `repo` scope (classic) or *Contents: Read and write* (fine-grained). Never paste tokens into scripts or chat. |
| Branching | Work on a feature branch and open a pull request into `main` if branch protection is enabled |

## 5. Network

- The NeoLoad load generators must reach the application under test (the hosts listed in each project's `servers` section).
- The NeoLoad CLI must reach the NeoLoad Web API URL (SaaS default, or your on-premise URL in `NLW_URL`).
