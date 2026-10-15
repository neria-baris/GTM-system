"""Stage C bridge from C2 proposals to source claims and guarded weekly state.

The corpus contains extraction proposals, not resolved Account x Use Case x Scope
identities. A source-scoped claim remains auditable without inventing an Opportunity.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any

from src.connectors.common import stable_provider_content
from src.extraction.full_corpus import validate_span
from src.ledger.models import Claim, Evidence, SourceRef
from src.ledger.store import Ledger, stable_id
from src.settings import business_as_of
from .quantitative import weekly_state
from .semantic_integration import integrate_semantics

VERSION = "c_full_corpus_2.0.0"
MATERIALIZABLE = {"auto_accepted_extraction"}
REVIEW = {"review_required"}
ALLOWED_SOURCE_DISPOSITIONS = {
    "extracted", "no_business_evidence", "abstained", "review_required",
    "transport_only", "excluded_by_schema_with_reason",
}


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _key(item: dict[str, Any]) -> tuple[str, str, str]:
    return item["provider"], item["native_object_type"], item.get("native_id", item.get("native_source_id"))


def _validate_coverage(manifest: dict, coverage: dict, candidates: list[dict], review: dict) -> dict:
    if not coverage.get("coverage_gate_passed") or coverage.get("unaccounted_source_count") != 0:
        raise ValueError("C2 source coverage gate failed")
    if not manifest.get("complete") or not coverage.get("manifest_complete"):
        raise ValueError("A2 or C2 manifest is incomplete")
    if coverage.get("a2_run_id") != manifest.get("run_id"):
        raise ValueError("C2 coverage belongs to another A2 run")
    envelopes = manifest["envelopes"]
    source_rows = coverage["source_coverage"]
    env_keys = [_key(e) for e in envelopes]
    coverage_keys = [_key(e) for e in source_rows]
    if (len(set(env_keys)) != len(env_keys) or len(set(coverage_keys)) != len(coverage_keys)
            or set(env_keys) != set(coverage_keys)
            or len(envelopes) != coverage["considered_source_count"]):
        raise ValueError("C2 coverage does not account for each A2 envelope exactly once")
    env_by_key = dict(zip(env_keys, envelopes))
    for row in source_rows:
        env = env_by_key[_key(row)]
        if (row["disposition"] not in ALLOWED_SOURCE_DISPOSITIONS or
                row["content_hash"] != env["content_hash"] or
                row["raw_snapshot_path"] != env["raw_snapshot_path"]):
            raise ValueError("C2 source disposition or source version mismatch")
    candidate_ids = [c["candidate_id"] for c in candidates]
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("Duplicate C2 candidate ID")
    for item in review["items"]:
        if not set(item["candidate_ids"]).issubset(candidate_ids):
            raise ValueError("C2 review item references an absent candidate")
    return env_by_key


def _safe_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Raw snapshot absent or outside source root")
    return path


def _route(candidate: dict, policy: dict) -> str:
    """C2 acceptance is extraction acceptance, never documentary acceptance."""
    if candidate.get("semantic_schema_version") and candidate["validation_status"] in {"semantic_validated_proposal", "review_required"}:
        return "semantic_proposal"
    if candidate["validation_status"] in REVIEW:
        return "review_required"
    if candidate["validation_status"] not in MATERIALIZABLE:
        return "unknown_unvalidated"
    route = candidate["extraction_route"]
    field = candidate["predicate"]
    configured = policy.get("field_routes", {}).get(field, {}).get("route")
    if route == "deterministic":
        return "source_claim"
    if route == "rule":
        return "source_annotation" if configured == "rules" else "unknown_route_unvalidated"
    if route in {"jev_single", "jev_ensemble"}:
        return "source_annotation" if configured == route else "unknown_route_unvalidated"
    if route == "llm":
        return "unknown_route_unvalidated"
    return "unknown_route_unvalidated"


def serialized_span(content: Any, span: dict) -> tuple[int, int, str]:
    """Map a JSON pointer to its exact serialized leaf, including repeated strings."""
    encode = lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    tokens = [t.replace("~1", "/").replace("~0", "~") for t in span["json_pointer"].split("/")[1:]]
    if not tokens or tokens.pop(0) != "content":
        raise ValueError("Expected snapshot content pointer")
    node, offset = content, 0
    for token in tokens:
        offset += 1  # opening object/array delimiter
        if isinstance(node, dict):
            for key in sorted(node):
                offset += len(encode(key)) + 1
                if key == token:
                    node = node[key]
                    break
                offset += len(encode(node[key])) + 1
            else:
                raise ValueError("Invalid source pointer")
        else:
            index = int(token)
            offset += sum(len(encode(x)) + 1 for x in node[:index])
            node = node[index]
    if isinstance(node, str):
        start = offset + 1 + len(encode(node[:span["start"]])[1:-1])
        exact = encode(node[span["start"]:span["end"]])[1:-1]
    else:
        start, exact = offset, encode(node)
    return start, start + len(exact), exact


def integrate_full_corpus(root: str | Path, ledger: Ledger, *, week_end: str | None = None,
                          manifest: dict | None = None, coverage: dict | None = None,
                          candidates: list[dict] | None = None, review: dict | None = None,
                          policy: dict | None = None, extraction_report: dict | None = None
                          ) -> dict[str, Any]:
    """Validate every source/candidate and materialize only supported source claims.

    Canonical events and values require an explicit, independently validated
    identity, scope, contract kind, and date. None is supplied by C2's current
    candidate schema, so source claims do not enter the quantitative ledger.
    """
    root = Path(root).resolve()
    production = candidates is None
    manifest = manifest if manifest is not None else _read(root / "outputs/A2/source_manifest.json")
    coverage = coverage if coverage is not None else _read(root / "outputs/C2/source_coverage_report.json")
    candidates = candidates if candidates is not None else _read(root / "outputs/C2/candidate_claims.json")
    review = review if review is not None else _read(root / "outputs/C2/review_queue.json")
    policy = policy if policy is not None else _read(root / "outputs/B/routing_policy.json")
    extraction_report = extraction_report if extraction_report is not None else _read(root / "outputs/C2/extraction_report.json")
    if production:
        from src.extraction.full_corpus import semantic_gate
        semantic_report = _read(root / "outputs/C2/semantic_extraction_report.json")
        if not semantic_gate(semantic_report) or not semantic_report.get("semantic_gate_passed"):
            raise ValueError("C2 semantic gate failed")
        if hashlib.sha256((root / "outputs/C2/candidate_claims.json").read_bytes()).hexdigest() != semantic_report.get("candidate_artifact_sha256"):
            raise ValueError("C2 semantic candidates changed after validation")
    env_by_key = _validate_coverage(manifest, coverage, candidates, review)
    if extraction_report.get("routing_policy_version") != policy.get("policy_version"):
        raise ValueError("C2 extraction used another B routing policy")

    snapshots: dict[tuple[str, str, str], dict] = {}
    raw_versions: dict[tuple[str, str, str], tuple[str, str]] = {}
    for key, env in env_by_key.items():
        snapshot = _read(_safe_path(root, env["raw_snapshot_path"]))
        content = snapshot["content"]
        stable = json.dumps(stable_provider_content(env["provider"], content),
                            ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if hashlib.sha256(stable.encode("utf-8")).hexdigest() != env["content_hash"]:
            raise ValueError(f"A2 content hash changed for {key}")
        canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        ref = SourceRef(*key)
        digest = ledger.ingest_raw(ref, env["content_hash"], canonical,
                                   env["retrieved_at"], env["retrieved_at"])
        snapshots[key] = snapshot
        raw_versions[key] = (canonical, digest)

    dispositions = []
    counts: Counter[str] = Counter()
    for candidate in candidates:
        key = _key(candidate)
        if key not in env_by_key:
            raise ValueError("C2 candidate is outside A2 manifest")
        env = env_by_key[key]
        if (candidate["content_hash"] != env["content_hash"] or
                candidate["raw_snapshot_path"] != env["raw_snapshot_path"]):
            raise ValueError("C2 candidate points to another raw version")
        span = candidate["evidence_span"]
        if not validate_span(snapshots[key], span):
            raise ValueError(f"Invalid exact C2 source span: {candidate['candidate_id']}")
        if candidate.get("VerifiedActualUSD") is not None or candidate.get("verified_signed") is True:
            raise ValueError("C2 model output attempted contractual verification")
        route = _route(candidate, policy)
        canonical, digest = raw_versions[key]
        start, end, encoded = serialized_span(snapshots[key]["content"], span)
        if canonical[start:end] != encoded:
            raise ValueError("C2 source span absent from immutable raw content")
        ref = SourceRef(*key)
        evidence_id = stable_id("c2_evidence", candidate["candidate_id"])
        evidence = Evidence(evidence_id=evidence_id, source_ref=ref,
                            source_version=env["content_hash"], source_hash=digest,
                            field_path=span["json_pointer"], block_id=span.get("block_id"),
                            start_offset=start, end_offset=end,
                            verbatim_excerpt=encoded, document_author=candidate.get("source_author"),
                            authorship=candidate.get("authorship") or "unknown",
                            assertion_type="crm_snapshot" if key[0] == "airtable" else "firsthand_report",
                            business_event_date=candidate.get("source_meeting_date") or (candidate.get("business_date")
                            if candidate.get("date_role") == "meeting_date" else None),
                            documented_at=None, source_first_seen_at=env["retrieved_at"],
                            ingested_at=env["retrieved_at"], date_precision="unknown",
                            derivation_rule=f"{VERSION}:{candidate['extractor_version']}:{candidate['extraction_route']}",
                            independence_group_id=candidate.get("independence_group"))
        ledger.add_evidence(evidence)
        claim_id = None
        if route in {"source_claim", "source_annotation"}:
            # A source subject is intentionally outside the canonical entity ID
            # space; an unresolved alias cannot identify a buying decision.
            subject = "source:" + ":".join(key)
            claim_id = stable_id("c2_claim", candidate["candidate_id"])
            ledger.add_claim(Claim(claim_id=claim_id, subject_id=subject,
                                   predicate=candidate["predicate"],
                                   object_value=str(candidate["value"]) if candidate.get("value") is not None else None,
                                   polarity=candidate.get("polarity") or "positive",
                                   contract_kind=candidate.get("contract_kind"),
                                   valid_from=None,
                                   evidence_ids=(evidence_id,),
                                   status="observed" if route == "source_claim" else "inferred",
                                   verification="unverified",
                                   extraction_confidence=candidate.get("extraction_confidence") or "unknown",
                                   resolution_reason=f"{VERSION}:{policy['policy_version']}:{candidate['extraction_route']}:{candidate['candidate_id']}"))
        counts[route] += 1
        dispositions.append({"candidate_id": candidate["candidate_id"], "source_ref": {
            "provider": key[0], "native_object_type": key[1], "native_id": key[2]},
            "evidence_id": evidence_id, "claim_id": claim_id,
            "evidence_span": span,
            "extraction_route": candidate["extraction_route"],
            "extractor_version": candidate["extractor_version"],
            "rule_version": candidate.get("rule_version"),
            "extraction_confidence": candidate.get("extraction_confidence"),
            "extraction_stability": candidate.get("extraction_stability"),
            "validation_status": candidate["validation_status"],
            "integration_disposition": route, "review_reason": candidate.get("review_reason"),
            "business_date_mention": candidate.get("business_date"),
            "date_role": candidate.get("date_role"),
            "source_meeting_date": candidate.get("source_meeting_date"),
            "canonical_opportunity_id": None, "event_id": None, "value_id": None})

    semantic_result = {"review_items": [], "semantic_claim_count": 0, "atomic_signal_count": 0,
                       "atomic_signals_by_type": {}, "source_scoped_signal_count": 0}
    if any(c.get("semantic_schema_version") for c in candidates):
        schema = _read(root / "data/raw" / manifest["run_id"] / "airtable/schema.json")
        semantic_result = integrate_semantics(ledger, candidates, dispositions, snapshots, env_by_key, schema)
    all_reviews = review["items"] + semantic_result["review_items"]
    state = weekly_state(ledger, week_end or business_as_of())
    if state["verified_actual_usd"] != "0":
        raise ValueError("Full-corpus extraction unexpectedly changed Verified Actual")
    return {"integration_version": VERSION, "a2_run_id": manifest["run_id"],
            "considered_source_count": len(env_by_key), "candidate_count": len(candidates),
            "materialized_source_claim_count": counts["source_claim"] + counts["source_annotation"] + semantic_result["semantic_claim_count"],
            "unknown_candidate_count": counts["unknown_unvalidated"] + counts["unknown_route_unvalidated"],
            "review_candidate_count": counts["review_required"],
            "unresolved_canonical_link_count": sum(d["canonical_opportunity_id"] is None for d in dispositions),
            "canonical_event_count": ledger.count("event"), "canonical_value_count": ledger.count("commercial_value"),
            "canonical_opportunity_count": ledger.db.execute("SELECT COUNT(*) FROM entity WHERE kind='Opportunity'").fetchone()[0],
            "semantic_integration": {k: v for k, v in semantic_result.items() if k != "review_items"},
            "atomic_signal_count": semantic_result["atomic_signal_count"],
            "atomic_signals_by_type": semantic_result["atomic_signals_by_type"],
            "source_scoped_signal_count": semantic_result["source_scoped_signal_count"],
            "review_item_count": len(all_reviews),
            "review_items": all_reviews,
            "disposition_counts": dict(counts), "candidate_dispositions": dispositions,
            "candidate_artifact": "outputs/C2/candidate_claims.json",
            "source_disposition_counts": coverage["disposition_counts"],
            "source_dispositions": [{"provider": row["provider"],
                                     "native_object_type": row["native_object_type"],
                                     "native_id": row["native_id"],
                                     "disposition": row["disposition"],
                                     "reason": row.get("reason")}
                                    for row in coverage["source_coverage"]],
            "llm_status": extraction_report["llm_status"], "jev_k": extraction_report["jev_k"],
            "routing_policy_version": policy["policy_version"],
            "quantitative_state": state,
            "verified_actual_model_mutations": 0}
