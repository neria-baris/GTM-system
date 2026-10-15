"""Source-to-canonical gates with generated local evidence, never live fixtures."""
import copy
import hashlib
import json

import pytest

from src.connectors.common import stable_provider_content
from src.ledger import Ledger
from src.models.full_corpus import integrate_full_corpus


def inputs(root):
    content = {'page': {'properties': {}}, 'text': 'Pilot verbal yes'}
    encoded = json.dumps(stable_provider_content('notion', content), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    raw = root / 'data/raw/fixture.json'
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps({'content': content}), encoding='utf-8')
    env = {'provider': 'notion', 'native_object_type': 'page', 'native_id': 'fixture-note',
           'content_hash': hashlib.sha256(encoded.encode()).hexdigest(), 'raw_snapshot_path': 'data/raw/fixture.json',
           'retrieved_at': '2026-09-27T00:00:00+00:00'}
    candidate = {**env, 'candidate_id': 'fixture-claim', 'extraction_route': 'deterministic',
                 'extractor_version': 'fixture', 'validation_status': 'auto_accepted_extraction',
                 'predicate': 'source_text', 'value': content['text'],
                 'evidence_span': {'coordinate_system': 'source_string_codepoints', 'json_pointer': '/content/text', 'start': 0, 'end': len(content['text']), 'exact_text': content['text']}}
    return {'manifest': {'complete': True, 'run_id': 'fixture', 'envelopes': [env]},
            'coverage': {'coverage_gate_passed': True, 'unaccounted_source_count': 0, 'manifest_complete': True,
                         'a2_run_id': 'fixture', 'considered_source_count': 1,
                         'disposition_counts': {'extracted': 1}, 'source_coverage': [{**env, 'disposition': 'extracted'}]},
            'candidates': [candidate], 'review': {'items': []},
            'policy': {'policy_version': 'fixture', 'field_routes': {}},
            'extraction_report': {'routing_policy_version': 'fixture', 'llm_status': 'fixture', 'jev_k': 0}}


def test_source_layout_never_invents_opportunities(tmp_path):
    ledger = Ledger()
    try:
        result = integrate_full_corpus(tmp_path, ledger, **inputs(tmp_path))
        assert result['considered_source_count'] == 1
        assert result['materialized_source_claim_count'] == 1
        assert result['canonical_opportunity_count'] == result['canonical_event_count'] == 0
        assert result['quantitative_state']['verified_actual_usd'] == '0'
        disposition = result['candidate_dispositions'][0]
        assert ledger.evidence(disposition['evidence_id'])['field_path'] == '/content/text'
    finally:
        ledger.close()


@pytest.mark.parametrize('fault,message', [('coverage','coverage gate'), ('verification','contractual verification'), ('span','source span'), ('hash','content hash')])
def test_source_to_canonical_rejects_invalid_input(tmp_path, fault, message):
    kwargs = inputs(tmp_path)
    if fault == 'coverage':
        kwargs['coverage']['unaccounted_source_count'] = 1
    elif fault == 'verification':
        kwargs['candidates'][0]['verified_signed'] = True
    elif fault == 'span':
        kwargs['candidates'][0]['evidence_span']['exact_text'] = 'Invented signed contract'
    else:
        (tmp_path / 'data/raw/fixture.json').write_text('{"content":{"text":"tampered"}}')
    ledger = Ledger()
    try:
        with pytest.raises(ValueError, match=message):
            integrate_full_corpus(tmp_path, ledger, **kwargs)
        assert ledger.count('event') == ledger.count('commercial_value') == 0
    finally:
        ledger.close()
