"""Belief-layer acceptance cases A-H plus sensor and boundary checks."""
from __future__ import annotations

import pytest

from src.belief import engine, metrics, review_policy
from src.belief.jev_sensors import apply as apply_sensor
from src.belief.ontology import band_rank
from src.belief.signals import SignalError, lexical_signals, make_signal

OPP = "opp-1"


def sig(kind, day, *, source=None, modality="asserted", confidence="medium", method="luna_semantic",
        kind_of_contract=None, first_seen=None, documented=None, polarity="positive", n=0, details=None):
    source = source or f"note-{day}"
    eid = f"ev:{source}:{kind}:{n}"
    return make_signal(kind, evidence_ids=[eid], method=method, id_seed=f"{source}:{kind}:{day}:{n}:{modality}",
                       effective_date=day, modality=modality, confidence=confidence, polarity=polarity,
                       contract_kind=kind_of_contract, opportunity_id=OPP, details=details,
                       evidence_availability=[{"evidence_id": eid, "documented_at": documented or day,
                                               "source_first_seen_at": first_seen or day,
                                               "independence_group": source}])


def from_text(text, day, source=None):
    source = source or f"note-{day}"
    out = []
    for n, r in enumerate(lexical_signals(text)):
        out.append(sig(r["signal_type"], day, source=source, modality=r["modality"], confidence=r["confidence"],
                       method="deterministic_rule", kind_of_contract=r["contract_kind"], n=n, details=r["details"]))
    return out


def meeting(day):
    return sig("meeting_held", day, method="deterministic_rule", confidence="high")


def state(signals, as_of="2026-06-30", **kw):
    return engine.infer(signals, as_of, **kw)["states"]


# A. Multiple soft signals imply a strong state, without any signed document.
def test_a_soft_signals_imply_active_pilot_without_signature():
    signals = [sig("data_received", "2026-05-04"), sig("kickoff_completed", "2026-05-11"),
               meeting("2026-05-11"), meeting("2026-05-25"), meeting("2026-06-08")]
    pilot = state(signals)["pilot_status"]
    assert pilot["value"] == "active"
    assert band_rank(pilot["band"]) >= band_rank("high")
    assert {"data_received", "kickoff_completed", "recurring_interaction"} <= {e["signal_type"] for e in pilot["supporting"]}
    assert any("No signed pilot agreement" in m for m in pilot["missing_expected"])
    assert "Against: No signed pilot agreement" in pilot["explanation"]
    assert not any(s["signal_type"] == "reported_signature" for s in signals)


# B. Planning is not execution.
def test_b_planned_pilot_is_not_active():
    signals = from_text("Pilot planned for next month", "2026-06-01")
    assert all(s["signal_type"] != "kickoff_completed" for s in signals)
    pilot = state(signals + [sig("pilot_scope_agreed", "2026-06-01")])["pilot_status"]
    assert pilot["value"] == "planned"
    planned_luna = sig("kickoff_completed", "2026-06-01", modality="planned")
    assert planned_luna["signal_type"] == "kickoff_scheduled" and planned_luna["details"]["retyped_from"] == "kickoff_completed"
    assert state([planned_luna])["pilot_status"]["value"] != "active"


# C. Conditional statements never imply commitment.
def test_c_conditional_rollout_is_not_commitment():
    signals = from_text("If the pilot works, we will roll out", "2026-06-01")
    luna = sig("verbal_commitment", "2026-06-01", modality="conditional", kind_of_contract="commercial")
    assert luna["signal_type"] == "customer_interest"
    s = state(signals + [luna])
    assert s["buyer_commitment"]["value"] not in {"verbal_commitment", "committed"}
    assert s["commercial_status"]["value"] not in {"terms_agreed", "reported_signed", "verified_signed"}
    indicative = from_text("rollout maybe €930k/yr if it works", "2026-06-01")
    assert indicative and all(x["details"].get("indicative") for x in indicative)


