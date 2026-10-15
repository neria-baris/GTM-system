"""Deterministic presentation_v1 materialization from Stage C canonical state.

This module reads the canonical ledger and Stage C quantitative output. It never
interprets source records or extractor proposals as business events.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from src.belief import presentation as belief_presentation
from src.belief.ontology import VERSION as BELIEF_VERSION
from src.belief.signals import collect_signals
from src import settings
from src.ledger.store import Ledger
from src.models.quantitative import GOAL_END, GOAL_START, VERSION as MODEL_VERSION, weekly_state

VERSION = "presentation_v1"
JOURNEY = ("encounter", "follow_up", "scoping", "pilot_path", "pilot_signed",
           "pilot_execution", "technical_milestone", "commercial_negotiation",
           "procurement_legal", "commercial_signed")
EVENT_TO_JOURNEY = {
    "initial_encounter": "encounter", "follow_up_held": "follow_up",
    "scoping_held": "scoping", "pilot_verbal_yes": "pilot_path",
    "sow_drafting": "pilot_path", "sow_sent": "pilot_path",
    "pilot_signed": "pilot_signed", "pilot_started": "pilot_execution",
    "technical_milestone": "technical_milestone",
    "commercial_proposal_sent": "commercial_negotiation",
    "procurement_legal_started": "procurement_legal",
    "commercial_signed": "commercial_signed",
}
FILES = ("overview", "opportunities", "opportunity_details", "weekly_snapshots",
         "evidence_summaries", "review_queue", "belief_states")
BELIEF_PROVENANCE = {"source": "canonical ledger atomic signals + canonical events/values/claims; source notes "
                               "linked by context (reconstruction) and valued with stated reasons",
                     "engine_version": BELIEF_VERSION,
                     "sensors": "Luna atomic signals, Jev sensor readings, deterministic rules"}


def _rows(ledger: Ledger, table: str) -> list[dict[str, Any]]:
    return [json.loads(row[0]) for row in ledger.db.execute(f"SELECT payload FROM {table} ORDER BY 1")]


def _usd(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _sum(values: list[Any]) -> str:
    return str(sum((_usd(v) for v in values if v is not None), Decimal(0)))


def _week_end(day: str) -> str:
    d = date.fromisoformat(day[:10])
    return (d + timedelta(days=6 - d.weekday())).isoformat()


def _safe_excerpt(e: dict[str, Any]) -> str:
    excerpt = e.get("verbatim_excerpt") or ""
    # C stores the JSON-encoded exact source span. Fixtures store plain text.
    if (e.get("derivation_rule") or "").startswith("c_full_corpus_"):
        return json.loads('"' + excerpt + '"')
    return excerpt


def _evidence_summary(e: dict[str, Any]) -> dict[str, Any]:
    ref = e.get("source_ref") or {}
    return {
        "evidence_id": e["evidence_id"], "source_system": ref.get("system", "unknown"),
        "source_type": ref.get("object_type", "unknown"),
        "reference": e.get("source_url") or ref.get("native_id") or e["evidence_id"],
        "title": None, "business_date": e.get("business_event_date"),
        "documented_at": e.get("documented_at"),
        "source_first_seen_at": e.get("source_first_seen_at"),
        "exact_excerpt": _safe_excerpt(e),
        "claim_status": "source_scoped" if (e.get("derivation_rule") or "").startswith("c_full_corpus_") else "canonical_evidence",
        "verification_status": "unverified", "source_version": e.get("source_version"),
    }


def _source_group(e: dict[str, Any]) -> str:
    """One source note or record: the native id of the evidence's source."""
    return (e.get("source_ref") or {}).get("native_id") or e["evidence_id"]


def _signal_group(signal: dict[str, Any], groups: dict[str, Any], group_of: dict[str, str]) -> str | None:
    """Source group of a source-scoped signal.

    Semantic integration writes `source:<provider>:<native_id>`; `source:<system>:<object_type>:<native_id>`
    and `source:<native_id>` are accepted too. Otherwise the signal's evidence must sit in one source.
    """
    ref = signal.get("subject_ref") or ""
    if ref.startswith("source:"):
        parts = ref.split(":")
        for start in (2, 3, 1):
            candidate = ":".join(parts[start:])
            if candidate in groups:
                return candidate
    own = {group_of.get(eid) for eid in signal.get("evidence_ids") or []}
    return next(iter(own)) if len(own) == 1 and None not in own else None


