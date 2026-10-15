"""Read-only Airtable base and schema discovery."""
from __future__ import annotations

from src.settings import source_baseline

from .common import DiscoveryError, ReadClient, airtable_pages


# Optional expected record counts per table role (config source_baseline.airtable).
BASELINE_COUNTS = (source_baseline() or {}).get("airtable") or {}
ALIASES = {"companies": {"companies", "accounts"},
           "contacts": {"contacts", "people"},
           "deals": {"deals", "opportunities"},
           "activities": {"activities", "meetings"}}


def list_bases(api: ReadClient) -> list[dict]:
    bases = []
    for page in airtable_pages(api, "/meta/bases", key="bases"):
        bases.extend(page["bases"])
    return bases


def schema_summary(schema: dict) -> list[dict]:
    return [{"id": t.get("id"), "name": t.get("name"),
             "fields": [{"id": f.get("id"), "name": f.get("name"), "type": f.get("type"),
                         "linked_table_id": (f.get("options") or {}).get("linkedTableId")}
                        for f in t.get("fields", [])],
             "views": [{"id": v.get("id"), "name": v.get("name"), "type": v.get("type")}
                       for v in t.get("views", [])]}
            for t in schema.get("tables", [])]


def discover_airtable(api: ReadClient, base_hint: str | None = None) -> dict:
    bases = list_bases(api)
    if base_hint and base_hint not in {b.get("id") for b in bases}:
        raise DiscoveryError("AIRTABLE_BASE_ID is not accessible to this token")
    inspected = []
    for base in bases:
        if base_hint and base["id"] != base_hint:
            continue
        schema = api.request("GET", f"/meta/bases/{base['id']}/tables")
        if not isinstance(schema.get("tables"), list):
            raise DiscoveryError("Airtable base schema is incomplete")
        summary = schema_summary(schema)
        matched = {kind: next((t for t in summary if t["name"].casefold() in names), None)
                   for kind, names in ALIASES.items()}
        evidence = [f"{kind} table schema" for kind, table in matched.items() if table]
        inspected.append({"id": base["id"], "name": base.get("name"),
                          "permission_level": base.get("permissionLevel"),
                          "tables": summary, "evidence": evidence, "schema": schema,
                          "role_table_ids": {k: v["id"] for k, v in matched.items() if v}})
    # A sole accessible base can be selected after schema inspection. Multiple bases
    # need independent evidence; names alone never choose between plausible bases.
    plausible = [b for b in inspected if len(b["evidence"]) >= 2]
    if base_hint:
        selected = inspected[0]
        reason = "validated AIRTABLE_BASE_ID scope hint"
    elif len(inspected) == 1:
        selected = inspected[0]
        reason = "sole accessible base after schema inspection"
    elif plausible:
        # Full count probes avoid assuming that matching table names identify the
        # expected corpus. Retain all candidate summaries if counts remain close.
        for candidate in plausible:
            counts = {}
            for role, table_id in candidate["role_table_ids"].items():
                total = 0
                for page in airtable_pages(api, f"/{candidate['id']}/{table_id}",
                                           params={"pageSize": 100}, key="records"):
                    total += len(page["records"])
                counts[role] = total
            candidate["record_counts"] = counts
            candidate["baseline_distance"] = sum(abs(counts.get(role, 0) - count)
                                               for role, count in BASELINE_COUNTS.items())
        ranked = sorted(plausible, key=lambda b: b["baseline_distance"])
        if (len(ranked[0]["role_table_ids"]) >= 3 and ranked[0]["baseline_distance"] <= 15
                and (len(ranked) == 1 or ranked[1]["baseline_distance"] >= ranked[0]["baseline_distance"] + 30)):
            selected = ranked[0]
            reason = "schema roles and record counts reconcile uniquely with the source baseline"
        else:
            selected = None
            reason = "multiple materially plausible GTM bases; set AIRTABLE_BASE_ID"
    else:
        selected = None
        reason = "multiple or zero plausible GTM bases; set AIRTABLE_BASE_ID"
    def safe(base: dict) -> dict:
        return {k: v for k, v in base.items() if k != "schema"}
    return {"accessible_bases": [{"id": b.get("id"), "name": b.get("name"),
                                   "permission_level": b.get("permissionLevel")} for b in bases],
            "candidate_bases": [safe(b) for b in inspected],
            "selected": safe(selected) if selected else None,
            "selected_schema": selected["schema"] if selected else None,
            "base_hint_supplied": bool(base_hint), "abstained": selected is None,
            "reason": reason}
