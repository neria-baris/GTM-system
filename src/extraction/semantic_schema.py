"""Closed, strict response contract for the C2 semantic bridge."""
from __future__ import annotations

from src.belief.ontology import EXTRACTABLE_TYPES, MODALITIES

SCHEMA_VERSION = "semantic_bridge_1.2.0"

EVENT_TYPES = (
    "initial_encounter", "follow_up_held", "scoping_held", "data_requested",
    "data_received", "pilot_verbal_yes", "sow_drafting", "sow_sent",
    "pilot_signed", "pilot_started", "technical_milestone", "blocker_opened",
    "blocker_resolved", "procurement_legal_started", "commercial_proposal_sent",
    "commercial_signed", "lost", "stalled", "revived",
)
POLARITIES = ("asserted", "negated", "hypothetical", "future_plan", "conditional", "unclear")
VALUE_TYPES = ("pilot_fee", "rollout_acv", "tcv", "expansion_increment_acv", "one_time_fee", "unknown_type")
VALUE_STATUSES = ("tentative", "discussed", "proposed", "signed_reported", "retracted", "unknown")
SIGNAL_FAMILIES = (
    "customer_commitment", "next_step_strength", "buyer_involvement", "procurement_legal",
    "blocker", "data_access", "technical_progress", "pilot_progress",
    "commercial_negotiation", "momentum",
)
CONTRACT_KINDS = ("pilot", "commercial", "amendment", "unknown")
SIGNAL_TYPES = tuple(EXTRACTABLE_TYPES)
SIGNAL_MODALITIES = tuple(MODALITIES)
ACTORS = ("customer", "seller", "third_party", "unknown")


def _nullable_string() -> dict:
    return {"type": ["string", "null"]}


def _item(extra: dict[str, dict]) -> dict:
    properties = {
        "quote": {"type": "string"},
        "account_candidate_id": _nullable_string(), "opportunity_candidate_id": _nullable_string(),
    }
    properties.update(extra)
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


SEMANTIC_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "account_links": {"type": "array", "items": _item({"relation": {"type": "string"}})},
        "contact_links": {"type": "array", "items": _item({"contact_candidate_id": _nullable_string(), "relation": {"type": "string"}})},
        "opportunity_candidates": {"type": "array", "items": _item({
            "use_case": {"type": "string"}, "commercial_scope": {"type": "string"},
            "relationship": {"type": "string", "enum": ["base", "expansion", "alternative", "conditional", "unresolved"]},
        })},
        "events": {"type": "array", "items": _item({
            "event_type": {"type": "string", "enum": list(EVENT_TYPES)},
            "polarity": {"type": "string", "enum": list(POLARITIES)},
            "event_date": _nullable_string(), "contract_kind": {"type": "string", "enum": list(CONTRACT_KINDS)},
        })},
        "commercial_values": {"type": "array", "items": _item({
            "amount": {"type": ["number", "null"]}, "currency": _nullable_string(),
            "unit": _nullable_string(), "value_type": {"type": "string", "enum": list(VALUE_TYPES)},
            "status": {"type": "string", "enum": list(VALUE_STATUSES)},
            "contract_kind": {"type": "string", "enum": list(CONTRACT_KINDS)},
            "scenario_relation": _nullable_string(),
        })},
        "signals": {"type": "array", "items": _item({
            "family": {"type": "string", "enum": list(SIGNAL_FAMILIES)},
            "value": {"type": "string"}, "polarity": {"type": "string", "enum": list(POLARITIES)},
        })},
        "atomic_signals": {"type": "array", "items": _item({
            "signal_type": {"type": "string", "enum": list(SIGNAL_TYPES)},
            "modality": {"type": "string", "enum": list(SIGNAL_MODALITIES)},
            "effective_date": _nullable_string(),
            "actor": {"type": "string", "enum": list(ACTORS)},
            "contract_kind": {"type": "string", "enum": list(CONTRACT_KINDS)},
        })},
        "relations": {"type": "array", "items": _item({
            "subject": {"type": "string"}, "predicate": {"type": "string"}, "object": {"type": "string"},
        })},
        "abstentions": {"type": "array", "items": _item({"reason": {"type": "string"}})},
    },
    "required": ["account_links", "contact_links", "opportunity_candidates", "events",
                 "commercial_values", "signals", "atomic_signals", "relations", "abstentions"],
}

COLLECTIONS = tuple(SEMANTIC_SCHEMA["properties"])
