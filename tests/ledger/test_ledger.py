from dataclasses import replace
from decimal import Decimal
import sqlite3

import pytest

from src.ledger import (Claim, CommercialValue, Event, Evidence, Ledger, LedgerError,
                        OfferOrContract, SourceRef, ingest_jsonl_export)
from src.ledger.fixtures import load_audit_fixtures
from src.ledger.store import stable_id


@pytest.fixture
def audit():
    ledger = Ledger()
    ids = load_audit_fixtures(ledger)
    yield ledger, ids
    ledger.close()


def _events(ledger, opp):
    return [e for e in ledger.events_as_of("2026-09-13", mode="retrospective_event_state")
            if e["opportunity_id"] == opp]


def test_fixture_idempotency_and_raw_immutability(audit):
    ledger, ids = audit
    before = {t: ledger.count(t) for t in ("raw_source", "entity", "evidence", "event", "commercial_value")}
    assert load_audit_fixtures(ledger) == ids
    assert before == {t: ledger.count(t) for t in before}
    ref = SourceRef("notion_audit_fixture", "meeting_page", "622275a3be2383f98c5301c75d72b221")
    with pytest.raises(LedgerError, match="immutable"):
        ledger.ingest_raw(ref, "audit_2026-09-13", "silently revised", "2026-09-27", "2026-09-27")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger.db.execute("DELETE FROM raw_source WHERE native_id=?", (ref.native_id,))


def test_opportunity_without_deal_and_source_id_separation(audit):
    ledger, ids = audit
    opp = ledger.entity(ids["Coldharbour"]["opportunity"])
    assert opp["id"] != "09b275a3be238224aeb7813f30635247"
    assert opp["origin_evidence_id"]
    assert opp["use_case_code"] == "cold_chain_replenishment"
    assert opp["commercial_scope_id"]
    assert ledger.entity_for_source(SourceRef("airtable_audit_fixture", "deal", "Coldharbour")) is None


def test_wisla_pilot_distinct_from_unsigned_commercial_and_crm_stage(audit):
    ledger, ids = audit
    opp = ids["Westra"]["opportunity"]
    assert {e["event_type"] for e in _events(ledger, opp)} == {"pilot_signed"}
    assert [v["value_type"] for v in ledger.values_for_opportunity(opp)] == ["pilot_fee"]
    assert ledger.count("conflict") == 1
    assert not ledger.detect_claim_conflicts()  # CRM stage and contract status are distinct predicates.


def test_frostline_reported_signature_without_verified_actual(audit):
    ledger, ids = audit
    opp = ids["Coldharbour"]["opportunity"]
    events = _events(ledger, opp)
    assert {e["event_type"] for e in events} == {"technical_milestone", "commercial_signed"}
    signature = next(e for e in events if e["event_type"] == "commercial_signed")
    assert signature["verification"] == "unverified"
    assert signature["recorded_at"] is None
    assert signature["date_precision"] == "inferred_year_day_in_body"
    value = ledger.values_for_opportunity(opp)[0]
    assert value["amount_decimal"] == "580000"
    assert value["term_months"] == 24
    assert value["status"] == "signed_reported"
    assert value["usd_normalized"] is None


def test_hanbit_no_pilot_signature_sow_sent_or_summed_scenarios(audit):
    ledger, ids = audit
    opp = ids["Halvard"]["opportunity"]
    assert {e["event_type"] for e in _events(ledger, opp)} == {"pilot_verbal_yes", "sow_drafting"}
    values = ledger.values_for_opportunity(opp)
    assert len(values) == 2
    assert {v["scenario_group_id"] for v in values} == {values[0]["scenario_group_id"]}
    assert values[0]["scenario_group_id"] is not None


def test_rhodope_scope_and_money_versions_without_pilot_acv(audit):
    ledger, ids = audit
    opp = ids["Rhona"]["opportunity"]
    values = ledger.values_for_opportunity(opp)
    assert {v["value_type"] for v in values} == {"pilot_fee", "rollout_acv"}
    rollout = [v for v in values if v["value_type"] == "rollout_acv"]
    assert len(rollout) == 2
    assert rollout[1]["replaces_value_id"] == rollout[0]["value_id"]
    assert rollout[1]["scope_version"] == 2
    assert {e["event_type"] for e in _events(ledger, opp)} == {"pilot_signed"}


