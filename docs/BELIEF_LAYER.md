# Belief-state layer: design

Status: implemented in release 1.2.0. Results, examples, validation and limitations are in
[section 10](#results).

## 1. Problem

The tracker was good at stating what is explicitly evidenced or formally verified, and poor at
answering the original question: *given everything observed so far, what is most likely
happening commercially, and why?* Three concrete causes in the 1.1.0 code:

1. Luna already extracted soft signals (`signals` collection), but they were stored as
   `semantic:signals` claims that no model read. The quantitative layer only consumed
   `signal:<family>` claims, which production never wrote.
2. Asserted events lacking typed details (`data_received`, `pilot_started`, `sow_sent`, …) were
   routed to human review (`required_event_details_not_extracted`) instead of being used.
3. Every uncertainty became a review item (377 in the frozen demo), whatever its decision impact.

## 2. Target data flow

```
Raw sources ─▶ Evidence extraction ─▶ Atomic signals ─▶ Belief state ─▶ Canonical commercial state ─▶ Quantitative model ─▶ Presentation
 (A2, immutable)  (C2: rules, Luna, Jev)  (ledger table)    (engine, per as-of     (ledger events/values/        (Models A–C + D)       (belief_states.json
                                                             date and time mode)     contracts — unchanged)                                 + existing files)
```

* Existing canonical persistence, evidence spans, hashes, validators and the Verified Actual gate
  are unchanged. The belief layer is additive.
* **Observed → Inferred → Verified** is a property of every displayed item:
  * *Observed*: an atomic signal anchored to an exact excerpt (`observation = observed`), or a
    language-level reading of one (`inferred_from_language`).
  * *Inferred*: a belief state computed from a combination of signals.
  * *Verified*: only the pre-existing documentary contract gate. No belief can set it.

## 3. Division of labour

| Component | Responsibility | Never does |
|---|---|---|
| Deterministic rules | Dates, currencies, amounts, IDs, CRM fields, meeting dates, cadence (recurring interaction), inactivity, modality guards (`if … works`, `maybe`, `next month`, negation) that can only *downgrade* a statement | Decide commercial state from one regex |
| Luna (`gpt-6-luna`) | Free-text extraction of candidate entities, events, values and **atomic signals** with modality and actor, each with an exact quote | Verify contracts, compute ACV, set state |
| Jev | Narrow **sensor** questions about one cited span: modality (current/planned/conditional/…), pilot activity (active vs planned), customer commitment, procurement started, real blocker | Determine the commercial state; one reading can move one signal by at most one confidence band |
| Belief engine | Combine signals over time into per-opportunity states with confidence bands and explanations | Touch Verified Actual, invent values |
| Existing gates | Contract verification, Verified Actual, identity/scope rules | — |

## 4. Atomic signal ontology (`src/belief/ontology.py`)

Signal record fields: `signal_id`, `signal_type`, `opportunity_id`, `account_id`,
`subject_ref` (source-scoped when unlinked), `effective_date`, `date_basis`, `evidence_ids`,
`evidence_availability` (documented/first-seen times per evidence, for no-hindsight evaluation),
`extraction_method`, `polarity`, `modality`, `observation`, `signal_confidence`,
`contract_kind`, `details`, `sensor_readings`, `contradicts`, `source_candidate_id`.

| Category | Signal types |
|---|---|
| Engagement | `customer_interest`, `meeting_held`, `senior_stakeholder_engaged`, *derived:* `recurring_interaction` |
| Commitment | `positive_intent`, `verbal_commitment` |
| Technical | `data_requested`, `data_received`, `technical_owner_assigned`, `customer_resources_allocated`, `technical_result_positive` |
| Pilot | `pilot_scope_discussed`, `pilot_scope_agreed`, `kickoff_scheduled`, `kickoff_completed`, `pilot_work_underway`, `pilot_completed` |
| Commercial | `pricing_discussed`, `budget_discussed`, `budget_confirmed`, `commercial_terms_discussed`, `commercial_terms_agreed`, `reported_signature`, `formal_signature_verified` (verification gate only) |
| Procurement | `procurement_mentioned`, `procurement_started`, `legal_involved`, `security_review_started` |
| Risk | `blocker_identified`, `budget_blocker`, `technical_blocker`, `legal_blocker`, `blocker_resolved`, `loss_of_momentum`, `no_response`, `explicit_rejection`, `project_paused`, `revived` |

Each type has a **persistence class**: `persistent` (a pilot that started did start),
`decaying` (interest, meetings, cadence, silence) or `until_resolved` (blockers, pauses).
Modality: `asserted`, `completed`, `planned`, `conditional`, `hypothetical`, `negated`,
`unclear`. A planned execution signal is re-typed to its planning counterpart
(`kickoff_completed` + planned ⇒ `kickoff_scheduled`); conditional and hypothetical statements
never support an achieved state.

## 5. Belief-state ontology

| Dimension | Values (ordered where meaningful) | Temporal behaviour |
|---|---|---|
| `engagement` | unknown · light · active · strong | decays with recency |
| `buyer_commitment` | unknown · interest · intent · verbal_commitment · committed · *withdrawn* | persistent, defeated by later rejection / budget block / pause |
| `technical_commitment` | unknown · exploring · resourced · engaged | persistent, opposed by later technical blockers / silence |
| `pilot_status` | unknown · discussed · planned · committed · active · completed · *paused* · *cancelled* | persistent; reversals win only when later |
| `procurement_status` | unknown · anticipated · underway | persistent |
| `commercial_status` | unknown · pricing_discussed · terms_negotiation · terms_agreed · reported_signed · verified_signed | `verified_signed` mirrors the documentary gate only |
| `blocker_state` | none_known · possible · active · resolved (+ kinds) | until resolved |
| `momentum` | unknown · strong · steady · weakening · stalled · lost | recency and inactivity driven |

## 6. Confidence: two separate concepts

*Signal confidence* — how sure we are that a span expresses signal X — is a band set by the
extraction method (explicit deterministic pattern: high; Luna: medium; corroborated by a rule
or a unanimous Jev sensor: +1 band; contradicted by a Jev sensor: −1 band).

*State confidence* — how sure we are that the opportunity is currently in state Y — is computed
by the engine from **heuristic support points** (documented, not a probability):

```
contribution = strength(type → value) × signal_confidence_factor × recency_factor × independence_factor
strength:     1 weak · 2 moderate · 3 strong · 4 decisive (per state value, in the rule table)
confidence:   low 0.5 · medium 0.75 · high 1.0 · very_high 1.0
recency:      persistent 1.0; decaying 1.0 (≤30 d) · 0.6 (≤60 d) · 0.3 (≤120 d) · 0.1
independence: first signal of a type 1.0, further sources of the same type 0.5, 0.25 …
              (several spans in one note count once)
support S = Σ contributions; opposition O = Σ opposing contributions
              (opposition later than the latest support counts fully, earlier opposition × 0.3)
band(S − O):  very_high ≥ 9 with ≥ 3 distinct signal types and no opposition
              high ≥ 5.5 with ≥ 2 distinct types · medium ≥ 3 · low > 0
caps:         one distinct signal type → at most medium; O ≥ ½S → one band lower, `contested`;
              last supporting evidence older than 90 days for a current-state value → at most medium, `stale`
```

Several medium signals of different types therefore produce a stronger belief than any single
one, and contradictory or stale evidence lowers it. The engine also reports
`model_dependence` (share of support points coming from Luna/Jev) so a reader can see when a
belief rests mainly on model inference. Bands are interpretable labels, not calibrated
probabilities; calibration would need labelled historical outcomes (see limitations).

## 7. Temporal behaviour and hindsight

The engine is evaluated at an `as_of` date in one of the two existing modes:

* `retrospective`: signals whose effective date ≤ `as_of` (what we now know happened then);
* `historically_known`: additionally, at least one evidence item has `documented_at` and
  `source_first_seen_at` ≤ the knowledge cutoff (what could have been known then).

Derived signals (recurring interaction, inactivity) are recomputed at evaluation time from the
available signals only, so they cannot leak later evidence. Reversals (pause, rejection, budget
freeze) defeat earlier progression; later progression or `revived` defeats earlier reversals;
historical facts (pilot started) are retained in the explanation.

## 8. Quantitative and presentation changes

* `weekly_state` adds `model_d` (per-opportunity belief summary) and `belief_metrics`
  (operationally active pilots, likely committed, commercial process underway, likely stalled,
  momentum distribution, probable blockers). Models A–C, the proxy and Verified Actual are
  unchanged. Separate value buckets: verified actual · reported unverified · known value by
  inferred state · indicative (conditional) mentions · unknown.
* New presentation file `belief_states.json` (live and demo): per-opportunity current beliefs
  with explanations, observed signals, verified facts, unresolved contradictions, weekly belief
  snapshots in both modes, portfolio metrics, and review triage.
* Review triage keeps every item (auditability) but marks `decision_needed` only for contract
  verification, structure-changing identity ambiguity, materially conflicting values, important
  contradictions and genuinely ambiguous decision-relevant states. Coherent high-confidence soft
  evidence never creates review.

## 9. Files

New: `src/belief/{ontology,signals,engine,metrics,review_policy,jev_sensors,presentation}.py`,
`scripts/build_demo_beliefs.py`, `demo/belief_states.json`, `tests/belief/`, `packaging/`.
Extended: ledger (`atomic_signal` table, append-only), semantic schema/instructions
(`atomic_signals` collection), C2 extraction (Jev sensors), semantic integration (signal
persistence), canonical validation, quantitative model, read model, presentation contract and
validator, frontend.

<a id="results"></a>
## 10. Results

### What changed, per stage

| Stage | Change |
|---|---|
| C2 extraction | Luna schema `semantic_bridge_1.2.0` adds the closed `atomic_signals` collection (type, modality, actor, effective date, contract kind; exact quote). Jev sensor questions run on routed atomic signals; a failed sensor batch abstains and never forces review. |
| C canonical | `semantic_integration` persists atomic signals for every validated semantic object (all event polarities, signals, values, atomic signals) plus `meeting_held` for single-opportunity dated notes. Asserted events lacking typed details become `semantic_signal_only` instead of review. `validate_canonical` re-validates every signal and rejects any verification-gate signal in extraction-only production. |
| Quantitative | `weekly_state` adds `model_d` per opportunity and `belief_metrics`; every pre-existing number is byte-identical (tested with and without signals). |
| Read model / contract | New `belief_states.json` + SQLite tables `belief_state`, `weekly_belief`, `review_triage`, all reconciled by the contract validator (evidence ids, bands, values, verified flags, triage coverage, week list, historical-mode nulls). |
| Product | Opportunity detail shows **Observed → Inferred → Verified** columns with structured "why" explanations; opportunities table gains an inferred-state column; overview gains a separate "Inferred commercial state — not verified, not a forecast" row; review defaults to decision-needed items; weekly view gains an "Inferred state" change card. |

### Before / after on the demo snapshot

Full table: [belief_before_after.md](belief_before_after.md) (generated by `scripts/build_demo_beliefs.py`).
The frozen demo cannot re-run Luna/Jev and its canonical SQLite is not shipped, so the demo's
signals come from the deterministic language sensor over the frozen exact excerpts, the
published event timeline and published values. This is disclosed in the file provenance and in
the product's methodology page.

* **Review queue:** 350 items, previously all presented as actionable → **19 decision-needed**
  (all contract verification) and 331 retained as informational (221 unlinked annotations,
  95 extraction audit records, 9 unlinked value annotations, 6 single provisional scopes). No item is deleted.
* **Rhona Transport** (before: `signed_reported`, `stalled_by_rule`): *Pilot committed* from the
  reported pilot signature, success criteria and pilot fee; *Momentum stalled (high)* with the number
  of idle days; Verified Actual stays $0 and the reported signature stays unverified.
* **Quorra Supply** (before: all fields unknown): *Pilot discussed (medium)*, positive intent and
  pricing discussed; "rollout maybe €1M/yr if it works" is read as **conditional pricing only** — no
  rollout commitment.
* **Unlinked notes** (source-scoped, not published as opportunities): "Contract NOT signed yet
  – still with their procurement/legal" → terms in negotiation and procurement underway (high),
  reported signature *negated*; "Lost – security review blocked data leaving site" → lost plus an
  active legal/security blocker.
* **Verified Actual: $0 before and after.** The offline sensor sees only each displayed
  opportunity's own excerpts; the published demo belief file comes from the live run, which also
  links context across notes (see §12).

### Tests and validation

* Acceptance cases A–H: `tests/belief/test_belief_engine.py` (plus reversal/revival, inactivity
  and staleness, sensor bounds, dataset phrases, seller plans, momentum and gate rules).
* Extraction/integration: `tests/full_corpus/test_belief_integration.py`,
  `tests/full_corpus/test_semantic_bridge.py` (schema, post-validation, Jev sensor mocks,
  signal-only routing, forged-verification rejection).
* Read model/contract: `tests/read_model/test_belief_read_model.py` (additivity of Model D,
  Verified Actual unchanged, no hindsight in historical mode, 12 tampering cases).
* Presentation: `tests/presentation/test_presentation_app.py` (inferred never rendered as
  verified, decision-needed default, reproducible demo file, gate regressions) and the headless
  browser smoke.

### Limitations and calibration

* **No calibration.** Bands are ordinal heuristic support levels. Turning them into
  probabilities requires labelled historical outcomes (opportunities whose later state is known)
  and a calibration study per dimension; the dataset has neither.
* **Weights and thresholds are expert-set** (documented in `src/belief/ontology.py`). They should
  be reviewed against a labelled sample before being used for forecasting.
* **Historical knowledge.** Production evidence has no `documented_at`, so the
  historically-known belief view is empty, exactly like the existing historical view; the
  retrospective view is labelled as reconstruction.
* **Demo sensor.** The demo uses the deterministic language sensor, not Luna/Jev; live runs use
  Luna atomic signals with Jev sensor readings and use rules only for mechanical facts and
  modality guards.
* **Identity is unchanged.** The belief layer never links evidence to an opportunity that the
  conservative identity rules did not link; signals from unlinked notes stay source-scoped.
* **Buyer commitment** describes commitment to the current engagement (a signed paid pilot counts
  as committed); it is not a commercial-deployment forecast.
* Two Jev downgrades on one signal can lower it by two bands (each reading moves at most one).

<a id="reasoned"></a>
## 11. Release 1.3.0: reasoned recognition, reconstruction and estimates

**Policy change (product owner).** Excess verification is a failure mode for soft-to-hard evidence;
reasons and reproducibility are accepted where conclusive documents are absent. The documentary gate
is kept and reported, but it is no longer the headline.

| Mechanism | Rule (all in `src/belief/`) |
|---|---|
| Deal reconstruction (`reconstruction.py`) | Sources (notes, CRM records) link when they share ≥ 1 rare phrase/term (in ≤ 3 sources) plus a second rare anchor or an exact amount (in ≤ 8 sources); sentences repeated in ≥ 3 sources are templates and give no anchors; names alone never link; conflicting named contacts block a merge; seeded opportunities never merge; AI annotations never supply topic anchors. Every link stores its score and shared anchors. |
| Context linking and dating (`context.py`) | Linked notes add their signals to the displayed opportunity or form a reconstructed deal (labelled inferred, not canonical). Undated statements take the date of the latest dated note in the deal; a CRM statement "Signed 16 May: €580k/yr" dates a signature only if the amount matches exactly one deal's signed amount. |
| Reasoned recognition (`valuation.py`) | Counted when commercial status is inferred `reported_signed` with high/very-high confidence, uncontested, one stated annual amount and currency, and a signature date in 2026-01-01…2027-03-31 and ≤ as-of. A coherent chain (positive results, decision to go commercial, ACV discussed) corroborates the report. |
| Estimates (`valuation.py`) | Stated rollout value (range −25%/+10%), else pilot fee × corpus median rollout/pilot ratio (IQR range), else corpus median rollout value; band medium/low; weighted by a heuristic stage weight (early 0.1 … reported signed 0.85). Estimates sharing the same evidence count once. |

**Result on the bundled dataset.** One reconstructed deal (distribution centre / expiry write-offs, contact Juhani; five notes
linked through "distribution centre", "ERP with fixed reorder schedules", "seasonal vaccines", "expiry write-offs" and €580k/yr) reaches
*reported signed* with high confidence from five signal types; the CRM annotation dates the signature
2026-05-16. **Recognised signed ACV: €580,000/yr × 1.12 = $649,600.** Documentary-verified: $0.
Estimated open pipeline $11.9M (range $9.1–13.2M; 8 stated values, 3 pilot-fee ratios, 1 corpus median);
weighted $4.07M. Nine reconstructed deals are published with their own beliefs and valuations.

**Limits.** Reconstruction can still link two notes that share a stock phrase present in only two
sources; the stage weights, ratio method and ranges are heuristic and uncalibrated; the documentary
figure remains the conservative reference.

## 12. Live run on the sample sources (release 1.3.0)

Sources: Airtable API (66 companies, 187 contacts, 5 deals), Notion meeting notes from the workspace
export (111 notes, 107 dated, 24 typed; the integration had no shared pages), GPT-6 Luna with medium
reasoning, Jev sensors (K = 5). Ingestion reconciled exactly with the configured source baseline.

Two gaps found on the sample data, and the fixes:

1. **Linkage.** Luna linked only 3 opportunities; 598 of 605 signals were unlinked. Note titles carry the
   customer ("Coldharbour", "WT", "Rhona followup"), so reconstruction now resolves titles to CRM accounts
   conservatively (full company name; a company's first word only if no other company shares it;
   initials only if unique; a contact name only if exactly one contact has it) and treats the same
   account as one deal unless it has several canonical scopes; different accounts never link. 154 sources
   resolved; 21 deals reconstructed.
2. **Recall.** For "SIGNED. €580k/yr, 2-yr term" Luna emitted only a relation, not a signature. Explicit
   cues are mechanical, so the deterministic language sensor now complements Luna on every excerpt (same
   type in the same note counts once), and Luna's instructions name this case explicitly.

Result: Coldharbour Pharma is inferred *reported signed* with high confidence from five signal types
(reported signature, positive results, decision to go commercial, ACV discussed, CRM corroboration dating
the signature 2026-05-16): **recognised signed ACV $649,600**; documentary-verified $0. Across 23 deals
(2 canonical + 21 reconstructed): 1 operationally active pilot, 5 likely committed, 2 with a commercial
process underway, 14 likely stalled or lost, 13 with probable blockers. Estimated open pipeline $9.71M
(range $7.28–10.69M; deals inferred lost are excluded and keep their last stated value for reference
only), weighted $2.44M. Review: 19 of 350 items need a decision.
