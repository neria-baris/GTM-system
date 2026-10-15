"""Source-anchored meeting-note extraction via OpenAI Responses Structured Outputs."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any

import httpx

from src.settings import seller_names

from .semantic_schema import (ACTORS, COLLECTIONS, CONTRACT_KINDS, EVENT_TYPES, POLARITIES,
                              SCHEMA_VERSION, SEMANTIC_SCHEMA, SIGNAL_FAMILIES, SIGNAL_MODALITIES,
                              SIGNAL_TYPES, VALUE_STATUSES, VALUE_TYPES)

URL = "https://api.openai.com/v1/responses"
ADAPTER_VERSION = "semantic_responses_1.2.0"
SELLER = " / ".join(seller_names()) or "the note authors' company"
INSTRUCTIONS = (
    "Extract only explicitly supported GTM facts from the supplied meeting note. "
    "Return all nine JSON arrays. Every object needs an exact verbatim quote from the "
    "submitted chunk, contained in one source string. Do not calculate offsets. Choose "
    "enough surrounding words to make the quote unique. Use only candidate IDs in the supplied "
    "identity context, or null when unresolved. An opportunity candidate may have a null "
    "existing ID; describe its use case and commercial scope from the note. Distinguish "
    "pilot verbal yes, SOW drafting/sent, pilot signed, and reported commercial signed. "
    "Do not infer missing journey steps, contractual verification, dates, amounts, currencies, "
    "or account identity. No USD conversion, ACV arithmetic, probability, or Verified Actual. "
    "Negated, conditional, hypothetical, and future plans retain their polarity. "
    "In atomic_signals, label each commercially meaningful statement with one closed signal_type and a "
    "modality: asserted (current fact), completed (past fact), planned, conditional, hypothetical, negated, "
    "or unclear. Planning is never execution; a conditional statement stays conditional. Set actor to "
    f"customer for the customer's own actions and seller for {SELLER}/seller actions or plans. "
    "effective_date only when the quote states that exact date. Never emit verification. "
    "Use abstentions for material ambiguity. Empty arrays are appropriate when unsupported. "
    "A line stating that a contract or deal was SIGNED (for example 'SIGNED. EUR580k/yr, 2-yr term') is an asserted "
    "reported_signature atomic signal; record it even when the account or contract kind is unclear."
)


def normalize_note(units: list[dict]) -> dict:
    """Join exact block strings; mapping retains each original JSON string coordinate."""
    parts, segments, cursor = [], [], 0
    previous_block = None
    for unit in units:
        if unit.get("source_part") != "notion_block" or not unit.get("text"):
            continue
        if parts and unit.get("block_id") != previous_block:
            parts.append("\n")
            cursor += 1
        start = cursor
        parts.append(unit["text"])
        cursor += len(unit["text"])
        segments.append({"global_start": start, "global_end": cursor,
                         "json_pointer": unit["json_pointer"], "source_start": unit["start"],
                         "block_id": unit.get("block_id"), "evidence_unit_id": unit["evidence_unit_id"]})
        previous_block = unit.get("block_id")
    return {"text": "".join(parts), "segments": segments}


def chunks(note: dict, max_chars: int = 6000, overlap_segments: int = 1) -> list[dict]:
    segments = note["segments"]
    if not segments:
        return []
    result, start = [], 0
    while start < len(segments):
        end = start + 1
        while end < len(segments) and segments[end]["global_end"] - segments[start]["global_start"] <= max_chars:
            end += 1
        a, b = segments[start]["global_start"], segments[end - 1]["global_end"]
        result.append({"start": a, "end": b, "text": note["text"][a:b]})
        if end == len(segments):
            break
        start = max(start + 1, end - overlap_segments)
    return result


def source_span(note: dict, item: dict, chunk: dict | None = None) -> dict:
    """Locate a unique literal quote in the submitted text; model offsets play no role."""
    chunk = chunk or {"start": 0, "end": len(note["text"]), "text": note["text"]}
    quote = item.get("quote")
    if not isinstance(quote, str) or not quote:
        raise ValueError("missing_exact_quote")
    if note["text"][chunk["start"]:chunk["end"]] != chunk["text"]:
        raise ValueError("invalid_submitted_chunk")
    relative = chunk["text"].find(quote)
    if relative < 0:
        raise ValueError("quote_absent_from_submitted_chunk")
    if chunk["text"].find(quote, relative + 1) >= 0:
        raise ValueError("ambiguous_repeated_quote")
    start = chunk["start"] + relative
    end = start + len(quote)
    for segment in note["segments"]:
        if segment["global_start"] <= start and end <= segment["global_end"]:
            offset = segment["source_start"] + start - segment["global_start"]
            return {"exact_text": quote, "start": offset, "end": offset + len(quote),
                    "json_pointer": segment["json_pointer"], "block_id": segment["block_id"],
                    "evidence_unit_id": segment["evidence_unit_id"], "global_start": start,
                    "global_end": end, "chunk_start": relative,
                    "chunk_end": relative + len(quote), "coordinate_system": "source_string_codepoints"}
    raise ValueError("span_crosses_source_strings")


def _date_supported(value: Any, quote: str) -> bool:
    return value is None or (isinstance(value, str) and value in quote and
                             bool(re.fullmatch(r"\d{4}-\d\d-\d\d", value)))


def _amount_supported(value: Any, quote: str) -> bool:
    if value is None:
        return True
    if type(value) not in (int, float):
        return False
    for match in re.finditer(r"(?<!\w)(\d[\d,]*(?:\.\d+)?)\s*([kKmM]?)(?!\w)", quote):
        number = float(match.group(1).replace(",", "")) * {"": 1, "k": 1000, "m": 1000000}[match.group(2).lower()]
        if abs(number - value) <= max(0.001, abs(value) * 0.000001):
            return True
    return False


def _currency_supported(value: Any, quote: str) -> bool:
    if value is None:
        return True
    return isinstance(value, str) and value in {"USD", "EUR", "GBP"} and bool(
        re.search({"USD": r"\$|\bUSD\b", "EUR": r"€|\bEUR\b", "GBP": r"£|\bGBP\b"}[value], quote, re.I))


def validate_output(note: dict, output: dict, identity: dict,
                    chunk: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Reject invalid objects, preserving explicit reasons; never repair claims."""
    if not isinstance(output, dict) or set(output) != set(COLLECTIONS):
        raise ValueError("invalid_top_level_schema")
    accepted, rejected = [], []
    allowed_accounts = {x["id"] for x in identity.get("accounts", [])}
    allowed_contacts = {x["id"] for x in identity.get("contacts", [])}
    allowed_opportunities = {x["id"] for x in identity.get("opportunities", [])}
    for collection in COLLECTIONS:
        items = output[collection]
        if not isinstance(items, list):
            raise ValueError("invalid_collection_schema")
        for index, item in enumerate(items):
            try:
                if not isinstance(item, dict) or any(k in item for k in ("VerifiedActualUSD", "verified_signed", "document_verified")):
                    raise ValueError("forbidden_verification_field")
                required = set(SEMANTIC_SCHEMA["properties"][collection]["items"]["properties"])
                if set(item) != required:
                    raise ValueError("invalid_item_schema")
                span = source_span(note, item, chunk)
                if item.get("account_candidate_id") not in allowed_accounts | {None}:
                    raise ValueError("invented_account_id")
                if item.get("opportunity_candidate_id") not in allowed_opportunities | {None}:
                    raise ValueError("invented_opportunity_id")
                if collection == "contact_links" and item.get("contact_candidate_id") not in allowed_contacts | {None}:
                    raise ValueError("invented_contact_id")
                if collection == "events":
                    if item.get("event_type") not in EVENT_TYPES or item.get("polarity") not in POLARITIES or item.get("contract_kind") not in CONTRACT_KINDS:
                        raise ValueError("invalid_event_enum")
                    if not _date_supported(item.get("event_date"), item["quote"]):
                        raise ValueError("unsupported_date")
                if collection == "commercial_values":
                    if item.get("value_type") not in VALUE_TYPES or item.get("status") not in VALUE_STATUSES or item.get("contract_kind") not in CONTRACT_KINDS:
                        raise ValueError("invalid_value_enum")
                    if not _amount_supported(item.get("amount"), item["quote"]) or not _currency_supported(item.get("currency"), item["quote"]):
                        raise ValueError("unsupported_amount_or_currency")
                if collection == "signals" and (item.get("family") not in SIGNAL_FAMILIES or item.get("polarity") not in POLARITIES):
                    raise ValueError("invalid_signal_enum")
                if collection == "atomic_signals":
                    if (item.get("signal_type") not in SIGNAL_TYPES or item.get("modality") not in SIGNAL_MODALITIES
                            or item.get("actor") not in ACTORS or item.get("contract_kind") not in CONTRACT_KINDS):
                        raise ValueError("invalid_atomic_signal_enum")
                    if not _date_supported(item.get("effective_date"), item["quote"]):
                        raise ValueError("unsupported_date")
                if collection == "opportunity_candidates" and (not item.get("use_case") or not item.get("commercial_scope")):
                    raise ValueError("missing_scope")
                accepted.append({"collection": collection, "data": item, "evidence_span": span})
            except ValueError as exc:
                rejected.append({"collection": collection, "index": index, "reason": str(exc)})
    # Overlapping chunks may repeat the same observation. Preserve distinct semantics.
    unique = {}
    for item in accepted:
        key = (item["collection"], item["evidence_span"]["json_pointer"],
               item["evidence_span"]["start"], json.dumps(item["data"], sort_keys=True, ensure_ascii=False))
        unique[key] = item
    return list(unique.values()), rejected


