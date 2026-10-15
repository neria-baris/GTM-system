"""Notion export zip -> API-shaped snapshots; read in memory, never extracted."""
import zipfile

import pytest

from src.connectors.notion_export_ingest import load_export
from src.extraction.full_corpus import notion_units
from src.extraction.semantic_llm import normalize_note

DB = "dd1275a3be238220b4aa81fa29081970"
NOTE = """# Coldharbour

Attendees: Owen Marsh, Dana Whitfield
Created by: Owner
Date: April 24, 2026
Meeting type: Pilot sync

# Notes

- SIGNED. €580k/yr, 2-yr term
- Rollout one distribution centre first
"""


def make_zip(tmp_path, notes, rows=None, extra=None):
    path = tmp_path / "export.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"WS/Meeting notes {DB}.csv", "Name,Date\n" + "".join(f"n{i},x\n" for i in range(rows if rows is not None else len(notes))))
        z.writestr(f"WS/Meeting notes {DB}_all.csv", "Name\n")
        for i, text in enumerate(notes):
            z.writestr(f"WS/Meeting notes/Note {i:032x}.md", text)
        for name, text in (extra or {}).items():
            z.writestr(name, text)
    return path


def test_export_pages_match_the_api_shape_and_extraction_units(tmp_path):
    objects, report = load_export(str(make_zip(tmp_path, [NOTE, "# Undated\n\n# Notes\n\n- Keen\n"],
                                               extra={"WS/GTM target 0123456789abcdef0123456789abcdef.md": "# Target\n"})))
    pages = [o for o in objects if o["schema_ref"] and o["native_object_type"] == "page"]
    assert report["record_count"] == 2 and report["structured_date_count"] == 1 and report["meeting_type_count"] == 1
    assert report["other_pages"] == 1 and len(report["export_sha256"]) == 64
    first = pages[0]["content"]["page"]
    assert first["properties"]["Date"]["date"]["start"] == "2026-04-24"
    assert [x["name"] for x in first["properties"]["Attendees"]["multi_select"]] == ["Owen Marsh", "Dana Whitfield"]
    assert pages[0]["schema_ref"] == "notion/data_source/dd1275a3-be23-8220-b4aa-81fa29081970"
    units, _ = notion_units({"content": pages[0]["content"]})
    text = normalize_note(units)["text"]
    assert "SIGNED. €580k/yr, 2-yr term" in text and "Rollout one distribution centre first" in text
    assert any(o["native_object_type"] == "data_source" for o in objects)


def test_export_rejects_unsafe_paths_and_inconsistent_counts(tmp_path):
    with pytest.raises(ValueError, match="inconsistent"):
        load_export(str(make_zip(tmp_path, [NOTE], rows=3)))
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr(f"WS/Meeting notes {DB}.csv", "Name\n")
        z.writestr("../evil 0123456789abcdef0123456789abcdef.md", "# x\n")
    with pytest.raises(ValueError, match="Unsafe"):
        load_export(str(bad))
