"""Belief layer in the quantitative model, read model and presentation contract."""
from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from src.belief.ontology import VERSION as BELIEF_VERSION
from src.belief.signals import availability, make_signal
from src.ledger import Evidence, Ledger, SourceRef
from src.ledger.fixtures import load_audit_fixtures
from src.ledger.store import stable_id
from src.models import quantitative
from src.tracker import read_model
from src.tracker.read_model import FILES, materialize, write_store_and_contract
from scripts.validate_presentation_contract import validate

AS_OF = "2026-09-13"
EXISTING = ("overview", "opportunities", "opportunity_details", "weekly_snapshots", "evidence_summaries", "review_queue")


@pytest.fixture
def audit():
    ledger = Ledger()
    try:
        yield ledger, load_audit_fixtures(ledger)
    finally:
        ledger.close()


def _without_belief(q):
    q = json.loads(json.dumps(q))
    q.pop("belief_metrics")
    assert q["model_versions"].pop("D") == BELIEF_VERSION
    for row in q["opportunities"].values():
        row.pop("model_d")
    return q


def _pilot_signals(ledger, oid, day="2026-09-05"):
    """Soft execution evidence for one opportunity, anchored to its existing fixture evidence."""
    ids = [ledger.entity(oid)["origin_evidence_id"]]
    return [make_signal(kind, evidence_ids=ids, method="deterministic_rule", id_seed=f"test:{oid}:{kind}",
                        effective_date=day, confidence="high", contract_kind="pilot", opportunity_id=oid,
                        evidence_availability=availability(ledger, ids))
            for kind in ("kickoff_completed", "pilot_work_underway", "data_received")]


def _evidence(ledger, slug, day, first_seen):
    ref = SourceRef("belief_fixture", "meeting_page", slug)
    text = f"Belief fixture note {slug}"
    digest = ledger.ingest_raw(ref, "v1", text, first_seen, first_seen)
    ev = Evidence(evidence_id=stable_id("evidence", slug), source_ref=ref, source_version="v1", source_hash=digest,
                  start_offset=0, end_offset=len(text), verbatim_excerpt=text, assertion_type="firsthand_report",
                  authorship="seller_staff", business_event_date=day, documented_at=first_seen,
                  source_first_seen_at=first_seen, ingested_at=first_seen)
    return ledger.add_evidence(ev)


def test_belief_file_materializes_and_validates(audit, tmp_path):
    ledger, _ = audit
    model = materialize(ledger)
    beliefs = model["belief_states"]
    assert "belief_states" in FILES
    assert beliefs["kind"] == "belief_states" and beliefs["engine_version"] == BELIEF_VERSION
    assert beliefs["provenance"]["engine_version"] == BELIEF_VERSION
    assert set(beliefs["opportunities"]) == {x["opportunity_id"] for x in model["opportunity_details"]}
    assert set(beliefs["review_triage"]) == {r["review_id"] for r in model["review_queue"]} | \
        {r["review_id"] for r in beliefs["belief_review_items"]}
    assert [w["week_end"] for w in beliefs["weekly"]] == [s["week_end"] for s in model["weekly_snapshots"]]
    assert beliefs["overview"]["value_buckets"]["verified_actual_usd"] == model["overview"]["verified_signed_acv_usd"] == "0"
    manifest = write_store_and_contract(model, tmp_path / "state.sqlite", tmp_path / "runtime")
    assert "belief_states.json" in manifest["files"]
    payload = json.loads((tmp_path / "runtime/belief_states.json").read_text(encoding="utf-8"))
    assert set(payload) == {"schema_version", "kind", "data"} and payload["kind"] == "belief_states"
    result = validate(tmp_path / "runtime", tmp_path / "state.sqlite")
    assert result["belief_opportunities"] == result["opportunities"] == len(model["opportunity_details"])
    assert result["decision_needed_reviews"] == beliefs["review_summary"]["decision_needed"]
    assert result["reviews"] == len(model["review_queue"])
    with sqlite3.connect(tmp_path / "state.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM belief_state").fetchone()[0] == len(beliefs["opportunities"])
        assert db.execute("SELECT COUNT(*) FROM review_triage").fetchone()[0] == len(beliefs["review_triage"])


