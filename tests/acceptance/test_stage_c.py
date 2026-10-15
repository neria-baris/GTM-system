"""The twenty numbered business cases from operational_spec section 11."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import json

import pytest

from src.ledger import (Ledger, Event, Evidence, OfferOrContract, CommercialValue,
                        SourceRef, Claim, Account, CommercialScope, Opportunity)
from src.ledger.fixtures import load_audit_fixtures
from src.ledger.store import stable_id
from src.models import weekly_state, ingest_envelopes, route_annotation
from src.models.integration import materialize_annotation, route_policy_candidates
from src.models.quantitative import _money

WEEK = "2026-09-13"


@pytest.fixture
def audit():
    ledger = Ledger()
    ids = load_audit_fixtures(ledger)
    yield ledger, ids
    ledger.close()


def view(audit, name, week=WEEK, mode="retrospective_event_state"):
    ledger, ids = audit
    return weekly_state(ledger, week, mode=mode)["opportunities"][ids[name]["opportunity"]]


def add_verified(ledger, opp, *, key, date="2026-05-16", kind="commercial",
                 amount="580000", currency="EUR", unit="per_year", term=24):
    scope = ledger.entity(opp)["commercial_scope_id"]
    ref = SourceRef("contract_fixture", "signed_document", key)
    text = f"Signed {kind} {key}: {amount} {currency} {unit} {date}"
    digest = ledger.ingest_raw(ref, "v1", text, date, date)
    ev = Evidence(evidence_id=stable_id("evidence", key), source_ref=ref,
                  source_version="v1", source_hash=digest, start_offset=0,
                  end_offset=len(text), verbatim_excerpt=text, assertion_type="document",
                  authorship="customer", business_event_date=date, documented_at=date,
                  source_first_seen_at=date, ingested_at=date, date_precision="day")
    ledger.add_evidence(ev)
    contract = OfferOrContract(id=stable_id("contract", key), opportunity_id=opp,
                               contract_kind=kind, scope_id=scope, status="verified_signed",
                               document_ref=f"doc:{key}", party_names=("Vendora", "Buyer"),
                               signature_date=date, term_start="2026-05-01", term_end="2028-04-30",
                               created_in_ledger_at=date, resolution_status="resolved")
    ledger.add_entity(contract)
    account = ledger.entity(opp)["account_id"]
    event = Event(event_id=stable_id("event", key), event_type="commercial_signed",
                  account_id=account, opportunity_id=opp, scope_id=scope,
                  contract_kind="commercial", event_date=date, first_seen_at=date,
                  evidence_ids=(ev.evidence_id,), verification="document_verified",
                  details={"commercial_contract_id": contract.id})
    ledger.add_event(event)
    value = CommercialValue(value_id=stable_id("value", key), opportunity_id=opp,
                            offer_or_contract_id=contract.id, scope_id=scope,
                            amount_decimal=Decimal(amount), currency_ISO=currency,
                            value_type="expansion_increment_acv" if kind != "commercial" else "rollout_acv",
                            status="signed_verified", unit=unit, term_months=term,
                            date_observed=date, source_evidence_ids=(ev.evidence_id,),
                            first_seen_at=date, recorded_at=date, verification="document_verified")
    ledger.add_value(value)
    return contract, value


def test_01_wisla_crm_stage_is_not_signature(audit):
    row = view(audit, "Westra")
    assert row["model_a"]["commercial_state"] == "not_signed_reported"
    assert row["model_a"]["pilot_state"] == "signed_reported"
    assert weekly_state(audit[0], WEEK)["verified_actual_usd"] == "0"
    assert any(x["kind"] == "crm_stage_exception" for x in weekly_state(audit[0], WEEK)["review_queue"])


def test_02_frostline_reported_then_documented(audit):
    ledger, ids = audit
    assert view(audit, "Coldharbour")["model_a"]["commercial_state"] == "reported_signed_pending"
    assert weekly_state(ledger, WEEK)["reported_signed_possible_acv_usd"] == "649600.00"
    assert weekly_state(ledger, WEEK)["verified_actual_usd"] == "0"
    add_verified(ledger, ids["Coldharbour"]["opportunity"], key="frostline_verified")
    assert weekly_state(ledger, WEEK)["verified_actual_usd"] == "649600.00"


def test_03_hanbit_verbal_yes_and_draft_only(audit):
    assert set(view(audit, "Halvard")["model_a"]["event_types"]) == {"pilot_verbal_yes", "sow_drafting"}


def test_04_rhodope_pilot_fee_excluded(audit):
    assert any(v["value_type"] == "pilot_fee" for v in audit[0].values_for_opportunity(audit[1]["Rhona"]["opportunity"]))
    assert weekly_state(audit[0], WEEK)["verified_actual_usd"] == "0"


def test_05_rhodope_value_replaced_not_summed(audit):
    vals = [v for v in audit[0].values_for_opportunity(audit[1]["Rhona"]["opportunity"]) if v["value_type"] == "rollout_acv"]
    assert len(vals) == 2 and vals[1]["replaces_value_id"] == vals[0]["value_id"]


def test_06_hanbit_exclusive_scenarios_not_summed(audit):
    row = view(audit, "Halvard")
    assert row["model_c"]["eligible_value_usd"] is None
    assert row["model_c"]["abstain_reason"] == "ambiguous_scope_or_identity"


def test_07_ai_assertion_is_not_customer_fact(audit):
    p = {"policy_version": "routing_1", "commercial_signature_auto_proposal_enabled": True,
         "deployment_status": "research_only_pending_dual_human_adjudication"}
    a = route_annotation("commercial_contract_status", "signed", "source-span", p, method="jev", confidence=.99)
    assert a["route"] == "human_review" and not a["verified_actual_mutation_allowed"]


def test_08_draft_email_no_outreach_event(audit):
    ledger, ids = audit
    ref = SourceRef("airtable", "contact", "draft-email")
    text = "Initial Email Body: Let's meet at the Summit"
    digest = ledger.ingest_raw(ref, "v1", text, WEEK, WEEK)
    ev = Evidence(source_ref=ref, source_version="v1", source_hash=digest,
                  verbatim_excerpt=text, start_offset=0, end_offset=len(text),
                  source_first_seen_at=WEEK, ingested_at=WEEK)
    ledger.add_evidence(ev)
    with pytest.raises(ValueError, match="No validated exact rule"):
        materialize_annotation(ledger, evidence_id=ev.evidence_id,
                               opportunity_id=ids["Halvard"]["opportunity"],
                               field="outreach_sent", label="sent", method="deterministic", policy={})
    assert "outreach_sent" not in weekly_state(ledger, WEEK)["model_a_counts_by_event"]


def test_09_later_source_cannot_backdate_knowledge(audit):
    assert view(audit, "Coldharbour", mode="historically_known_state")["model_a"]["event_types"] == []
    assert view(audit, "Coldharbour")["model_a"]["event_types"]


def test_10_kestrel_identity_and_scope_ambiguous(audit):
    assert audit[1]["Osprey"]["account"] != audit[1]["Osprey"]["other_account"]
    assert view(audit, "Osprey")["model_c"]["eligible_value_usd"] is None
    assert any(x["kind"] == "material_identity_or_scope" for x in weekly_state(audit[0], WEEK)["review_queue"])


def test_11_kaveri_data_kind_is_not_receipt(audit):
    assert view(audit, "Kavala")["model_b"]["data_access"] == "unknown"
    assert "data_received" not in view(audit, "Kavala")["model_a"]["event_types"]


def test_12_norvane_loss_not_revival(audit):
    row = view(audit, "Nordahl")
    assert row["model_a"]["lifecycle"] == "lost" and not row["model_c"]["open"]


def test_13_solmar_stalled_seller_plan(audit):
    row = view(audit, "Solvik")
    assert row["model_a"]["lifecycle"] == "stalled"
    assert row["model_b"]["next_step_strength"] == "unknown"  # no buyer commitment inferred


def test_14_technical_success_is_not_commercial_signature(audit):
    row = view(audit, "Coldharbour", week="2026-05-13")
    assert row["model_a"]["technical_state"] == "shadow_result_positive"
    assert row["model_a"]["commercial_state"] == "unknown"


def test_15_pilot_and_commercial_contract_state_parallel(audit):
    row = view(audit, "Westra")
    assert row["model_a"]["pilot_state"] == "signed_reported"
    assert row["model_a"]["commercial_state"] == "not_signed_reported"


def test_16_stage_entered_before_created_does_not_backfill(audit):
    ledger, ids = audit
    ref = SourceRef("airtable", "deal", "bad-stage-order")
    text = "Created Date: 2026-09-01; Stage Entered Date: 2026-08-01; Stage: Commercial deployment"
    digest = ledger.ingest_raw(ref, "v1", text, WEEK, WEEK)
    ev = Evidence(source_ref=ref, source_version="v1", source_hash=digest,
                  verbatim_excerpt=text, start_offset=0, end_offset=len(text),
                  source_first_seen_at=WEEK, ingested_at=WEEK, assertion_type="crm_snapshot")
    ledger.add_evidence(ev)
    ledger.add_claim(Claim(subject_id=ids["Westra"]["opportunity"], predicate="crm_current_stage",
                           object_value="Commercial deployment", evidence_ids=(ev.evidence_id,)))
    assert view(audit, "Westra", week="2026-08-02")["model_a"]["event_types"] == []


def test_17_duplicate_words_across_sources_are_not_one_event(audit):
    ledger, ids = audit
    text = "Pilot signed: €115k"
    evidence = []
    for native in ("note-a", "note-b"):
        ref = SourceRef("notion", "page", native)
        digest = ledger.ingest_raw(ref, "v1", text, WEEK, WEEK)
        ev = Evidence(source_ref=ref, source_version="v1", source_hash=digest,
                      verbatim_excerpt=text, start_offset=0, end_offset=len(text),
                      source_first_seen_at=WEEK, ingested_at=WEEK)
        ledger.add_evidence(ev)
        evidence.append(ev.evidence_id)
    assert evidence[0] != evidence[1]
    opp = ids["Halvard"]["opportunity"]
    account = ids["Halvard"]["account"]
    before = ledger.count("event")
    for native, evid in zip(("note-a", "note-b"), evidence):
        event = Event(event_id=stable_id("event", native), event_type="pilot_signed",
                      account_id=account, opportunity_id=opp, contract_kind="pilot",
                      event_date="2026-09-13", first_seen_at=WEEK,
                      evidence_ids=(evid,), details={"pilot_contract_id": native})
        ledger.add_event(event)
        ledger.add_event(event)
    assert ledger.count("event") == before + 2


def test_18_new_amendment_not_renewal_or_pilot(audit):
    ledger, ids = audit
    opp = ids["Coldharbour"]["opportunity"]
    add_verified(ledger, opp, key="base", amount="580000")
    add_verified(ledger, opp, key="renewal", kind="renewal", amount="0")
    add_verified(ledger, opp, key="amend", kind="amendment", amount="100000")
    assert weekly_state(ledger, WEEK)["verified_actual_usd"] == "761600.00"


def test_19_unsupported_currency_or_period_is_unknown(audit):
    ledger, ids = audit
    add_verified(ledger, ids["Coldharbour"]["opportunity"], key="bad_currency", currency="CHF")
    report = weekly_state(ledger, WEEK)
    assert report["verified_actual_usd"] == "0"
    assert report["unknown_signed_amount_count"] == 1


def test_20_signature_date_governs_goal_window(audit):
    ledger, ids = audit
    opp = ids["Coldharbour"]["opportunity"]
    add_verified(ledger, opp, key="last_day", date="2027-03-31", amount="100000")
    add_verified(ledger, opp, key="after_end", date="2027-04-01", amount="200000")
    assert weekly_state(ledger, "2027-04-04")["verified_actual_usd"] == "112000.00"


def test_integration_fixture_and_envelope_quantification_equal(audit, tmp_path):
    ledger, ids = audit
    before = weekly_state(ledger, WEEK)["verified_actual_usd"]
    content = {"record": {"id": "rec-example", "fields": {"Notes": "SIGNED. €580k/yr"}}}
    import hashlib
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    path = tmp_path / "raw.json"
    path.write_text(json.dumps({"content": content}), encoding="utf-8")
    manifest = {"envelopes": [{"provider": "airtable", "native_object_type": "record", "native_id": "rec-example",
                                "raw_snapshot_path": "raw.json", "content_hash": digest,
                                "retrieved_at": "2026-09-27T00:00:00Z"}]}
    evidence_ids = ingest_envelopes(ledger, manifest, tmp_path,
                                    subject_by_source={("airtable", "rec-example"): ids["Coldharbour"]["opportunity"]})
    assert evidence_ids and weekly_state(ledger, WEEK)["verified_actual_usd"] == before


def test_integration_model_alone_cannot_enter_actual(audit):
    assert weekly_state(audit[0], WEEK)["verified_actual_usd"] == "0"
    assert view(audit, "Coldharbour")["model_a"]["commercial_state"] == "reported_signed_pending"


def test_integration_transport_time_not_business_date(audit, tmp_path):
    content = {"record": {"fields": {"Notes": "pilot signed"}}}
    import hashlib
    raw = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    (tmp_path / "one.json").write_text(json.dumps({"content": content}), encoding="utf-8")
    ids = ingest_envelopes(audit[0], {"envelopes": [{"provider": "airtable", "native_object_type": "record", "native_id": "r1",
        "raw_snapshot_path": "one.json", "content_hash": hashlib.sha256(raw.encode()).hexdigest(),
        "retrieved_at": "2026-09-27T00:00:00Z"}]}, tmp_path)
    ev = audit[0].evidence(ids[0])
    assert ev["business_event_date"] is None and ev["documented_at"] is None


def test_integration_discovery_layout_does_not_change_semantics(audit):
    row = view(audit, "Coldharbour")
    assert row["model_a"]["commercial_state"] == "reported_signed_pending"
    assert "deal" not in row["model_a"]


def test_integration_notion_and_airtable_support_one_opportunity(audit):
    ledger, ids = audit
    opp = ids["Coldharbour"]["opportunity"]
    refs = [ledger.evidence(eid)["source_ref"]["system"] for eid in
            [ledger.entity(opp)["origin_evidence_id"]]]
    assert "notion_audit_fixture" in refs
    assert ledger.entity(ids["Coldharbour"]["account"])["source_refs"][0]["system"] == "airtable_audit_fixture"




def test_integration_unvalidated_annotation_is_only_inferred(audit):
    ledger, ids = audit
    ev = ledger.entity(ids["Coldharbour"]["opportunity"])["origin_evidence_id"]
    policy = json.loads(__import__("pathlib").Path("config/routing_policy.json").read_text(encoding="utf-8"))
    row = materialize_annotation(ledger, evidence_id=ev,
                                 opportunity_id=ids["Coldharbour"]["opportunity"],
                                 field="commercial_contract_status", label="signed",
                                 method="jev", policy=policy)
    assert row["event_id"] is None
    claim = next(c for c in ledger.db.execute("SELECT payload FROM claim")
                 if json.loads(c[0])["claim_id"] == row["claim_id"])
    assert json.loads(claim[0])["status"] == "inferred"
    assert weekly_state(ledger, WEEK)["verified_actual_usd"] == "0"


def test_integration_exact_signal_has_evidence_and_no_band_promotion(audit):
    ledger, ids = audit
    evid = next(e[0] for e in ledger.db.execute("SELECT evidence_id FROM evidence")
                if ledger.evidence(e[0])["verbatim_excerpt"].startswith("still waiting on data access"))
    policy = {"policy_version": "routing_1.0.0"}
    row = materialize_annotation(ledger, evidence_id=evid,
                                 opportunity_id=ids["Solvik"]["opportunity"],
                                 field="next_step_strength", label="seller_plan",
                                 method="deterministic", policy=policy)
    state = view(audit, "Solvik")["model_b"]
    assert row["claim_id"] and state["next_step_strength"] == "seller_plan"
    assert state["readiness_band"] == "early"
    assert state["signal_evidence"]["next_step_strength"][0]["evidence_ids"] == [evid]


def test_integration_resolved_open_quote_model_c_is_labeled_proxy():
    ledger = Ledger()
    ref = SourceRef("fixture", "note", "open-quote")
    text = "Rollout proposal sent: $100000 per year; pilot signed"
    digest = ledger.ingest_raw(ref, "v1", text, WEEK, WEEK)
    ev = Evidence(source_ref=ref, source_version="v1", source_hash=digest,
                  verbatim_excerpt=text, start_offset=0, end_offset=len(text),
                  business_event_date=WEEK, documented_at=WEEK,
                  source_first_seen_at=WEEK, ingested_at=WEEK)
    ledger.add_evidence(ev)
    account = Account(canonical_name="Example", created_in_ledger_at=WEEK, resolution_status="resolved")
    ledger.add_entity(account)
    scope = CommercialScope(scope_id=stable_id("scope", "open-quote"), account_id=account.id,
                            boundary_text="one rollout", product_use_case="control",
                            created_in_ledger_at=WEEK, resolution_status="resolved")
    ledger.add_entity(scope)
    opp = Opportunity(account_id=account.id, use_case_code="control", commercial_scope_id=scope.scope_id,
                      opportunity_group_id=stable_id("group", "open-quote"),
                      origin_evidence_id=ev.evidence_id, created_in_ledger_at=WEEK,
                      resolution_status="resolved")
    ledger.add_entity(opp)
    ledger.add_event(Event(event_type="pilot_signed", account_id=account.id,
                           opportunity_id=opp.id, scope_id=scope.scope_id, contract_kind="pilot",
                           event_date=WEEK, first_seen_at=WEEK, evidence_ids=(ev.evidence_id,),
                           details={"pilot_contract_id": "pilot-1"}))
    ledger.add_value(CommercialValue(opportunity_id=opp.id, scope_id=scope.scope_id,
                                     amount_decimal=Decimal("100000"), currency_ISO="USD",
                                     value_type="rollout_acv", status="proposed", unit="per_year",
                                     date_observed=WEEK, source_evidence_ids=(ev.evidence_id,)))
    result = weekly_state(ledger, WEEK)
    assert result["pipeline_quoted_value_by_band_usd"]["pilot_committed"] == "100000"
    assert Decimal(result["progression_weighted_proxy_usd"]) == Decimal("50000")
    assert result["value_coverage"]["largest_opportunity_share"] == "1"
    assert result["verified_actual_usd"] == "0"
    ledger.close()


