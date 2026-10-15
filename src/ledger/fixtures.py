"""Deterministic synthetic audit fixtures. These are excerpts, not live API results."""
from __future__ import annotations

from decimal import Decimal

from .models import (Account, Alias, Claim, CommercialScope, CommercialValue, Conflict,
                     Event, Evidence, Meeting, OfferOrContract, Opportunity, SourceRef)
from .store import Ledger, stable_id


SEEN = "2026-09-27T00:00:00+03:00"  # repository audit copy, not proof of earlier knowledge
INGESTED = SEEN
AUDIT_VERSION = "audit_2026-09-13"
NOTION = "https://app.notion.com/p/"


def _note(ledger: Ledger, slug: str, excerpt: str, event_date: str | None,
          *, precision: str = "day", authorship: str = "seller_staff") -> Evidence:
    ref = SourceRef("notion_audit_fixture", "meeting_page", slug)
    content = excerpt
    digest = ledger.ingest_raw(ref, AUDIT_VERSION, content, SEEN, INGESTED)
    item = Evidence(evidence_id=stable_id("evidence", slug + ":0"), source_ref=ref,
                    source_url=NOTION + slug, source_version=AUDIT_VERSION,
                    source_hash=digest, field_path="Notes", start_offset=0,
                    end_offset=len(excerpt), verbatim_excerpt=excerpt,
                    authorship=authorship, assertion_type="firsthand_report",
                    business_event_date=event_date, documented_at=None,
                    source_first_seen_at=SEEN, ingested_at=INGESTED,
                    date_precision=precision, derivation_rule="audit_excerpt_v1",
                    independence_group_id="meeting:" + slug)
    ledger.add_evidence(item)
    return item


def _entity(ledger: Ledger, name: str, source_id: str | None = None) -> Account:
    refs = (SourceRef("airtable_audit_fixture", "company", source_id),) if source_id else ()
    item = Account(id=stable_id("account", name), canonical_name=name,
                   source_refs=refs, created_in_ledger_at=INGESTED,
                   resolution_status="provisional")
    ledger.add_entity(item)
    return item


def _scope_opportunity(ledger: Ledger, account: Account, code: str,
                       boundary: str, evidence: Evidence, *, status: str = "provisional") -> tuple[CommercialScope, Opportunity]:
    key = account.canonical_name + ":" + code
    scope = CommercialScope(id=stable_id("scope_version", key + ":1"),
                            scope_id=stable_id("scope", key), account_id=account.id,
                            product_use_case=code, boundary_text=boundary,
                            created_in_ledger_at=INGESTED, resolution_status=status)
    ledger.add_entity(scope)
    opp = Opportunity(id=stable_id("opportunity", key), account_id=account.id,
                      use_case_code=code, use_case_description=boundary,
                      commercial_scope_id=scope.scope_id, scope_version=1,
                      opportunity_group_id=stable_id("group", key),
                      origin_evidence_id=evidence.evidence_id,
                      created_in_ledger_at=INGESTED, resolution_status=status)
    ledger.add_entity(opp)
    return scope, opp


def _meeting(ledger: Ledger, evidence: Evidence, opp: Opportunity | None) -> Meeting:
    item = Meeting(id=stable_id("meeting", evidence.source_ref.native_id),
                   source_ref=evidence.source_ref,
                   business_meeting_date=evidence.business_event_date,
                   recorded_at=None, evidence_ids=(evidence.evidence_id,),
                   linked_opportunity_ids=(opp.id,) if opp else (),
                   created_in_ledger_at=INGESTED,
                   resolution_status="provisional" if opp else "ambiguous")
    ledger.add_entity(item)
    return item


def _event(ledger: Ledger, evidence: Evidence, account: Account | None,
           opp: Opportunity | None, kind: str, *, contract: str | None = None,
           details: dict | None = None, verification: str = "unverified") -> Event:
    item = Event(event_id=stable_id("event", evidence.evidence_id + ":" + kind),
                 event_type=kind, account_id=account.id if account else None,
                 unresolved_entity_ref=None if account else evidence.source_ref.native_id,
                 opportunity_id=opp.id if opp else None,
                 scope_id=opp.commercial_scope_id if opp else None,
                 contract_kind=contract, event_date=evidence.business_event_date,
                 date_precision=evidence.date_precision if evidence.business_event_date else "date_unknown",
                 recorded_at=evidence.documented_at, first_seen_at=evidence.source_first_seen_at,
                 evidence_ids=(evidence.evidence_id,), verification=verification,
                 details=details or {})
    ledger.add_event(item)
    return item


