"""C2 semantic proposals -> persisted atomic signals (belief layer), offline."""
from __future__ import annotations

import json

import pytest

from src.belief import ontology
from src.belief.signals import collect_signals, make_signal
from src.extraction import full_corpus as c2
from src.extraction.ensemble import aggregate
from src.extraction.semantic_llm import normalize_note, validate_output
from src.extraction.semantic_schema import COLLECTIONS
from src.ledger import Evidence, Ledger, SourceRef
from src.ledger.store import stable_id
from src.models.canonical_store import save_canonical
from src.models.full_corpus import serialized_span
from src.models.semantic_integration import integrate_semantics

T = "2026-06-03T09:00:00Z"
NOTE = ("notion", "page", "p1")
ACCOUNT = ("airtable", "record", "recA")
BLOCKS = {
    "opp": "Acme replenishment pilot for one region",
    "received": "Customer uploaded the historical logs",
    "planned": "Pilot kickoff planned for next month",
    "conditional": "If the pilot works they will commit to rollout",
    "kickoff": "Kickoff held with their engineers",
    "verbal": "Customer gave a verbal yes to the pilot",
    "signed": "Rollout contract signed by procurement",
}
ENV = {"provider": "notion", "native_object_type": "page", "native_id": "p1", "content_hash": "h1",
       "raw_snapshot_path": "data/raw/run/notion/p1.json", "source_title": "Acme sync"}
SCHEMA = {"tables": [{"id": "tblC", "name": "Companies",
                      "fields": [{"id": "fN", "name": "Company Name"}, {"id": "fI", "name": "Industry"}]}]}
IDENTITY = {"accounts": [{"id": "recA", "name": "Acme"}], "contacts": [], "opportunities": []}


def snapshot(meeting_date="2026-06-02"):
    blocks = [{"block": {"id": f"b{i}", "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": text}]}},
               "children": []} for i, text in enumerate(BLOCKS.values())]
    return {"content": {"page": {"properties": {"Date": {"id": "d", "type": "date", "date": {"start": meeting_date}}}},
                        "blocks": blocks}}


def item(quote, **extra):
    return {"quote": quote, "account_candidate_id": "recA", "opportunity_candidate_id": None, **extra}


def model_output():
    out = {key: [] for key in COLLECTIONS}
    out["opportunity_candidates"] = [item(BLOCKS["opp"], use_case="replenishment", commercial_scope="one region",
                                          relationship="base")]
    event = dict(event_date=None, contract_kind="pilot")
    out["events"] = [item(BLOCKS["received"], event_type="data_received", polarity="asserted", **event),
                     item(BLOCKS["planned"], event_type="pilot_started", polarity="future_plan", **event),
                     item(BLOCKS["verbal"], event_type="pilot_verbal_yes", polarity="asserted", **event)]
    signal = dict(effective_date=None, actor="customer")
    out["atomic_signals"] = [
        item(BLOCKS["conditional"], signal_type="verbal_commitment", modality="conditional", contract_kind="commercial", **signal),
        item(BLOCKS["kickoff"], signal_type="kickoff_completed", modality="asserted", contract_kind="pilot", **signal)]
    return out


def candidates(output=None, snap=None):
    snap = snap or snapshot()
    units, _ = c2.notion_units(snap)
    accepted, rejected = validate_output(normalize_note(units), output or model_output(), IDENTITY)
    assert not rejected
    claims = c2._semantic_claims(ENV, snap, {"accepted": accepted, "calls": []}, IDENTITY)
    dates = [c for u in units for c in c2._text_claims(ENV, u, snap) if c.get("date_role") == "meeting_date"]
    return claims, dates


