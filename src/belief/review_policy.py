"""Decision-impact triage of review items.

Every existing review item is retained for audit; triage only decides whether a
human decision is needed. Soft evidence alone never requires review.
"""
from __future__ import annotations

import re
from typing import Any

from src.ledger.store import stable_id

from .ontology import DECISION_RELEVANT, DIMENSION_LABELS, VALUE_LABELS, band_rank

CONTRACT = re.compile(r"reported_signature|commercial_signature|signature_identity|pilot_signature|"
                      r"crm_stage_exception|signed_acv|contract_identity|contract_documentary|signature_date|"
                      r"signed_amount|reported_commercial", re.I)
VALUE_CONFLICT = re.compile(r"conflicting_or_exclusive_values|exclusivity_group_ambiguous|semantic_high_impact", re.I)
IDENTITY = re.compile(r"ambiguous_scope_or_identity|material_identity_or_scope|provisional_scope_requires_identity_review", re.I)
EXTRACTION_QA = re.compile(r"^rejected_semantic_proposal:|llm_relation_needs_review|jev_verification_failed", re.I)
NOW_A_SIGNAL = re.compile(r"required_event_details_not_extracted|pilot_scope_unresolved|procurement_domain_unresolved", re.I)


def triage(item: dict[str, Any], *, accounts_with_multiple_scopes: set[str],
           account_of: dict[str, str]) -> dict[str, Any]:
    reason = item.get("reason") or item.get("issue") or ""
    oid = item.get("opportunity_id")
    if CONTRACT.search(reason):
        return _t(True, "contract_verification", "Contract or signature status affects recognised value")
    if VALUE_CONFLICT.search(reason) and oid:
        return _t(True, "material_value_conflict", "Conflicting commercial values for a displayed opportunity")
    if IDENTITY.search(reason):
        if oid and account_of.get(oid) in accounts_with_multiple_scopes:
            return _t(True, "identity_structure", "Several provisional scopes for one account; the split changes opportunity structure")
        return _t(False, "identity_single_scope", "Single provisional scope; identity is retained as provisional, not blocking")
    if EXTRACTION_QA.search(reason):
        return _t(False, "extraction_quality_log", "Rejected or unverified model proposal; kept as an extraction audit record")
    if NOW_A_SIGNAL.search(reason):
        return _t(False, "used_as_soft_signal", "Statement is now used as an atomic signal; missing typed details do not block inference")
    if VALUE_CONFLICT.search(reason):
        return _t(False, "unlinked_value_annotation", "Unlinked high-impact proposal outside the displayed population")
    if not oid:
        return _t(False, "unlinked_annotation", "Not linked to a displayed opportunity; no decision changes the tracked state")
    return _t(False, "low_decision_impact", "Retained as annotation; no material state or value depends on it")


def _t(needed: bool, category: str, rationale: str) -> dict[str, Any]:
    return {"decision_needed": needed, "category": category, "rationale": rationale}


def belief_review_items(oid: str, belief: dict[str, Any]) -> list[dict[str, Any]]:
    """Review only important contradictions or genuinely ambiguous decision-relevant states."""
    items = []
    states = belief["states"]
    for dimension in DECISION_RELEVANT:
        s = states[dimension]
        if not s["band"]:
            continue
        support = sorted({e for x in s["supporting"] for e in x["evidence_ids"]})
        against = sorted({e for x in s["contradicting"] for e in x["evidence_ids"]})
        if s["contested"] and band_rank(s["band"]) <= band_rank("medium") and against:
            items.append(_item(oid, dimension, "belief_material_contradiction",
                               f"{DIMENSION_LABELS[dimension]} is contested: decide whether the later evidence reverses "
                               f"'{VALUE_LABELS.get(s['value'], s['value'])}'", support + against))
            continue
        rivals = [a for a in s.get("alternatives", []) if band_rank(a["band"]) >= band_rank(s["band"])
                  and band_rank(a["band"]) >= band_rank("medium") and _conflicting(dimension, s["value"], a["value"])]
        if rivals:
            items.append(_item(oid, dimension, "belief_ambiguous_state",
                               f"{DIMENSION_LABELS[dimension]} is ambiguous between "
                               f"'{VALUE_LABELS.get(s['value'], s['value'])}' and "
                               f"'{VALUE_LABELS.get(rivals[0]['value'], rivals[0]['value'])}'", support + against))
    return items


def _conflicting(dimension: str, a: str, b: str) -> bool:
    """Adjacent progression steps are compatible; progression vs reversal is not."""
    reversal = {"paused", "cancelled", "withdrawn"}
    return (a in reversal) != (b in reversal)


def _item(oid: str, dimension: str, reason: str, action: str, evidence_ids: list[str]) -> dict[str, Any]:
    return {"review_id": stable_id("belief_review", f"{oid}:{dimension}:{reason}"), "opportunity_id": oid,
            "issue": reason, "reason": reason, "dimension": dimension, "evidence_ids": evidence_ids,
            "financial_materiality_usd": None, "required_action": action, "status": "open",
            "origin": "belief_engine"}
