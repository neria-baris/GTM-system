"""Atomic commercial signal and belief-state ontology.

Observed -> Inferred -> Verified. Signals are observations (or language-level
readings) anchored to exact evidence. Belief states are inferred from
combinations of signals over time. Verification stays in the existing
deterministic contract gate; no belief can set it.

All weights below are heuristic support points, not probabilities. See
docs/BELIEF_LAYER.md for their semantics.
"""
from __future__ import annotations

from dataclasses import dataclass

VERSION = "belief_1.0.0"

BANDS = ("low", "medium", "high", "very_high")
BAND_FACTOR = {"low": 0.5, "medium": 0.75, "high": 1.0, "very_high": 1.0}
MODALITIES = ("asserted", "completed", "planned", "conditional", "hypothetical", "negated", "unclear")
ACHIEVED = frozenset({"asserted", "completed"})
POLARITIES = ("positive", "negative")
OBSERVATIONS = ("observed", "inferred_from_language", "derived_pattern")
METHODS = ("deterministic_rule", "crm_field", "ledger_event", "luna_semantic", "jev_sensor",
           "cadence_rule", "verification_gate")
MODEL_METHODS = frozenset({"luna_semantic", "jev_sensor"})
CONTRACT_KINDS = ("pilot", "commercial", "amendment", "unknown")
STRENGTH = {"weak": 1, "moderate": 2, "strong": 3, "decisive": 4}

# Band thresholds over net support points (support minus opposition).
THRESHOLDS = {"very_high": 9.0, "high": 5.5, "medium": 3.0}
STALE_AFTER_DAYS = 90
RECENCY = ((30, 1.0), (60, 0.6), (120, 0.3))
RECENCY_FLOOR = 0.1
EARLIER_OPPOSITION_FACTOR = 0.3
INACTIVITY_STALL_DAYS = 45  # Aligned with the existing Model B stalled-by-rule threshold.


@dataclass(frozen=True)
class SignalType:
    category: str
    persistence: str  # persistent | decaying | until_resolved
    strength: str
    label: str