def integrate(claims, dates, snap=None):
    snap = snap or snapshot()
    ledger = Ledger()
    canonical = json.dumps(snap["content"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    ref = SourceRef(*NOTE)
    digest = ledger.ingest_raw(ref, "h1", canonical, T, T)
    dispositions = []
    for c in claims + dates:
        start, end, encoded = serialized_span(snap["content"], c["evidence_span"])
        eid = ledger.add_evidence(Evidence(evidence_id=stable_id("c2_evidence", c["candidate_id"]), source_ref=ref,
                                           source_version="h1", source_hash=digest, start_offset=start, end_offset=end,
                                           verbatim_excerpt=encoded, source_first_seen_at=T, ingested_at=T,
                                           independence_group_id=c["independence_group"]))
        dispositions.append({"candidate_id": c["candidate_id"], "evidence_id": eid, "canonical_opportunity_id": None,
                             "event_id": None, "value_id": None})
    snapshots = {ACCOUNT: {"content": {"table_id": "tblC", "record": {"id": "recA", "fields": {"fN": "Acme"}}}}, NOTE: snap}
    envelopes = {ACCOUNT: {"retrieved_at": T}, NOTE: {"retrieved_at": T}}
    result = integrate_semantics(ledger, claims + dates, dispositions, snapshots, envelopes, SCHEMA)
    return ledger, result, dispositions


def by_clause(ledger):
    return {s["details"].get("clause"): s for s in ledger.signals() if s["extraction_method"] == "luna_semantic"}


def fake_jev(choices, fail=False):
    """K-repeat Jev stand-in: picks the configured option per question (else 'unclear')."""
    def run(state, questions, k):
        if fail:
            return {"requested_k": k, "successful_k": 0, "runs": [], "aggregate": None,
                    "failures": [{"run_index": 0, "kind": "timeout", "status_code": None}]}
        runs = []
        for _ in range(k):
            answers = {}
            for name, spec in questions.items():
                options = list(spec["criteria"])
                pick = choices.get(state, {}).get(name) or ("unclear" if "unclear" in options else options[0])
                probs = {o: 0.96 if o == pick else 0.04 / (len(options) - 1) for o in options}
                answers[name] = {"type": "choice", "choice": pick, "probabilities": probs, "confidence": 0.96}
            runs.append({"resolved_model": "jev-test", "latency_ms": 1, "raw_response": {"answers": answers}})
        return {"requested_k": k, "successful_k": k, "runs": runs, "failures": [], "aggregate": aggregate(runs, questions)}
    return run


def test_semantic_proposals_become_normalised_signals_without_soft_review():
    claims, dates = candidates()
    ledger, result, dispositions = integrate(claims, dates)
    try:
        signals = by_clause(ledger)
        oid = signals[BLOCKS["received"]]["opportunity_id"]
        assert oid and ledger.entity(oid)["use_case_description"] == "replenishment"
        # Asserted event lacking typed details: used as a signal, not sent to review.
        received = signals[BLOCKS["received"]]
        assert received["signal_type"] == "data_received" and received["modality"] == "asserted"
        assert received["effective_date"] == "2026-06-02" and received["date_basis"] == "structured_meeting_date_context"
        assert len(received["evidence_ids"]) == 2 and received["evidence_availability"]
        assert received["source_candidate_id"] in {c["candidate_id"] for c in claims}
        reasons = {r["reason"] for r in result["review_items"]}
        assert "required_event_details_not_extracted" not in reasons
        assert reasons == {"provisional_scope_requires_identity_review"}
        disposition = {d["candidate_id"]: d for d in dispositions}[received["source_candidate_id"]]
        assert disposition["integration_disposition"] == "semantic_signal_only" and disposition.get("event_id") is None
        # Planning is not execution; a condition is not a commitment.
        planned = signals[BLOCKS["planned"]]
        assert planned["signal_type"] == "kickoff_scheduled" and planned["details"]["retyped_from"] == "kickoff_completed"
        conditional = signals[BLOCKS["conditional"]]
        assert conditional["signal_type"] == "customer_interest" and conditional["signal_confidence"] == "low"
        assert conditional["modality"] == "conditional"
        # Asserted typed event still becomes one canonical event, cited by its signal and not derived twice.
        verbal = signals[BLOCKS["verbal"]]
        assert verbal["signal_type"] == "verbal_commitment" and verbal["details"]["event_id"]
        assert ledger.count("event") == 1
        collected = [s for s in collect_signals(ledger) if s["signal_type"] == "verbal_commitment"]
        assert [s["signal_id"] for s in collected] == [verbal["signal_id"]]
        assert not any(s["signal_type"] == "kickoff_completed" and s["details"].get("clause") == BLOCKS["planned"]
                       for s in collect_signals(ledger))
        # One dated single-opportunity note: one deterministic meeting signal for cadence.
        meetings = [s for s in ledger.signals() if s["signal_type"] == "meeting_held"]
        assert len(meetings) == 1 and meetings[0]["extraction_method"] == "deterministic_rule"
        assert meetings[0]["signal_confidence"] == "high" and meetings[0]["effective_date"] == "2026-06-02"
        assert meetings[0]["opportunity_id"] == oid and len(meetings[0]["evidence_ids"]) == 1
        assert result["atomic_signal_count"] == ledger.count("atomic_signal") == 6
        assert result["atomic_signals_by_type"]["data_received"] == 1 and result["source_scoped_signal_count"] == 0
        assert not any(s["signal_type"] == "formal_signature_verified" for s in ledger.signals())
    finally:
        ledger.close()


def test_unlinked_note_signals_are_source_scoped():
    output = model_output()
    output["opportunity_candidates"] = []
    claims, dates = candidates(output)
    ledger, result, _ = integrate(claims, dates)
    try:
        received = by_clause(ledger)[BLOCKS["received"]]
        assert received["opportunity_id"] is None and received["subject_ref"] == "source:notion:p1"
        assert result["source_scoped_signal_count"] == result["atomic_signal_count"] > 0
        assert not any(s["signal_type"] == "meeting_held" for s in ledger.signals())
        reasons = {r["reason"] for r in result["review_items"]}
        assert "unresolved_or_multiple_note_opportunity_scopes" in reasons
        assert not reasons & {"pilot_scope_unresolved", "required_event_details_not_extracted"}
    finally:
        ledger.close()


def test_only_reported_commercial_signature_atomic_signal_enters_review():
    output = {key: [] for key in COLLECTIONS}
    signal = dict(modality="asserted", effective_date=None, actor="customer")
    output["atomic_signals"] = [
        item(BLOCKS["signed"], signal_type="reported_signature", contract_kind="commercial", **signal),
        item(BLOCKS["kickoff"], signal_type="kickoff_completed", contract_kind="amendment", **signal),
        item(BLOCKS["verbal"], signal_type="reported_signature", contract_kind="pilot", **signal)]
    claims, _ = candidates(output)
    status = {c["evidence_span"]["exact_text"]: (c["validation_status"], c["review_reason"], c["value"]) for c in claims}
    assert status[BLOCKS["signed"]] == ("review_required", "semantic_high_impact_requires_review", "reported_signature")
    assert status[BLOCKS["kickoff"]] == ("semantic_validated_proposal", None, "kickoff_completed")
    assert status[BLOCKS["verbal"]] == ("semantic_validated_proposal", None, "reported_signature")


def test_jev_sensor_readings_move_a_signal_at_most_one_band(monkeypatch):
    claims, dates = candidates()
    calls = []
    choices = {BLOCKS["kickoff"]: {"statement_modality": "current", "pilot_activity": "active"},
               BLOCKS["conditional"]: {"statement_modality": "conditional", "customer_commitment": "conditional"}}
    def run(state, questions, k):
        calls.append((state, sorted(questions)))
        return fake_jev(choices)(state, questions, k)
    monkeypatch.setattr(c2, "run_batch", run)
    records = c2._verify_semantic_claims(claims, 3)
    kickoff = next(c for c in claims if c["evidence_span"]["exact_text"] == BLOCKS["kickoff"])
    assert (BLOCKS["kickoff"], ["pilot_activity", "statement_modality"]) in calls
    assert {r["sensor"]: r["choice"] for r in kickoff["jev_sensor"]["readings"]} == {
        "statement_modality": "current", "pilot_activity": "active"}
    assert any(r.get("purpose") == "belief_sensor" for r in records)
    assert all(c["validation_status"] != "review_required" for c in claims if c["predicate"] == "atomic_signals")
    ledger, _, _ = integrate(claims, dates)
    try:
        signals = by_clause(ledger)
        boosted = signals[BLOCKS["kickoff"]]
        assert boosted["signal_type"] == "kickoff_completed"
        assert ontology.band_rank(boosted["signal_confidence"]) - ontology.band_rank("medium") == 1
        assert {r["sensor"] for r in boosted["sensor_readings"]} == {"statement_modality", "pilot_activity"}
        assert signals[BLOCKS["conditional"]]["signal_type"] == "customer_interest"
        assert signals[BLOCKS["conditional"]]["signal_confidence"] == "low"
        assert signals[BLOCKS["received"]]["sensor_readings"] == []  # Events carry no sensor batch.
    finally:
        ledger.close()


def test_jev_sensor_can_downgrade_execution_to_plan(monkeypatch):
    claims, dates = candidates()
    monkeypatch.setattr(c2, "run_batch", fake_jev({BLOCKS["kickoff"]: {"pilot_activity": "planned"}}))
    c2._verify_semantic_claims(claims, 3)
    ledger, _, _ = integrate(claims, dates)
    try:
        kickoff = by_clause(ledger)[BLOCKS["kickoff"]]
        assert kickoff["signal_type"] == "kickoff_scheduled" and kickoff["modality"] == "planned"
        assert kickoff["signal_confidence"] == "medium"
    finally:
        ledger.close()


def test_failed_sensor_batch_yields_no_readings_and_no_review(monkeypatch):
    claims, dates = candidates()
    monkeypatch.setattr(c2, "run_batch", fake_jev({}, fail=True))
    c2._verify_semantic_claims(claims, 3)
    atomic = [c for c in claims if c["predicate"] == "atomic_signals"]
    assert atomic and all(c["jev_sensor"]["readings"] == [] for c in atomic)
    assert all(c["validation_status"] == "semantic_validated_proposal" for c in atomic)
    ledger, _, _ = integrate(claims, dates)
    try:
        kickoff = by_clause(ledger)[BLOCKS["kickoff"]]
        assert kickoff["signal_confidence"] == "medium" and kickoff["sensor_readings"] == []
    finally:
        ledger.close()


def metadata(result, dispositions):
    return {"review_items": result["review_items"], "candidate_dispositions": dispositions, "input_hashes": {},
            "c2_semantic_counts": {"opportunity_candidate_count": 1, "event_candidate_count": 3}}


def test_canonical_validation_reports_signals_and_rejects_forged_verification(tmp_path):
    claims, dates = candidates()
    ledger, result, dispositions = integrate(claims, dates)
    try:
        report = save_canonical(ledger, metadata(result, dispositions), tmp_path / "ok.sqlite")
        assert report["atomic_signal_count"] == 6 and report["atomic_signals_by_type"]["meeting_held"] == 1
        assert report["verified_actual_usd"] == "0"
        anchor = ledger.signals()[0]
        forged = make_signal("formal_signature_verified", evidence_ids=anchor["evidence_ids"], method="verification_gate",
                             id_seed="forged", opportunity_id=anchor["opportunity_id"], confidence="very_high",
                             effective_date="2026-06-02")
        ledger.add_signal(forged)
        with pytest.raises(ValueError, match="documentary verification"):
            save_canonical(ledger, metadata(result, dispositions), tmp_path / "forged.sqlite")
    finally:
        ledger.close()