def _belief_context(ledger: Ledger, evidence: dict[str, dict[str, Any]], signals: list[dict[str, Any]],
                    opportunity_ids: list[str], events: list[dict[str, Any]],
                    values: list[dict[str, Any]]) -> dict[str, Any]:
    """Sources, source-scoped signals and seed groups for contextual reconstruction and valuation."""
    group_of = {eid: _source_group(e) for eid, e in evidence.items()}
    sources: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for eid in sorted(evidence):
        e = evidence[eid]
        sources[group_of[eid]].append({"evidence_id": eid, "text": _safe_excerpt(e),
                                       "date": (e.get("business_event_date") or "")[:10] or None})
    source_signals: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in signals:
        if s.get("opportunity_id"):
            continue
        group = _signal_group(s, sources, group_of)
        if group is not None:
            source_signals[group].append(s)
    # Explicit cues ("SIGNED. EUR580k/yr", "Lost - ...") are mechanical: the deterministic language sensor
    # complements the model's recall. Same type in the same note counts once in the engine.
    from src.belief.signals import availability, lexical_signals, make_signal
    for group, items in sources.items():
        for item in items:
            for n, r in enumerate(lexical_signals(item["text"])):
                source_signals[group].append(make_signal(
                    r["signal_type"], evidence_ids=[item["evidence_id"]], method="deterministic_rule",
                    id_seed=f"lexical:{item['evidence_id']}:{n}:{r['signal_type']}", effective_date=item["date"],
                    modality=r["modality"], observation=r["observation"], confidence=r["confidence"],
                    contract_kind=r["contract_kind"], subject_ref=f"source:{group}",
                    evidence_availability=availability(ledger, [item["evidence_id"]]),
                    details={**(r.get("details") or {}), "clause": r["clause"], "sensor": "deterministic_language"}))
    claims = _rows(ledger, "claim")
    seed_groups: dict[str, set[str]] = {}
    for oid in opportunity_ids:
        ids = {(ledger.entity(oid) or {}).get("origin_evidence_id")}
        ids |= {eid for e in events if e.get("opportunity_id") == oid for eid in e.get("evidence_ids") or []}
        ids |= {eid for v in values if v.get("opportunity_id") == oid for eid in v.get("source_evidence_ids") or []}
        ids |= {eid for c in claims if c.get("subject_id") == oid for eid in c.get("evidence_ids") or []}
        ids |= {eid for s in signals if s.get("opportunity_id") == oid for eid in s.get("evidence_ids") or []}
        seed_groups[oid] = {group_of[eid] for eid in ids if eid in group_of}
    return {"sources": dict(sources), "source_signals": dict(source_signals), "seed_groups": seed_groups,
            "group_accounts": _group_accounts(ledger, set(sources))}


def _group_accounts(ledger: Ledger, groups: set[str]) -> dict[str, str]:
    """Source group -> account name: note titles resolved against CRM companies/contacts, and CRM links."""
    from src.belief.reconstruction import resolve_accounts
    entities = _rows(ledger, "entity")
    accounts = {x["id"]: x["canonical_name"] for x in entities if "canonical_name" in x and x.get("canonical_name")}
    record_account = {ref["native_id"]: x["id"] for x in entities if "canonical_name" in x
                      for ref in x.get("source_refs") or []}
    contacts: dict[str, list[str]] = {}
    for x in entities:
        if "display_name" in x and x.get("display_name"):
            contacts.setdefault(x["display_name"], []).extend(a["account_id"] for a in x.get("account_affiliations") or [])
    titles, out = {}, {}
    for system, object_type, native_id, content in ledger.db.execute(
            "SELECT system, object_type, native_id, content FROM raw_source"):
        if native_id not in groups:
            continue
        try:
            body = json.loads(content)
        except ValueError:
            continue
        if system == "notion" and object_type == "page":
            props = (body.get("page") or {}).get("properties") or {}
            titles[native_id] = "".join(t.get("plain_text", "") for p in props.values() if p.get("type") == "title"
                                        for t in p.get("title") or [])
        elif system == "airtable":
            if native_id in record_account:
                out[native_id] = accounts.get(record_account[native_id])
                continue
            linked = {record_account[v] for f in ((body.get("record") or {}).get("fields") or {}).values()
                      for v in (f if isinstance(f, list) else []) if isinstance(v, str) and v in record_account}
            if len(linked) == 1:
                out[native_id] = accounts.get(next(iter(linked)))
    for group, aid in resolve_accounts(titles, accounts, contacts).items():
        out[group] = accounts[aid]
    return {g: a for g, a in out.items() if a}


