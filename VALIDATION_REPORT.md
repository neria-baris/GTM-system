# Release validation

## Release 2.0.0: generic product

GTM Tracker is now organisation-neutral. Everything specific to one company lives in `config/tracker.json` (seller name, ACV target and window, reference date, timezone, FX, optional source baseline); the bundled data is a synthetic sample company ("Vendora") whose companies, contacts, deals, notes and team members are all invented.

| Check | Result |
|---|---|
| Offline tests | PASS · 303 passed, 4 live-provider tests skipped by default (`GTM_LIVE_TESTS=1` enables them) |
| New tests: CRM export client (paging, read-only, format validation, discovery + ingestion), organisation settings | PASS |
| Frontend build gate on the demo (`check_presentation_app.py`), including a check that no organisation name is hardcoded in the frontend | PASS |
| Demo server release-integrity check and rendering in headless Chrome (overview, opportunities, how it works): product logo, recognised $649,600, documentary-verified $0, no sample-company or legacy names in the UI | PASS |
| Live preflight (`run_live.py --check-only`) with the sample export files | PASS |
| Source ingestion from `config/notion_export.zip` and `config/crm_export.json` (111 notes, 66 companies, 187 contacts, 5 deals; 0 deltas against the configured baseline) | PASS |
| Live extraction with Luna | NOT RUN · OpenAI returned `insufficient_quota` (no credits); no model output was produced |

**Demo provenance.** Because the live extraction could not run, the demo is the previous live pipeline output (Luna medium reasoning, Jev) carried over to the sample with the same entity and phrase mapping used to build the sample sources. Exact excerpts, labels and names were mapped; reconstruction anchors, link anchors and deal labels were recomputed on the new text with the product's own reconstruction functions; file hashes and the revision id were recomputed. Figures are unchanged: 2 displayed opportunities, 38 weeks, 1,050 evidence references, 350 review items (19 decision-needed), 21 reconstructed deals, recognised signed ACV $649,600 (documentary-verified $0), estimated open pipeline $9.71M. A live run on the bundled exports regenerates the demo end to end once model credits are available.

**Known gap.** `tests/presentation/browser_smoke.cjs` still expects counts from an earlier 10-opportunity snapshot (it predates the 2-opportunity live demo) and its headless runner is not shipped; the browser check above was run separately.

## Security

| Check | Result |
|---|---|
| Empty `.env.example` placeholders; no `.env` in the release manifest | PASS |
| Old outputs, backups, archived snapshots and the previous executable removed | PASS |
| An executable built with keys embeds them (base64, not encryption); build shareable copies with `-NoKeys` | Documented |

## Earlier releases

1.2.0 added the belief-state layer (atomic signals, inferred states with heuristic bands, review triage); 1.3.0 added reasoned recognition, context reconstruction and estimates, and the one-file Windows executable. Their design and limits are documented in [docs/BELIEF_LAYER.md](docs/BELIEF_LAYER.md).
