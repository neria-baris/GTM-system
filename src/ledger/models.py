"""Typed ledger records. None means unknown; it never implies false or zero."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import uuid4


def new_id() -> str:
    return str(uuid4())


EVENT_TYPES = frozenset({
    "initial_encounter", "follow_up_held", "scoping_held", "data_requested",
    "data_received", "pilot_verbal_yes", "sow_drafting", "sow_sent",
    "pilot_signed", "pilot_started", "technical_milestone", "blocker_opened",
    "blocker_resolved", "procurement_legal_started", "commercial_proposal_sent",
    "commercial_signed", "lost", "stalled", "revived",
})
VALUE_TYPES = frozenset({"pilot_fee", "rollout_acv", "tcv", "expansion_increment_acv",
                         "one_time_fee", "unknown_type"})


@dataclass(frozen=True)
class SourceRef:
    system: str
    object_type: str
    native_id: str


@dataclass(frozen=True)
class Account:
    id: str = field(default_factory=new_id)
    canonical_name: str = ""
    legal_entity_name: str | None = None
    parent_account_id: str | None = None
    industry: str | None = None
    source_refs: tuple[SourceRef, ...] = ()
    created_in_ledger_at: str = ""
    resolution_status: str = "provisional"


@dataclass(frozen=True)
class Contact:
    id: str = field(default_factory=new_id)
    display_name: str = ""
    normalized_email: str | None = None
    account_affiliations: tuple[dict[str, Any], ...] = ()
    title: str | None = None
    source_refs: tuple[SourceRef, ...] = ()
    created_in_ledger_at: str = ""
    resolution_status: str = "provisional"


@dataclass(frozen=True)
class CommercialScope:
    id: str = field(default_factory=new_id)
    scope_id: str = ""
    account_id: str = ""
    version: int = 1
    site_fab_region: str | None = None
    process_line_asset: str | None = None
    product_use_case: str = ""
    covered_units: str | None = None
    term: str | None = None
    boundary_text: str = ""
    exclusivity_group_id: str | None = None
    version_valid_from: str | None = None
    replaces_scope_version: int | None = None
    source_refs: tuple[SourceRef, ...] = ()
    created_in_ledger_at: str = ""
    resolution_status: str = "provisional"


@dataclass(frozen=True)
class Opportunity:
    id: str = field(default_factory=new_id)
    account_id: str = ""
    use_case_code: str = ""
    use_case_description: str = ""
    commercial_scope_id: str = ""
    scope_version: int = 1
    opportunity_group_id: str = ""
    relationship: str = "base"
    parent_opportunity_id: str | None = None
    lifecycle: str = "open"
    origin_evidence_id: str = ""
    source_refs: tuple[SourceRef, ...] = ()
    created_in_ledger_at: str = ""
    resolution_status: str = "provisional"


@dataclass(frozen=True)
class Meeting:
    id: str = field(default_factory=new_id)
    source_ref: SourceRef | None = None
    business_meeting_date: str | None = None
    recorded_at: str | None = None
    attendees: tuple[dict[str, Any], ...] = ()
    meeting_type: str | None = None
    linked_opportunity_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    source_refs: tuple[SourceRef, ...] = ()
    created_in_ledger_at: str = ""
    resolution_status: str = "provisional"


@dataclass(frozen=True)
class OfferOrContract:
    id: str = field(default_factory=new_id)
    opportunity_id: str = ""
    contract_kind: str = ""
    scope_id: str = ""
    status: str = "discussed"
    document_ref: str | None = None
    party_names: tuple[str, ...] = ()
    signature_date: str | None = None
    effective_date: str | None = None
    term_start: str | None = None
    term_end: str | None = None
    parent_contract_id: str | None = None
    source_refs: tuple[SourceRef, ...] = ()
    created_in_ledger_at: str = ""
    resolution_status: str = "provisional"


@dataclass(frozen=True)
class Evidence:
    evidence_id: str = field(default_factory=new_id)
    source_ref: SourceRef | None = None
    source_url: str | None = None
    source_version: str = ""
    source_hash: str = ""
    field_path: str | None = None
    block_id: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    verbatim_excerpt: str = ""
    document_author: str | None = None
    speaker: str | None = None
    authorship: str = "unknown"
    assertion_type: str = "firsthand_report"
    business_event_date: str | None = None
    documented_at: str | None = None
    source_first_seen_at: str | None = None
    ingested_at: str = ""
    date_precision: str = "unknown"
    derivation_rule: str = "fixture_v1"
    independence_group_id: str | None = None


@dataclass(frozen=True)
class Claim:
    claim_id: str = field(default_factory=new_id)
    subject_id: str = ""
    predicate: str = ""
    object_value: str | None = None
    polarity: str = "positive"
    contract_kind: str | None = None
    scope_id: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    evidence_ids: tuple[str, ...] = ()
    status: str = "observed"
    verification: str = "unverified"
    extraction_confidence: str = "high"
    resolution_reason: str | None = None
    supersedes_claim_id: str | None = None
    identity_resolution_version: str = "identity_v1"


@dataclass(frozen=True)
class Event:
    event_id: str = field(default_factory=new_id)
    event_type: str = ""
    account_id: str | None = None
    unresolved_entity_ref: str | None = None
    opportunity_id: str | None = None
    scope_id: str | None = None
    contract_kind: str | None = None
    event_date: str | None = None
    date_precision: str = "unknown"
    recorded_at: str | None = None
    first_seen_at: str | None = None
    evidence_ids: tuple[str, ...] = ()
    actor_speaker: str | None = None
    polarity: str = "positive"
    assertion: str = "explicit"
    confidence: str = "high"
    status: str = "observed"
    verification: str = "unverified"
    review_state: str = "unreviewed"
    extraction_version: str = "fixture_v1"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CommercialValue:
    value_id: str = field(default_factory=new_id)
    opportunity_id: str = ""
    offer_or_contract_id: str | None = None
    scope_id: str = ""
    scope_version: int = 1
    amount_decimal: Decimal = Decimal("0")
    currency_ISO: str = ""
    value_type: str = "unknown_type"
    status: str = "tentative"
    unit: str = "unknown"
    term_months: int | None = None
    effective_period: str | None = None
    valid_from: str | None = None
    date_observed: str | None = None
    source_evidence_ids: tuple[str, ...] = ()
    recorded_at: str | None = None
    first_seen_at: str | None = None
    fx_policy_id: str | None = None
    usd_normalized: Decimal | None = None
    replaces_value_id: str | None = None
    scenario_group_id: str | None = None
    confidence: str = "high"
    verification: str = "unverified"


@dataclass(frozen=True)
class Alias:
    alias_id: str = field(default_factory=new_id)
    raw_string: str = ""
    normalized_string: str = ""
    entity_type: str = ""
    canonical_id: str | None = None
    source_ref: SourceRef | None = None
    context_ids: tuple[str, ...] = ()
    valid_from: str | None = None
    valid_to: str | None = None
    match_method: str = ""
    match_confidence: str = "low"
    decision: str = "ambiguous"
    reviewer: str | None = None
    decision_at: str | None = None


@dataclass(frozen=True)
class Conflict:
    conflict_id: str = field(default_factory=new_id)
    claim_ids: tuple[str, ...] = ()
    issue: str = ""
    severity: str = "review"
    resolution: str | None = None
    resolution_evidence_id: str | None = None
    resolved_at: str | None = None
