"""Optional narrow Responses API relation extractor. Output is never verification."""
from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx

MODEL_DEFAULT = "gpt-5.6-terra"
ADAPTER_VERSION = "c2_llm_1.0.0"
URL = "https://api.openai.com/v1/responses"

RELATION_SCHEMA = {
    "type": "object", "properties": {
        "relations": {"type": "array", "items": {"type": "object", "properties": {
            "quote": {"type": "string"}, "subject": {"type": ["string", "null"]},
            "predicate": {"type": "string"}, "object": {"type": ["string", "null"]},
            "contract_kind": {"type": ["string", "null"]},
            "value_type": {"type": ["string", "null"]},
        }, "required": ["quote", "subject", "predicate", "object", "contract_kind", "value_type"],
        "additionalProperties": False}},
    }, "required": ["relations"], "additionalProperties": False,
}


def validate_relations(source_text: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(result, dict) or not isinstance(result.get("relations"), list):
        raise ValueError("invalid structured relation output")
    accepted = []
    for item in result["relations"]:
        if not isinstance(item, dict) or not isinstance(item.get("quote"), str) or not item["quote"]:
            continue
        start = source_text.find(item["quote"])
        if start < 0:
            continue
        accepted.append({**item, "start": start, "end": start + len(item["quote"])})
    return accepted


def extract_relations(source_text: str, *, client: httpx.Client | None = None,
                      timeout_s: float = 40.0) -> dict[str, Any]:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return {"status": "not_run_missing_credentials", "relations": [], "rejected_count": 0}
    model = os.getenv("OPENAI_EXTRACTION_MODEL") or MODEL_DEFAULT
    payload = {"model": model, "store": False,
               "instructions": "Extract only relations explicitly supported by the supplied text. Copy each quote verbatim. Return an empty array when uncertain. Do not infer signature, dates, currencies, or entity identity.",
               "input": source_text,
               "text": {"format": {"type": "json_schema", "name": "evidence_relations", "strict": True,
                                   "schema": RELATION_SCHEMA}}}
    owns = client is None
    client = client or httpx.Client(timeout=timeout_s)
    started = time.monotonic()
    try:
        response = client.post(URL, json=payload,
                               headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                               timeout=timeout_s)
        response.raise_for_status()
        body = response.json()
        if body.get("status") != "completed":
            raise ValueError("incomplete response")
        texts = [part["text"] for output in body.get("output", [])
                 for part in output.get("content", []) if part.get("type") == "output_text"]
        if len(texts) != 1:
            raise ValueError("missing structured output")
        structured = json.loads(texts[0])
        accepted = validate_relations(source_text, structured)
        return {"status": "completed", "relations": accepted,
                "rejected_count": len(structured["relations"]) - len(accepted),
                "model_requested": model, "model_resolved": body.get("model"),
                "usage": body.get("usage"), "latency_ms": round((time.monotonic() - started) * 1000, 2),
                "adapter_version": ADAPTER_VERSION}
    except (httpx.HTTPError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return {"status": "provider_failure", "failure_kind": type(exc).__name__,
                "relations": [], "rejected_count": 0, "model_requested": model,
                "latency_ms": round((time.monotonic() - started) * 1000, 2)}
    finally:
        if owns:
            client.close()
