# GTMTracker.exe

A single Windows executable that runs the GTM Tracker without installing Python.

> **Security warning.** A build made on a machine with access keys **contains those keys**. They are
> base64-encoded only to avoid casual viewing: this is **not encryption**, and anyone with the exe can
> recover them. Do not share, upload or commit `dist\GTMTracker.exe`. For a shareable build, use `-NoKeys`.

## Build

From the project folder, after `.\INSTALL.ps1` (PyInstaller is installed into `.venv` if missing):

```powershell
.\packaging\BUILD_EXE.ps1            # or: .\.venv\Scripts\python.exe -B packaging\build_exe.py
.\packaging\BUILD_EXE.ps1 -NoKeys    # build without embedded keys
```

The build refreshes `RELEASE_MANIFEST.json`, stages exactly the files it lists (hash-verified) as
bundled data, embeds the access keys, scans every project module for imports, runs PyInstaller and
writes `dist\GTMTracker.exe`. Temporary build folders are removed. `.env`, `.venv`, `outputs\` and
`data\` are never staged as release files.

## Access keys

At build time, `NOTION_API_KEY`, `AIRTABLE_TOKEN`, `OPENAI_API_KEY`, `JEV_API_KEY` and the optional
settings from `.env.example` are read from the project `.env` if it exists, otherwise from the build
machine's environment variables. The build prints the embedded names, never the values.

At run time the precedence is: **workspace `.env` > embedded keys > process environment variables**, so the owner's configured keys win over unrelated machine-wide variables.
On first run, if the workspace has no `.env`, one is created from the embedded keys (only names that
had a value), so they can be edited later. `NAME=` (empty) in `.env` disables the embedded fallback for
that name. Key values are never displayed; status shows only `set`/`not set` and the source.

## Workspace

The project files are extracted to `GTMTracker_workspace` next to the exe, or to
`%LOCALAPPDATA%\GTMTracker\workspace` if that folder is not writable. Release files are re-extracted
only when the bundled `RELEASE_MANIFEST.json` changes (`repair` forces it). `.env`, `outputs\` and
`data\` in the workspace are never touched. The demo verifies every release file hash before serving.

## Menu and commands

Double-click for the menu: `[1]` open demo (default), `[2]` live preflight, `[3]` full live run,
`[4]` reopen last live result, `[5]` configure access keys, `[6]` offline self-tests, `[7]` open
workspace folder, `[0]` exit. Ctrl+C stops a server and returns to the menu.

```powershell
GTMTracker.exe demo [--port 8877] [--no-browser]
GTMTracker.exe check                       # no external calls; exit 2 if keys are missing
GTMTracker.exe live [--no-serve] [--port 8878] [--no-browser]
GTMTracker.exe serve-live [--port 8878] [--no-browser]
GTMTracker.exe keys | test | where | repair
```

The live pipeline runs each step as a child process of the exe itself (it acts as the Python
interpreter for `-B -m module` / `-B scripts\x.py`). If Node.js is missing, the exe sets
`GTM_NODE_OPTIONAL=1`, so the frontend check skips only its JavaScript syntax step and says so.
Self-tests that execute JavaScript still need Node.js.

## Known limitations

- Onefile PyInstaller executables are sometimes flagged by antivirus heuristics, and an unsigned exe
  shows a SmartScreen prompt ("More info" > "Run anyway").
- Each start unpacks the Python runtime to a temporary folder (about 1-3 s); child steps of a live run
  pay this cost again.
