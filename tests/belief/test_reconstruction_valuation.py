"""Contextual reconstruction, AI-annotation corroboration and reasoned valuation (soft-to-hard evidence)."""
from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path

import pytest

from src.belief import context, presentation, valuation
from src.belief.reconstruction import anchors, reconstruct, signature_dates
from src.belief.signals import lexical_signals, make_signal
from scripts.validate_presentation_contract import _belief_evidence_ids, _validate_context

ROOT = Path(__file__).resolve().parents[2]
AS_OF = "2026-09-13"
AI_NOTE = "[2026-05-18 sync — Claude] Signed 16 May: €580k/yr."
RICH = "Dairy category with shelf-life limits on chilled stock"


def fillers(n: int = 40) -> dict[str, list[str]]:
    """Unrelated sources so that shared anchors are rare, as in a real corpus."""
    return {f"filler-{k:02d}": [f"Note {k}: unrelated item{k} for site{k}"] for k in range(n)}


def corpus(**groups: list[str]) -> dict[str, list[str]]:
    return {**fillers(), **groups}


def linked(result, a: str, b: str) -> bool:
    owner = result["group_to_cluster"]
    return a in owner and owner.get(a) == owner.get(b)


# ---------------------------------------------------------------------------
# Reconstruction rules.

def test_shared_contact_name_alone_never_links():
    result = reconstruct(corpus(a=["Juhani says the roadmap slipped"], b=["Juhani says loads are steady"]))
    assert not linked(result, "a", "b")
    # A name plus an exact amount still lacks a rare topic anchor.
    result = reconstruct(corpus(a=["Juhani says €580k/yr rollout ACV is fine"], b=["Juhani says €580k/yr ACV agreed"]))
    assert not linked(result, "a", "b")
    assert anchors(["Next: book scoping w/ Juhani's team"])["names"] == {"juhani"}
    assert not any("juhani" in b for b in anchors(["Next: book scoping w/ Juhani's team"])["bigrams"])


def test_distinctive_shared_phrase_links_two_sources():
    result = reconstruct(corpus(a=[RICH, "Budget: pilot ~$300k"], b=[RICH, "Data: POS sales history"]))
    assert linked(result, "a", "b")
    cluster = next(c for c in result["clusters"] if "a" in c["groups"])
    assert cluster["opportunity_id"] is None and cluster["links"]
    assert all(link["score"] >= result["min_score"] and link["shared_anchors"] for link in cluster["links"])


def test_template_sentences_give_no_anchors():
    template = "Next: send one-pager and book the scoping call with procurement owners"
    three = reconstruct(corpus(a=[template, "alpha item"], b=[template, "beta item"], c=[template, "gamma item"]))
    assert three["templates_excluded"] >= 1
    assert not any({"a", "b", "c"} & set(c["groups"]) for c in three["clusters"])
    two = reconstruct(corpus(a=[template, "alpha item"], b=[template, "beta item"]))
    assert linked(two, "a", "b")


def test_two_seeded_opportunities_are_never_merged():
    result = reconstruct(corpus(a=[RICH], b=[RICH], c=[RICH + " today"]), seeds={"opp-A": {"a"}, "opp-B": {"b"}})
    owner = {c["opportunity_id"]: set(c["groups"]) for c in result["clusters"] if c["opportunity_id"]}
    assert "b" not in owner["opp-A"] and "a" not in owner["opp-B"]
    assert not any(c["opportunity_id"] is None and {"a", "b"} & set(c["groups"]) for c in result["clusters"])


def test_source_shared_by_two_seeded_opportunities_does_not_merge_them():
    # One note covering two scopes seeds both opportunities; their other notes must stay apart.
    result = reconstruct(corpus(a1=["Alpha deal kickoff"], b1=["Beta deal kickoff"], shared=["Both scopes noted"]),
                         seeds={"opp-A": {"a1", "shared"}, "opp-B": {"b1", "shared"}})
    clusters = result["clusters"]
    assert all(c["opportunity_id"] in {"opp-A", "opp-B"} for c in clusters)
    groups = {c["opportunity_id"]: set(c["groups"]) for c in clusters}
    assert not groups["opp-A"] & groups["opp-B"]
    assert "a1" in groups["opp-A"] and "b1" in groups["opp-B"]


def test_conflicting_contact_names_block_a_merge():
    differ = reconstruct(corpus(a=[f"Met Chiara: {RICH}"], b=[f"Met Felix: {RICH}"]))
    assert not linked(differ, "a", "b")
    same = reconstruct(corpus(a=[f"Met Chiara: {RICH}"], b=[f"Met Chiara again: {RICH}"]))
    assert linked(same, "a", "b")


