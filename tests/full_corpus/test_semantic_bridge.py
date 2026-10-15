import json

import httpx
import pytest

from src.extraction.semantic_llm import chunks, extract, normalize_note, source_span, validate_output
from src.extraction.semantic_schema import COLLECTIONS, SEMANTIC_SCHEMA


def note():
    units = [
        {"source_part": "notion_block", "text": "Pilot verbal yes", "start": 0,
         "json_pointer": "/content/blocks/0/block/paragraph/rich_text/0/plain_text",
         "block_id": "b0", "evidence_unit_id": "u0"},
        {"source_part": "notion_block", "text": "Commercial contract NOT signed", "start": 0,
         "json_pointer": "/content/blocks/1/block/paragraph/rich_text/0/plain_text",
         "block_id": "b1", "evidence_unit_id": "u1"},
    ]
    return normalize_note(units)


def empty_output():
    return {key: [] for key in COLLECTIONS}


def event(text, *, start=0, account="recA", event_type="pilot_verbal_yes", date=None):
    return {"quote": text,
            "account_candidate_id": account, "opportunity_candidate_id": None,
            "event_type": event_type, "polarity": "asserted", "event_date": date,
            "contract_kind": "pilot"}


def test_full_note_normalization_and_global_source_offsets():
    n = note()
    assert n["text"] == "Pilot verbal yes\nCommercial contract NOT signed"
    assert "".join(c["text"] for c in chunks(n, max_chars=10, overlap_segments=0)) == n["text"].replace("\n", "")
    start = n["text"].index("NOT signed")
    span = source_span(n, {"quote": "NOT signed", "start": start, "end": start + 10})
    assert span["block_id"] == "b1" and span["start"] == len("Commercial contract ")
    with pytest.raises(ValueError, match="span_crosses_source_strings"):
        source_span(n, {"quote": "yes\nCommercial", "start": 13, "end": 27})


def test_semantic_post_validation_rejects_invented_quote_identity_date_and_verification():
    n = note()
    context = {"accounts": [{"id": "recA"}], "contacts": [], "opportunities": []}
    output = empty_output()
    output["events"] = [event("Pilot verbal yes"), event("Pilot verbal yes", account="invented"),
                        event("Pilot verbal yes", date="2026-05-01"),
                        {**event("Pilot verbal yes"), "VerifiedActualUSD": 5},
                        event("Commercial signed", start=17, event_type="commercial_signed")]
    accepted, rejected = validate_output(n, output, context)
    assert len(accepted) == 1 and len(rejected) == 4
    assert {x["reason"] for x in rejected} == {"invented_account_id", "unsupported_date",
                                                  "forbidden_verification_field", "quote_absent_from_submitted_chunk"}


def test_commercial_value_requires_source_supported_number_and_currency():
    n = normalize_note([{"source_part": "notion_block", "text": "Pilot fee €95k", "start": 0,
                         "json_pointer": "/text", "block_id": "b", "evidence_unit_id": "u"}])
    base = {"quote": "Pilot fee €95k",
            "account_candidate_id": None, "opportunity_candidate_id": None,
            "amount": 95000, "currency": "EUR", "unit": None, "value_type": "pilot_fee",
            "status": "discussed", "contract_kind": "pilot", "scenario_relation": None}
    output = empty_output()
    output["commercial_values"] = [base, {**base, "amount": 580000}, {**base, "currency": "USD"}]
    accepted, rejected = validate_output(n, output, {"accounts": [], "contacts": [], "opportunities": []})
    assert len(accepted) == 1 and len(rejected) == 2


