"""Jev as a narrow sensor over one cited span.

Each question is closed and local to the quote. A reading can move one signal
by at most one confidence band or re-type it to a weaker modality. It never
creates a state on its own and never sets verification.
"""
from __future__ import annotations

from typing import Any, Callable

from src.extraction.jev_adapter import choice_question

from .ontology import shift_band
from .signals import normalise, validate_signal

SENSOR_VERSION = "jev_sensor_1.0.0"
SENSORS: dict[str, tuple[str, dict[str, str]]] = {
    "statement_modality": (
        "Read only the quoted text. Is the statement a current fact, a completed past fact, a plan for the future, "
        "conditional on something else, hypothetical, or negated? A plan or condition is not a completed action.",
        {"current": "Current fact", "completed": "Completed past fact", "planned": "Future plan or intention",
         "conditional": "Depends on a condition (if/once/subject to)", "hypothetical": "Possibility or speculation",
         "negated": "Explicitly did not happen / is not the case", "unclear": "Cannot tell from the quote"}),
    "pilot_activity": (
        "Does the quote show a pilot actively being executed now, only planned or prepared, completed, paused or "
        "cancelled, or none of these? Preparation, scoping and SOW drafting are not execution.",
        {"active": "Pilot is being executed", "planned": "Pilot planned or being prepared", "completed": "Pilot finished",
         "paused_or_cancelled": "Pilot paused or cancelled", "unclear": "No supported pilot activity"}),
    "customer_commitment": (
        "Does the customer explicitly commit to a next commercial step in this quote? Interest, enthusiasm or a "
        "seller plan is not commitment; a conditional promise is not commitment.",
        {"explicit_commitment": "Customer explicitly commits", "intent_only": "Positive intent without commitment",
         "interest_only": "Interest only", "conditional": "Commitment depends on a condition", "none": "No commitment",
         "unclear": "Cannot tell"}),
    "procurement_started": (
        "Has the customer's procurement, purchasing, legal or security process probably started for this deal? "
        "Mentioning that procurement will be needed is not starting it.",
        {"underway": "Process has started", "anticipated": "Mentioned as a future step", "not_started": "Explicitly not started",
         "unclear": "Cannot tell"}),
    "real_blocker": (
        "Is this quote a real, current blocker to the deal, a resolved blocker, only a risk or concern, or not a blocker?",
        {"active_blocker": "Current blocker", "resolved": "Blocker resolved", "risk_only": "Risk or concern, not blocking",
         "not_a_blocker": "Not a blocker", "unclear": "Cannot tell"}),
}
ROUTES = {
    "statement_modality": {"kickoff_completed", "pilot_work_underway", "verbal_commitment", "commercial_terms_agreed",
                           "budget_confirmed", "data_received", "procurement_started", "reported_signature"},
    "pilot_activity": {"kickoff_completed", "pilot_work_underway", "kickoff_scheduled", "pilot_completed"},
    "customer_commitment": {"verbal_commitment", "positive_intent", "budget_confirmed", "commercial_terms_agreed"},
    "procurement_started": {"procurement_started", "procurement_mentioned", "legal_involved", "security_review_started"},
    "real_blocker": {"blocker_identified", "budget_blocker", "technical_blocker", "legal_blocker"},
}
MODALITY_FROM_SENSOR = {"current": "asserted", "completed": "completed", "planned": "planned",
                        "conditional": "conditional", "hypothetical": "hypothetical", "negated": "negated"}


def questions_for(signal_type: str) -> dict[str, Any]:
    return {name: choice_question(*SENSORS[name]) for name, types in ROUTES.items() if signal_type in types}


def readings(batch: dict[str, Any]) -> list[dict[str, Any]]:
    """Stable, traceable readings from one K-repeat Jev batch; failures yield nothing."""
    out = []
    for question, agg in (batch.get("aggregate") or {}).items():
        if agg.get("type") != "choice":
            continue
        choice = agg["aggregate_choice"]
        p, agreement = agg["mean_probabilities"][choice], agg["top_choice_agreement_rate"]
        band = "high" if agreement == 1.0 and p >= 0.9 else "medium" if agreement >= 0.8 and p >= 0.7 else "low"
        out.append({"sensor": question, "choice": choice, "reading_band": band, "agreement": agreement,
                    "mean_probability": round(p, 4), "k": batch.get("successful_k"),
                    "resolved_models": sorted({r.get("resolved_model") for r in batch.get("runs", []) if r.get("resolved_model")}),
                    "sensor_version": SENSOR_VERSION})
    return out


def apply(signal: dict[str, Any], sensor_readings: list[dict[str, Any]]) -> dict[str, Any]:
    """Adjust one signal by at most one band; modality can only become weaker."""
    s = {**signal, "details": dict(signal.get("details") or {}),
         "sensor_readings": list(signal.get("sensor_readings") or []) + sensor_readings}
    original = s["details"].get("retyped_from") or s["signal_type"]
    for r in sensor_readings:
        if r["reading_band"] == "low" or r["choice"] == "unclear":
            continue
        if r["sensor"] == "statement_modality":
            modality = MODALITY_FROM_SENSOR.get(r["choice"])
            if modality in {"planned", "conditional", "hypothetical", "negated"} and s["modality"] in {"asserted", "completed"}:
                s = normalise({**s, "signal_type": original, "modality": modality})
                s["details"]["modality_source"] = "jev_sensor"
            elif modality in {"asserted", "completed"}:
                s["signal_confidence"] = shift_band(s["signal_confidence"], +1 if r["reading_band"] == "high" else 0)
        elif r["sensor"] == "pilot_activity":
            if r["choice"] == "planned" and s["signal_type"] in {"kickoff_completed", "pilot_work_underway"}:
                s = normalise({**s, "modality": "planned"})
            elif r["choice"] == "active" and s["signal_type"] in {"kickoff_completed", "pilot_work_underway"}:
                s["signal_confidence"] = shift_band(s["signal_confidence"], +1)
        elif r["sensor"] == "customer_commitment":
            if r["choice"] == "conditional":
                s = normalise({**s, "modality": "conditional"})
            elif r["choice"] in {"interest_only", "none"} and s["signal_type"] == "verbal_commitment":
                s["signal_confidence"] = shift_band(s["signal_confidence"], -1)
            elif r["choice"] == "explicit_commitment":
                s["signal_confidence"] = shift_band(s["signal_confidence"], +1)
        elif r["sensor"] == "procurement_started":
            if r["choice"] == "anticipated" and s["signal_type"] == "procurement_started":
                s = normalise({**s, "modality": "planned"})
            elif r["choice"] == "underway":
                s["signal_confidence"] = shift_band(s["signal_confidence"], +1)
        elif r["sensor"] == "real_blocker":
            if r["choice"] in {"risk_only", "not_a_blocker"}:
                s["signal_confidence"] = shift_band(s["signal_confidence"], -1)
            elif r["choice"] == "resolved":
                s["details"]["sensor_says_resolved"] = True
    if s["signal_confidence"] == "very_high" and s["extraction_method"] != "verification_gate":
        s["signal_confidence"] = "high"
    return validate_signal(s)


def sense(signal: dict[str, Any], quote: str, k: int,
          run: Callable[[str, dict[str, Any], int], dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Run the routed sensor questions for one signal's quote and apply the readings."""
    q = questions_for(signal["signal_type"])
    if not q or not quote:
        return signal, None
    batch = run(quote, q, k)
    return apply(signal, readings(batch)), {"signal_id": signal["signal_id"], "questions": list(q), **batch}
