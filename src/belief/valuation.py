"""Reasoned valuation: recognised signed ACV and contextual estimates.

Soft-to-hard evidence: excess verification makes the tracker useless, so a
signature is recognised when the belief layer supports it with high confidence
and the amount, currency and annual period are stated in the evidence. The
stricter documentary gate is still reported separately.

Where no number is stated, a value is estimated from context and every estimate
carries its basis, range and confidence band. Nothing here is a calibrated
probability.
"""
from __future__ import annotations

from decimal import Decimal
import re
import statistics
from typing import Any

from src.settings import goal_window

from .ontology import band_rank
from .reconstruction import money_mentions

VERSION = "valuation_1.0.0"
GOAL_START, GOAL_END = goal_window()
# Heuristic likelihood weights by inferred stage (documented, not calibrated).
STAGE_WEIGHT = {"lost": 0.0, "unknown": 0.05, "early": 0.1, "pilot_committed": 0.35, "pilot_active_or_completed": 0.5,
                "commercial_process": 0.7, "reported_signed_unverified": 0.85, "verified_signed": 1.0}
CONDITIONAL = re.compile(r"\bif\b|\bmaybe\b|\bpotential|\bcould\b|\bmight\b", re.I)
SIGNED = re.compile(r"\bsigned\b", re.I)


def _fx():
    from src.models.quantitative import FX
    return FX


def usd(amount: float, currency: str) -> Decimal | None:
    rate = _fx().get(currency)
    return None if rate is None else (Decimal(str(amount)) * rate).quantize(Decimal("1"))


