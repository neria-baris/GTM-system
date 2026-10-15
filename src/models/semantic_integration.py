"""Conservative C2 proposals -> canonical entities and atomic signals. No documentary verification."""
from collections import Counter, defaultdict
from decimal import Decimal
import json
import re

from src.belief import jev_sensors, signals
from src.ledger.models import Account, Contact, CommercialScope, Opportunity, OfferOrContract, Claim, Event, CommercialValue
from src.ledger.store import stable_id

VERSION = "semantic_canonical_1.1.0"
# Typed event details the ledger requires but extraction does not supply: the
# statement is used as an atomic signal only, without a canonical journey event.
SIGNAL_ONLY_EVENTS = {"data_requested", "data_received", "sow_sent", "pilot_started", "blocker_resolved",
                      "commercial_proposal_sent", "revived"}


def _persist_signals(ledger, c, d, *, oid, aid, when, precision, evidence_ids):
    """Every validated Luna reading becomes an evidence-anchored signal; normalisation keeps
    plans, conditions and negations from supporting achieved states."""
    readings = signals.semantic_readings(c["predicate"], c["semantic_payload"])
    sensor = (c.get("jev_sensor") or {}).get("readings") or []
    out = []
    for n, r in enumerate(readings):
        signal = signals.make_signal(
            r["signal_type"], evidence_ids=evidence_ids, method="luna_semantic",
            id_seed=f"candidate:{c['candidate_id']}:{n}:{r['signal_type']}", effective_date=when,
            date_basis=precision, modality=r["modality"], observation=r["observation"], confidence=r["confidence"],
            contract_kind=r.get("contract_kind"), opportunity_id=oid, account_id=aid,
            subject_ref=None if oid else "source:" + c["provider"] + ":" + c["native_source_id"],
            evidence_availability=signals.availability(ledger, evidence_ids), source_candidate_id=c["candidate_id"],
            details={**(r.get("details") or {}), "clause": r.get("clause"), "predicate": "semantic:" + c["predicate"],
                     "claim_id": d["claim_id"],
                     **({"event_id": d["event_id"]} if d.get("event_id") else {})})
        if sensor:
            signal = jev_sensors.apply(signal, sensor)
        ledger.add_signal(signal)
        out.append(signal)
    return out