# D. Positive commercial signals followed by "budget frozen indefinitely".
def test_d_later_budget_freeze_updates_state():
    positive = [sig("verbal_commitment", "2026-04-01", kind_of_contract="commercial", confidence="high"),
                sig("commercial_terms_discussed", "2026-04-15", kind_of_contract="commercial", confidence="high"),
                sig("legal_involved", "2026-04-20"), meeting("2026-04-20")]
    before = state(positive, as_of="2026-05-01")
    freeze = from_text("Budget frozen indefinitely", "2026-05-10")
    assert {s["signal_type"] for s in freeze} == {"budget_blocker"}
    after = state(positive + freeze, as_of="2026-05-20")
    assert after["blocker_state"]["value"] == "active" and "budget_blocker" in after["blocker_state"]["blocker_kinds"]
    assert after["momentum"]["value"] == "stalled"
    assert after["commercial_status"]["opposition_points"] > 0
    assert band_rank(after["buyer_commitment"]["band"]) < band_rank(before["buyer_commitment"]["band"]) or \
        after["buyer_commitment"]["value"] == "withdrawn"
    assert after["commercial_status"]["contradicting"][0]["signal_type"] == "budget_blocker"


# E. Inferred states never change Verified Actual.
def test_e_inference_never_reaches_verified_actual():
    signals = [sig("data_received", "2026-05-04"), sig("kickoff_completed", "2026-05-11"),
               sig("commercial_terms_agreed", "2026-06-01", kind_of_contract="commercial", confidence="high"),
               sig("reported_signature", "2026-06-10", kind_of_contract="commercial", confidence="high"),
               meeting("2026-05-11"), meeting("2026-05-25"), meeting("2026-06-08")]
    belief = engine.infer(signals, "2026-06-30")
    assert belief["states"]["commercial_status"]["value"] == "reported_signed"
    assert belief["states"]["commercial_status"]["verified"] is False
    assert belief["states"]["commercial_status"]["missing_expected"] == ["No documentary contract verification"]
    m = metrics.portfolio({OPP: belief}, {OPP: {"known_open_value_usd": None}}, verified_actual_usd="0")
    assert m["value_buckets"]["verified_actual_usd"] == "0"
    with pytest.raises(SignalError):
        make_signal("formal_signature_verified", evidence_ids=["e"], method="luna_semantic", id_seed="x",
                    opportunity_id=OPP, effective_date="2026-06-10")


# F. Historical reconstruction without hindsight.
def test_f_later_discovered_evidence_does_not_leak():
    early = [sig("verbal_commitment", "2026-03-01", kind_of_contract="pilot", first_seen="2026-03-02")]
    late_found = sig("kickoff_completed", "2026-03-10", first_seen="2026-05-01", documented="2026-05-01")
    retro = state(early + [late_found], as_of="2026-03-20")
    known = state(early + [late_found], as_of="2026-03-20", mode="historically_known", knowledge_cutoff="2026-03-20")
    assert any(e["signal_type"] == "kickoff_completed" for x in retro.values() for e in x["supporting"])
    assert not any(e["signal_type"] == "kickoff_completed" for x in known.values() for e in x["supporting"])
    assert known["pilot_status"]["value"] == "committed"
    future = sig("pilot_completed", "2026-04-01")
    assert state(early + [future], as_of="2026-03-20")["pilot_status"]["value"] != "completed"


# G. Several independent medium signals beat any one of them.
def test_g_weak_signals_combine():
    parts = [sig("legal_involved", "2026-06-01", source="a"), sig("security_review_started", "2026-06-05", source="b"),
             sig("commercial_terms_discussed", "2026-06-07", source="c", kind_of_contract="commercial"),
             sig("procurement_mentioned", "2026-06-09", source="d")]
    combined = state(parts)["procurement_status"]
    singles = [state([p])["procurement_status"] for p in parts]
    assert combined["value"] == "underway"
    assert all(band_rank(combined["band"]) > band_rank(s["band"]) for s in singles)
    assert combined["support_points"] > max(s["support_points"] for s in singles)
    repeated = state([sig("legal_involved", "2026-06-01", source="a", n=i) for i in range(4)])["procurement_status"]
    assert repeated["support_points"] == state([parts[0]])["procurement_status"]["support_points"]


