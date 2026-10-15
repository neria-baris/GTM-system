"""Local CRM export (Airtable base shape) served through the read-only client interface.

Used instead of the Airtable API when the CRM is supplied as a JSON file. The file is
read once and never executed. Discovery and ingestion run unchanged on top of it, so a
local export and a live base produce the same snapshots and envelopes.

Format `airtable-base-export/1`:
    {"format": ..., "base": {"id", "name"}, "tables": [<Airtable meta table>...],
     "records": {<table id>: [<Airtable record with fields keyed by field id>...]}}
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

FORMAT = "airtable-base-export/1"
PAGE_SIZE = 100
MAX_BYTES = 50 * 1024 * 1024


class ExportClient:
    provider = "airtable"

    def __init__(self, path: str | Path):
        raw = Path(path).read_bytes()
        if len(raw) > MAX_BYTES:
            raise ValueError("CRM export is unexpectedly large")
        self.sha256 = hashlib.sha256(raw).hexdigest()
        self.file = Path(path).name
        data = json.loads(raw.decode("utf-8"))
        if data.get("format") != FORMAT:
            raise ValueError(f"CRM export format must be {FORMAT}")
        base = data["base"]
        if not isinstance(data.get("tables"), list) or not isinstance(data.get("records"), dict):
            raise ValueError("CRM export needs tables and records")
        table_ids = {t["id"] for t in data["tables"]}
        if set(data["records"]) - table_ids:
            raise ValueError("CRM export has records for an unknown table")
        self.base = {"id": base["id"], "name": base.get("name"), "permissionLevel": base.get("permissionLevel", "read")}
        self.tables = data["tables"]
        self.records = {tid: list(data["records"].get(tid, [])) for tid in table_ids}

    def request(self, method: str, path: str, *, params=None, body=None) -> dict:
        if method != "GET":
            raise ValueError("read-only API methods only")
        params = params or {}
        if path == "/meta/bases":
            return {"bases": [self.base]}
        if path == f"/meta/bases/{self.base['id']}/tables":
            return {"tables": json.loads(json.dumps(self.tables))}
        match = re.fullmatch(rf"/{re.escape(self.base['id'])}/([^/]+)", path)
        if not match or match.group(1) not in self.records:
            raise ValueError("Unknown CRM export path")
        rows = self.records[match.group(1)]
        start = int(params.get("offset") or 0)
        size = int(params.get("pageSize") or PAGE_SIZE)
        page = {"records": json.loads(json.dumps(rows[start:start + size]))}
        if start + size < len(rows):
            page["offset"] = str(start + size)
        return page
