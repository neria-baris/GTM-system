"""Validate presentation_v1 JSON, SQLite reconciliation, and non-inference gates."""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.belief.ontology import BANDS, DIMENSIONS, VERSION as BELIEF_VERSION
from src.belief.presentation import KIND as BELIEF_KIND
from src.belief.valuation import GOAL_END as RECOGNITION_END, GOAL_START as RECOGNITION_START
from src.tracker.read_model import EVENT_TO_JOURNEY, FILES, JOURNEY, VERSION


VALUATION_KINDS = {"recognized_signed_acv", "estimate", "unknown"}
ESTIMATE_BASES = {"stated_rollout_value", "pilot_fee_times_corpus_ratio", "corpus_median_rollout"}
RECOGNIZABLE_STATUS = {"reported_signed", "verified_signed"}
RECOGNIZABLE_BANDS = {"high", "very_high"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def amount(value: str | None) -> Decimal | None:
    if value is None:
        return None
    require(isinstance(value, str) and bool(re.fullmatch(r"-?\d+(?:\.\d+)?", value)),
            "Money must be a decimal string or null")
    return Decimal(value)


def _no_native_payload(value: object) -> None:
    banned = {"jev", "llm", "probabilities", "probability_vector", "raw_snapshot",
              "native_payload", "candidate_claims", "response_body", "api_key",
              "crm_stage", "airtable_deal", "source_object", "semantic_payload",
              "semantic_model", "raw_response", "identity_candidates"}
    if isinstance(value, dict):
        for key, nested in value.items():
            require(not any(fragment in key.lower() for fragment in banned),
                    f"Provider/model-native key leaked: {key}")
            _no_native_payload(nested)
    elif isinstance(value, list):
        for nested in value:
            _no_native_payload(nested)


def _validate_schema(value: object, rule: dict, schema: dict, location: str = "$ ") -> None:
    """Validate the JSON Schema keywords used by presentation_v1 without a dependency."""
    if "$ref" in rule:
        name = rule["$ref"].removeprefix("#/$defs/")
        require(name in schema["$defs"], f"Unknown schema reference {name}")
        return _validate_schema(value, schema["$defs"][name], schema, location)
    if "oneOf" in rule:
        passed = 0
        for branch in rule["oneOf"]:
            try:
                _validate_schema(value, branch, schema, location)
                passed += 1
            except ValueError:
                pass
        require(passed == 1, f"Schema oneOf mismatch at {location}")
        return
    if "const" in rule:
        require(value == rule["const"], f"Schema const mismatch at {location}")
    if "enum" in rule:
        require(value in rule["enum"], f"Schema enum mismatch at {location}")
    kinds = rule.get("type")
    if kinds:
        kinds = kinds if isinstance(kinds, list) else [kinds]
        require(any((kind == "object" and isinstance(value, dict)) or
                    (kind == "array" and isinstance(value, list)) or
                    (kind == "string" and isinstance(value, str)) or
                    (kind == "null" and value is None) or
                    (kind == "integer" and isinstance(value, int) and not isinstance(value, bool))
                    for kind in kinds), f"Schema type mismatch at {location}")
    if isinstance(value, dict):
        require(all(key in value for key in rule.get("required", [])),
                f"Schema required field missing at {location}")
        require(len(value) >= rule.get("minProperties", 0), f"Schema property count at {location}")
        properties = rule.get("properties", {})
        for key, nested in value.items():
            if key in properties:
                _validate_schema(nested, properties[key], schema, f"{location}.{key}")
            elif rule.get("additionalProperties") is False:
                raise ValueError(f"Schema extra property at {location}.{key}")
            elif isinstance(rule.get("additionalProperties"), dict):
                _validate_schema(nested, rule["additionalProperties"], schema, f"{location}.{key}")
    if isinstance(value, str):
        if "pattern" in rule:
            require(bool(re.fullmatch(rule["pattern"], value)), f"Schema pattern mismatch at {location}")
        if rule.get("format") == "date":
            from datetime import date
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f"Schema date mismatch at {location}") from exc