# H. Coherent high-confidence soft evidence does not enter review.
def test_h_coherent_inference_needs_no_review():
    signals = [sig("data_received", "2026-05-04"), sig("kickoff_completed", "2026-05-11"),
               sig("technical_owner_assigned", "2026-05-11"), meeting("2026-05-11"), meeting("2026-05-25"),
               meeting("2026-06-08")]
    belief = engine.infer(signals, "2026-06-30")
    assert review_policy.belief_review_items(OPP, belief) == []
    soft = review_policy.triage({"review_id": "r1", "reason": "required_event_details_not_extracted", "opportunity_id": OPP},
                                accounts_with_multiple_scopes=set(), account_of={OPP: "acct"})
    assert soft["decision_needed"] is False
    contract = review_policy.triage({"review_id": "r2", "reason": "reported_signature_pending_documentary_verification",
                                     "opportunity_id": OPP}, accounts_with_multiple_scopes=set(), account_of={OPP: "acct"})
    assert contract["decision_needed"] is True
    contested = engine.infer([sig("kickoff_completed", "2026-05-11"), sig("pilot_work_underway", "2026-05-20"),
                              sig("project_paused", "2026-06-01", confidence="high"),
                              sig("pilot_work_underway", "2026-06-02", source="x")], "2026-06-30")
    assert contested["states"]["pilot_status"]["value"] in {"active", "paused"}


def test_reversal_then_revival_and_history_kept():
    start = [sig("kickoff_completed", "2026-03-01"), sig("data_received", "2026-03-02")]
    paused = start + [sig("project_paused", "2026-04-01", confidence="high")]
    s = state(paused, as_of="2026-04-10")
    assert s["pilot_status"]["value"] == "paused"
    assert any(h["signal_type"] == "kickoff_completed" for h in engine.infer(paused, "2026-04-10")["history"])
    revived = paused + [sig("revived", "2026-04-20"), sig("pilot_work_underway", "2026-04-21")]
    assert state(revived, as_of="2026-04-25")["pilot_status"]["value"] == "active"


def test_inactivity_is_temporal_and_stale_caps_current_state():
    signals = [sig("data_received", "2026-01-04"), sig("kickoff_completed", "2026-01-11"),
               meeting("2026-01-11"), meeting("2026-01-25"), meeting("2026-02-08")]
    fresh = state(signals, as_of="2026-02-15")
    old = state(signals, as_of="2026-06-30")
    assert fresh["momentum"]["value"] in {"strong", "steady"}
    assert old["momentum"]["value"] == "stalled" and old["momentum"]["band"] == "high"
    assert old["pilot_status"]["stale"] and band_rank(old["pilot_status"]["band"]) <= band_rank("medium")


