"""Live wiring of contextual reconstruction and valuation into the read model and its validator."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal

import pytest

from src.belief.signals import availability, lexical_signals, make_signal
from src.ledger import Evidence, Ledger, SourceRef
from src.ledger.fixtures import load_audit_fixtures
from src.ledger.store import stable_id
from src.tracker import read_model
from src.tracker.read_model import _belief_context, _rows, _signal_group, materialize, write_store_and_contract
from scripts.validate_presentation_contract import validate

EXISTING = ("overview", "opportunities", "opportunity_details", "weekly_snapshots", "evidence_summaries", "review_queue")
SYSTEM, OBJECT = "notion_context", "meeting_page"
# One deal spread over unlinked notes (no opportunity identity), plus an AI-written CRM annotation.
DEAL = {
    "ctx-note-1": ("2026-02-02", ["Cold-chain warehouses with defrost cycles", "Integration: WMS with static setpoints",
                                  "Pilot scope: one freezer aisle", "Budget: pilot ~€90k",
                                  "rollout maybe €410k/yr if it works", "Verbal yes to paid pilot, SOW being drafted"]),
    "ctx-note-2": ("2026-03-15", ["Cold-chain warehouses with defrost cycles", "Exec committee approved: go to commercial",
                                  "ACV discussed €410k/yr", "Results: 9% lower kWh, no temperature excursions"]),
    "ctx-note-3": (None, ["SIGNED. €410k/yr, 3-yr term", "Rollout one freezer aisle first"]),
    "ctx-crm": ("2026-06-03", ["[2026-06-03 sync — Claude] Signed 1 Jun: €410k/yr."]),
}
FILLERS = {f"ctx-filler-{k:02d}": ("2026-04-01", [f"Note {k}: unrelated item{k} for site{k}"]) for k in range(20)}
DEAL_GROUPS = ["ctx-note-1", "ctx-note-2", "ctx-note-3"]


def _add_source(ledger: Ledger, native_id: str, day: str | None, texts: list[str]) -> list[str]:
    ref = SourceRef(SYSTEM, OBJECT, native_id)
    content = "\n".join(texts)
    seen = "2026-09-01T00:00:00+03:00"
    digest = ledger.ingest_raw(ref, "v1", content, seen, seen)
    ids, offset = [], 0
    for n, text in enumerate(texts):
        ev = Evidence(evidence_id=stable_id("ctx_evidence", f"{native_id}:{n}"), source_ref=ref, source_version="v1",
                      source_hash=digest, start_offset=offset, end_offset=offset + len(text), verbatim_excerpt=text,
                      assertion_type="firsthand_report", authorship="seller_staff", business_event_date=day,
                      documented_at=seen, source_first_seen_at=seen, ingested_at=seen)
        ids.append(ledger.add_evidence(ev))
        offset += len(text) + 1
    return ids


def _add_source_signals(ledger: Ledger, native_id: str, day: str | None, ids: list[str], texts: list[str],
                        subject_ref: str) -> None:
    for eid, text in zip(ids, texts):
        for n, r in enumerate(lexical_signals(text)):
            ledger.add_signal(make_signal(
                r["signal_type"], evidence_ids=[eid], method="deterministic_rule",
                id_seed=f"ctx:{eid}:{n}:{r['signal_type']}", effective_date=day, modality=r["modality"],
                observation=r["observation"], confidence=r["confidence"], contract_kind=r["contract_kind"],
                subject_ref=subject_ref, evidence_availability=availability(ledger, [eid]),
                details={**(r.get("details") or {}), "clause": r["clause"]}))


def load_context_corpus(ledger: Ledger) -> None:
    for native_id, (day, texts) in {**DEAL, **FILLERS}.items():
        ids = _add_source(ledger, native_id, day, texts)
        # Semantic integration writes source:<provider>:<native_id>; the 4-part form is accepted too.
        subject = f"source:{SYSTEM}:{OBJECT}:{native_id}" if native_id == "ctx-note-2" else f"source:{SYSTEM}:{native_id}"
        _add_source_signals(ledger, native_id, day, ids, texts, subject)


@pytest.fixture
def audit():
    ledger = Ledger()
    try:
        yield ledger, load_audit_fixtures(ledger)
    finally:
        ledger.close()


@pytest.fixture
def context_ledger(audit):
    ledger, ids = audit
    load_context_corpus(ledger)
    return ledger, ids


def _reconstructed(beliefs):
    return next(x for x in beliefs["reconstructed_opportunities"].values() if x["groups"] == DEAL_GROUPS)


def test_signal_group_accepts_semantic_and_qualified_subject_refs():
    groups = {"rec1": [], "abc:def": [], "page-9": []}
    group_of = {"e1": "rec1", "e2": "page-9"}
    sig = lambda ref, ids=("e1",): {"subject_ref": ref, "evidence_ids": list(ids)}
    assert _signal_group(sig("source:airtable:rec1"), groups, group_of) == "rec1"
    assert _signal_group(sig("source:notion:meeting_page:page-9"), groups, group_of) == "page-9"
    assert _signal_group(sig("source:notion:abc:def"), groups, group_of) == "abc:def"
    assert _signal_group(sig("source:page-9"), groups, group_of) == "page-9"
    assert _signal_group(sig("source:notion:unknown", ("e2",)), groups, group_of) == "page-9"
    assert _signal_group(sig("source:notion:unknown", ("e1", "e2")), groups, group_of) is None
    assert _signal_group(sig(None, ("missing",)), groups, group_of) is None


def test_context_inputs_cover_sources_signals_and_seeds(context_ledger):
    ledger, _ = context_ledger
    evidence = {e["evidence_id"]: e for e in _rows(ledger, "evidence")}
    signals = read_model.collect_signals(ledger)
    opps = {o["id"]: o for o in _rows(ledger, "entity") if "use_case_code" in o}
    ctx = _belief_context(ledger, evidence, signals, sorted(opps), _rows(ledger, "event"),
                          _rows(ledger, "commercial_value"))
    assert sum(len(v) for v in ctx["sources"].values()) == len(evidence)
    note = ctx["sources"]["ctx-note-3"]
    assert sorted(e["text"] for e in note) == sorted(DEAL["ctx-note-3"][1])
    assert [e["evidence_id"] for e in note] == sorted(e["evidence_id"] for e in note)
    assert all(e["date"] is None for e in note)
    assert {e["date"] for e in ctx["sources"]["ctx-note-1"]} == {"2026-02-02"}
    assert set(DEAL_GROUPS) <= set(ctx["source_signals"])
    assert all(s["opportunity_id"] is None for sigs in ctx["source_signals"].values() for s in sigs)
    for oid, opp in opps.items():
        origin = evidence.get(opp["origin_evidence_id"])
        if origin:
            assert origin["source_ref"]["native_id"] in ctx["seed_groups"][oid]
        assert not ctx["seed_groups"][oid] & {"ctx-note-1", "ctx-note-2", "ctx-note-3", "ctx-crm"}


def test_live_reconstruction_recognises_signed_acv(context_ledger, tmp_path):
    ledger, _ = context_ledger
    model = materialize(ledger)
    beliefs = model["belief_states"]
    deal = _reconstructed(beliefs)
    assert deal["status"] == "inferred_from_context" and deal["links"]
    value = deal["valuation"]
    assert value["kind"] == "recognized_signed_acv" and value["recognized"] is True
    assert value["amount_usd"] == "459200" and value["signature_date"] == "2026-06-01"
    assert value["reasons"] and value["evidence_ids"]
    assert value["documentary_verified"] is False
    # The 4-part subject_ref signals were linked into the deal.
    linked = {(s.get("evidence_ids") or [None])[0] for s in deal["observed_signals"]}
    assert stable_id("ctx_evidence", "ctx-note-2:2") in linked
    assert "ctx-crm" not in deal["groups"]
    totals = beliefs["overview"]["valuation"]
    assert totals["recognized_signed_acv_usd"] == "459200" and totals["recognized_deal_count"] == 1
    assert totals["documentary_verified_usd"] == model["overview"]["verified_signed_acv_usd"] == "0"
    assert beliefs["overview"]["value_buckets"]["verified_actual_usd"] == "0"
    assert all(x["verified_actual_usd"] == "0" for x in model["opportunity_details"])
    write_store_and_contract(model, tmp_path / "state.sqlite", tmp_path / "runtime")
    assert validate(tmp_path / "runtime", tmp_path / "state.sqlite")["belief_opportunities"] == len(beliefs["opportunities"])


def test_context_wiring_leaves_existing_files_identical(context_ledger, monkeypatch):
    ledger, _ = context_ledger
    with_context = materialize(ledger)
    original = read_model.belief_presentation.build

    def without_context(**kwargs):
        for key in ("sources", "source_signals", "seed_groups"):
            kwargs.pop(key)
        return original(**kwargs)

    monkeypatch.setattr(read_model.belief_presentation, "build", without_context)
    plain = materialize(ledger)
    for name in EXISTING:
        assert with_context[name] == plain[name], name
    assert plain["belief_states"]["reconstructed_opportunities"] == {}
    assert with_context["belief_states"]["reconstructed_opportunities"]
    for oid, entry in with_context["belief_states"]["opportunities"].items():
        assert entry["verified"] == plain["belief_states"]["opportunities"][oid]["verified"]


def test_context_belief_file_is_deterministic(context_ledger, tmp_path):
    ledger, _ = context_ledger
    first, second = materialize(ledger), materialize(ledger)
    dump = lambda m: json.dumps(m["belief_states"], sort_keys=True, ensure_ascii=False)
    assert dump(first) == dump(second)
    a = write_store_and_contract(first, tmp_path / "a.sqlite", tmp_path / "a")
    b = write_store_and_contract(second, tmp_path / "b.sqlite", tmp_path / "b")
    assert a["files"] == b["files"]


# ---------------------------------------------------------------------------
# Validator tampering on the new sections.

def _tamper(out, mutate):
    path = out / "belief_states.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload["data"])
    path.write_text(json.dumps(payload), encoding="utf-8")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _deal(d):
    return next(x for x in d["reconstructed_opportunities"].values() if (x["valuation"] or {}).get("recognized"))


def _of_kind(d, kind):
    return next(x["valuation"] for _, x in sorted(d["opportunities"].items()) if x["valuation"]["kind"] == kind)


def _commercial(d):
    return _deal(d)["current"]["states"]["commercial_status"]


def _bump(d, key):
    totals = d["overview"]["valuation"]
    totals[key] = str(Decimal(totals[key]) + 1)


def _range_excludes(d):
    v = _of_kind(d, "estimate")
    v["range_usd"] = [str(Decimal(v["amount_usd"]) + 1), str(Decimal(v["amount_usd"]) + 2)]


TAMPERING = {
    "valuation kind": (lambda d: _of_kind(d, "estimate").update(kind="forecast"), "Valuation kind invalid"),
    "valuation missing": (lambda d: _deal(d).update(valuation=None), "Valuation missing"),
    "recognised contested": (lambda d: _commercial(d).update(contested=True), "uncontested signature belief"),
    "recognised low band": (lambda d: _commercial(d).update(band="medium"), "uncontested signature belief"),
    "recognised without signature": (lambda d: _commercial(d).update(value="terms_negotiation"),
                                     "uncontested signature belief"),
    "recognised before window": (lambda d: _deal(d)["valuation"].update(signature_date="2025-12-31"),
                                 "outside the target window"),
    "recognised after window": (lambda d: _deal(d)["valuation"].update(signature_date="2027-04-01"),
                                "outside the target window"),
    "recognised without date": (lambda d: _deal(d)["valuation"].update(signature_date=None), "outside the target window"),
    "recognised without amount": (lambda d: _deal(d)["valuation"].update(amount_usd=None), "without an amount"),
    "recognised documentary": (lambda d: _deal(d)["valuation"].update(documentary_verified=True),
                               "outside the documentary gate"),
    "recognised total": (lambda d: _bump(d, "recognized_signed_acv_usd"), "Recognised signed ACV total mismatch"),
    "recognised count": (lambda d: d["overview"]["valuation"].update(recognized_deal_count=2),
                         "Recognised signed ACV total mismatch"),
    "documentary figure": (lambda d: d["overview"]["valuation"].update(documentary_verified_usd="100"),
                           "Documentary-verified figure differs"),
    "estimate range": (_range_excludes, "outside its range"),
    "estimate basis": (lambda d: _of_kind(d, "estimate").update(basis="gut_feel"), "Estimate basis invalid"),
    "estimate recognised": (lambda d: _of_kind(d, "estimate").update(recognized=True), "Only a recognised"),
    "unknown with amount": (lambda d: _of_kind(d, "unknown").update(amount_usd="5"), "Unknown valuation carries"),
    "estimated total": (lambda d: _bump(d, "estimated_open_pipeline_usd"), "Estimated pipeline total mismatch"),
    "weighted total": (lambda d: _bump(d, "weighted_pipeline_usd"), "Estimated pipeline total mismatch"),
    "reconstructed single source": (lambda d: _deal(d).update(groups=_deal(d)["groups"][:1]), "at least two"),
    "reconstructed without links": (lambda d: _deal(d).update(links=[]), "without links"),
    "reconstructed verified": (lambda d: _commercial(d).update(verified=True), "Reconstructed deal marked verified"),
    "reconstructed count": (lambda d: d["overview"].update(reconstructed_deal_count=99), "Reconstructed deal count"),
    "reconstructed signal evidence": (lambda d: _deal(d)["observed_signals"][0]["evidence_ids"].append("not-published"),
                                      "unresolved evidence"),
    "valuation evidence": (lambda d: _deal(d)["valuation"]["evidence_ids"].append("not-published"),
                           "unresolved evidence"),
    "corroboration evidence": (lambda d: _deal(d)["corroboration"][0].update(evidence_id="not-published"),
                               "unresolved evidence"),
}


@pytest.mark.parametrize("case", sorted(TAMPERING))
def test_validator_rejects_context_tampering(context_ledger, tmp_path, case):
    ledger, _ = context_ledger
    out = tmp_path / "runtime"
    write_store_and_contract(materialize(ledger), tmp_path / "state.sqlite", out)
    validate(out, tmp_path / "state.sqlite")
    mutate, message = TAMPERING[case]
    _tamper(out, mutate)
    with pytest.raises(ValueError, match=message):
        validate(out, tmp_path / "state.sqlite")
