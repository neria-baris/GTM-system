"""Deterministic canonical SQLite persistence and read-only validation for C/D."""
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from src.belief.signals import SignalError, validate_signal
from src.ledger.store import Ledger
from src.settings import business_as_of
from .quantitative import weekly_state


def load_canonical(path):
    path = Path(path).resolve()
    ledger = Ledger.__new__(Ledger)
    ledger.db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    ledger.db.row_factory = sqlite3.Row
    stage_c = json.loads(ledger.db.execute("SELECT payload FROM canonical_metadata WHERE key='integration'").fetchone()[0])
    return ledger, stage_c


def save_canonical(ledger, stage_c, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".building.sqlite")
    if temp.exists():
        raise ValueError("Unfinished canonical build exists; inspect before replacing")
    with closing(sqlite3.connect(temp)) as target:
        ledger.db.backup(target)
        target.execute("CREATE TABLE canonical_metadata(key TEXT PRIMARY KEY,payload TEXT NOT NULL)")
        target.execute("INSERT INTO canonical_metadata VALUES ('integration',?)", (json.dumps(stage_c, sort_keys=True, ensure_ascii=False),))
        target.execute("CREATE TABLE review_item(review_id TEXT PRIMARY KEY,payload TEXT NOT NULL)")
        for item in stage_c["review_items"]:
            target.execute("INSERT INTO review_item VALUES (?,?)", (item["review_id"], json.dumps(item, sort_keys=True)))
        target.commit()
    result = validate_canonical(temp)
    temp.replace(path)
    return result


def validate_canonical(path):
    ledger, stage_c = load_canonical(path)
    try:
        if ledger.db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or list(ledger.db.execute("PRAGMA foreign_key_check")):
            raise ValueError("Canonical SQLite integrity failure")
        rows = lambda table: [json.loads(r[0]) for r in ledger.db.execute(f"SELECT payload FROM {table}")]
        entities = {x["id"]: x for x in rows("entity")}
        evidence = {x["evidence_id"]: x for x in rows("evidence")}
        events, values, claims = rows("event"), rows("commercial_value"), rows("claim")
        kinds = dict(ledger.db.execute("SELECT kind,COUNT(*) FROM entity GROUP BY kind"))
        opps = {oid: x for oid, x in entities.items() if "use_case_code" in x}
        for oid, opp in opps.items():
            scope = entities.get(opp["commercial_scope_id"])
            if not scope or scope["account_id"] != opp["account_id"] or opp["account_id"] not in entities or opp["origin_evidence_id"] not in evidence:
                raise ValueError("Canonical opportunity has broken identity/scope/evidence")
        for ev in evidence.values():
            ref = ev["source_ref"]
            raw = ledger.db.execute("SELECT content FROM raw_source WHERE system=? AND object_type=? AND native_id=? AND version=?",
                (ref["system"], ref["object_type"], ref["native_id"], ev["source_version"])).fetchone()
            if not raw or raw[0][ev["start_offset"]:ev["end_offset"]] != ev["verbatim_excerpt"]:
                raise ValueError("Canonical evidence has invalid raw span")
        for item in events + values + claims:
            ids = item.get("evidence_ids", item.get("source_evidence_ids", []))
            if not ids or not set(ids) <= evidence.keys():
                raise ValueError("Canonical event/value/claim lacks evidence")
            if item.get("opportunity_id") and item["opportunity_id"] not in opps:
                raise ValueError("Canonical event/value has broken opportunity")
            if item.get("verification") == "document_verified" or item.get("status") == "signed_verified":
                raise ValueError("Extraction-only production state attempted documentary verification")
        for event in events:
            if event["polarity"] != "positive" or event["status"] != "observed":
                raise ValueError("Non-asserted semantic event became a journey event")
        signal_rows = list(ledger.db.execute("SELECT signal_id,signal_type,opportunity_id,effective_date,payload FROM atomic_signal")
                           ) if ledger.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='atomic_signal'").fetchone() else []
        signals = [json.loads(r[4]) for r in signal_rows]
        for row, signal in zip(signal_rows, signals):
            if tuple(row[:4]) != tuple(signal.get(k) for k in ("signal_id", "signal_type", "opportunity_id", "effective_date")):
                raise ValueError("Canonical atomic signal row differs from its payload")
            try:
                validate_signal(signal)
            except (SignalError, KeyError) as exc:
                raise ValueError(f"Canonical atomic signal is invalid: {exc}") from exc
            if not set(signal["evidence_ids"]) <= evidence.keys():
                raise ValueError("Canonical atomic signal lacks evidence")
            if signal.get("opportunity_id") and signal["opportunity_id"] not in opps:
                raise ValueError("Canonical atomic signal has broken opportunity")
            if signal["signal_type"] == "formal_signature_verified" or signal["extraction_method"] == "verification_gate":
                raise ValueError("Extraction-only production state attempted documentary verification")
        expected = stage_c["c2_semantic_counts"]
        if expected["opportunity_candidate_count"] > 0 and not opps:
            raise ValueError("Accepted C2 opportunities became zero canonical opportunities")
        event_signals = [r for r in ledger.db.execute("SELECT payload FROM atomic_signal")
                         if json.loads(r[0]).get("details", {}).get("predicate") == "semantic:events"]             if ledger.db.execute("SELECT 1 FROM sqlite_master WHERE name='atomic_signal'").fetchone() else []
        # Asserted events without typed details are kept as signals, not dropped.
        if expected["event_candidate_count"] > 0 and not events and not event_signals:
            raise ValueError("Accepted C2 events became zero canonical events")
        state = weekly_state(ledger, business_as_of())
        if state["verified_actual_usd"] != "0":
            raise ValueError("Model-only evidence changed Verified Actual")
        dispositions = {d["candidate_id"]: d for d in stage_c["candidate_dispositions"]}
        for review in stage_c["review_items"]:
            ids = review.get("evidence_ids") or [dispositions[c]["evidence_id"] for c in review.get("candidate_ids", [])]
            if not ids or not set(ids) <= evidence.keys():
                raise ValueError("Canonical review lacks source evidence")
        return {"canonical_gate_passed": True, "entity_counts": kinds,
            "canonical_opportunity_count": len(opps), "canonical_opportunity_ids": sorted(opps),
            "canonical_event_count": len(events), "events_by_type": dict(Counter(e["event_type"] for e in events)),
            "linked_event_count": sum(e["opportunity_id"] is not None for e in events),
            "undated_event_count": sum(e["event_date"] is None for e in events),
            "canonical_value_count": len(values), "claim_count": len(claims), "evidence_count": len(evidence),
            "review_item_count": len(stage_c["review_items"]), "conflict_count": ledger.count("conflict"),
            "atomic_signal_count": len(signals),
            "atomic_signals_by_type": dict(Counter(s["signal_type"] for s in signals)),
            "resolution_counts": dict(Counter(o["resolution_status"] for o in opps.values())),
            "reported_signature_pending_verification_count": sum(e["event_type"] == "commercial_signed" for e in events),
            "verified_actual_usd": state["verified_actual_usd"], "input_hashes": stage_c["input_hashes"],
            "production_sources": "A2 immutable snapshots and C2 accepted proposals; no audit fixtures"}
    finally:
        ledger.close()
