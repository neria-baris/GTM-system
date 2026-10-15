"""Atomic commercial signals: construction, modality normalisation and derivation.

A signal is one observation about one opportunity (or one unlinked source),
anchored to exact evidence. Signals never carry verification; the only
`formal_signature_verified` signals come from the existing documentary gate.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable

from src.ledger.store import stable_id

from .ontology import (BANDS, CONTRACT_KINDS, DERIVED_TYPES, METHODS, MODALITIES, OBSERVATIONS,
                       PLANNED_COUNTERPART, POLARITIES, SIGNAL_TYPES, SPECULATIVE_COUNTERPART, VERSION,
                       shift_band)

# Discussion-level types: a planned or conditional statement still shows the
# topic was raised, so these keep their type at one band lower confidence.
DISCUSSION_TYPES = frozenset({"pricing_discussed", "budget_discussed", "pilot_scope_discussed",
                              "customer_interest", "procurement_mentioned", "data_requested",
                              "commercial_terms_discussed", "blocker_identified", "budget_blocker",
                              "technical_blocker", "legal_blocker"})
RISK_TYPES = frozenset({"blocker_identified", "budget_blocker", "technical_blocker", "legal_blocker",
                        "loss_of_momentum", "no_response", "explicit_rejection", "project_paused"})
# Model or CRM annotations that predict rather than report (never customer facts).
AI_ANNOTATION = re.compile(r"\[[^\]]*\bsync\b[^\]]*(?:Claude|GPT|AI)\b[^\]]*\]|\bconversion to deployment\b|"
                           r"\bchance of signing\b|\bprobability\b|\binternal prediction\b|"
                           r"\bdecision expected\b|% pilot intent\b", re.I)
TARGET_STATEMENT = re.compile(r"\b(?:target|goal|quota|objective)\b|\bACV\)? signed in commercial deployments by\b", re.I)


class SignalError(ValueError):
    pass


def _band(value: str | None, default: str = "medium") -> str:
    return value if value in BANDS else default


def make_signal(signal_type: str, *, evidence_ids: Iterable[str], method: str, id_seed: str,
                effective_date: str | None = None, date_basis: str | None = None,
                modality: str = "asserted", polarity: str = "positive", observation: str = "observed",
                confidence: str = "medium", contract_kind: str | None = None,
                opportunity_id: str | None = None, account_id: str | None = None,
                subject_ref: str | None = None, evidence_availability: list[dict] | None = None,
                details: dict | None = None, sensor_readings: list[dict] | None = None,
                source_candidate_id: str | None = None, contradicts: Iterable[str] = ()) -> dict[str, Any]:
    """Build a validated, modality-normalised signal payload (JSON-serialisable)."""
    evidence_ids = sorted(set(evidence_ids))
    signal = {
        "signal_id": stable_id("atomic_signal", id_seed), "signal_type": signal_type,
        "opportunity_id": opportunity_id, "account_id": account_id,
        "subject_ref": subject_ref or (f"opportunity:{opportunity_id}" if opportunity_id else None),
        "effective_date": effective_date[:10] if effective_date else None,
        "date_basis": date_basis or ("source_explicit_date" if effective_date else "date_unknown"),
        "evidence_ids": evidence_ids, "evidence_availability": evidence_availability or [],
        "extraction_method": method, "polarity": polarity, "modality": modality,
        "observation": observation, "signal_confidence": _band(confidence),
        "contract_kind": contract_kind if contract_kind in CONTRACT_KINDS else None,
        "details": dict(details or {}), "sensor_readings": list(sensor_readings or []),
        "contradicts": sorted(set(contradicts)), "source_candidate_id": source_candidate_id,
        "ontology_version": VERSION,
    }
    return validate_signal(normalise(signal))


def normalise(signal: dict[str, Any]) -> dict[str, Any]:
    """Planning is not execution; conditions are not commitments; negation opposes."""
    s = dict(signal)
    s["details"] = dict(s.get("details") or {})
    kind, modality = s["signal_type"], s["modality"]
    if s["details"].get("seller_plan"):
        s["details"]["inert_reason"] = "seller_plan_not_customer_action"
        return s
    if modality == "negated" and kind not in RISK_TYPES:
        s["polarity"] = "negative"
    elif modality == "planned" and kind not in DISCUSSION_TYPES:
        if kind in PLANNED_COUNTERPART:
            s["details"].setdefault("retyped_from", kind)
            s["signal_type"] = PLANNED_COUNTERPART[kind]
        else:
            s["details"]["inert_reason"] = "planned_statement_not_execution"
    elif modality in {"conditional", "hypothetical"} and kind not in DISCUSSION_TYPES:
        if kind in SPECULATIVE_COUNTERPART:
            s["details"].setdefault("retyped_from", kind)
            s["signal_type"] = SPECULATIVE_COUNTERPART[kind]
            s["signal_confidence"] = shift_band(s["signal_confidence"], -1)
        else:
            s["details"]["inert_reason"] = f"{modality}_statement_not_fact"
    elif modality in {"planned", "conditional", "hypothetical"}:
        # Topic was raised, but only as a plan or possibility.
        s["signal_confidence"] = shift_band(s["signal_confidence"], -1)
        s["details"]["indicative"] = True
    elif modality == "unclear":
        s["signal_confidence"] = "low"
    return s


def validate_signal(s: dict[str, Any]) -> dict[str, Any]:
    if s["signal_type"] not in SIGNAL_TYPES:
        raise SignalError(f"Signal type outside ontology: {s['signal_type']}")
    if s["signal_type"] in DERIVED_TYPES and s["extraction_method"] != "cadence_rule":
        raise SignalError("Derived signals are produced by the engine only")
    if s["extraction_method"] not in METHODS or s["modality"] not in MODALITIES:
        raise SignalError("Invalid signal method or modality")
    if s["polarity"] not in POLARITIES or s["observation"] not in OBSERVATIONS:
        raise SignalError("Invalid signal polarity or observation")
    if not s["evidence_ids"]:
        raise SignalError("Signal requires exact evidence")
    if (s["signal_type"] == "formal_signature_verified") != (s["extraction_method"] == "verification_gate"):
        raise SignalError("Formal verification signals come only from the documentary gate")
    if not s["opportunity_id"] and not s["subject_ref"]:
        raise SignalError("Signal needs an opportunity or a source-scoped subject")
    return s


# ---------------------------------------------------------------------------
# Deterministic language sensor. Mechanical cues only: explicit wording,
# amounts and modality markers. In live runs Luna is the semantic extractor and
# this sensor corroborates or downgrades; the offline demo uses it directly.

CLAUSE_SPLIT = re.compile(r"[;\n]+|\.(?!\d)|(?<!\d)\.|\s[-–—]\s|(?<!\d),|,(?!\d)")
SELLER_PLAN = re.compile(r"^\s*next\s*:", re.I)
CONDITIONAL = re.compile(r"\bif\b|\bunless\b|\bprovided that\b|\bassuming\b|\bsubject to\b|\bdepending on\b|"
                         r"\bonce\b.{0,40}\b(?:works?|succeeds?|proven|passes)\b", re.I)
HYPOTHETICAL = re.compile(r"\b(?:would|could|might|maybe|perhaps|potential(?:ly)?|possibl[ey]|hypothetical(?:ly)?)\b|"
                          r"(?<!\d )\bmay\b(?! \d)", re.I)
PLANNED = re.compile(r"\bplan(?:ned|s)?\b|\bplanning\b|\bwill\b|\bto be\b|\bgoing to\b|\bscheduled\b|\bupcoming\b|"
                     r"\bnext (?:week|month|quarter|year)\b|\bexpected\b|\btargeting\b|\baim(?:s|ing)? to\b|"
                     r"\bintend(?:s|ed)? to\b|^\s*next\s*:", re.I)
NEGATED = re.compile(r"\bnot\b|\bno\b(?! (?:\w+ )?(?:violations?|issues?|problems?|incidents?|regressions?)\b)|\bnever\b|\bwithout\b|n't\b|\byet to\b|\bstill waiting\b|\bwaiting (?:on|for)\b|"
                     r"\bpending\b", re.I)
COMPLETED = re.compile(r"\bsince\b|\bheld\b|\bcompleted\b|\bdone\b|\bwas\b|\bwere\b|\bhad\b|\blast (?:week|month)\b", re.I)
PILOT_CUE = re.compile(r"\bpilot\b|\bSOW\b|\bPoC\b|\bproof of concept\b|\btrial\b", re.I)
COMMERCIAL_CUE = re.compile(r"\brollout\b|\broll out\b|\bcommercial\b|\bdeployment\b|/yr\b|\bper year\b|\bannual\b|"
                            r"\bACV\b|\b\d+-yr\b|\byear term\b", re.I)
MONEY = re.compile(r"[$€£]\s*\d|\b\d+(?:[.,]\d+)?\s*[kKmM]?\s*(?:USD|EUR|GBP)\b")

# (signal_type, pattern, observation, confidence, modality_sensitive)
PATTERNS: tuple[tuple[str, re.Pattern, str, str, bool], ...] = tuple(
    (t, re.compile(p, re.I), o, c, m) for t, p, o, c, m in (
        ("explicit_rejection", r"^\s*(?:closed[- ]?lost|lost)\b|^\s*closed\s*(?:[-–—:]|$)|\bclosed[- ]lost\b|\brejected\b|\bdeclined\b|"
                               r"\bsaid no\b|\bnot moving forward\b|\bwon't proceed\b|\bchose (?:another|a competitor)\b", "observed", "high", False),
        ("project_paused", r"\b(?:project|pilot|initiative|programme|program)\b.{0,25}\b(?:paused|on hold|postponed|suspended|"
                           r"deferred|put on ice)\b|\b(?:paused|on hold|postponed|put on ice)\b", "observed", "high", False),
        ("budget_blocker", r"\bbudget\b.{0,25}\b(?:not approved|frozen|freeze|cut|on hold|rejected|pulled|pressure|denied)\b|"
                           r"\bno budget\b|\b(?:frozen|freeze)\b.{0,15}\bbudget\b", "observed", "high", False),
        ("legal_blocker", r"\b(?:security|legal|procurement|compliance)\b.{0,40}\b(?:blocked|blocking|rejected|refused|stuck)\b|"
                          r"\bblocked\b.{0,30}\b(?:security|legal|procurement)\b", "observed", "high", False),
        ("technical_blocker", r"\b(?:integration|performance|latency|accuracy|data access)\b.{0,30}\b(?:blocked|issue|problem|failing|"
                              r"concern)\b|\bwaiting on data access\b|\bdata access\b.{0,15}\bblocked\b", "observed", "medium", False),
        ("blocker_identified", r"\bblock(?:ed|er|ers)\b|\bpushback\b|\bsceptical\b|\bskeptical\b|\bobjection\b", "observed", "medium", False),
        ("blocker_resolved", r"\b(?:blocker|issue|concern)s?\b.{0,20}\b(?:resolved|cleared|removed)\b|\bunblocked\b|"
                             r"\bsecurity approved\b|\bapproved access\b", "observed", "high", True),
        ("no_response", r"\bno (?:reply|response|answer)\b|\b(?:hasn't|has not|didn't|did not) (?:replied|respond|reply|answer)|"
                        r"\bunresponsive\b|\bghost(?:ed|ing)\b", "observed", "high", False),
        ("loss_of_momentum", r"\b(?:went|gone|going) (?:quiet|dark|cold)\b|\bnot urgent\b|\blow priority\b|\bdeprioriti[sz]ed\b|"
                             r"\bslipp(?:ed|ing)\b|\bpushed (?:back|out)\b|\bback burner\b|\bnot a priority\b|"
                             r"\bfollow-up not booked\b", "inferred_from_language", "medium", False),
        ("revived", r"\bre-?engaged\b|\brevived\b|\bback on (?:track|the table)\b|\bresum(?:ed|ing)\b|\brestarted\b", "observed", "medium", True),
        ("reported_signature", r"\bsigned\b|\bsignature\b|\bexecuted (?:the )?(?:contract|agreement|SOW)\b", "observed", "high", True),
        ("verbal_commitment", r"\bverbal(?:ly)? (?:yes|agreement|commit\w*)\b|\bagreed to (?:a |the )?(?:paid )?(?:pilot|rollout|deployment)\b|"
                              r"\bgreen ?light\b|\bgo ahead\b|\bgo to commercial\b|\bcommitted to\b", "observed", "high", True),
        ("budget_confirmed", r"\bbudget\b.{0,15}\b(?:approved|confirmed|secured|allocated|signed off)\b|"
                             r"\b(?:approved|secured)\b.{0,10}\bbudget\b|\bPO (?:issued|raised|received)\b", "observed", "high", True),
        ("budget_discussed", r"\bbudget\b", "observed", "medium", True),
        ("commercial_terms_agreed", r"\bterms (?:agreed|accepted|finali[sz]ed)\b|\bagreed (?:on )?(?:the )?(?:terms|pricing|price)\b|"
                                    r"\bhandshake\b", "observed", "high", True),
        ("commercial_terms_discussed", r"\bpricing not (?:yet )?agreed\b|\bterms not (?:yet )?agreed\b", "observed", "high", False),
        ("commercial_terms_discussed", r"\b(?:commercial|rollout) (?:terms|proposal|offer|negotiation|pricing)\b|\bproposal sent\b|"
                                       r"\bterms (?:in discussion|discussed|under negotiation)\b|\bnegotiat\w*\b|\bACV discussed\b",
                                       "observed", "medium", True),
        ("pricing_discussed", r"\bpric(?:e|ing)\b|\bquote[ds]?\b|\bfee\b", "observed", "medium", True),
        ("procurement_started", r"\b(?:procurement|purchasing|vendor onboarding)\b.{0,25}\b(?:started|underway|in progress|reviewing|review)\b|"
                                r"\bwith (?:their |the )?(?:procurement|purchasing)\b|\bsent to procurement\b|\bvendor (?:form|registration)\b",
                                "observed", "high", True),
        ("procurement_mentioned", r"\bprocurement\b|\bpurchasing\b|\bbudget committee\b|\bvendor onboarding\b", "observed", "medium", True),
        ("legal_involved", r"\blegal\b|\bMSA\b|\bNDA\b|\bcontract review\b|\bredlines?\b", "observed", "medium", True),
        ("security_review_started", r"\bsecurity (?:review|questionnaire|assessment|audit)\b|\binfosec\b|\bIT security\b|\bDPA\b",
                                    "observed", "medium", True),
        ("pilot_completed", r"\bpilot (?:completed|finished|concluded|wrapped up|ended)\b|\bfinal (?:pilot )?results\b", "observed", "high", True),
        ("kickoff_completed", r"\bkick[- ]?off (?:held|done|completed|happened|took place)\b|\bkicked off\b|"
                              r"\bpilot (?:started|launched|began|kicked off)\b|\bpilot live\b|\bgo-live\b|\bwent live\b", "observed", "high", True),
        ("kickoff_scheduled", r"\bkick[- ]?off\b|\bpilot (?:planned|scheduled|to start|starts?)\b|\bpilot start(?:ing)? (?:date|on|in)\b",
                              "observed", "medium", True),
        ("pilot_work_underway", r"\b(?:pilot|shadow[- ]mode)\b.{0,30}\b(?:running|underway|in progress|ongoing)\b|"
                                r"\bmid-?pilot\b|\bweek \d+ of (?:the )?pilot\b|\bpilot sync\b", "observed", "high", True),
        ("pilot_work_underway", r"^\s*(?:wk|week) \d+\s*$", "inferred_from_language", "medium", False),
        ("technical_result_positive", r"\bresults?\b.{0,40}\b(?:better|improv\w*|positive|promising|passed|success\w*|beat|exceed\w*)\b|"
                                      r"\b\d+(?:\.\d+)?% (?:better|improvement|reduction|faster|lower)\b|\bno constraint violations\b",
                                      "observed", "medium", True),
        ("data_received", r"\b(?:uploaded|shared|provided|delivered|sent|received)\b.{0,40}\b(?:data|logs|dataset|history|records)\b|"
                          r"\b(?:data|logs|dataset)\b.{0,30}\b(?:received|uploaded|delivered|shared|in hand|arrived)\b|"
                          r"\baccess granted\b", "observed", "high", True),
        ("data_requested", r"\b(?:requested|asked for|request(?:ing)?|need(?:s|ed)?|send us)\b.{0,20}\b(?:data|logs|access|dataset)\b|"
                           r"^\s*data\s*:", "observed", "medium", True),
        ("technical_owner_assigned", r"\b(?:technical|tech|engineering|project) (?:owner|lead|champion|point of contact)\b|"
                                     r"\bassigned (?:an? )?(?:engineer|owner|lead)\b", "observed", "high", True),
        ("customer_resources_allocated", r"\b(?:allocated|assigned|dedicated|committed) (?:\d+ )?(?:engineers?|FTEs?|team|resources|staff)\b|"
                                         r"\b(?:engineers?|team) (?:assigned|allocated|dedicated)\b", "observed", "high", True),
        ("pilot_scope_agreed", r"\bscope (?:agreed|signed off|confirmed|locked)\b|\bagreed (?:the )?scope\b|"
                               r"\bSOW (?:being )?(?:drafted|drafting|sent|in progress|under review)\b|^\s*success\s*=",
                               "inferred_from_language", "medium", True),
        ("pilot_scope_discussed", r"\bpilot scope\b|^\s*scope\s*:|\bscoping\b", "observed", "medium", True),
        ("senior_stakeholder_engaged", r"\b(?:CFO|CEO|CTO|COO|CIO|SVP|EVP|VP)\b|\bsteering committee\b|\bhead of\b|\bdirector\b",
                                       "inferred_from_language", "medium", True),
        ("positive_intent", r"\bkeen\b|\beager\b|\bexcited\b|\bstrong interest\b|\bwants? (?:a |an |to |it |the )|\bwould like to\b",
                            "inferred_from_language", "medium", True),
        ("customer_interest", r"\bcurious\b|\binterest(?:ed|ing)\b|\bintro(?:duction)?\b|\bmet \w+ at\b|\bpolite\b", "inferred_from_language", "low", True),
        ("meeting_held", r"\b(?:meeting|call|workshop|demo|deep dive|sync)\b.{0,15}\b(?:held|done|completed|took place)\b|"
                         r"\bmet with\b", "observed", "medium", True),
    ))
# A specific pattern pre-empts these generic ones inside the same clause.
SUBSUMES = {
    "explicit_rejection": {"loss_of_momentum", "blocker_identified", "customer_interest"},
    "budget_blocker": {"budget_discussed", "blocker_identified", "budget_confirmed"},
    "legal_blocker": {"blocker_identified", "legal_involved", "security_review_started"},
    "technical_blocker": {"blocker_identified", "data_requested"},
    "budget_confirmed": {"budget_discussed"},
    "procurement_started": {"procurement_mentioned"},
    "commercial_terms_agreed": {"commercial_terms_discussed", "pricing_discussed"},
    "commercial_terms_discussed": {"pricing_discussed"},
    "kickoff_completed": {"kickoff_scheduled"},
    "pilot_scope_agreed": {"pilot_scope_discussed"},
    "data_received": {"data_requested"},
    "blocker_resolved": {"blocker_identified"},
    "loss_of_momentum": {"customer_interest"},
    "no_response": {"data_requested", "technical_blocker"},
    "verbal_commitment": {"positive_intent"},
}


def contract_kind_of(text: str, context: str = "") -> str:
    for source in (text, context):
        pilot, commercial = bool(PILOT_CUE.search(source)), bool(COMMERCIAL_CUE.search(source))
        if pilot != commercial:
            return "pilot" if pilot else "commercial"
    return "unknown"


def modality_of(clause: str, span: tuple[int, int] | None = None) -> str:
    """Condition, speculation and plans scope the clause; negation must sit next to the cue."""
    if CONDITIONAL.search(clause):
        return "conditional"
    if HYPOTHETICAL.search(clause):
        return "hypothetical"
    start, end = span or (0, len(clause))
    if NEGATED.search(clause[max(0, start - 25):end + 8]):
        return "negated"
    if PLANNED.search(clause):
        return "planned"
    return "completed" if COMPLETED.search(clause) else "asserted"


def lexical_signals(text: str) -> list[dict[str, Any]]:
    """Return clause-level signal readings: type, modality, observation, confidence, kind, clause."""
    if not text or AI_ANNOTATION.search(text) or TARGET_STATEMENT.search(text):
        return []
    found: list[dict[str, Any]] = []
    # "Next: ..." records a seller's own plan, not a customer action.
    seller_plan = bool(SELLER_PLAN.search(text))
    for clause in (c.strip() for c in CLAUSE_SPLIT.split(text)):
        if not clause:
            continue
        hits = [(t, o, c, m, match) for t, p, o, c, m in PATTERNS if (match := p.search(clause))]
        blocked = {g for t, *_ in hits for g in SUBSUMES.get(t, ())}
        for kind, observation, confidence, sensitive, match in hits:
            if kind in blocked:
                continue
            modality = "planned" if seller_plan else modality_of(clause, match.span()) if sensitive else "asserted"
            found.append({"signal_type": kind, "modality": modality, "observation": observation,
                          "confidence": confidence, "contract_kind": contract_kind_of(clause, text), "clause": clause,
                          "details": {"seller_plan": True} if seller_plan else {}})
        if MONEY.search(clause) and not any(h[0] in {"pricing_discussed", "commercial_terms_discussed",
                                                       "commercial_terms_agreed"} for h in hits):
            found.append({"signal_type": "pricing_discussed", "modality": modality_of(clause), "observation": "observed",
                          "confidence": "high", "contract_kind": contract_kind_of(clause, text), "clause": clause,
                          "details": {}})
    unique = {}
    for item in found:
        unique.setdefault((item["signal_type"], item["modality"], item["contract_kind"]), item)
    return list(unique.values())


# ---------------------------------------------------------------------------
# Mapping existing canonical rows into atomic signals.

EVENT_SIGNALS: dict[str, tuple[tuple[str, str | None], ...]] = {
    "initial_encounter": (("meeting_held", None), ("customer_interest", None)),
    "follow_up_held": (("meeting_held", None),),
    "scoping_held": (("meeting_held", None), ("pilot_scope_discussed", None)),
    "data_requested": (("data_requested", None),),
    "data_received": (("data_received", None),),
    "pilot_verbal_yes": (("verbal_commitment", "pilot"),),
    "sow_drafting": (("pilot_scope_agreed", "pilot"),),
    "sow_sent": (("pilot_scope_agreed", "pilot"),),
    "pilot_signed": (("reported_signature", "pilot"),),
    "pilot_started": (("kickoff_completed", "pilot"),),
    "technical_milestone": (("pilot_work_underway", None),),
    "blocker_opened": (("blocker_identified", None),),
    "blocker_resolved": (("blocker_resolved", None),),
    "procurement_legal_started": (("procurement_started", None),),
    "commercial_proposal_sent": (("commercial_terms_discussed", "commercial"),),
    "commercial_signed": (("reported_signature", "commercial"),),
    "lost": (("explicit_rejection", None),),
    "stalled": (("loss_of_momentum", None),),
    "revived": (("revived", None),),
}
SEMANTIC_POLARITY_TO_MODALITY = {"asserted": "asserted", "negated": "negated", "hypothetical": "hypothetical",
                                 "future_plan": "planned", "conditional": "conditional", "unclear": "unclear"}
BLOCKER_KIND = {"budget": "budget_blocker", "technical": "technical_blocker", "data": "technical_blocker",
                "legal": "legal_blocker", "security": "legal_blocker", "procurement": "legal_blocker"}


def availability(ledger, evidence_ids: Iterable[str]) -> list[dict[str, Any]]:
    out = []
    for eid in sorted(set(evidence_ids)):
        ev = ledger.evidence(eid) or {}
        out.append({"evidence_id": eid, "documented_at": ev.get("documented_at"),
                    "source_first_seen_at": ev.get("source_first_seen_at"),
                    "business_event_date": ev.get("business_event_date"),
                    "independence_group": ev.get("independence_group_id") or (ev.get("source_ref") or {}).get("native_id"),
                    "authorship": ev.get("authorship")})
    return out


def _excerpt(ledger, evidence_ids: Iterable[str]) -> str:
    texts = []
    for eid in evidence_ids:
        ev = ledger.evidence(eid) or {}
        text = ev.get("verbatim_excerpt") or ""
        if (ev.get("derivation_rule") or "").startswith("c_full_corpus_"):
            try:
                text = json.loads('"' + text + '"')
            except json.JSONDecodeError:
                pass
        texts.append(text)
    return "\n".join(texts)


def _method_for_event(event: dict[str, Any]) -> str:
    version = event.get("extraction_version") or ""
    return "luna_semantic" if version.startswith("semantic_canonical") else "ledger_event"


def from_event(ledger, event: dict[str, Any]) -> list[dict[str, Any]]:
    """A canonical (asserted, observed) event becomes one or more signals."""
    if event.get("polarity") != "positive" or not event.get("opportunity_id"):
        return []
    out = []
    details = event.get("details") or {}
    method = _method_for_event(event)
    for kind, contract_kind in EVENT_SIGNALS.get(event["event_type"], ()):
        if event["event_type"] == "technical_milestone" and details.get("result") == "passed":
            kind = "technical_result_positive"
        if kind == "blocker_identified":
            kind = BLOCKER_KIND.get(str(details.get("blocker_kind") or "").lower(), kind)
        if event["event_type"] == "procurement_legal_started" and details.get("domain") == "legal":
            kind = "legal_involved"
        verified = (event["event_type"] == "commercial_signed" and event.get("verification") == "document_verified"
                    and (ledger.entity(details.get("commercial_contract_id") or "") or {}).get("status") == "verified_signed")
        ids = list(event["evidence_ids"])
        common = dict(evidence_ids=ids, effective_date=event.get("event_date"),
                      date_basis=event.get("date_precision"), opportunity_id=event["opportunity_id"],
                      account_id=event.get("account_id"), evidence_availability=availability(ledger, ids),
                      contract_kind=contract_kind or event.get("contract_kind"),
                      details={"event_id": event["event_id"], "event_type": event["event_type"]})
        out.append(make_signal(kind, method=method, id_seed=f"event:{event['event_id']}:{kind}",
                               confidence="medium" if method == "luna_semantic" else "high", **common))
        if verified:
            out.append(make_signal("formal_signature_verified", method="verification_gate",
                                   id_seed=f"event:{event['event_id']}:verified", confidence="very_high", **common))
    return out


def from_value(ledger, value: dict[str, Any]) -> list[dict[str, Any]]:
    if not value.get("opportunity_id") or value.get("status") == "retracted":
        return []
    kind = "pilot" if value.get("value_type") == "pilot_fee" else "commercial" \
        if value.get("value_type") in {"rollout_acv", "tcv", "expansion_increment_acv"} else "unknown"
    ids = list(value["source_evidence_ids"])
    signal_type = "commercial_terms_discussed" if value.get("status") == "proposed" and kind == "commercial" else "pricing_discussed"
    return [make_signal(signal_type, evidence_ids=ids, method="deterministic_rule",
                        id_seed=f"value:{value['value_id']}", effective_date=value.get("date_observed"),
                        opportunity_id=value["opportunity_id"], evidence_availability=availability(ledger, ids),
                        contract_kind=kind, confidence="high",
                        details={"value_id": value["value_id"], "value_type": value.get("value_type"),
                                 "value_status": value.get("status")})]


SIGNAL_FAMILY_DEFAULTS = {
    "customer_commitment": "positive_intent", "next_step_strength": "positive_intent",
    "buyer_involvement": "senior_stakeholder_engaged", "procurement_legal": "procurement_mentioned",
    "blocker": "blocker_identified", "data_access": "data_requested", "technical_progress": "pilot_work_underway",
    "pilot_progress": "pilot_scope_discussed", "commercial_negotiation": "commercial_terms_discussed",
    "momentum": "loss_of_momentum",
}
FAMILY_VALUE_SIGNALS = {
    ("data_access", "provided_or_access_granted"): "data_received", ("data_access", "requested"): "data_requested",
    ("data_access", "access_blocked"): "technical_blocker", ("procurement_legal", "in_progress"): "procurement_started",
    ("procurement_legal", "required"): "procurement_mentioned", ("procurement_legal", "rejected"): "legal_blocker",
    ("blocker", "open"): "blocker_identified", ("blocker", "resolved"): "blocker_resolved",
    ("next_step_strength", "owner_and_date"): "kickoff_scheduled", ("next_step_strength", "completed"): "meeting_held",
    ("buyer_involvement", "economic_buyer_identified_and_met"): "senior_stakeholder_engaged",
    ("buyer_involvement", "senior_stakeholder_met"): "senior_stakeholder_engaged",
    ("technical_progress", "shadow_result_positive"): "technical_result_positive",
    ("momentum", "stalled_explicit"): "loss_of_momentum",
}


def from_family_reading(family: str, value: str, quote: str) -> list[dict[str, Any]]:
    """Map a Luna/legacy signal family + free value to atomic readings (language + table)."""
    readings = [r for r in lexical_signals(" ".join(x for x in (value, quote) if x))]
    if readings:
        return readings
    kind = FAMILY_VALUE_SIGNALS.get((family, value)) or SIGNAL_FAMILY_DEFAULTS.get(family)
    if not kind:
        return []
    return [{"signal_type": kind, "modality": modality_of(quote or value), "observation": "inferred_from_language",
             "confidence": "medium", "contract_kind": contract_kind_of(quote or value), "clause": quote or value}]


def from_claim(ledger, claim: dict[str, Any]) -> list[dict[str, Any]]:
    """Map opportunity-subject claims (semantic and legacy signal claims)."""
    subject = claim.get("subject_id") or ""
    opp = ledger.entity(subject)
    if not opp or "use_case_code" not in opp or claim.get("status") not in {"observed", "inferred", "contradicted"}:
        return []
    predicate = claim.get("predicate") or ""
    ids = list(claim["evidence_ids"])
    if (ids and all((ledger.evidence(i) or {}).get("authorship") == "ai_generated" for i in ids)):
        return []
    common = dict(evidence_ids=ids, effective_date=claim.get("valid_from"),
                  date_basis="claim_valid_from" if claim.get("valid_from") else None,
                  opportunity_id=subject, account_id=opp.get("account_id"),
                  evidence_availability=availability(ledger, ids))
    readings: list[dict[str, Any]] = []
    method = "deterministic_rule"
    if predicate.startswith("signal:"):
        readings = from_family_reading(predicate[7:], claim.get("object_value") or "", _excerpt(ledger, ids))
        method = "ledger_event" if (claim.get("resolution_reason") or "").startswith("fixture") else "deterministic_rule"
    elif predicate == "commercial_contract_signed" and claim.get("polarity") == "negative":
        readings = [{"signal_type": "reported_signature", "modality": "negated", "observation": "observed",
                     "confidence": "high", "contract_kind": "commercial", "clause": _excerpt(ledger, ids)}]
    elif predicate.startswith("semantic:"):
        method = "luna_semantic"
        try:
            payload = json.loads(claim.get("object_value") or "{}")
        except json.JSONDecodeError:
            return []
        readings = semantic_readings(predicate[9:], payload)
    out = []
    for n, r in enumerate(readings):
        out.append(make_signal(r["signal_type"], method=method, id_seed=f"claim:{claim['claim_id']}:{n}:{r['signal_type']}",
                               modality=r["modality"], observation=r["observation"], confidence=r["confidence"],
                               contract_kind=r.get("contract_kind") or claim.get("contract_kind"),
                               details={"claim_id": claim["claim_id"], "predicate": predicate, "clause": r.get("clause")},
                               **common))
    return out


def semantic_readings(collection: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Readings from one validated Luna object. Luna's modality is kept unless a
    deterministic guard finds a weaker one (guards can only downgrade)."""
    quote = payload.get("quote") or ""
    guard = modality_of(quote)
    if collection == "atomic_signals":
        kind = payload.get("signal_type")
        if kind not in SIGNAL_TYPES:
            return []
        modality = _weaker(payload.get("modality") or "unclear", guard)
        return [{"signal_type": kind, "modality": modality,
                 "observation": "observed" if modality in {"asserted", "completed"} and payload.get("actor") != "seller"
                 else "inferred_from_language",
                 "confidence": "medium", "contract_kind": payload.get("contract_kind"), "clause": quote,
                 # A seller plan is not a customer action.
                 "details": {"seller_plan": True} if payload.get("actor") == "seller" and modality == "planned" else {}}]
    if collection == "events":
        modality = _weaker(SEMANTIC_POLARITY_TO_MODALITY.get(payload.get("polarity"), "unclear"), guard)
        return [{"signal_type": kind, "modality": modality, "observation": "observed", "confidence": "medium",
                 "contract_kind": contract_kind or payload.get("contract_kind"), "clause": quote}
                for kind, contract_kind in EVENT_SIGNALS.get(payload.get("event_type"), ())]
    if collection == "signals":
        polarity = SEMANTIC_POLARITY_TO_MODALITY.get(payload.get("polarity"), "unclear")
        return [{**r, "modality": _weaker(polarity, r["modality"])}
                for r in from_family_reading(payload.get("family") or "", payload.get("value") or "", quote)]
    if collection == "commercial_values" and payload.get("status") not in {"retracted", "unknown"}:
        kind = "pilot" if payload.get("value_type") == "pilot_fee" else contract_kind_of(quote)
        return [{"signal_type": "pricing_discussed", "modality": guard if guard != "negated" else "asserted",
                 "observation": "observed", "confidence": "high", "contract_kind": kind, "clause": quote}]
    return []