def _review_items(stage_c: dict[str, Any] | None, quantitative: dict[str, Any],
                  evidence: dict[str, dict[str, Any]], ledger: Ledger) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    dispositions = {r["candidate_id"]: r for r in (stage_c or {}).get("candidate_dispositions", [])}
    for item in (stage_c or {}).get("review_items", []):
        ids = sorted(set(item.get("evidence_ids") or []) |
                     {dispositions[c]["evidence_id"] for c in item.get("candidate_ids", []) if c in dispositions})
        if not ids or any(eid not in evidence for eid in ids):
            raise ValueError("Stage C review item has unresolved evidence")
        out.append({"review_id": item["review_id"], "opportunity_id": item.get("opportunity_id"),
                    "issue": item.get("reason") or "review_required",
                    "reason": item.get("reason") or "review_required",
                    "evidence_ids": ids, "financial_materiality_usd": None,
                    "required_action": item.get("single_decision_needed") or "Review source evidence",
                    "status": "open"})
    for i, item in enumerate(quantitative.get("review_queue", [])):
        ids = set(item.get("evidence_ids", []))
        oid = item.get("opportunity_id")
        if oid and not ids:
            opp = ledger.entity(oid)
            if opp and opp.get("origin_evidence_id"):
                ids.add(opp["origin_evidence_id"])
            for claim in _rows(ledger, "claim"):
                if claim["subject_id"] == oid:
                    ids.update(claim["evidence_ids"])
        if item.get("contract_id") and not ids:
            for event in _rows(ledger, "event"):
                if event["details"].get("commercial_contract_id") == item["contract_id"]:
                    ids.update(event["evidence_ids"])
        ids = sorted(ids)
        if any(eid not in evidence for eid in ids):
            raise ValueError("Quantitative review item has unresolved evidence")
        out.append({"review_id": f"canonical:{i}:{item['kind']}",
                    "opportunity_id": item.get("opportunity_id"), "issue": item["kind"],
                    "reason": item["kind"], "evidence_ids": ids,
                    "financial_materiality_usd": None,
                    "required_action": "Resolve canonical evidence or contract gate", "status": "open"})
    return out