def _belief_evidence_ids(value: object) -> set[str]:
    """Every evidence ID referenced anywhere in the belief file (any *evidence_ids or evidence_id key)."""
    found: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            if key.endswith("evidence_ids"):
                require(isinstance(nested, list) and all(isinstance(x, str) for x in nested),
                        f"Belief {key} must be a list of evidence IDs")
                found.update(nested)
            elif key == "evidence_id":
                require(isinstance(nested, str), "Belief evidence_id must be an evidence ID")
                found.add(nested)
            else:
                found |= _belief_evidence_ids(nested)
    elif isinstance(value, list):
        for nested in value:
            found |= _belief_evidence_ids(nested)
    return found


def _belief_state(dimension: str, value: object, band: object) -> None:
    require(dimension in DIMENSIONS, f"Belief dimension outside ontology: {dimension}")
    require(value in DIMENSIONS[dimension], f"Belief value outside ontology: {dimension}={value}")
    require(band is None or band in BANDS, f"Invalid belief band: {band}")


def _compact_states(states: object) -> None:
    require(isinstance(states, dict), "Belief snapshot states malformed")
    for dimension, pair in states.items():
        require(isinstance(pair, list) and len(pair) == 2, "Belief snapshot state malformed")
        _belief_state(dimension, pair[0], pair[1])


def _states(states: object, where: str) -> None:
    require(isinstance(states, dict) and set(states) == set(DIMENSIONS), f"Belief dimensions incomplete ({where})")
    for dimension, state in states.items():
        require(state["dimension"] == dimension, "Belief dimension key mismatch")
        _belief_state(dimension, state["value"], state["band"])
        for alternative in state.get("alternatives", []):
            _belief_state(dimension, alternative["value"], alternative["band"])


def _valuation(value: object, belief: dict, as_of: str, where: str, *, formal: bool) -> Decimal | None:
    """One subject's valuation; returns the recognised signed ACV it contributes (or None)."""
    require(isinstance(value, dict), f"Valuation missing ({where})")
    kind = value.get("kind")
    require(kind in VALUATION_KINDS, f"Valuation kind invalid ({where}): {kind}")
    require(isinstance(value.get("reasons"), list) and bool(value["reasons"]), f"Valuation without reasons ({where})")
    require(value.get("documentary_verified") in (None, False) or formal,
            f"Valuation documentary-verified outside the documentary gate ({where})")
    if kind != "recognized_signed_acv":
        require(not value.get("recognized"), f"Only a recognised signed ACV can be recognised ({where})")
    if kind == "unknown":
        require(value.get("amount_usd") is None, f"Unknown valuation carries an amount ({where})")
        return None
    if kind == "estimate":
        require(value.get("basis") in ESTIMATE_BASES, f"Estimate basis invalid ({where})")
        estimate, rng = amount(value.get("amount_usd")), value.get("range_usd")
        require(estimate is not None and isinstance(rng, list) and len(rng) == 2, f"Estimate amount/range missing ({where})")
        low, high = amount(rng[0]), amount(rng[1])
        require(low is not None and high is not None and low <= estimate <= high, f"Estimate outside its range ({where})")
        require(value.get("band") in BANDS, f"Estimate band invalid ({where})")
        amount(value.get("weighted_usd"))
        require(value["basis"] == "corpus_median_rollout" or bool(value.get("evidence_ids")),
                f"Estimate without evidence ({where})")
        return None
    commercial = belief["states"]["commercial_status"]
    require(commercial["value"] in RECOGNIZABLE_STATUS and commercial["band"] in RECOGNIZABLE_BANDS
            and not commercial.get("contested"),
            f"Recognised signed ACV without a high-confidence uncontested signature belief ({where})")
    require(isinstance(value.get("recognized"), bool), f"Recognition flag missing ({where})")
    require(bool(value.get("evidence_ids")), f"Recognised signed ACV without evidence ({where})")
    if not value["recognized"]:
        return None
    recognized = amount(value.get("amount_usd"))
    require(recognized is not None and recognized > 0, f"Recognised signed ACV without an amount ({where})")
    day = value.get("signature_date")
    require(isinstance(day, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)) and
            RECOGNITION_START <= day <= min(RECOGNITION_END, as_of),
            f"Recognised signature outside the target window ({where})")
    return recognized


