"""Offline raw-export ingestion. Live read-only discovery belongs to Stage A2."""
from __future__ import annotations

import json
from pathlib import Path

from .models import SourceRef
from .store import Ledger, LedgerError


def ingest_jsonl_export(ledger: Ledger, path: str | Path) -> int:
    """Ingest rows with source_ref, version, content and observed timestamps.

    This preserves bytes represented by each JSON content string as a new immutable
    source version; it deliberately does not derive customers, events or contracts.
    """
    count = 0
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                ref = SourceRef(**row["source_ref"])
                if not isinstance(row["content"], str):
                    raise TypeError("content must be a string")
                ledger.ingest_raw(ref, row["version"], row["content"],
                                  row["first_seen_at"], row["ingested_at"])
            except (KeyError, TypeError, ValueError) as exc:
                raise LedgerError(f"Invalid export row {line_number}: {exc}") from exc
            count += 1
    return count
