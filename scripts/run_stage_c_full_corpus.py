"""Rebuild the Stage C production integration from A2, B, and C2 artifacts."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ledger import Ledger
from src.models.full_corpus import integrate_full_corpus
from src.models.canonical_store import save_canonical
from scripts.repair_support import backup


def main() -> None:
    backup(ROOT, [ROOT / "outputs/C"])
    ledger = Ledger()
    try:
        result = integrate_full_corpus(ROOT, ledger)
        semantic = json.loads((ROOT / "outputs/C2/semantic_extraction_report.json").read_text(encoding="utf-8"))
        result["c2_semantic_counts"] = {k: semantic[k] for k in ("opportunity_candidate_count", "event_candidate_count")}
        result["input_hashes"] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
            "outputs/A2/source_manifest.json", "outputs/C2/candidate_claims.json", "outputs/C2/semantic_extraction_report.json",
            "outputs/C2/source_coverage_report.json", "outputs/C2/review_queue.json", "outputs/C2/extraction_report.json", "outputs/B/routing_policy.json")}
        reviews = json.loads((ROOT / "outputs/C2/review_queue.json").read_text(encoding="utf-8"))
        grouped = {}
        for rejected in reviews.get("semantic_rejections", []):
            grouped.setdefault((rejected["source_id"], rejected["reason"]), []).append(rejected)
        from src.ledger.store import stable_id
        for (sid, reason), rejected in grouped.items():
            context_ids = [d["evidence_id"] for d in result["candidate_dispositions"] if d["source_ref"]["native_id"] == sid]
            if not context_ids:
                raise ValueError("Rejected semantic source has no review evidence")
            result["review_items"].append({"review_id": stable_id("rejected_semantics", sid + reason),
                "candidate_ids": [], "evidence_ids": sorted(set(context_ids)), "reason": "rejected_semantic_proposal:" + reason,
                "single_decision_needed": "Inspect source context and re-annotate the rejected proposal; no rejected object is a fact",
                "rejected_proposal_count": len(rejected)})
        result["review_item_count"] = len(result["review_items"])
        canonical_report = save_canonical(ledger, result, ROOT / "outputs/C/canonical_state.sqlite")
        (ROOT / "outputs/C/canonical_state_report.json").write_text(json.dumps(canonical_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (ROOT / "outputs/C/implementation_report.md").write_text(
            "# Stage C implementation and validation\n\n"
            f"Production input: {result['considered_source_count']} immutable A2 sources and {result['candidate_count']} C2 candidates. "
            "No gold/audit fixture populates production. C2 semantic and source coverage gates are checked before integration; input hashes are persisted.\n\n"
            f"Canonical SQLite: {canonical_report['entity_counts']}; {canonical_report['canonical_event_count']} events, "
            f"{canonical_report['canonical_value_count']} values, {canonical_report['claim_count']} claims, "
            f"{canonical_report['evidence_count']} exact evidence references, {canonical_report['review_item_count']} reviews.\n\n"
            f"Atomic signals (belief layer): {canonical_report['atomic_signal_count']} persisted, "
            f"{result['source_scoped_signal_count']} source-scoped (unlinked); by type: {canonical_report['atomic_signals_by_type']}. "
            "Each signal cites exact evidence; none carries verification.\n\n"
            "All opportunities remain provisional. Only exact normalized Account x Use Case x Scope tuples merge. "
            "Note-local event/value linkage requires a single candidate scope for the selected account. Ambiguous links remain claims/review; asserted statements lacking typed event details are used as atomic signals without a canonical event; "
            "non-asserted events never enter journey state (they become planned/conditional/negated signals). "
            "Unresolved soft signals remain annotations without generating individual manual tasks.\n\n"
            f"Verified Actual: {canonical_report['verified_actual_usd']} USD. "
            f"Reported signatures pending verification: {canonical_report['reported_signature_pending_verification_count']}; "
            f"undated events: {canonical_report['undated_event_count']}. No model output establishes documentary verification. "
            "FX/ACV rules remain in the existing deterministic models; unknown currency/unit/scope is never zero.\n\n"
            "Canonical gate passed after reopening the saved database read-only. Exact serialized evidence offsets follow the JSON pointer, even for repeated text. "
            "The acceptance_report.json separately records the executed operational-spec regression tests. D consumes this persisted database, not extraction artifacts.\n",
            encoding="utf-8")
        (ROOT / "outputs/C/upstream_stale.json").write_text(json.dumps({"status": "rebuilt_and_validated", "input_hashes": result["input_hashes"]}, indent=2), encoding="utf-8")
    finally:
        ledger.close()
    out = ROOT / "outputs/C/full_corpus_integration.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in (
        "considered_source_count", "candidate_count", "materialized_source_claim_count",
        "unknown_candidate_count", "review_candidate_count", "unresolved_canonical_link_count",
        "verified_actual_model_mutations", "canonical_opportunity_count", "canonical_event_count", "canonical_value_count",
        "atomic_signal_count", "source_scoped_signal_count")}, sort_keys=True))


if __name__ == "__main__":
    main()
