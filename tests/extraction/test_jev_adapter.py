from __future__ import annotations

import httpx
import pytest

from src.extraction.jev_adapter import JevError, choice_question, evaluate


Q = {"commercial_contract_status": choice_question("Commercial contract status?", {"signed": "Signed", "not_signed": "Not signed", "unclear": "Unknown"})}


def response(choice="not_signed"):
    return {"model": "jev-1.13.0", "answers": {"commercial_contract_status": {"type": "choice", "choice": choice, "probabilities": {"signed": 0.01, "not_signed": 0.98, "unclear": 0.01}, "confidence": 0.96}}, "usage": {"input_tokens": 12, "output_tokens": 3}}


def test_live_wire_contract_and_safe_response(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "private-test-key")
    seen = []

    def handler(request):
        seen.append(request)
        assert request.url == "https://api.typesafe.ai/v1/systemone"
        assert request.headers["authorization"] == "Bearer private-test-key"
        assert request.headers["idempotency-key"]
        assert request.content.count(b'"model":"jev-latest"') == 1
        return httpx.Response(200, json={**response(), "secret_extension": "drop-me"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        got = evaluate("Commercial contract NOT signed", Q, client=client)
    assert len(seen) == 1
    assert got["resolved_model"] == "jev-1.13.0"
    assert got["raw_response"]["answers"]["commercial_contract_status"]["probabilities"]["not_signed"] == .98
    assert "private-test-key" not in str(got)
    assert "secret_extension" not in str(got)


@pytest.mark.parametrize("status", [401, 422])
def test_hard_errors_do_not_retry_or_echo_body(monkeypatch, status):
    monkeypatch.setenv("JEV_API_KEY", "private-test-key")
    calls = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: (calls.append(request), httpx.Response(status, text="private-test-key"))[1])) as client:
        with pytest.raises(JevError) as caught:
            evaluate("state", Q, client=client, sleep=lambda _: None)
    assert len(calls) == 1
    assert caught.value.kind == "hard_http_failure"
    assert "private-test-key" not in str(caught.value)


def test_transient_retries_bounded_and_idempotent(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "private-test-key")
    keys = []

    def handler(request):
        keys.append(request.headers["idempotency-key"])
        return httpx.Response(429) if len(keys) == 1 else httpx.Response(200, json=response())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        got = evaluate("state", Q, client=client, sleep=lambda _: None)
    assert got["attempts"] == 2
    assert len(set(keys)) == 1


def test_invalid_distribution_is_rejected(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "private-test-key")
    bad = response()
    bad["answers"]["commercial_contract_status"]["probabilities"]["signed"] = .6
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=bad))) as client:
        with pytest.raises(JevError, match="invalid_response"):
            evaluate("state", Q, client=client)


def test_missing_key_fails_before_network(monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    with pytest.raises(JevError, match="missing_credentials"):
        evaluate("state", Q)


def test_noul_has_no_invented_confidence_and_score_keeps_order(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "private-test-key")
    questions = {"binary": {"type": "noul", "instructions": "Was access granted?"}, "ordered": {"type": "score", "instructions": "How urgent?", "criteria": ["normal", "soon", "now"]}}
    body = {"model": "jev-1.13.0", "answers": {"binary": {"type": "noul", "noul": 0.7}, "ordered": {"type": "score", "score": 1.5, "legend": {"0": "normal", "1": "soon", "2": "now"}, "probabilities": {"0": 0, "1": 0.5, "2": 0.5}, "confidence": 0.5}}, "usage": None}
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as client:
        got = evaluate("state", questions, client=client)
    assert got["raw_response"]["answers"]["binary"] == {"type": "noul", "noul": 0.7}
    assert got["raw_response"]["answers"]["ordered"]["legend"]["2"] == "now"