SIGNAL_TYPES: dict[str, SignalType] = {
    # Engagement
    "customer_interest": SignalType("engagement", "decaying", "weak", "Customer expressed interest"),
    "meeting_held": SignalType("engagement", "decaying", "weak", "Meeting held"),
    "senior_stakeholder_engaged": SignalType("engagement", "persistent", "moderate", "Senior stakeholder engaged"),
    "recurring_interaction": SignalType("engagement", "decaying", "moderate", "Recurring interaction cadence"),
    # Commitment
    "positive_intent": SignalType("commitment", "decaying", "moderate", "Explicit positive intent"),
    "verbal_commitment": SignalType("commitment", "persistent", "strong", "Verbal commitment"),
    # Technical
    "data_requested": SignalType("technical", "persistent", "weak", "Data requested"),
    "data_received": SignalType("technical", "persistent", "strong", "Customer data received"),
    "technical_owner_assigned": SignalType("technical", "persistent", "moderate", "Customer technical owner assigned"),
    "customer_resources_allocated": SignalType("technical", "persistent", "moderate", "Customer resources allocated"),
    "technical_result_positive": SignalType("technical", "persistent", "moderate", "Positive technical result"),
    # Pilot
    "pilot_scope_discussed": SignalType("pilot", "persistent", "weak", "Pilot scope discussed"),
    "pilot_scope_agreed": SignalType("pilot", "persistent", "moderate", "Pilot scope agreed"),
    "kickoff_scheduled": SignalType("pilot", "persistent", "moderate", "Pilot kickoff scheduled / planned"),
    "kickoff_completed": SignalType("pilot", "persistent", "strong", "Pilot kickoff completed"),
    "pilot_work_underway": SignalType("pilot", "persistent", "strong", "Pilot work underway"),
    "pilot_completed": SignalType("pilot", "persistent", "strong", "Pilot completed"),
    # Commercial
    "pricing_discussed": SignalType("commercial", "persistent", "weak", "Pricing discussed"),
    "budget_discussed": SignalType("commercial", "persistent", "weak", "Budget discussed"),
    "budget_confirmed": SignalType("commercial", "persistent", "strong", "Budget confirmed"),
    "commercial_terms_discussed": SignalType("commercial", "persistent", "moderate", "Commercial terms discussed"),
    "commercial_terms_agreed": SignalType("commercial", "persistent", "strong", "Commercial terms agreed"),
    "reported_signature": SignalType("commercial", "persistent", "strong", "Signature reported (unverified)"),
    "formal_signature_verified": SignalType("commercial", "persistent", "decisive", "Signature formally verified"),
    # Procurement
    "procurement_mentioned": SignalType("procurement", "persistent", "weak", "Procurement mentioned"),
    "procurement_started": SignalType("procurement", "persistent", "strong", "Procurement started"),
    "legal_involved": SignalType("procurement", "persistent", "moderate", "Legal involved"),
    "security_review_started": SignalType("procurement", "persistent", "moderate", "Security review started"),
    # Risk
    "blocker_identified": SignalType("risk", "until_resolved", "moderate", "Blocker identified"),
    "budget_blocker": SignalType("risk", "until_resolved", "strong", "Budget blocker"),
    "technical_blocker": SignalType("risk", "until_resolved", "moderate", "Technical blocker"),
    "legal_blocker": SignalType("risk", "until_resolved", "moderate", "Legal / security / procurement blocker"),
    "blocker_resolved": SignalType("risk", "persistent", "moderate", "Blocker resolved"),
    "loss_of_momentum": SignalType("risk", "decaying", "moderate", "Loss of momentum"),
    "no_response": SignalType("risk", "decaying", "moderate", "No response from customer"),
    "explicit_rejection": SignalType("risk", "persistent", "decisive", "Explicit rejection / closed"),
    "project_paused": SignalType("risk", "until_resolved", "strong", "Project paused"),
    "revived": SignalType("risk", "persistent", "moderate", "Re-engaged after pause or stall"),
}

BLOCKER_TYPES = frozenset({"blocker_identified", "budget_blocker", "technical_blocker", "legal_blocker"})
DERIVED_TYPES = frozenset({"recurring_interaction"})
# Types an extractor may emit. Formal verification is produced only by the gate,
# and cadence only by the engine at evaluation time.
EXTRACTABLE_TYPES = tuple(t for t in SIGNAL_TYPES if t not in DERIVED_TYPES | {"formal_signature_verified"})

# A planned statement about execution is re-typed to its planning counterpart;
# a negated or conditional one never supports an achieved state.
PLANNED_COUNTERPART = {
    "kickoff_completed": "kickoff_scheduled", "pilot_work_underway": "kickoff_scheduled",
    "data_received": "data_requested", "pilot_scope_agreed": "pilot_scope_discussed",
    "commercial_terms_agreed": "commercial_terms_discussed", "budget_confirmed": "budget_discussed",
    "procurement_started": "procurement_mentioned", "verbal_commitment": "positive_intent",
    "reported_signature": "commercial_terms_discussed", "pilot_completed": "pilot_work_underway",
}
# Conditional/hypothetical statements may only show that a topic was raised.
SPECULATIVE_COUNTERPART = {
    "verbal_commitment": "customer_interest", "positive_intent": "customer_interest",
    "reported_signature": "pricing_discussed", "commercial_terms_agreed": "pricing_discussed",
    "commercial_terms_discussed": "pricing_discussed", "budget_confirmed": "budget_discussed",
    "kickoff_completed": "pilot_scope_discussed", "pilot_work_underway": "pilot_scope_discussed",
    "kickoff_scheduled": "pilot_scope_discussed", "pilot_scope_agreed": "pilot_scope_discussed",
    "procurement_started": "procurement_mentioned",
}

