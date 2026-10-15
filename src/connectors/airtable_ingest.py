"""Complete Airtable record ingestion with schema kept separately."""
from __future__ import annotations

from .common import ReadClient, airtable_pages


def ingest_airtable(api: ReadClient, discovery: dict) -> tuple[list[dict], dict]:
    if discovery["abstained"]:
        raise ValueError("Airtable discovery abstained")
    base = discovery["selected"]
    objects = []
    counts = {}
    for table in base["tables"]:
        records = []
        for page in airtable_pages(api, f"/{base['id']}/{table['id']}",
                                   params={"pageSize": 100, "returnFieldsByFieldId": "true"},
                                   key="records"):
            records.extend(page["records"])
        counts[table["id"]] = len(records)
        for record in records:
            objects.append({"native_object_type": "record", "native_id": record["id"],
                            "content": {"record": record, "base_id": base["id"],
                                        "table_id": table["id"]},
                            "schema_ref": f"airtable/{base['id']}/{table['id']}"})
    return objects, {"record_count": len(objects), "counts_by_table_id": counts,
                     "complete_pagination": True}
