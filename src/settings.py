"""Organisation settings: seller identity, goal, reference date, FX and source baseline.

Read once from config/tracker.json (or the file named by GTM_CONFIG). Missing keys fall
back to the defaults below, so a partial file is valid.
"""
from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS: dict[str, Any] = {
    "product_name": "GTM Tracker",
    "seller": {"name": "Seller", "aliases": []},
    "goal": {"amount_usd": "5000000", "start": "2026-01-01", "deadline": "2027-03-31"},
    "business_as_of": None,
    "timezone": "UTC",
    "fx_to_usd": {"USD": "1"},
    "source_baseline": None,
}


@lru_cache(maxsize=1)
def settings() -> dict[str, Any]:
    path = Path(os.getenv("GTM_CONFIG") or ROOT / "config/tracker.json")
    loaded = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    merged = {**DEFAULTS, **{k: v for k, v in loaded.items() if not k.startswith("_")}}
    for key in ("seller", "goal"):
        merged[key] = {**DEFAULTS[key], **(loaded.get(key) or {})}
    return merged


def seller_names() -> list[str]:
    seller = settings()["seller"]
    return [n for n in [seller["name"], *seller.get("aliases", [])] if n]


def goal_amount() -> Decimal:
    return Decimal(str(settings()["goal"]["amount_usd"]))


def goal_window() -> tuple[str, str]:
    goal = settings()["goal"]
    return goal["start"], goal["deadline"]


def business_as_of() -> str:
    """Reference date for snapshots; null in the config means today (UTC)."""
    configured = settings()["business_as_of"]
    if configured:
        return configured
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).date().isoformat()


def timezone() -> str:
    return settings()["timezone"]


def fx_to_usd() -> dict[str, Decimal]:
    return {code: Decimal(str(rate)) for code, rate in settings()["fx_to_usd"].items()}


def source_baseline() -> dict[str, Any] | None:
    baseline = settings()["source_baseline"]
    return {k: v for k, v in baseline.items() if not k.startswith("_")} if baseline else None