def _validate_context(beliefs: dict, overview: dict) -> None:
    """Reconstructed deals, valuations and their totals (soft-to-hard evidence)."""
    as_of = beliefs["business_as_of"]
    opportunities = beliefs["opportunities"]
    reconstructed = beliefs.get("reconstructed_opportunities") or {}
    totals = beliefs["overview"].get("valuation")
    if totals is None:
        require(all(entry.get("valuation") is None for entry in opportunities.values()) and not reconstructed,
                "Valuation totals missing")
        return
    subjects = {}
    for oid, entry in opportunities.items():
        subjects[oid] = (entry["valuation"], entry["current"], entry["verified"]["formal_contract_verified"])
    for cid, entry in reconstructed.items():
        require(entry["cluster_id"] == cid and entry["status"] == "inferred_from_context",
                "Reconstructed deal key/status mismatch")
        require(cid not in opportunities, "Reconstructed deal collides with an opportunity")
        require(isinstance(entry["groups"], list) and len(set(entry["groups"])) >= 2,
                "Reconstructed deal needs at least two linked sources")
        require(isinstance(entry["links"], list) and bool(entry["links"]), "Reconstructed deal without links")
        for link in entry["links"]:
            require(link["group"] in entry["groups"] and bool(link["shared_anchors"]),
                    "Reconstructed link without anchors")
        _states(entry["current"]["states"], cid)
        require(not any(s.get("verified") for s in entry["current"]["states"].values()),
                "Reconstructed deal marked verified")
        subjects[f"reconstructed:{cid}"] = (entry["valuation"], entry["current"], False)
    recognized = Decimal(0)
    count = 0
    estimates, seen = [], set()
    for subject, (value, belief, formal) in sorted(subjects.items()):
        got = _valuation(value, belief, as_of, subject, formal=formal)
        if got is not None:
            recognized += got
            count += 1
        if value["kind"] == "estimate":
            key = frozenset(value.get("evidence_ids") or []) or subject
            if key not in seen:
                seen.add(key)
                estimates.append(value)
    require(amount(totals["recognized_signed_acv_usd"]) == recognized and totals["recognized_deal_count"] == count,
            "Recognised signed ACV total mismatch")
    require(totals["documentary_verified_usd"] == overview["verified_signed_acv_usd"],
            "Documentary-verified figure differs from Verified Actual")
    total = lambda xs: sum((amount(x) for x in xs), Decimal(0))
    require(amount(totals["estimated_open_pipeline_usd"]) == total(v["amount_usd"] for v in estimates) and
            [amount(x) for x in totals["estimated_open_pipeline_range_usd"]] ==
            [total(v["range_usd"][0] for v in estimates), total(v["range_usd"][1] for v in estimates)] and
            amount(totals["weighted_pipeline_usd"]) == total(v["weighted_usd"] for v in estimates),
            "Estimated pipeline total mismatch")
    require(beliefs["overview"].get("reconstructed_deal_count") == len(reconstructed),
            "Reconstructed deal count mismatch")


