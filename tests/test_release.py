import hashlib
import json
from pathlib import Path

import pytest

from scripts import run_live

ROOT = Path(__file__).resolve().parents[1]


def test_all_production_imports_and_runtime_resources_are_packaged():
    assert len(run_live.audit_resources()) >= 25


def test_live_preflight_missing_credentials_never_starts_pipeline(monkeypatch):
    monkeypatch.setattr(run_live, 'configure', lambda: None)
    monkeypatch.setattr(run_live.subprocess, 'run', lambda *a, **k: pytest.fail('Preflight started a process'))
    assert run_live.main(['--check-only']) == 2


def test_live_preflight_loads_dotenv_and_stops_before_external_calls(monkeypatch, tmp_path):
    original = run_live.ROOT
    (tmp_path / '.env').write_text(''.join(key + '=fixture-only\n' for key in run_live.REQUIRED))
    monkeypatch.setattr(run_live, 'ROOT', tmp_path)
    run_live.configure()
    monkeypatch.setattr(run_live, 'ROOT', original)
    monkeypatch.setattr(run_live.subprocess, 'run', lambda *a, **k: pytest.fail('Preflight started a process'))
    assert run_live.main(['--check-only']) == 0


def test_live_command_plan_uses_real_modules_and_not_demo():
    plan = run_live.commands()
    text = json.dumps(plan)
    assert 'src.connectors.sync_cli' in text and 'src.extraction.full_corpus' in text
    assert '--require-jev' in text and '--llm' in text
    assert 'run_stage_c_full_corpus.py' in text and 'build_stage_d.py' in text
    assert 'validate_canonical_state.py' in text and 'validate_presentation_contract.py' in text
    assert 'runtime.live_server' in text
    assert 'demo' not in text and 'run_pipeline.py' not in text


def test_live_server_routes_fresh_contract_without_touching_demo():
    from runtime.live_server import LiveHandler
    handler = LiveHandler.__new__(LiveHandler)
    assert Path(handler.translate_path('/demo/overview.json')) == ROOT / 'outputs/D/runtime/overview.json'


def test_frozen_demo_hashes_and_metrics():
    manifest = json.loads((ROOT / 'RELEASE_MANIFEST.json').read_text())
    for relative in manifest['primary_frozen_data_files']:
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == manifest['sha256'][relative]
    read = lambda name: json.loads((ROOT / 'demo' / (name + '.json')).read_text())['data']
    assert len(read('opportunities')) == manifest['frozen_product_metrics']['displayed_opportunities']
    assert read('overview')['verified_signed_acv_usd'] == manifest['frozen_product_metrics']['verified_actual_usd']
