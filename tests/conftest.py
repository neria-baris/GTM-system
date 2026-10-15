"""Packaged tests are offline, even when the caller has live credentials.

Tests marked `live` call the real providers with the owner's keys. They run only
when GTM_LIVE_TESTS=1 and are skipped otherwise.
"""
import os
from pathlib import Path
import socket

import pytest

ROOT = Path(__file__).resolve().parents[1]


def pytest_configure(config):
    config.addinivalue_line("markers", "live: calls real provider APIs; run with GTM_LIVE_TESTS=1")


@pytest.fixture(autouse=True)
def offline_only(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        if os.environ.get("GTM_LIVE_TESTS") != "1":
            pytest.skip("live provider test; set GTM_LIVE_TESTS=1 to run")
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=True)
        return
    for key in ('OPENAI_API_KEY', 'JEV_API_KEY', 'NOTION_API_KEY', 'AIRTABLE_TOKEN'):
        monkeypatch.delenv(key, raising=False)
    original = socket.socket.connect
    def connect(sock, address):
        if isinstance(address, tuple) and address[0] not in {'127.0.0.1', 'localhost', '::1'}:
            raise AssertionError('External network access is forbidden in the test suite')
        return original(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', connect)
