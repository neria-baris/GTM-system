# Install and run the full system

The package contains the complete application source and a separate immutable demo. All commands below run from the folder containing this file.

## Requirements

- Windows with PowerShell 5.1+.
- Python 3.10+ with `venv` and `pip`.
- Node.js 22+ for JavaScript build/test checks. No npm packages, bundler or frontend framework installation is needed.
- A modern browser. Chrome is needed only for the optional browser acceptance script.
- Internet for dependency installation and live execution; never for the installed demo.

## Installation

```powershell
.\INSTALL.ps1
```

The helper creates `.venv`, installs `requirements.txt`, and checks the static frontend against the demo presentation files. It fails visibly on an error and never runs ingestion or models.

Equivalent manual setup:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -B scripts/check_presentation_app.py --app app --runtime demo --output .local/frontend_build.json
```

The frontend is already browser-ready in `app/`. The build command validates JavaScript syntax, navigation, evidence links, semantic presentation rules and snapshot hashes; it does not regenerate business data.

## Configure for your organisation

`config/tracker.json` holds everything that is specific to one company. The shipped values describe the bundled synthetic sample (seller "Vendora"); replace them before running on your own data.

| Key | Purpose |
|---|---|
| `seller.name`, `seller.aliases` | Your company name(s). The extractor labels your own actions and plans as seller actions (never as customer commitments), and the name is ignored as a deal anchor and in note titles. |
| `goal.amount_usd`, `goal.start`, `goal.deadline` | The new signed commercial ACV target and the window in which signatures count. |
| `business_as_of` | Reference date of the weekly snapshot. `null` means today. |
| `timezone` | Label shown with week endings. |
| `fx_to_usd` | Planning FX rates for converting stated amounts to USD. Unknown currencies stay unknown, never zero. |
| `source_baseline` | Optional expected source counts and known page IDs used only for reconciliation warnings and discovery tie-breaks. Set to `null` for your own data. |

Another file can be used with the `GTM_CONFIG` environment variable.

## Credentials and sources

```powershell
Copy-Item .env.example .env
```

Edit `.env` locally. Never share it. Values in `.env` take precedence over existing environment variables. Empty optional settings use the defaults below.

| Variable | Purpose |
|---|---|
| `NOTION_API_KEY` | Read access to the meeting notes and their blocks (not needed with `NOTION_EXPORT_ZIP`) |
| `AIRTABLE_TOKEN` | Read access to CRM base discovery, schema and records (not needed with `CRM_EXPORT_JSON`) |
| `OPENAI_API_KEY` | Required: structured semantic extraction |
| `JEV_API_KEY` | Required: bounded classification/verification |
| `NOTION_EXPORT_ZIP` | Optional: a Notion workspace export (Markdown & CSV) used instead of the Notion API |
| `CRM_EXPORT_JSON` | Optional: a CRM export file (`airtable-base-export/1`) used instead of the Airtable API |
| `AIRTABLE_BASE_ID` | Optional: restrict discovery to an accessible base; useful when multiple bases are available |
| `NOTION_ROOT_PAGE_ID`, `NOTION_DATABASE_ID`, `NOTION_DATA_SOURCE_ID` | Optional: narrow source discovery |
| `OPENAI_SEMANTIC_MODEL` | Default `gpt-6-luna`; production semantic extractor |
| `OPENAI_SEMANTIC_REASONING` | Default `medium` (Luna reasoning effort) |
| `OPENAI_SEMANTIC_MAX_CONCURRENCY` | Default `8` |
| `JEV_REPEATS` | Default `5` |
| `JEV_MAX_CONCURRENCY` | Default `3`; the existing worker cap also limits semantic concurrency |
| `OPENAI_EXTRACTION_MODEL` | Optional legacy narrow relation-extraction route; default `gpt-5.6-terra`, separate from the Luna semantic extractor |

Source discovery is conservative and may require scope hints when several workspaces or bases are accessible. Preflight cannot verify credentials without external calls.

To run on the bundled synthetic sample, set `NOTION_EXPORT_ZIP=config/notion_export.zip` and `CRM_EXPORT_JSON=config/crm_export.json`; only the OpenAI and Jev keys are then needed.

## Tests and frontend validation

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q
.\.venv\Scripts\python.exe -B scripts/check_presentation_app.py --app app --runtime demo --output .local/frontend_build.json
```

The packaged suite blocks external network connections and uses mock provider responses and synthetic regression inputs. Tests do not populate live production state. Opt-in provider checks run with `GTM_LIVE_TESTS=1`.

