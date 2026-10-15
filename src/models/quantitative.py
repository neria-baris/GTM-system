"""Deterministic weekly Models A, B, C over Stage A's evidence ledger."""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
from datetime import date, timedelta
import json
from typing import Any

from src.belief import engine as belief_engine, metrics as belief_metrics
from src.belief.ontology import VERSION as BELIEF_VERSION
from src.belief.signals import collect_signals
from src.ledger.store import Ledger, _known_by
from src.settings import fx_to_usd, goal_amount, goal_window

VERSION = "models_1.0.1"
GOAL = goal_amount()
FX = fx_to_usd()
SIGNALS = ("customer_commitment", "next_step_strength", "buyer_involvement",
           "procurement_legal", "blocker", "data_access", "technical_progress",
           "pilot_progress", "commercial_negotiation", "momentum")
BANDS = ("early", "pilot_committed", "pilot_started_evidenced", "commercial_process", "reported_signed_pending")
WEIGHTS = {"early": Decimal("0.25"), "pilot_committed": Decimal("0.5"),
           "pilot_started_evidenced": Decimal("0.5"), "commercial_process": Decimal("0.75")}
GOAL_START, GOAL_END = goal_window()


def _rows(ledger: Ledger, table: str) -> list[dict[str, Any]]:
    return [json.loads(row[0]) for row in ledger.db.execute(f"SELECT payload FROM {table}")]


def _available(ledger: Ledger, evidence_ids: list[str], mode: str, cutoff: str) -> bool:
    if mode == "retrospective_event_state":
        return bool(evidence_ids)
    return any((ev := ledger.evidence(eid)) and ev["documented_at"] and
               ev["source_first_seen_at"] and _known_by(ev["documented_at"], cutoff) and
               _known_by(ev["source_first_seen_at"], cutoff) for eid in evidence_ids)


def _money(value: dict[str, Any]) -> Decimal | None:
    rate = FX.get(value["currency_ISO"])
    if rate is None or value["unit"] not in {"per_year", "per_month"}:
        return None
    amount = Decimal(value["amount_decimal"])
    amount *= Decimal(12) if value["unit"] == "per_month" else Decimal(1)
    if value["term_months"] is not None and value["term_months"] < 12:
        amount *= Decimal(value["term_months"]) / Decimal(12)
    return amount * rate


def _actual(ledger: Ledger, week_end: str, mode: str, cutoff: str,
            events: list[dict[str, Any]], values: list[dict[str, Any]]) -> tuple[Decimal, int, int, list[dict[str, Any]]]:
    total = Decimal(0)
    contracts: set[str] = set()
    unknown = 0
    review: list[dict[str, Any]] = []
    for event in events:
        if event["event_type"] != "commercial_signed":
            continue
        cid = event["details"].get("commercial_contract_id")
        if not cid or cid in contracts:
            continue
        contract = ledger.entity(cid)
        if not contract or contract["contract_kind"] not in {"commercial", "amendment", "renewal"}:
            continue
        if event["verification"] != "document_verified" or contract["status"] != "verified_signed":
            review.append({"kind": "reported_commercial_signature", "opportunity_id": event["opportunity_id"],
                           "event_id": event["event_id"], "evidence_ids": event["evidence_ids"]})
            continue
        sig = contract["signature_date"]
        if (event["event_date"] != sig or contract["resolution_status"] != "resolved" or
                contract["scope_id"] != event["scope_id"] or not contract["document_ref"] or
                not contract["party_names"] or not contract["term_start"] or not contract["term_end"]):
            review.append({"kind": "contract_identity_scope_or_date_ambiguous", "contract_id": cid})
            continue
        if not sig or sig > min(week_end, GOAL_END) or sig < GOAL_START:
            if not sig:
                review.append({"kind": "signature_date_unknown", "contract_id": cid})
            continue
        contracts.add(cid)
        if contract["contract_kind"] == "renewal":
            # Only an explicit expansion increment can count.
            acceptable = {"expansion_increment_acv"}
        elif contract["contract_kind"] == "amendment":
            acceptable = {"expansion_increment_acv"}
        else:
            acceptable = {"rollout_acv"}
        matches = [v for v in values if v["offer_or_contract_id"] == cid and
                   v["value_type"] in acceptable and v["status"] == "signed_verified" and
                   v["verification"] == "document_verified" and
                   _available(ledger, v["source_evidence_ids"], mode, cutoff)]
        if len(matches) != 1:
            unknown += 1
            review.append({"kind": "signed_acv_ambiguous", "contract_id": cid})
            continue
        joint = set(event["evidence_ids"]) & set(matches[0]["source_evidence_ids"])
        if not any((ev := ledger.evidence(eid)) and ev["assertion_type"] == "document" and
                   ev["authorship"] != "ai_generated" for eid in joint):
            unknown += 1
            review.append({"kind": "contract_documentary_link_missing", "contract_id": cid})
            continue
        amount = _money(matches[0])
        if amount is None or matches[0]["scope_id"] != contract["scope_id"]:
            unknown += 1
            review.append({"kind": "signed_amount_period_currency_or_scope", "contract_id": cid})
            continue
        # A renewal with no expansion is a known zero contribution, never a new sale.
        total += amount
    return total, len(contracts), unknown, review