DIMENSIONS: dict[str, tuple[str, ...]] = {
    "engagement": ("unknown", "light", "active", "strong"),
    "buyer_commitment": ("unknown", "interest", "intent", "verbal_commitment", "committed", "withdrawn"),
    "technical_commitment": ("unknown", "exploring", "resourced", "engaged"),
    "pilot_status": ("unknown", "discussed", "planned", "committed", "active", "completed", "paused", "cancelled"),
    "procurement_status": ("unknown", "anticipated", "underway"),
    "commercial_status": ("unknown", "pricing_discussed", "terms_negotiation", "terms_agreed",
                          "reported_signed", "verified_signed"),
    "blocker_state": ("none_known", "possible", "active", "resolved"),
    "momentum": ("unknown", "strong", "steady", "weakening", "stalled", "lost"),
}
DECISION_RELEVANT = ("pilot_status", "commercial_status", "procurement_status", "buyer_commitment")


@dataclass(frozen=True)
class ValueRule:
    """Support table for one state value.

    `support` maps a signal key to strength points. A key is `type` or
    `type@kind`; `@kind` matches the signal's contract kind exactly, and an
    unknown contract kind matches at half strength.
    `gate`: at least one of these keys must support the value.
    `opposed_by`: signal keys whose later occurrence argues against the value.
    `current`: a current-state claim, capped when its evidence is stale.
    `missing_hint`: expected evidence whose absence is reported (not penalised).
    """
    support: dict[str, float]
    gate: tuple[str, ...]
    opposed_by: dict[str, float]
    current: bool = False
    missing_hint: tuple[tuple[str, str], ...] = ()


REVERSALS = {"explicit_rejection": 4.0, "project_paused": 3.0, "budget_blocker": 2.0}