def test_no_key_is_explicit(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert extract(note(), {"accounts": [], "contacts": [], "opportunities": []})["status"] == "not_run_missing_credentials"


def test_responses_structured_wire_and_validation(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    output = empty_output()
    output["events"] = [event("Pilot verbal yes")]
    body = {"status": "completed", "model": "gpt-6-luna-test", "usage": {"input_tokens": 10, "output_tokens": 5},
            "output": [{"content": [{"type": "output_text", "text": json.dumps(output)}]}]}
    def handler(request):
        payload = json.loads(request.content)
        assert payload["store"] is False and payload["reasoning"]["effort"] == "medium"
        assert payload["text"]["format"]["strict"] is True
        assert payload["text"]["format"]["schema"] == SEMANTIC_SCHEMA
        assert "tools" not in payload
        return httpx.Response(200, json=body)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = extract(note(), {"accounts": [{"id": "recA"}], "contacts": [], "opportunities": []}, client=client)
    assert result["status"] == "completed"
    assert result["accepted"][0]["data"]["event_type"] == "pilot_verbal_yes"
    assert result["calls"][0]["resolved_model"] == "gpt-6-luna-test"


def test_quote_only_schema_and_computed_offsets_ignore_legacy_coordinates():
    for collection in COLLECTIONS:
        properties = SEMANTIC_SCHEMA["properties"][collection]["items"]["properties"]
        assert "start" not in properties and "end" not in properties
    n = note()
    span = source_span(n, {"quote": "NOT signed", "start": -999, "end": 9999})
    assert span["global_start"] == n["text"].index("NOT signed")
    assert span["global_end"] == len(n["text"])
    assert span["start"] == 20 and span["end"] == 30


def test_quote_must_be_unique_inside_exact_submitted_chunk():
    n = normalize_note([{"source_part": "notion_block", "text": "yes yes", "start": 5,
                         "json_pointer": "/text", "block_id": "b", "evidence_unit_id": "u"}])
    with pytest.raises(ValueError, match="ambiguous_repeated_quote"):
        source_span(n, {"quote": "yes"})
    span = source_span(n, {"quote": "yes"}, {"start": 4, "end": 7, "text": "yes"})
    assert (span["start"], span["end"], span["global_start"], span["chunk_start"]) == (9, 12, 4, 0)
    with pytest.raises(ValueError, match="quote_absent_from_submitted_chunk"):
        source_span(note(), {"quote": "Pilot"}, chunks(note(), max_chars=10)[1])


def test_computed_span_resolves_original_json_string():
    from src.extraction.full_corpus import notion_units, validate_span
    snapshot = {"content": {"page": {}, "blocks": [
        {"block": {"id": "b0", "type": "paragraph", "paragraph": {
            "rich_text": [{"plain_text": "Pilot verbal yes"}]}}, "children": []},
        {"block": {"id": "b1", "type": "paragraph", "paragraph": {
            "rich_text": [{"plain_text": "Commercial contract NOT signed"}]}}, "children": []}]}}
    n = normalize_note(notion_units(snapshot)[0])
    span = source_span(n, {"quote": "NOT signed"})
    assert span["json_pointer"] == "/content/blocks/1/block/paragraph/rich_text/0/plain_text"
    assert validate_span(snapshot, span)
    with pytest.raises(ValueError, match="span_crosses_source_strings"):
        source_span(n, {"quote": "yes\nCommercial"})


@pytest.mark.parametrize("body,category", [
    ({"status": "completed", "output": [{"content": [{"type": "refusal", "refusal": "private"}]}]}, "model_refusal"),
    ({"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}, "incomplete_max_output_tokens"),
    ({"status": "completed", "output": []}, "missing_structured_output"),
    ({"status": "completed", "output": [{"content": [{"type": "output_text", "text": "{}"},
                                                       {"type": "output_text", "text": "{}"}]}]}, "multiple_structured_outputs"),
    ({"status": "completed", "output": [{"content": [{"type": "output_text", "text": "{}"}]}]}, "invalid_top_level_schema"),
    ({"status": "completed", "output": [{"content": [{"type": "output_text", "text": "secret malformed"}]}]}, "invalid_json"),
])
def test_failure_diagnostics_are_safe_and_explicit(monkeypatch, body, category):
    monkeypatch.setenv("OPENAI_API_KEY", "private-key-never-log")
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as client:
        result = extract(note(), {}, client=client)
    assert result["status"] == "provider_failure"
    assert result["calls"][0]["failure_detail"] == category
    assert "private" not in json.dumps(result) and "secret malformed" not in json.dumps(result)


def test_transient_failure_retried_with_bound_and_backoff(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    delays = []
    monkeypatch.setattr("src.extraction.semantic_llm.time.sleep", delays.append)
    count = 0
    def handler(_):
        nonlocal count
        count += 1
        return httpx.Response(429, json={"error": {"message": "sensitive"}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = extract(note(), {}, client=client)
    assert count == 3 and delays == [1, 2]
    assert result["status"] == "provider_failure"
    assert len(result["calls"][0]["transport_attempts"]) == 3
    assert "sensitive" not in json.dumps(result)


def atomic(quote, *, signal_type="data_received", modality="asserted", date=None, actor="customer", kind="pilot"):
    return {"quote": quote, "account_candidate_id": "recA", "opportunity_candidate_id": None,
            "signal_type": signal_type, "modality": modality, "effective_date": date, "actor": actor,
            "contract_kind": kind}


def test_atomic_signal_schema_uses_closed_ontology_enums():
    from src.belief.ontology import CONTRACT_KINDS as ONTOLOGY_KINDS, EXTRACTABLE_TYPES, MODALITIES
    from src.extraction.semantic_schema import SCHEMA_VERSION
    assert SCHEMA_VERSION == "semantic_bridge_1.2.0"
    assert "atomic_signals" in COLLECTIONS and "atomic_signals" in SEMANTIC_SCHEMA["required"]
    item = SEMANTIC_SCHEMA["properties"]["atomic_signals"]["items"]
    assert item["additionalProperties"] is False and set(item["required"]) == set(item["properties"])
    props = item["properties"]
    assert props["signal_type"]["enum"] == list(EXTRACTABLE_TYPES)
    assert "formal_signature_verified" not in props["signal_type"]["enum"]
    assert "recurring_interaction" not in props["signal_type"]["enum"]
    assert props["modality"]["enum"] == list(MODALITIES)
    assert props["actor"]["enum"] == ["customer", "seller", "third_party", "unknown"]
    assert props["contract_kind"]["enum"] == list(ONTOLOGY_KINDS)
    assert props["effective_date"] == {"type": ["string", "null"]}
    for name in ("events", "commercial_values", "signals", "opportunity_candidates"):
        assert name in SEMANTIC_SCHEMA["properties"]


def test_atomic_signal_post_validation():
    n = normalize_note([{"source_part": "notion_block", "text": "Logs received on 2026-05-04; kickoff next month",
                         "start": 0, "json_pointer": "/text", "block_id": "b", "evidence_unit_id": "u"}])
    output = empty_output()
    output["atomic_signals"] = [
        atomic("Logs received on 2026-05-04", date="2026-05-04"),
        atomic("kickoff next month", signal_type="kickoff_scheduled", modality="planned", actor="seller"),
        atomic("Logs received", signal_type="formal_signature_verified"),
        atomic("Logs received", modality="probably"),
        atomic("Logs received", actor="vendor"),
        atomic("Logs received", date="2026-06-01"),
        {**atomic("Logs received"), "verified_signed": True},
        {**atomic("Logs received"), "extra": 1},
    ]
    accepted, rejected = validate_output(n, output, {"accounts": [{"id": "recA"}], "contacts": [], "opportunities": []})
    assert [x["data"]["signal_type"] for x in accepted] == ["data_received", "kickoff_scheduled"]
    assert [x["reason"] for x in rejected] == ["invalid_atomic_signal_enum"] * 3 + [
        "unsupported_date", "forbidden_verification_field", "invalid_item_schema"]


def test_instructions_separate_plans_conditions_and_actors():
    from src.extraction.semantic_llm import INSTRUCTIONS
    for phrase in ("atomic_signals", "Planning is never execution", "conditional statement stays conditional",
                   "actor", "Never emit verification"):
        assert phrase in INSTRUCTIONS
