"""Lossless Notion page and recursive block acquisition."""
from __future__ import annotations

from .common import ReadClient, notion_pages


def block_tree(api: ReadClient, block_id: str) -> list[dict]:
    blocks = []
    for page in notion_pages(api, "GET", f"/blocks/{block_id}/children", params={"page_size": 100}):
        for block in page["results"]:
            item = {"block": block, "children": block_tree(api, block["id"]) if block.get("has_children") else []}
            blocks.append(item)
    return blocks


def ingest_notion(api: ReadClient, discovery: dict) -> tuple[list[dict], dict]:
    if discovery["abstained"]:
        raise ValueError("Notion discovery abstained")
    source = discovery["selected"]
    objects = []
    # Refresh pages so properties are preserved independently of query result shape.
    for row in discovery["selected_rows"]:
        page = api.request("GET", f"/pages/{row['id']}")
        objects.append({"native_object_type": "page", "native_id": row["id"],
                        "content": {"page": page, "blocks": block_tree(api, row["id"]),
                                    "query_row": row}, "schema_ref": f"notion/data_source/{source['id']}" if source["kind"] == "data_source" else None})
    # Preserve selected collection and enclosing database as provider objects.
    if source["kind"] == "data_source":
        ds = api.request("GET", f"/data_sources/{source['id']}")
        objects.append({"native_object_type": "data_source", "native_id": source["id"],
                        "content": {"object": ds}, "schema_ref": f"notion/data_source/{source['id']}"})
    else:
        root_page = api.request("GET", f"/pages/{source['id']}")
        objects.append({"native_object_type": "page", "native_id": source["id"],
                        "content": {"page": root_page, "blocks": block_tree(api, source["id"])},
                        "schema_ref": None})
    if source.get("database_id"):
        db = api.request("GET", f"/databases/{source['database_id']}")
        objects.append({"native_object_type": "database", "native_id": db["id"],
                        "content": {"object": db}, "schema_ref": None})
    # If root scope is explicit, recursively preserve its page tree and other blocks.
    root = discovery.get("hints_used", {}).get("root_page_id") or discovery.get("selected_root_page_id")
    if root and root != source["id"]:
        root_page = api.request("GET", f"/pages/{root}")
        objects.append({"native_object_type": "page", "native_id": root,
                        "content": {"page": root_page, "blocks": block_tree(api, root)},
                        "schema_ref": None})
    present = {o["native_id"] for o in objects}
    for supplemental in discovery.get("supplemental_pages", []):
        pid = supplemental["id"]
        if pid not in present:
            page = api.request("GET", f"/pages/{pid}")
            objects.append({"native_object_type": "page", "native_id": pid,
                            "content": {"page": page, "blocks": block_tree(api, pid)},
                            "schema_ref": None})
            present.add(pid)
    return objects, {"page_count": len(discovery["selected_rows"]), "complete_pagination": True}
