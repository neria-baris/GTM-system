"""Canonical roundtrip using synthetic inputs; no recorded live corpus required."""
import sqlite3

import pytest

from src.ledger import Ledger
from src.ledger import Account, CommercialScope, Opportunity, Event, Evidence, SourceRef
from src.models.canonical_store import load_canonical, save_canonical, validate_canonical


def test_canonical_roundtrip_readonly_and_exact_evidence(tmp_path):
    ledger = Ledger()
    try:
        text = 'Follow-up held for the control use case at one site'
        ref = SourceRef('fixture', 'note', 'meeting')
        digest = ledger.ingest_raw(ref, 'v1', text, '2026-09-01', '2026-09-01')
        evidence = Evidence(source_ref=ref, source_version='v1', source_hash=digest,
                            verbatim_excerpt=text, start_offset=0, end_offset=len(text),
                            source_first_seen_at='2026-09-01', ingested_at='2026-09-01')
        ledger.add_evidence(evidence)
        account = Account(id='fixture-account', canonical_name='Example', created_in_ledger_at='2026-09-01')
        scope = CommercialScope(id='fixture-scope', scope_id='fixture-scope', account_id=account.id,
                                product_use_case='control', boundary_text='one site', created_in_ledger_at='2026-09-01')
        opportunity = Opportunity(account_id=account.id, use_case_code='control', commercial_scope_id=scope.id,
                                  opportunity_group_id='fixture-group', origin_evidence_id=evidence.evidence_id,
                                  created_in_ledger_at='2026-09-01')
        for item in (account, scope, opportunity):
            ledger.add_entity(item)
        ledger.add_event(Event(event_type='follow_up_held', account_id=account.id, opportunity_id=opportunity.id,
                               scope_id=scope.id, event_date='2026-09-01', first_seen_at='2026-09-01',
                               evidence_ids=(evidence.evidence_id,)))
        metadata = {'review_items': [], 'candidate_dispositions': [], 'input_hashes': {},
                    'c2_semantic_counts': {'opportunity_candidate_count': 1, 'event_candidate_count': 1}}
        destination = tmp_path / 'canonical.sqlite'
        saved = save_canonical(ledger, metadata, destination)
        assert saved['canonical_opportunity_count'] > 0
        assert saved == validate_canonical(destination)
        loaded, restored = load_canonical(destination)
        try:
            with pytest.raises(sqlite3.OperationalError, match='readonly'):
                loaded.db.execute('CREATE TABLE forbidden(id TEXT)')
            assert restored == metadata
            assert loaded.count('event') == ledger.count('event') > 0
            assert saved['verified_actual_usd'] == '0'
        finally:
            loaded.close()
    finally:
        ledger.close()
