"""Contextual expansion: reconstruct deals, link evidence, date undated statements, value subjects.

Inputs are source groups (one note or CRM record each) with their exact
evidence texts and their own source-scoped signals. Output augments displayed
opportunities with context-linked evidence and publishes reconstructed deals
that the conservative identity rules could not link. Every link, inferred date
and valuation carries its reasons.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.ledger.store import stable_id

from . import engine, metrics, valuation
from .reconstruction import AI_ANNOTATION, money_mentions, reconstruct, signature_dates

VERSION = "context_1.0.0"


def _copy(signal: dict[str, Any], subject: str, opportunity_id: str | None, link: dict[str, Any],
          date: str | None, date_basis: str | None) -> dict[str, Any]:
    s = dict(signal)
    s["details"] = {**(signal.get("details") or {}), "linked_by_context": link}
    s["signal_id"] = stable_id("context_signal", f"{signal['signal_id']}:{subject}")
    s["opportunity_id"] = opportunity_id
    s["subject_ref"] = subject if not opportunity_id else f"opportunity:{opportunity_id}"
    if not s.get("effective_date") and date:
        s["effective_date"], s["date_basis"] = date, date_basis
    return s


def _label(cluster: dict[str, Any], names: set[str]) -> str:
    topics = [a.split(":", 1)[1] for a in cluster["anchors"] if a.startswith("bigram:")][:3]
    amount = next((a.split(":", 1)[1] for a in cluster["anchors"] if a.startswith("amount:") and a.endswith("/yr")), None)
    if cluster.get("accounts"):
        return f"{' / '.join(cluster['accounts'])} · reconstructed deal"
    who = f"contact {', '.join(sorted(n.title() for n in names))}" if names else "account unresolved"
    return f"Reconstructed deal · {' / '.join(topics) or 'context'}{' · ' + amount if amount else ''} · {who}"


def expand(*, rows: dict[str, dict[str, Any]], by_opp: dict[str, list[dict[str, Any]]],
           sources: dict[str, list[dict[str, Any]]], source_signals: dict[str, list[dict[str, Any]]],
           seed_groups: dict[str, set[str]], as_of: str,
           group_accounts: dict[str, str] | None = None) -> dict[str, Any]:
    recon = reconstruct({g: [e["text"] for e in evs] for g, evs in sources.items()}, seed_groups,
                        accounts=group_accounts)
    clusters = recon["clusters"]
    dated = {g: sorted(e["date"] for e in evs if e.get("date")) for g, evs in sources.items()}
    # Corroborating CRM statements ("Signed 16 May: EUR580k/yr") date a deal's signature when the
    # amount uniquely matches one reconstructed deal's signed amount.
    signed_amounts = defaultdict(set)
    for c in clusters:
        for g in c["groups"]:
            for e in sources[g]:
                if "signed" in e["text"].lower() and not AI_ANNOTATION.search(e["text"]):
                    for m in money_mentions(e["text"]):
                        if m["annual"]:
                            signed_amounts[(m["amount"], m["currency"])].add(c["cluster_id"])
    corroboration: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for g, evs in sources.items():
        for e in evs:
            if not AI_ANNOTATION.search(e["text"]):
                continue
            days = signature_dates(e["text"], e.get("date"))
            for m in money_mentions(e["text"]):
                owners = signed_amounts.get((m["amount"], m["currency"])) or set()
                if days and m["annual"] and len(owners) == 1:
                    corroboration[next(iter(owners))].append({"group": g, "evidence_id": e["evidence_id"],
                                                              "signature_date": days[0], "text": e["text"],
                                                              "amount": m["amount"], "currency": m["currency"]})
    expanded = {oid: list(sigs) for oid, sigs in by_opp.items()}
    subjects: dict[str, dict[str, Any]] = {}
    for c in clusters:
        groups = c["groups"]
        latest = max((d for g in groups for d in dated.get(g, []) if d <= as_of), default=None)
        corr = corroboration.get(c["cluster_id"], [])
        sig_date = min(x["signature_date"] for x in corr) if corr else None
        link = {"cluster_id": c["cluster_id"], "anchors": c["anchors"][:6],
                "links": [{"group": l["group"], "score": l["score"], "shared_anchors": l["shared_anchors"]} for l in c["links"]]}
        oid = c["opportunity_id"] if c["opportunity_id"] in rows else None
        subject = f"opportunity:{oid}" if oid else f"reconstructed:{c['cluster_id']}"
        added = []
        for g in groups:
            if oid and g in seed_groups.get(oid, set()):
                continue
            for s in source_signals.get(g, []):
                date, basis = (sig_date, "corroborated_signature_date") if s["signal_type"] == "reported_signature" and sig_date \
                    else (latest, "inferred_from_deal_sequence")
                added.append(_copy(s, subject, oid, {**link, "group": g}, date, basis))
        for x in corr:
            from .signals import make_signal
            added.append(make_signal("reported_signature", evidence_ids=[x["evidence_id"]], method="crm_field",
                                     id_seed=f"corroboration:{c['cluster_id']}:{x['evidence_id']}",
                                     effective_date=x["signature_date"], date_basis="explicit_in_crm_annotation",
                                     observation="inferred_from_language", confidence="low", contract_kind="commercial",
                                     opportunity_id=oid, subject_ref=subject,
                                     details={"ai_annotation": True, "corroborates": "signature date and amount",
                                              "linked_by_context": {**link, "group": x["group"]}}))
        if oid:
            expanded[oid].extend(added)
        else:
            names = set()
            for g in groups:
                for e in sources[g]:
                    from .reconstruction import anchors
                    names |= anchors([e["text"]])["names"]
            subjects[c["cluster_id"]] = {"cluster_id": c["cluster_id"], "label": _label(c, names), "groups": groups,
                                         "accounts": c.get("accounts", []),
                                         "links": link["links"], "anchors": c["anchors"], "signals": added,
                                         "signature_date": sig_date, "corroboration": corr}
    # Valuation for displayed opportunities and reconstructed deals.
    group_mentions = {g: valuation.mentions(evs) for g, evs in sources.items()}
    stats = valuation.corpus_stats(list(group_mentions.values()))
    cluster_of_opp = {c["opportunity_id"]: c for c in clusters if c["opportunity_id"] in rows}
    valuations, beliefs = {}, {}
    for oid in rows:
        groups = set(seed_groups.get(oid, set())) | set((cluster_of_opp.get(oid) or {}).get("groups", []))
        ms = [m for g in sorted(groups) for m in group_mentions.get(g, [])]
        belief = engine.infer(expanded[oid], as_of)
        beliefs[oid] = belief
        sig = _signature_date(expanded[oid])
        valuations[oid] = valuation.value_subject(belief, metrics.inferred_stage(belief), ms, stats, sig, as_of)
    for cid, sub in subjects.items():
        ms = [m for g in sub["groups"] for m in group_mentions.get(g, [])]
        # The corroborating CRM statement is cited by the valuation it dates.
        ms += valuation.mentions([{"evidence_id": x["evidence_id"], "text": x["text"], "date": None}
                                  for x in sub["corroboration"]])
        belief = engine.infer(sub["signals"], as_of)
        sub["belief"] = belief
        sub["valuation"] = valuation.value_subject(belief, metrics.inferred_stage(belief), ms, stats,
                                                   sub["signature_date"] or _signature_date(sub["signals"]), as_of)
    return {"version": VERSION, "reconstruction": {k: v for k, v in recon.items() if k != "clusters"},
            "expanded": expanded, "subjects": subjects, "valuations": valuations, "corpus_stats": stats,
            "clusters": clusters}


def _signature_date(signals: list[dict[str, Any]]) -> str | None:
    dates = [s["effective_date"] for s in signals if s["signal_type"] == "reported_signature" and s["polarity"] == "positive"
             and (s.get("contract_kind") in {"commercial", None, "unknown"}) and s.get("effective_date")
             and not (s.get("details") or {}).get("inert_reason")]
    return min(dates) if dates else None
