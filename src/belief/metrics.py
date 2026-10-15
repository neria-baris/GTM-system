"""Portfolio metrics over inferred belief states.

These are counts of inferred states. They never add to, subtract from or
replace Verified Actual, reported-signature value or the Model C proxy.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any

from .ontology import band_rank

HIGH = band_rank("high")
MEDIUM = band_rank("medium")


def _at_least(state: dict[str, Any], band: int) -> bool:
    return band_rank(state.get("band")) >= band


def classify(belief: dict[str, Any]) -> dict[str, bool]:
    s = belief["states"]
    pilot, commercial, procurement = s["pilot_status"], s["commercial_status"], s["procurement_status"]
    commitment, momentum, blockers = s["buyer_commitment"], s["momentum"], s["blocker_state"]
    return {
        "operationally_active_pilot": pilot["value"] == "active" and _at_least(pilot, HIGH),
        "likely_committed_pilot": (pilot["value"] in {"committed", "active", "completed"} and _at_least(pilot, MEDIUM)),
        "likely_committed_buyer": commitment["value"] in {"verbal_commitment", "committed"} and _at_least(commitment, MEDIUM),
        "commercial_process_underway": ((commercial["value"] in {"terms_negotiation", "terms_agreed", "reported_signed"}
                                         and _at_least(commercial, MEDIUM))
                                        or (procurement["value"] == "underway" and _at_least(procurement, MEDIUM))),
        "likely_stalled": momentum["value"] in {"stalled", "lost"} and _at_least(momentum, MEDIUM),
        "strong_momentum": momentum["value"] == "strong",
        "weak_momentum": momentum["value"] in {"weakening", "stalled"},
        "probable_blocker": blockers["value"] == "active" and _at_least(blockers, MEDIUM),
        "model_dependent": any(x.get("depends_on_model_inference") for x in s.values() if x.get("band")),
    }


def portfolio(beliefs: dict[str, dict[str, Any]], value_facts: dict[str, dict[str, Any]] | None = None,
              verified_actual_usd: str | None = None, reported_unverified_usd: str | None = None) -> dict[str, Any]:
    """Counts by inferred state plus separately labelled value buckets.

    value_facts[oid] may carry `known_open_value_usd` (eligible value from Model C, or None)
    and `indicative_value_count` (amounts stated conditionally or for pilots only).
    """
    value_facts = value_facts or {}
    flags = {oid: classify(b) for oid, b in beliefs.items()}
    counts = Counter()
    for f in flags.values():
        counts.update(k for k, v in f.items() if v)
    by_stage: dict[str, list[str]] = {}
    for oid, b in beliefs.items():
        stage = inferred_stage(b)
        by_stage.setdefault(stage, []).append(oid)
    known_by_stage = {}
    for stage, ids in by_stage.items():
        amounts = [Decimal(value_facts[o]["known_open_value_usd"]) for o in ids
                   if (value_facts.get(o) or {}).get("known_open_value_usd") is not None]
        known_by_stage[stage] = {"opportunities": len(ids), "with_known_value": len(amounts),
                                 "known_value_usd": str(sum(amounts, Decimal(0))) if amounts else None,
                                 "unknown_value_count": len(ids) - len(amounts)}
    return {
        "opportunities": len(beliefs),
        "operationally_active_pilots": counts["operationally_active_pilot"],
        "likely_committed_pilots": counts["likely_committed_pilot"],
        "likely_committed_buyers": counts["likely_committed_buyer"],
        "commercial_process_underway": counts["commercial_process_underway"],
        "likely_stalled": counts["likely_stalled"],
        "strong_momentum": counts["strong_momentum"], "weak_momentum": counts["weak_momentum"],
        "probable_blockers": counts["probable_blocker"],
        "model_dependent_beliefs": counts["model_dependent"],
        "momentum_distribution": dict(Counter(b["states"]["momentum"]["value"] for b in beliefs.values())),
        "pilot_status_distribution": dict(Counter(b["states"]["pilot_status"]["value"] for b in beliefs.values())),
        "inferred_stage_distribution": {k: len(v) for k, v in sorted(by_stage.items())},
        "value_buckets": {
            "verified_actual_usd": verified_actual_usd,
            "reported_unverified_usd": reported_unverified_usd,
            "known_value_by_inferred_stage": known_by_stage,
            "indicative_value_mentions": sum((value_facts.get(o) or {}).get("indicative_value_count", 0) for o in beliefs),
            "unknown_value_count": sum(1 for o in beliefs if (value_facts.get(o) or {}).get("known_open_value_usd") is None),
            "rule": "Inferred states never change Verified Actual. Known values are grouped by inferred stage only "
                    "when Model C already found an eligible value; indicative amounts are counted, not summed.",
        },
        "flags": flags,
    }


def inferred_stage(belief: dict[str, Any]) -> str:
    """Most advanced decision-relevant inferred stage with at least medium confidence."""
    s = belief["states"]
    ok = lambda d, values: s[d]["value"] in values and _at_least(s[d], MEDIUM)
    if s["momentum"]["value"] == "lost" and _at_least(s["momentum"], MEDIUM):
        return "lost"
    if ok("commercial_status", {"verified_signed"}):
        return "verified_signed"
    if ok("commercial_status", {"reported_signed"}):
        return "reported_signed_unverified"
    if ok("commercial_status", {"terms_negotiation", "terms_agreed"}) or ok("procurement_status", {"underway"}):
        return "commercial_process"
    if ok("pilot_status", {"active", "completed"}):
        return "pilot_active_or_completed"
    if ok("pilot_status", {"committed"}) or ok("buyer_commitment", {"verbal_commitment", "committed"}):
        return "pilot_committed"
    if ok("pilot_status", {"planned", "discussed"}) or ok("buyer_commitment", {"intent", "interest"}):
        return "early"
    return "unknown"
