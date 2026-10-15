"""Repeated System One observations. A failed run invalidates the batch."""
from __future__ import annotations

import statistics
from typing import Any, Callable

from .jev_adapter import evaluate


def aggregate(runs: list[dict[str, Any]], questions: dict[str, Any]) -> dict[str, Any]:
    if not runs:
        raise ValueError("no successful Jev runs")
    result: dict[str, Any] = {}
    for field, question in questions.items():
        answers = [run["raw_response"]["answers"][field] for run in runs]
        if question["type"] == "choice":
            options = list(question["criteria"])
            if any(set(a["probabilities"]) != set(options) or a["choice"] not in options for a in answers):
                raise ValueError("unaligned choice vector")
            means = {o: statistics.fmean(a["probabilities"][o] for a in answers) for o in options}
            deviations = {o: statistics.pstdev(a["probabilities"][o] for a in answers) for o in options}
            top = max(options, key=lambda o: (means[o], -options.index(o)))
            confidences = [a["confidence"] for a in answers]
            result[field] = {
                "type": "choice", "mean_probabilities": means, "std_probabilities": deviations,
                "aggregate_choice": top, "top_choice_agreement_rate": sum(a["choice"] == top for a in answers) / len(answers),
                "mean_confidence": statistics.fmean(confidences), "min_confidence": min(confidences),
                "max_confidence": max(confidences),
                "identical_responses": all(a == answers[0] for a in answers),
            }
        elif question["type"] == "noul":
            values = [a["noul"] for a in answers]
            result[field] = {"type": "noul", "mean_noul": statistics.fmean(values),
                             "std_noul": statistics.pstdev(values),
                             "identical_responses": len(set(values)) == 1}
        else:
            raise ValueError("C2 supports only Choice and Noul aggregation")
    return result


def run_batch(state: str, questions: dict[str, Any], k: int,
              call: Callable[..., dict[str, Any]] = evaluate) -> dict[str, Any]:
    """Make exactly K separate calls. On any failure retain runs and abstain; no replacement calls."""
    if not 1 <= k <= 20:
        raise ValueError("Jev repeats must be between 1 and 20")
    runs = []
    failures = []
    for index in range(k):
        try:
            runs.append(call(state, questions))
        except Exception as exc:
            failures.append({"run_index": index, "kind": getattr(exc, "kind", type(exc).__name__),
                             "status_code": getattr(exc, "status_code", None)})
            break
    return {"requested_k": k, "successful_k": len(runs), "runs": runs, "failures": failures,
            "aggregate": aggregate(runs, questions) if len(runs) == k else None}


def commercial_signature_gate(batch: dict[str, Any], threshold: float = .95) -> bool:
    """Permits only a *reported* signature proposal, never verification or Actual."""
    if batch["successful_k"] != batch["requested_k"] or batch["requested_k"] < 2:
        return False
    item = (batch.get("aggregate") or {}).get("commercial_contract_status")
    return bool(item and item["aggregate_choice"] == "signed"
                and item["mean_probabilities"]["signed"] >= threshold
                and item["top_choice_agreement_rate"] == 1.0
                and all(run["raw_response"]["answers"]["commercial_contract_status"]["choice"] == "signed"
                        for run in batch["runs"]))
