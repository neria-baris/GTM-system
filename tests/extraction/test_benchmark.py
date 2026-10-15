from __future__ import annotations

import json
from pathlib import Path

from src.extraction import benchmark
from src.extraction.benchmark import DATASET, RUBRICS, _ensemble, _safe_span_for_reported_signature, _signature_candidate, _source_span, rules, run
from src.extraction.jev_adapter import JevError


def test_frozen_audit_spans_are_exact_and_counted():
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    rows = data["rows"]
    assert sum(row["origin"] == "audit_selected" for row in rows) == 18
    assert len({row["source_ref"]["native_id"] for row in rows}) == len(rows)
    source = Path("context/audit_evidence.md").read_text(encoding="utf-8")
    for row in rows:
        span = row["source_span"]
        assert row["text"] in span["exact_text"]
        if row["origin"] == "audit_selected":
            assert source[span["start"]:span["end"]] == span["exact_text"]


def test_rules_preserve_contract_and_data_distinctions():
    pilot = rules("Pilot signed: €135k. Commercial contract NOT signed yet; legal is reviewing pricing.")
    assert pilot["pilot_contract_status"] == "signed"
    assert pilot["commercial_contract_status"] == "not_signed"
    assert rules("Data: 18 months lot moves")["data_access"] == "unknown"
    assert rules("The rollout budget is not approved; contract status was not discussed.")["commercial_contract_status"] == "unclear"
    assert rules("Draft outreach email, not sent: thank you for signing commercial agreement")["commercial_contract_status"] == "unclear"
    assert rules("Verbal yes to paid pilot, SOW being drafted")["pilot_contract_status"] == "verbal_yes"


def test_signature_proposal_requires_safe_exact_quote():
    assert _safe_span_for_reported_signature("SIGNED. €580k/yr, 2-yr term")
    assert _safe_span_for_reported_signature("Commercial contract NOT signed") is None
    assert _safe_span_for_reported_signature("Draft email: commercial agreement signed") is None
    assert _safe_span_for_reported_signature("Pilot signed: €115k") is None


def test_reported_signature_span_maps_to_audit_corpus():
    row = next(row for row in json.loads(DATASET.read_text(encoding="utf-8"))["rows"] if row["id"] == "frostline_commercial_report")
    span = _source_span(row, _safe_span_for_reported_signature(row["text"]))
    source = Path("context/audit_evidence.md").read_text(encoding="utf-8")
    assert source[span["start"]:span["end"]] == span["exact_text"]


def test_require_jev_fails_without_credentials_and_records_status(monkeypatch, tmp_path):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    assert run(True, tmp_path) == 1
    report = json.loads((tmp_path / "evaluation_report.json").read_text(encoding="utf-8"))
    assert report["live_run_status"] == "not_run_missing_credentials"
    assert report["jev_raw_metrics"] is None
    assert report["estimated_cost_usd"] is None


def _fake_run(signed_probability: float, *, selected: str | None = None) -> dict:
    answers = {}
    for field, (_, options) in RUBRICS.items():
        unknown = "unclear" if "unclear" in options else "unknown"
        probabilities = {option: 0.0 for option in options}
        probabilities[unknown] = 1.0
        if field == "commercial_contract_status":
            probabilities[unknown] = 1 - signed_probability
            probabilities["signed"] = signed_probability
        top = selected if field == "commercial_contract_status" and selected else max(probabilities, key=probabilities.get)
        answers[field] = {"type": "choice", "choice": top, "probabilities": probabilities, "confidence": 1.0}
    return {"raw_response": {"answers": answers, "usage": {"input_tokens": 10, "output_tokens": 2}},
            "resolved_model": "jev-test", "requested_model": "jev-latest", "latency_ms": 10.0, "attempts": 1}


