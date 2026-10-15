"""Shared transport, immutable snapshots, and provider-neutral handoff."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any
from uuid import uuid4

import httpx


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def stable_provider_content(provider: str, value: Any) -> Any:
    """Exclude ephemeral response metadata from hashes, not from raw snapshots."""
    if provider != "notion":
        return value
    if isinstance(value, dict):
        return {k: stable_provider_content(provider, v) for k, v in value.items()
                if k != "request_id"}
    if isinstance(value, list):
        return [stable_provider_content(provider, v) for v in value]
    return value


def safe_error(exc: Exception) -> str:
    """Never include HTTP request URLs, headers, or response bodies in reports."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.RequestError):
        return type(exc).__name__
    return str(exc) if isinstance(exc, (DiscoveryError, IncompleteFetch)) else type(exc).__name__


class DiscoveryError(RuntimeError):
    pass


class IncompleteFetch(RuntimeError):
    pass


class ReadClient:
    def __init__(self, provider: str, token: str, client: httpx.Client | None = None,
                 sleep=time.sleep, max_retries: int = 4):
        self.provider = provider
        self.client = client or httpx.Client(timeout=30)
        self.sleep = sleep
        self.max_retries = max_retries
        self.last_request = 0.0
        self.headers = {"Authorization": f"Bearer {token}"}
        if provider == "notion":
            self.base = "https://api.notion.com/v1"
            self.headers["Notion-Version"] = "2026-03-11"
        else:
            self.base = "https://api.airtable.com/v0"

    def request(self, method: str, path: str, *, params=None, body=None) -> dict:
        if method not in ("GET", "POST") or (method == "POST" and
            (self.provider != "notion" or not (path == "/search" or
             re.fullmatch(r"/data_sources/[^/]+/query", path)))):
            raise ValueError("read-only API methods only")
        for attempt in range(self.max_retries + 1):
            if self.provider == "airtable":
                delay = .22 - (time.monotonic() - self.last_request)
                if delay > 0:
                    self.sleep(delay)
            try:
                response = self.client.request(method, self.base + path, headers=self.headers,
                                               params=params, json=body)
                self.last_request = time.monotonic()
                if response.status_code in (429, 500, 502, 503, 504):
                    if attempt == self.max_retries:
                        raise IncompleteFetch(f"{self.provider} HTTP {response.status_code} after retries")
                    retry_after = response.headers.get("Retry-After")
                    try:
                        wait = float(retry_after) if retry_after else (30 if self.provider == "airtable" and response.status_code == 429 else min(2 ** attempt, 8))
                    except ValueError:
                        wait = min(2 ** attempt, 8)
                    self.sleep(min(max(wait, 0), 30))
                    continue
                response.raise_for_status()
                value = response.json()
                if not isinstance(value, dict):
                    raise IncompleteFetch(f"{self.provider} returned non-object JSON")
                return value
            except (httpx.RequestError, ValueError) as exc:
                if attempt == self.max_retries:
                    raise IncompleteFetch(f"{self.provider} {type(exc).__name__} after retries") from exc
                self.sleep(min(2 ** attempt, 8))
        raise AssertionError("retry loop exhausted")


def notion_pages(api: ReadClient, method: str, path: str, *, body=None, params=None):
    seen = set()
    cursor = None
    while True:
        b = dict(body or {})
        p = dict(params or {})
        if cursor:
            (b if method == "POST" else p)["start_cursor"] = cursor
        result = api.request(method, path, body=b if method == "POST" else None,
                             params=p if method == "GET" else None)
        if not isinstance(result.get("results"), list) or not isinstance(result.get("has_more"), bool):
            raise IncompleteFetch("Notion pagination metadata missing")
        if (result.get("request_status") or {}).get("type") == "incomplete":
            raise IncompleteFetch("Notion reported incomplete search/query results")
        yield result
        if not result["has_more"]:
            break
        cursor = result.get("next_cursor")
        if not cursor or cursor in seen:
            raise IncompleteFetch("Notion pagination cursor missing or repeated")
        seen.add(cursor)


def airtable_pages(api: ReadClient, path: str, *, params=None, key: str):
    seen = set()
    offset = None
    while True:
        p = dict(params or {})
        if offset:
            p["offset"] = offset
        result = api.request("GET", path, params=p)
        if not isinstance(result.get(key), list):
            raise IncompleteFetch(f"Airtable {key} page missing")
        yield result
        offset = result.get("offset")
        if not offset:
            break
        if offset in seen:
            raise IncompleteFetch("Airtable offset repeated")
        seen.add(offset)


@dataclass(frozen=True)
class EvidenceSourceEnvelope:
    provider: str
    native_object_type: str
    native_id: str
    parent_native_ids: list[str]
    source_title: str | None
    retrieved_at: str
    content_hash: str
    raw_snapshot_path: str
    content_complete: bool
    schema_ref: str | None


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def new_run_id() -> str:
    return str(uuid4())


def parent_ids(obj: dict) -> list[str]:
    parent = obj.get("parent") or {}
    return [str(v) for k, v in parent.items() if k.endswith("_id") and isinstance(v, str)]


def diff_manifest(current: list[EvidenceSourceEnvelope], previous: list[dict] | None,
                  *, complete: bool) -> dict:
    old = {(e["provider"], e["native_object_type"], e["native_id"]): e["content_hash"]
           for e in previous or []}
    now = {(e.provider, e.native_object_type, e.native_id): e.content_hash for e in current}
    result = {"new": 0, "changed": 0, "unchanged": 0,
              "missing_from_current_fetch": 0, "trusted_deletions": False}
    for key, value in now.items():
        result["new" if key not in old else "unchanged" if old[key] == value else "changed"] += 1
    if complete:
        result["missing_from_current_fetch"] = len(old.keys() - now.keys())
    return result
