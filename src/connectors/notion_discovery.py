"""Discover accessible Notion GTM collections without presuming a database."""
from __future__ import annotations

from src.settings import source_baseline

from .common import DiscoveryError, ReadClient, notion_pages, parent_ids

# Optional corpus hints from config source_baseline: expected note count, known page IDs, target page.
_BASELINE = source_baseline() or {}
EXPECTED_NOTES = _BASELINE.get("notion_meeting_notes")
SAMPLE_PAGE_IDS = {str(i).replace("-", "").lower() for i in _BASELINE.get("notion_sample_page_ids") or []}
TARGET_PAGE_ID = str(_BASELINE.get("notion_target_page_id") or "").replace("-", "").lower() or None


def title_of(obj: dict) -> str:
    title = obj.get("title")
    if isinstance(title, list):
        return "".join(part.get("plain_text", "") for part in title)
    for value in (obj.get("properties") or {}).values():
        if value.get("type") == "title" or "title" in value:
            return "".join(part.get("plain_text", "") for part in value.get("title", []))
    return ""


def safe_object(obj: dict) -> dict:
    props = obj.get("properties") or {}
    return {"id": obj.get("id"), "object": obj.get("object"), "title": title_of(obj),
            "parent_native_ids": parent_ids(obj), "url": obj.get("url"),
            "properties": [{"id": p.get("id"), "name": name, "type": p.get("type")}
                           for name, p in props.items()]}


def query_data_source(api: ReadClient, data_source_id: str) -> list[dict]:
    rows = []
    for page in notion_pages(api, "POST", f"/data_sources/{data_source_id}/query", body={"page_size": 100}):
        rows.extend(page["results"])
    return rows