def test_quantitative_model_d_is_additive(audit):
    ledger, _ = audit
    q = quantitative.weekly_state(ledger, AS_OF)
    assert q["model_versions"]["D"] == BELIEF_VERSION
    assert "flags" not in q["belief_metrics"]
    assert q["belief_metrics"]["value_buckets"]["verified_actual_usd"] == q["verified_actual_usd"]
    assert q["belief_metrics"]["value_buckets"]["reported_unverified_usd"] == q["reported_signed_possible_acv_usd"]
    assert all(set(x["model_d"]) == {"states", "headline", "inferred_stage"} for x in q["opportunities"].values())
    for mode in ("retrospective_event_state", "historically_known_state"):
        with_signals = quantitative.weekly_state(ledger, AS_OF, mode=mode)
        without = quantitative.weekly_state(ledger, AS_OF, mode=mode, atomic_signals=[])
        assert _without_belief(with_signals) == _without_belief(without)


def test_existing_presentation_identical_with_and_without_signals(audit, monkeypatch):
    ledger, _ = audit
    with_signals = materialize(ledger)
    monkeypatch.setattr(read_model, "collect_signals", lambda _ledger: [])
    without = materialize(ledger)
    for name in EXISTING:
        assert with_signals[name] == without[name], name
    assert with_signals["overview"]["verified_signed_acv_usd"] == without["overview"]["verified_signed_acv_usd"] == "0"
    assert set(without["belief_states"]["overview"]["inferred_stage_distribution"]) == {"unknown"}
    assert with_signals["belief_states"]["overview"]["inferred_stage_distribution"] != \
        without["belief_states"]["overview"]["inferred_stage_distribution"]


def test_persisted_signals_change_beliefs_not_actual(audit, tmp_path):
    ledger, ids = audit
    oid = ids["Halvard"]["opportunity"]
    before = materialize(ledger)
    assert before["belief_states"]["opportunities"][oid]["current"]["states"]["pilot_status"]["value"] != "active"
    for signal in _pilot_signals(ledger, oid):
        ledger.add_signal(signal)
    after = materialize(ledger)
    pilot = after["belief_states"]["opportunities"][oid]["current"]["states"]["pilot_status"]
    assert pilot["value"] == "active" and pilot["band"] in {"high", "very_high"}
    assert pilot["verified"] is False and pilot["inferred"] is True
    assert after["belief_states"]["opportunities"][oid]["inferred_stage"] == "pilot_active_or_completed"
    assert after["belief_states"]["overview"]["operationally_active_pilots"] == 1
    for name in EXISTING:
        assert before[name] == after[name], name
    assert after["overview"]["verified_signed_acv_usd"] == "0"
    q = quantitative.weekly_state(ledger, AS_OF)
    assert q["opportunities"][oid]["model_d"]["states"]["pilot_status"][0] == "active"
    assert q["verified_actual_usd"] == "0" and q["belief_metrics"]["value_buckets"]["verified_actual_usd"] == "0"
    write_store_and_contract(after, tmp_path / "state.sqlite", tmp_path / "runtime")
    assert validate(tmp_path / "runtime", tmp_path / "state.sqlite")["belief_opportunities"] > 0