RULES: dict[str, dict[str, ValueRule]] = {
    "pilot_status": {
        "discussed": ValueRule({"pilot_scope_discussed": 2, "pricing_discussed@pilot": 1, "budget_discussed": 1,
                                "data_requested": 1, "customer_interest": 0.5},
                               ("pilot_scope_discussed", "pricing_discussed@pilot", "data_requested"), {}),
        "planned": ValueRule({"kickoff_scheduled": 3, "pilot_scope_agreed": 2, "data_requested": 1,
                              "pilot_scope_discussed": 1},
                             ("kickoff_scheduled", "pilot_scope_agreed"), {"explicit_rejection": 4, "project_paused": 2}),
        "committed": ValueRule({"verbal_commitment@pilot": 3, "reported_signature@pilot": 4, "pilot_scope_agreed": 2,
                                "budget_confirmed": 2, "customer_resources_allocated": 1, "pricing_discussed@pilot": 1},
                               ("verbal_commitment@pilot", "reported_signature@pilot", "budget_confirmed"),
                               {"explicit_rejection": 4, "project_paused": 2, "budget_blocker": 2},
                               missing_hint=(("reported_signature@pilot", "No signed pilot agreement or SOW in the evidence"),)),
        "active": ValueRule({"kickoff_completed": 3, "pilot_work_underway": 4, "data_received": 2,
                             "recurring_interaction": 2, "technical_owner_assigned": 1,
                             "customer_resources_allocated": 1, "technical_result_positive": 1},
                            ("kickoff_completed", "pilot_work_underway", "data_received"),
                            {"explicit_rejection": 4, "project_paused": 3, "no_response": 1, "loss_of_momentum": 1},
                            current=True,
                            missing_hint=(("reported_signature@pilot", "No signed pilot agreement or SOW in the evidence"),)),
        "completed": ValueRule({"pilot_completed": 4, "technical_result_positive": 2},
                               ("pilot_completed",), {}),
        "paused": ValueRule({"project_paused": 3, "budget_blocker": 1, "loss_of_momentum": 1, "no_response": 1},
                            ("project_paused",), {"revived": 3}, current=True),
        "cancelled": ValueRule({"explicit_rejection": 4}, ("explicit_rejection",), {"revived": 3}),
    },
    "buyer_commitment": {
        "interest": ValueRule({"customer_interest": 2, "meeting_held": 1, "positive_intent": 1},
                              ("customer_interest", "meeting_held", "positive_intent"), {}),
        "intent": ValueRule({"positive_intent": 3, "pilot_scope_discussed": 1, "data_requested": 1, "budget_discussed": 1,
                             "senior_stakeholder_engaged": 1},
                            ("positive_intent",), {"explicit_rejection": 4, "loss_of_momentum": 1}),
        "verbal_commitment": ValueRule({"verbal_commitment": 4, "kickoff_scheduled": 1, "pilot_scope_agreed": 1,
                                        "senior_stakeholder_engaged": 1},
                                       ("verbal_commitment",), dict(REVERSALS)),
        "committed": ValueRule({"reported_signature": 4, "budget_confirmed": 3, "commercial_terms_agreed": 3,
                                "customer_resources_allocated": 2, "data_received": 1, "kickoff_completed": 1,
                                "verbal_commitment": 1},
                               ("reported_signature", "budget_confirmed", "commercial_terms_agreed",
                                "customer_resources_allocated"), dict(REVERSALS)),
        "withdrawn": ValueRule({"explicit_rejection": 4, "budget_blocker": 2, "project_paused": 2},
                               ("explicit_rejection", "budget_blocker", "project_paused"), {"revived": 3}, current=True),
    },
    "technical_commitment": {
        "exploring": ValueRule({"data_requested": 2, "pilot_scope_discussed": 1, "meeting_held": 1},
                               ("data_requested", "pilot_scope_discussed"), {}),
        "resourced": ValueRule({"technical_owner_assigned": 3, "customer_resources_allocated": 3, "data_received": 2},
                               ("technical_owner_assigned", "customer_resources_allocated", "data_received"),
                               {"technical_blocker": 1, "explicit_rejection": 3}),
        "engaged": ValueRule({"recurring_interaction": 3, "pilot_work_underway": 3, "kickoff_completed": 2,
                              "data_received": 2, "technical_result_positive": 2, "technical_owner_assigned": 1},
                             ("recurring_interaction", "pilot_work_underway", "technical_result_positive"),
                             {"technical_blocker": 2, "no_response": 1, "explicit_rejection": 3}, current=True),
    },
    "procurement_status": {
        "anticipated": ValueRule({"procurement_mentioned": 2, "budget_discussed": 1, "legal_involved": 1},
                                 ("procurement_mentioned",), {}),
        "underway": ValueRule({"procurement_started": 4, "legal_involved": 2, "security_review_started": 2,
                               "commercial_terms_discussed": 1, "procurement_mentioned": 1},
                              ("procurement_started", "legal_involved", "security_review_started"),
                              {"explicit_rejection": 4, "legal_blocker": 1}, current=True),
    },
    "commercial_status": {
        "pricing_discussed": ValueRule({"pricing_discussed": 2, "budget_discussed": 1},
                                       ("pricing_discussed", "budget_discussed"), {}),
        "terms_negotiation": ValueRule({"commercial_terms_discussed@commercial": 3, "procurement_started": 2,
                                        "legal_involved": 1, "security_review_started": 1, "procurement_mentioned": 1,
                                        "pricing_discussed@commercial": 1},
                                       ("commercial_terms_discussed@commercial", "procurement_started", "legal_involved"),
                                       {"explicit_rejection": 4, "budget_blocker": 2}),
        "terms_agreed": ValueRule({"commercial_terms_agreed@commercial": 4, "budget_confirmed@commercial": 2,
                                   "verbal_commitment@commercial": 2},
                                  ("commercial_terms_agreed@commercial",),
                                  {"explicit_rejection": 4, "budget_blocker": 3, "legal_blocker": 1}),
        # A coherent chain (results -> decision to go commercial -> ACV discussed -> signed) corroborates the report.
        "reported_signed": ValueRule({"reported_signature@commercial": 4, "commercial_terms_agreed@commercial": 1,
                                      "procurement_started": 1, "verbal_commitment@commercial": 1,
                                      "commercial_terms_discussed@commercial": 1, "technical_result_positive": 1,
                                      "senior_stakeholder_engaged": 0.5},
                                     ("reported_signature@commercial",), {"explicit_rejection": 4},
                                     missing_hint=(("formal_signature_verified", "No documentary contract verification"),)),
        "verified_signed": ValueRule({"formal_signature_verified": 4}, ("formal_signature_verified",), {}),
    },
}
PROGRESSIONS = {
    "pilot_status": ("discussed", "planned", "committed", "active", "completed"),
    "buyer_commitment": ("interest", "intent", "verbal_commitment", "committed"),
    "technical_commitment": ("exploring", "resourced", "engaged"),
    "procurement_status": ("anticipated", "underway"),
    "commercial_status": ("pricing_discussed", "terms_negotiation", "terms_agreed", "reported_signed", "verified_signed"),
}
REVERSAL_VALUES = {"pilot_status": ("paused", "cancelled"), "buyer_commitment": ("withdrawn",)}