def mentions(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Money mentions with modality and signature context, each tied to its evidence."""
    out = []
    for e in evidence:
        text = e.get("text") or ""
        for clause in re.split(r"[;\n]|,(?!\d)", text):
            for m in money_mentions(clause):
                m.update(evidence_id=e["evidence_id"], date=e.get("date"),
                         conditional=bool(CONDITIONAL.search(clause)),
                         signed=bool(SIGNED.search(text)) and not re.search(r"\bnot signed\b|\bunsigned\b", text, re.I),
                         ai_annotation=m["ai_annotation"])
                out.append(m)
    return out


def corpus_stats(all_mentions: list[list[dict[str, Any]]]) -> dict[str, Any]:
    """Rollout/pilot ratio and rollout values learned from the whole corpus (per subject)."""
    ratios, rollouts = [], []
    for ms in all_mentions:
        pilots = [usd(m["amount"], m["currency"]) for m in ms if m["kind"] == "pilot" and not m["ai_annotation"]]
        annual = [usd(m["amount"], m["currency"]) for m in ms if m["annual"] and m["kind"] == "commercial" and not m["ai_annotation"]]
        pilots, annual = [x for x in pilots if x], [x for x in annual if x]
        if annual:
            rollouts.append(float(max(annual)))
        if pilots and annual:
            ratios.append(float(max(annual)) / float(max(pilots)))
    q = lambda xs, p: statistics.quantiles(xs, n=4)[p] if len(xs) >= 4 else (min(xs) if p == 0 else max(xs))
    return {"ratio_median": statistics.median(ratios) if ratios else None,
            "ratio_iqr": [q(ratios, 0), q(ratios, 2)] if ratios else None, "ratio_n": len(ratios),
            "rollout_median_usd": statistics.median(rollouts) if rollouts else None,
            "rollout_iqr_usd": [q(rollouts, 0), q(rollouts, 2)] if rollouts else None, "rollout_n": len(rollouts)}


def _round(x: float | Decimal) -> str:
    return str(int(round(float(x), -4)))


def value_subject(belief: dict[str, Any], stage: str, ms: list[dict[str, Any]], stats: dict[str, Any],
                  signature_date: str | None, as_of: str) -> dict[str, Any]:
    """Recognised signed ACV (if the reasoning supports it) or a contextual estimate."""
    commercial = belief["states"]["commercial_status"]
    real = [m for m in ms if not m["ai_annotation"]]
    signed_annual = [m for m in real if m["signed"] and m["annual"]]
    corroborating = [m for m in ms if m["ai_annotation"] and m["signed"] and m["annual"]]
    result: dict[str, Any] = {"version": VERSION, "stage": stage, "stage_weight": STAGE_WEIGHT.get(stage, 0.05)}
    if (commercial["value"] in {"reported_signed", "verified_signed"} and band_rank(commercial["band"]) >= band_rank("high")
            and not commercial["contested"] and signed_annual):
        amounts = {(m["amount"], m["currency"]) for m in signed_annual}
        if len(amounts) == 1:
            amount, currency = next(iter(amounts))
            value = usd(amount, currency)
            in_window = bool(signature_date and GOAL_START <= signature_date <= min(GOAL_END, as_of))
            reasons = [f"Signature reported in the source with {currency} {amount:,.0f} per year",
                       f"Commercial status inferred 'reported signed' with {commercial['band'].replace('_', ' ')} confidence "
                       f"from {commercial['distinct_signal_types']} independent signal types"]
            if corroborating:
                reasons.append("CRM annotation independently reports the same signed annual amount")
            reasons.append(f"Signature date {signature_date or 'unknown'} "
                           f"{'within' if in_window else 'outside'} the target window")
            result.update(kind="recognized_signed_acv", recognized=in_window and value is not None,
                          amount_usd=str(value) if value is not None else None, currency=currency, local_amount=amount,
                          signature_date=signature_date, reasons=reasons,
                          evidence_ids=sorted({m["evidence_id"] for m in signed_annual + corroborating}),
                          documentary_verified=commercial["value"] == "verified_signed" and commercial.get("verified", False),
                          rule="Recognised when commercial status is inferred 'reported signed' with high confidence, "
                               "uncontested, with one stated annual amount and currency and a signature date in the window.")
            return result
    stated = [m for m in real if m["annual"] and m["kind"] == "commercial"]
    pilots = [m for m in real if m["kind"] == "pilot"]
    if stage == "lost":
        # A lost deal is not open pipeline; its last stated value is kept for reference only.
        last = max(stated, key=lambda x: x["amount"]) if stated else None
        momentum = belief["states"].get("momentum") or {}
        band = (momentum.get("band") or "unstated").replace("_", " ")
        result.update(kind="unknown", amount_usd=None, closed_lost=True,
                      last_stated_value_usd=str(usd(last["amount"], last["currency"])) if last else None,
                      evidence_ids=sorted({e for x in momentum.get("supporting") or [] for e in x["evidence_ids"]}),
                      reasons=[f"Deal inferred lost ({band} confidence): not part of the open pipeline"] +
                              ([f"Last stated value {last['text']} kept for reference only"] if last else []))
        return result
    if stated:
        m = max(stated, key=lambda x: (not x["conditional"], x["amount"]))
        value = usd(m["amount"], m["currency"])
        low, high = float(value) * 0.75, float(value) * 1.1
        result.update(kind="estimate", basis="stated_rollout_value", amount_usd=_round(value),
                      range_usd=[_round(low), _round(high)], band="medium" if not m["conditional"] else "low",
                      evidence_ids=[m["evidence_id"]],
                      reasons=[f"Rollout value stated in the source ({m['text']}){' conditionally' if m['conditional'] else ''}",
                               "Range: -25% / +10% around the stated figure (negotiation discount heuristic)"])
    elif pilots and stats.get("ratio_median"):
        m = max(pilots, key=lambda x: x["amount"])
        fee = float(usd(m["amount"], m["currency"]) or 0)
        lo, hi = stats["ratio_iqr"]
        result.update(kind="estimate", basis="pilot_fee_times_corpus_ratio",
                      amount_usd=_round(fee * stats["ratio_median"]), range_usd=[_round(fee * lo), _round(fee * hi)],
                      band="low", evidence_ids=[m["evidence_id"]],
                      reasons=[f"Pilot fee {m['text']} × median rollout/pilot ratio {stats['ratio_median']:.1f} "
                               f"observed in {stats['ratio_n']} deals (IQR {lo:.1f}–{hi:.1f})"])
    elif stats.get("rollout_median_usd") and stage not in {"lost", "unknown"}:
        lo, hi = stats["rollout_iqr_usd"]
        result.update(kind="estimate", basis="corpus_median_rollout", amount_usd=_round(stats["rollout_median_usd"]),
                      range_usd=[_round(lo), _round(hi)], band="low", evidence_ids=[],
                      reasons=[f"No amount in the evidence; median stated rollout value across {stats['rollout_n']} deals"])
    else:
        result.update(kind="unknown", amount_usd=None, reasons=["No amount and no comparable context"])
        return result
    result["weighted_usd"] = _round(Decimal(result["amount_usd"]) * Decimal(str(result["stage_weight"])))
    result["rule"] = ("Estimate, not a commitment: stated value, else pilot fee × corpus ratio, else corpus median. "
                      "Weighted by a heuristic stage weight; not a calibrated probability.")
    return result


def totals(valuations: dict[str, dict[str, Any]], documentary_verified_usd: str | None) -> dict[str, Any]:
    recognized = [v for v in valuations.values() if v.get("kind") == "recognized_signed_acv" and v.get("recognized")]
    estimates, seen = [], set()
    for subject, v in sorted(valuations.items()):
        # Two subjects valued from the same stated evidence (e.g. alternative scopes) count once;
        # the first subject in key order is kept, so totals are reproducible from the published file.
        key = frozenset(v.get("evidence_ids") or []) or subject
        if v.get("kind") == "estimate" and key not in seen:
            seen.add(key)
            estimates.append(v)
    s = lambda xs: str(sum((Decimal(x) for x in xs), Decimal(0)))
    return {"recognized_signed_acv_usd": s(v["amount_usd"] for v in recognized),
            "recognized_deal_count": len(recognized),
            "documentary_verified_usd": documentary_verified_usd,
            "estimated_open_pipeline_usd": s(v["amount_usd"] for v in estimates),
            "estimated_open_pipeline_range_usd": [s(v["range_usd"][0] for v in estimates), s(v["range_usd"][1] for v in estimates)],
            "weighted_pipeline_usd": s(v["weighted_usd"] for v in estimates),
            "estimate_count_by_basis": {b: sum(v.get("basis") == b for v in estimates)
                                        for b in ("stated_rollout_value", "pilot_fee_times_corpus_ratio", "corpus_median_rollout")},
            "stage_weights": STAGE_WEIGHT,
            "semantics": "Recognised signed ACV counts signatures the belief layer supports with high confidence; the "
                         "documentary-verified figure is the stricter gate. Estimates and weights are heuristic."}