def test_kestrel_accounts_stay_separate_and_name_is_candidate(audit):
    ledger, ids = audit
    case = ids["Osprey"]
    assert case["account"] != case["other_account"]
    assert ledger.resolve_identity(entity_type="Account", raw_string="Osprey Grocers Ltd.") == ("candidate", None)
    assert ledger.entity(case["opportunity"])["resolution_status"] == "ambiguous"
    assert len(ledger.values_for_opportunity(case["opportunity"])) == 1


def test_kaveri_data_kind_not_data_received(audit):
    ledger, ids = audit
    opp = ids["Kavala"]["opportunity"]
    assert _events(ledger, opp) == []
    claim = ledger.db.execute("SELECT payload FROM claim WHERE predicate='data_kind'").fetchone()
    assert claim is not None and "POS sales history" in claim[0]


def test_norvane_lost_not_revived_and_solmar_stalled_not_lost(audit):
    ledger, ids = audit
    assert {e["event_type"] for e in _events(ledger, ids["Nordahl"]["opportunity"])} == {"lost"}
    assert {e["event_type"] for e in _events(ledger, ids["Solvik"]["opportunity"])} == {"stalled"}


def test_historical_knowledge_excludes_audit_copy(audit):
    ledger, ids = audit
    assert ledger.events_as_of("2026-09-13", mode="historically_known_state") == []
    assert ledger.events_as_of("2026-09-13", mode="retrospective_event_state")
    # Even a source seen early cannot establish prior knowledge when documented_at is missing.
    assert ledger.events_as_of("2026-09-13", mode="historically_known_state",
                               knowledge_cutoff="2026-09-30") == []


def test_historical_knowledge_requires_both_documented_and_seen_times():
    ledger = Ledger()
    ref = SourceRef("export", "note", "one")
    digest = ledger.ingest_raw(ref, "v1", "pilot signed", "2026-09-10", "2026-09-10")
    evidence = Evidence(source_ref=ref, source_version="v1", source_hash=digest,
                        start_offset=0, end_offset=12, verbatim_excerpt="pilot signed",
                        business_event_date="2026-09-09", documented_at="2026-09-10",
                        source_first_seen_at="2026-09-10", ingested_at="2026-09-10")
    ledger.add_evidence(evidence)
    ledger.add_event(Event(event_type="pilot_signed", account_id=stable_id("account", "test"),
                           contract_kind="pilot", event_date="2026-09-09",
                           first_seen_at="2026-09-10", evidence_ids=(evidence.evidence_id,),
                           details={"pilot_contract_id": "test-pilot"}))
    assert ledger.events_as_of("2026-09-09", mode="historically_known_state", knowledge_cutoff="2026-09-09") == []
    assert len(ledger.events_as_of("2026-09-13", mode="historically_known_state")) == 1
    ledger.close()


def test_event_taxonomy_and_no_synthetic_earlier_steps(audit):
    ledger, ids = audit
    with pytest.raises(LedgerError, match="closed taxonomy"):
        ledger.add_event(Event(event_type="outreach_sent", account_id=ids["Halvard"]["account"],
                               event_date="2026-09-10", evidence_ids=(stable_id("evidence", "x"),)))
    assert not any(e["event_type"] in {"initial_encounter", "pilot_started", "sow_sent"}
                   for e in ledger.events_as_of("2026-09-13", mode="retrospective_event_state"))


def test_unknown_money_and_verified_gate(audit):
    ledger, ids = audit
    value = ledger.values_for_opportunity(ids["Coldharbour"]["opportunity"])[0]
    evidence_id = value["source_evidence_ids"][0]
    common = dict(opportunity_id=value["opportunity_id"], scope_id=value["scope_id"],
                  currency_ISO="EUR", value_type="rollout_acv", source_evidence_ids=(evidence_id,))
    with pytest.raises(LedgerError, match="amount"):
        ledger.add_value(CommercialValue(**common, amount_decimal=None))
    with pytest.raises(LedgerError, match="contractual"):
        ledger.add_value(CommercialValue(**common, amount_decimal=Decimal("580000"),
                                         status="signed_verified"))


