"""Organisation settings: config values, defaults for missing keys, and the today fallback."""
import json
from datetime import datetime, timezone
from decimal import Decimal

from src import settings


def load(monkeypatch, tmp_path, value):
    path = tmp_path / "tracker.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setenv("GTM_CONFIG", str(path))
    settings.settings.cache_clear()


def test_configured_values(monkeypatch, tmp_path):
    load(monkeypatch, tmp_path, {"seller": {"name": "Acme", "aliases": ["Acme Inc"]},
                                 "goal": {"amount_usd": "1200000"}, "business_as_of": "2026-03-01",
                                 "fx_to_usd": {"USD": "1", "EUR": "1.1"}, "source_baseline": None})
    try:
        assert settings.seller_names() == ["Acme", "Acme Inc"]
        assert settings.goal_amount() == Decimal("1200000")
        assert settings.goal_window() == ("2026-01-01", "2027-03-31")  # unspecified keys keep defaults
        assert settings.business_as_of() == "2026-03-01"
        assert settings.fx_to_usd()["EUR"] == Decimal("1.1")
        assert settings.source_baseline() is None
    finally:
        settings.settings.cache_clear()


def test_missing_reference_date_means_today(monkeypatch, tmp_path):
    load(monkeypatch, tmp_path, {})
    try:
        assert settings.business_as_of() == datetime.now(timezone.utc).date().isoformat()
        assert settings.timezone() == "UTC"
    finally:
        settings.settings.cache_clear()


def test_bundled_config_matches_the_sample():
    settings.settings.cache_clear()
    assert settings.seller_names() == ["Vendora"]
    assert settings.business_as_of() == "2026-09-13"
    assert settings.source_baseline()["airtable"]["contacts"] == 187