def test_lexical_sensor_on_dataset_phrases():
    kinds = lambda text: {(r["signal_type"], r["modality"], r["contract_kind"]) for r in lexical_signals(text)}
    assert ("verbal_commitment", "asserted", "pilot") in kinds("Verbal yes to paid pilot, SOW being drafted")
    assert ("pilot_scope_agreed", "asserted", "pilot") in kinds("Verbal yes to paid pilot, SOW being drafted")
    assert ("reported_signature", "asserted", "pilot") in kinds("Pilot signed: €185k, 13 weeks")
    assert ("reported_signature", "asserted", "commercial") in kinds("SIGNED. €580k/yr, 2-yr term")
    assert ("reported_signature", "negated", "unknown") in kinds("Contract NOT signed yet - still with their procurement/legal")
    assert {"procurement_started", "legal_involved"} <= {k for k, *_ in kinds("Contract NOT signed yet - still with their procurement/legal")}
    assert ("explicit_rejection", "asserted", "unknown") in kinds("Closed - not a priority vs capacity ramp.")
    assert {k for k, *_ in kinds("Lost - security review blocked data leaving site")} >= {"explicit_rejection", "legal_blocker"}
    assert lexical_signals("[2026-07-20 sync — Claude] Lead from RetailForward West 2026; ~5% pilot intent by 23 Aug.") == []
    assert lexical_signals("~60% conversion to deployment.") == []
    assert ("kickoff_completed", "completed", "pilot") in kinds("Pilot live since 21 Feb.")
    assert ("reported_signature", "asserted", "commercial") in kinds("Signed 16 May: €580k/yr.")
    assert ("pricing_discussed", "conditional", "commercial") in kinds("rollout maybe €1.1M/yr if it works")
    assert not any(m == "negated" for _, m, _ in kinds("they want it in the WMS not as a separate tool"))
    assert not any(m == "negated" for _, m, _ in kinds("Results: 14% fewer expiry write-offs, no constraint violations"))
    assert ("pilot_work_underway", "asserted", "unknown") in kinds("wk 4. next: interim results to their VP")
    assert all(r["details"].get("seller_plan") for r in lexical_signals("Next: send one-pager, book scoping w/ Juhani's team"))
    assert "meeting_held" not in {k for k, *_ in kinds("Keen - wants a deep dive with their engineers")}
    assert ("commercial_terms_discussed", "asserted", "commercial") in kinds("pricing not agreed, pushback on annual fee")


def test_jev_sensor_moves_one_signal_at_most_one_band_and_only_weakens_modality():
    s = sig("kickoff_completed", "2026-05-01", confidence="medium")
    reading = lambda sensor, choice, band="high": [{"sensor": sensor, "choice": choice, "reading_band": band}]
    planned = apply_sensor(s, reading("pilot_activity", "planned"))
    assert planned["signal_type"] == "kickoff_scheduled"
    stronger = apply_sensor(s, reading("pilot_activity", "active"))
    assert stronger["signal_confidence"] == "high"
    capped = apply_sensor(stronger, reading("pilot_activity", "active"))
    assert capped["signal_confidence"] == "high"
    ignored = apply_sensor(s, reading("statement_modality", "planned", band="low"))
    assert ignored["signal_type"] == "kickoff_completed"
    one = engine.infer([stronger], "2026-05-10")["states"]["pilot_status"]
    assert band_rank(one["band"]) <= band_rank("medium")


def test_seller_plan_is_inert_but_customer_plan_still_counts_as_plan():
    from src.belief.signals import semantic_readings
    def build(actor):
        r = semantic_readings("atomic_signals", {"quote": "We will send the SOW next week", "signal_type": "pilot_scope_agreed",
                                                 "modality": "planned", "actor": actor, "contract_kind": "pilot",
                                                 "effective_date": None})[0]
        return make_signal(r["signal_type"], evidence_ids=["e"], method="luna_semantic", id_seed=actor, opportunity_id=OPP,
                           effective_date="2026-06-01", modality=r["modality"], details=r["details"])
    assert build("seller")["details"]["inert_reason"] == "seller_plan_not_customer_action"
    assert "inert_reason" not in build("customer")["details"]


def test_momentum_strong_needs_separate_interactions_and_no_open_blocker():
    one_note = [sig(k, "2026-06-20", source="n1") for k in ("verbal_commitment", "pilot_scope_agreed", "pricing_discussed")]
    assert state(one_note)["momentum"]["value"] == "steady"
    two_notes = one_note + [sig("data_received", "2026-06-25", source="n2")]
    assert state(two_notes)["momentum"]["value"] == "strong"
    blocked = two_notes + [sig("blocker_identified", "2026-06-26", source="n3")]
    assert state(blocked)["momentum"]["value"] == "steady"


def test_unknown_kind_price_cannot_gate_pilot_state():
    price = sig("pricing_discussed", "2026-06-20", kind_of_contract="unknown")
    assert state([price])["pilot_status"]["value"] == "unknown"
    assert state([sig("pricing_discussed", "2026-06-20", kind_of_contract="pilot")])["pilot_status"]["value"] == "discussed"
