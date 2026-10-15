"""Rebuild Stage D from the canonical Stage C integration."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.models.canonical_store import load_canonical, validate_canonical
from src.tracker.read_model import materialize, write_store_and_contract
from scripts.repair_support import backup


def main() -> None:
    canonical_path = ROOT / "outputs/C/canonical_state.sqlite"
    validate_canonical(canonical_path)
    backup(ROOT, [ROOT / "outputs/D", ROOT / "data/runtime/gtm_state.sqlite"])
    ledger, stage_c = load_canonical(canonical_path)
    try:
        model = materialize(ledger, stage_c=stage_c)
    finally:
        ledger.close()
    sqlite_path = ROOT / "data/runtime/gtm_state.sqlite"
    runtime = ROOT / "outputs/D/runtime"
    manifest = write_store_and_contract(model, sqlite_path, runtime)
    from scripts.validate_presentation_contract import validate
    validated = validate(runtime, sqlite_path)
    population = model["_population_reconciliation"]
    (ROOT / "outputs/D/read_model_report.json").write_text(json.dumps({**validated, **population,
        "canonical_sqlite_sha256": hashlib.sha256(canonical_path.read_bytes()).hexdigest(),
        "presentation_gate_passed": True, "verified_actual_usd": model["overview"]["verified_signed_acv_usd"]}, indent=2), encoding="utf-8")
    (ROOT / "outputs/D/upstream_stale.json").write_text(json.dumps({"status": "rebuilt_and_validated",
        "canonical_sqlite_sha256": hashlib.sha256(canonical_path.read_bytes()).hexdigest()}), encoding="utf-8")
    snapshot_path = ROOT / f"outputs/D/snapshot_{manifest['business_as_of']}.json"
    snapshot_path.write_text(json.dumps({"schema_version": "presentation_v1",
        "snapshot": model["weekly_snapshots"][-1], "overview": model["overview"]},
        ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = ROOT / "outputs/D/end_to_end_report.md"
    overview = model["overview"]
    beliefs = model["belief_states"]
    triage = beliefs["review_summary"]
    report.write_text(f"""# Stage D end-to-end report

Contract: `presentation_v1`, revision `{manifest['revision_id']}`. Business as of
`{manifest['business_as_of']}`; knowledge cutoff `{manifest['knowledge_cutoff']}`;
timezone `{manifest['timezone']}`. Canonical model `{manifest['canonical_model_version']}`.

## Reconciliation

- Verified Actual: ${overview['verified_signed_acv_usd']} against the ${float(overview['target']['amount_usd']):,.0f} target.
- Reported signed pending verification: {overview['reported_signed_pending_verification_usd'] or 'unknown'} USD; {overview['counts']['reported_signature']} reported signature opportunity states.
- Known open commercial value: ${overview['known_value_open_commercial_pipeline_usd']} (known-value subset, with unknown values kept separate).
- Model C: {overview['heuristic_proxy']['amount_usd']} USD progression sensitivity proxy; **not a forecast or expected ACV**.

## Materialization

- {len(model['opportunity_details'])} canonical opportunities, {sum(len(x['event_timeline']) for x in model['opportunity_details'])} canonical linked events, {sum(len(x['commercial_values']) for x in model['opportunity_details'])} linked values.
- {len(model['evidence_summaries'])} evidence summaries and {len(model['review_queue'])} review items.
- {len(model['weekly_snapshots'])} weekly snapshots. Journey distribution: `{json.dumps(overview['journey_distribution'], sort_keys=True)}`.
- Journey milestones derive only from observed canonical event types. Later events do not create earlier milestones; CRM stage is excluded.
- Historical knowledge quality at the reference date: `{manifest['historical_knowledge_quality']}`. Source retrieval after the reference date cannot prove what was known on `{manifest['business_as_of']}`; no historical availability is invented.

## Belief layer (inferred, not verified)

- Engine `{beliefs['engine_version']}`: {len(beliefs['opportunities'])} opportunities with inferred belief states; bands are heuristic support levels, not probabilities.
- Review triage: {triage['decision_needed']} decision-needed and {triage['informational']} informational of {triage['total']} retained items ({len(model['review_queue'])} review queue items, {len(beliefs['belief_review_items'])} belief-engine items).
- Inferred stage distribution: `{json.dumps(beliefs['overview']['inferred_stage_distribution'], sort_keys=True)}`.
- Inferred states never change Verified Actual (belief value bucket: ${beliefs['overview']['value_buckets']['verified_actual_usd']}).

The SQLite store and every JSON file are rebuilt from the same canonical Stage C ledger. Presentation consumers are extractor and provider agnostic. They receive neither source objects nor Jev/LLM payloads.
""", encoding="utf-8")
    print(json.dumps({"revision_id": manifest["revision_id"], "opportunities": len(model["opportunity_details"]),
                      "review_items": len(model["review_queue"])}, sort_keys=True))


if __name__ == "__main__":
    main()
