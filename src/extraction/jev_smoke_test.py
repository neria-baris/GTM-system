"""One live Jev request; deliberately no retries or document data."""
from __future__ import annotations

import json

from .jev_adapter import JevError, choice_question, evaluate


def main() -> int:
    questions = {
        "pilot_contract_status": choice_question("What is the explicitly reported status of the pilot contract?", {"signed": "Pilot contract explicitly signed", "not_signed": "Pilot explicitly unsigned", "unclear": "No clear pilot status"}),
        "commercial_contract_status": choice_question("What is the explicitly reported status of the commercial deployment contract? Do not treat the pilot as commercial.", {"signed": "Commercial contract explicitly signed", "not_signed": "Commercial contract explicitly unsigned", "unclear": "No clear commercial status"}),
        "procurement_legal_state": choice_question("What is the explicitly reported procurement or legal state for the commercial contract?", {"not_started_explicit": "Explicitly not started", "required": "Required, not underway", "in_progress": "Review underway", "approved": "Approved", "rejected": "Rejected", "unknown": "No evidence"}),
    }
    try:
        result = evaluate("Pilot signed: €135k. Commercial contract NOT signed yet; legal is reviewing pricing.", questions, max_attempts=1)
    except JevError as exc:
        print(json.dumps({"live_run_status": "failed", "failure_kind": exc.kind, "status_code": exc.status_code}))
        return 1
    print(json.dumps({"live_run_status": "success", "requested_model": result["requested_model"], "resolved_model": result["resolved_model"], "attempts": result["attempts"], "latency_ms": result["latency_ms"], "usage": result["raw_response"]["usage"], "choices": {k: v["choice"] for k, v in result["raw_response"]["answers"].items()}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
