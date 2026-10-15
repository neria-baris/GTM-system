"""Stage D business boundary and non-inference regression tests."""
from __future__ import annotations

import json
from pathlib import Path
from decimal import Decimal

import pytest

from src.ledger import Ledger
from src.ledger import Event, Evidence, OfferOrContract, CommercialValue, SourceRef
from src.ledger.fixtures import load_audit_fixtures
from src.ledger.store import stable_id
from src.tracker.read_model import materialize, movement, write_store_and_contract
from scripts.validate_presentation_contract import validate


@pytest.fixture
def fixture_model():
    ledger = Ledger()
    try:
        ids = load_audit_fixtures(ledger)
        yield ids, materialize(ledger)
    finally:
        ledger.close()


def _detail(model, oid):
    return next(x for x in model["opportunity_details"] if x["opportunity_id"] == oid)


def test_summary_detail_identity_and_evidence(fixture_model):
    _, model = fixture_model
    details = {x["opportunity_id"]: x for x in model["opportunity_details"]}
    evidence = {x["evidence_id"] for x in model["evidence_summaries"]}
    assert {x["opportunity_id"] for x in model["opportunities"]} == set(details)
    assert all(set(x["supporting_evidence_ids"]) <= evidence for x in details.values())


def test_pending_never_actual_and_pilot_fee_excluded(fixture_model):
    ids, model = fixture_model
    coldharbour = _detail(model, ids["Coldharbour"]["opportunity"])
    assert coldharbour["commercial_state"] == "reported_signed_pending"
    assert coldharbour["verified_actual_usd"] == "0"
    assert model["overview"]["verified_signed_acv_usd"] == "0"
    assert not any(x["selected_for_open_value"] for x in coldharbour["commercial_values"]
                   if x["value_type"] == "pilot_fee")


def test_unique_document_verified_commercial_value_reconciles():
    ledger = Ledger()
    try:
        ids = load_audit_fixtures(ledger)
        oid = ids["Coldharbour"]["opportunity"]
        scope = ledger.entity(oid)["commercial_scope_id"]
        ref = SourceRef("contract_fixture", "signed_document", "frostline_verified")
        text = "Signed commercial Coldharbour: 580000 EUR per_year 2026-05-16"
        digest = ledger.ingest_raw(ref, "v1", text, "2026-05-16", "2026-05-16")
        ev = Evidence(evidence_id=stable_id("evidence", "frostline_verified"),
                      source_ref=ref, source_version="v1", source_hash=digest,
                      start_offset=0, end_offset=len(text), verbatim_excerpt=text,
                      assertion_type="document", authorship="customer",
                      business_event_date="2026-05-16", documented_at="2026-05-16",
                      source_first_seen_at="2026-05-16", ingested_at="2026-05-16")
        ledger.add_evidence(ev)
        contract = OfferOrContract(id=stable_id("contract", "frostline_verified"),
                                   opportunity_id=oid, contract_kind="commercial", scope_id=scope,
                                   status="verified_signed", document_ref="doc:frostline_verified",
                                   party_names=("Vendora", "Buyer"), signature_date="2026-05-16",
                                   term_start="2026-05-01", term_end="2028-04-30",
                                   created_in_ledger_at="2026-05-16", resolution_status="resolved")
        ledger.add_entity(contract)
        ledger.add_event(Event(event_id=stable_id("event", "frostline_verified"),
                               event_type="commercial_signed", account_id=ids["Coldharbour"]["account"],
                               opportunity_id=oid, scope_id=scope, contract_kind="commercial",
                               event_date="2026-05-16", first_seen_at="2026-05-16", extraction_version="fixture_v1", evidence_ids=(ev.evidence_id,),
                               verification="document_verified",
                               details={"commercial_contract_id": contract.id}))
        ledger.add_value(CommercialValue(value_id=stable_id("value", "frostline_verified"),
                           opportunity_id=oid, offer_or_contract_id=contract.id, scope_id=scope,
                           amount_decimal=Decimal("580000"), currency_ISO="EUR",
                           value_type="rollout_acv", status="signed_verified", unit="per_year",
                           term_months=24, date_observed="2026-05-16",
                           source_evidence_ids=(ev.evidence_id,), verification="document_verified"))
        model = materialize(ledger)
        assert model["overview"]["verified_signed_acv_usd"] == "649600.00"
        assert _detail(model, oid)["verified_actual_usd"] == "649600.00"
    finally:
        ledger.close()