def movement(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Supported weekly changes. Comparing an object with itself is an empty diff."""
    kinds: list[dict[str, Any]] = []
    old = previous.get("opportunities", {})
    new = current.get("opportunities", {})
    for oid in sorted(set(old) | set(new)):
        a, b = old.get(oid), new.get(oid)
        if a is None:
            kinds.append({"opportunity_id": oid, "kind": "new_opportunity"})
            continue
        if b is None:
            kinds.append({"opportunity_id": oid, "kind": "restatement"})
            continue
        for field, kind in (("furthest_evidenced_journey_milestone", "journey_advance"),
                            ("known_open_commercial_value_usd", "value_revision"),
                            ("readiness_band", "band_change"),
                            ("blocker_state", "blocker_change"),
                            ("momentum", "momentum_change"),
                            ("lifecycle", "lifecycle_change"),
                            ("reported_signed_pending_verification_usd", "reported_signed"),
                            ("verified_actual_usd", "verified_actual")):
            if a.get(field) != b.get(field):
                kinds.append({"opportunity_id": oid, "kind": kind,
                              "from": a.get(field), "to": b.get(field)})
        if (a.get("account_id"), a.get("commercial_scope_id")) != (
                b.get("account_id"), b.get("commercial_scope_id")):
            kinds.append({"opportunity_id": oid, "kind": "identity_correction"})
        event_types = {e["event_id"]: e["event_type"] for e in b.get("event_timeline", [])}
        for eid in sorted(set(b.get("event_ids", [])) - set(a.get("event_ids", []))):
            kinds.append({"opportunity_id": oid, "kind": "new_event", "event_id": eid})
            if event_types.get(eid) in {"blocker_opened", "blocker_resolved", "lost", "stalled",
                                        "revived", "commercial_signed"}:
                kinds.append({"opportunity_id": oid, "kind": event_types[eid], "event_id": eid})
    return {"changes": kinds, "count": len(kinds)}


def _integrated(ledger: Ledger, q: dict[str, Any], week: str,
                events: list[dict[str, Any]], values: list[dict[str, Any]],
                reviews: list[dict[str, Any]], evidence: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    entities = _rows(ledger, "entity")
    accounts = {x["id"]: x for x in entities if "canonical_name" in x}
    scopes = {(x["scope_id"], x["version"]): x for x in entities if "exclusivity_group_id" in x}
    opportunities = {x["id"]: x for x in entities if "use_case_code" in x}
    claims = {x["claim_id"]: x for x in _rows(ledger, "claim")}
    conflicts = _rows(ledger, "conflict")
    event_by_id = {e["event_id"]: e for e in events}
    by_opp_values: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for v in values:
        if v.get("date_observed") and v["date_observed"] <= week:
            by_opp_values[v["opportunity_id"]].append(v)
    result: dict[str, dict[str, Any]] = {}
    for oid, model in sorted(q["opportunities"].items()):
        opp = opportunities[oid]
        account = accounts.get(opp["account_id"], {})
        scope = scopes.get((opp["commercial_scope_id"], opp["scope_version"]), {})
        es = [event_by_id[eid] for eid in model["model_a"]["event_ids"]]
        origin = evidence.get(opp["origin_evidence_id"])
        if not es and not (origin and origin.get("business_event_date") and
                           origin["business_event_date"] <= week):
            continue
        observed = sorted({EVENT_TO_JOURNEY[e["event_type"]] for e in es
                           if e["event_type"] in EVENT_TO_JOURNEY}, key=JOURNEY.index)
        furthest = observed[-1] if observed else None
        missing = [x for x in JOURNEY[:JOURNEY.index(furthest)] if x not in observed] if furthest else []
        signed = [e for e in es if e["event_type"] == "commercial_signed"]
        pending = any(e["verification"] != "document_verified" for e in signed)
        # C determines the eligible open value and which alternatives count.
        c = model["model_c"]
        eligible = c["eligible_value_usd"]
        value_id = c["value_id"]
        pending_values = [v for v in by_opp_values[oid] if v["status"] == "signed_reported" and
                          v["value_type"] in {"rollout_acv", "expansion_increment_acv"}]
        pending_usd = None
        if pending and len(pending_values) == 1:
            from src.models.quantitative import _money
            amount = _money(pending_values[0])
            pending_usd = str(amount) if amount is not None else None
        from src.models.quantitative import _actual, _money
        actual_amount, _, _, _ = _actual(ledger, week, "retrospective_event_state", week,
                                         es, by_opp_values[oid])
        actual = str(actual_amount)
        linked_reviews = [r["review_id"] for r in reviews if r["opportunity_id"] == oid]
        related_conflicts = []
        for conflict in conflicts:
            related = [claims[cid] for cid in conflict["claim_ids"] if cid in claims]
            if any(c["subject_id"] == oid for c in related):
                related_conflicts.append({"conflict_id": conflict["conflict_id"],
                    "issue": conflict["issue"], "severity": conflict["severity"],
                    "resolution": conflict["resolution"],
                    "evidence_ids": sorted({eid for c in related for eid in c["evidence_ids"]})})
        conflicting_ids = sorted({eid for c in related_conflicts for eid in c["evidence_ids"]})
        signal_ids = {eid for entries in model["model_b"].get("signal_evidence", {}).values()
                      for entry in entries for eid in entry.get("evidence_ids", [])}
        evidence_ids = sorted({eid for e in es for eid in e["evidence_ids"]} |
                              {eid for v in by_opp_values[oid] for eid in v["source_evidence_ids"]} |
                              signal_ids |
                              ({opp["origin_evidence_id"]} if opp["origin_evidence_id"] else set()))
        if any(eid not in evidence for eid in evidence_ids + conflicting_ids):
            raise ValueError("Unresolved canonical evidence")
        event_timeline = [{"event_id": e["event_id"], "event_type": e["event_type"],
                           "event_date": e["event_date"], "evidence_ids": e["evidence_ids"],
                           "verification": e["verification"]} for e in es]
        signals = model["model_b"]["signals"]
        result[oid] = {
            "opportunity_id": oid, "account_id": opp["account_id"],
            "account_label": account.get("canonical_name") or "Unknown account",
            "use_case_code": opp["use_case_code"],
            "use_case_label": opp["use_case_description"] or opp["use_case_code"],
            "commercial_scope_id": opp["commercial_scope_id"],
            "scope_version": opp["scope_version"],
            "scope_label": scope.get("boundary_text") or opp["commercial_scope_id"],
            "exclusivity_group_id": scope.get("exclusivity_group_id"),
            "relationship": opp["relationship"], "resolution_status": opp["resolution_status"],
            "observed_milestones": observed,
            "furthest_evidenced_journey_milestone": furthest,
            "missing_prior_milestones": missing,
            "pilot_state": model["model_a"]["pilot_state"],
            "technical_state": model["model_a"]["technical_state"],
            "commercial_state": model["model_a"]["commercial_state"],
            "lifecycle": model["model_a"]["lifecycle"],
            "momentum": signals["momentum"], "buyer_state": signals["buyer_involvement"],
            "procurement_legal_state": signals["procurement_legal"],
            "data_access_state": signals["data_access"],
            "next_step_state": signals["next_step_strength"],
            "blocker_state": signals["blocker"],
            "readiness_band": model["model_b"]["readiness_band"],
            "last_meaningful_event": event_timeline[-1] if event_timeline else None,
            "known_open_commercial_value_usd": eligible,
            "value_status": "known_eligible" if eligible is not None else
                            (c["abstain_reason"] or "unknown"),
            "selected_value_id": value_id,
            "reported_signed_pending_verification_usd": pending_usd,
            "verified_actual_usd": actual,
            "evidence_status": model["model_a"]["evidence_status"],
            "review_status": "open" if linked_reviews else "none",
            "review_ids": linked_reviews, "supporting_evidence_ids": evidence_ids,
            "conflicting_evidence_ids": conflicting_ids, "event_ids": [e["event_id"] for e in es],
            "event_timeline": event_timeline,
            "commercial_values": [{"value_id": v["value_id"], "value_type": v["value_type"],
                                    "status": v["status"], "usd_normalized":
                                    str(_money(v)) if _money(v) is not None else None,
                                    "evidence_ids": v["source_evidence_ids"],
                                    "scenario_group_id": v.get("scenario_group_id"),
                                    "selected_for_open_value": v["value_id"] == value_id}
                                   for v in by_opp_values[oid]],
            "conflicts": related_conflicts,
        }
    return result


def materialize(ledger: Ledger, *, business_as_of: str | None = None,
                stage_c: dict[str, Any] | None = None,
                knowledge_cutoff: str | None = None) -> dict[str, Any]:
    """Return the complete versioned read model from a Stage C ledger."""
    business_as_of = business_as_of or settings.business_as_of()
    cutoff = knowledge_cutoff or business_as_of
    signals = collect_signals(ledger)
    q = weekly_state(ledger, business_as_of, atomic_signals=signals)
    events = _rows(ledger, "event")
    values = _rows(ledger, "commercial_value")
    evidence = {e["evidence_id"]: e for e in _rows(ledger, "evidence")}
    reviews = _review_items(stage_c, q, evidence, ledger)
    integrated = _integrated(ledger, q, business_as_of, events, values, reviews, evidence)
    canonical_opps = {o["id"]: o for o in _rows(ledger, "entity") if "use_case_code" in o}
    excluded = []
    expected = set()
    for oid, opp in canonical_opps.items():
        origin = evidence.get(opp["origin_evidence_id"])
        dated = [e["event_date"] for e in events if e["opportunity_id"] == oid and e.get("event_date")]
        if origin and origin.get("business_event_date"):
            dated.append(origin["business_event_date"])
        if any(day <= business_as_of for day in dated):
            expected.add(oid)
        else:
            excluded.append({"opportunity_id": oid, "reason": "business_date_unknown" if not dated else "after_business_as_of"})
    if set(integrated) != expected or (canonical_opps and not integrated):
        raise ValueError("Canonical/D opportunity population reconciliation failed")
    for review in reviews:
        if review["opportunity_id"] not in integrated:
            review["opportunity_id"] = None
    if _sum([x["verified_actual_usd"] for x in integrated.values()]) != q["verified_actual_usd"]:
        raise ValueError("Opportunity Actual does not reconcile with Stage C")
    journey_distribution = dict(Counter(x["furthest_evidenced_journey_milestone"] or "unknown"
                                        for x in integrated.values()))
    open_values = [x["known_open_commercial_value_usd"] for x in integrated.values()
                   if x["known_open_commercial_value_usd"] is not None]
    overview = {
        "target": {"amount_usd": q["goal_usd"], "start": GOAL_START, "deadline": GOAL_END},
        "verified_signed_acv_usd": q["verified_actual_usd"],
        "reported_signed_pending_verification_usd": q["reported_signed_possible_acv_usd"],
        "reported_signed_pending_unknown_amount_count": q["reported_signed_pending_count"] -
            sum(x["commercial_state"] == "reported_signed_pending" and
                x["reported_signed_pending_verification_usd"] is not None for x in integrated.values()),
        "known_value_open_commercial_pipeline_usd": _sum(open_values),
        "value_coverage": q["value_coverage"], "journey_distribution": journey_distribution,
        "counts": {"opportunities": len(integrated),
                   "signed_pilot": sum(x["pilot_state"] in {"signed_reported", "signed_verified"} for x in integrated.values()),
                   "reported_signature": q["reported_signed_pending_count"],
                   "verified_signature": q["verified_contract_count"],
                   "stalled": sum(x["lifecycle"] == "stalled" for x in integrated.values()),
                   "lost": sum(x["lifecycle"] == "lost" for x in integrated.values()),
                   "review": len(reviews)},
        "latest_weekly_movement": {"changes": [], "count": 0},
        "heuristic_proxy": {"label": "Model C progression sensitivity proxy; not a forecast or expected ACV",
                             "amount_usd": q["progression_weighted_proxy_usd"],
                             "sensitivity_usd": q["progression_weighted_sensitivity_usd"]},
    }
    summary_rows = [{k: x[k] for k in (
        "opportunity_id", "account_id", "account_label", "use_case_label", "commercial_scope_id",
        "scope_label", "furthest_evidenced_journey_milestone", "pilot_state", "technical_state",
        "commercial_state", "lifecycle", "momentum", "buyer_state", "procurement_legal_state",
        "data_access_state", "next_step_state", "blocker_state", "readiness_band",
        "known_open_commercial_value_usd", "value_status", "reported_signed_pending_verification_usd",
        "verified_actual_usd", "last_meaningful_event", "evidence_status", "review_status")}
                    | {"main_issue": next((r["issue"] for r in reviews if r["opportunity_id"] == x["opportunity_id"]), None),
                       "review_flag": x["review_status"] == "open"} for x in integrated.values()]
    event_days = [e["event_date"] for e in events if e.get("event_date") and e["event_date"] <= business_as_of]
    first = _week_end(min(event_days)) if event_days else business_as_of
    end = date.fromisoformat(business_as_of)
    cursor = date.fromisoformat(first)
    weeks = []
    while cursor < end:
        weeks.append(cursor.isoformat())
        cursor += timedelta(days=7)
    if business_as_of not in weeks:
        weeks.append(business_as_of)
    snapshots = []
    prior = None
    for week in weeks:
        week_cutoff = cutoff if week == business_as_of else week
        current_q = q if week == business_as_of else weekly_state(ledger, week, atomic_signals=signals)
        current_reviews = _review_items(stage_c, current_q, evidence, ledger)
        current = integrated if week == business_as_of else _integrated(
            ledger, current_q, week, events, values, current_reviews, evidence)
        historical = weekly_state(ledger, week, mode="historically_known_state",
                                  knowledge_cutoff=week_cutoff, atomic_signals=signals)
        known_evidence = [e for e in evidence.values() if e.get("documented_at") and
                          e.get("source_first_seen_at") and e["documented_at"][:10] <= week_cutoff and
                          e["source_first_seen_at"][:10] <= week_cutoff]
        quality = "unavailable" if not known_evidence else "partial"
        current_shape = {"opportunities": current}
        changes = movement(prior, current_shape) if prior else {"changes": [], "count": 0}
        journey_changes = [x for x in changes["changes"] if x["kind"] in
                           {"new_opportunity", "new_event", "journey_advance"}]
        economic_changes = [x for x in changes["changes"] if x["kind"] in
                            {"value_revision", "reported_signed", "verified_actual", "band_change",
                             "identity_correction", "commercial_signed"}]
        risk_changes = [x for x in changes["changes"] if x["kind"] in
                        {"momentum_change", "lifecycle_change", "blocker_change", "blocker_opened",
                         "blocker_resolved", "lost", "stalled", "revived", "restatement"}]
        snapshots.append({"week_end": week, "knowledge_cutoff": week_cutoff,
            "retrospective_event_state": {"mode": "retrospective_event_state",
                "opportunities": current, "verified_actual_usd": current_q["verified_actual_usd"]},
            "historically_known_state": {"mode": "historically_known_state",
                "historical_knowledge_quality": quality,
                "opportunity_ids": sorted(oid for oid, x in historical["opportunities"].items()
                                          if quality != "unavailable" and
                                          x["model_a"]["evidence_status"] == "available"),
                "verified_actual_usd": historical["verified_actual_usd"] if quality != "unavailable" else None},
            "historical_knowledge_quality": quality,
            "movement": {"journey": journey_changes, "economics": economic_changes,
                         "risk": risk_changes, "count": changes["count"]},
            "movement_baseline": "previous_reporting_week" if prior else "first_snapshot_no_prior_comparison"})
        prior = current_shape
    historical_quality = snapshots[-1]["historical_knowledge_quality"]
    overview["latest_weekly_movement"] = snapshots[-1]["movement"]
    beliefs = belief_presentation.build(
        opportunities=list(integrated.values()), signals=signals, business_as_of=business_as_of,
        knowledge_cutoff=cutoff, weeks=[x["week_end"] for x in snapshots], historical_quality=historical_quality,
        review_items=reviews, verified_actual_usd=q["verified_actual_usd"],
        reported_unverified_usd=q["reported_signed_possible_acv_usd"], evidence_ids=set(evidence),
        **_belief_context(ledger, evidence, signals, list(integrated), events, values))
    # Historical belief snapshots follow each week's own knowledge quality; unprovable weeks stay empty.
    for weekly, snap in zip(beliefs["weekly"], snapshots):
        weekly["historical_knowledge_quality"] = snap["historical_knowledge_quality"]
        if snap["historical_knowledge_quality"] == "unavailable":
            weekly["historically_known"] = None
    beliefs["provenance"] = dict(BELIEF_PROVENANCE)
    return {"overview": overview, "opportunities": summary_rows,
            "opportunity_details": list(integrated.values()), "weekly_snapshots": snapshots,
            "evidence_summaries": [_evidence_summary(e) for e in evidence.values()],
            "review_queue": reviews, "belief_states": beliefs, "_canonical": q,
            "_population_reconciliation": {"canonical_opportunity_count": len(canonical_opps),
                "materialized_opportunity_count": len(integrated), "as_of_exclusions": excluded,
                "canonical_opportunity_ids": sorted(canonical_opps), "materialized_opportunity_ids": sorted(integrated),
                "population_gate_passed": True},
            "_metadata": {"business_as_of": business_as_of, "knowledge_cutoff": cutoff,
                          "historical_knowledge_quality": historical_quality,
                          "canonical_model_version": MODEL_VERSION,
                          "source_run_ids": {"a2": (stage_c or {}).get("a2_run_id"),
                                             "c": hashlib.sha256(json.dumps(stage_c,
                                                 sort_keys=True, ensure_ascii=False,
                                                 separators=(",", ":")).encode("utf-8")).hexdigest()[:24]
                                             if stage_c is not None else None}}}


def write_store_and_contract(model: dict[str, Any], sqlite_path: str | Path,
                             output_dir: str | Path) -> dict[str, Any]:
    """Atomically rebuild SQLite and JSON from one materialized in-memory model."""
    sqlite_path, output_dir = Path(sqlite_path), Path(output_dir)
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    temp = sqlite_path.with_suffix(".building")
    if temp.exists():
        temp.unlink()
    db = sqlite3.connect(temp)
    try:
        db.executescript("""
        CREATE TABLE opportunity_state(opportunity_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE journey_events(event_id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL, event_type TEXT NOT NULL, milestone TEXT, evidence_ids TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE commercial_values(value_id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL, usd_normalized TEXT, status TEXT NOT NULL, selected_for_open_value INTEGER NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE weekly_opportunity_state(week_end TEXT NOT NULL, mode TEXT NOT NULL, opportunity_id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(week_end,mode,opportunity_id));
        CREATE TABLE weekly_summary(week_end TEXT NOT NULL, mode TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(week_end,mode));
        CREATE TABLE evidence_summary(evidence_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE review_items(review_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE belief_state(opportunity_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE weekly_belief(week_end TEXT NOT NULL, mode TEXT NOT NULL, opportunity_id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(week_end,mode,opportunity_id));
        CREATE TABLE review_triage(review_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        """)
        encode = lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for x in model["opportunity_details"]:
            db.execute("INSERT INTO opportunity_state VALUES (?,?)", (x["opportunity_id"], encode(x)))
            for e in x["event_timeline"]:
                db.execute("INSERT INTO journey_events VALUES (?,?,?,?,?,?)",
                           (e["event_id"], x["opportunity_id"], e["event_type"],
                            EVENT_TO_JOURNEY.get(e["event_type"]), encode(e["evidence_ids"]), encode(e)))
            for v in x["commercial_values"]:
                db.execute("INSERT INTO commercial_values VALUES (?,?,?,?,?,?)",
                           (v["value_id"], x["opportunity_id"], v["usd_normalized"], v["status"],
                            int(v["selected_for_open_value"]), encode(v)))
        for snap in model["weekly_snapshots"]:
            for mode, value in (("retrospective_event_state", snap["retrospective_event_state"]),
                                ("historically_known_state", snap["historically_known_state"])):
                db.execute("INSERT INTO weekly_summary VALUES (?,?,?)", (snap["week_end"], mode, encode(value)))
            for oid, x in snap["retrospective_event_state"]["opportunities"].items():
                db.execute("INSERT INTO weekly_opportunity_state VALUES (?,?,?,?)",
                           (snap["week_end"], "retrospective_event_state", oid, encode(x)))
            for oid in snap["historically_known_state"]["opportunity_ids"]:
                db.execute("INSERT INTO weekly_opportunity_state VALUES (?,?,?,?)",
                           (snap["week_end"], "historically_known_state", oid,
                            encode({"opportunity_id": oid, "historical_knowledge_quality":
                                    snap["historical_knowledge_quality"]})))
        for e in model["evidence_summaries"]:
            db.execute("INSERT INTO evidence_summary VALUES (?,?)", (e["evidence_id"], encode(e)))
        for r in model["review_queue"]:
            db.execute("INSERT INTO review_items VALUES (?,?)", (r["review_id"], encode(r)))
        beliefs = model["belief_states"]
        for oid, x in beliefs["opportunities"].items():
            db.execute("INSERT INTO belief_state VALUES (?,?)", (oid, encode(x)))
        for week in beliefs["weekly"]:
            for mode in ("retrospective", "historically_known"):
                for oid, x in (week[mode] or {}).items():
                    db.execute("INSERT INTO weekly_belief VALUES (?,?,?,?)", (week["week_end"], mode, oid, encode(x)))
        for rid, x in beliefs["review_triage"].items():
            db.execute("INSERT INTO review_triage VALUES (?,?)", (rid, encode(x)))
        db.commit()
    finally:
        db.close()
    temp.replace(sqlite_path)
    inventory = {}
    for name in FILES:
        payload = {"schema_version": VERSION, "kind": name, "data": model[name]}
        path = output_dir / f"{name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        inventory[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    meta = model["_metadata"]
    revision = hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest()[:24]
    manifest = {"schema_version": VERSION, "snapshot_id": f"{meta['business_as_of']}:{revision}",
                "revision_id": revision, "generated_at": datetime.now(timezone.utc).isoformat(),
                "business_as_of": meta["business_as_of"], "knowledge_cutoff": meta["knowledge_cutoff"],
                "timezone": settings.timezone(), "source_run_ids": meta["source_run_ids"],
                "canonical_model_version": meta["canonical_model_version"],
                "target": model["overview"]["target"],
                "historical_knowledge_quality": meta["historical_knowledge_quality"],
                "files": inventory}
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest
