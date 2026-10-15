"""Full-corpus boundary: every C2 proposal has an auditable disposition."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ledger import Ledger
from src.models.full_corpus import integrate_full_corpus
from src.models.quantitative import historically_known_state

ROOT = Path(__file__).resolve().parents[2]


def source(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))












def test_serialized_evidence_pointer_disambiguates_repeated_strings():
    from src.models.full_corpus import serialized_span
    content = {"a": "same quote", "b": ["same quote", "prefix same quote"]}
    span = {"json_pointer": "/content/b/1", "start": 7, "end": 17, "exact_text": "same quote"}
    start, end, exact = serialized_span(content, span)
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"))
    assert encoded[start:end] == exact == "same quote"
    assert start == encoded.rindex("same quote")
