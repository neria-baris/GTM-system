"""C2: immutable A2 envelopes to anchored extraction proposals and coverage audit."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
from typing import Any

from src.belief import jev_sensors
from src.connectors.common import content_hash, stable_provider_content
from .benchmark import RUBRICS, RULE_VERSION, rules
from .ensemble import commercial_signature_gate, run_batch
from .jev_adapter import ADAPTER_VERSION as JEV_ADAPTER_VERSION, choice_question
from .llm_adapter import extract_relations
from .semantic_llm import extract as extract_semantic, normalize_note
from .semantic_schema import SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[2]
VERSION = "c2_full_corpus_2.1.0"
C2_RULE_VERSION = "c2_unsigned_context_1.0.0"
ALLOWED = {"extracted", "no_business_evidence", "abstained", "review_required", "transport_only", "excluded_by_schema_with_reason"}
UNKNOWN = {"unknown", "unclear"}
MONEY = re.compile(r"(?<![\w])(?P<symbol>[$€£])\s*(?P<number>\d+(?:[.,]\d+)?)\s*(?P<scale>[kKmM])?(?!\w)|(?<![\w])(?P<code>USD|EUR|GBP)\s*(?P<code_number>\d+(?:[.,]\d+)?)\s*(?P<code_scale>[kKmM])?", re.I)
DATE = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
COMPLEX = re.compile(r"\b(?:versus|vs\.?|alternative|conditional|if both|two (?:sites|regions|plants|fabs|stores|warehouses)|scope change|instead|amendment)\b", re.I)
BUSINESS = re.compile(r"\b(?:pilot|commercial|rollout|contract|SOW|proposal|signed|unsigned|blocker|procurement|legal|budget|data access|buyer|meeting|next:|pricing|ACV|fee)\b|[$€£]", re.I)
SIGNATURE_CUE = re.compile(r"\b(?:signed|signature|executed)\b", re.I)
TRANSPORT_TYPES = {("notion", "data_source"), ("notion", "database")}


def load_env(path: Path = ROOT / ".env") -> None:
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            match = re.fullmatch(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.*?)\s*", line)
            if match:
                os.environ.setdefault(match[1], match[2].strip("\"'"))


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def pointer(parts: list[str]) -> str:
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def resolve_pointer(value: Any, path: str) -> Any:
    node = value
    for part in path.lstrip("/").split("/") if path else []:
        part = part.replace("~1", "/").replace("~0", "~")
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def exact_span(unit: dict, quote: str, start: int | None = None) -> dict:
    text = unit["text"]
    start = text.find(quote) if start is None else start
    if start < 0 or text[start:start + len(quote)] != quote:
        raise ValueError("quote is not verbatim source evidence")
    return {"json_pointer": unit["json_pointer"], "start": unit["start"] + start,
            "end": unit["start"] + start + len(quote), "exact_text": quote,
            "coordinate_system": "source_string_codepoints", "block_id": unit.get("block_id"),
            "field_id": unit.get("field_id"), "field_name": unit.get("field_name"),
            "table_id": unit.get("table_id")}


def validate_span(snapshot: dict, span: dict) -> bool:
    source = resolve_pointer(snapshot, span["json_pointer"])
    if span["coordinate_system"] == "json_scalar":
        return type(source) in (int, float) and str(source) == span["exact_text"]
    return isinstance(source, str) and source[span["start"]:span["end"]] == span["exact_text"]


def segment(text: str, base: dict, max_chars: int = 700) -> list[dict]:
    """Exact non-overlapping windows; no source text is altered or discarded."""
    if not text:
        return []
    windows = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            split = max(text.rfind("\n", start + 1, end), text.rfind(". ", start + 1, end))
            if split > start + max_chars // 3:
                end = split + (2 if text[split:split + 2] == ". " else 1)
        unit = {**base, "start": start, "end": end, "text": text[start:end]}
        unit["evidence_unit_id"] = hashlib.sha256((base["json_pointer"] + ":" + str(start) + ":" + str(end)).encode()).hexdigest()[:24]
        windows.append(unit)
        start = end
    return windows


def _rich_units(snapshot: dict, path: list[str], rich: list, base: dict) -> list[dict]:
    units = []
    for i, item in enumerate(rich):
        if isinstance(item, dict) and isinstance(item.get("plain_text"), str):
            units.extend(segment(item["plain_text"], {**base, "json_pointer": pointer(path + [str(i), "plain_text"]) }))
    return units


def notion_units(snapshot: dict) -> tuple[list[dict], list[dict]]:
    units, fields = [], []
    content = snapshot["content"]
    page = content.get("page", {})
    author = (page.get("created_by") or {}).get("name")
    for name, prop in page.get("properties", {}).items():
        typ = prop.get("type")
        base = {"property_name": name, "property_id": prop.get("id"), "source_part": "notion_property",
                "source_author": author}
        if typ in ("title", "rich_text"):
            units.extend(_rich_units(snapshot, ["content", "page", "properties", name, typ], prop.get(typ) or [], base))
        elif typ == "date" and (prop.get("date") or {}).get("start"):
            path = ["content", "page", "properties", name, "date", "start"]
            units.extend(segment(prop["date"]["start"], {**base, "json_pointer": pointer(path), "structured_type": "date"}))
        elif typ in ("select", "multi_select"):
            selections = prop.get(typ) or []
            selections = selections if isinstance(selections, list) else [selections]
            for i, selected in enumerate(selections):
                if isinstance(selected, dict) and isinstance(selected.get("name"), str):
                    path = ["content", "page", "properties", name, typ] + ([str(i)] if typ == "multi_select" else []) + ["name"]
                    units.extend(segment(selected["name"], {**base, "json_pointer": pointer(path), "structured_type": typ}))
        fields.append({"property_name": name, "property_id": prop.get("id"), "type": typ,
                       "status": "considered" if typ not in ("created_by", "last_edited_by") else "metadata_only",
                       "reason": "provider_authorship_metadata" if typ in ("created_by", "last_edited_by") else None})

    def walk(items: list, path: list[str]) -> None:
        for index, tree in enumerate(items):
            block = tree.get("block", {})
            kind = block.get("type")
            bpath = path + [str(index), "block"]
            rich = (block.get(kind) or {}).get("rich_text") if kind else None
            if isinstance(rich, list):
                units.extend(_rich_units(snapshot, bpath + [kind, "rich_text"], rich,
                                         {"source_part": "notion_block", "block_id": block.get("id"),
                                          "block_type": kind, "source_author": author}))
            fields.append({"block_id": block.get("id"), "type": kind, "status": "considered"})
            walk(tree.get("children") or [], path + [str(index), "children"])
    walk(content.get("blocks") or [], ["content", "blocks"])
    return units, fields


def airtable_units(snapshot: dict, schema: dict) -> tuple[list[dict], list[dict]]:
    content = snapshot["content"]
    table_id = content["table_id"]
    table = next((t for t in schema["tables"] if t["id"] == table_id), None)
    if table is None:
        raise ValueError("Airtable table missing from preserved schema")
    values = content["record"].get("fields", {})
    units, fields = [], []
    for field in table["fields"]:
        fid, name, typ = field["id"], field["name"], field["type"]
        value = values.get(fid)
        reason = None
        if re.search(r"(?:draft|initial email body|follow-up email|app message|email subject|attachment)", name, re.I):
            reason = "unsent_draft_or_attachment_no_sent_at"
        elif re.search(r"(?:logo|photo|\(AI\)|\bAI\b|Gemini|probability|assessment)", name, re.I):
            reason = "display_or_ai_annotation_not_customer_fact"
        elif typ == "multipleRecordLinks":
            reason = "provider_relation_ids_identity_context_only"
        elif value is None or value == "" or value == []:
            reason = "empty_or_absent_not_negative_evidence"
        status = "excluded_semantic_with_reason" if reason else "considered"
        fields.append({"table_id": table_id, "record_id": content["record"]["id"], "field_id": fid,
                       "field_name": name, "field_type": typ, "status": status,
                       "reason": reason, "present": fid in values, "empty": value in (None, "", [])})
        if reason:
            continue
        base = {"source_part": "airtable_field", "table_id": table_id, "field_id": fid,
                "field_name": name, "field_type": typ, "json_pointer": pointer(["content", "record", "fields", fid])}
        if isinstance(value, str):
            units.extend(segment(value, base))
        elif type(value) in (int, float):
            # JSON number coordinates are a whole scalar, never a fabricated substring.
            item = {**base, "start": 0, "end": 0, "text": str(value), "structured_scalar": value,
                    "evidence_unit_id": hashlib.sha256(base["json_pointer"].encode()).hexdigest()[:24]}
            units.append(item)
        elif isinstance(value, list):
            for i, entry in enumerate(value):
                if isinstance(entry, str):
                    units.extend(segment(entry, {**base, "json_pointer": base["json_pointer"] + "/" + str(i)}))
    return units, fields


def candidate(env: dict, unit: dict, span: dict, predicate: str, value: Any, route: str,
              *, validation: str = "auto_accepted_extraction", reason: str | None = None,
              more: dict | None = None) -> dict:
    seed = json.dumps([env["provider"], env["native_id"], env["content_hash"], span, predicate, value],
                      ensure_ascii=False, sort_keys=True)
    return {"candidate_id": hashlib.sha256(seed.encode()).hexdigest()[:24],
            "provider": env["provider"], "native_object_type": env["native_object_type"],
            "native_source_id": env["native_id"], "content_hash": env["content_hash"],
            "raw_snapshot_path": env["raw_snapshot_path"], "evidence_unit_id": unit["evidence_unit_id"],
            "evidence_span": span, "predicate": predicate, "value": value, "polarity": "asserted",
            "event_type": None, "contract_kind": None, "signal_family": None, "monetary": None,
            "business_date": None, "source_author": unit.get("source_author"),
            "authorship": "unknown", "account_candidate_id": None,
            "opportunity_candidate_id": None, "unresolved_alias": env.get("source_title"),
            "extraction_route": route, "extractor_version": VERSION,
            "rule_version": RULE_VERSION if route == "rule" else None,
            "extraction_confidence": "high" if route == "deterministic" else "medium",
            "extraction_stability": None,
            "validation_status": validation, "review_reason": reason,
            "independence_group": f"{env['provider']}:{env['native_id']}",
            "verified_signed": None, "VerifiedActualUSD": None, **(more or {})}


def _text_claims(env: dict, unit: dict, snapshot: dict, context_text: str = "") -> list[dict]:
    text = unit["text"]
    if not text or (not BUSINESS.search(text) and unit.get("structured_type") != "date"
                    and unit.get("field_name") not in ("Deal Stage", "Close Date", "Created Date", "Stage Entered Date", "Amount")):
        return []
    if "structured_scalar" in unit:
        if unit.get("field_name") == "Amount":
            span = {"json_pointer": unit["json_pointer"], "start": None, "end": None,
                    "exact_text": str(unit["structured_scalar"]), "coordinate_system": "json_scalar",
                    "field_id": unit.get("field_id"), "field_name": unit.get("field_name"),
                    "table_id": unit.get("table_id")}
            if validate_span(snapshot, span):
                return [candidate(env, unit, span, "crm_amount_untyped", unit["structured_scalar"], "deterministic",
                                  validation="review_required", reason="crm_amount_contract_kind_period_and_currency_unverified",
                                  more={"monetary": {"amount": unit["structured_scalar"], "currency": None,
                                                     "period": None, "value_type": "unknown", "status": "crm_snapshot"}})]
        return []
    found = []
    labels = rules(text)
    for field, label in labels.items():
        if label in UNKNOWN or field == "commercial_contract_status" or field == "contract_kind":
            continue
        # The rule's input is the exact bounded unit. Its full span is retained so a reviewer sees context.
        span = exact_span(unit, text, 0)
        if validate_span(snapshot, span):
            high = field == "pilot_contract_status" and label == "signed"
            found.append(candidate(env, unit, span, field, label, "rule",
                                   validation="review_required" if high else "auto_accepted_extraction",
                                   reason="pilot_signature_requires_contract_kind_review" if high else None,
                                   more={"contract_kind": "pilot" if field == "pilot_contract_status" else None,
                                         "signal_family": field if field in ("blocker_state", "buyer_involvement", "next_step_strength", "procurement_legal", "data_access") else None}))
    for match in MONEY.finditer(text):
        symbol = match.group("symbol") or match.group("code")
        currency = {"$": "USD", "€": "EUR", "£": "GBP"}.get(symbol, symbol.upper())
        number = match.group("number") or match.group("code_number")
        scale = match.group("scale") or match.group("code_scale")
        period = "annual" if re.search(r"(?:/yr|per year|annual|ACV)", text[match.end():match.end()+18], re.I) else None
        value_type = "unknown"  # Linking an amount to pilot, rollout, or TCV needs context/review.
        span = exact_span(unit, match.group(), match.start())
        if validate_span(snapshot, span):
            material = bool(COMPLEX.search(text) or (SIGNATURE_CUE.search(text) and re.search(r"commercial|rollout|/yr", text, re.I)))
            found.append(candidate(env, unit, span, "monetary_mention", match.group(), "deterministic",
                                   validation="review_required" if material else "auto_accepted_extraction",
                                   reason="amount_scope_or_period_linkage_unresolved" if material else None,
                                   more={"monetary": {"amount_text": number, "scale": scale,
                                                      "currency": currency, "period": period,
                                                      "value_type": value_type, "status": "mentioned_unverified"}}))
    for match in DATE.finditer(text):
        span = exact_span(unit, match.group(), match.start())
        if validate_span(snapshot, span):
            found.append(candidate(env, unit, span, "explicit_date_mention", match.group(), "deterministic",
                                   more={"business_date": match.group(), "date_role": "meeting_date" if unit.get("property_name") == "Date" else
                                         unit.get("field_name") or "unresolved_from_context"}))
    if unit.get("field_name") == "Deal Stage":
        span = exact_span(unit, text, 0)
        if validate_span(snapshot, span):
            found.append(candidate(env, unit, span, "crm_stage_snapshot", text, "deterministic",
                                   more={"assertion_type": "crm_snapshot", "contract_kind": None}))
    negative = re.search(r"(?:commercial|rollout|deployment|commercial contract).{0,40}\b(?:not signed|unsigned|no signature)\b|\b(?:not signed|unsigned)\b.{0,25}\bcommercial\b", text, re.I)
    if negative:
        span = exact_span(unit, negative.group(), negative.start())
        if validate_span(snapshot, span):
            found.append(candidate(env, unit, span, "commercial_contract_status", "not_signed_reported", "rule",
                                   validation="review_required", reason="commercial_status_requires_context_review",
                                   more={"contract_kind": "commercial", "polarity": "negative"}))
    # A generic unsigned contract can refer to a pilot. Retain the statement
    # only as a review proposal when separate, same-object context suggests
    # commercial pricing; the reviewer must resolve the contract kind.
    generic_unsigned = re.search(r"\bcontract\s+(?:is\s+)?(?:not signed|unsigned)\b", text, re.I)
    if generic_unsigned and not negative and re.search(r"\b(?:annual fee|commercial pricing|rollout pricing)\b", context_text, re.I):
        span = exact_span(unit, generic_unsigned.group(), generic_unsigned.start())
        if validate_span(snapshot, span):
            found.append(candidate(env, unit, span, "contract_status", "not_signed_reported", "rule",
                                   validation="review_required", reason="unsigned_contract_kind_requires_review",
                                   more={"contract_kind": None, "polarity": "negative",
                                         "assertion_type": "source_report", "rule_version": C2_RULE_VERSION}))
    return found


def _jev_questions(text: str, policy: dict) -> dict[str, Any]:
    fields = []
    if re.search(r"block|pushback|not approved|no reply|waiting|resolved", text, re.I):
        fields.append("blocker_state")
    if re.search(r"pilot|commercial|rollout|contract|signed|SOW|agreement", text, re.I):
        fields.append("contract_kind")
    if SIGNATURE_CUE.search(text) and re.search(r"commercial|rollout|annual|/yr|contract", text, re.I):
        fields.append("commercial_contract_status")
    return {name: choice_question(*RUBRICS[name]) for name in fields if name in policy["field_routes"]}


def _jev_for_unit(env: dict, unit: dict, snapshot: dict, policy: dict, k: int) -> tuple[list[dict], dict | None]:
    text = unit["text"]
    q = _jev_questions(text, policy)
    if not q:
        return [], None
    batch = run_batch(text, q, k)
    batch_record = {"source_id": env["native_id"], "evidence_unit_id": unit["evidence_unit_id"],
                    "questions": list(q), **batch}
    if batch["aggregate"] is None:
        return [], batch_record
    found = []
    for field, aggregate in batch["aggregate"].items():
        label = aggregate["aggregate_choice"]
        if label in UNKNOWN:
            continue
        setting = policy["field_routes"][field]
        validated_route = setting["route"] == "jev_ensemble"
        threshold = setting.get("threshold") or policy.get("candidate_threshold") or .95
        stable = aggregate["mean_probabilities"][label] >= threshold and aggregate["top_choice_agreement_rate"] == 1.0
        route = "jev_ensemble"
        if field == "commercial_contract_status" and label == "signed":
            stable = commercial_signature_gate(batch, max(.95, threshold))
            if not stable:
                continue
            label = "reported_signed_pending_verification"
        elif setting["route"] == "jev_single":
            first = batch["runs"][0]["raw_response"]["answers"][field]
            label = first["choice"]
            stable = (label not in UNKNOWN and first["probabilities"][label] >= threshold
                      and first["confidence"] >= threshold)
            route = "jev_single"
            if field == "contract_kind" and re.search(r"\bpilot\b", text, re.I) and re.search(r"\bcommercial\b|\brollout\b", text, re.I):
                stable = False
        elif not (validated_route and stable):
            continue  # Repetition is diagnostic, not an unvalidated route promotion.
        if not stable:
            continue
        span = exact_span(unit, text, 0)
        if not validate_span(snapshot, span):
            continue
        high = field == "commercial_contract_status" or (field == "contract_kind" and label == "amendment")
        found.append(candidate(env, unit, span, field, label, route,
                               validation="review_required" if high else "auto_accepted_extraction",
                               reason="reported_signature_requires_documentary_verification" if field == "commercial_contract_status" else
                                      "contract_amendment_requires_review" if high else None,
                               more={"contract_kind": "commercial" if field == "commercial_contract_status" else label if field == "contract_kind" else None,
                                     "signal_family": field if field == "blocker_state" else None,
                                     "extraction_confidence": "high",
                                     "extraction_stability": aggregate["top_choice_agreement_rate"],
                                     "jev": {"requested_k": k, "runs": batch["runs"], "aggregate": aggregate,
                                             "resolved_models": sorted({r["resolved_model"] for r in batch["runs"]}),
                                             "adapter_version": JEV_ADAPTER_VERSION}}))
    return found, batch_record


def _read_snapshot(env: dict) -> dict:
    path = (ROOT / env["raw_snapshot_path"]).resolve()
    if not path.is_relative_to((ROOT / "data/raw").resolve()) or not path.is_file():
        raise ValueError("missing_or_unsafe_snapshot_path")
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    if content_hash(stable_provider_content(env["provider"], snapshot["content"])) != env["content_hash"]:
        raise ValueError("snapshot_content_hash_mismatch")
    if snapshot.get("retrieval_provenance", {}).get("complete_pagination") is False:
        raise ValueError("incomplete_snapshot_provenance")
    return snapshot


def _identity_catalog(envelopes: list[dict], schema: dict) -> dict:
    """Source-native candidate IDs only; no canonical identity inference."""
    tables = {t["id"]: t for t in schema["tables"]}
    catalog = {"accounts": [], "contacts": [], "opportunities": []}
    for env in envelopes:
        if env["provider"] != "airtable" or env["native_object_type"] != "record":
            continue
        snapshot = _read_snapshot(env)
        content = snapshot["content"]
        table = tables[content["table_id"]]
        values = content["record"].get("fields", {})
        by_name = {field["name"]: values.get(field["id"]) for field in table["fields"]}
        name = (by_name.get("Company Name") or by_name.get("Full Name") or by_name.get("Deal Name"))
        if not isinstance(name, str) or not name.strip():
            continue
        if table["name"] == "Companies":
            catalog["accounts"].append({"id": env["native_id"], "name": name})
        elif table["name"] == "Contacts":
            catalog["contacts"].append({"id": env["native_id"], "name": name,
                                        "company_record_ids": by_name.get("Company") or []})
        elif table["name"] == "Deals":
            catalog["opportunities"].append({"id": env["native_id"], "name": name,
                                             "account_record_ids": by_name.get("Company") or []})
    return catalog


def _identity_context(env: dict, snapshot: dict, catalog: dict, note: dict) -> dict:
    title = env.get("source_title") or ""
    properties = snapshot["content"].get("page", {}).get("properties", {})
    attendees = [x.get("name", "") for x in (properties.get("Attendees", {}).get("multi_select") or [])]
    haystack = title + "\n" + "\n".join(attendees) + "\n" + note["text"]
    def mentioned(name: str) -> bool:
        return len(name.strip()) >= 4 and bool(re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", haystack, re.I))
    first_tokens = [re.split(r"\W+", item["name"].strip())[0].casefold() for item in catalog["accounts"]]
    token_counts = Counter(first_tokens)
    accounts = [item for item, token in zip(catalog["accounts"], first_tokens)
                if mentioned(item["name"]) or (len(token) >= 5 and token_counts[token] == 1
                                              and mentioned(token))]
    account_ids = {item["id"] for item in accounts}
    contacts = [item for item in catalog["contacts"] if mentioned(item["name"]) or
                bool(account_ids.intersection(item.get("company_record_ids") or []))]
    # A full contact name may nominate its linked company; first names never do.
    linked_accounts = {aid for item in contacts if mentioned(item["name"])
                       for aid in item.get("company_record_ids", [])}
    accounts = [item for item in catalog["accounts"] if item["id"] in account_ids | linked_accounts]
    account_ids = {item["id"] for item in accounts}
    opportunities = [item for item in catalog["opportunities"] if
                     mentioned(item["name"]) or bool(account_ids.intersection(item.get("account_record_ids") or []))]
    return {"accounts": accounts, "contacts": contacts[:30], "opportunities": opportunities[:20],
            "title": title, "meeting_date": (properties.get("Date", {}).get("date") or {}).get("start"),
            "participants": attendees}


def _semantic_claims(env: dict, snapshot: dict, semantic: dict, identity: dict) -> list[dict]:
    claims = []
    for item in semantic["accepted"]:
        category, data, span = item["collection"], item["data"], item["evidence_span"]
        if category == "abstentions":
            continue
        if not validate_span(snapshot, span):
            raise ValueError("semantic_span_snapshot_mismatch")
        unit = {"evidence_unit_id": span["evidence_unit_id"], "source_author":
                (snapshot["content"]["page"].get("created_by") or {}).get("name")}
        if category == "atomic_signals":
            # Soft signals are evidence for inference, not review; only a reported
            # commercial signature keeps the existing signature review gate.
            high = data.get("signal_type") == "reported_signature" and data.get("contract_kind") == "commercial"
        else:
            high = (category == "events" and data.get("event_type") == "commercial_signed"
                    or category == "commercial_values" and data.get("status") == "signed_reported"
                    or category == "opportunity_candidates" and data.get("relationship") in ("alternative", "conditional")
                    or category in ("commercial_values", "opportunity_candidates") and len(identity["accounts"]) > 1
                    or data.get("contract_kind") == "amendment")
        label = (data.get("signal_type") or data.get("event_type") or data.get("family") or data.get("value_type") or
                 data.get("relation") or data.get("predicate") or category)
        call = next((run for run in semantic["calls"]
                     if run.get("status") == "completed" and run["chunk_start"] <= span["global_start"]
                     and span["global_end"] <= run["chunk_end"]), {})
        claim = candidate(env, unit, span, category, label, "llm",
                          validation="review_required" if high else "semantic_validated_proposal",
                          reason="semantic_high_impact_requires_review" if high else None,
                          more={"semantic_schema_version": SCHEMA_VERSION,
                                "semantic_model": {key: call.get(key) for key in
                                                   ("requested_model", "resolved_model", "usage", "latency_ms")},
                                "semantic_payload": data, "account_candidate_id": data.get("account_candidate_id"),
                                "opportunity_candidate_id": data.get("opportunity_candidate_id"),
                                "event_type": data.get("event_type"), "polarity": data.get("polarity"),
                                "signal_type": data.get("signal_type"), "modality": data.get("modality"),
                                "contract_kind": data.get("contract_kind"),
                                "signal_family": data.get("family"),
                                "business_date": data.get("event_date") or data.get("effective_date"),
                                "monetary": {key: data.get(key) for key in ("amount", "currency", "unit", "value_type", "status", "scenario_relation")}
                                if category == "commercial_values" else None})
        if category == "opportunity_candidates":
            claim["opportunity_candidate_id"] = "provisional:" + claim["candidate_id"]
        claims.append(claim)
    return claims


def _verify_semantic_claims(claims: list[dict], k: int) -> list[dict]:
    """Jev is a diagnostic verifier of narrow, exact semantic spans, never a parser."""
    records = []
    for claim in claims:
        if claim.get("semantic_schema_version") != SCHEMA_VERSION:
            continue
        data = claim["semantic_payload"]
        if claim["predicate"] == "atomic_signals":
            # Narrow sensors over the exact span; a failed batch yields no readings and no review.
            sensors = jev_sensors.questions_for(data.get("signal_type"))
            if sensors:
                batch = run_batch(claim["evidence_span"]["exact_text"], sensors, k)
                claim["jev_sensor"] = {"readings": jev_sensors.readings(batch), "questions": list(sensors), **batch}
                records.append({"source_id": claim["native_source_id"], "candidate_id": claim["candidate_id"],
                                "questions": list(sensors), "purpose": "belief_sensor", **batch})
            continue
        question = None
        if claim["predicate"] == "events":
            question = {
                "pilot_signed": "pilot_contract_status",
                "pilot_verbal_yes": "pilot_contract_status",
                "commercial_signed": "commercial_contract_status",
                "commercial_proposal_sent": "commercial_contract_status",
                "procurement_legal_started": "procurement_legal",
                "blocker_opened": "blocker_state", "blocker_resolved": "blocker_state",
            }.get(data.get("event_type"))
        elif claim["predicate"] == "commercial_values" and data.get("value_type") in ("pilot_fee", "rollout_acv", "tcv"):
            question = "contract_kind"
        if question not in RUBRICS:
            continue
        questions = {question: choice_question(*RUBRICS[question])}
        batch = run_batch(claim["evidence_span"]["exact_text"], questions, k)
        claim["jev_verification"] = {"question": question, **batch}
        records.append({"source_id": claim["native_source_id"], "candidate_id": claim["candidate_id"],
                        "questions": [question], **batch})
        if batch["aggregate"] is None:
            claim["validation_status"] = "review_required"
            claim["review_reason"] = "jev_verification_failed"
        elif data.get("event_type") == "commercial_signed" and not commercial_signature_gate(batch, .95):
            claim["validation_status"] = "review_required"
            claim["review_reason"] = "reported_commercial_signature_jev_gate_unmet"
    return records


def _process(env: dict, schema: dict, policy: dict, k: int, use_jev: bool, llm: str,
             catalog: dict | None = None) -> dict:
    row = {"provider": env["provider"], "native_object_type": env["native_object_type"],
           "native_id": env["native_id"], "content_hash": env["content_hash"],
           "raw_snapshot_path": env["raw_snapshot_path"], "disposition": None,
           "evidence_unit_count": 0, "field_count": 0, "empty_field_count": 0,
           "excluded_field_count": 0, "reason": None}
    if not env.get("content_complete"):
        row.update(disposition="abstained", reason="a2_incomplete_source")
        return {"coverage": row, "claims": [], "fields": [], "jev": [], "llm": [], "semantic": None}
    try:
        snapshot = _read_snapshot(env)
        if (env["provider"], env["native_object_type"]) in TRANSPORT_TYPES:
            row.update(disposition="transport_only", reason="provider_schema_transport_object")
            return {"coverage": row, "claims": [], "fields": [], "jev": [], "llm": [], "semantic": None}
        if env["provider"] == "notion" and env["native_object_type"] == "page":
            units, fields = notion_units(snapshot)
        elif env["provider"] == "airtable" and env["native_object_type"] == "record":
            units, fields = airtable_units(snapshot, schema)
        else:
            row.update(disposition="excluded_by_schema_with_reason", reason="unsupported_provider_object_schema")
            return {"coverage": row, "claims": [], "fields": [], "jev": [], "llm": [], "semantic": None}
        row["evidence_unit_count"] = len(units)
        row["field_count"] = len(fields)
        row["empty_field_count"] = sum(f.get("empty", False) for f in fields)
        row["excluded_field_count"] = sum(f.get("status") == "excluded_semantic_with_reason" for f in fields)
        claims, jev_records, llm_records = [], [], []
        semantic_record = None
        if env["provider"] == "notion" and env["native_object_type"] == "page" and (env.get("schema_ref") or "").startswith("notion/data_source/"):
            note = normalize_note(units)
            identity = _identity_context(env, snapshot, catalog or {"accounts": [], "contacts": [], "opportunities": []}, note)
            response = extract_semantic(note, identity) if note["text"] else {
                "status": "empty_body", "accepted": [], "rejected": [], "calls": []}
            semantic_record = {"source_id": env["native_id"], "body_length": len(note["text"]),
                               "body_segment_count": len(note["segments"]),
                               "identity_candidate_counts": {key: len(identity[key]) for key in ("accounts", "contacts", "opportunities")},
                               **response}
            claims.extend(_semantic_claims(env, snapshot, response, identity))
            if use_jev and response["status"] == "completed":
                jev_records.extend(_verify_semantic_claims(claims, k))
        context_text = "\n".join(unit["text"] for unit in units if isinstance(unit.get("text"), str))
        for unit in units:
            claims.extend(_text_claims(env, unit, snapshot, context_text))
            if use_jev and semantic_record is None and not unit.get("structured_scalar") and BUSINESS.search(unit["text"]):
                more, batch = _jev_for_unit(env, unit, snapshot, policy, k)
                claims.extend(more)
                if batch:
                    jev_records.append(batch)
            if llm == "auto" and semantic_record is None and COMPLEX.search(unit["text"]):
                response = extract_relations(unit["text"])
                llm_records.append({"evidence_unit_id": unit["evidence_unit_id"], **response})
                for relation in response["relations"]:
                    span = exact_span(unit, relation["quote"], relation["start"])
                    if validate_span(snapshot, span):
                        claims.append(candidate(env, unit, span, relation["predicate"], relation.get("object"), "llm",
                                                validation="review_required", reason="llm_relation_needs_review",
                                                more={"unresolved_alias": relation.get("subject"),
                                                      "contract_kind": relation.get("contract_kind"),
                                                      "llm": {key: value for key, value in response.items() if key != "relations"}}))
        unique = {c["candidate_id"]: c for c in claims}
        claims = list(unique.values())
        meeting_date = ((snapshot.get("content", {}).get("page", {}).get("properties", {}).get("Date") or {}).get("date") or {}).get("start")
        if meeting_date:
            for claim in claims:
                claim["source_meeting_date"] = meeting_date
        if semantic_record and semantic_record["status"] in ("provider_failure", "not_run_missing_credentials"):
            row.update(disposition="abstained", reason="required_semantic_extraction_failed")
        elif semantic_record and semantic_record["rejected"]:
            row.update(disposition="review_required", reason="semantic_post_validation_rejection")
        elif any(c["validation_status"] == "review_required" for c in claims):
            row["disposition"] = "review_required"
        elif any(r["status"] == "not_run_missing_credentials" for r in llm_records):
            row.update(disposition="abstained", reason="complex_relation_fallback_unavailable")
        elif claims:
            row["disposition"] = "extracted"
        elif semantic_record and any(x["collection"] == "abstentions" for x in semantic_record["accepted"]):
            row.update(disposition="abstained", reason="semantic_abstention")
        elif any(j["failures"] for j in jev_records):
            row.update(disposition="abstained", reason="jev_batch_failed")
        else:
            row["disposition"] = "no_business_evidence"
        return {"coverage": row, "claims": claims, "fields": fields, "jev": jev_records, "llm": llm_records,
                "semantic": semantic_record}
    except (ValueError, KeyError, OSError, TypeError, AttributeError, json.JSONDecodeError) as exc:
        row.update(disposition="abstained", reason=f"source_read_or_schema_failure:{type(exc).__name__}:{str(exc)[:80]}")
        return {"coverage": row, "claims": [], "fields": [], "jev": [], "llm": [], "semantic": None}


def coverage_gate(report: dict) -> bool:
    rows = report.get("source_coverage")
    if not isinstance(rows, list) or not isinstance(report.get("manifest_source_count"), int):
        return False
    expected = report.get("expected_by_provider_object_type")
    observed = dict(Counter(f"{row.get('provider')}/{row.get('native_object_type')}" for row in rows))
    dispositions = dict(Counter(row.get("disposition") for row in rows))
    duplicates = duplicate_coverage_rows(rows)
    return bool(report.get("extraction_executed") is True
                and report.get("manifest_complete") is True
                and report["manifest_source_count"] == report.get("considered_source_count") == len(rows)
                and expected == report.get("considered_by_provider_object_type") == observed
                and report.get("disposition_counts") == dispositions
                and report.get("unaccounted_source_count") == 0
                and report.get("unaccounted_source_list") == []
                and report.get("duplicate_coverage_count") == 0
                and report.get("duplicate_coverage_list") == duplicates == []
                and not report.get("incomplete_source_warnings")
                and all(row.get("disposition") in ALLOWED for row in rows))


def duplicate_coverage_rows(rows: list[dict]) -> list[list[str]]:
    keys = [(r["provider"], r["native_id"], r["content_hash"]) for r in rows]
    return [list(key) for key, count in Counter(keys).items() if count > 1]


def _review_queue(claims: list[dict]) -> dict:
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for claim in claims:
        if claim["validation_status"] == "review_required":
            group = (claim.get("unresolved_alias") or claim["native_source_id"], claim["review_reason"])
            grouped[group].append(claim)
    items = []
    for (alias, reason), group in grouped.items():
        evidence = {(c["native_source_id"], c["evidence_span"]["exact_text"]):
                    {"source_id": c["native_source_id"], "span": c["evidence_span"],
                     "candidate_id": c["candidate_id"]} for c in group}
        material = [c["monetary"] for c in group if c.get("monetary")]
        items.append({"review_id": hashlib.sha256((str(alias) + str(reason)).encode()).hexdigest()[:20],
                      "account_or_opportunity_alias": alias, "reason": reason,
                      "candidate_ids": [c["candidate_id"] for c in group],
                      "supporting_or_conflicting_evidence": list(evidence.values()),
                      "financial_materiality": material or None,
                      "single_decision_needed": "Confirm the exact contract, scope, and amount linkage from source documents" if material else
                      "Decide whether the unsigned statement refers to a pilot or commercial contract" if reason == "unsigned_contract_kind_requires_review" else
                      "Decide whether the cited evidence supports this reported status or relation"})
    return {"summary": {"review_item_count": len(items), "candidate_count": sum(map(len, grouped.values())),
                        "reasons": dict(Counter(item["reason"] for item in items))}, "items": items}


def semantic_gate(report: dict) -> bool:
    """Rejected proposals are explicit review, never accepted evidence or silent failures."""
    return bool(report["selected_meeting_notes"] == report["bodies_dispositioned"]
                and report["semantic_attempts"] > 0
                and report["opportunity_candidate_count"] > 0 and report["event_candidate_count"] > 0
                and report["resolved_account_link_count"] > 0
                and report["span_validation_failures"] == 0
                and report["forbidden_verification_attempt_count"] == 0
                and set(report["status_counts"]) <= {"completed", "empty_body"}
                and report["source_coverage_gate_passed"])


def run(manifest_path: Path, output_dir: Path, *, require_jev: bool, jev_repeats: int,
        llm: str, max_concurrency: int) -> int:
    load_env()
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("C2 semantic bridge requires OPENAI_API_KEY for the production live run")
    if require_jev and not os.getenv("JEV_API_KEY"):
        raise RuntimeError("--require-jev requires JEV_API_KEY")
    raw_manifest = manifest_path.read_bytes()
    manifest = json.loads(raw_manifest)
    envelopes = manifest["envelopes"]
    schema_path = ROOT / "data/raw" / manifest["run_id"] / "airtable/schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    policy = json.loads((ROOT / "outputs/B/routing_policy.json").read_text(encoding="utf-8"))
    catalog = _identity_catalog(envelopes, schema)
    results = [None] * len(envelopes)
    with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
        futures = {pool.submit(_process, env, schema, policy, jev_repeats,
                               bool(os.getenv("JEV_API_KEY")), llm, catalog): i for i, env in enumerate(envelopes)}
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    rows = [r["coverage"] for r in results]
    expected = Counter(f"{e['provider']}/{e['native_object_type']}" for e in envelopes)
    considered = Counter(f"{r['provider']}/{r['native_object_type']}" for r in rows)
    ids = [(r["provider"], r["native_id"], r["content_hash"]) for r in rows]
    duplicates = duplicate_coverage_rows(rows)
    unaccounted = [e for e in envelopes if (e["provider"], e["native_id"], e["content_hash"]) not in ids]
    incomplete = [{"source_id": r["native_id"], "reason": r["reason"]} for r in rows
                  if r["reason"] and (r["reason"].startswith("a2_incomplete") or r["reason"].startswith("source_read"))]
    report = {"a2_run_id": manifest["run_id"], "source_manifest_path": str(manifest_path),
              "source_manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
              "extraction_executed": True,
              "manifest_complete": manifest.get("complete") is True,
              "manifest_source_count": len(envelopes), "considered_source_count": len(rows),
              "expected_by_provider_object_type": dict(expected), "considered_by_provider_object_type": dict(considered),
              "disposition_counts": dict(Counter(r["disposition"] for r in rows)),
              "text_unit_count": sum(r["evidence_unit_count"] for r in rows),
              "field_count": sum(r["field_count"] for r in rows),
              "empty_field_count": sum(r["empty_field_count"] for r in rows),
              "excluded_field_count": sum(r["excluded_field_count"] for r in rows),
              "field_coverage": [{"source_id": e["native_id"], "provider": e["provider"], "fields": r["fields"]}
                                 for e, r in zip(envelopes, results) if r["fields"]],
              "source_coverage": rows, "unaccounted_source_list": unaccounted,
              "unaccounted_source_count": len(unaccounted),
              "duplicate_coverage_list": duplicates, "duplicate_coverage_count": len(duplicates),
              "incomplete_source_warnings": incomplete}
    report["coverage_gate_passed"] = coverage_gate(report)
    claims = [claim for r in results for claim in r["claims"]]
    semantic_records = [r["semantic"] for r in results if r["semantic"] is not None]
    semantic_claims = [c for c in claims if c.get("semantic_schema_version") == SCHEMA_VERSION]
    semantic = {"schema_version": SCHEMA_VERSION,
                "requested_model": os.getenv("OPENAI_SEMANTIC_MODEL") or "gpt-6-luna",
                "selected_meeting_notes": sum(e["provider"] == "notion" and e["native_object_type"] == "page" and
                                              (e.get("schema_ref") or "").startswith("notion/data_source/") for e in envelopes),
                "bodies_dispositioned": len(semantic_records),
                "bodies_inspected": sum(r["body_length"] > 0 for r in semantic_records),
                "semantic_attempts": sum(len(r["calls"]) for r in semantic_records),
                "status_counts": dict(Counter(r["status"] for r in semantic_records)),
                "sources_with_business_claims": len({c["native_source_id"] for c in semantic_claims}),
                "opportunity_candidate_count": sum(c["predicate"] == "opportunity_candidates" for c in semantic_claims),
                "event_candidate_count": sum(c["predicate"] == "events" for c in semantic_claims),
                "events_by_type": dict(Counter(c["event_type"] for c in semantic_claims if c["event_type"])),
                "signals_by_family": dict(Counter(c["signal_family"] for c in semantic_claims if c["signal_family"])),
                "commercial_value_count": sum(c["predicate"] == "commercial_values" for c in semantic_claims),
                "resolved_account_link_count": sum(c["account_candidate_id"] is not None for c in semantic_claims),
                "unresolved_account_link_count": sum(c["account_candidate_id"] is None for c in semantic_claims),
                "unresolved_opportunity_link_count": sum(c["opportunity_candidate_id"] is None for c in semantic_claims),
                "resolved_opportunity_link_count": sum(c["opportunity_candidate_id"] is not None and
                                                       not str(c["opportunity_candidate_id"]).startswith("provisional:")
                                                       for c in semantic_claims),
                "provisional_opportunity_candidate_count": sum(c["predicate"] == "opportunity_candidates" for c in semantic_claims),
                "span_validation_failures": sum(not validate_span(_read_snapshot(e), c["evidence_span"])
                                                for e, result in zip(envelopes, results) for c in result["claims"]
                                                if c.get("semantic_schema_version") == SCHEMA_VERSION),
                "span_validation_failure_definition": "Accepted semantic claims failing exact immutable-source validation; rejected model proposals are separately categorized below.",
                "rejected_proposal_count": sum(len(r["rejected"]) for r in semantic_records),
                "rejected_proposal_reasons": dict(Counter(x["reason"] for r in semantic_records for x in r["rejected"])),
                "forbidden_verification_attempt_count": sum(x["reason"] == "forbidden_verification_field"
                                                           for r in semantic_records for x in r["rejected"]),
                "source_coverage_gate_passed": report["coverage_gate_passed"],
                "provider_error_categories": dict(Counter(call.get("error_category", "unclassified_failure")
                                                          for r in semantic_records for call in r["calls"]
                                                          if call["status"] != "completed")),
                "model_abstention_count": sum(x["collection"] == "abstentions" for r in semantic_records
                                              for x in r["accepted"]),
                "jev_verification_count": sum("jev_verification" in c for c in semantic_claims),
                "atomic_signal_candidate_count": sum(c["predicate"] == "atomic_signals" for c in semantic_claims),
                "atomic_signals_by_type": dict(Counter(c["signal_type"] for c in semantic_claims
                                                       if c["predicate"] == "atomic_signals")),
                "jev_sensor_batch_count": sum("jev_sensor" in c for c in semantic_claims),
                "review_count": sum(c["validation_status"] == "review_required" for c in semantic_claims),
                "abstention_count": sum(r["status"] != "completed" for r in semantic_records),
                "model_usage_total": {key: sum(((call.get("usage") or {}).get(key) or 0) for r in semantic_records
                                                for call in r["calls"]) for key in ("input_tokens", "output_tokens")},
                "model_calls": [{"source_id": r["source_id"], **call} for r in semantic_records for call in r["calls"]],
                "source_dispositions": [{"source_id": r["source_id"], "status": r["status"],
                                         "body_length": r["body_length"], "rejected": r["rejected"]}
                                        for r in semantic_records]}
    semantic["semantic_gate_passed"] = semantic_gate(semantic)
    jev = [batch for r in results for batch in r["jev"]]
    llm_runs = [entry for r in results for entry in r["llm"]]
    runs = [item for batch in jev for item in batch["runs"]]
    latencies = [item["latency_ms"] for item in runs]
    agreements = [a["top_choice_agreement_rate"] for batch in jev if batch["aggregate"]
                  for a in batch["aggregate"].values() if a["type"] == "choice"]
    deviations = [v for batch in jev if batch["aggregate"] for a in batch["aggregate"].values()
                  if a["type"] == "choice" for v in a["std_probabilities"].values()]
    extraction = {"extraction_version": VERSION, "routing_policy_version": policy.get("policy_version"),
                  "candidate_claim_count": len(claims),
                  "claims_by_type": dict(Counter(c["predicate"] for c in claims)),
                  "claims_by_route": dict(Counter(c["extraction_route"] for c in claims)),
                  "jev_k": jev_repeats, "jev_batch_count": len(jev), "jev_call_count": len(runs),
                  "jev_batches": jev, "jev_resolved_models": sorted({r["resolved_model"] for r in runs}),
                  "jev_latency_mean_ms": statistics.fmean(latencies) if latencies else None,
                  "jev_latency_median_ms": statistics.median(latencies) if latencies else None,
                  "jev_usage_total": {key: sum((r["raw_response"].get("usage") or {}).get(key) or 0 for r in runs)
                                      for key in ("input_tokens", "output_tokens")},
                  "ensemble_mean_top_choice_agreement": statistics.fmean(agreements) if agreements else None,
                  "ensemble_mean_option_std": statistics.fmean(deviations) if deviations else None,
                  "jev_identical_batch_question_count": sum(a["identical_responses"] for batch in jev if batch["aggregate"]
                                                            for a in batch["aggregate"].values()),
                  "provider_failures": [f for batch in jev for f in batch["failures"]],
                  "llm_status": "not_run_missing_credentials" if llm == "auto" and not os.getenv("OPENAI_API_KEY") else
                                "disabled" if llm == "off" else "completed_or_reported_per_unit",
                  "llm_runs": llm_runs, "llm_call_count": sum(r["status"] != "not_run_missing_credentials" for r in llm_runs),
                  "abstention_count": report["disposition_counts"].get("abstained", 0),
                  "review_source_count": report["disposition_counts"].get("review_required", 0),
                  "abstention_reasons": dict(Counter(r["reason"] for r in rows if r["disposition"] == "abstained")),
                  "review_reasons": dict(Counter(c["review_reason"] for c in claims if c["review_reason"])),
                  "commercial_signature_candidate_count": sum(c["value"] == "reported_signed_pending_verification" for c in claims),
                  "verified_actual_mutations": 0,
                  "accuracy_claim": None,
                  "limitation": "Unlabeled full-corpus extraction does not establish generalized accuracy or calibrated probabilities."}
    dump(output_dir / "source_coverage_report.json", report)
    dump(output_dir / "candidate_claims.json", claims)
    semantic["candidate_artifact_sha256"] = hashlib.sha256((output_dir / "candidate_claims.json").read_bytes()).hexdigest()
    dump(output_dir / "semantic_extraction_report.json", semantic)
    review_queue = _review_queue(claims)
    review_queue["semantic_rejections"] = [{"source_id": r["source_id"], **item}
                                          for r in semantic_records for item in r["rejected"]]
    review_queue["semantic_failures"] = [call for call in semantic["model_calls"] if call["status"] != "completed"]
    review_queue["summary"]["rejected_proposal_count"] = semantic["rejected_proposal_count"]
    dump(output_dir / "review_queue.json", review_queue)
    dump(output_dir / "extraction_report.json", extraction)
    (output_dir / "implementation_report.md").write_text(
        f"# Stage C2 implementation report\n\nA2 run: `{manifest['run_id']}`. "
        f"Considered {len(rows)}/{len(envelopes)} source envelopes; coverage gate: **{'PASS' if report['coverage_gate_passed'] else 'FAIL'}**. "
        f"Created {len(claims)} anchored candidate claims and {_review_queue(claims)['summary']['review_item_count']} grouped review items.\n\n"
        f"Jev: {len(jev)} batches, {len(runs)} calls, K={jev_repeats}; failed batches abstain. "
        f"Semantic bridge: {semantic['bodies_dispositioned']}/{semantic['selected_meeting_notes']} meeting-note bodies dispositioned, "
        f"{semantic['opportunity_candidate_count']} opportunity and {semantic['event_candidate_count']} event candidates; "
        f"semantic gate: **{'PASS' if semantic['semantic_gate_passed'] else 'FAIL'}**. "
        f"LLM: {extraction['llm_status']}. No candidate can set verified signed or VerifiedActualUSD. "
        f"B policy allows ensemble auto acceptance only for validated fields; repeated results otherwise remain diagnostic. "
        f"Commercial signature proposals require unanimous K calls and always enter review.\n\n"
        f"This corpus is unlabeled; no generalized accuracy is claimed. Exact spans use immutable snapshot JSON pointers and codepoint offsets.\n",
        encoding="utf-8")
    return 0 if semantic["semantic_gate_passed"] and (not require_jev or not extraction["provider_failures"]) else 1


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-jev", action="store_true")
    parser.add_argument("--jev-repeats", type=int, default=int(os.getenv("JEV_REPEATS", "5")))
    parser.add_argument("--llm", choices=("auto", "off"), default="auto")
    parser.add_argument("--source-manifest", type=Path, default=ROOT / "outputs/A2/source_manifest.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/C2")
    parser.add_argument("--check-coverage", type=Path)
    args = parser.parse_args()
    if args.check_coverage:
        report = json.loads(args.check_coverage.read_text(encoding="utf-8"))
        semantic_path = args.check_coverage.with_name("semantic_extraction_report.json")
        semantic = json.loads(semantic_path.read_text(encoding="utf-8")) if semantic_path.is_file() else {}
        return 0 if coverage_gate(report) and semantic.get("semantic_gate_passed") is True else 1
    return run(args.source_manifest, args.output_dir, require_jev=args.require_jev,
               jev_repeats=args.jev_repeats, llm=args.llm,
               max_concurrency=max(1, min(16, int(os.getenv("JEV_MAX_CONCURRENCY", "3")),
                                      int(os.getenv("OPENAI_SEMANTIC_MAX_CONCURRENCY", "8")))))


if __name__ == "__main__":
    raise SystemExit(main())