def _validate_beliefs(beliefs: dict, by_id: dict, evidence: dict, reviews: dict, overview: dict,
                      snapshots: list) -> int:
    """Observed -> Inferred -> Verified boundary checks for belief_states.json."""
    require(beliefs.get("kind") == BELIEF_KIND and beliefs.get("engine_version") == BELIEF_VERSION,
            "Belief kind/engine version mismatch")
    opportunities = beliefs["opportunities"]
    require(set(opportunities) == set(by_id), "Belief/opportunity population mismatch")
    require(all(eid in evidence for eid in _belief_evidence_ids(beliefs)), "Belief references unresolved evidence")
    latest_quality = snapshots[-1]["historical_knowledge_quality"]
    for oid, entry in opportunities.items():
        require(entry["opportunity_id"] == oid, "Belief opportunity key mismatch")
        verified = entry["verified"]
        require(verified["verified_actual_usd"] == by_id[oid]["verified_actual_usd"],
                "Belief Verified Actual differs from the contract gate")
        states = entry["current"]["states"]
        require(set(states) == set(DIMENSIONS), "Belief dimensions incomplete")
        for dimension, state in states.items():
            require(state["dimension"] == dimension, "Belief dimension key mismatch")
            _belief_state(dimension, state["value"], state["band"])
            for alternative in state.get("alternatives", []):
                _belief_state(dimension, alternative["value"], alternative["band"])
            if state.get("verified"):
                require(dimension == "commercial_status" and state["value"] == "verified_signed" and
                        verified["formal_contract_verified"] is True,
                        "Inferred state marked verified outside the documentary gate")
        history = entry["historically_known"]
        if latest_quality == "unavailable":
            require(history["available"] is False and history["states"] is None,
                    "Unprovable historical belief forward-filled")
        elif history["states"] is not None:
            _compact_states(history["states"])
    belief_overview = beliefs["overview"]
    require(belief_overview["value_buckets"]["verified_actual_usd"] == overview["verified_signed_acv_usd"],
            "Belief value bucket differs from Verified Actual")
    _validate_context(beliefs, overview)
    require(belief_overview["opportunities"] == len(by_id), "Belief overview population mismatch")
    triage = beliefs["review_triage"]
    belief_items = {x["review_id"]: x for x in beliefs["belief_review_items"]}
    require(len(belief_items) == len(beliefs["belief_review_items"]), "Duplicate belief review ID")
    require(not set(belief_items) & set(reviews), "Belief review ID collides with review queue")
    require(set(triage) == set(reviews) | set(belief_items), "Review triage does not cover every review item")
    for item in belief_items.values():
        require(item["opportunity_id"] in opportunities and item["evidence_ids"] and item["required_action"],
                "Incomplete belief review item")
    for t in triage.values():
        require(isinstance(t["decision_needed"], bool) and bool(t["category"]) and bool(t["rationale"]),
                "Incomplete review triage")
    needed = sum(t["decision_needed"] for t in triage.values())
    summary = beliefs["review_summary"]
    require(summary["total"] == len(triage) and summary["decision_needed"] == needed and
            summary["informational"] == len(triage) - needed, "Review triage summary mismatch")
    weekly = beliefs["weekly"]
    require([w["week_end"] for w in weekly] == [x["week_end"] for x in snapshots], "Belief weeks differ from snapshots")
    for week, snap in zip(weekly, snapshots):
        require(week["historical_knowledge_quality"] == snap["historical_knowledge_quality"],
                "Belief historical quality differs from snapshot")
        if week["historical_knowledge_quality"] == "unavailable":
            require(week["historically_known"] is None, "Unprovable historical belief forward-filled")
        for mode in ("retrospective", "historically_known"):
            for oid, states in (week[mode] or {}).items():
                require(oid in opportunities, "Weekly belief has unresolved opportunity")
                _compact_states(states)
    return needed


