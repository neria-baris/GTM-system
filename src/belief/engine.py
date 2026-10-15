"""Temporal belief-state engine.

Pure and deterministic: `infer(signals, as_of, ...)` reads only the signals it is
given and the evaluation date. It never reads or writes Verified Actual.
Derived signals (recurring interaction, inactivity) are recomputed here from the
signals available at `as_of`, so a historical evaluation cannot see later evidence.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from src.ledger.store import _known_by, stable_id

from .ontology import (BAND_FACTOR, BANDS, BLOCKER_TYPES, DECISION_RELEVANT, DIMENSION_LABELS, DIMENSIONS,
                       EARLIER_OPPOSITION_FACTOR, INACTIVITY_STALL_DAYS, MODEL_METHODS, PROGRESSIONS,
                       RECENCY, RECENCY_FLOOR, REVERSAL_VALUES, RULES, SIGNAL_TYPES, STALE_AFTER_DAYS,
                       STRENGTH, THRESHOLDS, VALUE_LABELS, VERSION, band_rank, shift_band)
from .signals import RISK_TYPES

MODES = ("retrospective", "historically_known")
PROGRESS_TYPES = frozenset(t for t, v in SIGNAL_TYPES.items()
                           if v.category in {"commitment", "technical", "pilot", "commercial", "procurement"})
INTERACTION_TYPES = frozenset({"meeting_held", "pilot_work_underway"})


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days


def is_available(signal: dict[str, Any], as_of: str, mode: str, cutoff: str | None = None) -> bool:
    """No hindsight: effective by `as_of`; in historical mode also knowable by the cutoff."""
    effective = signal.get("effective_date")
    if not effective or effective[:10] > as_of[:10]:
        return False
    if mode == "historically_known":
        cutoff = cutoff or as_of
        return any(e.get("documented_at") and e.get("source_first_seen_at")
                   and _known_by(e["documented_at"], cutoff) and _known_by(e["source_first_seen_at"], cutoff)
                   for e in signal.get("evidence_availability") or [])
    return True


def _group(signal: dict[str, Any]) -> str:
    groups = sorted({e.get("independence_group") for e in signal.get("evidence_availability") or []
                     if e.get("independence_group")})
    return groups[0] if groups else (signal.get("details") or {}).get("independence_group") or \
        ",".join(signal["evidence_ids"][:1]) or signal["signal_id"]


def _recency(signal: dict[str, Any], as_of: str) -> float:
    if SIGNAL_TYPES[signal["signal_type"]].persistence != "decaying":
        return 1.0
    age = _days(signal["effective_date"], as_of)
    return next((factor for limit, factor in RECENCY if age <= limit), RECENCY_FLOOR)


def _match(key: str, signal: dict[str, Any]) -> float:
    """1.0 exact, 0.5 when the signal's contract kind is unknown, 0 otherwise."""
    kind, _, contract = key.partition("@")
    if signal["signal_type"] != kind:
        return 0.0
    if not contract:
        return 1.0
    actual = signal.get("contract_kind") or "unknown"
    return 1.0 if actual == contract else 0.5 if actual == "unknown" else 0.0


def _cadence(signals: list[dict[str, Any]], as_of: str) -> list[dict[str, Any]]:
    """Recurring interaction: >= 3 interaction dates within 75 days, or >= 2 after a kickoff."""
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in signals:
        if s["signal_type"] in INTERACTION_TYPES and s["polarity"] == "positive" and not s["details"].get("inert_reason"):
            by_day[s["effective_date"]].append(s)
    days = sorted(by_day)
    if len(days) < 2:
        return []
    starts = sorted(s["effective_date"] for s in signals if s["signal_type"] in {"kickoff_completed"}
                    and s["polarity"] == "positive")
    window = [d for d in days if _days(d, days[-1]) <= 75]
    after_start = [d for d in days if starts and d >= starts[0]]
    chosen = window if len(window) >= 3 else after_start if len(after_start) >= 2 else []
    if not chosen:
        return []
    members = [s for d in chosen for s in by_day[d]]
    evidence = sorted({e for s in members for e in s["evidence_ids"]})
    availability = {e["evidence_id"]: e for s in members for e in s.get("evidence_availability") or []}
    first = members[0]
    return [{"signal_id": stable_id("derived_signal", f"cadence:{first.get('opportunity_id') or first.get('subject_ref')}:"
                                    f"{','.join(chosen)}:{as_of}"),
             "signal_type": "recurring_interaction", "opportunity_id": first.get("opportunity_id"),
             "account_id": first.get("account_id"), "subject_ref": first.get("subject_ref"),
             "effective_date": chosen[-1], "date_basis": "derived_from_dated_interactions",
             "evidence_ids": evidence, "evidence_availability": [availability[k] for k in sorted(availability)],
             "extraction_method": "cadence_rule", "polarity": "positive", "modality": "completed",
             "observation": "derived_pattern", "signal_confidence": "high", "contract_kind": None,
             "details": {"interaction_dates": chosen, "independence_group": "cadence",
                         "rule": ">=3 dated interactions within 75 days, or >=2 after kickoff"},
             "sensor_readings": [], "contradicts": [], "source_candidate_id": None, "ontology_version": VERSION}]