def test_historically_known_belief_excludes_later_discovered_evidence(audit):
    ledger, ids = audit
    oid = ids["Halvard"]["opportunity"]
    early = _evidence(ledger, "belief_early", "2026-06-01", "2026-06-01")
    late = _evidence(ledger, "belief_late", "2026-06-05", "2026-08-01")
    for kind, eid, day in (("kickoff_completed", early, "2026-06-01"), ("pilot_completed", late, "2026-06-05")):
        ledger.add_signal(make_signal(kind, evidence_ids=[eid], method="deterministic_rule", id_seed=f"hist:{kind}",
                                      effective_date=day, confidence="high", contract_kind="pilot", opportunity_id=oid,
                                      evidence_availability=availability(ledger, [eid])))
    pilot = lambda q: q["opportunities"][oid]["model_d"]["states"]["pilot_status"][0]
    retro = quantitative.weekly_state(ledger, "2026-06-30")
    known = quantitative.weekly_state(ledger, "2026-06-30", mode="historically_known_state")
    later = quantitative.weekly_state(ledger, "2026-06-30", mode="historically_known_state", knowledge_cutoff="2026-08-02")
    assert pilot(retro) == "completed"
    assert pilot(known) == "active"
    assert pilot(later) == "completed"
    assert retro["verified_actual_usd"] == known["verified_actual_usd"] == later["verified_actual_usd"] == "0"


def _tamper(out, mutate):
    path = out / "belief_states.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload["data"])
    path.write_text(json.dumps(payload), encoding="utf-8")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _first(data):
    return next(iter(data["opportunities"].values()))


def _set_verified_signed(data):
    state = _first(data)["current"]["states"]["commercial_status"]
    state.update(value="verified_signed", band="very_high", verified=True)


TAMPERING = {
    "missing evidence": (lambda d: _first(d)["current"]["states"]["pilot_status"]["strongest_evidence_ids"].append(
        "not-published"), "unresolved evidence"),
    "observed signal evidence": (lambda d: d["belief_review_items"].append(
        {"review_id": "x", "opportunity_id": None, "evidence_ids": ["not-published"], "required_action": "x"}),
        "unresolved evidence"),
    "invalid band": (lambda d: _first(d)["current"]["states"]["momentum"].update(band="certain"), "Invalid belief band"),
    "invalid value": (lambda d: _first(d)["current"]["states"]["pilot_status"].update(value="signed"), "outside ontology"),
    "verified inferred state": (lambda d: _first(d)["current"]["states"]["pilot_status"].update(verified=True),
                                "verified outside the documentary gate"),
    "verified without gate": (_set_verified_signed, "verified outside the documentary gate"),
    "missing triage": (lambda d: d["review_triage"].pop(next(iter(d["review_triage"]))), "triage"),
    "actual changed": (lambda d: _first(d)["verified"].update(verified_actual_usd="100"), "Verified Actual"),
    "bucket changed": (lambda d: d["overview"]["value_buckets"].update(verified_actual_usd="100"), "Verified Actual"),
    "history forward-filled": (lambda d: d["weekly"][-1].update(historically_known={}), "forward-filled"),
    "weeks differ": (lambda d: d["weekly"].pop(0), "weeks differ"),
    "population": (lambda d: d["opportunities"].pop(next(iter(d["opportunities"]))), "population"),
}


@pytest.mark.parametrize("case", sorted(TAMPERING))
def test_validator_rejects_belief_tampering(audit, tmp_path, case):
    ledger, _ = audit
    out = tmp_path / "runtime"
    write_store_and_contract(materialize(ledger), tmp_path / "state.sqlite", out)
    mutate, message = TAMPERING[case]
    _tamper(out, mutate)
    with pytest.raises(ValueError, match=message):
        validate(out, tmp_path / "state.sqlite")


def test_validator_rejects_sqlite_belief_drift(audit, tmp_path):
    ledger, _ = audit
    out = tmp_path / "runtime"
    write_store_and_contract(materialize(ledger), tmp_path / "state.sqlite", out)
    with sqlite3.connect(tmp_path / "state.sqlite") as db:
        db.execute("DELETE FROM review_triage WHERE review_id=(SELECT MIN(review_id) FROM review_triage)")
    with pytest.raises(ValueError, match="review triage mismatch"):
        validate(out, tmp_path / "state.sqlite")
