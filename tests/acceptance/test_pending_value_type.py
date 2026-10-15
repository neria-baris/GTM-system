import pytest
from src.ledger import Ledger
from src.ledger.fixtures import load_audit_fixtures
from src.models import quantitative


@pytest.mark.parametrize("value_type", ["pilot_fee", "unknown_type", "tcv", "one_time_fee"])
def test_pending_signature_does_not_turn_untyped_or_pilot_money_into_acv(monkeypatch, value_type):
    ledger = Ledger()
    try:
        ids = load_audit_fixtures(ledger)
        oid = ids["Coldharbour"]["opportunity"]
        original = quantitative._rows
        def rows(store, table):
            data = original(store, table)
            if table == "commercial_value":
                return [{**v, "value_type": value_type} if v["opportunity_id"] == oid else v for v in data]
            return data
        monkeypatch.setattr(quantitative, "_rows", rows)
        result = quantitative.weekly_state(ledger, "2026-09-13")
        assert result["reported_signed_possible_acv_usd"] is None
        assert result["verified_actual_usd"] == "0"
    finally:
        ledger.close()
