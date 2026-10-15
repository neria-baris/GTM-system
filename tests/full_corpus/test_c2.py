import copy
import json

import httpx
import pytest

from src.extraction.ensemble import aggregate, commercial_signature_gate, run_batch
from src.extraction.full_corpus import (airtable_units, coverage_gate, exact_span,
                                        notion_units, segment, validate_span, _text_claims,
                                        duplicate_coverage_rows)
from src.extraction.llm_adapter import extract_relations, validate_relations


Q = {"commercial_contract_status": {"type": "choice", "criteria": {
    "signed": "signed", "not_signed": "unsigned", "unclear": "unknown"}}}


def answer(signed, not_signed, unclear, choice, confidence=.98):
    return {"resolved_model": "jev-test", "latency_ms": 2,
            "raw_response": {"usage": {"input_tokens": 2, "output_tokens": 1},
                             "answers": {"commercial_contract_status": {"type": "choice", "choice": choice,
                                 "probabilities": {"signed": signed, "not_signed": not_signed,
                                                   "unclear": unclear}, "confidence": confidence}}}}


def test_choice_aggregation_aligns_options_and_never_averages_labels():
    a = answer(.8, .1, .1, "signed")
    b = answer(.6, .3, .1, "signed")
    b["raw_response"]["answers"]["commercial_contract_status"]["probabilities"] = {
        "unclear": .1, "not_signed": .3, "signed": .6}
    got = aggregate([a, b], Q)["commercial_contract_status"]
    assert got["mean_probabilities"]["signed"] == pytest.approx(.7)
    assert got["std_probabilities"]["signed"] == pytest.approx(.1)
    assert got["aggregate_choice"] == "signed"
    assert "mean_choice" not in got
    assert aggregate([b, a], Q)["commercial_contract_status"]["mean_probabilities"] == got["mean_probabilities"]


def test_identical_and_disagreement_stability():
    a = answer(.98, .01, .01, "signed")
    same = aggregate([a, copy.deepcopy(a)], Q)["commercial_contract_status"]
    assert same["identical_responses"] and same["std_probabilities"]["signed"] == 0
    mixed = aggregate([a, answer(.01, .98, .01, "not_signed")], Q)["commercial_contract_status"]
    assert mixed["top_choice_agreement_rate"] == .5
    assert mixed["std_probabilities"]["signed"] > 0


def test_commercial_signature_strict_gate_and_no_actual_path():
    a = answer(.99, .005, .005, "signed")
    batch = {"requested_k": 5, "successful_k": 5, "runs": [a] * 5,
             "aggregate": aggregate([a] * 5, Q)}
    assert commercial_signature_gate(batch)
    assert "VerifiedActualUSD" not in batch
    batch["runs"][-1] = answer(.1, .8, .1, "not_signed")
    batch["aggregate"] = aggregate(batch["runs"], Q)
    assert not commercial_signature_gate(batch)


def test_failed_jev_run_abstains_without_replacement():
    calls = []
    def call(_state, _questions):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("failed")
        return answer(.99, .005, .005, "signed")
    batch = run_batch("text", Q, 5, call)
    assert len(calls) == 2 and batch["successful_k"] == 1
    assert batch["aggregate"] is None and batch["failures"][0]["run_index"] == 1


def test_coverage_gate_duplicate_and_missing():
    rows = [{"provider": "notion", "native_object_type": "page", "native_id": "p1",
             "content_hash": "h1", "disposition": "extracted"},
            {"provider": "notion", "native_object_type": "page", "native_id": "p2",
             "content_hash": "h2", "disposition": "no_business_evidence"}]
    base = {"extraction_executed": True, "manifest_source_count": 2, "considered_source_count": 2,
            "unaccounted_source_count": 0, "duplicate_coverage_count": 0,
            "unaccounted_source_list": [], "duplicate_coverage_list": [],
            "incomplete_source_warnings": [], "manifest_complete": True,
            "expected_by_provider_object_type": {"notion/page": 2},
            "considered_by_provider_object_type": {"notion/page": 2},
            "disposition_counts": {"extracted": 1, "no_business_evidence": 1},
            "source_coverage": rows}
    assert coverage_gate(base)
    assert not coverage_gate({**base, "considered_source_count": 1, "unaccounted_source_count": 1})
    assert not coverage_gate({**base, "duplicate_coverage_count": 1})
    assert not coverage_gate({**base, "incomplete_source_warnings": ["read failed"]})
    assert not coverage_gate({**base, "source_coverage": []})
    assert not coverage_gate({**base, "source_coverage": [rows[0], rows[0]]})
    row = {"provider": "notion", "native_id": "p", "content_hash": "h"}
    assert duplicate_coverage_rows([row, dict(row)]) == [["notion", "p", "h"]]