`experiments/extraction/frozen_v1.json` is a small executable evaluation fixture referenced by the extraction module. `context/audit_evidence.md` is its exact-span source fixture, built from the synthetic sample. Neither is live input.

## Live workflow

```powershell
.\RUN_LIVE.ps1 -CheckOnly
.\RUN_LIVE.ps1
```

`-CheckOnly` loads `.env`, checks credential presence, imports every production module, resolves runtime resources and stops **before any API request**. Missing credentials produce exit code 2. It never validates a credential by contacting a service.

The actual run reads the notes and the CRM (API or export files), extracts with Luna plus bounded Jev verification, validates evidence, persists canonical SQLite, materializes the quantitative read model, validates the presentation contract and starts the product on `http://127.0.0.1:8878/app/`. Each step must pass before the next runs. Use `-Port 8890` to change the port, or `-NoServe` to finish after validation.

Newly generated files go to `data/raw/`, `outputs/` and `data/runtime/`. The active routing policy is installed from `config/routing_policy.json` without changing thresholds or routes.

If outputs from a previous live run already exist, the runner refuses to overwrite or mix them. Stop any live server and move `outputs/` to your own archive before another live run. Preserve immutable `data/raw/`. This does not affect `demo/`.

To reopen an already validated live result without re-ingestion:

```powershell
.\.venv\Scripts\python.exe -B -m runtime.live_server --port 8878
```

The server revalidates the live read model and serves it through the same frontend. Although the frontend's local data URL is `/demo/`, live-server routing maps it exclusively to the new presentation output. It never falls back to the demo data.

## Export files instead of the APIs

**Notion.** If the Notion integration has no shared pages, export the workspace (Notion: `•••` → Export → Markdown & CSV) and set `NOTION_EXPORT_ZIP`, or pass `--notion-export path\to\export.zip` to `scripts/run_live.py`. `src/connectors/notion_export_ingest.py` reads the zip in memory (never extracted), rejects unsafe paths, checks that the note pages match the exported database rows, and converts each note into the same page/block snapshot shape the API returns, recording the export file and its SHA-256 as provenance.

**CRM.** Set `CRM_EXPORT_JSON`, or pass `--crm-export path\to\crm.json`. The file has the shape `{"format": "airtable-base-export/1", "base": {"id", "name"}, "tables": [<Airtable table schema>], "records": {<table id>: [<records with fields keyed by field id>]}}`. `src/connectors/airtable_export.py` serves it through the same read-only client interface as the Airtable API, so discovery, ingestion and provenance are identical; snapshots record `crm_export_json` as the acquisition.

After a validated live run, `scripts/publish_live_demo.py` makes it the product demo and archives the previous demo snapshot under `demo_archive/`.

## Belief layer

`src/belief/` holds the signal ontology, the deterministic language sensor, the temporal belief engine, review triage and the `belief_states.json` builder. Live runs persist atomic signals in the canonical SQLite (`atomic_signal` table) and publish `belief_states.json` with the other contract files. A belief file can also be derived offline from a published snapshot's exact excerpts:

```powershell
.\.venv\Scripts\python.exe -B scripts/build_demo_beliefs.py --output outputs\belief_states.json --report docs/belief_before_after.md
.\.venv\Scripts\python.exe -B scripts/update_release_manifest.py
```

After changing any release file, rerun `scripts/update_release_manifest.py`; the demo server refuses to start when a release hash differs.

## Windows executable

`.\packaging\BUILD_EXE.ps1` (or `-NoKeys`) builds `dist\GTMTracker.exe`; see [packaging/README_EXE.md](packaging/README_EXE.md) for key embedding, precedence (workspace `.env` > embedded > environment), workspace location and commands. When Node.js is absent, the executable sets `GTM_NODE_OPTIONAL=1`, so the live frontend gate skips only its JavaScript syntax step; release hash verification still applies.

## Runtime resources and limitations

`config/runtime_resources.json` lists the runtime instructions, schemas and configuration. Luna instructions and structured schema are Python constants in `semantic_llm.py` and `semantic_schema.py`; relation extraction and Jev rubrics also live in Python. No external Markdown prompt directory is required.

SQLite tables are initialized by the included store/persistence code; no external database or migration service is needed. Source permissions, model availability, discovery ambiguity and semantic validation can legitimately stop a live run. Contract verification remains external to model inference.

The demo always runs separately with `.\RUN_DEMO.ps1`, without installing dependencies or configuring credentials. Ctrl+C stops either local server. Neither server exposes source code, `.env`, raw ingestion files or model responses.
