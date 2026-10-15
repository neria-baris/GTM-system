"""Provider-neutral source to ledger bridge. Discovery layout is never business truth."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from src.ledger.models import Claim, Event, Evidence, SourceRef
from src.ledger.store import Ledger, stable_id
from src.connectors.common import stable_provider_content

VERSION = "integration_1.0.0"
SIGNAL_FIELDS = {"customer_commitment", "next_step_strength", "buyer_involvement",
                 "procurement_legal", "blocker", "data_access", "technical_progress",
                 "pilot_progress", "commercial_negotiation", "momentum"}
TRANSPORT_KEYS = {"retrieval_provenance", "createdTime", "created_time", "last_edited_time",
                  "last_edited_by", "created_by", "parent", "base_id", "table_id", "query_row"}


def _leaves(value: Any, path: str = "content") -> Iterable[tuple[str, str]]:
    """Return source text leaves with stable paths; no schema or table assumptions."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key not in TRANSPORT_KEYS:
                yield from _leaves(child, f"{path}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _leaves(child, f"{path}/{index}")
    elif isinstance(value, str) and value.strip():
        yield path, value


def ingest_envelopes(ledger: Ledger, manifest: dict[str, Any] | str | Path,
                     root: str | Path, *, subject_by_source: dict[tuple[str, str], str] | None = None
                     ) -> list[str]:
    """Ingest immutable A2 snapshots and exact text evidence, with explicit identity bindings.

    A2 retrieval time is first-seen time only. Business and documentation dates
    remain unknown until a field-specific extraction supplies evidence for them.
    """
    if isinstance(manifest, (str, Path)):
        manifest = json.loads(Path(manifest).read_text(encoding="utf-8"))
    root = Path(root).resolve()
    bindings = subject_by_source or {}
    made: list[str] = []
    for env in manifest["envelopes"]:
        candidate = (root / env["raw_snapshot_path"]).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise ValueError("Snapshot path is absent or outside repository")
        snapshot = json.loads(candidate.read_text(encoding="utf-8"))
        content = snapshot["content"]
        # A2 hashes stable provider content, excluding retrieval metadata.
        canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        stable = json.dumps(stable_provider_content(env["provider"], content), ensure_ascii=False,
                            sort_keys=True, separators=(",", ":"))
        if hashlib.sha256(stable.encode("utf-8")).hexdigest() != env["content_hash"]:
            raise ValueError("Envelope content hash mismatch")
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        ref = SourceRef(env["provider"], env["native_object_type"], env["native_id"])
        seen = env["retrieved_at"]
        ledger.ingest_raw(ref, digest, canonical, seen, seen)
        for field_path, exact in _leaves(content):
            # The raw ledger row is canonical JSON; a JSON pointer plus the
            # encoded source substring remains exact even for quotes/newlines.
            encoded = json.dumps(exact, ensure_ascii=False)[1:-1]
            start = canonical.find(encoded)
            if start < 0:
                raise ValueError("Text leaf absent from immutable snapshot")
            ev = Evidence(evidence_id=stable_id("evidence", f"{ref}:{digest}:{field_path}"),
                          source_ref=ref, source_version=digest, source_hash=digest,
                          field_path=field_path, start_offset=start, end_offset=start + len(encoded),
                          verbatim_excerpt=encoded, source_first_seen_at=seen, ingested_at=seen,
                          documented_at=None, business_event_date=None, date_precision="unknown",
                          derivation_rule=VERSION, assertion_type="crm_snapshot" if ref.system == "airtable" else "firsthand_report",
                          independence_group_id=f"{ref.system}:{ref.object_type}:{ref.native_id}")
            ledger.add_evidence(ev)
            made.append(ev.evidence_id)
            subject = bindings.get((ref.system, ref.native_id))
            if subject:
                # A linked source is still a source assertion, not a business event.
                ledger.add_claim(Claim(claim_id=stable_id("claim", f"source:{ev.evidence_id}:{subject}"),
                                       subject_id=subject, predicate="source_text", object_value=exact,
                                       evidence_ids=(ev.evidence_id,), extraction_confidence="high"))
    return made


def route_annotation(field: str, label: str, evidence_id: str, policy: dict[str, Any],
                     *, method: str, confidence: float | None = None) -> dict[str, Any]:
    """Field-level routing decision. Model labels remain proposed annotations."""
    if not evidence_id:
        raise ValueError("Annotation requires exact source evidence")
    critical = field in {"commercial_contract_status", "contract_kind", "signed_amount", "identity_merge"}
    if method == "deterministic":
        route = "exact_rule"
    elif method == "jev" and policy.get("commercial_signature_auto_proposal_enabled") and policy.get("deployment_status") == "validated":
        route = "jev_bounded_proposal" if confidence is not None and confidence >= policy.get("candidate_threshold", 1) else "human_review"
    else:
        route = "human_review" if critical else "abstain_unvalidated_provider"
    if field == "commercial_contract_status" and label == "signed":
        route = "human_review"
    return {"field": field, "label": label, "evidence_id": evidence_id,
            "method": method, "policy_version": policy.get("policy_version"),
            "route": route, "verified_actual_mutation_allowed": False}


def materialize_annotation(ledger: Ledger, *, evidence_id: str, opportunity_id: str,
                           field: str, label: str, method: str, policy: dict[str, Any],
                           date_evidence_id: str | None = None,
                           business_event_date: str | None = None,
                           details: dict[str, Any] | None = None) -> dict[str, Any]:
    """Record a cited observation; emit only safe dated events, never verified facts.

    A date supplied by an extractor must carry its own source evidence. No
    transport timestamp or unvalidated model choice becomes a business date.
    """
    ev = ledger.evidence(evidence_id)
    opp = ledger.entity(opportunity_id)
    if ev is None or opp is None or "use_case_code" not in opp:
        raise ValueError("Existing evidence and canonical opportunity required")
    if method == "deterministic":
        source = ev["verbatim_excerpt"].lower()
        safe = {
            ("pilot_contract_status", "verbal_yes"): r"verbal yes.{0,30}pilot|pilot.{0,30}verbal yes",
            ("pilot_contract_status", "signed"): r"pilot signed\s*:",
            ("commercial_contract_status", "signed"): r"commercial.{0,40}signed|signed.{0,40}commercial",
            ("commercial_contract_status", "not_signed"): r"contract not signed|commercial.{0,35}unsigned",
            ("data_access", "provided_or_access_granted"): r"data (?:uploaded|provided|delivered)|access granted",
            ("next_step_strength", "seller_plan"): r"next:|chase in|plan to follow up",
            ("blocker", "open"): r"blocked|blocker|not approved|waiting on data access",
            ("momentum", "stalled_explicit"): r"no reply|stalled|paused",
        }
        pattern = safe.get((field, label))
        if pattern is None or re.search(pattern, source) is None:
            raise ValueError("No validated exact rule supports this annotation")
    decision = route_annotation(field, label, evidence_id, policy, method=method)
    if business_event_date:
        date_ev = ledger.evidence(date_evidence_id) if date_evidence_id else None
        if not date_ev or business_event_date not in date_ev["verbatim_excerpt"]:
            raise ValueError("Business date needs an exact cited source span")
    event_date = business_event_date or ev["business_event_date"]
    known = {"pilot_contract_status": {"verbal_yes": "pilot_verbal_yes", "signed": "pilot_signed"},
             "commercial_contract_status": {"signed": "commercial_signed"},
             "data_access": {"provided_or_access_granted": "data_received"}}
    event_type = known.get(field, {}).get(label)
    evidence_ids = tuple(dict.fromkeys([evidence_id] + ([date_evidence_id] if date_evidence_id else [])))
    claim = Claim(claim_id=stable_id("claim", f"{opportunity_id}:{field}:{label}:{evidence_id}"),
                  subject_id=opportunity_id, predicate=f"signal:{field}" if field in SIGNAL_FIELDS else field,
                  object_value=label,
                  contract_kind="pilot" if field == "pilot_contract_status" else
                  "commercial" if field == "commercial_contract_status" else None,
                  scope_id=opp["commercial_scope_id"], valid_from=event_date,
                  evidence_ids=evidence_ids, status="observed" if decision["route"] == "exact_rule" else "inferred",
                  verification="unverified",
                  extraction_confidence="high" if method == "deterministic" else "low",
                  resolution_reason=f"{method}:{decision['policy_version']}:{decision['route']}")
    ledger.add_claim(claim)
    emitted = None
    if event_type and event_date and decision["route"] == "exact_rule":
        required = {"pilot_verbal_yes": "pilot_scope", "pilot_signed": "pilot_contract_id",
                    "commercial_signed": "commercial_contract_id", "data_received": "data_kind"}
        info = details or {}
        if event_type == "data_received" and not info.get("delivery_or_access"):
            info = {}
        if info.get(required[event_type]) and (event_type != "data_received" or info.get("delivery_or_access")):
            item = Event(event_id=stable_id("event", f"{claim.claim_id}:{event_type}"),
                         event_type=event_type, account_id=opp["account_id"],
                         opportunity_id=opportunity_id, scope_id=opp["commercial_scope_id"],
                         contract_kind=claim.contract_kind, event_date=event_date,
                         date_precision=ev["date_precision"] if not business_event_date else "cited_date",
                         recorded_at=ev["documented_at"], first_seen_at=ev["source_first_seen_at"],
                         evidence_ids=evidence_ids, verification="unverified",
                         extraction_version=VERSION, details=info)
            ledger.add_event(item)
            emitted = item.event_id
    return {**decision, "claim_id": claim.claim_id, "event_id": emitted}


def route_policy_candidates(ledger: Ledger, policy: dict[str, Any],
                            subject_by_source: dict[tuple[str, str], str]) -> list[dict[str, Any]]:
    """Re-anchor B candidate spans to A2 raw versions and queue material review.

    B's audit-corpus offsets are not A2 offsets. A candidate is accepted only
    when its exact quote occurs in the immutable live-source snapshot and the
    native source has an explicit canonical identity binding.
    """
    queued = []
    for proposal in policy.get("candidate_proposals_for_review", []):
        src = proposal.get("source_ref") or {}
        native = str(src.get("native_id", "")).replace("-", "").lower()
        bindings = [(key, subject) for key, subject in subject_by_source.items()
                    if key[0] == "notion" and key[1].replace("-", "").lower() == native]
        if len(bindings) != 1:
            queued.append({"kind": "ambiguous_entity", "native_id": src.get("native_id"),
                           "candidate": proposal["document_id"]})
            continue
        key, subject = bindings[0]
        rows = ledger.db.execute("SELECT version,sha256,content,first_seen_at,ingested_at FROM raw_source "
                                 "WHERE system=? AND object_type='page' AND native_id=? ORDER BY rowid DESC", key).fetchall()
        quote = proposal.get("span", {}).get("exact_text")
        if len(rows) != 1 or not quote:
            queued.append({"kind": "source_version_or_span_ambiguous", "native_id": key[1]})
            continue
        raw = rows[0]
        encoded = json.dumps(quote, ensure_ascii=False)[1:-1]
        start = raw["content"].find(encoded)
        if start < 0:
            queued.append({"kind": "candidate_span_not_in_snapshot", "native_id": key[1]})
            continue
        ref = SourceRef(key[0], "page", key[1])
        evidence = Evidence(evidence_id=stable_id("evidence", f"B:{ref}:{raw['version']}:{start}:{encoded}"),
                            source_ref=ref, source_version=raw["version"], source_hash=raw["sha256"],
                            field_path="candidate_span", start_offset=start, end_offset=start + len(encoded),
                            verbatim_excerpt=encoded, source_first_seen_at=raw["first_seen_at"],
                            ingested_at=raw["ingested_at"], documented_at=None,
                            business_event_date=None, date_precision="unknown",
                            derivation_rule=f"stage_b:{policy.get('policy_version')}")
        ledger.add_evidence(evidence)
        decision = materialize_annotation(ledger, evidence_id=evidence.evidence_id,
                                          opportunity_id=subject, field="commercial_contract_status",
                                          label="signed", method="jev", policy=policy)
        queued.append({"kind": "reported_commercial_signature", "opportunity_id": subject,
                       "evidence_id": evidence.evidence_id, "route": decision["route"],
                       "claim_id": decision["claim_id"], "event_id": decision["event_id"]})
    return queued