def _value(ledger: Ledger, evidence: Evidence, opp: Opportunity, amount: str,
           currency: str, kind: str, status: str, unit: str, *,
           offer_id: str | None = None, replaces: str | None = None,
           scenario: str | None = None, version: int = 1, term: int | None = None) -> CommercialValue:
    item = CommercialValue(value_id=stable_id("value", evidence.evidence_id + ":" + kind),
                           opportunity_id=opp.id, offer_or_contract_id=offer_id,
                           scope_id=opp.commercial_scope_id, scope_version=version,
                           amount_decimal=Decimal(amount), currency_ISO=currency,
                           value_type=kind, status=status, unit=unit,
                           term_months=term, date_observed=evidence.business_event_date,
                           source_evidence_ids=(evidence.evidence_id,),
                           recorded_at=evidence.documented_at,
                           first_seen_at=evidence.source_first_seen_at,
                           replaces_value_id=replaces, scenario_group_id=scenario)
    ledger.add_value(item)
    return item


def load_audit_fixtures(ledger: Ledger) -> dict[str, dict[str, str]]:
    """Load eight audit cases idempotently and return their canonical IDs.

    No fixture is represented as a verified commercial contract. Source first-seen
    is the audit-copy date, while documented_at remains unknown.
    """
    ids: dict[str, dict[str, str]] = {}

    # Westra: pilot and later commercial unsigned report, plus a separate CRM stage claim.
    a = _entity(ledger, "Westra Trading", "recspxjeYxXU3CK6l")
    e = _note(ledger, "867275a3be2382bf9d3d017640f07ff5", "Pilot signed: €135k, 10 weeks", "2026-08-18")
    scope, opp = _scope_opportunity(ledger, a, "inventory_optimisation", "shadow-mode planning on 500 SKUs", e)
    ids["Westra"] = {"account": a.id, "opportunity": opp.id}
    _meeting(ledger, e, opp)
    pilot = OfferOrContract(id=stable_id("contract", "westra:pilot"), opportunity_id=opp.id,
                            contract_kind="pilot", scope_id=scope.scope_id,
                            status="reported_signed", created_in_ledger_at=INGESTED)
    ledger.add_entity(pilot)
    _event(ledger, e, a, opp, "pilot_signed", contract="pilot", details={"pilot_contract_id": pilot.id})
    _value(ledger, e, opp, "135000", "EUR", "pilot_fee", "signed_reported", "once", offer_id=pilot.id)
    e2 = _note(ledger, "622275a3be2383f98c5301c75d72b221",
               "Contract NOT signed yet - still with their procurement/legal", "2026-09-11")
    _meeting(ledger, e2, opp)
    c2 = Claim(claim_id=stable_id("claim", "westra:commercial_unsigned"), subject_id=opp.id,
               predicate="commercial_contract_signed", polarity="negative", contract_kind="commercial",
               scope_id=scope.scope_id, valid_from="2026-09-11", valid_to="2026-09-11",
               evidence_ids=(e2.evidence_id,))
    ledger.add_claim(c2)
    crm_ref = SourceRef("airtable_audit_fixture", "deal_stage", "recNF3RTjL7QRNloa")
    crm_text = "Commercial deployment"
    digest = ledger.ingest_raw(crm_ref, AUDIT_VERSION, crm_text, SEEN, INGESTED)
    crm_ev = Evidence(evidence_id=stable_id("evidence", "westra:stage"), source_ref=crm_ref,
                      source_version=AUDIT_VERSION, source_hash=digest, field_path="Stage",
                      start_offset=0, end_offset=len(crm_text), verbatim_excerpt=crm_text,
                      authorship="seller_staff", assertion_type="crm_snapshot",
                      business_event_date=None, documented_at=None,
                      source_first_seen_at=SEEN, ingested_at=INGESTED,
                      date_precision="snapshot_only", derivation_rule="audit_excerpt_v1")
    ledger.add_evidence(crm_ev)
    stage_claim = Claim(claim_id=stable_id("claim", "westra:crm_stage"), subject_id=opp.id,
                        predicate="crm_current_stage", object_value=crm_text,
                        evidence_ids=(crm_ev.evidence_id,))
    ledger.add_claim(stage_claim)
    ledger.add_conflict(Conflict(conflict_id=stable_id("conflict", "westra:stage_exception"),
                                 claim_ids=(c2.claim_id, stage_claim.claim_id),
                                 issue="CRM commercial deployment stage versus explicit unsigned commercial contract",
                                 severity="review"))

    # Coldharbour: source note has no structured Date; its date and year are body-inferred.
    a = _entity(ledger, "Coldharbour Pharma", "recIGgZF0EJepGDd0")
    e = _note(ledger, "09b275a3be238224aeb7813f30635247",
              "(call on 16/05)\n- SIGNED. €580k/yr, 2-yr term\n- Rollout one distribution centre first",
              "2026-05-16", precision="inferred_year_day_in_body")
    scope, opp = _scope_opportunity(ledger, a, "cold_chain_replenishment", "rollout one distribution centre first", e)
    ids["Coldharbour"] = {"account": a.id, "opportunity": opp.id}
    _meeting(ledger, e, opp)
    contract = OfferOrContract(id=stable_id("contract", "coldharbour:commercial"),
                               opportunity_id=opp.id, contract_kind="commercial", scope_id=scope.scope_id,
                               status="reported_signed", created_in_ledger_at=INGESTED)
    ledger.add_entity(contract)
    _event(ledger, e, a, opp, "commercial_signed", contract="commercial",
           details={"commercial_contract_id": contract.id})
    _value(ledger, e, opp, "580000", "EUR", "rollout_acv", "signed_reported", "per_year",
           offer_id=contract.id, term=24)
    e2 = _note(ledger, "dff275a3be238253ae57011349adc7a2",
               "(call on 13/05)\n- Results: 14% fewer expiry write-offs, no constraint violations\n- Steering committee: go to commercial",
               "2026-05-13", precision="inferred_year_day_in_body")
    _meeting(ledger, e2, opp)
    _event(ledger, e2, a, opp, "technical_milestone",
           details={"milestone_kind": "shadow_result", "result": "passed"})

    # Halvard conditional rollout values are scenarios of one opportunity.
    a = _entity(ledger, "Halvard Supermarkets", "recD7Z4zX4ghZJfgt")
    e = _note(ledger, "4b2275a3be23833e95ac8182ddeebc9c",
              "Budget: pilot ~$300k, rollout maybe $1.3M/yr if it works\n- Verbal yes to paid pilot, SOW being drafted",
              "2026-09-10")
    scope, opp = _scope_opportunity(ledger, a, "store_replenishment", "pilot dairy; commercial base network", e)
    ids["Halvard"] = {"account": a.id, "opportunity": opp.id}
    _meeting(ledger, e, opp)
    _event(ledger, e, a, opp, "pilot_verbal_yes", contract="pilot", details={"pilot_scope": "dairy category"})
    _event(ledger, e, a, opp, "sow_drafting", contract="pilot")
    group = stable_id("scenario", "halvard:region_rollout")
    _value(ledger, e, opp, "1300000", "USD", "rollout_acv", "tentative", "per_year", scenario=group)
    e2 = _note(ledger, "ab6275a3be2383a3bde1810caea42602",
               "They want to extend to a second region if pilot works\n- Ji-woo's number for full rollout ~€2.2M/yr",
               "2026-08-20")
    _meeting(ledger, e2, opp)
    _value(ledger, e2, opp, "2200000", "EUR", "rollout_acv", "tentative", "per_year", scenario=group)

    # Rhona: same buying decision, a revised scope and value, pilot fee separate.
    a = _entity(ledger, "Rhona Transport", "rec5l7sxgdr3MvgNy")
    e = _note(ledger, "f8f275a3be2382b7a2b6018e82c71734",
              "Budget: pilot ~€95k, rollout maybe €400k/yr if it works", "2026-04-02")
    scope, opp = _scope_opportunity(ledger, a, "inventory_optimisation", "shadow-mode planning rollout", e)
    ids["Rhona"] = {"account": a.id, "opportunity": opp.id}
    _meeting(ledger, e, opp)
    prior = _value(ledger, e, opp, "400000", "EUR", "rollout_acv", "tentative", "per_year")
    e2 = _note(ledger, "c4c275a3be238328b35b01ff71f53b1d",
               "Pilot signed: €95k, 16 weeks\n- Scope: 3-warehouse cluster", "2026-05-22")
    _meeting(ledger, e2, opp)
    pilot = OfferOrContract(id=stable_id("contract", "rhona:pilot"), opportunity_id=opp.id,
                            contract_kind="pilot", scope_id=scope.scope_id,
                            status="reported_signed", created_in_ledger_at=INGESTED)
    ledger.add_entity(pilot)
    _event(ledger, e2, a, opp, "pilot_signed", contract="pilot", details={"pilot_contract_id": pilot.id})
    _value(ledger, e2, opp, "95000", "EUR", "pilot_fee", "signed_reported", "once", offer_id=pilot.id)
    e3 = _note(ledger, "8e7275a3be238389bfdb8194b20208d6",
               "Jonas: budget pressure, rollout scoped down to shadow-mode planning on 500 SKUs\n- realistic full value now ~$220k/yr", "2026-07-10")
    revised = CommercialScope(id=stable_id("scope_version", "Rhona Transport:inventory_optimisation:2"),
                              scope_id=scope.scope_id, account_id=a.id, version=2,
                              product_use_case="inventory_optimisation", boundary_text="smaller rollout scope",
                              version_valid_from="2026-07-10", replaces_scope_version=1,
                              created_in_ledger_at=INGESTED, resolution_status="provisional")
    ledger.add_entity(revised)
    _meeting(ledger, e3, opp)
    _value(ledger, e3, opp, "220000", "USD", "rollout_acv", "tentative", "per_year",
           replaces=prior.value_id, version=2)

    # Osprey names stay separate accounts; dairy/bakery cannot be summed.
    semi = _entity(ledger, "Osprey Grocers Ltd.", "recsPTg3H5PtHbyM3")
    full = _entity(ledger, "Osprey Grocers", "rect6Ma6n13y7bkp5")
    ledger.add_identity_relation(semi.id, full.id, "possible_same_entity")
    e = _note(ledger, "98a275a3be23829f902e0107aa75370a",
              "Budget: pilot ~$185k, rollout maybe $960k/yr if it works", "2026-08-27")
    scope, opp = _scope_opportunity(ledger, full, "store_replenishment", "bakery or dairy; scope unresolved", e,
                                    status="ambiguous")
    ids["Osprey"] = {"account": full.id, "other_account": semi.id, "opportunity": opp.id}
    _meeting(ledger, e, opp)
    _value(ledger, e, opp, "960000", "USD", "rollout_acv", "tentative", "per_year")
    e2 = _note(ledger, "d76275a3be2382dea71581fd96445589",
               "Pilot scope: dairy category", "2026-09-09")
    alternate = CommercialScope(id=stable_id("scope_version", "Osprey Grocers:store_replenishment:2"),
                                scope_id=scope.scope_id, account_id=full.id, version=2,
                                product_use_case="store_replenishment", boundary_text="dairy category; relation to bakery unclear",
                                version_valid_from="2026-09-09", replaces_scope_version=1,
                                created_in_ledger_at=INGESTED, resolution_status="ambiguous")
    ledger.add_entity(alternate)
    _meeting(ledger, e2, opp)
    ledger.add_alias(Alias(alias_id=stable_id("alias", "osprey:name_candidate"), raw_string="Osprey Grocers Ltd.",
                           normalized_string="osprey grocers ltd.", entity_type="Account",
                           canonical_id=full.id, match_method="similar_name",
                           match_confidence="low", decision="candidate", decision_at=SEEN))

    # Kavala mentions a data kind, without a request or receipt.
    a = _entity(ledger, "Kavala Markets", "recXW8Ku6UScnu2mD")
    e = _note(ledger, "ae6275a3be2382a4a1648129ac854a97",
              "Data: POS sales history\n- Pilot scope: dairy category", "2026-08-30")
    scope, opp = _scope_opportunity(ledger, a, "store_replenishment", "dairy category", e)
    ids["Kavala"] = {"account": a.id, "opportunity": opp.id}
    _meeting(ledger, e, opp)
    ledger.add_claim(Claim(claim_id=stable_id("claim", "kavala:data_kind"), subject_id=opp.id,
                           predicate="data_kind", object_value="POS sales history",
                           evidence_ids=(e.evidence_id,)))

    # Nordahl explicit loss; future revisit is not revival.
    a = _entity(ledger, "Nordahl Distribution", "recTysPhTvhhpxZmT")
    e = _note(ledger, "edc275a3be2383b6890981b628e70aa6",
              "Lost - building in-house with their data science team\n- Juhani open to revisit next year",
              "2026-07-22")
    scope, opp = _scope_opportunity(ledger, a, "inventory_optimisation", "commercial deployment", e)
    ids["Nordahl"] = {"account": a.id, "opportunity": opp.id}
    _meeting(ledger, e, opp)
    _event(ledger, e, a, opp, "lost", details={"reason": "building in-house"})

    # Solvik seller chase plan does not imply buyer agreement or lost state.
    a = _entity(ledger, "Solvik Supermarkets", "reczEuZgFu7jy4ThU")
    e = _note(ledger, "fd1275a3be2382388a160158f54b4502",
              "still waiting on data access, no reply to last 2 emails\n- chase in 2 weeks",
              "2026-07-22")
    scope, opp = _scope_opportunity(ledger, a, "store_replenishment", "commercial deployment", e)
    ids["Solvik"] = {"account": a.id, "opportunity": opp.id}
    _meeting(ledger, e, opp)
    _event(ledger, e, a, opp, "stalled", details={"reason": "no reply", "seller_plan": "chase in 2 weeks"})
    return ids