def test_notion_exact_span_and_empty_not_negative():
    snapshot = {"content": {"page": {"properties": {"Date": {"id": "d", "type": "date", "date": None}}},
                            "blocks": [{"block": {"id": "b1", "type": "paragraph",
                                                  "paragraph": {"rich_text": [{"plain_text": "commercial not signed"}]}},
                                        "children": []}]}}
    units, fields = notion_units(snapshot)
    assert len(units) == 1 and len(fields) == 2
    span = exact_span(units[0], "not signed")
    assert validate_span(snapshot, span) and span["block_id"] == "b1"
    assert not _text_claims({"provider": "notion", "native_object_type": "page", "native_id": "p",
                             "content_hash": "h", "raw_snapshot_path": "x", "source_title": "X"},
                            {**units[0], "text": ""}, snapshot)


def test_long_text_windows_preserve_every_character_and_offset():
    text = "First paragraph. " * 70
    windows = segment(text, {"json_pointer": "/content/text"}, max_chars=80)
    assert "".join(w["text"] for w in windows) == text
    assert windows[0]["start"] == 0 and windows[-1]["end"] == len(text)
    assert all(windows[i]["end"] == windows[i + 1]["start"] for i in range(len(windows) - 1))


def test_airtable_field_pointer_and_unsent_draft():
    schema = {"tables": [{"id": "tbl", "fields": [
        {"id": "fldA", "name": "Notes", "type": "multilineText"},
        {"id": "fldB", "name": "Initial Email Body", "type": "multilineText"},
        {"id": "fldC", "name": "Empty", "type": "singleLineText"}]}]}
    snapshot = {"content": {"table_id": "tbl", "record": {"id": "rec", "fields": {
        "fldA": "Pilot signed", "fldB": "We signed a commercial contract"}}}}
    units, fields = airtable_units(snapshot, schema)
    assert len(units) == 1
    assert fields[1]["reason"] == "unsent_draft_or_attachment_no_sent_at"
    assert fields[2]["reason"] == "empty_or_absent_not_negative_evidence"
    span = exact_span(units[0], "Pilot signed")
    assert span["json_pointer"] == "/content/record/fields/fldA"
    assert validate_span(snapshot, span)


def test_llm_rejects_invented_quote_and_missing_key(monkeypatch):
    assert validate_relations("Pilot signed", {"relations": [
        {"quote": "Commercial signed", "predicate": "status"}]}) == []
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert extract_relations("complex note")["status"] == "not_run_missing_credentials"


def test_empty_and_unknown_not_false_or_zero():
    schema = {"tables": [{"id": "tbl", "fields": [{"id": "fld", "name": "Notes", "type": "multilineText"}]}]}
    snapshot = {"content": {"table_id": "tbl", "record": {"id": "rec", "fields": {}}}}
    units, fields = airtable_units(snapshot, schema)
    assert units == [] and fields[0]["empty"]
    assert fields[0]["reason"] == "empty_or_absent_not_negative_evidence"
    assert "false" not in str(fields[0]["reason"]).lower()


def test_generic_unsigned_contract_with_annual_pricing_remains_review_only():
    snapshot = {"content": {"page": {"properties": {}}, "blocks": [
        {"block": {"id": "b1", "type": "paragraph", "paragraph": {"rich_text": [
            {"plain_text": "Contract NOT signed yet"}]}}, "children": []},
        {"block": {"id": "b2", "type": "paragraph", "paragraph": {"rich_text": [
            {"plain_text": "pricing not agreed, pushback on annual fee"}]}}, "children": []}]}}
    units, _ = notion_units(snapshot)
    env = {"provider": "notion", "native_object_type": "page", "native_id": "p",
           "content_hash": "h", "raw_snapshot_path": "x", "source_title": "WT"}
    claims = _text_claims(env, units[0], snapshot, "\n".join(u["text"] for u in units))
    unsigned = [c for c in claims if c["predicate"] == "contract_status"]
    assert len(unsigned) == 1
    assert unsigned[0]["value"] == "not_signed_reported"
    assert unsigned[0]["contract_kind"] is None
    assert unsigned[0]["validation_status"] == "review_required"
    assert unsigned[0]["evidence_span"]["exact_text"] == "Contract NOT signed"
    assert _text_claims(env, units[0], snapshot, "pilot extension") == []


def test_llm_structured_wire_and_verbatim_filter(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    body = {"status": "completed", "model": "test-model", "usage": {"input_tokens": 4},
            "output": [{"content": [{"type": "output_text", "text":
                '{"relations":[{"quote":"pilot fee","subject":null,"predicate":"value","object":"fee","contract_kind":"pilot","value_type":"fee"},{"quote":"invented","subject":null,"predicate":"value","object":null,"contract_kind":null,"value_type":null}]}'}]}]}
    def handler(request):
        payload = json.loads(request.content)
        assert payload["store"] is False
        assert payload["text"]["format"]["type"] == "json_schema"
        return httpx.Response(200, json=body)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = extract_relations("pilot fee", client=client)
    assert result["status"] == "completed" and result["rejected_count"] == 1
    assert result["relations"][0]["quote"] == "pilot fee"