def _eligible_value(ledger: Ledger, opp: dict[str, Any], values: list[dict[str, Any]],
                    week_end: str, mode: str, cutoff: str) -> tuple[Decimal | None, str | None, str | None]:
    if opp["resolution_status"] != "resolved":
        return None, None, "ambiguous_scope_or_identity"
    candidates = [v for v in values if v["opportunity_id"] == opp["id"] and
                  v["value_type"] in {"rollout_acv", "expansion_increment_acv"} and
                  v["status"] in {"proposed", "tentative"} and v["date_observed"] and
                  v["date_observed"] <= week_end and
                  _available(ledger, v["source_evidence_ids"], mode, cutoff)]
    if not candidates:
        return None, None, "no_eligible_quote"
    proposals = [v for v in candidates if v["status"] == "proposed"]
    pool = proposals or candidates
    # A documented replacement removes its predecessor for the current view.
    replaced = {v["replaces_value_id"] for v in pool if v["replaces_value_id"]}
    pool = [v for v in pool if v["value_id"] not in replaced]
    if len(pool) != 1:
        return None, None, "conflicting_or_exclusive_values"
    amount = _money(pool[0])
    return amount, pool[0]["value_id"], None if amount is not None else "unsupported_currency_or_period"


def _model_d(signals: list[dict[str, Any]], state: dict[str, Any], week_end: str, mode: str,
             cutoff: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Model D: inferred belief states per opportunity. Reads Models A-C, never writes them."""
    belief_mode = "historically_known" if mode == "historically_known_state" else "retrospective"
    by_opp: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in signals:
        if s.get("opportunity_id") in state:
            by_opp[s["opportunity_id"]].append(s)
    beliefs, value_facts = {}, {}
    for oid, row in state.items():
        belief = beliefs[oid] = belief_engine.infer(by_opp[oid], week_end, mode=belief_mode, knowledge_cutoff=cutoff)
        row["model_d"] = {"states": belief_engine.compact(belief), "headline": belief_engine.headline(belief)["text"],
                          "inferred_stage": belief_metrics.inferred_stage(belief)}
        indicative = sum(1 for s in by_opp[oid] if s["signal_type"] == "pricing_discussed"
                         and ((s.get("details") or {}).get("indicative") or s.get("contract_kind") == "pilot")
                         and belief_engine.is_available(s, week_end, belief_mode, cutoff))
        value_facts[oid] = {"known_open_value_usd": row["model_c"]["eligible_value_usd"],
                            "indicative_value_count": indicative}
    return beliefs, value_facts


def weekly_state(ledger: Ledger, week_end: str, *, mode: str = "retrospective_event_state",
                 knowledge_cutoff: str | None = None,
                 atomic_signals: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """`atomic_signals` may carry precomputed belief-layer signals (collect_signals) to avoid recomputation."""
    if mode not in {"retrospective_event_state", "historically_known_state"}:
        raise ValueError("Invalid time mode")
    cutoff = knowledge_cutoff or week_end
    events = ledger.events_as_of(week_end, mode=mode, knowledge_cutoff=cutoff)
    values = _rows(ledger, "commercial_value")
    opps = {o["id"]: o for o in _rows(ledger, "entity") if "use_case_code" in o}
    accounts = {a["id"]: a for a in _rows(ledger, "entity") if "canonical_name" in a}
    claims = [c for c in _rows(ledger, "claim") if
              _available(ledger, c["evidence_ids"], mode, cutoff) and
              (not c["valid_from"] or c["valid_from"] <= week_end)]
    actual, contract_count, unknown_signed, review = _actual(ledger, week_end, mode, cutoff, events, values)
    by_opp: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event["opportunity_id"] in opps:
            by_opp[event["opportunity_id"]].append(event)
    state: dict[str, Any] = {}
    counts = Counter()
    industry_week = Counter()
    dollars = defaultdict(Decimal)
    open_counts = Counter()
    possible_signed = Decimal(0)
    possible_known = 0
    for oid, opp in opps.items():
        es = sorted(by_opp[oid], key=lambda e: (e["event_date"], e["event_id"]))
        kinds = {e["event_type"] for e in es}
        for e in es:
            counts[e["event_type"]] += 1
            industry = (accounts.get(opp["account_id"]) or {}).get("industry") or "unknown"
            event_day = date.fromisoformat(e["event_date"])
            week = event_day + timedelta(days=6 - event_day.weekday())
            industry_week[(week.isoformat(), industry, e["event_type"])] += 1
        signed = [e for e in es if e["event_type"] == "commercial_signed"]
        pending = any(e["verification"] != "document_verified" for e in signed)
        verified = any(e["verification"] == "document_verified" for e in signed)
        lost = "lost" in kinds and "revived" not in kinds
        stalled = "stalled" in kinds and "revived" not in kinds
        engagement = [e for e in es if e["event_type"] in {"initial_encounter", "follow_up_held", "scoping_held"}]
        verified_engagement = [e for e in engagement if e["verification"] in {"reviewed", "document_verified"}]
        buyer_actions = [e for e in es if e["event_type"] in {"initial_encounter", "follow_up_held",
                         "scoping_held", "data_received", "pilot_verbal_yes", "pilot_signed",
                         "pilot_started", "commercial_signed", "revived"}]
        last_buyer_action = buyer_actions[-1]["event_date"] if buyer_actions else None
        if pending:
            band = "reported_signed_pending"
        elif "commercial_proposal_sent" in kinds or "procurement_legal_started" in kinds:
            band = "commercial_process"
        elif "pilot_started" in kinds:
            band = "pilot_started_evidenced"
        elif "pilot_signed" in kinds or "pilot_verbal_yes" in kinds:
            band = "pilot_committed"
        else:
            band = "early"
        signal_claims: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for c in claims:
            if (c["subject_id"] == oid and c["predicate"].startswith("signal:") and
                    c["status"] in {"observed", "contradicted"}):
                signal_claims[c["predicate"][7:]].append(c)
        signals = {}
        signal_evidence = {}
        for name in SIGNALS:
            active = [c for c in signal_claims[name] if not c["valid_to"] or c["valid_to"] >= week_end]
            distinct = {c["object_value"] for c in active}
            signals[name] = "contradicted" if len(distinct) > 1 or any(c["status"] == "contradicted" for c in active) else \
                next(iter(distinct)) if distinct else "unknown"
            signal_evidence[name] = [{"claim_id": c["claim_id"], "evidence_ids": c["evidence_ids"],
                                      "extraction_route": c["resolution_reason"]} for c in active]
        if stalled:
            signals["momentum"] = "stalled_explicit"
            signal_evidence["momentum"] = [{"event_id": e["event_id"], "evidence_ids": e["evidence_ids"],
                                             "extraction_route": e["extraction_version"]} for e in es if e["event_type"] == "stalled"]
        stalled_by_rule = bool(last_buyer_action and
                               (date.fromisoformat(week_end) - date.fromisoformat(last_buyer_action)).days >= 45 and
                               not lost and not signed and signals["next_step_strength"] not in {"owner_and_date"})
        if stalled_by_rule and not stalled:
            signals["momentum"] = "stalled_by_rule"
            signal_evidence["momentum"] = [{"rule": "45_days_since_documented_buyer_action",
                                             "last_buyer_action_event_id": buyer_actions[-1]["event_id"],
                                             "evidence_ids": buyer_actions[-1]["evidence_ids"]}]
        if "pilot_signed" in kinds:
            signals["pilot_progress"] = "signed_reported"
            signal_evidence["pilot_progress"] = [{"event_id": e["event_id"], "evidence_ids": e["evidence_ids"],
                                                   "extraction_route": e["extraction_version"]} for e in es if e["event_type"] == "pilot_signed"]
        elif "pilot_verbal_yes" in kinds:
            signals["pilot_progress"] = "verbal_yes"
            signal_evidence["pilot_progress"] = [{"event_id": e["event_id"], "evidence_ids": e["evidence_ids"],
                                                   "extraction_route": e["extraction_version"]} for e in es if e["event_type"] == "pilot_verbal_yes"]
        if pending:
            signals["commercial_negotiation"] = "reported_signed"
            signal_evidence["commercial_negotiation"] = [{"event_id": e["event_id"], "evidence_ids": e["evidence_ids"],
                                                           "extraction_route": e["extraction_version"]} for e in signed]
        elif verified:
            signals["commercial_negotiation"] = "verified_signed"
            signal_evidence["commercial_negotiation"] = [{"event_id": e["event_id"], "evidence_ids": e["evidence_ids"],
                                                           "extraction_route": e["extraction_version"]} for e in signed]
        if "technical_milestone" in kinds:
            technical = next(e for e in reversed(es) if e["event_type"] == "technical_milestone")
            signals["technical_progress"] = "shadow_result_positive" if technical["details"].get("result") == "passed" else "unknown"
            signal_evidence["technical_progress"] = [{"event_id": technical["event_id"],
                                                       "evidence_ids": technical["evidence_ids"],
                                                       "extraction_route": technical["extraction_version"]}]
        related = [c for c in claims if c["subject_id"] == oid]
        commercial_unsigned = any(c["predicate"] == "commercial_contract_signed" and c["polarity"] == "negative" for c in related)
        if commercial_unsigned and not signed:
            signals["commercial_negotiation"] = "not_signed_reported"
            signal_evidence["commercial_negotiation"] = [{"claim_id": c["claim_id"],
                                                           "evidence_ids": c["evidence_ids"],
                                                           "extraction_route": c["resolution_reason"]}
                                                          for c in related if c["predicate"] == "commercial_contract_signed" and c["polarity"] == "negative"]
        if any(c["predicate"] == "crm_current_stage" and c["object_value"] == "Commercial deployment" for c in related) and commercial_unsigned:
            review.append({"kind": "crm_stage_exception", "opportunity_id": oid})
        if opp["resolution_status"] == "ambiguous":
            review.append({"kind": "material_identity_or_scope", "opportunity_id": oid})
        eligible, value_id, reason = _eligible_value(ledger, opp, values, week_end, mode, cutoff)
        if reason in {"conflicting_or_exclusive_values", "ambiguous_scope_or_identity"}:
            review.append({"kind": reason, "opportunity_id": oid})
        if pending:
            matches = [v for v in values if v["opportunity_id"] == oid and v["status"] == "signed_reported" and
                       v["value_type"] in {"rollout_acv", "expansion_increment_acv"} and
                       _available(ledger, v["source_evidence_ids"], mode, cutoff)]
            if len(matches) == 1 and (m := _money(matches[0])) is not None:
                possible_signed += m
                possible_known += 1
        origin = ledger.evidence(opp["origin_evidence_id"])
        origin_visible = bool(origin and origin["business_event_date"] and
                              origin["business_event_date"] <= week_end and
                              _available(ledger, [opp["origin_evidence_id"]], mode, cutoff))
        visible = bool(es or origin_visible or any(c["subject_id"] == oid and c["valid_from"] for c in related))
        is_open = visible and not (lost or pending or verified)
        if is_open:
            open_counts[band] += 1
            if eligible is not None:
                dollars[band] += eligible
        state[oid] = {
            "model_a": {"event_types": [e["event_type"] for e in es],
                        "event_ids": [e["event_id"] for e in es],
                        "last_verified_engagement_event": verified_engagement[-1]["event_type"] if verified_engagement else None,
                        "engagement_state": engagement[-1]["event_type"] if engagement else "unknown",
                        "last_buyer_action_date": last_buyer_action,
                        "last_event_date": es[-1]["event_date"] if es else None,
                        "pilot_state": "signed_reported" if "pilot_signed" in kinds else "verbal_yes" if "pilot_verbal_yes" in kinds else "unknown",
                        "technical_state": signals["technical_progress"],
                        "commercial_state": "verified_signed" if verified else "reported_signed_pending" if pending else "not_signed_reported" if commercial_unsigned else "unknown",
                        "lifecycle": "lost" if lost else "stalled" if stalled or stalled_by_rule else "signed" if verified else "open",
                        "evidence_status": "available" if es else "unknown"},
            "model_b": {"phase": band, "readiness_band": band, "signals": signals,
                        "signal_evidence": signal_evidence,
                        "unknown_signal_count": sum(x == "unknown" for x in signals.values()),
                        "conflict_count": sum(c["status"] == "contradicted" for c in related),
                        "blocker_state": signals["blocker"], "next_step_strength": signals["next_step_strength"],
                        "data_access": signals["data_access"], "buyer_involvement": signals["buyer_involvement"],
                        "technical_progress": signals["technical_progress"], "stalled_overlay": stalled or stalled_by_rule,
                        "stalled_by_rule": stalled_by_rule},
            "model_c": {"open": is_open, "eligible_value_usd": str(eligible) if is_open and eligible is not None else None,
                        "value_id": value_id if is_open else None, "abstain_reason": reason},
        }
    # Only explicitly exclusive scopes compete. A shared opportunity group can
    # also contain a separately purchasable expansion, so it is not enough.
    group_members: dict[str, list[str]] = defaultdict(list)
    scopes = [s for s in _rows(ledger, "entity") if "exclusivity_group_id" in s]
    for oid, opp in opps.items():
        matched = [s for s in scopes if s["scope_id"] == opp["commercial_scope_id"] and
                   s["version"] == opp["scope_version"]]
        group = matched[0]["exclusivity_group_id"] if matched else None
        if group and state[oid]["model_c"]["open"]:
            group_members[group].append(oid)
    for members in group_members.values():
        if len(members) > 1:
            proposed = [oid for oid in members if
                        state[oid]["model_c"]["eligible_value_usd"] is not None and
                        "commercial_proposal_sent" in state[oid]["model_a"]["event_types"]]
            base = [oid for oid in members if
                    state[oid]["model_c"]["eligible_value_usd"] is not None and
                    opps[oid]["relationship"] == "base"]
            chosen = proposed[0] if len(proposed) == 1 else base[0] if not proposed and len(base) == 1 else None
            for oid in members:
                if oid == chosen:
                    continue
                band = state[oid]["model_b"]["readiness_band"]
                amount = state[oid]["model_c"]["eligible_value_usd"]
                if amount is not None:
                    dollars[band] -= Decimal(amount)
                state[oid]["model_c"].update(eligible_value_usd=None,
                                              abstain_reason="exclusive_alternative_not_selected" if chosen else "exclusivity_group_ambiguous")
            if chosen is None:
                review.append({"kind": "exclusivity_group_ambiguous", "opportunity_ids": members})
    eligible_amounts = [Decimal(s["model_c"]["eligible_value_usd"]) for s in state.values()
                        if s["model_c"]["open"] and s["model_c"]["eligible_value_usd"] is not None]
    n_open = sum(s["model_c"]["open"] for s in state.values())
    total_open = sum(eligible_amounts, Decimal(0))
    weighted = sum((dollars[b] * WEIGHTS[b] for b in WEIGHTS), Decimal(0))
    sensitivity_low = sum((dollars[b] * max(Decimal(0), WEIGHTS[b] - Decimal("0.25")) for b in WEIGHTS), Decimal(0))
    sensitivity_high = sum((dollars[b] * min(Decimal(1), WEIGHTS[b] + Decimal("0.25")) for b in WEIGHTS), Decimal(0))
    possible_signed_usd = str(possible_signed) if possible_known else None
    beliefs, value_facts = _model_d(collect_signals(ledger) if atomic_signals is None else atomic_signals,
                                    state, week_end, mode, cutoff)
    portfolio = belief_metrics.portfolio(beliefs, value_facts, verified_actual_usd=str(actual),
                                         reported_unverified_usd=possible_signed_usd)
    portfolio.pop("flags")
    return {"week_end": week_end, "knowledge_cutoff": cutoff, "mode": "retrospective" if mode.startswith("retrospective") else "historically_known",
            "goal_usd": str(GOAL), "verified_actual_usd": str(actual), "verified_contract_count": contract_count,
            "reported_signed_pending_count": sum(s["model_b"]["readiness_band"] == "reported_signed_pending" for s in state.values()),
            "reported_signed_possible_acv_usd": possible_signed_usd,
            "unknown_signed_amount_count": unknown_signed, "remaining_usd": str(max(Decimal(0), GOAL - actual)),
            "model_a_counts_by_event": dict(counts),
            "model_a_counts_by_industry_week": [{"date": date, "industry": industry, "event_type": kind, "count": count}
                                                for (date, industry, kind), count in sorted(industry_week.items())],
            "pipeline_counts_by_band": dict(open_counts),
            "pipeline_quoted_value_by_band_usd": {b: str(dollars[b]) for b in WEIGHTS},
            "progression_weighted_proxy_usd": str(weighted),
            "progression_weighted_sensitivity_usd": [str(sensitivity_low), str(sensitivity_high)],
            "value_coverage": {"open_opportunities": n_open, "with_eligible_value": len(eligible_amounts),
                               "fraction": len(eligible_amounts) / n_open if n_open else None,
                               "unknown_value_count": n_open - len(eligible_amounts),
                               "largest_opportunity_share": str(max(eligible_amounts) / total_open) if total_open else None,
                               "label": "known-value subset"},
            "identity_unresolved_count": sum(o["resolution_status"] != "resolved" for o in opps.values()),
            "claim_conflict_count": len(_rows(ledger, "conflict")), "review_queue": review,
            "top_exception_ids": [r.get("event_id") or r.get("opportunity_id") or r.get("contract_id") for r in review],
            "opportunities": state, "belief_metrics": portfolio,
            "model_versions": {"A": VERSION, "B": VERSION, "C": VERSION, "D": BELIEF_VERSION},
            "fx_policy_id": "planning_2026_audit"}


def retrospective_event_state(ledger: Ledger, week_end: str) -> dict[str, Any]:
    return weekly_state(ledger, week_end, mode="retrospective_event_state")


def historically_known_state(ledger: Ledger, week_end: str, knowledge_cutoff: str | None = None) -> dict[str, Any]:
    return weekly_state(ledger, week_end, mode="historically_known_state", knowledge_cutoff=knowledge_cutoff)