def test_ai_annotation_never_creates_topic_anchors():
    note = AI_NOTE + " seasonal vaccines with spiky demand"
    a = anchors([note])
    assert not (a["terms"] or a["bigrams"] or a["amounts"] or a["names"])
    result = reconstruct(corpus(ai=[note], deal=["seasonal vaccines with spiky demand", "rollout €580k/yr ACV"]))
    assert "ai" not in result["group_to_cluster"]
    assert signature_dates(AI_NOTE) == ["2026-05-16"]
    assert signature_dates("Signed 16 May: €580k/yr.") == []
    assert signature_dates("Signed 16 May: €580k/yr.", "2026-05-18") == ["2026-05-16"]
    assert signature_dates("Signed 20 Dec", "2026-01-05") == ["2025-12-20"]


# ---------------------------------------------------------------------------
# Context expansion end to end on a synthetic corpus shaped like the demo deal.

def _ev(group: str, texts: list[str], day: str | None = None) -> list[dict]:
    return [{"evidence_id": f"{group}:{i}", "text": t, "date": day} for i, t in enumerate(texts)]


def _signals(group: str, evs: list[dict]) -> list[dict]:
    out = []
    for e in evs:
        for n, r in enumerate(lexical_signals(e["text"])):
            out.append(make_signal(r["signal_type"], evidence_ids=[e["evidence_id"]], method="deterministic_rule",
                                   id_seed=f"t:{e['evidence_id']}:{n}:{r['signal_type']}", effective_date=e["date"],
                                   modality=r["modality"], observation=r["observation"], confidence=r["confidence"],
                                   contract_kind=r["contract_kind"], subject_ref=f"source:{group}",
                                   details={**(r.get("details") or {}), "clause": r["clause"]}))
    return out


def deal_sources(*, second_signed_deal: bool = False, ai_note: str = AI_NOTE) -> dict[str, list[dict]]:
    sources = {
        "n1": _ev("n1", ["seasonal vaccines with spiky demand", "expiry write-offs stuck ~1.4% - Juhani says this costs them real money"],
                  "2026-01-20"),
        "n2": _ev("n2", ["seasonal vaccines with spiky demand", "Integration: ERP with fixed reorder schedules",
                         "Pilot scope: one distribution centre", "Budget: pilot ~€115k", "rollout maybe €580k/yr if it works",
                         "Verbal yes to paid pilot, SOW being drafted"], "2026-02-10"),
        "n3": _ev("n3", ["Steering committee: go to commercial", "ACV discussed €580k/yr",
                         "Results: 14% fewer expiry write-offs, no constraint violations", "Integration: ERP with fixed reorder schedules"]),
        "n4": _ev("n4", ["SIGNED. €580k/yr, 2-yr term", "Rollout one distribution centre first"]),
        "crm": _ev("crm", [ai_note], "2026-05-18"),
    }
    if second_signed_deal:
        sources["m1"] = _ev("m1", ["Store region shrink alarms", "Pilot scope: one store region"], "2026-02-01")
        sources["m2"] = _ev("m2", ["Store region shrink alarms", "SIGNED. €580k/yr, 1-yr term"])
    for g, texts in fillers().items():
        sources[g] = _ev(g, texts, "2026-03-01")
    return sources


def expand(sources: dict[str, list[dict]]) -> dict:
    return context.expand(rows={}, by_opp={}, sources=sources,
                          source_signals={g: _signals(g, e) for g, e in sources.items()}, seed_groups={}, as_of=AS_OF)


def _deal(ctx: dict) -> dict:
    return next(s for s in ctx["subjects"].values() if "n4" in s["groups"])


def test_ai_annotation_dates_a_unique_signed_deal():
    ctx = expand(deal_sources())
    deal = _deal(ctx)
    assert deal["groups"] == ["n1", "n2", "n3", "n4"] and "crm" not in deal["groups"]
    assert deal["signature_date"] == "2026-05-16"
    assert [c["evidence_id"] for c in deal["corroboration"]] == ["crm:0"]
    signed = [s for s in deal["signals"] if s["signal_type"] == "reported_signature"]
    assert signed and all(s["effective_date"] == "2026-05-16" for s in signed)
    annotation = [s for s in signed if s["details"].get("ai_annotation")]
    assert len(annotation) == 1 and annotation[0]["signal_confidence"] == "low"
    value = deal["valuation"]
    assert value["kind"] == "recognized_signed_acv" and value["recognized"] is True
    assert value["amount_usd"] == "649600" and value["signature_date"] == "2026-05-16"


def test_ai_annotation_does_not_date_an_ambiguous_amount():
    ctx = expand(deal_sources(second_signed_deal=True))
    deals = [s for s in ctx["subjects"].values() if {"n4", "m2"} & set(s["groups"])]
    assert len(deals) == 2
    for deal in deals:
        assert deal["corroboration"] == [] and deal["signature_date"] is None
        assert not any(s["details"].get("ai_annotation") for s in deal["signals"])
        assert not any(s.get("date_basis") == "corroborated_signature_date" for s in deal["signals"])


