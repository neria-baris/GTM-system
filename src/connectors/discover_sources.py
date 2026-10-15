"""CLI: python -m src.connectors.discover_sources notion|airtable."""
from __future__ import annotations

import argparse
import json
import os
import sys

from .common import ReadClient, safe_error
from .notion_discovery import discover_notion
from .airtable_discovery import discover_airtable


def notion_hints() -> dict:
    return {"root_page_id": os.getenv("NOTION_ROOT_PAGE_ID"),
            "database_id": os.getenv("NOTION_DATABASE_ID"),
            "data_source_id": os.getenv("NOTION_DATA_SOURCE_ID")}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("provider", choices=("notion", "airtable"))
    args = parser.parse_args()
    key = os.getenv("NOTION_API_KEY" if args.provider == "notion" else "AIRTABLE_TOKEN")
    if not key:
        print(json.dumps({"status": "error", "error": "required provider token missing"}))
        return 2
    try:
        api = ReadClient(args.provider, key)
        if args.provider == "notion":
            report = discover_notion(api, notion_hints())
            report.pop("selected_rows", None)
            report["notion_api_version"] = "2026-03-11"
        else:
            report = discover_airtable(api, os.getenv("AIRTABLE_BASE_ID"))
            report.pop("selected_schema", None)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 3 if report["abstained"] else 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": safe_error(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