def test_identity_native_id_and_exact_email_require_account(audit):
    ledger, ids = audit
    ref = SourceRef("airtable_audit_fixture", "company", "recD7Z4zX4ghZJfgt")
    assert ledger.resolve_identity(entity_type="Account", raw_string="Halvard", source_ref=ref) == (
        "confirmed", ids["Halvard"]["account"])
    assert ledger.resolve_identity(entity_type="Contact", raw_string=" Hsiao-Wen@Example.COM ") == (
        "ambiguous", None)


def test_conflict_only_same_contract_scope_and_overlapping_time(audit):
    ledger, ids = audit
    evidence_id = stable_id("evidence", "622275a3be2383f98c5301c75d72b221:0")
    opp = ids["Westra"]["opportunity"]
    c1 = Claim(claim_id=stable_id("claim", "test:pilot_negative"), subject_id=opp,
               predicate="signed", polarity="negative", contract_kind="pilot",
               scope_id="scope", valid_from="2026-09-11", valid_to="2026-09-11",
               evidence_ids=(evidence_id,))
    c2 = replace(c1, claim_id=stable_id("claim", "test:commercial_positive"),
                 polarity="positive", contract_kind="commercial")
    ledger.add_claim(c1)
    ledger.add_claim(c2)
    assert (c1.claim_id, c2.claim_id) not in ledger.detect_claim_conflicts()
    c3 = replace(c2, claim_id=stable_id("claim", "test:pilot_positive"), contract_kind="pilot")
    ledger.add_claim(c3)
    assert (c1.claim_id, c3.claim_id) in ledger.detect_claim_conflicts()


def test_exact_evidence_span_and_verified_contract_gate(audit):
    ledger, ids = audit
    ref = SourceRef("export", "contract", "verified-one")
    digest = ledger.ingest_raw(ref, "v1", "Signed 2026-09-12 EUR 580000 per year", "2026-09-13", "2026-09-13")
    bad = Evidence(source_ref=ref, source_version="v1", source_hash=digest,
                   start_offset=0, end_offset=6, verbatim_excerpt="Unsigned", ingested_at="2026-09-13")
    with pytest.raises(LedgerError, match="span"):
        ledger.add_evidence(bad)
    evidence = replace(bad, evidence_id=stable_id("evidence", "test:contract"),
                       start_offset=0, end_offset=6, verbatim_excerpt="Signed",
                       assertion_type="document", documented_at="2026-09-13",
                       source_first_seen_at="2026-09-13")
    ledger.add_evidence(evidence)
    opp = ids["Coldharbour"]["opportunity"]
    scope = ledger.entity(opp)["commercial_scope_id"]
    incomplete = OfferOrContract(opportunity_id=opp, contract_kind="commercial",
                                 scope_id=scope, status="verified_signed",
                                 created_in_ledger_at="2026-09-13")
    with pytest.raises(LedgerError, match="Verified contract"):
        ledger.add_entity(incomplete)
    contract = replace(incomplete, id=stable_id("contract", "test:verified"),
                       document_ref="export:verified-one", party_names=("Coldharbour", "Vendora"),
                       signature_date="2026-09-12", term_start="2026-10-01", term_end="2027-09-30")
    ledger.add_entity(contract)
    value = CommercialValue(opportunity_id=opp, offer_or_contract_id=contract.id,
                            scope_id=scope, amount_decimal=Decimal("580000"),
                            currency_ISO="EUR", value_type="rollout_acv", unit="per_year",
                            status="signed_verified", verification="document_verified",
                            source_evidence_ids=(evidence.evidence_id,))
    ledger.add_value(value)
    assert ledger.values_for_opportunity(opp)[-1]["status"] == "signed_verified"


def test_jsonl_export_is_raw_only_and_idempotent(tmp_path):
    path = tmp_path / "export.jsonl"
    path.write_text('{"source_ref":{"system":"test","object_type":"note","native_id":"1"},"version":"v1","content":"draft SOW","first_seen_at":"2026-09-27","ingested_at":"2026-09-27"}\n', encoding="utf-8")
    ledger = Ledger()
    assert ingest_jsonl_export(ledger, path) == 1
    assert ingest_jsonl_export(ledger, path) == 1
    assert ledger.count("raw_source") == 1
    assert ledger.count("event") == 0
    ledger.close()
