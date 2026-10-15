"""Notion workspace export (Markdown & CSV zip) -> API-shaped page snapshots.

Used when the Notion API integration has no shared pages. The zip is read in
memory (never extracted or executed). Each meeting note becomes a page object
with the same property and block shape the API returns, so extraction runs
unchanged. Provenance records the export file and its SHA-256; no business
inference happens here.
"""
from __future__ import annotations

import csv
from datetime import datetime
import hashlib
import io
from pathlib import PurePosixPath
import re
import zipfile

ID = re.compile(r"\s([0-9a-f]{32})\.(md|csv)$")
PROPERTY = re.compile(r"^([A-Za-z][A-Za-z ]{0,40}):\s(.*)$")
MAX_BYTES = 50 * 1024 * 1024


def dashed(hex32: str) -> str:
    h = hex32.lower()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def _date(value: str) -> str | None:
    for fmt in ("%B %d, %Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _rich(text: str) -> list[dict]:
    return [{"type": "text", "plain_text": text, "text": {"content": text}, "annotations": {}}]


def parse_page(markdown: str, page_id: str, parent_id: str | None) -> dict:
    """Title, property lines (until the first heading) and blocks, with exact source strings."""
    lines = markdown.replace("\r\n", "\n").split("\n")
    title = lines[0][2:].strip() if lines and lines[0].startswith("# ") else ""
    props: dict[str, dict] = {"Name": {"id": "title", "type": "title", "title": _rich(title)}}
    creator = None
    i = 1
    while i < len(lines) and not lines[i].startswith("#"):
        m = PROPERTY.match(lines[i].strip())
        if m:
            key, value = m.group(1), m.group(2).strip()
            if key == "Date":
                start = _date(value)
                props["Date"] = {"id": "date", "type": "date", "date": {"start": start} if start else None}
            elif key == "Attendees":
                props["Attendees"] = {"id": "attendees", "type": "multi_select",
                                      "multi_select": [{"name": n.strip()} for n in value.split(",") if n.strip()]}
            elif key == "Meeting type":
                props["Meeting type"] = {"id": "meeting_type", "type": "select", "select": {"name": value}}
            elif key == "Created by":
                creator = value
                props["Created by"] = {"id": "created_by", "type": "created_by", "created_by": {"name": value}}
            elif key == "Last edited by":
                props["Last edited by"] = {"id": "last_edited_by", "type": "last_edited_by",
                                           "last_edited_by": {"name": value}}
        i += 1
    blocks = []
    for n, raw in enumerate(lines[i:]):
        text = raw.strip()
        if not text:
            continue
        if text.startswith("#"):
            kind, body = "heading_" + str(min(3, len(text) - len(text.lstrip("#")))), text.lstrip("#").strip()
        elif text.startswith(("- ", "* ")):
            kind, body = "bulleted_list_item", text[2:].strip()
        else:
            kind, body = "paragraph", text
        block_id = f"{page_id}-l{i + n:04d}"
        blocks.append({"block": {"object": "block", "id": block_id, "type": kind, "has_children": False,
                                 kind: {"rich_text": _rich(body)}}, "children": []})
    page = {"object": "page", "id": page_id, "created_by": {"name": creator} if creator else {},
            "parent": {"type": "database_id", "database_id": parent_id} if parent_id else {"type": "workspace"},
            "properties": props}
    return {"page": page, "blocks": blocks}


def load_export(path: str) -> tuple[list[dict], dict]:
    """Return API-shaped objects for every page and the meeting-notes collection, plus a report."""
    raw = open(path, "rb").read()
    if len(raw) > MAX_BYTES:
        raise ValueError("Notion export is unexpectedly large")
    digest = hashlib.sha256(raw).hexdigest()
    archive = zipfile.ZipFile(io.BytesIO(raw))
    names = [n for n in archive.namelist() if not n.endswith("/")]
    if any(n.startswith("/") or ".." in PurePosixPath(n).parts for n in names):
        raise ValueError("Unsafe path in Notion export")
    collections = [n for n in names if n.endswith(".csv") and not n.endswith("_all.csv") and ID.search(n)]
    if len(collections) != 1:
        raise ValueError("Expected exactly one exported database (meeting notes)")
    collection = collections[0]
    db_hex = ID.search(collection).group(1)
    db_id = dashed(db_hex)
    folder = collection[:ID.search(collection).start()]
    rows = list(csv.DictReader(io.StringIO(archive.read(collection).decode("utf-8-sig"))))
    objects = []
    note_count = dated = typed = 0
    for name in sorted(names):
        m = ID.search(name)
        if not m or m.group(2) != "md":
            continue
        page_id = dashed(m.group(1))
        in_db = name.startswith(folder + "/")
        content = parse_page(archive.read(name).decode("utf-8-sig"), page_id, db_id if in_db else None)
        content["export_source"] = {"file": name, "export_sha256": digest}
        objects.append({"native_object_type": "page", "native_id": page_id, "content": content,
                        "schema_ref": f"notion/data_source/{db_id}" if in_db else None})
        if in_db:
            note_count += 1
            props = content["page"]["properties"]
            dated += bool((props.get("Date") or {}).get("date"))
            typed += "Meeting type" in props
    schema = {"object": "data_source", "id": db_id, "title": _rich(PurePosixPath(folder).name),
              "properties": {k: {"name": k} for k in (rows[0].keys() if rows else [])},
              "export_source": {"file": collection, "export_sha256": digest, "row_count": len(rows)}}
    objects.append({"native_object_type": "data_source", "native_id": db_id, "content": {"object": schema},
                    "schema_ref": f"notion/data_source/{db_id}"})
    if note_count != len(rows):
        raise ValueError(f"Export inconsistent: {note_count} note pages vs {len(rows)} database rows")
    report = {"acquisition": "notion_export_zip", "export_sha256": digest, "page_count": note_count,
              "record_count": note_count, "structured_date_count": dated, "meeting_type_count": typed,
              "other_pages": len(objects) - note_count - 1, "complete_pagination": True,
              "selected": {"id": db_id, "kind": "data_source", "record_count": note_count,
                           "structured_date_count": dated, "meeting_type_count": typed}}
    return objects, report
