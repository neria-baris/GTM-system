import json

import httpx
import pytest

from src.connectors.common import (EvidenceSourceEnvelope, IncompleteFetch, ReadClient,
                                   content_hash, diff_manifest, notion_pages, stable_provider_content)
from src.connectors.notion_discovery import discover_notion, query_data_source
from src.connectors.notion_ingest import block_tree
from src.connectors.airtable_discovery import discover_airtable, list_bases
from src.connectors.airtable_ingest import ingest_airtable
from src.connectors.sync_cli import run


def api(provider, handler, *, sleeps=None, retries=1):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return ReadClient(provider, "DO_NOT_REPORT_SECRET", client=client,
                      sleep=(sleeps or (lambda _: None)), max_retries=retries)


def response(data, status=200, headers=None):
    return httpx.Response(status, json=data, headers=headers)


def ds(identifier, name="Meeting notes"):
    return {"object": "data_source", "id": identifier,
            "title": [{"plain_text": name}],
            "properties": {"Name": {"id": "n", "type": "title"},
                           "Date": {"id": "d", "type": "date"},
                           "Meeting type": {"id": "m", "type": "select"}}}


def note(identifier):
    return {"object": "page", "id": identifier,
            "properties": {"Date": {"date": {"start": "2026-01-01"}},
                           "Meeting type": {"select": {"name": "call"}}}}


def test_notion_search_and_query_pagination_and_hint():
    calls = []
    def handler(request):
        calls.append((request.url.path, json.loads(request.content or b"{}")))
        path = request.url.path
        body = calls[-1][1]
        if path.endswith("/search"):
            return response({"results": [ds("s1")] if not body.get("start_cursor") else [],
                             "has_more": not body.get("start_cursor"),
                             "next_cursor": "next" if not body.get("start_cursor") else None})
        if path.endswith("/query"):
            return response({"results": [note("p1")] if not body.get("start_cursor") else [note("p2")],
                             "has_more": not body.get("start_cursor"),
                             "next_cursor": "next" if not body.get("start_cursor") else None})
        if path.endswith("/data_sources/s1"):
            return response(ds("s1"))
        raise AssertionError(path)
    result = discover_notion(api("notion", handler), {"data_source_id": "s1"})
    assert result["selected"]["record_count"] == 2
    assert result["selected"]["structured_date_count"] == 2
    assert len([c for c in calls if c[0].endswith("/search")]) == 2
    assert len([c for c in calls if c[0].endswith("/query")]) == 2


def test_notion_multiple_candidates_abstain_and_bad_hint():
    def handler(request):
        path = request.url.path
        if path.endswith("/search"):
            return response({"results": [ds("one"), ds("two")], "has_more": False})
        if path.endswith("/query"):
            return response({"results": [note("p")], "has_more": False})
        if path.endswith("/data_sources/bad"):
            return response({}, 404)
        raise AssertionError(path)
    notion = api("notion", handler)
    assert discover_notion(notion)["abstained"]
    with pytest.raises(httpx.HTTPStatusError):
        discover_notion(notion, {"data_source_id": "bad"})


def test_recursive_blocks_all_cursors():
    def handler(request):
        path = request.url.path
        cursor = request.url.params.get("start_cursor")
        if path.endswith("/root/children"):
            return response({"results": [{"id": "nested", "has_children": True}] if not cursor else
                             [{"id": "sibling", "has_children": False}],
                             "has_more": not cursor, "next_cursor": "more" if not cursor else None})
        return response({"results": [{"id": "leaf", "has_children": False}], "has_more": False})
    result = block_tree(api("notion", handler), "root")
    assert [v["block"]["id"] for v in result] == ["nested", "sibling"]
    assert result[0]["children"][0]["block"]["id"] == "leaf"


def table(identifier, name):
    return {"id": identifier, "name": name,
            "fields": [{"id": "fld1", "name": "Name", "type": "singleLineText"},
                       {"id": "fld2", "name": "Relation", "type": "multipleRecordLinks",
                        "options": {"linkedTableId": "tbl2"}}],
            "views": [{"id": "viw1", "name": "Grid", "type": "grid"}]}


def test_airtable_bases_pagination_one_base_and_schema():
    def handler(request):
        path = request.url.path
        if path.endswith("/meta/bases"):
            return response({"bases": [{"id": "app1", "name": "CRM"}], "offset": "more"}
                            if not request.url.params.get("offset") else {"bases": []})
        if path.endswith("/tables"):
            return response({"tables": [table("tbl1", "Companies"), table("tbl2", "Contacts")]})
        raise AssertionError(path)
    airtable = api("airtable", handler)
    assert len(list_bases(airtable)) == 1
    result = discover_airtable(airtable)
    assert result["selected"]["id"] == "app1"
    assert result["selected"]["tables"][0]["fields"][1]["linked_table_id"] == "tbl2"