def validate(directory: str | Path, sqlite_path: str | Path) -> dict[str, int]:
    directory, sqlite_path = Path(directory), Path(sqlite_path)
    schema = json.loads((ROOT / "schemas/presentation_v1.schema.json").read_text(encoding="utf-8"))
    require(schema["$defs"]["manifest"]["properties"]["schema_version"]["const"] == VERSION,
            "Schema version mismatch")
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    _validate_schema(manifest, schema, schema)
    for key in schema["$defs"]["manifest"]["required"]:
        require(key in manifest, f"Manifest missing {key}")
    require(manifest["schema_version"] == VERSION, "Manifest version mismatch")
    require(manifest["historical_knowledge_quality"] in {"complete", "partial", "unavailable"},
            "Missing historical quality")
    require(isinstance(manifest["timezone"], str) and manifest["timezone"], "Timezone missing")
    require(set(manifest["files"]) == {f"{name}.json" for name in FILES}, "File inventory mismatch")
    data = {}
    for name in FILES:
        path = directory / f"{name}.json"
        require(path.is_file(), f"Missing {path.name}")
        require(hashlib.sha256(path.read_bytes()).hexdigest() == manifest["files"][path.name],
                f"Hash mismatch: {name}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        _validate_schema(payload, schema, schema)
        require(set(payload) == {"schema_version", "kind", "data"} and
                payload["schema_version"] == VERSION and payload["kind"] == name,
                f"Malformed {name}")
        data[name] = payload["data"]
        if name == "belief_states" and isinstance(payload["data"], dict) and \
                isinstance(payload["data"].get("review_triage"), dict):
            # Triage is keyed by review ID (data, not field names); the keys are checked against
            # the review queue below and every triage record is still scanned.
            payload = {**payload, "data": {**payload["data"],
                                           "review_triage": list(payload["data"]["review_triage"].values())}}
        _no_native_payload(payload)
    overview = data["overview"]
    for key in ("target", "verified_signed_acv_usd", "reported_signed_pending_verification_usd",
                "known_value_open_commercial_pipeline_usd", "value_coverage", "journey_distribution",
                "counts", "latest_weekly_movement", "heuristic_proxy"):
        require(key in overview, f"Overview missing {key}")
    require(overview["target"] == manifest["target"], "Target mismatch")
    require("proxy" in overview["heuristic_proxy"]["label"].lower() and
            "not a forecast" in overview["heuristic_proxy"]["label"].lower(),
            "Proxy shaped as forecast")
    amount(overview["verified_signed_acv_usd"])
    amount(overview["reported_signed_pending_verification_usd"])
    amount(overview["known_value_open_commercial_pipeline_usd"])
    amount(overview["heuristic_proxy"]["amount_usd"])
    summaries = data["opportunities"]
    details = data["opportunity_details"]
    evidence = {e["evidence_id"]: e for e in data["evidence_summaries"]}
    reviews = {r["review_id"]: r for r in data["review_queue"]}
    require(len(evidence) == len(data["evidence_summaries"]), "Duplicate evidence ID")
    require(len(reviews) == len(data["review_queue"]), "Duplicate review ID")
    by_id = {x["opportunity_id"]: x for x in details}
    require(len(by_id) == len(details), "Duplicate opportunity ID")
    require({x["opportunity_id"] for x in summaries} == set(by_id), "Summary/detail identity mismatch")
    actual = Decimal(0)
    pending = Decimal(0)
    open_value = Decimal(0)
    selected_ids = []
    selected_groups = []
    for row in summaries:
        detail = by_id[row["opportunity_id"]]
        for key in ("account_id", "commercial_scope_id", "furthest_evidenced_journey_milestone",
                    "known_open_commercial_value_usd", "value_status", "verified_actual_usd"):
            require(row[key] == detail[key], f"Summary/detail mismatch {key}")
        require(row["review_flag"] == (detail["review_status"] == "open"), "Review flag mismatch")
        observed = {EVENT_TO_JOURNEY[e["event_type"]] for e in detail["event_timeline"]
                    if e["event_type"] in EVENT_TO_JOURNEY}
        require(set(detail["observed_milestones"]) == observed,
                "Unsupported journey milestone")
        furthest = max(observed, key=JOURNEY.index) if observed else None
        require(detail["furthest_evidenced_journey_milestone"] == furthest,
                "Unsupported furthest journey milestone")
        missing = [x for x in JOURNEY[:JOURNEY.index(furthest)] if x not in observed] if furthest else []
        require(detail["missing_prior_milestones"] == missing, "Missing prior milestones corrupted")
        for eid in detail["supporting_evidence_ids"] + detail["conflicting_evidence_ids"]:
            require(eid in evidence, "Unresolved evidence reference")
        for event in detail["event_timeline"]:
            require(all(eid in evidence for eid in event["evidence_ids"]), "Unresolved event evidence")
        for rid in detail["review_ids"]:
            require(rid in reviews and reviews[rid]["opportunity_id"] == detail["opportunity_id"],
                    "Broken review linkage")
        actual += amount(detail["verified_actual_usd"])
        p = amount(detail["reported_signed_pending_verification_usd"])
        if p is not None:
            pending += p
        o = amount(detail["known_open_commercial_value_usd"])
        if o is not None:
            open_value += o
        elif detail["value_status"] == "known_eligible":
            raise ValueError("Unknown money changed to zero")
        for value in detail["commercial_values"]:
            require(all(eid in evidence for eid in value["evidence_ids"]), "Unresolved value evidence")
            require(value["value_type"] != "pilot_fee" or not value["selected_for_open_value"],
                    "Pilot fee in open commercial value")
            if value["selected_for_open_value"]:
                require(value["value_id"] == detail["selected_value_id"], "Selected value mismatch")
                selected_ids.append(value["value_id"])
                group = detail["exclusivity_group_id"] or value["scenario_group_id"]
                if group:
                    selected_groups.append(group)
        require(not (p is not None and amount(detail["verified_actual_usd"]) == p and p != 0
                     and detail["commercial_state"] == "reported_signed_pending"),
                "Pending entered Actual")
    require(len(selected_ids) == len(set(selected_ids)), "Duplicate counted value")
    require(len(selected_groups) == len(set(selected_groups)), "Alternative scopes summed")
    require(actual == amount(overview["verified_signed_acv_usd"]), "Actual reconciliation error")
    require(open_value == amount(overview["known_value_open_commercial_pipeline_usd"]),
            "Open value reconciliation error")
    if overview["reported_signed_pending_verification_usd"] is not None:
        require(pending == amount(overview["reported_signed_pending_verification_usd"]),
                "Pending reconciliation error")
    require(dict(Counter(x["furthest_evidenced_journey_milestone"] or "unknown" for x in details)) ==
            overview["journey_distribution"], "Journey distribution mismatch")
    for review in reviews.values():
        require(review["evidence_ids"] and all(eid in evidence for eid in review["evidence_ids"]),
                "Review has unresolved evidence")
        require(review["opportunity_id"] is None or review["opportunity_id"] in by_id,
                "Review has unresolved opportunity")
        require(review["required_action"] and review["reason"] and review["status"],
                "Incomplete review item")
    snapshots = data["weekly_snapshots"]
    require(bool(snapshots), "No weekly snapshots")
    for snap in snapshots:
        require(snap["historical_knowledge_quality"] in {"complete", "partial", "unavailable"},
                "Missing historical quality")
        require(snap["historically_known_state"]["historical_knowledge_quality"] ==
                snap["historical_knowledge_quality"], "Historical mode mismatch")
        if snap["historical_knowledge_quality"] == "unavailable":
            require(snap["historically_known_state"]["verified_actual_usd"] is None and
                    snap["historically_known_state"]["opportunity_ids"] == [],
                    "Unprovable historical availability forward-filled")
        require(set(snap["movement"]) == {"journey", "economics", "risk", "count"},
                "Weekly movement dimensions missing")
    require(snapshots[-1]["week_end"] == manifest["business_as_of"], "Snapshot date mismatch")
    require(snapshots[-1]["historical_knowledge_quality"] ==
            manifest["historical_knowledge_quality"], "Manifest history mismatch")
    beliefs = data["belief_states"]
    decision_needed = _validate_beliefs(beliefs, by_id, evidence, reviews, overview, snapshots)
    with sqlite3.connect(sqlite_path) as db:
        for table in ("opportunity_state", "journey_events", "commercial_values",
                      "weekly_opportunity_state", "weekly_summary", "evidence_summary", "review_items",
                      "belief_state", "weekly_belief", "review_triage"):
            db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        require(db.execute("SELECT COUNT(*) FROM opportunity_state").fetchone()[0] == len(details),
                "SQLite opportunity count mismatch")
        require(db.execute("SELECT COUNT(*) FROM evidence_summary").fetchone()[0] == len(evidence),
                "SQLite evidence count mismatch")
        require(db.execute("SELECT COUNT(*) FROM review_items").fetchone()[0] == len(reviews),
                "SQLite review count mismatch")
        for oid, payload in db.execute("SELECT opportunity_id,payload FROM opportunity_state"):
            require(json.loads(payload) == by_id[oid], "SQLite/JSON state mismatch")
        stored = {oid: json.loads(payload) for oid, payload in db.execute("SELECT opportunity_id,payload FROM belief_state")}
        require(stored == beliefs["opportunities"], "SQLite/JSON belief state mismatch")
        stored = {(w, m, oid): json.loads(payload) for w, m, oid, payload in
                  db.execute("SELECT week_end,mode,opportunity_id,payload FROM weekly_belief")}
        expected = {(week["week_end"], mode, oid): states for week in beliefs["weekly"]
                    for mode in ("retrospective", "historically_known") for oid, states in (week[mode] or {}).items()}
        require(stored == expected, "SQLite/JSON weekly belief mismatch")
        stored = {rid: json.loads(payload) for rid, payload in db.execute("SELECT review_id,payload FROM review_triage")}
        require(stored == beliefs["review_triage"], "SQLite/JSON review triage mismatch")
    return {"opportunities": len(details), "evidence": len(evidence),
            "reviews": len(reviews), "weeks": len(snapshots),
            "belief_opportunities": len(beliefs["opportunities"]), "decision_needed_reviews": decision_needed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime_dir", type=Path)
    parser.add_argument("--sqlite", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(validate(args.runtime_dir, args.sqlite), sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error) as exc:
        print(f"presentation_v1 invalid: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