def test_ai_annotation_with_unmatched_amount_dates_nothing():
    ctx = expand(deal_sources(ai_note="[2026-05-18 sync — Claude] Signed 16 May: €640k/yr."))
    deal = _deal(ctx)
    assert deal["corroboration"] == [] and deal["signature_date"] is None


# ---------------------------------------------------------------------------
# Recognition rules.

def belief(value: str = "reported_signed", band: str = "high", contested: bool = False, verified: bool = False) -> dict:
    return {"states": {"commercial_status": {"value": value, "band": band, "contested": contested,
                                             "distinct_signal_types": 4, "verified": verified}}}


def mentions(*texts: str, day: str = "2026-05-16") -> list[dict]:
    return valuation.mentions([{"evidence_id": f"e{i}", "text": t, "date": day} for i, t in enumerate(texts)])


STATS = {"ratio_median": 5.0, "ratio_iqr": [4.0, 6.0], "ratio_n": 4,
         "rollout_median_usd": 800000.0, "rollout_iqr_usd": [500000.0, 1000000.0], "rollout_n": 6}


def value(b=None, *texts, stage="reported_signed_unverified", date="2026-05-16", stats=STATS):
    return valuation.value_subject(b or belief(), stage, mentions(*texts), stats, date, AS_OF)


def test_recognition_requires_confident_uncontested_signature_with_stated_annual_amount():
    v = value(None, "SIGNED. €580k/yr, 2-yr term")
    assert v["kind"] == "recognized_signed_acv" and v["recognized"] is True
    assert v["amount_usd"] == "649600" and v["currency"] == "EUR" and v["local_amount"] == 580000
    assert v["evidence_ids"] == ["e0"] and len(v["reasons"]) >= 3 and v["documentary_verified"] is False
    verified = value(belief("verified_signed", "very_high", verified=True), "SIGNED. €580k/yr")
    assert verified["recognized"] is True and verified["documentary_verified"] is True


@pytest.mark.parametrize("b,texts", [
    (belief(contested=True), ("SIGNED. €580k/yr, 2-yr term",)),
    (belief(band="medium"), ("SIGNED. €580k/yr, 2-yr term",)),
    (belief("terms_negotiation"), ("SIGNED. €580k/yr, 2-yr term",)),
    (belief(), ("SIGNED. €580k, 2-yr term",)),
    (belief(), ("SIGNED. €580k/yr, 2-yr term", "SIGNED. €620k/yr, 3-yr term")),
    (belief(), ("Contract NOT signed yet, €580k/yr proposed",)),
    (belief(), ("[2026-05-18 sync — Claude] Signed 16 May: €580k/yr.",)),
], ids=["contested", "medium_band", "not_signed_state", "no_annual_period", "ambiguous_amount", "negated",
        "ai_annotation_only"])
def test_recognition_refused(b, texts):
    v = value(b, *texts)
    assert v["kind"] != "recognized_signed_acv" and not v.get("recognized")


@pytest.mark.parametrize("day", ["2025-12-31", "2027-04-01", "2026-09-20", None])
def test_recognition_refused_outside_the_window(day):
    v = value(None, "SIGNED. €580k/yr, 2-yr term", date=day)
    assert v["kind"] == "recognized_signed_acv" and v["recognized"] is False
    totals = valuation.totals({"x": v}, "0")
    assert totals["recognized_signed_acv_usd"] == "0" and totals["recognized_deal_count"] == 0


# ---------------------------------------------------------------------------
# Estimates.

def test_estimate_from_stated_rollout_value():
    v = value(belief("pricing_discussed", "medium"), "rollout maybe €770k/yr if it works", stage="pilot_committed")
    assert v["kind"] == "estimate" and v["basis"] == "stated_rollout_value" and v["band"] == "low"
    assert v["amount_usd"] == "860000" and v["range_usd"] == ["650000", "950000"]
    assert v["weighted_usd"] == "300000" and v["evidence_ids"] == ["e0"] and v["reasons"]
    firm = value(belief("pricing_discussed", "medium"), "ACV discussed €770k/yr", stage="commercial_process")
    assert firm["band"] == "medium"


def test_estimate_from_pilot_fee_times_corpus_ratio():
    v = value(belief("unknown", None), "Budget: pilot ~€115k", stage="pilot_committed")
    assert v["basis"] == "pilot_fee_times_corpus_ratio" and v["band"] == "low"
    assert v["amount_usd"] == "640000" and v["range_usd"] == ["520000", "770000"]
    low, high = (Decimal(x) for x in v["range_usd"])
    assert low <= Decimal(v["amount_usd"]) <= high