def _band_for(net: float, distinct: int, opposition: float) -> str | None:
    if net <= 0:
        return None
    if net >= THRESHOLDS["very_high"] and distinct >= 3 and opposition == 0:
        return "very_high"
    if net >= THRESHOLDS["high"] and distinct >= 2:
        return "high"
    if net >= THRESHOLDS["medium"]:
        return "medium"
    return "low"


def _entry(signal: dict[str, Any], contribution: float) -> dict[str, Any]:
    return {"signal_id": signal["signal_id"], "signal_type": signal["signal_type"],
            "label": SIGNAL_TYPES[signal["signal_type"]].label, "effective_date": signal["effective_date"],
            "evidence_ids": signal["evidence_ids"], "method": signal["extraction_method"],
            "observation": signal["observation"], "modality": signal["modality"],
            "signal_confidence": signal["signal_confidence"], "contract_kind": signal.get("contract_kind"),
            "polarity": signal["polarity"], "contribution": round(contribution, 2)}


def _resolved(signal: dict[str, Any], signals: list[dict[str, Any]]) -> bool:
    """A blocker or pause is neutralised by a later resolution or revival."""
    if signal["signal_type"] in BLOCKER_TYPES:
        cures = {"blocker_resolved", "revived"}
    elif signal["signal_type"] in {"project_paused", "explicit_rejection", "loss_of_momentum", "no_response"}:
        cures = {"revived"}
    else:
        return False
    return any(s["signal_type"] in cures and s["polarity"] == "positive" and s["effective_date"] >= signal["effective_date"]
               and s["signal_id"] != signal["signal_id"] for s in signals)


def _evaluate(rule, signals: list[dict[str, Any]], as_of: str) -> dict[str, Any]:
    raw: dict[str, dict[str, tuple[float, dict]]] = defaultdict(dict)
    gate_hit = False
    for s in signals:
        if s["polarity"] != "positive" or s["details"].get("inert_reason"):
            continue
        for key, weight in rule.support.items():
            match = _match(key, s)
            if not match:
                continue
            value = weight * match * BAND_FACTOR[s["signal_confidence"]] * _recency(s, as_of)
            group = _group(s)
            if value > raw[s["signal_type"]].get(group, (0.0, None))[0]:
                raw[s["signal_type"]][group] = (value, s)
            gate_hit = gate_hit or (key in rule.gate and match == 1.0)
            break
    support, supporting = 0.0, []
    for kind, groups in raw.items():
        for rank, (value, s) in enumerate(sorted(groups.values(), key=lambda x: (-x[0], x[1]["signal_id"]))):
            contribution = value * (1.0, 0.5)[min(rank, 1)] * (0.5 if rank >= 2 else 1.0)
            support += contribution
            supporting.append(_entry(s, contribution))
    last = max((e["effective_date"] for e in supporting), default=None)
    opposition, contradicting = 0.0, []
    for s in signals:
        if s["details"].get("inert_reason"):
            continue
        weight = 0.0
        if s["polarity"] == "positive" and s["signal_type"] in rule.opposed_by and not _resolved(s, signals):
            weight = rule.opposed_by[s["signal_type"]]
        elif s["polarity"] == "negative":
            weight = max((w * _match(k, {**s, "polarity": "positive"}) for k, w in rule.support.items()), default=0.0)
        if not weight:
            continue
        timing = 1.0 if not last or s["effective_date"] >= last else EARLIER_OPPOSITION_FACTOR
        value = weight * BAND_FACTOR[s["signal_confidence"]] * _recency(s, as_of) * timing
        opposition += value
        contradicting.append(_entry(s, value))
    distinct = len([k for k, g in raw.items() if g])
    return {"support": support, "opposition": opposition, "supporting": supporting,
            "contradicting": contradicting, "distinct": distinct, "gate": gate_hit, "last": last}


