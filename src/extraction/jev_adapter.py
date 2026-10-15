"""Small, inspectable HTTP adapter for TypeSafe System One.

The API key is read for each call and is never included in exceptions or results.
See https://docs.typesafe.ai/api for the wire format.
"""
from __future__ import annotations

import os
import random
import time
import uuid
from typing import Any, Callable

import httpx

ADAPTER_VERSION = "1.1.0"
URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"


class JevError(RuntimeError):
    def __init__(self, kind: str, status_code: int | None = None):
        self.kind = kind
        self.status_code = status_code
        super().__init__(f"Jev {kind}" + (f" (HTTP {status_code})" if status_code else ""))


def choice_question(instructions: str, criteria: dict[str, str]) -> dict[str, Any]:
    if not instructions.strip() or not 2 <= len(criteria) <= 255:
        raise ValueError("choice requires instructions and 2–255 options")
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


def _prob(value: Any) -> bool:
    return type(value) in (int, float) and 0 <= value <= 1


def _validate_request(state: Any, questions: dict[str, Any]) -> None:
    if not isinstance(state, (str, dict, list)) or not isinstance(questions, dict) or not 1 <= len(questions) <= 32:
        raise ValueError("invalid state or question count")
    for key, question in questions.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(question, dict):
            raise ValueError("invalid question")
        kind = question.get("type")
        if kind not in {"choice", "noul", "score"} or not question.get("instructions"):
            raise ValueError("invalid question type or instructions")
        criteria = question.get("criteria")
        if kind == "choice" and (not isinstance(criteria, dict) or not 2 <= len(criteria) <= 255):
            raise ValueError("invalid choice criteria")
        if kind == "score" and (not isinstance(criteria, list) or not 2 <= len(criteria) <= 10):
            raise ValueError("score requires an ordered scale")
        if kind == "noul" and criteria is not None and (not isinstance(criteria, dict) or not set(criteria) <= {"true", "false"}):
            raise ValueError("invalid noul criteria")


def _validate_response(body: Any, questions: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(body, dict) or not isinstance(body.get("model"), str) or not body["model"].strip():
        raise JevError("invalid_response")
    answers = body.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise JevError("invalid_response")
    safe_answers: dict[str, Any] = {}
    for key, question in questions.items():
        answer = answers[key]
        kind = question["type"]
        if not isinstance(answer, dict) or answer.get("type") != kind:
            raise JevError("invalid_response")
        if kind == "noul":
            if not _prob(answer.get("noul")):
                raise JevError("invalid_response")
            safe_answers[key] = {"type": kind, "noul": answer["noul"]}
            continue
        expected = set(question["criteria"]) if kind == "choice" else {str(i) for i in range(len(question["criteria"]))}
        probabilities = answer.get("probabilities")
        if not isinstance(probabilities, dict) or set(probabilities) != expected or not all(_prob(v) for v in probabilities.values()) or abs(sum(probabilities.values()) - 1) > 0.02 or not _prob(answer.get("confidence")):
            raise JevError("invalid_response")
        if kind == "choice":
            if answer.get("choice") not in expected or probabilities[answer["choice"]] + 0.02 < max(probabilities.values()):
                raise JevError("invalid_response")
            safe_answers[key] = {"type": kind, "choice": answer["choice"], "probabilities": probabilities, "confidence": answer["confidence"]}
        else:
            legend = answer.get("legend")
            if (not isinstance(legend, dict) or set(legend) != expected
                    or [legend[str(i)] for i in range(len(expected))] != question["criteria"]
                    or type(answer.get("score")) not in (int, float)
                    or not 0 <= answer["score"] <= len(expected) - 1):
                raise JevError("invalid_response")
            safe_answers[key] = {"type": kind, "score": answer["score"], "legend": legend, "probabilities": probabilities, "confidence": answer["confidence"]}
    usage = body.get("usage")
    safe_usage = None
    if usage is not None:
        if not isinstance(usage, dict):
            raise JevError("invalid_response")
        safe_usage = {}
        for name in ("input_tokens", "output_tokens"):
            value = usage.get(name)
            if value is not None and (type(value) is not int or value < 0):
                raise JevError("invalid_response")
            safe_usage[name] = value
    return {"model": body["model"], "answers": safe_answers, "usage": safe_usage}


def evaluate(
    state: str | dict | list,
    questions: dict[str, Any],
    *,
    timeout_s: float = 20.0,
    max_attempts: int = 3,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Evaluate one state. Retries reuse a request idempotency key."""
    _validate_request(state, questions)
    key = os.environ.get("JEV_API_KEY")
    if not key:
        raise JevError("missing_credentials")
    if timeout_s <= 0 or not 1 <= max_attempts <= 5:
        raise ValueError("invalid timeout or retry bound")
    payload = {"state": state, "model": MODEL, "questions": questions}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())}
    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=timeout_s)
    assert client is not None
    start = time.monotonic()
    try:
        for attempt in range(1, max_attempts + 1):
            try:
                response = client.post(URL, json=payload, headers=headers, timeout=timeout_s)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
                if attempt == max_attempts:
                    raise JevError("transport_failure") from None
                sleep(min(8.0, 0.5 * 2 ** (attempt - 1)) + random.uniform(0, 0.2))
                continue
            if response.status_code == 200:
                try:
                    safe = _validate_response(response.json(), questions)
                except ValueError:
                    raise JevError("invalid_response") from None
                return {"adapter_version": ADAPTER_VERSION, "requested_model": MODEL, "resolved_model": safe["model"], "raw_response": safe, "latency_ms": round((time.monotonic() - start) * 1000, 2), "timeout_s": timeout_s, "attempts": attempt}
            if response.status_code in {401, 422}:
                raise JevError("hard_http_failure", response.status_code)
            if response.status_code in {429, 529} or 500 <= response.status_code <= 599:
                if attempt < max_attempts:
                    sleep(min(8.0, 0.5 * 2 ** (attempt - 1)) + random.uniform(0, 0.2))
                    continue
                raise JevError("retry_exhausted", response.status_code)
            raise JevError("http_failure", response.status_code)
        raise AssertionError("unreachable")
    finally:
        if owns_client:
            client.close()