def test_airtable_multiple_plausible_abstains_and_hint_validates():
    def handler(request):
        path = request.url.path
        if path.endswith("/meta/bases"):
            return response({"bases": [{"id": "app1", "name": "Vendora"},
                                       {"id": "app2", "name": "Other"}]})
        if path.endswith("/tables"):
            return response({"tables": [table("t1", "Companies"), table("t2", "Contacts"),
                                        table("t3", "Deals")]})
        if path.endswith("/t1") or path.endswith("/t2") or path.endswith("/t3"):
            return response({"records": []})
        raise AssertionError(path)
    airtable = api("airtable", handler)
    assert discover_airtable(airtable)["abstained"]
    assert discover_airtable(airtable, "app2")["selected"]["id"] == "app2"
    with pytest.raises(Exception):
        discover_airtable(airtable, "missing")


def test_airtable_records_paginate_schema_keeps_omitted_fields():
    calls = []
    def handler(request):
        calls.append(request)
        return response({"records": [{"id": "rec1", "fields": {"fld1": "A"}}], "offset": "next"}
                        if not request.url.params.get("offset") else
                        {"records": [{"id": "rec2", "fields": {}}]})
    discovery = {"abstained": False, "selected": {"id": "app1", "tables": [
        {"id": "tbl1", "name": "Companies", "fields": [
            {"id": "fld1", "name": "Name"}, {"id": "fld2", "name": "Empty"}]}]}}
    records, report = ingest_airtable(api("airtable", handler), discovery)
    assert report["record_count"] == 2
    assert records[1]["content"]["record"]["fields"] == {}
    assert len(discovery["selected"]["tables"][0]["fields"]) == 2
    assert all(r.url.params["returnFieldsByFieldId"] == "true" for r in calls)


def test_retry_partial_failure_hash_and_transport_boundary():
    seen, waits = [], []
    def retry(request):
        seen.append(request)
        return response({}, 503) if len(seen) == 1 else response({"ok": True})
    assert api("airtable", retry, sleeps=waits.append).request("GET", "/meta/bases") == {"ok": True}
    assert waits
    def broken(request):
        return response({"results": [], "has_more": True})
    with pytest.raises(IncompleteFetch):
        list(notion_pages(api("notion", broken), "POST", "/search"))
    assert content_hash({"b": 2, "a": 1}) == content_hash({"a": 1, "b": 2})
    first = {"page": {"id": "p", "request_id": "one", "properties": {"Name": "A"}}}
    second = {"page": {"id": "p", "request_id": "two", "properties": {"Name": "A"}}}
    assert content_hash(stable_provider_content("notion", first)) == content_hash(stable_provider_content("notion", second))
    envelope = EvidenceSourceEnvelope("notion", "page", "p", [], None, "now", "hash", "raw", True, None)
    assert not ({"acv", "commercial_signed", "probability", "canonical_opportunity_id"}
                & set(envelope.__dict__))
    previous = [dict(provider="notion", native_object_type="page", native_id="p", content_hash="hash")]
    assert diff_manifest([envelope], previous, complete=True)["unchanged"] == 1
    assert diff_manifest([], previous, complete=False)["missing_from_current_fetch"] == 0
    assert "DO_NOT_REPORT_SECRET" not in json.dumps(diff_manifest([], previous, complete=False))


def test_notion_provider_incomplete_status_blocks_fetch():
    def handler(request):
        return response({"results": [], "has_more": False,
                         "request_status": {"type": "incomplete", "incomplete_reason": "limit"}})
    with pytest.raises(IncompleteFetch):
        list(notion_pages(api("notion", handler), "POST", "/search"))


def test_require_live_missing_tokens_produces_incomplete_artifacts(tmp_path, monkeypatch):
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    monkeypatch.delenv("AIRTABLE_TOKEN", raising=False)
    monkeypatch.setenv("UNRELATED_SECRET", "DO_NOT_REPORT_SECRET")
    output = tmp_path / "out"
    assert run(output, tmp_path / "raw", require_live=True) == 2
    assert not json.loads((output / "source_manifest.json").read_text())["complete"]
    assert not (tmp_path / "raw").exists()
    for path in output.iterdir():
        assert "DO_NOT_REPORT_SECRET" not in path.read_text()