def _state(dimension: str, value: str, ev: dict[str, Any], rule, as_of: str, signals: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not ev["gate"] or ev["support"] <= 0:
        return None
    support, opposition = ev["support"], ev["opposition"]
    if opposition >= support:
        return None
    net = support - opposition
    verified_only = all(e["method"] == "verification_gate" for e in ev["supporting"])
    band = "very_high" if verified_only else _band_for(net, ev["distinct"], opposition)
    if band is None:
        return None
    caps = []
    if ev["distinct"] == 1 and not verified_only and band_rank(band) > band_rank("medium"):
        band, _ = "medium", caps.append("single_signal_type")
    contested = opposition > 0 and opposition >= 0.5 * support
    if contested:
        band = shift_band(band, -1)
        caps.append("contradicted")
    stale = bool(rule.current and ev["last"] and _days(ev["last"], as_of) > STALE_AFTER_DAYS)
    if stale and band_rank(band) > band_rank("medium"):
        band = "medium"
        caps.append("stale_evidence")
    model_points = sum(e["contribution"] for e in ev["supporting"] if e["method"] in MODEL_METHODS)
    share = model_points / support if support else 0.0
    present = {s["signal_type"] for s in signals if s["polarity"] == "positive"}
    missing = [text for key, text in rule.missing_hint if key.partition("@")[0] not in present]
    supporting = sorted(ev["supporting"], key=lambda e: (-e["contribution"], e["effective_date"] or ""))
    return {"dimension": dimension, "value": value, "band": band, "support_points": round(support, 2),
            "opposition_points": round(opposition, 2), "distinct_signal_types": ev["distinct"],
            "supporting": supporting, "contradicting": sorted(ev["contradicting"], key=lambda e: -e["contribution"]),
            "strongest_evidence_ids": supporting[0]["evidence_ids"] if supporting else [],
            "missing_expected": missing, "last_meaningful_update": ev["last"],
            "model_dependence": "high" if share > 0.66 else "partial" if share > 0.33 else "low",
            "depends_on_model_inference": share > 0.5, "stale": stale, "contested": contested,
            "caps_applied": caps, "inferred": True, "verified": value == "verified_signed" and verified_only}


def _rule_dimension(dimension: str, signals: list[dict[str, Any]], as_of: str) -> dict[str, Any]:
    candidates = {}
    for value, rule in RULES[dimension].items():
        state = _state(dimension, value, _evaluate(rule, signals, as_of), rule, as_of, signals)
        if state:
            candidates[value] = state
    progression = [v for v in PROGRESSIONS[dimension] if v in candidates]
    confident = [v for v in progression if band_rank(candidates[v]["band"]) >= band_rank("medium")]
    chosen = (confident or progression or [None])[-1]
    for reversal in REVERSAL_VALUES.get(dimension, ()):
        r = candidates.get(reversal)
        if not r or band_rank(r["band"]) < band_rank("medium"):
            continue
        if chosen is None or (r["last_meaningful_update"] or "") >= (candidates[chosen]["last_meaningful_update"] or ""):
            chosen = reversal
    if chosen is None:
        return _unknown(dimension)
    state = dict(candidates[chosen])
    state["alternatives"] = [{"value": v, "band": c["band"]} for v, c in candidates.items() if v != chosen]
    return state


def _unknown(dimension: str, value: str | None = None) -> dict[str, Any]:
    return {"dimension": dimension, "value": value or DIMENSIONS[dimension][0], "band": None, "support_points": 0.0,
            "opposition_points": 0.0, "distinct_signal_types": 0, "supporting": [], "contradicting": [],
            "strongest_evidence_ids": [], "missing_expected": [], "last_meaningful_update": None,
            "model_dependence": "low", "depends_on_model_inference": False, "stale": False, "contested": False,
            "caps_applied": [], "inferred": True, "verified": False, "alternatives": []}


def _blockers(signals: list[dict[str, Any]], as_of: str) -> dict[str, Any]:
    blockers = [s for s in signals if s["signal_type"] in BLOCKER_TYPES and s["polarity"] == "positive"
                and not s["details"].get("inert_reason")]
    if not blockers:
        return _unknown("blocker_state", "none_known")
    open_ = [s for s in blockers if not _resolved(s, signals)]
    resolutions = [s for s in signals if s["signal_type"] == "blocker_resolved" and s["polarity"] == "positive"]
    if not open_:
        state = _unknown("blocker_state", "resolved")
        state.update(band="medium", supporting=[_entry(s, 1.0) for s in resolutions],
                     last_meaningful_update=max(s["effective_date"] for s in resolutions),
                     strongest_evidence_ids=resolutions[-1]["evidence_ids"])
        return state
    firm = [s for s in open_ if band_rank(s["signal_confidence"]) >= band_rank("medium")
            and not any(r.get("choice") in {"risk_only", "not_a_blocker"} for r in s.get("sensor_readings") or [])]
    groups = {_group(s) for s in firm}
    band = ("very_high" if len(groups) >= 2 and len({s["signal_type"] for s in firm}) >= 2 else
            "high" if any(s["signal_confidence"] in {"high", "very_high"} for s in firm) else "medium") if firm else "low"
    chosen = firm or open_
    entries = sorted((_entry(s, STRENGTH[SIGNAL_TYPES[s["signal_type"]].strength] * BAND_FACTOR[s["signal_confidence"]])
                      for s in chosen), key=lambda e: (-e["contribution"], e["effective_date"]))
    model_share = sum(e["contribution"] for e in entries if e["method"] in MODEL_METHODS) / max(1e-9, sum(e["contribution"] for e in entries))
    state = _unknown("blocker_state", "active" if firm else "possible")
    state.update(band=band, supporting=entries, strongest_evidence_ids=entries[0]["evidence_ids"],
                 last_meaningful_update=max(s["effective_date"] for s in chosen),
                 support_points=round(sum(e["contribution"] for e in entries), 2),
                 distinct_signal_types=len({s["signal_type"] for s in chosen}),
                 model_dependence="high" if model_share > 0.66 else "partial" if model_share > 0.33 else "low",
                 depends_on_model_inference=model_share > 0.5,
                 blocker_kinds=sorted({s["signal_type"] for s in chosen}),
                 alternatives=[{"value": "resolved", "band": "medium"}] if resolutions else [])
    return state


def _engagement(signals: list[dict[str, Any]], as_of: str) -> dict[str, Any]:
    best: dict[tuple[str, str], tuple[float, dict]] = {}
    for s in signals:
        if s["polarity"] != "positive" or s["signal_type"] in RISK_TYPES or s["details"].get("inert_reason"):
            continue
        age = _days(s["effective_date"], as_of)
        recency = next((f for limit, f in RECENCY if age <= limit), RECENCY_FLOOR)
        value = STRENGTH[SIGNAL_TYPES[s["signal_type"]].strength] * BAND_FACTOR[s["signal_confidence"]] * recency
        key = (s["signal_type"], _group(s))
        if value > best.get(key, (0.0, None))[0]:
            best[key] = (value, s)
    if not best:
        return _unknown("engagement")
    score = sum(v for v, _ in best.values())
    types = {k[0] for k in best}
    value = "strong" if score >= 8 and len(types) >= 3 else "active" if score >= 3.5 else "light"
    band = "high" if len(types) >= 3 else "medium" if len(types) == 2 else "low"
    entries = sorted((_entry(s, v) for v, s in best.values()), key=lambda e: (-e["contribution"], e["effective_date"]))
    state = _unknown("engagement", value)
    model_share = sum(e["contribution"] for e in entries if e["method"] in MODEL_METHODS) / score
    state.update(band=band, supporting=entries[:8], support_points=round(score, 2), distinct_signal_types=len(types),
                 strongest_evidence_ids=entries[0]["evidence_ids"],
                 last_meaningful_update=max(e["effective_date"] for e in entries),
                 model_dependence="high" if model_share > 0.66 else "partial" if model_share > 0.33 else "low",
                 depends_on_model_inference=model_share > 0.5,
                 stale=_days(max(e["effective_date"] for e in entries), as_of) > STALE_AFTER_DAYS)
    return state


def _momentum(signals: list[dict[str, Any]], as_of: str, states: dict[str, dict[str, Any]]) -> dict[str, Any]:
    positives = [s for s in signals if s["polarity"] == "positive" and s["signal_type"] not in RISK_TYPES
                 and s["signal_type"] != "revived" and not s["details"].get("inert_reason")]
    revivals = [s for s in signals if s["signal_type"] == "revived" and s["polarity"] == "positive"]
    last_positive = max((s["effective_date"] for s in positives + revivals), default=None)
    rejection = [s for s in signals if s["signal_type"] == "explicit_rejection" and s["polarity"] == "positive"
                 and not _resolved(s, signals)]
    pauses = [s for s in signals if s["signal_type"] in {"project_paused", "budget_blocker"} and s["polarity"] == "positive"
              and not _resolved(s, signals) and (not last_positive or s["effective_date"] >= last_positive)]
    soft = [s for s in signals if s["signal_type"] in {"loss_of_momentum", "no_response"} and s["polarity"] == "positive"
            and _days(s["effective_date"], as_of) <= 60 and (not last_positive or s["effective_date"] >= last_positive)
            and not _resolved(s, signals)]
    if rejection and (not last_positive or max(s["effective_date"] for s in rejection) >= last_positive):
        state = _unknown("momentum", "lost")
        state.update(band="very_high" if len({_group(s) for s in rejection}) >= 2 else "high",
                     supporting=[_entry(s, 4.0) for s in rejection], strongest_evidence_ids=rejection[-1]["evidence_ids"],
                     last_meaningful_update=max(s["effective_date"] for s in rejection))
        return state
    if states.get("commercial_status", {}).get("value") == "verified_signed":
        return _unknown("momentum")
    if not last_positive and not pauses and not soft:
        return _unknown("momentum")
    idle = _days(last_positive, as_of) if last_positive else None
    recent_signals = [s for s in positives if _days(s["effective_date"], as_of) <= 30 and s["signal_type"] in PROGRESS_TYPES]
    recent = {s["signal_type"] for s in recent_signals}
    # Strong momentum needs separate recent interactions and no open recent blocker.
    recent_interactions = {(s["effective_date"], _group(s)) for s in recent_signals}
    open_blockers = [s for s in signals if s["signal_type"] in BLOCKER_TYPES and s["polarity"] == "positive"
                     and not _resolved(s, signals) and _days(s["effective_date"], as_of) <= 60]
    if pauses:
        value, band, basis = "stalled", "high", pauses
    elif idle is not None and idle >= INACTIVITY_STALL_DAYS:
        value, band, basis = "stalled", "high" if idle >= 90 else "medium", []
    elif soft or (idle is not None and idle >= 30):
        value, band, basis = "weakening", "medium", soft
    elif len(recent) >= 2 and len(recent_interactions) >= 2 and not open_blockers:
        value, band, basis = "strong", "high" if len(recent) >= 3 else "medium", []
    else:
        value, band, basis = "steady", "medium", []
    latest = [s for s in positives if s["effective_date"] == last_positive]
    state = _unknown("momentum", value)
    supporting = [_entry(s, 2.0) for s in basis] or [_entry(s, 1.0) for s in latest[:3]]
    state.update(band=band, supporting=supporting, strongest_evidence_ids=supporting[0]["evidence_ids"] if supporting else [],
                 last_meaningful_update=max([last_positive or ""] + [s["effective_date"] for s in basis]) or None,
                 days_since_customer_activity=idle,
                 rule=f"stalled when no customer activity for >= {INACTIVITY_STALL_DAYS} days or an unresolved pause; "
                      "weakening at 30 days or after recent silence/slippage; strong with >= 2 progression signal types in 30 days")
    return state


def _explain(state: dict[str, Any]) -> str:
    dim = DIMENSION_LABELS[state["dimension"]]
    value = VALUE_LABELS.get(state["value"], state["value"])
    if state["band"] is None:
        return f"{dim}: {value} — no supporting evidence."
    def items(entries):
        seen, out = set(), []
        for e in entries:
            text = e["label"].lower() + (f" ({e['effective_date']})" if e.get("effective_date") else "")
            if e.get("polarity") == "negative":
                text = "evidence against: " + text
            if text not in seen:
                seen.add(text)
                out.append(text)
        return out[:5]
    text = f"{dim}: {value} — {state['band'].replace('_', ' ')} confidence (inferred)."
    if state["supporting"]:
        text += " For: " + "; ".join(items(state["supporting"])) + "."
    against = items(state["contradicting"]) + state.get("missing_expected", [])
    if against:
        text += " Against: " + "; ".join(against) + "."
    if state.get("days_since_customer_activity") is not None:
        text += f" {state['days_since_customer_activity']} days since the last customer activity."
    if state["stale"]:
        text += " Latest supporting evidence is older than 90 days."
    if state["depends_on_model_inference"]:
        text += " Rests mainly on model-extracted evidence."
    return text


def infer(signals: list[dict[str, Any]], as_of: str, *, mode: str = "retrospective",
          knowledge_cutoff: str | None = None) -> dict[str, Any]:
    """Belief states for one opportunity (or source-scoped subject) at `as_of`."""
    if mode not in MODES:
        raise ValueError("Unknown belief mode")
    available = [s for s in signals if is_available(s, as_of, mode, knowledge_cutoff)]
    undated = sum(1 for s in signals if not s.get("effective_date"))
    available += _cadence(available, as_of)
    available.sort(key=lambda s: (s["effective_date"], s["signal_id"]))
    states: dict[str, dict[str, Any]] = {}
    for dimension in ("pilot_status", "buyer_commitment", "technical_commitment", "procurement_status", "commercial_status"):
        states[dimension] = _rule_dimension(dimension, available, as_of)
    states["blocker_state"] = _blockers(available, as_of)
    states["engagement"] = _engagement(available, as_of)
    states["momentum"] = _momentum(available, as_of, states)
    for state in states.values():
        state.setdefault("alternatives", [])
        state["explanation"] = _explain(state)
    contradictions = [{"dimension": d, "value": s["value"], "band": s["band"],
                       "supporting_evidence_ids": sorted({e for x in s["supporting"] for e in x["evidence_ids"]}),
                       "contradicting_evidence_ids": sorted({e for x in s["contradicting"] for e in x["evidence_ids"]}),
                       "material": d in DECISION_RELEVANT and s["contested"]}
                      for d, s in states.items() if s["contradicting"] and s["band"]]
    history = sorted({(s["effective_date"], s["signal_type"]) for s in available
                      if s["polarity"] == "positive" and SIGNAL_TYPES[s["signal_type"]].persistence == "persistent"
                      and s["signal_type"] in PROGRESS_TYPES and not s["details"].get("inert_reason")})
    return {"engine_version": VERSION, "as_of": as_of, "mode": mode, "knowledge_cutoff": knowledge_cutoff or as_of,
            "states": states, "contradictions": contradictions,
            "history": [{"date": d, "signal_type": t, "label": SIGNAL_TYPES[t].label} for d, t in history],
            "signals_considered": len(available), "signals_unavailable": len(signals) - undated - len(
                [s for s in available if s["extraction_method"] != "cadence_rule"]),
            "undated_signals": undated}


def compact(belief: dict[str, Any]) -> dict[str, list]:
    """Weekly-snapshot form: dimension -> [value, band]."""
    return {d: [s["value"], s["band"]] for d, s in belief["states"].items()}


def headline(belief: dict[str, Any]) -> dict[str, Any]:
    """One-line inferred summary; priorities follow decision relevance."""
    states = belief["states"]
    parts = []
    for dimension in ("pilot_status", "commercial_status", "procurement_status", "momentum"):
        s = states[dimension]
        if s["band"] and (dimension != "commercial_status" or s["value"] not in {"pricing_discussed"}):
            parts.append({"dimension": dimension, "value": s["value"], "band": s["band"],
                          "text": f"{DIMENSION_LABELS[dimension]}: {VALUE_LABELS.get(s['value'], s['value'])}"})
    if states["blocker_state"]["value"] == "active":
        s = states["blocker_state"]
        parts.append({"dimension": "blocker_state", "value": "active", "band": s["band"], "text": "Active blocker"})
    return {"parts": parts[:4], "text": " · ".join(f"{p['text']} ({p['band'].replace('_', ' ')})" for p in parts[:4])
            or "No inferred commercial state"}


__all__ = ["infer", "is_available", "compact", "headline", "MODES", "BANDS"]
