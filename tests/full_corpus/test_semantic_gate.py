from src.extraction.full_corpus import semantic_gate


def test_semantic_gate_rejections_are_review_but_failed_processing_blocks():
    report = dict(selected_meeting_notes=111, bodies_dispositioned=111,
                  semantic_attempts=111, opportunity_candidate_count=2, event_candidate_count=3,
                  resolved_account_link_count=1, span_validation_failures=0,
                  forbidden_verification_attempt_count=0, status_counts={"completed": 111},
                  source_coverage_gate_passed=True, rejected_proposal_count=2)
    assert semantic_gate(report)
    for field in ("span_validation_failures", "forbidden_verification_attempt_count"):
        assert not semantic_gate({**report, field: 1})
    assert not semantic_gate({**report, "status_counts": {"completed": 104, "provider_failure": 7}})
    assert not semantic_gate({**report, "bodies_dispositioned": 110})
    assert not semantic_gate({**report, "source_coverage_gate_passed": False})