def discover_notion(api: ReadClient, hints: dict | None = None) -> dict:
    hints = {k: v for k, v in (hints or {}).items() if v}
    objects = []
    for page in notion_pages(api, "POST", "/search", body={"page_size": 100}):
        objects.extend(page["results"])
    by_id = {o.get("id"): o for o in objects}
    for key, kind, path in (("root_page_id", "page", "/pages/"),
                            ("database_id", "database", "/databases/"),
                            ("data_source_id", "data_source", "/data_sources/")):
        if hints.get(key):
            obj = api.request("GET", path + hints[key])
            if obj.get("object") != kind or obj.get("id") != hints[key]:
                raise DiscoveryError(f"Notion {key} is not an accessible {kind}")
            by_id[obj["id"]] = obj
    objects = list(by_id.values())
    datasources = [o for o in objects if o.get("object") == "data_source"]
    # A database can expose data sources not individually returned by search.
    for db in [o for o in objects if o.get("object") == "database"]:
        for item in db.get("data_sources", []):
            sid = item.get("id")
            if sid and sid not in by_id:
                source = api.request("GET", f"/data_sources/{sid}")
                by_id[sid] = source
                datasources.append(source)
    # Search exposes pages/data sources, but a data source's database may not
    # itself appear there. Retrieve the parent chain for scope-hint validation.
    for source in datasources:
        for database_id in parent_ids(source):
            if database_id not in by_id:
                database = api.request("GET", f"/databases/{database_id}")
                if database.get("object") == "database":
                    by_id[database_id] = database
    objects = list(by_id.values())
    candidates = []
    for source in datasources:
        names = {name.casefold() for name in (source.get("properties") or {})}
        title = title_of(source).casefold()
        evidence = []
        if "meeting" in title and ("note" in title or "minutes" in title):
            evidence.append("meeting-note title")
        if "date" in names and ("meeting type" in names or "attendees" in names):
            evidence.append("meeting-note property schema")
        if not evidence and source.get("id") != hints.get("data_source_id"):
            continue
        rows = query_data_source(api, source["id"])
        count_date = sum(bool((p.get("properties") or {}).get("Date", {}).get("date")) for p in rows)
        count_type = sum(bool((p.get("properties") or {}).get("Meeting type", {}).get("select")) for p in rows)
        if EXPECTED_NOTES and len(rows) and abs(len(rows) - EXPECTED_NOTES) <= 15:
            evidence.append(f"record count near expected {EXPECTED_NOTES}")
        overlap = len({str(row.get("id", "")).replace("-", "").lower() for row in rows}
                      & SAMPLE_PAGE_IDS)
        if overlap:
            evidence.append(f"{overlap} known sample page IDs present")
        candidates.append({"id": source["id"], "title": title_of(source),
                           "kind": "data_source",
                           "database_id": next((i for i in parent_ids(source) if i), None),
                           "record_count": len(rows), "structured_date_count": count_date,
                           "meeting_type_count": count_type, "sample_overlap": overlap,
                           "evidence": evidence, "rows": rows})
    if not candidates:
        from .notion_ingest import block_tree
        for root in [o for o in objects if o.get("object") == "page" and
                     "meeting" in title_of(o).casefold() and "note" in title_of(o).casefold()]:
            tree = block_tree(api, root["id"])
            page_ids = []
            def visit(items):
                for entry in items:
                    block = entry["block"]
                    if block.get("type") == "child_page":
                        page_ids.append(block["id"])
                    visit(entry["children"])
            visit(tree)
            if page_ids:
                rows = [api.request("GET", f"/pages/{pid}") for pid in page_ids]
                candidates.append({"id": root["id"], "title": title_of(root),
                                   "kind": "page_tree", "database_id": None,
                                   "record_count": len(rows),
                                   "structured_date_count": sum(bool((p.get("properties") or {}).get("Date", {}).get("date")) for p in rows),
                                   "meeting_type_count": sum(bool((p.get("properties") or {}).get("Meeting type", {}).get("select")) for p in rows),
                                   "sample_overlap": len({str(p["id"]).replace("-", "").lower() for p in rows} & SAMPLE_PAGE_IDS),
                                   "evidence": ["meeting-note page-tree title", "child pages traversed"],
                                   "rows": rows})
    # A root hint is a narrowing constraint over the discovered parent graph.
    def descendant(candidate: dict, ancestor: str) -> bool:
        current = candidate["id"]
        seen = set()
        while current and current not in seen:
            if current == ancestor:
                return True
            seen.add(current)
            current = next(iter(parent_ids(by_id.get(current, {}))), None)
        return False
    if hints.get("database_id"):
        candidates = [c for c in candidates if c["database_id"] == hints["database_id"]]
    if hints.get("data_source_id"):
        candidates = [c for c in candidates if c["id"] == hints["data_source_id"]]
    if hints.get("root_page_id"):
        candidates = [c for c in candidates if descendant(c, hints["root_page_id"])]
    if hints and not candidates:
        raise DiscoveryError("Notion scope hint contains no accessible meeting-note corpus")
    plausible = [c for c in candidates if c["record_count"] and
                 ("meeting-note property schema" in c["evidence"] or
                  "meeting-note title" in c["evidence"] or
                  "meeting-note page-tree title" in c["evidence"])]
    if len(plausible) == 1:
        chosen = plausible[0]
    elif plausible:
        ranked = sorted(plausible, key=lambda c: (c["sample_overlap"],
                                                   -abs(c["record_count"] - (EXPECTED_NOTES or c["record_count"]))), reverse=True)
        chosen = (ranked[0] if ranked[0]["sample_overlap"] >= 2 and
                  ranked[0]["sample_overlap"] > ranked[1]["sample_overlap"] else None)
    else:
        chosen = None
    supplemental = []
    selected_root_page_id = None
    if chosen:
        database = by_id.get(chosen.get("database_id")) or {}
        selected_root_page_id = next(iter(parent_ids(database)), None)
        # A configured target page is an evidence lead, not a scope ID.
        # Include it only when current discovery independently exposes it.
        supplemental = [safe_object(o) for o in objects if TARGET_PAGE_ID and o.get("object") == "page" and
                        str(o.get("id", "")).replace("-", "").lower() == TARGET_PAGE_ID]
    return {"accessible_object_count": len(objects),
            "accessible_objects": [safe_object(o) for o in objects],
            "candidates": [{k: v for k, v in c.items() if k != "rows"} for c in candidates],
            "selected": {k: v for k, v in chosen.items() if k != "rows"} if chosen else None,
            "selected_rows": chosen["rows"] if chosen else [],
            "supplemental_pages": supplemental,
            "selected_root_page_id": selected_root_page_id,
            "abstained": chosen is None,
            "hints_used": hints,
            "reason": "supported meeting-note data source by schema and baseline overlap" if chosen else "zero or multiple materially plausible corpora"}
