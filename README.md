# GTM Tracker

An evidence-based go-to-market tracker for B2B teams. It reads CRM records and qualitative meeting notes, turns them into an auditable weekly commercial state, and shows how far signed commercial ACV is from your target — with every number traceable to the exact sentence it came from.

## Quick demo

```powershell
.\RUN_DEMO.ps1
```

Open the local URL printed in PowerShell. Python 3.10+ is required; the demo needs no packages, credentials, internet or API calls. Keep the window open; Ctrl+C stops it. Use `-Port 8880` if needed.

The demo runs on a **synthetic sample company**, "Vendora", which sells demand forecasting and replenishment to grocery retailers, wholesale distributors, food manufacturers and pharma distributors. Every company, contact, deal, note and team member in it is invented. The demo is the output of a real pipeline run (Luna semantic extraction with Jev verification) on the sample's sources, carried over to the current sample content with the same entity and phrase mapping, at the business reference date **13 September 2026**. A live run on `config/notion_export.zip` and `config/crm_export.json` regenerates it end to end:

- **$649,600 signed ACV recognised by reasoning** — one deal (Coldharbour Pharma, signed 16 May 2026, €580k/yr); the stricter documentary-verified figure is $0 and is shown separately.
- 21 deals reconstructed from context across unlinked notes and CRM records.
- An estimated open pipeline of about $9.7M (lost deals excluded), each estimate with its basis and range.
- 19 review questions that need a human decision, out of 350 retained items.

Every figure links back to the exact source sentence. The sample sources are in `config/notion_export.zip` and `config/crm_export.json`.

## Use it for your own company

1. Edit `config/tracker.json`: your company name (`seller`), your ACV target and its window, the reference date (`null` = today), timezone and planning FX rates. Set `source_baseline` to `null`.
2. Point the run at your sources in `.env`: Notion and Airtable API keys, or export files (`NOTION_EXPORT_ZIP`, `CRM_EXPORT_JSON`), plus OpenAI and Jev keys for extraction.
3. Run `.\RUN_LIVE.ps1 -CheckOnly`, then `.\RUN_LIVE.ps1`.

See [INSTALL.md](INSTALL.md) for every setting.

## Install the full system

```powershell
.\INSTALL.ps1
```

See [INSTALL.md](INSTALL.md) for requirements, configuration, tests and operating instructions. The full connectors, semantic extraction, deterministic validation, canonical persistence, quantitative read model and frontend source are included. Installation downloads Python dependencies; the frontend has no npm dependencies.

## Run live

```powershell
Copy-Item .env.example .env
# Fill in your own credentials or export paths in .env, then:
.\RUN_LIVE.ps1 -CheckOnly
.\RUN_LIVE.ps1
```

Live mode reads the actual sources (Notion and Airtable APIs, or their export files), can incur API charges, and writes new results separately. It **does not use the demo as input**; the demo remains available unchanged.

## One-file Windows executable

```powershell
.\packaging\BUILD_EXE.ps1          # builds dist\GTMTracker.exe (about 1 minute)
```

Double-click `GTMTracker.exe` for a menu (demo, live preflight, live run, reopen live result, configure keys, self-tests). The demo needs no Python, Node or internet. Access keys found at build time (project `.env`, otherwise environment variables) are embedded and copied to the workspace `.env` on first run; **a build with keys must not be shared** (use `-NoKeys`). See [packaging/README_EXE.md](packaging/README_EXE.md).

## How to use it

- **Overview:** compare signed ACV with the target, pending signatures, open value and unknowns.
- **Opportunities:** inspect each opportunity, observed journey, values and supporting evidence.
- **Weekly Movement:** explore recorded changes and the limits of historical reconstruction.
- **Review:** filter unresolved identity, scope, value and verification questions; inspect exact evidence.
- **How it works:** understand the methodology, tools and conservative business rules.

## Observed → Inferred → Verified

Atomic commercial signals (data received, kickoff, recurring meetings, procurement started, budget blocker, …) are combined over time into inferred states — pilot status, buyer and technical commitment, procurement, commercial status, blockers, momentum, engagement — each with a confidence band, a structured explanation and the supporting and contradicting evidence. Inferred states never change Verified Actual. The review queue defaults to the items that need a human decision; all items remain available. Design, ontology, confidence rules and limitations: [docs/BELIEF_LAYER.md](docs/BELIEF_LAYER.md).

## Reasoned recognition and estimates

Soft-to-hard evidence makes strict documentary verification too narrow: a tracker that always reports $0 is not useful. The headline is therefore **Signed ACV recognised by reasoning**: a signature counts when the belief layer infers "reported signed" with high confidence and no contradiction, the source states one annual amount and currency, and the signature date (stated, or corroborated elsewhere) falls in the target window. The stricter **documentary-verified** figure is shown directly beneath it. Deals scattered across unlinked notes are **reconstructed from context** (shared rare phrases and exact amounts; names alone never link), and every open deal gets an **estimate** with its basis (stated value → pilot fee × corpus ratio → corpus median), range and band. Details: [docs/BELIEF_LAYER.md](docs/BELIEF_LAYER.md#reasoned).

## Important semantics

Documentary-verified Actual requires documentary verification and is shown separately from the reasoned headline. A pilot signature is never commercial ACV; pilot fees are not commercial ACV. Unknown is not zero. The progression proxy is a sensitivity measure, not a forecast. Review is read-only; unresolved evidence is preserved. All displayed opportunities are provisional. Inferred states are labelled as inferred with heuristic confidence bands, not probabilities; they are never verified facts and never count as Actual.