def test_unknown_money_not_zero_and_alternatives_not_summed(fixture_model):
    ids, model = fixture_model
    osprey = _detail(model, ids["Osprey"]["opportunity"])
    assert osprey["known_open_commercial_value_usd"] is None
    assert osprey["value_status"] != "known_eligible"
    assert model["overview"]["known_value_open_commercial_pipeline_usd"] != "0" or model["overview"]["value_coverage"]["unknown_value_count"] > 0


def test_journey_only_observed_events_and_no_crm_promotion(fixture_model):
    ids, model = fixture_model
    westra = _detail(model, ids["Westra"]["opportunity"])
    assert "pilot_signed" in westra["observed_milestones"]
    assert "commercial_signed" not in westra["observed_milestones"]
    assert "encounter" not in westra["observed_milestones"]
    assert "encounter" in westra["missing_prior_milestones"]


def test_self_diff_empty_and_history_unavailable(fixture_model):
    _, model = fixture_model
    shape = {"opportunities": {x["opportunity_id"]: x for x in model["opportunity_details"]}}
    assert movement(shape, shape) == {"changes": [], "count": 0}
    latest = model["weekly_snapshots"][-1]
    assert latest["historical_knowledge_quality"] == "unavailable"
    assert latest["historically_known_state"]["verified_actual_usd"] is None


def test_contract_validation_and_deterministic_rebuild(fixture_model, tmp_path):
    _, model = fixture_model
    first = tmp_path / "first"
    second = tmp_path / "second"
    a = write_store_and_contract(model, first / "state.sqlite", first / "runtime")
    b = write_store_and_contract(model, second / "state.sqlite", second / "runtime")
    assert a["revision_id"] == b["revision_id"]
    assert a["files"] == b["files"]
    assert validate(first / "runtime", first / "state.sqlite")["opportunities"] > 0


def test_contract_rejects_native_payload_and_broken_review(fixture_model, tmp_path):
    _, model = fixture_model
    out = tmp_path / "runtime"
    manifest = write_store_and_contract(model, tmp_path / "state.sqlite", out)
    path = out / "opportunities.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["data"][0]["jev_probability_vector"] = [0.5, 0.5]
    path.write_text(json.dumps(payload), encoding="utf-8")
    import hashlib
    manifest["files"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="native"):
        validate(out, tmp_path / "state.sqlite")




def test_d_build_entrypoint_only_loads_persisted_canonical_state():
    import ast
    root = Path(__file__).resolve().parents[2]
    source = (root / "scripts/build_stage_d.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "load_canonical" in calls
    assert "integrate_full_corpus" not in calls
    assert not any(isinstance(node, ast.ImportFrom) and (node.module or "").startswith("src.extraction") for node in ast.walk(tree))


def test_canonical_population_has_explicit_as_of_reconciliation(fixture_model):
    _, model = fixture_model
    reconciliation = model["_population_reconciliation"]
    included = set(reconciliation["materialized_opportunity_ids"])
    excluded = {x["opportunity_id"] for x in reconciliation["as_of_exclusions"]}
    assert included | excluded == set(reconciliation["canonical_opportunity_ids"])
    assert not included & excluded
    assert included == {x["opportunity_id"] for x in model["opportunity_details"]}


def test_semantic_native_payload_rejected():
    from scripts.validate_presentation_contract import _no_native_payload
    with pytest.raises(ValueError, match="native"):
        _no_native_payload({"semantic_payload": {"event_type": "pilot_signed"}})