VALUE_LABELS = {
    "unknown": "Unknown", "none_known": "None known", "light": "Light", "active": "Active", "strong": "Strong",
    "interest": "Interest", "intent": "Positive intent", "verbal_commitment": "Verbal commitment",
    "committed": "Committed", "withdrawn": "Withdrawn", "exploring": "Exploring", "resourced": "Resourced",
    "engaged": "Engaged", "discussed": "Discussed", "planned": "Planned", "completed": "Completed",
    "paused": "Paused", "cancelled": "Cancelled", "anticipated": "Anticipated", "underway": "Underway",
    "pricing_discussed": "Pricing discussed", "terms_negotiation": "Terms in negotiation",
    "terms_agreed": "Terms agreed", "reported_signed": "Signature reported (unverified)",
    "verified_signed": "Signature verified", "possible": "Possible", "resolved": "Resolved",
    "steady": "Steady", "weakening": "Weakening", "stalled": "Stalled", "lost": "Lost",
}
DIMENSION_LABELS = {
    "engagement": "Engagement", "buyer_commitment": "Buyer commitment",
    "technical_commitment": "Technical commitment", "pilot_status": "Pilot status",
    "procurement_status": "Procurement", "commercial_status": "Commercial status",
    "blocker_state": "Blockers", "momentum": "Momentum",
}

CONFIDENCE_SEMANTICS = (
    "Bands summarise heuristic support points: strength of each supporting signal x its extraction "
    "confidence x recency x independence, minus later contradicting evidence. They are ordinal labels, "
    "not calibrated probabilities. Several distinct signal types are required for high or very high; "
    "contradictions and evidence older than 90 days lower the band."
)


def band_rank(band: str | None) -> int:
    return BANDS.index(band) if band in BANDS else -1


def shift_band(band: str, steps: int) -> str:
    return BANDS[max(0, min(len(BANDS) - 1, BANDS.index(band) + steps))]


def ontology_summary() -> dict:
    """Machine-readable ontology published with the presentation contract."""
    return {"version": VERSION, "bands": list(BANDS), "modalities": list(MODALITIES),
            "observations": list(OBSERVATIONS), "methods": list(METHODS),
            "signal_types": {k: {"category": v.category, "persistence": v.persistence,
                                 "strength": v.strength, "label": v.label} for k, v in SIGNAL_TYPES.items()},
            "dimensions": {k: list(v) for k, v in DIMENSIONS.items()},
            "dimension_labels": DIMENSION_LABELS, "value_labels": VALUE_LABELS,
            "confidence_semantics": CONFIDENCE_SEMANTICS}
