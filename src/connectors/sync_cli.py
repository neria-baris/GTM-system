"""Full read-only source ingestion and immutable run manifest."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path

from src.settings import source_baseline

from .airtable_discovery import discover_airtable
from .airtable_export import ExportClient
from .airtable_ingest import ingest_airtable
from .common import (EvidenceSourceEnvelope, ReadClient, content_hash, diff_manifest,
                     new_run_id, parent_ids, safe_error, stable_provider_content, utc_now, write_json)
from .discover_sources import notion_hints
from .notion_discovery import discover_notion, title_of
from .notion_ingest import ingest_notion
from .notion_export_ingest import load_export


def _previous_manifest(output_dir: Path) -> list[dict] | None:
    path = output_dir / "source_manifest.json"
    if not path.exists():
        return None
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
        if not previous.get("complete"):
            return None
        envelopes = previous.get("envelopes") or []
        if previous.get("hash_version") != "provider-stable-v2":
            for envelope in envelopes:
                if envelope.get("provider") == "notion":
                    raw = Path(envelope["raw_snapshot_path"])
                    if raw.exists():
                        value = json.loads(raw.read_text(encoding="utf-8"))["content"]
                        envelope["content_hash"] = content_hash(stable_provider_content("notion", value))
        return envelopes
    except (ValueError, OSError):
        return None


def _write_output(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _envelope(provider: str, item: dict, raw_path: Path, retrieved: str) -> EvidenceSourceEnvelope:
    content = item["content"]
    native = content.get("page") or content.get("object") or content.get("record") or {}
    if provider == "notion":
        parents = parent_ids(native)
        title = title_of(native) or None
    else:
        parents = [content["base_id"], content["table_id"]]
        title = None
    return EvidenceSourceEnvelope(provider, item["native_object_type"], item["native_id"],
                                  parents, title, retrieved, content_hash(stable_provider_content(provider, content)),
                                  raw_path.as_posix(), True, item.get("schema_ref"))


def run(output_dir: Path, raw_root: Path, require_live: bool = False, notion_export: Path | None = None,
        crm_export: Path | None = None) -> int:
    run_id, timestamp = new_run_id(), utc_now()
    discovery = {"run_id": run_id, "timestamp": timestamp,
                 "notion_api_version": "2026-03-11", "providers": {}}
    ingest = {"run_id": run_id, "timestamp": timestamp, "providers": {},
              "complete_pagination": False}
    tokens = {"notion": os.getenv("NOTION_API_KEY"), "airtable": os.getenv("AIRTABLE_TOKEN")}
    # A Notion workspace export replaces Notion API access; a CRM export file replaces the Airtable API.
    exports = {"notion": notion_export, "airtable": crm_export}
    missing = [name for name, token in tokens.items() if not token and not exports[name]]
    if missing:
        discovery["providers"] = {name: {"status": "blocked_missing_credential" if name in missing else "not_attempted"}
                                  for name in tokens}
        ingest["status"] = "blocked_missing_credential"
        ingest["warnings"] = [f"{name} credential unavailable" for name in missing]
        _write_output(output_dir / "source_discovery_report.json", discovery)
        _write_output(output_dir / "source_ingest_report.json", ingest)
        _write_output(output_dir / "source_manifest.json", {"run_id": run_id, "timestamp": timestamp,
                                                              "complete": False, "envelopes": []})
        _implementation(output_dir, "Live run blocked: required provider credentials unavailable; no snapshot or manifest created.")
        return 2 if require_live else 0
    try:
        airtable_api = ExportClient(crm_export) if crm_export else ReadClient("airtable", tokens["airtable"])
        if notion_export:
            notion_items, notion_report = load_export(str(notion_export))
            n = {"abstained": False, "selected": notion_report["selected"], "acquisition": "notion_export_zip",
                 "export_sha256": notion_report["export_sha256"], "export_file": Path(notion_export).name}
            discovery["providers"]["notion"] = dict(n)
        else:
            notion_api = ReadClient("notion", tokens["notion"])
            n = discover_notion(notion_api, notion_hints())
            discovery["providers"]["notion"] = {k: v for k, v in n.items() if k != "selected_rows"}
            if n["abstained"]:
                raise RuntimeError("Notion discovery abstained; set a validated NOTION scope hint")
        a = discover_airtable(airtable_api, os.getenv("AIRTABLE_BASE_ID"))
        discovery["providers"]["airtable"] = {k: v for k, v in a.items() if k != "selected_schema"}
        if a["abstained"]:
            raise RuntimeError("Airtable discovery abstained; set AIRTABLE_BASE_ID")
        discovery["providers"]["notion"]["status"] = "selected"
        discovery["providers"]["airtable"]["status"] = "selected"
        if crm_export:
            discovery["providers"]["airtable"].update({"acquisition": "crm_export_json", "export_file": airtable_api.file,
                                                      "export_sha256": airtable_api.sha256})
        baseline = source_baseline()
        discovery["source_baseline"] = baseline
        if not notion_export:
            notion_items, notion_report = ingest_notion(notion_api, n)
        airtable_items, airtable_report = ingest_airtable(airtable_api, a)
        counts = {t["name"]: airtable_report["counts_by_table_id"].get(t["id"], 0)
                  for t in a["selected"]["tables"]}
        discovery["reconciliation"] = {"notion_current": {k: n["selected"][k] for k in
                                        ("record_count", "structured_date_count", "meeting_type_count")},
                                        "airtable_current_by_table": counts,
                                        "logic": "title/property schema and complete source counts versus the configured "
                                                 "baseline; no business inference"}
        warnings = []
        if baseline:
            expected_crm = baseline.get("airtable") or {}
            discovery["reconciliation"].update({
                "notion_delta_vs_baseline": {
                    "meeting_notes": n["selected"]["record_count"] - baseline["notion_meeting_notes"],
                    "structured_date": n["selected"]["structured_date_count"] - baseline["notion_structured_date"],
                    "meeting_type": n["selected"]["meeting_type_count"] - baseline["notion_meeting_type"]},
                "airtable_delta_vs_baseline": {name: next((value - old for table, value in counts.items()
                    if table.casefold() == name), None) for name, old in expected_crm.items()}})
            if n["selected"]["record_count"] < baseline["notion_meeting_notes"] / 2:
                warnings.append(f"Notion corpus is less than half the expected {baseline['notion_meeting_notes']} notes")
            for table, old in expected_crm.items():
                actual = next((v for k, v in counts.items() if k.casefold() == table), None)
                if actual is not None and actual != old:
                    warnings.append(f"CRM {table} count changed from baseline {old} to {actual}")
        discovery["warnings"] = warnings
        discovery["status"] = "complete"
        raw_root.mkdir(parents=True, exist_ok=True)
        run_dir = raw_root / run_id
        run_dir.mkdir(exist_ok=False)
        envelopes = []
        for provider, items in (("notion", notion_items), ("airtable", airtable_items)):
            for item in items:
                path = run_dir / provider / item["native_object_type"] / f"{item['native_id']}.json"
                write_json(path, {"content": item["content"],
                                  "retrieval_provenance": {"provider": provider,
                                      "retrieved_at": timestamp, "complete_pagination": True,
                                      "acquisition": ("notion_export_zip" if notion_export else "api") if provider == "notion"
                                                     else ("crm_export_json" if crm_export else "api"),
                                      "native_id": item["native_id"],
                                      "scope": n["selected"]["id"] if provider == "notion" else a["selected"]["id"]}})
                envelopes.append(_envelope(provider, item, path, timestamp))
        write_json(run_dir / "notion" / "inventory.json", discovery["providers"]["notion"])
        write_json(run_dir / "notion" / "schema.json", {
            "selected_collection": next((i["content"]["object"] for i in notion_items
                                         if i["native_object_type"] == "data_source"), None)})
        write_json(run_dir / "airtable" / "schema.json", a["selected_schema"])
        write_json(run_dir / "airtable" / "inventory.json", discovery["providers"]["airtable"])
        previous = _previous_manifest(output_dir)
        ingest.update({"status": "complete", "complete_pagination": True,
                       "providers": {"notion": notion_report, "airtable": airtable_report},
                       "change_detection": diff_manifest(envelopes, previous, complete=True),
                       "warnings": warnings, "raw_snapshot": run_dir.as_posix()})
        manifest = {"run_id": run_id, "timestamp": timestamp, "complete": True,
                    "hash_version": "provider-stable-v2",
                    "envelopes": [asdict(e) for e in envelopes]}
        _write_output(output_dir / "source_discovery_report.json", discovery)
        _write_output(output_dir / "source_ingest_report.json", ingest)
        _write_output(output_dir / "source_manifest.json", {"run_id": run_id, "timestamp": timestamp,
                                                              "complete": False, "envelopes": []})
        _write_output(output_dir / "source_manifest.json", manifest)
        _implementation(output_dir, f"Complete live ingestion. Snapshot: {run_dir.as_posix()}; {len(envelopes)} source objects.")
        return 0
    except Exception as exc:
        discovery["status"] = "incomplete"
        discovery["error"] = safe_error(exc)
        ingest.update({"status": "incomplete", "warnings": [safe_error(exc)],
                       "complete_pagination": False, "trusted_deletions": False})
        _write_output(output_dir / "source_discovery_report.json", discovery)
        _write_output(output_dir / "source_ingest_report.json", ingest)
        _implementation(output_dir, f"Live ingestion incomplete: {safe_error(exc)}. No complete manifest emitted.")
        return 2


def _implementation(output_dir: Path, statement: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "implementation_report.md").write_text(
        "# Stage A2 implementation\n\n" + statement +
        "\n\nAdapters use read-only API operations, preserve provider JSON and separate schema, "
        "and emit transport-only envelopes. Source timestamps remain metadata. "
        "Configured source baseline counts, when present, are reconciliation checks only.\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-live", action="store_true")
    parser.add_argument("--mode", choices=("full",), default="full")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/A2"))
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw"))
    parser.add_argument("--notion-export", type=Path, default=os.getenv("NOTION_EXPORT_ZIP") or None,
                        help="Notion workspace export zip (Markdown & CSV) used instead of the Notion API")
    parser.add_argument("--crm-export", type=Path, default=os.getenv("CRM_EXPORT_JSON") or None,
                        help="CRM export JSON (airtable-base-export/1) used instead of the Airtable API")
    args = parser.parse_args()
    return run(args.output_dir, args.raw_root, args.require_live, args.notion_export, args.crm_export)


if __name__ == "__main__":
    raise SystemExit(main())