MODALITY_STRENGTH = {"asserted": 6, "completed": 6, "planned": 4, "conditional": 3, "hypothetical": 2,
                     "unclear": 1, "negated": 0}


def _weaker(model_modality: str, guard_modality: str) -> str:
    """Deterministic guards may only weaken a model's modality, never strengthen it."""
    if guard_modality in {"asserted", "completed"}:
        return model_modality
    if model_modality == "negated":
        return "negated"
    return min((model_modality, guard_modality), key=lambda m: MODALITY_STRENGTH.get(m, 1))


def _table_exists(ledger, name: str) -> bool:
    return bool(ledger.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def collect_signals(ledger) -> list[dict[str, Any]]:
    """Persisted atomic signals plus signals derived from canonical events, values and claims."""
    by_id: dict[str, dict[str, Any]] = {}
    if _table_exists(ledger, "atomic_signal"):
        for (payload,) in ledger.db.execute("SELECT payload FROM atomic_signal ORDER BY signal_id"):
            s = json.loads(payload)
            by_id[s["signal_id"]] = s
    # A claim or event already persisted as signals (e.g. with Jev readings) is not derived twice.
    covered = {v for s in by_id.values() for k in ("claim_id", "event_id") if (v := s["details"].get(k))}
    rows = lambda table: [json.loads(r[0]) for r in ledger.db.execute(f"SELECT payload FROM {table}")]
    derived: list[dict[str, Any]] = []
    for event in rows("event"):
        derived.extend(from_event(ledger, event))
    for value in rows("commercial_value"):
        derived.extend(from_value(ledger, value))
    for claim in rows("claim"):
        derived.extend(from_claim(ledger, claim))
    for s in derived:
        keys = {s["details"].get("claim_id"), s["details"].get("event_id")}
        if s["extraction_method"] == "verification_gate" or not keys & covered:
            by_id.setdefault(s["signal_id"], s)
    return sorted(by_id.values(), key=lambda s: (s["effective_date"] or "9999", s["signal_id"]))
