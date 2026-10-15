"""Build the `belief_states` presentation file (shared by live read model and demo).

Inputs are already-published facts (opportunity rows, review items, evidence ids)
and atomic signals. Output separates Observed, Inferred and Verified explicitly.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable

from . import context, engine, metrics, review_policy, valuation
from .ontology import DECISION_RELEVANT, SIGNAL_TYPES, VERSION, ontology_summary

KIND = "belief_states"
WEEKLY_DIMENSIONS = DECISION_RELEVANT + ("momentum", "blocker_state")


def _observed(signal: dict[str, Any]) -> dict[str, Any]:
    d = signal.get("details") or {}
    return {"signal_id": signal["signal_id"], "signal_type": signal["signal_type"],
            "label": SIGNAL_TYPES[signal["signal_type"]].label, "effective_date": signal.get("effective_date"),
            "modality": signal["modality"], "polarity": signal["polarity"], "observation": signal["observation"],
            "method": signal["extraction_method"], "signal_confidence": signal["signal_confidence"],
            "contract_kind": signal.get("contract_kind"), "evidence_ids": signal["evidence_ids"],
            "retyped_from": d.get("retyped_from"), "inert_reason": d.get("inert_reason"),
            "indicative": bool(d.get("indicative")), "sensor_readings": signal.get("sensor_readings") or []}


def _verified(row: dict[str, Any], signals: list[dict[str, Any]]) -> dict[str, Any]:
    achieved = lambda s: s["polarity"] == "positive" and not (s.get("details") or {}).get("inert_reason")
    reported = {s.get("contract_kind") or "unknown" for s in signals if s["signal_type"] == "reported_signature" and achieved(s)}
    formal = any(s["signal_type"] == "formal_signature_verified" for s in signals) or \
        row.get("commercial_state") == "verified_signed"
    return {"verified_actual_usd": row.get("verified_actual_usd"),
            "formal_contract_verified": formal,
            "reported_pilot_signature": "pilot" in reported,
            "reported_commercial_signature": "commercial" in reported or ("unknown" in reported and not formal),
            "reported_signed_pending_verification_usd": row.get("reported_signed_pending_verification_usd"),
            "rule": "Only a documentary-verified commercial contract counts toward Verified Actual. "
                    "Inferred states and reported signatures never do."}


def _value_facts(row: dict[str, Any], signals: list[dict[str, Any]]) -> dict[str, Any]:
    indicative = sum(1 for s in signals if s["signal_type"] == "pricing_discussed"
                     and ((s.get("details") or {}).get("indicative") or s.get("contract_kind") == "pilot"))
    return {"known_open_value_usd": row.get("known_open_commercial_value_usd"), "indicative_value_count": indicative}


def _changes(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[dict[str, Any]]:
    if previous is None:
        return []
    out = []
    for oid in sorted(set(previous) | set(current)):
        a, b = previous.get(oid) or {}, current.get(oid) or {}
        for dim in WEEKLY_DIMENSIONS:
            if a.get(dim) != b.get(dim) and b.get(dim) and (b[dim][1] or (a.get(dim) or [None, None])[1]):
                out.append({"opportunity_id": oid, "dimension": dim, "from": a.get(dim), "to": b.get(dim)})
    return out


def build(*, opportunities: list[dict[str, Any]], signals: Iterable[dict[str, Any]], business_as_of: str,
          knowledge_cutoff: str | None = None, weeks: list[str] | None = None,
          historical_quality: str = "unavailable", review_items: list[dict[str, Any]] | None = None,
          verified_actual_usd: str | None = None, reported_unverified_usd: str | None = None,
          evidence_ids: set[str] | None = None, accounts_with_multiple_scopes: set[str] | None = None,
          sources: dict[str, list[dict[str, Any]]] | None = None,
          source_signals: dict[str, list[dict[str, Any]]] | None = None,
          seed_groups: dict[str, set[str]] | None = None, group_accounts: dict[str, str] | None = None) -> dict[str, Any]:
    """`sources`/`source_signals`/`seed_groups` enable contextual reconstruction and valuation:
    group -> evidence [{evidence_id, text, date}], group -> its source-scoped signals, opportunity -> its groups."""
    cutoff = knowledge_cutoff or business_as_of
    rows = {r["opportunity_id"]: r for r in opportunities}
    by_opp: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in signals:
        if s.get("opportunity_id") in rows:
            if evidence_ids is not None and not set(s["evidence_ids"]) <= evidence_ids:
                raise ValueError("Belief signal references unpublished evidence")
            by_opp[s["opportunity_id"]].append(s)
    ctx = None
    if sources is not None:
        ctx = context.expand(rows=rows, by_opp={oid: by_opp[oid] for oid in rows}, sources=sources,
                             source_signals=source_signals or {}, seed_groups=seed_groups or {}, as_of=business_as_of,
                             group_accounts=group_accounts)
        by_opp = defaultdict(list, ctx["expanded"])
        if evidence_ids is not None:
            for sub in ctx["subjects"].values():
                for sig in sub["signals"]:
                    if not set(sig["evidence_ids"]) <= evidence_ids:
                        raise ValueError("Reconstructed signal references unpublished evidence")
    current = {oid: engine.infer(by_opp[oid], business_as_of) for oid in rows}
    historical_ok = historical_quality != "unavailable"
    out_opps = {}
    for oid, belief in current.items():
        hist = engine.infer(by_opp[oid], business_as_of, mode="historically_known", knowledge_cutoff=cutoff) \
            if historical_ok else None
        out_opps[oid] = {
            "opportunity_id": oid, "headline": engine.headline(belief), "inferred_stage": metrics.inferred_stage(belief),
            "current": belief,
            "observed_signals": [_observed(s) for s in sorted(by_opp[oid], key=lambda s: (s.get("effective_date") or "9999", s["signal_id"]))],
            "verified": _verified(rows[oid], by_opp[oid]),
            "unresolved_contradictions": [c for c in belief["contradictions"] if c["material"]],
            "valuation": ctx["valuations"][oid] if ctx else None,
            "context_links": sorted({l["group"] for s in by_opp[oid]
                                     for l in [(s.get("details") or {}).get("linked_by_context") or {}] if l.get("group")}),
            "historically_known": {"available": historical_ok,
                                   "states": engine.compact(hist) if hist else None,
                                   "note": None if historical_ok else
                                   "Historical knowledge quality is unavailable: source timestamps do not show what was known then."},
        }
    value_facts = {oid: _value_facts(rows[oid], by_opp[oid]) for oid in rows}
    overview = metrics.portfolio(current, value_facts, verified_actual_usd, reported_unverified_usd)
    overview.pop("flags")
    reconstructed = {}
    if ctx:
        for cid, sub in ctx["subjects"].items():
            b = sub["belief"]
            reconstructed[cid] = {"cluster_id": cid, "label": sub["label"], "groups": sub["groups"], "links": sub["links"],
                                  "accounts": sub.get("accounts", []),
                                  "anchors": sub["anchors"], "headline": engine.headline(b),
                                  "inferred_stage": metrics.inferred_stage(b), "current": b,
                                  "observed_signals": [_observed(x) for x in sorted(sub["signals"], key=lambda x: (x.get("effective_date") or "9999", x["signal_id"]))],
                                  "valuation": sub["valuation"], "corroboration": sub["corroboration"],
                                  "status": "inferred_from_context",
                                  "note": "Not a canonical opportunity: reconstructed by linking unlinked notes through shared distinctive anchors."}
        all_vals = {**ctx["valuations"], **{f"reconstructed:{k}": v["valuation"] for k, v in reconstructed.items()}}
        overview["valuation"] = valuation.totals(all_vals, verified_actual_usd)
        overview["valuation"]["corpus_stats"] = ctx["corpus_stats"]
        overview["reconstructed_deal_count"] = len(reconstructed)
        # The same inferred-state counts over canonical opportunities plus reconstructed deals.
        combined = {**current, **{f"reconstructed:{k}": ctx["subjects"][k]["belief"] for k in reconstructed}}
        portfolio_all = metrics.portfolio(combined)
        portfolio_all.pop("flags")
        portfolio_all.pop("value_buckets")
        overview["portfolio_with_reconstructed"] = {**portfolio_all, "canonical_opportunities": len(current),
                                                    "reconstructed_deals": len(reconstructed)}
        overview["reconstruction"] = ctx["reconstruction"]
    # Review triage over every existing item; belief items only for material contradictions/ambiguity.
    account_of = {oid: r.get("account_id") for oid, r in rows.items()}
    if accounts_with_multiple_scopes is None:
        counts = Counter(account_of.values())
        accounts_with_multiple_scopes = {a for a, n in counts.items() if a and n > 1}
    triage = {r["review_id"]: review_policy.triage(r, accounts_with_multiple_scopes=accounts_with_multiple_scopes,
                                                   account_of=account_of) for r in review_items or []}
    belief_items = [i for oid, b in current.items() for i in review_policy.belief_review_items(oid, b)]
    for item in belief_items:
        triage[item["review_id"]] = {"decision_needed": True, "category": item["reason"],
                                     "rationale": "Decision-relevant inferred state is contradicted or ambiguous"}
    needed = sum(t["decision_needed"] for t in triage.values())
    weekly = []
    previous = None
    for week in weeks or []:
        retro = {}
        for oid in rows:
            b = engine.infer(by_opp[oid], week)
            if b["signals_considered"]:
                retro[oid] = engine.compact(b)
        known = None
        if historical_ok:
            known = {}
            for oid in rows:
                b = engine.infer(by_opp[oid], week, mode="historically_known", knowledge_cutoff=week)
                if b["signals_considered"]:
                    known[oid] = engine.compact(b)
        weekly.append({"week_end": week, "retrospective": retro, "historically_known": known,
                       "historical_knowledge_quality": historical_quality, "changes": _changes(previous, retro)})
        previous = retro
    return {"engine_version": VERSION, "kind": KIND, "business_as_of": business_as_of, "knowledge_cutoff": cutoff,
            "ontology": ontology_summary(), "opportunities": out_opps, "overview": overview,
            "reconstructed_opportunities": reconstructed,
            "review_triage": triage, "belief_review_items": belief_items,
            "review_summary": {"total": len(triage), "decision_needed": needed, "informational": len(triage) - needed,
                               "by_category": dict(Counter(t["category"] for t in triage.values()))},
            "weekly": weekly,
            "boundaries": ["Observed: atomic signals anchored to exact evidence.",
                           "Inferred: belief states from combinations of signals; bands are heuristic, not probabilities.",
                           "Verified: only the documentary contract gate; inferred states never change Verified Actual."]}