def test_estimate_from_corpus_median_and_unknown():
    v = value(belief("unknown", None), stage="early")
    assert v["basis"] == "corpus_median_rollout" and v["amount_usd"] == "800000"
    assert v["range_usd"] == ["500000", "1000000"] and v["evidence_ids"] == []
    for stage in ("unknown", "lost"):
        assert value(belief("unknown", None), stage=stage)["kind"] == "unknown"
    assert value(belief("unknown", None), "Budget: pilot ~€115k", stage="early",
                 stats={**STATS, "ratio_median": None})["basis"] == "corpus_median_rollout"


def test_corpus_stats_learn_rollout_and_ratio():
    subjects = [mentions("Budget: pilot ~$100k", "rollout maybe $500k/yr if it works"),
                mentions("Budget: pilot ~$200k", "ACV discussed $800k/yr"),
                mentions("[2026-05-18 sync — Claude] Signed 16 May: $900k/yr.")]
    stats = valuation.corpus_stats(subjects)
    assert stats["ratio_n"] == 2 and stats["ratio_median"] == 4.5
    assert stats["rollout_n"] == 2 and stats["rollout_median_usd"] == 650000.0


def test_totals_dedupe_estimates_sharing_evidence():
    stated = value(belief("pricing_discussed", "medium"), "ACV discussed €770k/yr", stage="commercial_process")
    same_evidence = value(belief("pricing_discussed", "medium"), "ACV discussed €770k/yr", stage="pilot_committed")
    median_a = value(belief("unknown", None), stage="early")
    median_b = value(belief("unknown", None), stage="early")
    recognized = value(None, "SIGNED. €580k/yr")
    vals = {"opp-b": same_evidence, "opp-a": stated, "m1": median_a, "m2": median_b, "r": recognized}
    totals = valuation.totals(vals, "0")
    assert totals["estimated_open_pipeline_usd"] == str(Decimal(stated["amount_usd"]) + 1600000)
    assert totals["estimate_count_by_basis"] == {"stated_rollout_value": 1, "pilot_fee_times_corpus_ratio": 0,
                                                 "corpus_median_rollout": 2}
    # The first subject in key order is kept, so totals do not depend on insertion order.
    assert totals["weighted_pipeline_usd"] == str(Decimal(stated["weighted_usd"]) + 2 * Decimal(median_a["weighted_usd"]))
    assert valuation.totals(dict(reversed(list(vals.items()))), "0") == totals
    assert totals["recognized_signed_acv_usd"] == "649600" and totals["recognized_deal_count"] == 1
    assert totals["documentary_verified_usd"] == "0"


# ---------------------------------------------------------------------------
# Shipped demo, end to end.

def _demo(name: str):
    return json.loads((ROOT / "demo" / f"{name}.json").read_text(encoding="utf-8"))["data"]


def test_demo_recognises_exactly_one_signed_deal():
    beliefs, overview = _demo("belief_states"), _demo("overview")
    evidence = {e["evidence_id"] for e in _demo("evidence_summaries")}
    subjects = [*beliefs["opportunities"].values(), *beliefs["reconstructed_opportunities"].values()]
    recognized = [s for s in subjects if (s["valuation"] or {}).get("recognized")]
    assert len(recognized) == 1
    deal = recognized[0]
    v = deal["valuation"]
    assert v["kind"] == "recognized_signed_acv" and v["amount_usd"] == "649600"
    assert v["signature_date"] == "2026-05-16" and v["reasons"] and v["evidence_ids"]
    assert set(v["evidence_ids"]) <= evidence
    assert deal["status"] == "inferred_from_context" and len(deal["groups"]) >= 2 and deal["links"]
    totals = beliefs["overview"]["valuation"]
    assert totals["recognized_signed_acv_usd"] == "649600" and totals["recognized_deal_count"] == 1
    assert totals["documentary_verified_usd"] == overview["verified_signed_acv_usd"] == "0"
    assert Decimal(totals["estimated_open_pipeline_usd"]) > 0
    low, high = (Decimal(x) for x in totals["estimated_open_pipeline_range_usd"])
    assert low <= Decimal(totals["estimated_open_pipeline_usd"]) <= high
    assert Decimal(totals["weighted_pipeline_usd"]) > 0 and sum(totals["estimate_count_by_basis"].values()) > 0
    assert beliefs["overview"]["value_buckets"]["verified_actual_usd"] == "0"
    # The contract validator accepts the demo's new sections and every cited evidence ID resolves.
    _validate_context(beliefs, overview)
    assert _belief_evidence_ids(beliefs) <= evidence


def test_presentation_build_without_sources_has_no_context_sections():
    result = presentation.build(opportunities=[], signals=[], business_as_of=AS_OF)
    assert result["reconstructed_opportunities"] == {} and "valuation" not in result["overview"]
