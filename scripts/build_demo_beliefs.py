"""Derive demo/belief_states.json from the frozen presentation snapshot (offline).

The canonical SQLite behind the frozen demo is not shipped and Luna/Jev cannot be
re-run offline, so atomic signals are derived here from the frozen exact excerpts
with the deterministic language sensor (src.belief.signals.lexical_signals), plus
the published event timeline and commercial values. The six frozen data files are
read only; the manifest gains exactly one inventory entry (belief_states.json).
Output is deterministic: rerunning produces identical bytes.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.belief import engine, presentation  # noqa: E402
from src.belief.metrics import inferred_stage  # noqa: E402
from src.belief.ontology import DIMENSION_LABELS, VALUE_LABELS  # noqa: E402
from src.belief.signals import EVENT_SIGNALS, SignalError, lexical_signals, make_signal  # noqa: E402

FROZEN = ("overview", "opportunities", "opportunity_details", "weekly_snapshots", "evidence_summaries", "review_queue")
OUTPUT_NAME = "belief_states.json"
BUILDER = "scripts/build_demo_beliefs.py"
SENSOR = "Offline deterministic language sensor over frozen exact excerpts; Luna and Jev are not re-run for the demo"
NOTE = ("Derived offline from the frozen presentation snapshot. Atomic signals come from the deterministic language "
        "sensor applied to each displayed opportunity's own exact excerpts, from the published event timeline and from "
        "published commercial values. Evidence from other notes is not attached (identity is not inferred here). "
        "Confidence bands are heuristic support levels, not probabilities. Inferred states never change Verified Actual.")


def dumps(payload: Any, newline: str = "\n") -> str:
    """Same formatting as the frozen files; their line-ending convention is preserved."""
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").replace("\n", newline)


def newline_of(runtime: Path) -> str:
    return "\r\n" if b"\r\n" in (runtime / "manifest.json").read_bytes() else "\n"


def load(runtime: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    manifest = json.loads((runtime / "manifest.json").read_text(encoding="utf-8"))
    data, hashes = {}, {}
    for name in FROZEN:
        raw = (runtime / f"{name}.json").read_bytes()
        hashes[f"{name}.json"] = hashlib.sha256(raw).hexdigest()
        expected = manifest["files"].get(f"{name}.json")
        if expected != hashes[f"{name}.json"]:
            raise ValueError(f"Frozen file does not match the manifest: {name}.json")
        payload = json.loads(raw)
        if payload.get("kind") != name:
            raise ValueError(f"Unexpected payload kind in {name}.json")
        data[name] = payload["data"]
    return manifest, data, hashes


def availability(evidence: dict[str, Any], ids) -> list[dict[str, Any]]:
    out = []
    for eid in sorted(set(ids)):
        e = evidence[eid]
        out.append({"evidence_id": eid, "documented_at": e.get("documented_at"),
                    "source_first_seen_at": e.get("source_first_seen_at"),
                    "business_event_date": e.get("business_date"), "independence_group": e.get("reference")})
    return out


def excerpt_signals(evidence: dict[str, Any], ids, *, opportunity_id: str | None = None,
                    account_id: str | None = None, subject_ref: str | None = None) -> list[dict[str, Any]]:
    """Language-sensor signals, one per (subject, evidence, reading index, type), plus meetings per dated note."""
    scope = opportunity_id or subject_ref
    out = []
    for eid in sorted(ids):
        e = evidence[eid]
        for n, reading in enumerate(lexical_signals(e.get("exact_excerpt") or "")):
            out.append(make_signal(
                reading["signal_type"], evidence_ids=[eid], method="deterministic_rule",
                id_seed=f"demo:{scope}:{eid}:{n}:{reading['signal_type']}",
                effective_date=e.get("business_date"), modality=reading["modality"],
                observation=reading["observation"], confidence=reading["confidence"],
                contract_kind=reading["contract_kind"], opportunity_id=opportunity_id, account_id=account_id,
                subject_ref=subject_ref, evidence_availability=availability(evidence, [eid]),
                details={**(reading.get("details") or {}), "clause": reading["clause"]}))
    # A dated meeting note records a meeting held on its business date.
    notes: dict[tuple[str, str], list[str]] = defaultdict(list)
    for eid in ids:
        e = evidence[eid]
        if e.get("business_date") and e.get("source_type") == "page":
            notes[(e["reference"], e["business_date"][:10])].append(eid)
    for (reference, day), eids in sorted(notes.items()):
        dated = sorted(i for i in eids if (evidence[i].get("exact_excerpt") or "").strip() == day)
        chosen = dated[:1] or sorted(eids)[:1]
        out.append(make_signal(
            "meeting_held", evidence_ids=chosen, method="deterministic_rule", confidence="high",
            id_seed=f"demo:{scope}:meeting:{reference}:{day}", effective_date=day,
            date_basis="source_explicit_date", opportunity_id=opportunity_id, account_id=account_id,
            subject_ref=subject_ref, evidence_availability=availability(evidence, chosen),
            details={"source_reference": reference, "rule": "dated meeting note"}))
    return out


def opportunity_signals(row: dict[str, Any], evidence: dict[str, Any], reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    oid, account = row["opportunity_id"], row.get("account_id")
    ids = set(row.get("supporting_evidence_ids") or []) | set(row.get("conflicting_evidence_ids") or [])
    ids |= {e for r in reviews if r.get("opportunity_id") == oid for e in r.get("evidence_ids") or []}
    ids = {i for i in ids if i in evidence}
    signals = excerpt_signals(evidence, ids, opportunity_id=oid, account_id=account)
    for event in row.get("event_timeline") or []:
        eids = [i for i in event.get("evidence_ids") or [] if i in evidence]
        if not eids:
            continue
        for kind, contract_kind in EVENT_SIGNALS.get(event["event_type"], ()):
            signals.append(make_signal(
                kind, evidence_ids=eids, method="luna_semantic", id_seed=f"event:{event['event_id']}:{kind}",
                effective_date=event.get("event_date"), confidence="medium", contract_kind=contract_kind,
                opportunity_id=oid, account_id=account, evidence_availability=availability(evidence, eids),
                details={"event_id": event["event_id"], "event_type": event["event_type"],
                         "event_verification": event.get("verification")}))
    for value in row.get("commercial_values") or []:
        eids = [i for i in value.get("evidence_ids") or [] if i in evidence]
        if not eids:
            continue
        dates = sorted(evidence[i]["business_date"][:10] for i in eids if evidence[i].get("business_date"))
        signals.append(make_signal(
            "pricing_discussed", evidence_ids=eids, method="deterministic_rule",
            id_seed=f"value:{oid}:{value['value_id']}", effective_date=dates[-1] if dates else None,
            confidence="high", contract_kind="pilot" if value.get("value_type") == "pilot_fee" else "commercial",
            opportunity_id=oid, account_id=account, evidence_availability=availability(evidence, eids),
            details={"value_id": value["value_id"], "value_type": value.get("value_type"),
                     "value_status": value.get("status")}))
    return signals


def build(runtime: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest, data, hashes = load(runtime)
    evidence = {e["evidence_id"]: e for e in data["evidence_summaries"]}
    signals = [s for row in data["opportunity_details"]
               for s in opportunity_signals(row, evidence, data["review_queue"])]
    # Every note/record is a source group; reconstruction may link it to a deal by context.
    groups: dict[str, list[str]] = defaultdict(list)
    for eid, e in sorted(evidence.items()):
        groups[e["reference"]].append(eid)
    sources = {g: [{"evidence_id": i, "text": evidence[i].get("exact_excerpt") or "",
                    "date": (evidence[i].get("business_date") or "")[:10] or None} for i in ids] for g, ids in groups.items()}
    source_signals = {g: excerpt_signals(evidence, ids, subject_ref=f"source:{g}") for g, ids in groups.items()}
    seed_groups = {row["opportunity_id"]: {evidence[i]["reference"] for s in signals if s["opportunity_id"] == row["opportunity_id"]
                                           for i in s["evidence_ids"]} for row in data["opportunity_details"]}
    result = presentation.build(
        sources=sources, source_signals=source_signals, seed_groups=seed_groups,
        opportunities=data["opportunity_details"], signals=signals, business_as_of=manifest["business_as_of"],
        knowledge_cutoff=manifest["knowledge_cutoff"], weeks=[w["week_end"] for w in data["weekly_snapshots"]],
        historical_quality=manifest["historical_knowledge_quality"], review_items=data["review_queue"],
        verified_actual_usd=data["overview"]["verified_signed_acv_usd"],
        reported_unverified_usd=data["overview"]["reported_signed_pending_verification_usd"],
        evidence_ids=set(evidence))
    result["provenance"] = {"derived_from_snapshot_id": manifest["snapshot_id"], "input_file_sha256": hashes,
                            "builder": BUILDER, "sensor": SENSOR, "note": NOTE}
    payload = {"schema_version": manifest["schema_version"], "kind": "belief_states", "data": result}
    return payload, {"manifest": manifest, "data": data, "evidence": evidence, "signals": signals}


def write(runtime: Path, payload: dict[str, Any], output: Path | None = None) -> Path:
    newline = newline_of(runtime)
    text = dumps(payload, newline)
    target = output or runtime / OUTPUT_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))
    if output is None:
        path = runtime / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["files"][OUTPUT_NAME] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        path.write_bytes(dumps(manifest, newline).encode("utf-8"))
    return target


# ---------------------------------------------------------------------------
# Before/after report.

def _fmt(state: dict[str, Any]) -> str:
    value = VALUE_LABELS.get(state["value"], state["value"])
    return f"{value} ({state['band'].replace('_', ' ')})" if state.get("band") else value


def _cell(text: Any) -> str:
    return str(text if text is not None else "—").replace("|", "\\|").replace("\n", " ")


EXAMPLE_PATTERNS = ("Pilot live since", "Contract NOT signed yet", "Lost - security review",
                    "Steering committee: go to commercial", "SIGNED.")


def source_examples(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    evidence, data = ctx["evidence"], ctx["data"]
    as_of = ctx["manifest"]["business_as_of"]
    linked = set()
    for row in data["opportunity_details"]:
        linked |= set(row.get("supporting_evidence_ids") or []) | set(row.get("conflicting_evidence_ids") or [])
    linked |= {e for r in data["review_queue"] if r.get("opportunity_id") for e in r["evidence_ids"]}
    linked_refs = {evidence[e]["reference"] for e in linked if e in evidence}
    by_ref: dict[str, list[str]] = defaultdict(list)
    for eid, e in evidence.items():
        by_ref[e["reference"]].append(eid)
    examples = []
    for pattern in EXAMPLE_PATTERNS:
        refs = sorted(r for r, ids in by_ref.items() if r not in linked_refs
                      and any(pattern in (evidence[i].get("exact_excerpt") or "") for i in ids))
        if not refs:
            continue
        ref = refs[0]
        ids = by_ref[ref]
        signals = excerpt_signals(evidence, ids, subject_ref=f"source:{ref}")
        dated = any(s.get("effective_date") for s in signals)
        illustrative = False
        if not dated:
            # Undated source: signals cannot enter a dated belief. For illustration only, the
            # same readings are evaluated as if dated at the snapshot date (not published).
            illustrative = True
            signals = [{**s, "effective_date": as_of, "date_basis": "illustrative_snapshot_date"} for s in signals]
        belief = engine.infer(signals, as_of)
        examples.append({"pattern": pattern, "reference": ref, "source_system": evidence[ids[0]]["source_system"],
                         "business_dates": sorted({evidence[i]["business_date"] for i in ids if evidence[i].get("business_date")}),
                         "excerpts": sorted({evidence[i]["exact_excerpt"] for i in ids}),
                         "signals": sorted({(s["signal_type"], s["modality"], s["details"].get("retyped_from") or "",
                                             s["details"].get("inert_reason") or "") for s in signals}),
                         "illustrative": illustrative, "belief": belief, "stage": inferred_stage(belief)})
    return examples


def report(payload: dict[str, Any], ctx: dict[str, Any]) -> str:
    result, data, manifest = payload["data"], ctx["data"], ctx["manifest"]
    rows = {r["opportunity_id"]: r for r in data["opportunity_details"]}
    triage = result["review_triage"]
    lines = [
        "# Belief layer: before / after on the frozen demo snapshot", "",
        f"Snapshot `{manifest['snapshot_id']}` · business as of {manifest['business_as_of']} · "
        f"generated by `{BUILDER}` (deterministic; rerun gives identical bytes).", "",
        f"**Sensor disclosure.** {SENSOR}. The canonical SQLite behind the frozen demo is not shipped, so atomic signals "
        "are derived from the frozen exact excerpts of each displayed opportunity, its published event timeline "
        "(`luna_semantic`, because the demo events came from semantic integration) and its published commercial values. "
        "Evidence from other notes is not attached to an opportunity; identity is not inferred here.", "",
        f"**Verified Actual is unchanged: {data['overview']['verified_signed_acv_usd']} USD** "
        "(`$0`). No inferred state is added to any money total; the belief layer only adds inferred, labelled states.", "",
        "Confidence bands are heuristic support levels (ordinal), not probabilities.", "",
        "## 1. Per opportunity", "",
        "| Opportunity | BEFORE (tracker fields) | AFTER (inferred, with band) |",
        "|---|---|---|",
    ]
    for oid, belief in sorted(result["opportunities"].items(), key=lambda kv: (rows[kv[0]]["account_label"], kv[0])):
        r = rows[oid]
        states = belief["current"]["states"]
        linked = sum(1 for x in data["review_queue"] if x.get("opportunity_id") == oid)
        needed = sum(1 for x in data["review_queue"] if x.get("opportunity_id") == oid and triage[x["review_id"]]["decision_needed"])
        needed += sum(1 for x in result["belief_review_items"] if x["opportunity_id"] == oid)
        before = (f"pilot_state={r.get('pilot_state')}; commercial_state={r.get('commercial_state')}; "
                  f"lifecycle={r.get('lifecycle')}; momentum={r.get('momentum')}; readiness_band={r.get('readiness_band')}; "
                  f"linked review items={linked}")
        after = (f"**{belief['headline']['text']}**<br>stage: {belief['inferred_stage']}; "
                 + "; ".join(f"{DIMENSION_LABELS[d]}: {_fmt(states[d])}" for d in
                             ("pilot_status", "buyer_commitment", "commercial_status", "momentum", "blocker_state"))
                 + f"; decision-needed review items={needed}")
        lines.append(f"| {_cell(r['account_label'])} `{oid[:8]}` | {_cell(before)} | {_cell(after)} |")
    summary = result["review_summary"]
    before_cats = Counter(x["reason"] for x in data["review_queue"])
    lines += ["", "## 2. Review queue", "",
              f"* **Before:** {len(data['review_queue'])} open review items, all presented as equally actionable "
              f"({len(before_cats)} distinct reasons).",
              f"* **After:** {summary['total']} items retained for audit ({len(result['belief_review_items'])} new "
              f"belief-engine items); **{summary['decision_needed']} decision-needed**, {summary['informational']} informational.",
              "", "| Triage category | Decision needed | Items |", "|---|---|---|"]
    needed_by_cat = {t["category"]: t["decision_needed"] for t in triage.values()}
    for cat, n in sorted(summary["by_category"].items(), key=lambda kv: (not needed_by_cat[kv[0]], -kv[1], kv[0])):
        lines.append(f"| {cat} | {'yes' if needed_by_cat[cat] else 'no'} | {n} |")
    ov = result["overview"]
    lines += ["", "## 3. Portfolio (inferred — not verified, not a forecast)", "",
              f"* Operationally active pilots (high+): {ov['operationally_active_pilots']}",
              f"* Likely committed pilots: {ov['likely_committed_pilots']}",
              f"* Likely committed buyers: {ov['likely_committed_buyers']}",
              f"* Commercial process underway: {ov['commercial_process_underway']}",
              f"* Likely stalled: {ov['likely_stalled']}",
              f"* Probable blockers: {ov['probable_blockers']}",
              f"* Inferred stage distribution: {json.dumps(ov['inferred_stage_distribution'], sort_keys=True)}",
              f"* Momentum distribution: {json.dumps(ov['momentum_distribution'], sort_keys=True)}",
              f"* Verified Actual: {ov['value_buckets']['verified_actual_usd']} USD (unchanged); reported unverified: "
              f"{ov['value_buckets']['reported_unverified_usd'] or 'unknown'}.",
              "", "## 4. Source-scoped examples (unlinked notes)", "",
              "Each example runs the engine on all evidence of one note or record that is not linked to a displayed "
              "opportunity (`subject_ref = source:<reference>`). These are not published as opportunities.", ""]
    for ex in source_examples(ctx):
        belief = ex["belief"]
        lines += [f"### “{ex['pattern']}” — {ex['source_system']} `{ex['reference']}`", "",
                  "Excerpts: " + " · ".join(f"“{_cell(x)}”" for x in ex["excerpts"][:10]), "",
                  "Signals (type / modality / retyped from / inert reason): "
                  + "; ".join("/".join(x for x in s if x) for s in ex["signals"]), ""]
        if ex["illustrative"]:
            lines += ["*Undated source: these signals cannot enter a dated belief state. The states below are an "
                      "illustration only, evaluating the same readings as if dated at the snapshot date.*", ""]
        lines.append(f"Inferred stage: **{ex['stage']}**")
        lines.append("")
        for d in ("pilot_status", "buyer_commitment", "commercial_status", "procurement_status", "momentum", "blocker_state"):
            s = belief["states"][d]
            if s.get("band"):
                lines.append(f"* {s['explanation']}")
        lines.append("")
    lines += ["## 5. Boundaries", ""] + [f"* {b}" for b in result["boundaries"]] + [""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=ROOT / "demo")
    parser.add_argument("--output", type=Path, help="Write the belief file here instead of the runtime (no manifest change)")
    parser.add_argument("--report", type=Path, help="Write a markdown before/after report")
    args = parser.parse_args()
    payload, ctx = build(args.runtime)
    target = write(args.runtime, payload, args.output)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_bytes(report(payload, ctx).encode("utf-8"))
    summary = payload["data"]["review_summary"]
    print(json.dumps({"written": str(target), "opportunities": len(payload["data"]["opportunities"]),
                      "signals": len(ctx["signals"]), "review_total": summary["total"],
                      "decision_needed": summary["decision_needed"],
                      "inferred_stage_distribution": payload["data"]["overview"]["inferred_stage_distribution"]}))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, SignalError) as exc:
        raise SystemExit("Unable to build demo beliefs: " + str(exc))