def extract(note: dict, context: dict, *, client: httpx.Client | None = None,
            timeout_s: float = 90.0) -> dict:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return {"status": "not_run_missing_credentials", "accepted": [], "rejected": [], "calls": []}
    model = os.getenv("OPENAI_SEMANTIC_MODEL") or "gpt-6-luna"
    reasoning = os.getenv("OPENAI_SEMANTIC_REASONING") or "medium"
    own = client is None
    client = client or httpx.Client(timeout=timeout_s)
    calls, accepted, rejected = [], [], []
    try:
        for chunk in chunks(note):
            payload = {"model": model, "store": False, "reasoning": {"effort": reasoning},
                       "instructions": INSTRUCTIONS, "input": json.dumps({
                           "full_note_length": len(note["text"]), "chunk_global_start": chunk["start"],
                           "chunk_text": chunk["text"], "identity_candidates": context}, ensure_ascii=False),
                       "text": {"format": {"type": "json_schema", "name": "gtm_semantic_evidence",
                                           "strict": True, "schema": SEMANTIC_SCHEMA}}}
            started = time.monotonic()
            body = {}
            attempts = []
            response_shape = None
            try:
                for attempt in range(3):
                    try:
                        response = client.post(URL, json=payload,
                                               headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                                               timeout=timeout_s)
                        response.raise_for_status()
                        break
                    except httpx.HTTPError as exc:
                        status_code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                        transient = isinstance(exc, httpx.TransportError) or status_code in {408, 409, 429, 500, 502, 503, 504}
                        attempts.append({"attempt": attempt + 1, "category": "transport_error" if status_code is None else "http_error",
                                         "http_status": status_code, "retryable": transient})
                        if not transient or attempt == 2:
                            raise
                        time.sleep(min(8, 2 ** attempt))
                body = response.json()
                response_shape = [{"type": item.get("type"), "channel": item.get("channel"),
                                   "content_types": [part.get("type") for part in item.get("content", [])]}
                                  for item in body.get("output", [])]
                if any(part.get("type") == "refusal" for output in body.get("output", [])
                       for part in output.get("content", [])):
                    raise ValueError("model_refusal")
                if body.get("status") != "completed":
                    reason = (body.get("incomplete_details") or {}).get("reason")
                    raise ValueError("incomplete_max_output_tokens" if reason == "max_output_tokens" else
                                     "incomplete_content_filter" if reason == "content_filter" else "response_not_completed")
                parts = [part["text"] for output in body.get("output", []) for part in output.get("content", [])
                         if part.get("type") == "output_text"]
                if len(parts) != 1:
                    raise ValueError("missing_structured_output" if not parts else "multiple_structured_outputs")
                structured = json.loads(parts[0])
                valid, invalid = validate_output(note, structured, context, chunk)
                # A model must not cite text outside the submitted chunk.
                for item in valid:
                    span = item["evidence_span"]
                    if chunk["start"] <= span["global_start"] and span["global_end"] <= chunk["end"]:
                        accepted.append(item)
                    else:
                        rejected.append({"collection": item["collection"], "reason": "span_outside_submitted_chunk"})
                rejected.extend(invalid)
                calls.append({"status": "completed", "requested_model": model, "resolved_model": body.get("model"),
                              "usage": body.get("usage"), "latency_ms": round((time.monotonic() - started) * 1000, 2),
                              "transport_attempts": attempts,
                              "chunk_start": chunk["start"], "chunk_end": chunk["end"]})
            except (httpx.HTTPError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                safe_reasons = {"model_refusal", "incomplete_max_output_tokens", "incomplete_content_filter",
                                "response_not_completed", "missing_structured_output", "multiple_structured_outputs", "invalid_top_level_schema",
                                "invalid_collection_schema"}
                detail = (str(exc) if type(exc) is ValueError and str(exc) in safe_reasons else
                          "invalid_json" if isinstance(exc, json.JSONDecodeError) else
                          "http_error" if isinstance(exc, httpx.HTTPStatusError) else
                          "transport_error" if isinstance(exc, httpx.TransportError) else "malformed_response")
                calls.append({"status": "provider_failure", "failure_kind": type(exc).__name__,
                              "failure_detail": detail, "error_category": detail,
                              "response_shape": response_shape,
                              "requested_model": model, "resolved_model": body.get("model") if isinstance(body, dict) else None,
                              "usage": body.get("usage") if isinstance(body, dict) else None,
                              "transport_attempts": attempts,
                              "latency_ms": round((time.monotonic() - started) * 1000, 2),
                              "chunk_start": chunk["start"], "chunk_end": chunk["end"]})
        unique = {}
        for item in accepted:
            span = item["evidence_span"]
            key_ = hashlib.sha256(json.dumps([item["collection"], span["json_pointer"], span["start"], item["data"]],
                                            sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            unique[key_] = item
        status = "completed" if calls and all(x["status"] == "completed" for x in calls) else "provider_failure"
        return {"status": status, "accepted": list(unique.values()), "rejected": rejected, "calls": calls,
                "adapter_version": ADAPTER_VERSION, "schema_version": SCHEMA_VERSION}
    finally:
        if own:
            client.close()