def test_ensemble_aligns_probability_vectors_and_requires_signature_agreement():
    runs = [_fake_run(.99), _fake_run(.97), _fake_run(.04)]
    answer = _ensemble(runs)["commercial_contract_status"]
    assert answer["choice"] == "signed"
    assert abs(answer["probabilities"]["signed"] - (0.99 + 0.97 + 0.04) / 3) < 1e-12
    assert answer["probability_stddev"]["signed"] > 0
    assert answer["top_choice_agreement"] == 2 / 3
    assert not answer["all_runs_agree_on_top"]
    row = {"text": "Vendora note: both parties signed the commercial deployment agreement today."}
    assert not _signature_candidate(row, answer, ensemble=True)
    identical = _ensemble([_fake_run(.99) for _ in range(5)])["commercial_contract_status"]
    assert identical["probability_stddev"]["signed"] == 0
    assert _signature_candidate(row, identical, ensemble=True)


def test_ensemble_noul_and_score_keep_primitive_meaning():
    question_set = {
        "binary": {"type": "noul", "instructions": "Was access granted?"},
        "ordered": {"type": "score", "instructions": "Ordered urgency", "criteria": ["normal", "soon", "now"]},
    }
    runs = []
    for noul, levels in ((.2, {"0": .8, "1": .2, "2": 0.0}), (.8, {"2": .6, "0": .1, "1": .3})):
        runs.append({"raw_response": {"answers": {
            "binary": {"type": "noul", "noul": noul},
            "ordered": {"type": "score", "score": 1.0, "legend": {"0": "normal", "1": "soon", "2": "now"},
                        "probabilities": levels, "confidence": .7},
        }}})
    aggregate = _ensemble(runs, question_set)
    assert aggregate["binary"]["mean_noul"] == .5
    assert abs(aggregate["binary"]["stddev_noul"] - .3) < 1e-12
    assert abs(aggregate["ordered"]["probabilities"]["0"] - .45) < 1e-12
    assert aggregate["ordered"]["top_level"] == 0
    assert "score" not in aggregate["ordered"]


def test_live_benchmark_repeats_same_batched_questions_without_credits(monkeypatch, tmp_path):
    rows = json.loads(DATASET.read_text(encoding="utf-8"))["rows"][:2]
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps({"dataset_version": "mock_v1", "label_status": "test", "rows": rows}), encoding="utf-8")
    monkeypatch.setattr(benchmark, "DATASET", fixture)
    monkeypatch.setenv("JEV_API_KEY", "mock-only")
    calls = []

    def fake_evaluate(state, questions):
        calls.append((state, tuple(questions)))
        return _fake_run(.01)

    monkeypatch.setattr(benchmark, "evaluate", fake_evaluate)
    assert run(True, tmp_path, 3) == 0
    assert len(calls) == 6
    assert all(len(fields) == 8 for _, fields in calls)
    report = json.loads((tmp_path / "evaluation_report.json").read_text(encoding="utf-8"))
    assert report["jev_single"]["usage"]["calls"] == 2
    assert report["jev_ensemble"]["usage"]["calls"] == 6
    assert report["jev_ensemble"]["incremental_usage_over_single"]["calls"] == 4
    assert len(report["per_document"][0]["jev_ensemble"]["commercial_contract_status"]["run_answers"]) == 3
    policy = json.loads((tmp_path / "routing_policy.json").read_text(encoding="utf-8"))
    assert set(policy["field_routes"]) == set(RUBRICS)
    assert policy["verified_actual_usd_mutation_allowed"] is False


def test_required_live_benchmark_records_provider_failure_without_claims(monkeypatch, tmp_path):
    monkeypatch.setenv("JEV_API_KEY", "mock-only")

    def fail(*args, **kwargs):
        raise JevError("hard_http_failure", 401)

    monkeypatch.setattr(benchmark, "evaluate", fail)
    assert run(True, tmp_path, 5) == 1
    report = json.loads((tmp_path / "evaluation_report.json").read_text(encoding="utf-8"))
    assert report["live_run_status"] == "failed"
    assert report["provider_failures"][0]["status_code"] == 401
    assert report["jev_ensemble"]["raw_metrics"] is None
    policy = json.loads((tmp_path / "routing_policy.json").read_text(encoding="utf-8"))
    assert not policy["commercial_signature_auto_proposal_enabled"]
    assert not policy["candidate_proposals_for_review"]