def integrate_semantics(ledger, candidates, dispositions, snapshots, envelopes, schema):
    by_candidate = {d["candidate_id"]: d for d in dispositions}
    tables = {t["id"]: t for t in schema["tables"]}
    account_map = {}
    # Native record identity is authoritative only within its source; no name merges.
    records = []
    for key, snapshot in snapshots.items():
        if key[:2] != ("airtable", "record"):
            continue
        content = snapshot["content"]
        table = tables[content["table_id"]]
        fields = {f["name"]: content["record"].get("fields", {}).get(f["id"]) for f in table["fields"]}
        records.append((key, table["name"], fields))
        if table["name"] == "Companies" and fields.get("Company Name"):
            from src.ledger.models import SourceRef
            aid = stable_id("live_account", key[2])
            ledger.add_entity(Account(id=aid, canonical_name=fields["Company Name"],
                industry=fields.get("Industry"), source_refs=(SourceRef(*key),),
                created_in_ledger_at=envelopes[key]["retrieved_at"], resolution_status="resolved"))
            account_map[key[2]] = aid
    for key, table, fields in records:
        if table == "Contacts" and fields.get("Full Name"):
            from src.ledger.models import SourceRef
            ledger.add_entity(Contact(id=stable_id("live_contact", key[2]), display_name=fields["Full Name"],
                normalized_email=(fields.get("Email") or "").strip().lower() or None, title=fields.get("Title"),
                account_affiliations=tuple({"account_id": account_map[a], "valid_from": None, "valid_to": None}
                                           for a in fields.get("Company", []) if a in account_map),
                source_refs=(SourceRef(*key),), created_in_ledger_at=envelopes[key]["retrieved_at"],
                resolution_status="provisional"))
    sem = [c for c in candidates if c.get("semantic_schema_version") and
           c["validation_status"] in {"semantic_validated_proposal", "review_required"}]
    reviews = []
    def review(c, reason, oid=None):
        reviews.append({"review_id": stable_id("semantic_review", c["candidate_id"] + reason),
            "reason": reason, "candidate_ids": [c["candidate_id"]], "opportunity_id": oid,
            "single_decision_needed": "Resolve the cited identity, scope, event details or value without inferring missing facts"})
    local = defaultdict(set)
    opp_by_candidate = {}
    accounts_to_opps = defaultdict(set)
    for c in sem:
        if c["predicate"] != "opportunity_candidates":
            continue
        p = c["semantic_payload"]
        aid = account_map.get(p.get("account_candidate_id"))
        use_case, boundary = p["use_case"].strip(), p["commercial_scope"].strip()
        if (not aid or p["relationship"] != "base" or not use_case or not boundary or
                re.search(r"\b(?:unknown|unspecified|not stated|unresolved)\b", use_case + " " + boundary, re.I)):
            review(c, "unresolved_account_use_case_or_scope")
            continue
        # Only exact normalized tuples merge. Semantic similarity is not an identity decision.
        seed = json.dumps([aid, " ".join(use_case.casefold().split()), " ".join(boundary.casefold().split())])
        oid, scope_id = stable_id("live_opportunity", seed), stable_id("live_scope", seed)
        eid = by_candidate[c["candidate_id"]]["evidence_id"]
        seen = ledger.evidence(eid)["ingested_at"]
        if ledger.entity(oid) is None:
            ledger.add_entity(CommercialScope(id=scope_id, scope_id=scope_id, account_id=aid,
                product_use_case=use_case, boundary_text=boundary, created_in_ledger_at=seen,
                resolution_status="provisional"))
            ledger.add_entity(Opportunity(id=oid, account_id=aid, use_case_code=stable_id("use_case", use_case.casefold()),
                use_case_description=use_case, commercial_scope_id=scope_id,
                opportunity_group_id=stable_id("unresolved_account_scopes", aid),
                origin_evidence_id=eid, created_in_ledger_at=seen, resolution_status="provisional"))
        opp_by_candidate[c["candidate_id"]] = oid
        local[(c["native_source_id"], aid)].add(oid)
        accounts_to_opps[aid].add(oid)
        review(c, "provisional_scope_requires_identity_review", oid)
    date_evidence = defaultdict(list)
    for c in candidates:
        if c.get("date_role") == "meeting_date" and c.get("business_date"):
            date_evidence[c["native_source_id"]].append((c["business_date"], by_candidate[c["candidate_id"]]["evidence_id"]))
    pending = []
    for c in sem:
        d = by_candidate[c["candidate_id"]]
        p = c["semantic_payload"]
        aid = account_map.get(p.get("account_candidate_id"))
        eligible = local[(c["native_source_id"], aid)] if aid else set()
        oid = opp_by_candidate.get(c["candidate_id"]) or (next(iter(eligible)) if len(eligible) == 1 else None)
        opp = ledger.entity(oid) if oid else None
        scope = opp["commercial_scope_id"] if opp else None
        eid = d["evidence_id"]
        evidence_ids = [eid]
        when = c.get("business_date") or p.get("effective_date")
        precision = "source_explicit_date" if when else "date_unknown"
        dated = date_evidence[c["native_source_id"]]
        if not when and len({day for day, _ in dated}) == 1:
            when = dated[0][0]
            evidence_ids.append(dated[0][1])
            precision = "structured_meeting_date_context"
        d["canonical_opportunity_id"] = oid
        subject = oid or "source:" + c["provider"] + ":" + c["native_source_id"]
        claim_id = stable_id("semantic_claim", c["candidate_id"])
        ledger.add_claim(Claim(claim_id=claim_id, subject_id=subject, predicate="semantic:" + c["predicate"],
            object_value=json.dumps(p, ensure_ascii=False, sort_keys=True), polarity=p.get("polarity") or "unclear",
            contract_kind=c.get("contract_kind"), scope_id=scope, valid_from=when,
            evidence_ids=tuple(evidence_ids), status="observed", verification="unverified",
            extraction_confidence="medium", resolution_reason=VERSION + ":source_supported_proposal"))
        d["claim_id"] = claim_id
        d["integration_disposition"] = "semantic_proposal"
        pending.append((c, d, dict(oid=oid, aid=aid, when=when, precision=precision, evidence_ids=evidence_ids)))
        if not oid and c["predicate"] in {"events", "commercial_values"}:
            review(c, "unresolved_or_multiple_note_opportunity_scopes")
        if c["predicate"] == "events":
            # Non-asserted statements are claims only. They cannot advance any journey.
            if p["polarity"] != "asserted":
                continue
            kind = p["event_type"]
            info = {}
            if kind in {"pilot_signed", "commercial_signed"}:
                contract_kind = "pilot" if kind == "pilot_signed" else "commercial"
                if not opp or p["contract_kind"] != contract_kind:
                    review(c, "signature_identity_scope_or_contract_kind_unresolved", oid)
                    continue
                cid = stable_id("reported_contract", oid + ":" + contract_kind)
                if ledger.entity(cid) is None:
                    ledger.add_entity(OfferOrContract(id=cid, opportunity_id=oid, contract_kind=contract_kind,
                        scope_id=scope, status="reported_signed", signature_date=when,
                        created_in_ledger_at=ledger.evidence(eid)["ingested_at"], resolution_status="provisional"))
                info["pilot_contract_id" if contract_kind == "pilot" else "commercial_contract_id"] = cid
                review(c, "reported_signature_pending_documentary_verification", oid)
            elif kind == "pilot_verbal_yes":
                if not opp:
                    d["integration_disposition"] = "semantic_signal_only"
                    continue
                info["pilot_scope"] = ledger.entity(scope)["boundary_text"]
            elif kind == "technical_milestone":
                info.update(milestone_kind="other", result="unknown")
            elif kind == "blocker_opened":
                info["blocker_kind"] = "other"
            elif kind == "procurement_legal_started":
                quote = p["quote"].casefold()
                info["domain"] = "both" if "procurement" in quote and "legal" in quote else "legal" if "legal" in quote else "procurement" if "procurement" in quote else None
                if not info["domain"]:
                    d["integration_disposition"] = "semantic_signal_only"
                    continue
            elif kind in SIGNAL_ONLY_EVENTS:
                d["integration_disposition"] = "semantic_signal_only"
                continue
            event_id = stable_id("semantic_event", c["candidate_id"])
            ledger.add_event(Event(event_id=event_id, event_type=kind, account_id=aid,
                unresolved_entity_ref=None if aid else c["native_source_id"], opportunity_id=oid,
                scope_id=scope, contract_kind=p["contract_kind"], event_date=when, date_precision=precision,
                first_seen_at=ledger.evidence(eid)["source_first_seen_at"], evidence_ids=tuple(evidence_ids),
                polarity="positive", assertion="explicit", status="observed", verification="unverified",
                review_state="unreviewed", extraction_version=VERSION, details=info))
            d["event_id"] = event_id
        elif c["predicate"] == "commercial_values":
            if (not opp or p["amount"] is None or not p["currency"] or
                    p["status"] not in {"tentative", "proposed", "signed_reported", "retracted"}):
                review(c, "value_amount_currency_status_or_scope_unresolved", oid)
                continue
            unit = p.get("unit")
            # Source-supported unit normalization only; never annualize an unknown unit.
            quote = p["quote"].casefold()
            normalized = "per_year" if unit in {"per_year", "per year", "annual", "/yr"} and re.search(r"/yr|per year|annual", quote) else "unknown"
            vid = stable_id("semantic_value", c["candidate_id"])
            ledger.add_value(CommercialValue(value_id=vid, opportunity_id=oid, scope_id=scope,
                amount_decimal=Decimal(str(p["amount"])), currency_ISO=p["currency"], value_type=p["value_type"],
                status=p["status"], unit=normalized, date_observed=when, source_evidence_ids=tuple(evidence_ids),
                first_seen_at=ledger.evidence(eid)["source_first_seen_at"], verification="unverified",
                scenario_group_id=stable_id("unresolved_scenario", aid) if p.get("scenario_relation") else None))
            d["value_id"] = vid
    # Signals are persisted after event creation so each one can cite its canonical event.
    persisted = []
    for c, d, link in pending:
        made = _persist_signals(ledger, c, d, **link)
        persisted.extend(made)
        d["signal_ids"] = [x["signal_id"] for x in made]
    # A dated meeting note linked to exactly one opportunity is an observed interaction;
    # the engine derives cadence (recurring interaction) from these at evaluation time.
    provider_of = {c["native_source_id"]: c["provider"] for c in sem}
    for (source_id, aid), oids in sorted(local.items()):
        dated = date_evidence[source_id]
        if len(oids) != 1 or len({day for day, _ in dated}) != 1:
            continue
        oid, (day, date_eid) = next(iter(oids)), dated[0]
        signal = signals.make_signal("meeting_held", evidence_ids=[date_eid], method="deterministic_rule",
            id_seed=f"meeting:{provider_of[source_id]}:{source_id}:{oid}:{day}", effective_date=day,
            date_basis="structured_meeting_date_context", modality="completed", observation="observed", confidence="high",
            opportunity_id=oid, account_id=aid, evidence_availability=signals.availability(ledger, [date_eid]),
            details={"rule": "single_opportunity_meeting_note", "native_source_id": source_id})
        ledger.add_signal(signal)
        persisted.append(signal)
    return {"review_items": reviews,
            "atomic_signal_count": len(persisted),
            "atomic_signals_by_type": dict(Counter(x["signal_type"] for x in persisted)),
            "source_scoped_signal_count": sum(x["opportunity_id"] is None for x in persisted),
            "semantic_claim_count": len(sem),
            "provisional_opportunity_count": len(set(opp_by_candidate.values())),
            "unresolved_opportunity_candidate_count": sum(c["predicate"] == "opportunity_candidates" and c["candidate_id"] not in opp_by_candidate for c in sem),
            "accounts_with_multiple_provisional_scopes": sum(len(ids) > 1 for ids in accounts_to_opps.values())}
