"""Frozen rules versus single and repeated live Jev extraction benchmark.

This module produces annotations and a routing policy only. It has no ledger
write path and cannot set verified commercial signature or VerifiedActualUSD.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import statistics
from pathlib import Path
from typing import Any

from .jev_adapter import ADAPTER_VERSION, MODEL, JevError, choice_question, evaluate

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "experiments/extraction/frozen_v1.json"
RULE_VERSION = "rules_1.1.0"
THRESHOLDS = (0.70, 0.85, 0.95)
UNKNOWN = {"unclear", "unknown"}

RUBRICS: dict[str, tuple[str, dict[str, str]]] = {
    "contract_kind": ("Which contract kind is explicitly discussed? If multiple kinds, choose the one whose status is most directly stated; otherwise unclear. Do not infer a signed contract.", {"pilot": "Pilot trial agreement", "commercial": "Commercial deployment or rollout", "amendment": "Change to a signed contract", "renewal": "Extension of existing contract term", "unclear": "No unambiguous contract kind"}),
    "pilot_contract_status": ("What is the explicitly reported status of the pilot contract in this note? Absence is unclear. A template, draft, or prediction is not a customer action.", {"signed": "Pilot explicitly reported signed", "not_signed": "Pilot explicitly reported unsigned", "verbal_yes": "Verbal agreement only", "drafting": "Pilot SOW or agreement being drafted", "unclear": "No supported pilot status"}),
    "commercial_contract_status": ("What is the explicitly reported status of the commercial deployment contract? A signed pilot, budget, verbal yes, draft, forecast, or CRM stage is not a commercial signature. Absence is unclear.", {"signed": "Commercial contract explicitly reported signed", "not_signed": "Commercial contract explicitly reported unsigned", "proposal_or_terms": "Commercial proposal, SOW draft, pricing or terms only", "unclear": "No supported commercial status"}),
    "blocker_state": ("What is the explicitly reported status of a business, legal, or data blocker? Absence is unknown.", {"open": "Blocker currently open", "resolved": "Prior blocker explicitly resolved", "unknown": "No supported blocker state"}),
    "next_step_strength": ("What next step is evidenced? A seller plan is not a buyer agreement, and a proposed meeting is not a held meeting.", {"seller_plan": "Seller only plans to act", "buyer_agreed": "Buyer agreed a next action", "owner_and_date": "Buyer agreed with owner and date", "completed": "Next action explicitly completed", "unknown": "No supported next step"}),
    "buyer_involvement": ("What buyer participation is evidenced by a held meeting, not a proposal or contact title?", {"technical_only": "Explicitly technical participants only", "senior_stakeholder_met": "Senior stakeholder actually met", "economic_buyer_identified_and_met": "Budget owner identified and actually met", "unknown": "No supported buyer involvement level"}),
    "procurement_legal": ("What is the explicitly stated procurement or legal state for the relevant commercial scope? SOW drafting is not approval.", {"not_started_explicit": "Explicitly not started", "required": "Required, not started", "in_progress": "Review or negotiation underway", "approved": "Explicitly approved", "rejected": "Explicitly rejected", "unknown": "No supported status"}),
    "data_access": ("What data access is explicitly evidenced? Data named or requested is not data received.", {"requested": "Data explicitly requested", "provided_or_access_granted": "Data delivered or access granted", "access_blocked": "Access explicitly blocked", "unknown": "No supported access state"}),
}


def questions() -> dict[str, Any]:
    return {name: choice_question(instructions, criteria) for name, (instructions, criteria) in RUBRICS.items()}


def rules(text: str) -> dict[str, str]:
    """Conservative regex baseline. Every non-unknown return requires local wording."""
    lower = text.lower()
    result = {field: "unclear" if field in {"contract_kind", "pilot_contract_status", "commercial_contract_status"} else "unknown" for field in RUBRICS}
    if re.search(r"draft (?:outreach )?email|template copied|ai sync estimates|internal prediction", lower):
        return result
    pilot = bool(re.search(r"\bpilot\b", lower))
    commercial = bool(re.search(r"\bcommercial\b|\brollout\b|annual fee|\bacv\b", lower))
    result["contract_kind"] = "pilot" if pilot and not commercial else "commercial" if commercial and not pilot else "unclear"
    if re.search(r"\bamendment\b", lower):
        result["contract_kind"] = "amendment"
    if re.search(r"\brenewal\b", lower):
        result["contract_kind"] = "renewal"
    if re.search(r"pilot signed\s*:", lower):
        result["pilot_contract_status"] = "signed"
    elif re.search(r"pilot.{0,35}(?:not signed|unsigned|no signature)", lower):
        result["pilot_contract_status"] = "not_signed"
    elif re.search(r"verbal yes.{0,30}pilot", lower):
        result["pilot_contract_status"] = "verbal_yes"
    elif re.search(r"pilot.{0,25}sow.{0,20}draft", lower):
        result["pilot_contract_status"] = "drafting"
    if re.search(r"(?:commercial|contract|agreement).{0,30}(?:not signed|unsigned)|no contract signed|not a signed agreement", lower):
        result["commercial_contract_status"] = "not_signed"
    elif re.search(r"(?:commercial|deployment).{0,55}(?:signed|agreement)|signed.{0,30}(?:commercial|deployment)|signed\..{0,30}/yr", lower):
        result["commercial_contract_status"] = "signed"
    elif re.search(r"commercial sow.{0,25}draft|pricing not agreed|annual fee|terms in discussion|proposal sent", lower):
        result["commercial_contract_status"] = "proposal_or_terms"
    if re.search(r"blocker.{0,25}resolv|security approved access", lower):
        result["blocker_state"] = "resolved"
    elif re.search(r"block(?:ed|er)|not approved|no reply|pushback|waiting on data access|pricing not agreed", lower):
        result["blocker_state"] = "open"
    if re.search(r"next:|chase in|propose a .* meeting", lower):
        result["next_step_strength"] = "seller_plan"
    elif re.search(r"buyer agreed.{0,40}meeting", lower):
        result["next_step_strength"] = "buyer_agreed"
    if re.search(r"\bcfo\b.{0,55}(?:budget|attended)|(?:budget|attended).{0,55}\bcfo\b", lower):
        result["buyer_involvement"] = "economic_buyer_identified_and_met"
    if re.search(r"(?:legal|procurement).{0,25}(?:review|with)|reviewing pricing", lower):
        result["procurement_legal"] = "in_progress"
    elif re.search(r"security approved access", lower):
        result["procurement_legal"] = "approved"
    if re.search(r"(?:uploaded|provided|delivered).{0,60}data|uploaded 18 months|access granted|approved access", lower):
        result["data_access"] = "provided_or_access_granted"
    elif re.search(r"security.{0,30}blocked data|data access.{0,25}blocked", lower):
        result["data_access"] = "access_blocked"
    elif re.search(r"requested data|asked for data", lower):
        result["data_access"] = "requested"
    return result


def _safe_span_for_reported_signature(text: str) -> dict[str, Any] | None:
    """A proposal needs a quote; it is never contract verification."""
    if re.search(r"draft|template|prediction|chance of signing|if .*works|not signed|unsigned", text, re.I):
        return None
    match = re.search(r"(?:both parties signed.{0,65}commercial|commercial.{0,55}(?:signed|agreement signed)|SIGNED\..{0,35}/yr)", text, re.I)
    if not match:
        return None
    return {"start": match.start(), "end": match.end(), "exact_text": match.group(0)}


def _source_span(row: dict[str, Any], local_span: dict[str, Any]) -> dict[str, Any]:
    """Map a validated local quote to the immutable audit corpus when possible."""
    parent = row["source_span"]
    offset = parent["exact_text"].find(row["text"])
    if offset < 0 or row["text"][local_span["start"]:local_span["end"]] != local_span["exact_text"]:
        raise ValueError("quote is not an exact source substring")
    start = parent["start"] + offset + local_span["start"]
    return {"source_path": row["source_path"], "source_hash_sha256": row["source_hash_sha256"], "coordinate_system": "source_file_codepoints" if row["source_path"] else "synthetic_text", "start": start, "end": start + len(local_span["exact_text"]), "exact_text": local_span["exact_text"]}


def _metrics(rows: list[dict[str, Any]], predictions: dict[str, dict[str, str]]) -> dict[str, Any]:
    result: dict[str, Any] = {"n_documents": len(rows), "fields": {}}
    for field, (_, options) in RUBRICS.items():
        total = len(rows)
        abstained = sum(predictions[row["id"]][field] in UNKNOWN for row in rows)
        classes = {}
        for label in options:
            if label in UNKNOWN:
                continue
            tp = sum(predictions[row["id"]][field] == label and row["labels"][field] == label for row in rows)
            fp = sum(predictions[row["id"]][field] == label and row["labels"][field] != label for row in rows)
            fn = sum(predictions[row["id"]][field] != label and row["labels"][field] == label for row in rows)
            support = tp + fn
            precision = tp / (tp + fp) if tp + fp else None
            recall = tp / support if support else None
            f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else None
            classes[label] = {"support": support, "tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}
        result["fields"][field] = {"abstained": abstained, "abstention_rate": abstained / total if total else None, "classes": classes}
    return result


def _threshold(answers: dict[str, Any], threshold: float) -> dict[str, str]:
    result = {}
    for field, answer in answers.items():
        choice = answer["choice"]
        result[field] = choice if answer["probabilities"][choice] >= threshold and answer["confidence"] >= threshold else ("unclear" if field in {"contract_kind", "pilot_contract_status", "commercial_contract_status"} else "unknown")
    return result


def _ensemble(runs: list[dict[str, Any]], question_set: dict[str, Any] | None = None) -> dict[str, Any]:
    """Aggregate aligned primitive outputs; never average categorical labels."""
    if not runs:
        raise ValueError("an ensemble needs at least one run")
    question_set = questions() if question_set is None else question_set
    result = {}
    for field, question in question_set.items():
        answers = [run["raw_response"]["answers"][field] for run in runs]
        kind = question["type"]
        if any(answer["type"] != kind for answer in answers):
            raise ValueError("ensemble primitive types differ")
        if kind == "noul":
            probabilities = [answer["noul"] for answer in answers]
            result[field] = {"type": "noul", "mean_noul": statistics.fmean(probabilities),
                             "stddev_noul": statistics.pstdev(probabilities), "run_answers": answers}
            continue
        options = list(question["criteria"]) if kind == "choice" else [str(i) for i in range(len(question["criteria"]))]
        if any(set(answer["probabilities"]) != set(options) for answer in answers):
            raise ValueError("ensemble probability options differ from the question")
        if kind == "score" and any(answer["legend"] != answers[0]["legend"] for answer in answers):
            raise ValueError("ensemble Score levels differ across runs")
        means = {option: statistics.fmean(answer["probabilities"][option] for answer in answers) for option in options}
        deviations = {option: statistics.pstdev(answer["probabilities"][option] for answer in answers) for option in options}
        top = max(options, key=lambda option: means[option])
        confidence = [answer["confidence"] for answer in answers]
        aggregate = {
            "type": kind, "probabilities": means,
            "probability_stddev": deviations,
            "confidence": statistics.fmean(confidence),
            "confidence_min": min(confidence), "confidence_max": max(confidence),
            "run_answers": answers,
        }
        if kind == "choice":
            aggregate.update({"choice": top,
                              "top_choice_agreement": sum(answer["choice"] == top for answer in answers) / len(answers),
                              "all_runs_agree_on_top": all(answer["choice"] == top for answer in answers)})
        else:
            aggregate.update({"top_level": int(top), "legend": answers[0]["legend"]})
        result[field] = aggregate
    return result


def _signature_candidate(row: dict[str, Any], answer: dict[str, Any], *, ensemble: bool) -> bool:
    return bool(
        answer["choice"] == "signed"
        and answer["probabilities"]["signed"] >= 0.95
        and answer["confidence"] >= 0.95
        and (not ensemble or answer["all_runs_agree_on_top"])
        and _safe_span_for_reported_signature(row["text"]) is not None
    )


def _usage_summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "calls": len(runs),
        "input_tokens": sum((run["raw_response"]["usage"] or {}).get("input_tokens") or 0 for run in runs),
        "output_tokens": sum((run["raw_response"]["usage"] or {}).get("output_tokens") or 0 for run in runs),
        "total_latency_ms": round(sum(run["latency_ms"] for run in runs), 2),
        "median_call_latency_ms": round(statistics.median(run["latency_ms"] for run in runs), 2) if runs else None,
    }


def _route_stats(rows: list[dict[str, Any]], predictions: dict[str, dict[str, str]], field: str) -> dict[str, int]:
    """Unknown is abstention; a wrong known label counts as an error."""
    return {
        "covered": sum(predictions[row["id"]][field] not in UNKNOWN for row in rows),
        "errors": sum(predictions[row["id"]][field] not in UNKNOWN and predictions[row["id"]][field] != row["labels"][field] for row in rows),
        "critical_errors": sum(row["split"] == "critical_held_out" and predictions[row["id"]][field] not in UNKNOWN and predictions[row["id"]][field] != row["labels"][field] for row in rows),
    }


def run(require_jev: bool, output_dir: Path, jev_repeats: int = 5) -> int:
    if not 1 <= jev_repeats <= 20:
        raise ValueError("jev_repeats must be between 1 and 20")
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    rows = dataset["rows"]
    output_dir.mkdir(parents=True, exist_ok=True)
    rule_predictions = {row["id"]: rules(row["text"]) for row in rows}
    report: dict[str, Any] = {
        "adapter_version": ADAPTER_VERSION, "rules_version": RULE_VERSION,
        "requested_model": MODEL, "resolved_models": [],
        "dataset_version": dataset["dataset_version"], "dataset_label_status": dataset["label_status"],
        "run_timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "live_run_status": "not_run_missing_credentials", "provider_failures": [],
        "sample_size": len(rows), "audit_selected_count": sum(r["origin"] == "audit_selected" for r in rows),
        "critical_held_out_count": sum(r["split"] == "critical_held_out" for r in rows),
        "llm_provider_status": "not_run_missing_credentials" if not os.getenv("OPENAI_API_KEY") else "not_run_no_adapter_configured",
        "rules_metrics": _metrics(rows, rule_predictions),
        "splits_available": sorted({r["split"] for r in rows}),
        "jev_single": {"raw_metrics": None, "thresholded_metrics": {}, "split_metrics": {}, "usage": None},
        "jev_ensemble": {"k": jev_repeats, "raw_metrics": None, "thresholded_metrics": {}, "split_metrics": {}, "usage": None,
                         "incremental_usage_over_single": None, "agreement_summary": None, "variance_summary": None},
        "per_document": [], "estimated_cost_usd": None,
    }
    all_runs: dict[str, list[dict[str, Any]]] = {}
    if os.getenv("JEV_API_KEY"):
        report["live_run_status"] = "running"
        for row in rows:
            runs = []
            for repeat_index in range(jev_repeats):
                try:
                    response = evaluate(row["text"], questions())
                except JevError as exc:
                    report["provider_failures"].append({"document_id": row["id"], "repeat_index": repeat_index,
                                                        "kind": exc.kind, "status_code": exc.status_code})
                    break
                runs.append(response)
                report["resolved_models"].append(response["resolved_model"])
            if len(runs) != jev_repeats:
                if require_jev:
                    break
                continue
            all_runs[row["id"]] = runs
            aggregate = _ensemble(runs)
            report["per_document"].append({
                "document_id": row["id"], "source_ref": row["source_ref"], "split": row["split"],
                "source_path": row["source_path"], "source_hash_sha256": row["source_hash_sha256"],
                "source_span": row["source_span"],
                "gold_labels": row["labels"], "rule_labels": rule_predictions[row["id"]],
                "jev_single": runs[0], "jev_runs": runs, "jev_ensemble": aggregate,
                "jev_ensemble_usage": _usage_summary(runs),
            })
        report["resolved_models"] = sorted(set(report["resolved_models"]))
        report["live_run_status"] = "success" if len(all_runs) == len(rows) else "failed"
    evaluated = [row for row in rows if row["id"] in all_runs]
    single_answers = {row["id"]: all_runs[row["id"]][0]["raw_response"]["answers"] for row in evaluated}
    ensemble_answers = {row["id"]: _ensemble(all_runs[row["id"]]) for row in evaluated}
    if evaluated:
        for name, answers in (("jev_single", single_answers), ("jev_ensemble", ensemble_answers)):
            section = report[name]
            section["raw_metrics"] = _metrics(evaluated, {row["id"]: {field: ans["choice"] for field, ans in answers[row["id"]].items()} for row in evaluated})
            for threshold in THRESHOLDS:
                predictions = {row["id"]: _threshold(answers[row["id"]], threshold) for row in evaluated}
                section["thresholded_metrics"][str(threshold)] = _metrics(evaluated, predictions)
            for split in report["splits_available"]:
                split_rows = [row for row in evaluated if row["split"] == split]
                if split_rows:
                    section["split_metrics"][split] = {
                        "raw": _metrics(split_rows, {row["id"]: {field: ans["choice"] for field, ans in answers[row["id"]].items()} for row in split_rows}),
                        "threshold_0.95": _metrics(split_rows, {row["id"]: _threshold(answers[row["id"]], 0.95) for row in split_rows}),
                    }
            selected_runs = [run for row in evaluated for run in (all_runs[row["id"]][:1] if name == "jev_single" else all_runs[row["id"]])]
            section["usage"] = _usage_summary(selected_runs)
        single_usage = report["jev_single"]["usage"]
        ensemble_usage = report["jev_ensemble"]["usage"]
        report["jev_ensemble"]["incremental_usage_over_single"] = {
            key: round(ensemble_usage[key] - single_usage[key], 2) for key in
            ("calls", "input_tokens", "output_tokens", "total_latency_ms")
        }
        report["jev_ensemble"]["agreement_summary"] = {
            field: {"mean_top_choice_agreement": statistics.fmean(ensemble_answers[row["id"]][field]["top_choice_agreement"] for row in evaluated),
                    "unanimous_documents": sum(ensemble_answers[row["id"]][field]["all_runs_agree_on_top"] for row in evaluated)}
            for field in RUBRICS
        }
        report["jev_ensemble"]["variance_summary"] = {
            field: {option: statistics.fmean(ensemble_answers[row["id"]][field]["probability_stddev"][option] for row in evaluated)
                    for option in options}
            for field, (_, options) in RUBRICS.items()
        }
    # Preserve the original metric names for consumers of the first single-call report.
    report["jev_raw_metrics"] = report["jev_single"]["raw_metrics"]
    report["jev_thresholded_metrics"] = report["jev_single"]["thresholded_metrics"]
    if evaluated:
        single_usage = report["jev_single"]["usage"]
        report["latency_ms"] = {
            "total": single_usage["total_latency_ms"],
            "median_per_document": single_usage["median_call_latency_ms"],
            "max_per_document": max(all_runs[row["id"]][0]["latency_ms"] for row in evaluated),
        }
        report["token_usage"] = {key: single_usage[key] for key in ("input_tokens", "output_tokens", "calls")}
    else:
        report["latency_ms"] = None
        report["token_usage"] = None
    critical = [row for row in evaluated if row["split"] == "critical_held_out"]
    proposal_results = {}
    for name, answers in (("jev_single", single_answers), ("jev_ensemble", ensemble_answers)):
        proposed = [row for row in evaluated if _signature_candidate(row, answers[row["id"]]["commercial_contract_status"], ensemble=name == "jev_ensemble")]
        proposal_results[name] = {
            "proposed_count": len(proposed),
            "critical_held_out_false_positives": sum(row["split"] == "critical_held_out" and row["labels"]["commercial_contract_status"] != "signed" for row in proposed),
            "critical_held_out_true_positives": sum(row["split"] == "critical_held_out" and row["labels"]["commercial_contract_status"] == "signed" for row in proposed),
        }
    report["signature_proposal_comparison"] = proposal_results
    routes = {}
    selection_rows = [row for row in evaluated if row["split"] != "critical_held_out"]
    for field in RUBRICS:
        options = {"rules": {row["id"]: rule_predictions[row["id"]] for row in evaluated}}
        if evaluated:
            options["jev_single"] = {row["id"]: _threshold(single_answers[row["id"]], 0.95) for row in evaluated}
            options["jev_ensemble"] = {row["id"]: _threshold(ensemble_answers[row["id"]], 0.95) for row in evaluated}
        stats = {name: _route_stats(evaluated, predictions, field) for name, predictions in options.items()}
        selection_stats = {name: _route_stats(selection_rows, predictions, field) for name, predictions in options.items()}
        selected = "rules" if evaluated else "review"
        if selection_rows:
            baseline = selection_stats["rules"]
            baseline_critical = stats["rules"]["critical_errors"]
            for name in ("jev_single", "jev_ensemble"):
                candidate = selection_stats[name]
                if (stats[name]["critical_errors"] <= baseline_critical and candidate["errors"] <= baseline["errors"]
                        and (candidate["covered"] > baseline["covered"] or candidate["errors"] < baseline["errors"])):
                    selected, baseline, baseline_critical = name, candidate, stats[name]["critical_errors"]
        if field == "commercial_contract_status":
            # Classifier output remains a reported claim proposal, with an exact quote and review.
            selected = "review"
        routes[field] = {"route": selected, "threshold": 0.95 if selected.startswith("jev_") else None,
                         "agreement_policy": "all_runs_top_label" if selected == "jev_ensemble" else None,
                         "comparison": stats, "selection_subset_comparison": selection_stats}
    single_proposals = proposal_results["jev_single"]
    ensemble_proposals = proposal_results["jev_ensemble"]
    selected_signature_route = "jev_single"
    if (ensemble_proposals["critical_held_out_false_positives"] <= single_proposals["critical_held_out_false_positives"]
            and ensemble_proposals["critical_held_out_true_positives"] >= single_proposals["critical_held_out_true_positives"]
            and (ensemble_proposals["critical_held_out_false_positives"] < single_proposals["critical_held_out_false_positives"]
                 or ensemble_proposals["critical_held_out_true_positives"] > single_proposals["critical_held_out_true_positives"])):
        selected_signature_route = "jev_ensemble"
    selected_fp = proposal_results[selected_signature_route]["critical_held_out_false_positives"]
    candidate_rows = []
    selected_answers = ensemble_answers if selected_signature_route == "jev_ensemble" else single_answers
    for row in evaluated:
        if row["origin"] == "audit_selected" and _signature_candidate(row, selected_answers[row["id"]]["commercial_contract_status"], ensemble=selected_signature_route == "jev_ensemble"):
            candidate_rows.append({"document_id": row["id"], "source_ref": row["source_ref"],
                                   "span": _source_span(row, _safe_span_for_reported_signature(row["text"])),
                                   "proposed_claim": "reported_signed_pending_verification"})
    routing = {
        "policy_version": "routing_2.0.0", "dataset_version": dataset["dataset_version"],
        "field_routes": routes, "commercial_signature_proposal_route": selected_signature_route,
        "route_selection_subset": "noncritical_rows_only; frozen_v1 calls these held_out, so route selection is exploratory",
        "candidate_threshold": 0.95,
        "commercial_signature_agreement_policy": "all_runs_top_label" if selected_signature_route == "jev_ensemble" else "single_call",
        "critical_held_out_evaluated": len(critical), "critical_held_out_false_positive_proposals": selected_fp,
        "commercial_signature_auto_proposal_enabled": report["live_run_status"] == "success" and len(critical) == sum(r["split"] == "critical_held_out" for r in rows) and selected_fp == 0,
        "deployment_status": "research_only_pending_dual_human_adjudication",
        "candidate_proposals_for_review": candidate_rows,
        "required_verification": "identified_signed_commercial_document_or_authorized_attestation_with_parties_scope_signature_date_amount_term_and_currency",
        "verified_actual_usd_mutation_allowed": False,
        "always_review": ["reported commercial signature", "signed ACV unknown", "contract amendment", "financially material identity merge or split", "conflicting contract status"],
        "unknown_policy": "abstain_and_route_if_material",
        "limitations": "Provisional labels and one audit-reported commercial signature do not estimate generalization or calibrated accuracy. Repeated Jev calls do not imply statistical independence or improved calibration.",
    }
    (output_dir / "evaluation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "routing_policy.json").write_text(json.dumps(routing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mistakes = []
    for row in evaluated:
        answer = single_answers[row["id"]]["commercial_contract_status"]
        if answer["choice"] == "signed" and row["labels"]["commercial_contract_status"] != "signed":
            guarded = answer["probabilities"]["signed"] >= 0.95 and answer["confidence"] >= 0.95 and _safe_span_for_reported_signature(row["text"]) is not None
            mistakes.append(f"- `{row['id']}`: raw Jev said signed (p={answer['probabilities']['signed']}, confidence={answer['confidence']}); gold=`{row['labels']['commercial_contract_status']}`. Threshold and quote guard: {'passes' if guarded else 'rejected'}.")
    analysis = ["# Stage B error analysis", "", f"Dataset: `{dataset['dataset_version']}`; labels are provisional audit-derived labels, not dual human adjudication.", "", f"Live status: `{report['live_run_status']}`; resolved model(s): {', '.join(report['resolved_models']) or 'none'}.", "", "## Raw commercial signature errors", "", *(mistakes or ["- None observed in this fixture."]), "", f"Critical held-out false proposal count with selected {selected_signature_route} route, 0.95 threshold, unanimity when repeated, and quote guard: {selected_fp}.", "", "The ensemble averages aligned probability vectors, not labels. Its variance and agreement are descriptive; repeated calls do not imply statistical independence or improved calibration.", "", "A proposed reported signature still requires documentary or authorized attestation review. This fixture contains only one audit-reported commercial signature, so its recall and precision do not generalize.", ""]
    (output_dir / "error_analysis.md").write_text("\n".join(analysis), encoding="utf-8")
    print(json.dumps({"live_run_status": report["live_run_status"], "sample_size": len(rows), "jev_calls": sum(len(runs) for runs in all_runs.values()), "provider_failures": len(report["provider_failures"]), "commercial_signature_auto_proposal_enabled": routing["commercial_signature_auto_proposal_enabled"]}))
    return 1 if require_jev and report["live_run_status"] != "success" else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-jev", action="store_true")
    parser.add_argument("--jev-repeats", type=int, default=5)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/B")
    args = parser.parse_args()
    return run(args.require_jev, args.output_dir, args.jev_repeats)


if __name__ == "__main__":
    raise SystemExit(main())
