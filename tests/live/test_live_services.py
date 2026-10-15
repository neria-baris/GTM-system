"""Opt-in checks against the real providers (GTM_LIVE_TESTS=1). Key values are never printed."""
import os

import httpx
import pytest

from src.belief.jev_sensors import readings, questions_for
from src.belief.signals import make_signal
from src.extraction.ensemble import run_batch
from src.extraction.semantic_llm import extract, normalize_note

pytestmark = pytest.mark.live


def _key(name):
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"{name} is not configured")
    return value


def test_airtable_token_reads_the_crm_base():
    r = httpx.get("https://api.airtable.com/v0/meta/bases", headers={"Authorization": f"Bearer {_key('AIRTABLE_TOKEN')}"},
                  timeout=30)
    assert r.status_code == 200, r.status_code
    assert r.json().get("bases"), "token sees no Airtable base"


def test_notion_source_is_available():
    """Notion API pages, or the configured workspace export when the integration has no shared pages."""
    r = httpx.post("https://api.notion.com/v1/search", json={"page_size": 10}, timeout=30,
                   headers={"Authorization": f"Bearer {_key('NOTION_API_KEY')}", "Notion-Version": "2026-03-11"})
    assert r.status_code == 200, r.status_code
    if r.json().get("results"):
        return
    export = os.environ.get("NOTION_EXPORT_ZIP")
    assert export, ("Notion key is valid but no page is shared with the integration and no NOTION_EXPORT_ZIP is set "
                    "(Notion: page menu -> Connections -> add the integration, or export the workspace)")
    from pathlib import Path
    from src.connectors.notion_export_ingest import load_export
    path = Path(export) if Path(export).is_absolute() else Path(__file__).resolve().parents[2] / export
    _, report = load_export(str(path))
    assert report["record_count"] > 0


def test_jev_sensor_separates_plans_from_execution():
    signal = make_signal("kickoff_completed", evidence_ids=["live"], method="luna_semantic", id_seed="live-jev",
                         opportunity_id="live", effective_date="2026-06-01")
    _key("JEV_API_KEY")
    batch = run_batch("Pilot planned for next month.", questions_for("kickoff_completed"), 1)
    assert batch["aggregate"], batch["failures"]
    choices = {r["sensor"]: r["choice"] for r in readings(batch)}
    assert choices.get("pilot_activity") == "planned" or choices.get("statement_modality") == "planned", choices
    assert signal["signal_type"] == "kickoff_completed"


def test_luna_extracts_atomic_signals_with_medium_reasoning():
    _key("OPENAI_API_KEY")
    os.environ.setdefault("OPENAI_SEMANTIC_REASONING", "medium")
    units = [{"source_part": "notion_block", "start": 0, "json_pointer": "/x", "block_id": "b", "evidence_unit_id": "u",
              "text": "Kickoff held on Monday. Customer uploaded 18 months of lot history. If the pilot works, they will roll out."}]
    result = extract(normalize_note(units), {"accounts": [], "contacts": [], "opportunities": []})
    assert result["status"] == "completed", [c.get("failure_detail") for c in result["calls"]]
    kinds = {x["data"].get("signal_type") for x in result["accepted"] if x["collection"] == "atomic_signals"}
    assert kinds & {"kickoff_completed", "data_received"}, kinds
