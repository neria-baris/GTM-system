"""SQLite storage and conservative Stage A rules. Raw rows and ledger facts are append only."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from .models import (Alias, Claim, CommercialValue, Conflict, Event, Evidence,
                     EVENT_TYPES, SourceRef, VALUE_TYPES)


class LedgerError(ValueError):
    pass


SCHEMA_VERSION = "ledger_v1"
NAMESPACE = UUID("b90a5baf-cd71-4c47-98b7-0aa6ad38157c")
ENTITY_TYPES = {"Account", "Contact", "Opportunity", "CommercialScope", "Meeting", "OfferOrContract"}


def stable_id(kind: str, key: str) -> str:
    """Fixture/source-key UUID. Native IDs remain separate source references."""
    return str(uuid5(NAMESPACE, f"{kind}:{key}"))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      default=lambda obj: str(obj) if isinstance(obj, Decimal) else asdict(obj))


def _payload(record: Any) -> dict[str, Any]:
    return json.loads(_json(asdict(record)))


def _ref_key(ref: SourceRef) -> tuple[str, str, str]:
    return ref.system, ref.object_type, ref.native_id


def _known_by(timestamp: str, cutoff: str) -> bool:
    # A date-only cutoff denotes its entire civil day. Timestamp cutoffs retain
    # their precise clock time and UTC offset.
    if len(cutoff) == 10:
        return timestamp[:10] <= cutoff
    if len(timestamp) == 10:
        return timestamp < cutoff[:10]
    return datetime.fromisoformat(timestamp) <= datetime.fromisoformat(cutoff)


class Ledger:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self._schema()

    def close(self) -> None:
        self.db.close()

    def _schema(self) -> None:
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS raw_source(
          system TEXT NOT NULL, object_type TEXT NOT NULL, native_id TEXT NOT NULL,
          version TEXT NOT NULL, sha256 TEXT NOT NULL, content TEXT NOT NULL,
          first_seen_at TEXT NOT NULL, ingested_at TEXT NOT NULL,
          PRIMARY KEY(system,object_type,native_id,version));
        CREATE TABLE IF NOT EXISTS entity(
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
          created_in_ledger_at TEXT NOT NULL, resolution_status TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS source_link(
          system TEXT NOT NULL, object_type TEXT NOT NULL, native_id TEXT NOT NULL,
          entity_id TEXT NOT NULL REFERENCES entity(id),
          PRIMARY KEY(system,object_type,native_id));
        CREATE TABLE IF NOT EXISTS evidence(
          evidence_id TEXT PRIMARY KEY, source_system TEXT NOT NULL,
          source_object_type TEXT NOT NULL, native_id TEXT NOT NULL,
          source_version TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS claim(
          claim_id TEXT PRIMARY KEY, subject_id TEXT NOT NULL, predicate TEXT NOT NULL,
          contract_kind TEXT, scope_id TEXT, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS event(
          event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, account_id TEXT,
          opportunity_id TEXT, event_date TEXT, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS commercial_value(
          value_id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL, scope_id TEXT NOT NULL,
          replaces_value_id TEXT REFERENCES commercial_value(value_id), payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS alias_decision(
          alias_id TEXT PRIMARY KEY, normalized_string TEXT NOT NULL,
          entity_type TEXT NOT NULL, canonical_id TEXT, decision TEXT NOT NULL,
          decision_at TEXT, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS conflict(
          conflict_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS identity_relation(
          left_id TEXT NOT NULL, right_id TEXT NOT NULL, relation TEXT NOT NULL,
          evidence_id TEXT, PRIMARY KEY(left_id,right_id,relation));
        CREATE TABLE IF NOT EXISTS atomic_signal(
          signal_id TEXT PRIMARY KEY, signal_type TEXT NOT NULL, opportunity_id TEXT,
          effective_date TEXT, payload TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_signal_opp ON atomic_signal(opportunity_id,effective_date);
        CREATE INDEX IF NOT EXISTS idx_event_time ON event(event_date,opportunity_id);
        CREATE INDEX IF NOT EXISTS idx_alias ON alias_decision(entity_type,normalized_string);
        """)
        for table in ("raw_source", "entity", "source_link", "evidence", "claim", "event",
                      "commercial_value", "alias_decision", "conflict", "identity_relation",
                      "atomic_signal"):
            self.db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table} "
                            "BEGIN SELECT RAISE(ABORT, 'append-only ledger'); END")
            self.db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} "
                            "BEGIN SELECT RAISE(ABORT, 'append-only ledger'); END")

    def _insert_once(self, table: str, key_column: str, key: str, columns: dict[str, Any]) -> None:
        old = self.db.execute(f"SELECT * FROM {table} WHERE {key_column}=?", (key,)).fetchone()
        if old:
            if any(old[name] != value for name, value in columns.items()):
                raise LedgerError(f"Immutable {table} {key} differs from existing version")
            return
        names = ",".join(columns)
        marks = ",".join("?" for _ in columns)
        self.db.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", tuple(columns.values()))
        self.db.commit()

    def ingest_raw(self, ref: SourceRef, version: str, content: str,
                   first_seen_at: str, ingested_at: str) -> str:
        if not all(_ref_key(ref)) or not version or not first_seen_at or not ingested_at:
            raise LedgerError("Raw source needs a complete key, version and timestamps")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        old = self.db.execute("SELECT sha256 FROM raw_source WHERE system=? AND object_type=? AND native_id=? AND version=?",
                              (*_ref_key(ref), version)).fetchone()
        if old:
            if old["sha256"] != digest:
                raise LedgerError("Raw version is immutable; use a new source version")
            return digest
        self.db.execute("INSERT INTO raw_source VALUES (?,?,?,?,?,?,?,?)",
                        (*_ref_key(ref), version, digest, content, first_seen_at, ingested_at))
        self.db.commit()
        return digest

    def add_entity(self, record: Any) -> str:
        kind = type(record).__name__
        if kind not in ENTITY_TYPES:
            raise LedgerError(f"Unsupported entity {kind}")
        data = _payload(record)
        entity_id = data["id"]
        if not data["created_in_ledger_at"] or data["resolution_status"] not in {"resolved", "provisional", "ambiguous"}:
            raise LedgerError("Entity needs ledger creation time and resolution status")
        if kind == "Opportunity":
            if not all(data.get(k) for k in ("account_id", "use_case_code", "commercial_scope_id", "origin_evidence_id")):
                raise LedgerError("Opportunity requires Account × Use Case × Commercial Scope and origin evidence")
            if data["relationship"] not in {"base", "expansion", "alternative"}:
                raise LedgerError("Invalid opportunity relationship")
            if data["relationship"] == "expansion" and not data["parent_opportunity_id"]:
                raise LedgerError("Expansion requires a parent opportunity")
            if data["relationship"] == "expansion" and data["resolution_status"] != "resolved":
                raise LedgerError("Unresolved expansion must remain a scenario of the base")
            account = self.entity(data["account_id"])
            scope = self.db.execute("SELECT payload FROM entity WHERE kind='CommercialScope'").fetchall()
            matching = [json.loads(r["payload"]) for r in scope
                        if (json.loads(r["payload"])["scope_id"] == data["commercial_scope_id"] and
                            json.loads(r["payload"])["version"] == data["scope_version"])]
            if not account or not matching or matching[0]["account_id"] != data["account_id"]:
                raise LedgerError("Opportunity Account and Commercial Scope must agree")
        if kind == "CommercialScope" and (not data["account_id"] or not data["boundary_text"] or not data["scope_id"]):
            raise LedgerError("Scope needs account, scope ID and boundary")
        if kind == "OfferOrContract" and data["contract_kind"] not in {"pilot", "commercial", "amendment", "renewal"}:
            raise LedgerError("Invalid contract kind")
        if kind == "OfferOrContract" and data["status"] == "verified_signed":
            if not (data["document_ref"] and data["party_names"] and data["signature_date"] and
                    data["scope_id"] and data["term_start"] and data["term_end"]):
                raise LedgerError("Verified contract needs identified document, parties, scope, signature date and term")
        columns = {"id": entity_id, "kind": kind, "payload": _json(data),
                   "created_in_ledger_at": data["created_in_ledger_at"],
                   "resolution_status": data["resolution_status"]}
        refs = list(data.get("source_refs") or [])
        if kind == "Meeting" and data.get("source_ref"):
            refs.append(data["source_ref"])
        for r in refs:
            existing = self.db.execute("SELECT entity_id FROM source_link WHERE system=? AND object_type=? AND native_id=?",
                                       (r["system"], r["object_type"], r["native_id"])).fetchone()
            if existing and existing["entity_id"] != entity_id:
                raise LedgerError("Source native ID already maps to another canonical entity")
        self._insert_once("entity", "id", entity_id, columns)
        for r in refs:
            self.db.execute("INSERT OR IGNORE INTO source_link VALUES (?,?,?,?)",
                            (r["system"], r["object_type"], r["native_id"], entity_id))
        self.db.commit()
        return entity_id

    def entity(self, entity_id: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT payload FROM entity WHERE id=?", (entity_id,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def entity_for_source(self, ref: SourceRef) -> str | None:
        row = self.db.execute("SELECT entity_id FROM source_link WHERE system=? AND object_type=? AND native_id=?",
                              _ref_key(ref)).fetchone()
        return row["entity_id"] if row else None

    def add_evidence(self, item: Evidence) -> str:
        if item.source_ref is None or not item.source_version or not item.verbatim_excerpt or not item.ingested_at:
            raise LedgerError("Evidence requires source, version, exact excerpt and ingestion time")
        if item.start_offset is not None and (item.end_offset is None or item.start_offset >= item.end_offset):
            raise LedgerError("Invalid evidence span")
        if item.authorship not in {"customer", "seller_staff", "third_party", "ai_generated", "unknown"}:
            raise LedgerError("Invalid authorship")
        raw = self.db.execute("SELECT sha256,content FROM raw_source WHERE system=? AND object_type=? AND native_id=? AND version=?",
                              (*_ref_key(item.source_ref), item.source_version)).fetchone()
        if not raw or raw["sha256"] != item.source_hash:
            raise LedgerError("Evidence must reference an ingested immutable raw version")
        if item.start_offset is None or item.end_offset is None:
            if item.verbatim_excerpt not in raw["content"]:
                raise LedgerError("Evidence excerpt absent from raw source")
        elif raw["content"][item.start_offset:item.end_offset] != item.verbatim_excerpt:
            raise LedgerError("Evidence span differs from raw source")
        self._insert_once("evidence", "evidence_id", item.evidence_id,
                          {"evidence_id": item.evidence_id, "source_system": item.source_ref.system,
                           "source_object_type": item.source_ref.object_type,
                           "native_id": item.source_ref.native_id, "source_version": item.source_version,
                           "payload": _json(_payload(item))})
        return item.evidence_id

    def evidence(self, evidence_id: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT payload FROM evidence WHERE evidence_id=?", (evidence_id,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def _check_evidence(self, ids: tuple[str, ...]) -> None:
        if not ids or any(self.evidence(i) is None for i in ids):
            raise LedgerError("Material fact requires existing evidence")

    def add_claim(self, item: Claim) -> str:
        self._check_evidence(item.evidence_ids)
        if item.status not in {"observed", "inferred", "contradicted", "superseded", "unknown"}:
            raise LedgerError("Invalid claim status")
        self._insert_once("claim", "claim_id", item.claim_id,
                          {"claim_id": item.claim_id, "subject_id": item.subject_id,
                           "predicate": item.predicate, "contract_kind": item.contract_kind,
                           "scope_id": item.scope_id, "payload": _json(_payload(item))})
        return item.claim_id

    def add_event(self, item: Event) -> str:
        if item.event_type not in EVENT_TYPES:
            raise LedgerError("Event type outside closed taxonomy")
        if not item.account_id and not item.unresolved_entity_ref:
            raise LedgerError("Event needs account or unresolved entity reference")
        if item.event_date is None and item.date_precision != "date_unknown":
            raise LedgerError("Unknown event date must be explicit")
        if not item.first_seen_at or not item.extraction_version:
            raise LedgerError("Event needs first-seen time and extraction version")
        self._check_evidence(item.evidence_ids)
        if item.assertion not in {"explicit", "inferred"}:
            raise LedgerError("Invalid event assertion")
        if item.event_type == "commercial_signed" and item.contract_kind != "commercial":
            raise LedgerError("Commercial signature requires commercial contract kind")
        if item.event_type == "pilot_signed" and item.contract_kind != "pilot":
            raise LedgerError("Pilot signature requires pilot contract kind")
        required = {
            "data_requested": ("data_kind", "requester"),
            "data_received": ("data_kind", "delivery_or_access"),
            "pilot_verbal_yes": ("pilot_scope",),
            "sow_sent": ("recipient", "sent_at"),
            "pilot_signed": ("pilot_contract_id",),
            "pilot_started": ("start_date",),
            "technical_milestone": ("milestone_kind", "result"),
            "blocker_opened": ("blocker_kind",),
            "blocker_resolved": ("blocker_id", "resolution_evidence_id"),
            "procurement_legal_started": ("domain",),
            "commercial_proposal_sent": ("offer_id",),
            "commercial_signed": ("commercial_contract_id",),
            "revived": ("trigger_event_id",),
        }.get(item.event_type, ())
        if any(not item.details.get(field) for field in required):
            raise LedgerError(f"{item.event_type} lacks required event details")
        self._insert_once("event", "event_id", item.event_id,
                          {"event_id": item.event_id, "event_type": item.event_type,
                           "account_id": item.account_id, "opportunity_id": item.opportunity_id,
                           "event_date": item.event_date, "payload": _json(_payload(item))})
        return item.event_id

    def add_value(self, item: CommercialValue) -> str:
        if item.value_type not in VALUE_TYPES or item.status not in {"tentative", "proposed", "signed_reported", "signed_verified", "retracted"}:
            raise LedgerError("Invalid value type/status")
        if item.amount_decimal is None or not item.currency_ISO or not item.opportunity_id or not item.scope_id:
            raise LedgerError("Value requires amount, currency, opportunity and scope")
        self._check_evidence(item.source_evidence_ids)
        if item.status == "signed_verified" and (item.verification != "document_verified" or not item.offer_or_contract_id):
            raise LedgerError("Signed verified value requires verified contractual evidence")
        if item.status == "signed_verified":
            contract = self.entity(item.offer_or_contract_id)
            if not contract or contract["status"] != "verified_signed" or contract["scope_id"] != item.scope_id:
                raise LedgerError("Signed verified value requires a verified contract for the same scope")
            evidence = [self.evidence(i) for i in item.source_evidence_ids]
            if not any(e["assertion_type"] == "document" and e["authorship"] != "ai_generated"
                       for e in evidence):
                raise LedgerError("Signed verified value requires documentary evidence")
        if item.replaces_value_id:
            old = self.db.execute("SELECT payload FROM commercial_value WHERE value_id=?", (item.replaces_value_id,)).fetchone()
            if not old:
                raise LedgerError("Replacement value does not exist")
            prior = json.loads(old["payload"])
            if prior["opportunity_id"] != item.opportunity_id or prior["scope_id"] != item.scope_id:
                raise LedgerError("Replacement must belong to same opportunity and scope")
        self._insert_once("commercial_value", "value_id", item.value_id,
                          {"value_id": item.value_id, "opportunity_id": item.opportunity_id,
                           "scope_id": item.scope_id, "replaces_value_id": item.replaces_value_id,
                           "payload": _json(_payload(item))})
        return item.value_id

    def add_alias(self, item: Alias) -> str:
        if item.decision not in {"confirmed", "candidate", "rejected", "ambiguous"}:
            raise LedgerError("Invalid alias decision")
        if item.decision == "confirmed" and not item.canonical_id:
            raise LedgerError("Confirmed alias requires canonical ID")
        self._insert_once("alias_decision", "alias_id", item.alias_id,
                          {"alias_id": item.alias_id, "normalized_string": item.normalized_string,
                           "entity_type": item.entity_type, "canonical_id": item.canonical_id,
                           "decision": item.decision, "decision_at": item.decision_at,
                           "payload": _json(_payload(item))})
        return item.alias_id

    def resolve_identity(self, *, entity_type: str, raw_string: str,
                         source_ref: SourceRef | None = None, account_id: str | None = None,
                         at: str | None = None) -> tuple[str, str | None]:
        """Native ID wins. Exact contact email may match only within confirmed account.

        Name and initials never auto-confirm. Returns (decision, canonical_id).
        """
        if source_ref:
            found = self.entity_for_source(source_ref)
            if found:
                return "confirmed", found
        normalized = raw_string.strip().casefold()
        rows = self.db.execute("SELECT payload FROM alias_decision WHERE entity_type=? AND normalized_string=?",
                               (entity_type, normalized)).fetchall()
        eligible = []
        for row in rows:
            alias = json.loads(row["payload"])
            if at and ((alias["valid_from"] and at < alias["valid_from"]) or
                       (alias["valid_to"] and at > alias["valid_to"])):
                continue
            eligible.append(alias)
        confirmed = [a for a in eligible if a["decision"] == "confirmed"]
        ids = {a["canonical_id"] for a in confirmed}
        if entity_type == "Contact" and "@" in normalized:
            ids = {i for i in ids if account_id and account_id in
                   {x["account_id"] for x in (self.entity(i) or {}).get("account_affiliations", [])}}
        if len(ids) == 1:
            return "confirmed", next(iter(ids))
        if len(ids) > 1 or len(eligible) > 1:
            return "ambiguous", None
        return ("candidate", None) if eligible else ("ambiguous", None)

    def add_identity_relation(self, left_id: str, right_id: str, relation: str,
                              evidence_id: str | None = None) -> None:
        if relation not in {"possible_same_entity", "confirmed_same_entity", "distinct_entity"}:
            raise LedgerError("Invalid identity relation")
        if evidence_id and not self.evidence(evidence_id):
            raise LedgerError("Missing identity evidence")
        self.db.execute("INSERT OR IGNORE INTO identity_relation VALUES (?,?,?,?)",
                        (left_id, right_id, relation, evidence_id))
        self.db.commit()

    def add_conflict(self, item: Conflict) -> str:
        if len(item.claim_ids) < 2:
            raise LedgerError("Conflict needs at least two claims")
        for claim_id in item.claim_ids:
            if not self.db.execute("SELECT 1 FROM claim WHERE claim_id=?", (claim_id,)).fetchone():
                raise LedgerError("Conflict references missing claim")
        self._insert_once("conflict", "conflict_id", item.conflict_id,
                          {"conflict_id": item.conflict_id, "payload": _json(_payload(item))})
        return item.conflict_id

    def detect_claim_conflicts(self) -> list[tuple[str, str]]:
        """Find simultaneous opposite assertions for same subject/scope/contract.

        Different dated states are deliberately retained without declaring a conflict.
        """
        rows = [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM claim")]
        found = []
        for n, left in enumerate(rows):
            for right in rows[n + 1:]:
                fields = ("subject_id", "predicate", "scope_id", "contract_kind")
                if all(left[f] == right[f] for f in fields) and left["polarity"] != right["polarity"]:
                    l_from, l_to = left["valid_from"] or "0000", left["valid_to"] or "9999"
                    r_from, r_to = right["valid_from"] or "0000", right["valid_to"] or "9999"
                    if max(l_from, r_from) <= min(l_to, r_to):
                        found.append((left["claim_id"], right["claim_id"]))
        return found

    def events_as_of(self, week_end: str, *, mode: str,
                     knowledge_cutoff: str | None = None) -> list[dict[str, Any]]:
        """Return evidence-eligible events; no state synthesis or future leakage."""
        if mode not in {"retrospective_event_state", "historically_known_state"}:
            raise LedgerError("Unknown temporal mode")
        cutoff = knowledge_cutoff or week_end
        out = []
        for row in self.db.execute("SELECT payload FROM event WHERE event_date IS NOT NULL ORDER BY event_date,event_id"):
            event = json.loads(row["payload"])
            if not _known_by(event["event_date"], week_end):
                continue
            if mode == "historically_known_state":
                evidence = [self.evidence(i) for i in event["evidence_ids"]]
                if not any(e and e["documented_at"] and _known_by(e["documented_at"], cutoff) and
                           e["source_first_seen_at"] and _known_by(e["source_first_seen_at"], cutoff)
                           for e in evidence):
                    continue
            out.append(event)
        return out

    def add_signal(self, signal: dict[str, Any]) -> str:
        """Persist one atomic signal (belief layer). Signals never carry verification."""
        from src.belief.signals import validate_signal
        validate_signal(signal)
        self._check_evidence(tuple(signal["evidence_ids"]))
        if signal.get("opportunity_id") and not self.entity(signal["opportunity_id"]):
            raise LedgerError("Signal references a missing opportunity")
        self._insert_once("atomic_signal", "signal_id", signal["signal_id"],
                          {"signal_id": signal["signal_id"], "signal_type": signal["signal_type"],
                           "opportunity_id": signal.get("opportunity_id"),
                           "effective_date": signal.get("effective_date"), "payload": _json(signal)})
        return signal["signal_id"]

    def signals(self) -> list[dict[str, Any]]:
        return [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM atomic_signal ORDER BY signal_id")]

    def values_for_opportunity(self, opportunity_id: str) -> list[dict[str, Any]]:
        return [json.loads(r[0]) for r in self.db.execute(
            "SELECT payload FROM commercial_value WHERE opportunity_id=? ORDER BY rowid", (opportunity_id,))]

    def count(self, table: str) -> int:
        if table not in {"raw_source", "entity", "evidence", "claim", "event", "commercial_value", "alias_decision",
                         "conflict", "atomic_signal"}:
            raise LedgerError("Unknown table")
        return self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
