"""CRM export JSON served through the read-only client: discovery and ingestion run unchanged."""
import json
from pathlib import Path

import pytest

from src.connectors.airtable_discovery import discover_airtable
from src.connectors.airtable_export import FORMAT, ExportClient
from src.connectors.airtable_ingest import ingest_airtable
from src.connectors.common import airtable_pages

TABLES = [{"id": "tblC", "name": "Companies", "primaryFieldId": "fN",
           "fields": [{"id": "fN", "name": "Company Name", "type": "singleLineText"}], "views": []},
          {"id": "tblP", "name": "Contacts", "primaryFieldId": "fP",
           "fields": [{"id": "fP", "name": "Full Name", "type": "singleLineText"}], "views": []}]


def export(tmp_path, companies=3, **overrides) -> Path:
    data = {"format": FORMAT, "base": {"id": "appX", "name": "Sample CRM"}, "tables": TABLES,
            "records": {"tblC": [{"id": f"rec{i}", "createdTime": "2026-01-01T00:00:00.000Z",
                                  "fields": {"fN": f"Company {i}"}} for i in range(companies)],
                        "tblP": []}}
    data.update(overrides)
    path = tmp_path / "crm.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_export_pages_like_the_api(tmp_path):
    client = ExportClient(export(tmp_path, companies=250))
    pages = list(airtable_pages(client, "/appX/tblC", params={"pageSize": 100}, key="records"))
    assert [len(p["records"]) for p in pages] == [100, 100, 50]
    assert client.request("GET", "/meta/bases")["bases"][0]["id"] == "appX"


def test_export_is_read_only_and_validated(tmp_path):
    client = ExportClient(export(tmp_path))
    with pytest.raises(ValueError):
        client.request("POST", "/appX/tblC")
    with pytest.raises(ValueError):
        client.request("GET", "/appY/tblC")
    with pytest.raises(ValueError):
        ExportClient(export(tmp_path, format="other/1"))
    with pytest.raises(ValueError):
        ExportClient(export(tmp_path, records={"tblZ": []}))


def test_discovery_and_ingestion_run_on_the_export(tmp_path):
    client = ExportClient(export(tmp_path))
    found = discover_airtable(client)
    assert not found["abstained"] and found["selected"]["id"] == "appX"
    items, report = ingest_airtable(client, found)
    assert report["counts_by_table_id"] == {"tblC": 3, "tblP": 0}
    assert {i["content"]["record"]["fields"]["fN"] for i in items} == {"Company 0", "Company 1", "Company 2"}


def test_bundled_sample_export_is_valid():
    client = ExportClient(Path(__file__).resolve().parents[2] / "config/crm_export.json")
    found = discover_airtable(client)
    _, report = ingest_airtable(client, found)
    assert sorted(report["counts_by_table_id"].values()) == [0, 5, 66, 187]
