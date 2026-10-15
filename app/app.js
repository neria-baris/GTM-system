/* Presentation only: all business state and aggregates are published by D. */
'use strict';
const RUNTIME = '../demo/';
const FILES = ['overview', 'opportunities', 'opportunity_details', 'weekly_snapshots', 'evidence_summaries', 'review_queue', 'belief_states'];
const DIMENSIONS = ['pilot_status','buyer_commitment','technical_commitment','procurement_status','commercial_status','blocker_state','momentum','engagement'];
const JOURNEY = ['encounter','follow_up','scoping','pilot_path','pilot_signed','pilot_execution','technical_milestone','commercial_negotiation','procurement_legal','commercial_signed'];
const GROUPS = ['Signature verification','Contract & pilot review','Account & entity','Opportunity & scope','Commercial value','Evidence & source','Other review'];
const LABELS = {
  pilot_path:'Pilot discussion / preparation', pilot_signed:'Pilot signed · reported', commercial_signed:'Commercial signature',
  signed_reported:'Signature reported · unverified', reported_signed_pending:'Reported signed · pending verification',
  stalled_by_rule:'Stalled · rule-based', new_opportunity:'First appears in dated population',
  ambiguous_scope_or_identity:'Value withheld: scope or identity unresolved', unknown:'Unknown',
  provisional_scope_requires_identity_review:'Provisional scope needs identity review',
  available:'Evidence available', pilot_committed:'Pilot commitment evidenced', encounter:'Initial encounter',
  pilot_execution:'Pilot execution', follow_up:'Follow-up', scoping:'Scoping',
  commercial_negotiation:'Commercial negotiation', procurement_legal:'Procurement / legal',
  belief_material_contradiction:'Inferred state is contested', belief_ambiguous_state:'Inferred state is ambiguous'
};
/* Labels for the belief layer. Inferred values never read as verified facts. */
const BELIEF_LABELS = {
  pilot_status:'Pilot status', buyer_commitment:'Buyer commitment', technical_commitment:'Technical commitment',
  procurement_status:'Procurement', commercial_status:'Commercial status', blocker_state:'Blockers', momentum:'Momentum', engagement:'Engagement',
  unknown:'Unknown', none_known:'None known', light:'Light', active:'Active', strong:'Strong', interest:'Interest', intent:'Positive intent',
  verbal_commitment:'Verbal commitment', committed:'Committed', withdrawn:'Withdrawn', exploring:'Exploring', resourced:'Resourced',
  engaged:'Engaged', discussed:'Discussed', planned:'Planned', completed:'Completed', paused:'Paused', cancelled:'Cancelled',
  anticipated:'Anticipated', underway:'Underway', pricing_discussed:'Pricing discussed', terms_negotiation:'Terms in negotiation',
  terms_agreed:'Terms agreed', reported_signed:'Signature reported · unverified', verified_signed:'Signature · documentary gate decides',
  possible:'Possible', resolved:'Resolved', steady:'Steady', weakening:'Weakening', stalled:'Stalled', lost:'Lost',
  early:'Early', pilot_committed:'Pilot committed', pilot_active_or_completed:'Pilot active or completed', commercial_process:'Commercial process',
  reported_signed_unverified:'Signature reported · unverified',
  low:'Low', medium:'Medium', high:'High', very_high:'Very high',
  asserted:'Asserted', negated:'Negated', conditional:'Conditional', hypothetical:'Hypothetical', unclear:'Unclear',
  deterministic_rule:'Deterministic rule', crm_field:'CRM field', ledger_event:'Ledger event', luna_semantic:'Luna extraction',
  jev_sensor:'Jev sensor', cadence_rule:'Cadence rule', verification_gate:'Documentary gate',
  observed:'Observed', inferred_from_language:'Language reading', derived_pattern:'Derived pattern',
  contract_verification:'Contract verification', identity_structure:'Identity changes structure', material_value_conflict:'Material value conflict',
  belief_material_contradiction:'Inferred state contested', belief_ambiguous_state:'Inferred state ambiguous',
  identity_single_scope:'Single provisional scope', extraction_quality_log:'Extraction audit record', used_as_soft_signal:'Used as a soft signal',
  unlinked_value_annotation:'Unlinked value annotation', unlinked_annotation:'Unlinked annotation', low_decision_impact:'Low decision impact'
};
function esc(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function label(value) { if (value == null || value === '') return 'Unknown'; return LABELS[value] || String(value).replace(/_/g,' ').replace(/^./,c=>c.toUpperCase()); }
function money(value) {
  if (value == null || value === '') return 'Unknown';
  if (!/^-?\d+(\.\d+)?$/.test(String(value))) return 'Unknown';
  return new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',minimumFractionDigits:0,maximumFractionDigits:2}).format(Number(value));
}
function date(value) { if (!value) return 'Date unknown'; return new Date(value.slice(0,10)+'T12:00:00Z').toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'}); }
function reviewGroup(row) {
  const r = row.reason;
  if (/commercial_signature|reported_signature/.test(r)) return GROUPS[0];
  if (/signature|contract_kind|high_impact/.test(r)) return GROUPS[1];
  if (/invented_account|unresolved_account|relation_needs/.test(r)) return GROUPS[2];
  if (/value_|amount_|currency/.test(r)) return GROUPS[4];
  if (/scope|identity/.test(r)) return GROUPS[3];
  if (/rejected_|details_not_extracted/.test(r)) return GROUPS[5];
  return GROUPS[6];
}
function reviewTitle(row) {
  const r = row.reason;
  if (reviewGroup(row) === GROUPS[0]) return 'Reported signature needs documentary verification';
  if (/pilot_signature/.test(r)) return 'Confirm whether the signature applies to a pilot';
  if (/span_crosses/.test(r)) return 'Proposed excerpt crosses source boundaries';
  if (/quote_absent/.test(r)) return 'Proposed excerpt was not found exactly';
  if (/invented_account/.test(r)) return 'Proposed account reference rejected';
  if (/unsupported_amount/.test(r)) return 'Amount or currency needs source support';
  if (/relation_needs/.test(r)) return 'Proposed relationship needs review';
  if (/high_impact/.test(r)) return 'Confirm contract, scope and amount linkage';
  if (/unresolved_or_multiple/.test(r)) return 'Note does not resolve to one opportunity scope';
  return label(r.replace('rejected_semantic_proposal:',''));
}
function journeyStates(detail) {
  return JOURNEY.map(key => ({key, observed:detail.observed_milestones.includes(key), furthest:detail.furthest_evidenced_journey_milestone===key}));
}
function opportunityHref(id, week) { return '#opportunity/'+encodeURIComponent(id)+(week?'/'+encodeURIComponent(week):''); }
function badge(value,kind='') { return `<span class="badge ${kind}">${esc(label(value))}</span>`; }
function evidenceButton(ids, text='Why? View evidence') { return ids?.length ? `<button class="link" data-evidence="${esc(ids.join('|'))}">${esc(text)} ↗</button>` : '<span class="small">No linked evidence supplied</span>'; }
function movementCards(movement, opportunities, week) {
  return ['journey','economics','risk'].map(key=>`<section class="movement"><h2>${{journey:'Journey',economics:'Economics',risk:'Risk & review'}[key]}</h2>${movement[key].length ? movement[key].map(change=> {
    const o=opportunities.get(change.opportunity_id);
    return `<div class="change"><a href="${opportunityHref(change.opportunity_id,week)}">${esc(o?.account_label || 'Unresolved opportunity')}</a><p>${esc(o?.use_case_label || 'Use case unknown')}</p><p>${esc(label(change.kind))}</p>${change.from!==undefined?`<p>${esc(label(change.from))} → ${esc(label(change.to))}</p>`:''}</div>`;
  }).join('') : '<p class="empty">No recorded change this week.</p>'}</section>`).join('');
}
/* Belief layer: Observed -> Inferred -> Verified. Inferred states are labelled as such and never touch money. */
function beliefLabel(value) { if (value == null || value === '') return 'Unknown'; return BELIEF_LABELS[value] || label(value); }
function bandChip(band) { return band ? `<span class="chip band-${esc(band)}" title="Heuristic support band, not a probability">${esc(beliefLabel(band))}</span>` : '<span class="chip">No support</span>'; }
function compactText(pair) { return pair ? `${beliefLabel(pair[0])}${pair[1]?' · '+beliefLabel(pair[1]):''}` : 'Not inferred'; }
function headlineHtml(entry) {
  const parts=entry?.headline?.parts||[];
  if (!parts.length) return '<span class="small">No inferred commercial state</span>';
  return parts.map(p=>`<span class="inferred-part">${esc(beliefLabel(p.dimension))}: ${esc(beliefLabel(p.value))} ${bandChip(p.band)}</span>`).join('');
}
function beliefMarkers(s) {
  return [s.depends_on_model_inference?'<span class="marker" title="Most support points come from model extraction">Model-dependent</span>':'',
    s.stale?'<span class="marker" title="Latest supporting evidence is older than 90 days">Stale</span>':'',
    s.contested?'<span class="marker warn" title="Contradicting evidence is at least half the support">Contested</span>':''].join('');
}
function signalEntry(e) {
  return `<li><span>${esc(e.polarity==='negative'?'Against: ':'')}${esc(e.label)}</span> <span class="small">${esc(date(e.effective_date))} · ${esc(beliefLabel(e.method))} · ${esc(beliefLabel(e.modality))}</span> ${evidenceButton(e.evidence_ids,'Evidence')}</li>`;
}
function beliefStateHtml(dimension, s) {
  const why = s.band ? `<details class="why"><summary>Why?</summary><p>${esc(s.explanation)}</p>
    ${s.supporting.length?`<h4>Supporting signals</h4><ul class="signal-mini">${s.supporting.map(signalEntry).join('')}</ul>`:''}
    ${s.contradicting.length?`<h4>Contradicting signals</h4><ul class="signal-mini">${s.contradicting.map(signalEntry).join('')}</ul>`:''}
    ${(s.missing_expected||[]).length?`<p class="small">Expected but not observed: ${esc(s.missing_expected.join('; '))}</p>`:''}
    <p class="small">Last meaningful update: ${esc(date(s.last_meaningful_update))} · Support ${esc(s.support_points)} vs opposition ${esc(s.opposition_points)} heuristic points · Model dependence: ${esc(s.model_dependence)}${(s.caps_applied||[]).length?' · Capped: '+esc(s.caps_applied.map(label).join(', ')):''}</p></details>`
    : `<p class="small">${esc(s.explanation || 'No supporting signals.')} Unknown is not negative evidence.</p>`;
  return `<div class="belief-dim" data-dimension="${esc(dimension)}"><div class="belief-head"><span class="eyebrow">${esc(beliefLabel(dimension))}</span><span class="belief-value">${esc(beliefLabel(s.value))}</span>${bandChip(s.band)}${beliefMarkers(s)}</div>${why}</div>`;
}
function observedHtml(signals) {
  if (!signals.length) return '<p class="empty">No atomic signals observed.</p>';
  return `<ul class="signal-list">${signals.map(s=>`<li class="${s.inert_reason?'inert':''}"><div>${esc(s.polarity==='negative'?'Against: ':'')}${esc(s.label)}${s.retyped_from?` <span class="small">(read as ${esc(beliefLabel(s.retyped_from).toLowerCase())} → ${esc(s.modality)})</span>`:''}</div><div class="small">${esc(date(s.effective_date))} ${badge(s.modality)} ${esc(beliefLabel(s.method))} · ${esc(beliefLabel(s.observation))}${s.indicative?' · indicative':''}${s.inert_reason?' · not used: '+esc(label(s.inert_reason)):''}</div>${evidenceButton(s.evidence_ids,'Evidence')}</li>`).join('')}</ul>`;
}
function verifiedHtml(v, o) {
  return `<dl class="verified-facts"><div><dt>Verified Actual</dt><dd data-testid="detail-verified-actual">${money(o.verified_actual_usd)}</dd></div>
  <div><dt>Formal contract verification</dt><dd>${v.formal_contract_verified?'Yes · documentary gate':'No'}</dd></div>
  <div><dt>Pilot signature</dt><dd>${v.reported_pilot_signature?'Reported · unverified':'Not reported'}</dd></div>
  <div><dt>Commercial signature</dt><dd>${v.reported_commercial_signature?'Reported · unverified':'Not reported'}</dd></div></dl><p class="small">${esc(v.rule)}</p>`;
}
function oivSection(entry, o) {
  const head = '<div class="section-head"><h2>Observed → Inferred → Verified</h2><span class="small">Three separate kinds of statement</span></div>';
  if (!entry) return `<section class="oiv-wrap" data-section="observed-inferred-verified">${head}<p class="empty">No inferred state is published for this opportunity.</p></section>`;
  const states = entry.current.states;
  const contradictions = entry.unresolved_contradictions||[];
  return `<section class="oiv-wrap" data-section="observed-inferred-verified">${head}
  <div class="oiv"><section class="oiv-col observed-col" aria-label="Observed"><div class="eyebrow">Observed · atomic signals</div><p class="small">One reading of one exact excerpt each. Planned, conditional and negated statements stay labelled.</p>${observedHtml(entry.observed_signals)}</section>
  <section class="oiv-col inferred-col" aria-label="Inferred"><div class="eyebrow">Inferred · not verified</div><p class="small">Combined from signals over time. Bands are heuristic support levels, not probabilities.</p>${DIMENSIONS.filter(d=>states[d]).map(d=>beliefStateHtml(d,states[d])).join('')}
  ${contradictions.length?`<div class="contradictions"><h3>Unresolved contradictions</h3>${contradictions.map(c=>`<p>${esc(beliefLabel(c.dimension))}: ${esc(beliefLabel(c.value))} ${bandChip(c.band)} ${evidenceButton(c.supporting_evidence_ids,'For')} ${evidenceButton(c.contradicting_evidence_ids,'Against')}</p>`).join('')}</div>`:'<p class="small">No unresolved material contradictions.</p>'}</section>
  <section class="oiv-col verified-col" aria-label="Verified"><div class="eyebrow">Verified · documentary gate only</div>${verifiedHtml(entry.verified,o)}</section></div></section>`;
}
function weeklyBeliefHtml(weekEntry, id) {
  const states = weekEntry?.retrospective?.[id];
  const body = states ? `<dl class="facts">${DIMENSIONS.filter(d=>states[d]).map(d=>`<div><dt>${esc(beliefLabel(d))}</dt><dd>${esc(beliefLabel(states[d][0]))} ${bandChip(states[d][1])}</dd></div>`).join('')}</dl>` : '<p class="empty">No dated signals for this opportunity by this week.</p>';
  return `<section class="oiv-wrap" data-section="observed-inferred-verified"><div class="section-head"><h2>Inferred state at week end</h2><span class="small">Inferred · not verified</span></div><p class="small">Retrospective inference from evidence dated on or before this week. Historical knowledge quality: ${esc(label(weekEntry?.historical_knowledge_quality))}; this is not proof of what was known then.</p>${body}</section>`;
}
function beliefChangesCard(changes, opportunities, week) {
  return `<section class="movement"><h2>Inferred state</h2><p class="small">Inferred, not verified. Changes in heuristic belief bands.</p>${changes.length ? changes.map(c=>{
    const o=opportunities.get(c.opportunity_id);
    return `<div class="change"><a href="${opportunityHref(c.opportunity_id,week)}">${esc(o?.account_label || 'Unresolved opportunity')}</a><p>${esc(beliefLabel(c.dimension))}</p><p>${esc(compactText(c.from))} → ${esc(compactText(c.to))}</p></div>`;
  }).join('') : '<p class="empty">No inferred-state change this week.</p>'}</section>`;
}
function inferredOverview(b) {
  const o=b.overview.portfolio_with_reconstructed || b.overview, all=Boolean(b.overview.portfolio_with_reconstructed);
  const items=[['Operationally active pilots',o.operationally_active_pilots,'Pilot inferred active with high or very high support.'],
    ['Likely committed',o.likely_committed_pilots,'Pilot inferred committed, active or completed (medium or above).'],
    ['Commercial process underway',o.commercial_process_underway,'Terms or procurement inferred underway.'],
    ['Likely stalled',o.likely_stalled,'Momentum inferred stalled or lost.'],
    ['Probable blockers',o.probable_blockers,'Unresolved blocker inferred (medium or above).']];
  return `<section class="inferred-row" aria-label="Inferred commercial state"><div class="section-head"><h2>Inferred commercial state — not verified, not a forecast</h2><a class="small" href="#how-it-works">How inference works →</a></div><div class="inferred-grid">${items.map(([k,v,d])=>`<div class="metric"><div class="eyebrow">${k}</div><strong>${esc(v)}</strong><p>${d}</p></div>`).join('')}</div><p class="small">Counts by inferred state, of ${esc(o.opportunities)}${all?` (${esc(o.canonical_opportunities)} canonical opportunities and ${esc(o.reconstructed_deals)} deals reconstructed from context)`:' opportunities'}. They are counts, not money, and never change the documentary-verified figure.</p></section>`;
}
/* Valuation layer: recognised by reasoning, documentary-verified, and estimates stay three separate figures.
   Every figure is published by the belief layer; nothing is summed or weighted here. */
const VALUATION_LABELS = {
  recognized_signed_acv:'Recognised signed ACV · by reasoning', recognized_outside_window:'Signature reasoned · outside target window',
  estimate:'Estimate · not a commitment', unknown:'Value unknown',
  stated_rollout_value:'Stated rollout value', pilot_fee_times_corpus_ratio:'Pilot fee × corpus rollout/pilot ratio',
  corpus_median_rollout:'Corpus median rollout value'
};
function valuationLabel(value) { return VALUATION_LABELS[value] || beliefLabel(value); }
function valuationOf(snapshot) { return snapshot.belief_states && snapshot.belief_states.overview && snapshot.belief_states.overview.valuation || null; }
function isRecognised(v) { return v?.kind==='recognized_signed_acv' && v.recognized===true; }
function valuationKind(v) {
  if (!v) return 'unknown';
  if (v.kind==='recognized_signed_acv') return v.recognized===true ? 'recognized_signed_acv' : 'recognized_outside_window';
  return v.kind==='estimate' ? 'estimate' : 'unknown';
}
function reconstructedOf(snapshot) { return snapshot.belief_states?.reconstructed_opportunities || {}; }
function recognisedValuations(snapshot) {
  const b=snapshot.belief_states||{}, out=[];
  for (const [id,e] of Object.entries(b.opportunities||{})) if (isRecognised(e.valuation)) out.push({id,href:opportunityHref(id),label:snapshot.opportunity_details?.find(o=>o.opportunity_id===id)?.account_label||'Opportunity',valuation:e.valuation});
  for (const [id,r] of Object.entries(reconstructedOf(snapshot))) if (isRecognised(r.valuation)) out.push({id,href:reconstructedHref(id),label:r.label,valuation:r.valuation});
  return out;
}
function reconstructedHref(id) { return '#reconstructed/'+encodeURIComponent(id); }
function rangeText(range) { return Array.isArray(range) && range.length===2 ? `${money(range[0])} – ${money(range[1])}` : 'No range'; }
function localAmount(v) {
  if (v?.local_amount==null || !v.currency) return '';
  try { return new Intl.NumberFormat('en-US',{style:'currency',currency:v.currency,maximumFractionDigits:0}).format(v.local_amount); } catch { return ''; }
}
function uniqueIds(lists) { return [...new Set(lists.flat().filter(Boolean))]; }
function evidenceIdsForGroup(snapshot, group) { return (snapshot.evidence_summaries||[]).filter(e=>e.reference===group).map(e=>e.evidence_id); }
function recognisedHeadline(snapshot) {
  const o=snapshot.overview, v=valuationOf(snapshot), deals=recognisedValuations(snapshot);
  const ids=uniqueIds(deals.map(d=>d.valuation.evidence_ids||[]));
  const count=v ? v.recognized_deal_count : null;
  const explain=v ? `${esc(count)} ${count===1?'deal':'deals'} recognised. A signature counts here when the reasoning supports it with high confidence: a reported signature, a coherent uncontested corroborating chain, a stated annual amount and currency, and a signature date inside the target window. Estimates and weighted values are never included.`
    : 'Reasoned recognition is not published in this snapshot. Unknown is not zero.';
  return `<section class="headline" aria-label="Target reconciliation"><div class="actual"><div class="eyebrow">Signed ACV — recognised by reasoning</div><div class="actual-number" data-testid="recognised">${v?money(v.recognized_signed_acv_usd):money(null)}</div>
  <p>${explain} ${v ? evidenceButton(ids,'Why? View evidence') : ''}</p>
  ${deals.length?`<ul class="recognised-list" aria-label="Recognised deals">${deals.map(d=>`<li><a href="${d.href}">${esc(d.label)}</a> <span class="small">${money(d.valuation.amount_usd)}${localAmount(d.valuation)?' · '+esc(localAmount(d.valuation))+' per year':''} · signed ${esc(date(d.valuation.signature_date))} · not documentary-verified</span></li>`).join('')}</ul>`:''}
  <div class="documentary" data-testid="documentary-line"><span class="eyebrow">Stricter documentary gate</span><p>Documentary-verified: <strong data-testid="actual">${money(o.verified_signed_acv_usd)}</strong></p><p class="small">Only commercial contracts that pass documentary verification. Shown separately from the recognised figure and never mixed with it. ${esc(o.counts.verified_signature)} documentary-verified commercial signatures in this dated population.</p></div></div>
  <div class="target"><div class="eyebrow">New signed commercial ACV target</div><div class="target-number">${money(o.target.amount_usd)}</div><p>By ${date(o.target.deadline)}</p><div class="rule"></div><span class="small">Pilot fees never count toward the target.</span></div></section>`;
}
function estimatesHtml(snapshot) {
  const v=valuationOf(snapshot);
  if (!v) return '<section class="estimates" data-section="estimates" aria-label="Estimates"><p class="small">Contextual estimates are not published in this snapshot.</p></section>';
  const bases=Object.entries(v.estimate_count_by_basis||{});
  return `<section class="estimates" data-section="estimates" aria-label="Estimates"><div class="section-head"><h2>Estimates — reasoned from context, never counted as signed</h2><a class="small" href="#how-it-works">How estimates work →</a></div>
  <div class="metrics"><div class="metric"><div class="eyebrow">Estimated open pipeline</div><strong data-testid="estimated-pipeline">${money(v.estimated_open_pipeline_usd)}</strong><p>Range ${rangeText(v.estimated_open_pipeline_range_usd)}. Each value is estimated from a stated value, a pilot fee or the corpus, with its basis and evidence. Not part of signed ACV.</p></div>
  <div class="metric"><div class="eyebrow">Weighted pipeline · heuristic stage weighting</div><strong data-testid="weighted-pipeline">${money(v.weighted_pipeline_usd)}</strong><p>Each estimate multiplied by a heuristic weight for its inferred stage. Not a forecast and not a probability; the weights are not calibrated.</p></div>
  <div class="metric"><div class="eyebrow">Estimates by basis</div>${bases.map(([k,n])=>`<div class="line-row"><span>${esc(valuationLabel(k))}</span><strong>${esc(n)}</strong></div>`).join('')||'<p>No estimates.</p>'}</div></div></section>`;
}
function anchorText(anchor) {
  const [kind,...rest]=String(anchor).split(':'), value=rest.join(':');
  return {bigram:`“${value}” · phrase`,term:`“${value}” · rare term`,amount:`${value} · exact amount`,name:`${value} · name (never links alone)`}[kind] || String(anchor);
}
function contextLinksHtml(groups, snapshot) {
  const n=(groups||[]).length;
  return `<div class="context-links" data-testid="context-links"><p><strong>Linked by context: ${esc(n)} ${n===1?'note':'notes'}</strong> ${n?evidenceButton(uniqueIds(groups.map(g=>evidenceIdsForGroup(snapshot,g))),'Linked notes'):''}</p><p class="small">${n?'These notes were not linked by the identity rules. They were linked because they share distinctive anchors with this deal’s evidence: at least one rare shared phrase plus a second rare anchor or exact amount. Template sentences are excluded, names alone never link and conflicting contacts block a link.':'No additional notes matched this deal’s distinctive anchors.'}</p></div>`;
}
function valuationHtml(v, contextLinks, snapshot) {
  const kind=valuationKind(v);
  const head=`<div class="section-head"><h2>Valuation</h2><span class="small">${kind==='estimate'?'Estimate · not a commitment, not recognised':kind==='recognized_signed_acv'?'Recognised by reasoning · not documentary-verified':kind==='recognized_outside_window'?'Not recognised: outside the target window':'Unknown is not zero'}</span></div>`;
  if (!v) return `<section class="valuation" data-section="valuation" data-kind="unknown">${head}<p class="empty">No valuation is published for this deal.</p>${contextLinks?contextLinksHtml(contextLinks,snapshot):''}</section>`;
  const rows=[['Kind',`<span data-testid="valuation-kind">${esc(valuationLabel(kind))}</span>`],
    ['Amount',`<span data-testid="valuation-amount">${money(v.amount_usd)}</span>${localAmount(v)?` <span class="small">${esc(localAmount(v))} per year</span>`:''}`]];
  if (kind==='estimate') rows.push(['Range',esc(rangeText(v.range_usd))],['Confidence band',bandChip(v.band)],['Basis',esc(valuationLabel(v.basis))],
    ['Weighted · heuristic',`${money(v.weighted_usd)} <span class="small">not a probability</span>`]);
  if (kind.startsWith('recognized')) rows.push(['Signature date',esc(date(v.signature_date))],['Documentary verification',v.documentary_verified?'Yes · documentary gate':'No · reasoning only']);
  rows.push(['Inferred stage',`${esc(beliefLabel(v.stage))} <span class="small">heuristic stage weight ${esc(v.stage_weight)}</span>`]);
  return `<section class="valuation" data-section="valuation" data-kind="${esc(kind)}">${head}<dl class="facts">${rows.map(([k,d])=>`<div><dt>${k}</dt><dd>${d}</dd></div>`).join('')}</dl>
  <h3>Reasons</h3><ul class="reasons">${(v.reasons||[]).map(r=>`<li>${esc(r)}</li>`).join('')||'<li>No reasons supplied.</li>'}</ul>${v.rule?`<p class="small">${esc(v.rule)}</p>`:''}
  <p>${evidenceButton(v.evidence_ids||[],'Why? Valuation evidence')}</p>${contextLinks?contextLinksHtml(contextLinks,snapshot):''}</section>`;
}
function amountOf(v) { const n=Number(v?.amount_usd); return Number.isFinite(n) ? n : -1; }
function reconstructedRank(r) { return {recognized_signed_acv:3,recognized_outside_window:2,estimate:1}[valuationKind(r.valuation)] || 0; }
function reconstructedTable(snapshot) {
  const rows=Object.values(reconstructedOf(snapshot)).sort((a,b)=>reconstructedRank(b)-reconstructedRank(a) || amountOf(b.valuation)-amountOf(a.valuation) || String(a.label).localeCompare(String(b.label)));
  return `<section class="reconstructed" data-section="reconstructed-deals" aria-label="Reconstructed deals"><div class="section-head"><h2>Reconstructed deals (inferred from context)</h2><span class="small">${esc(rows.length)} deals · not canonical opportunities</span></div>
  <p class="small">Notes that the identity rules left unlinked, grouped into deals by shared distinctive anchors. They are inferred, not canonical: they never enter the opportunity list above, weekly movement or the documentary-verified figure. A reconstructed deal whose signature the reasoning supports with high confidence is counted in Signed ACV — recognised by reasoning.</p>
  <div class="table-wrap"><table><thead><tr><th>Reconstructed deal</th><th>Inferred state</th><th>Inferred stage</th><th>Valuation</th></tr></thead><tbody id="recon-rows">${rows.map(r=>`<tr><td class="scope-cell"><a class="account-link" href="${reconstructedHref(r.cluster_id)}">${esc(r.label)}</a><span class="small">${badge('inferred_from_context','pending')} ${esc((r.groups||[]).length)} linked notes</span></td><td class="inferred-cell"><span class="eyebrow">Inferred · not verified</span>${headlineHtml(r)}</td><td>${esc(beliefLabel(r.inferred_stage))}</td><td>${money(r.valuation?.amount_usd)}<span class="small">${esc(valuationLabel(valuationKind(r.valuation)))}</span></td></tr>`).join('')||'<tr><td colspan="4" class="empty">No deals were reconstructed from context.</td></tr>'}</tbody></table></div></section>`;
}
function reconstructedOiv(r) {
  const states=r.current?.states||{}, contradictions=(r.current?.contradictions||[]).filter(c=>c.material);
  return `<section class="oiv-wrap" data-section="observed-inferred-verified"><div class="section-head"><h2>Observed → Inferred → Verified</h2><span class="small">Three separate kinds of statement</span></div>
  <div class="oiv"><section class="oiv-col observed-col" aria-label="Observed"><div class="eyebrow">Observed · atomic signals</div><p class="small">Signals read from the linked notes. Each keeps its exact excerpt; dates inferred from the deal sequence are labelled by the engine.</p>${observedHtml(r.observed_signals||[])}</section>
  <section class="oiv-col inferred-col" aria-label="Inferred"><div class="eyebrow">Inferred · not verified</div><p class="small">Combined from signals over time. Bands are heuristic support levels, not probabilities.</p>${DIMENSIONS.filter(d=>states[d]).map(d=>beliefStateHtml(d,states[d])).join('')}
  ${contradictions.length?`<div class="contradictions"><h3>Unresolved contradictions</h3>${contradictions.map(c=>`<p>${esc(beliefLabel(c.dimension))}: ${esc(beliefLabel(c.value))} ${bandChip(c.band)} ${evidenceButton(c.supporting_evidence_ids,'For')} ${evidenceButton(c.contradicting_evidence_ids,'Against')}</p>`).join('')}</div>`:'<p class="small">No unresolved material contradictions.</p>'}</section>
  <section class="oiv-col verified-col" aria-label="Verified"><div class="eyebrow">Verified · documentary gate only</div><dl class="verified-facts"><div><dt>Documentary verification</dt><dd data-testid="reconstructed-documentary">${r.valuation?.documentary_verified?'Yes · documentary gate':'No'}</dd></div><div><dt>Canonical opportunity</dt><dd>No · inferred from context</dd></div></dl><p class="small">A reconstructed deal never enters the documentary-verified figure.</p></section></div></section>`;
}
function linkageHtml(r, snapshot) {
  const title=g=>(snapshot.evidence_summaries||[]).find(e=>e.reference===g)?.title || 'Source note';
  const rule=snapshot.belief_states?.overview?.reconstruction?.rule;
  return `<section class="linkage" data-section="reconstruction-links"><div class="section-head"><h2>How these notes were linked</h2><span class="small">${esc((r.groups||[]).length)} notes · heuristic, not calibrated</span></div>
  <p class="small">Distinctive anchors shared across the notes:</p><p class="anchors">${(r.anchors||[]).map(a=>`<span class="chip">${esc(anchorText(a))}</span>`).join(' ')||'<span class="small">No anchors published</span>'}</p>
  <div class="table-wrap"><table><thead><tr><th>Linked note</th><th>Link score</th><th>Shared anchors</th></tr></thead><tbody>${(r.links||[]).map(l=>`<tr><td>${esc(title(l.group))} ${evidenceButton(evidenceIdsForGroup(snapshot,l.group),'Note evidence')}</td><td>${esc(l.score)}</td><td>${(l.shared_anchors||[]).map(a=>`<span class="chip">${esc(anchorText(a))}</span>`).join(' ')}</td></tr>`).join('')||'<tr><td colspan="3" class="empty">No link details published.</td></tr>'}</tbody></table></div>
  <h3>Notes in this deal</h3><ul class="signal-list">${(r.groups||[]).map(g=>`<li>${esc(title(g))} ${evidenceButton(evidenceIdsForGroup(snapshot,g),'Evidence')}</li>`).join('')}</ul>
  <h3>Corroboration</h3>${(r.corroboration||[]).length?`<ul class="signal-list">${r.corroboration.map(c=>`<li><blockquote>${esc(c.text)}</blockquote><span class="small">Signature date ${esc(date(c.signature_date))} · ${esc(localAmount({local_amount:c.amount,currency:c.currency})||c.amount)} per year · CRM annotation corroborates the amount and date; it is not documentary verification</span> ${evidenceButton([c.evidence_id],'Evidence')}</li>`).join('')}</ul>`:'<p class="small">No independent corroboration published.</p>'}
  ${rule?`<p class="small">Linking rule: ${esc(rule)}.</p>`:''}</section>`;
}
function reconstructedDetail(id, snapshot) {
  const r=reconstructedOf(snapshot)[id];
  if (!r) return `${heading('02','Reconstructed deal unavailable','This reconstructed deal is not present in the published snapshot.')}<a href="#opportunities">Return to opportunities</a>`;
  return `<a class="back" href="#opportunities">← All opportunities</a><div class="eyebrow">Reconstructed deal · Inferred from context</div><h1 class="reconstructed-title">${esc(r.label)} ${badge('inferred_from_context','pending')}</h1>
  <div class="note" data-testid="reconstructed-note"><strong>Inferred from context.</strong> ${esc(r.note||'Not a canonical opportunity: reconstructed by linking unlinked notes through shared distinctive anchors.')} It is inferred, not verified, and never enters the documentary-verified figure.${isRecognised(r.valuation)?' Its signature is recognised by reasoning, so its value is part of Signed ACV — recognised by reasoning.':''}</div>
  <p class="intro">${headlineHtml(r)}</p>
  ${reconstructedOiv(r)}${valuationHtml(r.valuation,null,snapshot)}${linkageHtml(r,snapshot)}`;
}
function valuationMethod(snapshot) {
  const v=valuationOf(snapshot);
  const weights=Object.entries(v?.stage_weights||{}).sort((a,b)=>a[1]-b[1]), s=v?.corpus_stats||{};
  const fixed=x=>Number.isFinite(Number(x))?Number(x).toFixed(1):'unknown';
  return `<section class="method-section method-valuation" aria-label="Recognition, reconstruction and estimates"><div class="eyebrow">07 / Recognition, reconstruction and estimates</div><h2>Reasoned recognition, with the stricter gate kept visible.</h2>
  <div class="method-pair"><section><h3>Signed ACV — recognised by reasoning</h3><p>A signature is recognised when the belief layer supports it with high confidence: commercial status inferred as reported signed at a high band and uncontested, a coherent corroborating chain, one stated annual amount and currency, and a signature date inside the target window. The reasons and exact evidence are shown for every recognised deal.</p></section>
  <section><h3>Documentary-verified</h3><p>The stricter figure counts only commercial contracts that pass documentary verification. It is always shown directly under the recognised figure, and the two are never added together.</p></section></div>
  <h3>Deal reconstruction</h3><p>Notes that the identity rules could not link are grouped when they share distinctive anchors: at least one rare shared phrase (in three or fewer sources) plus a second rare anchor or an exact amount. Sentences repeated verbatim across sources are templates and give no anchors. Names alone never link, and notes naming different contacts are not merged. Two canonical opportunities are never merged. Each link records its score and shared anchors.${v?` ${esc(snapshot.belief_states.overview.reconstructed_deal_count)} deals were reconstructed in this snapshot.`:''}</p>
  <h3>Estimates</h3><p>Where no value is recognised, a value is estimated in this order: a stated (possibly conditional) rollout value; else the pilot fee × the median rollout/pilot ratio observed in the corpus (${fixed(s.ratio_median)} across ${esc(s.ratio_n ?? 'unknown')} deals); else the corpus median rollout value (${money(s.rollout_median_usd)}). Each estimate carries its basis, range, confidence band and evidence. The weighted pipeline multiplies each estimate by a heuristic weight for its inferred stage:</p>
  ${weights.length?`<div class="table-wrap"><table class="method-table"><thead><tr><th>Inferred stage</th><th>Heuristic weight</th></tr></thead><tbody>${weights.map(([k,w])=>`<tr><td>${esc(beliefLabel(k))}</td><td>${esc(w)}</td></tr>`).join('')}</tbody></table></div>`:''}
  <p class="small"><strong>These rules, ranges and weights are heuristic, not calibrated.</strong> The weighted pipeline is not a forecast or a probability, and no estimate or weighted value is added to the recognised or documentary-verified figures.</p></section>`;
}
function triageFor(row, snapshot) { return snapshot.belief_states?.review_triage?.[row.review_id]; }
function decisionNeeded(row, snapshot) { const t=triageFor(row,snapshot); return !t || t.decision_needed===true; }
function allReviews(snapshot) { return snapshot.review_queue.concat(snapshot.belief_states?.belief_review_items || []); }
function visibleReviews(rows, snapshot, includeInformational) { return rows.filter(r=>includeInformational || decisionNeeded(r,snapshot)); }
let data, opportunityMap, evidenceMap;
const $ = selector=>document.querySelector(selector);
function heading(number,title,description) { return `<div class="eyebrow">${number} / Operating notebook</div><h1>${title}</h1><p class="intro">${description}</p>`; }
function overview() {
  const o=data.overview, c=o.value_coverage;
  return `${heading('01','Commercial progress, with evidence.','A dated view of the commercial journey. Confirmed outcomes, reported claims and open questions stay separate.')}
  ${recognisedHeadline(data)}
  ${estimatesHtml(data)}
  <div class="section-head measures-head"><h2>Read-model measures · dated canonical population</h2><span class="small">Published by the read model; separate from the reasoned figures above</span></div>
  <section class="metrics" aria-label="Separate economic measures"><div class="metric"><div class="eyebrow">Reported signed · pending verification</div><strong>${money(o.reported_signed_pending_verification_usd)}</strong><p>${o.counts.reported_signature} reported signature opportunity states in the dated view. Unlinked and undated signature claims remain in Review.</p></div><div class="metric"><div class="eyebrow">Known open commercial value</div><strong>${money(o.known_value_open_commercial_pipeline_usd)}</strong><p>Known-value subset only. ${c.with_eligible_value} of ${c.open_opportunities} open opportunities have an eligible value; ${c.unknown_value_count} remain unknown.</p></div><div class="metric"><div class="eyebrow">Sensitivity proxy — not a forecast</div><strong>${money(o.heuristic_proxy.amount_usd)}</strong><p>Progression weighting of the known-value subset. Not a probability or expected revenue. Sensitivity: ${o.heuristic_proxy.sensitivity_usd.map(money).join(' – ')}.</p></div></section>
  <div class="note">Coverage matters: an unknown value is not zero. Undated opportunities are excluded from this dated population; their evidence can still require <a href="#review/Signature%20verification">signature verification</a>.</div>
  <div class="two-col"><section><div class="section-head"><h2>Observed journey</h2><a class="small" href="#opportunities">${o.counts.opportunities} opportunities →</a></div>${Object.entries(o.journey_distribution).map(([k,v])=>`<div class="line-row"><span>${esc(label(k))}</span><strong>${v}</strong></div>`).join('')}<p class="small">Furthest evidenced milestone only. Missing earlier milestones remain unobserved. A reported pilot signature is not a commercial signature.</p></section>${questionsPanel(data)}</div>
  ${inferredOverview(data.belief_states)}
  <div class="section-head"><h2>Latest movement</h2><a class="small" href="#weekly">Week ending ${date(data.manifest.business_as_of)} →</a></div><div class="movement-grid">${movementCards(o.latest_weekly_movement,opportunityMap,data.manifest.business_as_of)}</div>`;
}
function questionsPanel(snapshot) {
  const summary=snapshot.belief_states.review_summary, needed=visibleReviews(allReviews(snapshot),snapshot,false);
  return `<section><div class="section-head"><h2>Questions to resolve</h2><a class="small" href="#review">${summary.decision_needed} need a decision →</a></div>
  <div class="line-row"><span>Decision needed</span><strong data-testid="decision-needed">${summary.decision_needed}</strong></div><div class="line-row"><span>Informational · kept for audit</span><strong data-testid="informational">${summary.informational}</strong></div>
  ${GROUPS.map(g=>[g,needed.filter(r=>reviewGroup(r)===g).length]).filter(([,n])=>n).slice(0,4).map(([g,n])=>`<div class="line-row"><a href="#review/${encodeURIComponent(g)}">${g}</a><strong>${n}</strong></div>`).join('')}<p class="small">Every item is retained. Only items whose answer changes recognised value, opportunity structure or a contested inferred state need a decision. Categories guide attention; they are not financial risk scores.</p></section>`;
}
function opportunities() {
  return `${heading('02','Opportunities','Account × use case × commercial scope. Open an opportunity to inspect its observed events, value status and exact supporting evidence.')}<div class="toolbar"><label>Search account, use case or scope<input id="op-search" type="search" placeholder="Search opportunities"></label><label>Lifecycle<select id="op-lifecycle"><option value="">All states</option>${[...new Set(data.opportunities.map(o=>o.lifecycle))].map(s=>`<option value="${esc(s)}">${esc(label(s))}</option>`).join('')}</select></label><span id="op-count" class="result-count" aria-live="polite"></span></div><div class="table-wrap"><table><thead><tr><th>Account / identity</th><th>Use case / commercial scope</th><th>Observed journey</th><th>Commercial value</th><th>Momentum / review</th><th>Inferred state</th></tr></thead><tbody id="op-rows"></tbody></table></div><p class="small">Dated population as of ${date(data.manifest.business_as_of)}. Provisional scope identities require review. “Unknown” does not imply no contract or no activity. The inferred state combines soft signals; its band is a heuristic support level, not a probability, and it is never verification.</p>${reconstructedTable(data)}`;
}
function renderOpportunityRows() {
  const query=$('#op-search').value.toLowerCase(), lifecycle=$('#op-lifecycle').value;
  const rows=data.opportunities.filter(o=>(!lifecycle||o.lifecycle===lifecycle)&&[o.account_label,o.use_case_label,o.scope_label].join(' ').toLowerCase().includes(query)).sort((a,b)=>a.account_label.localeCompare(b.account_label));
  $('#op-count').textContent=`${rows.length} of ${data.opportunities.length} opportunities`;
  $('#op-rows').innerHTML=rows.map(o=>`<tr><td><a class="account-link" href="${opportunityHref(o.opportunity_id)}">${esc(o.account_label)}</a><span class="small">${badge(opportunityMap.get(o.opportunity_id).resolution_status,'pending')}</span></td><td class="scope-cell"><p>${esc(o.use_case_label || 'Use case unknown')}</p><span class="small">${esc(o.scope_label || 'Scope unknown')}</span></td><td>${esc(label(o.furthest_evidenced_journey_milestone))}<span class="small">${o.last_meaningful_event?date(o.last_meaningful_event.event_date):'No dated event linked'}</span><span class="small">Commercial: ${esc(label(o.commercial_state))}</span></td><td>${money(o.known_open_commercial_value_usd)}<span class="small">${esc(label(o.value_status))}</span></td><td>${esc(label(o.momentum))}<span class="small">${esc(label(o.main_issue))}</span><a class="small" href="#review/opportunity/${o.opportunity_id}">Review ${esc(o.review_status)} →</a></td><td class="inferred-cell"><span class="eyebrow">Inferred · not verified</span>${headlineHtml(data.belief_states.opportunities[o.opportunity_id])}</td></tr>`).join('') || '<tr><td colspan="6" class="empty">No opportunities match these filters.</td></tr>';
}
function detail(id,week) {
  const snapshot=week ? data.weekly_snapshots.find(s=>s.week_end===week) : null;
  const o=week ? snapshot?.retrospective_event_state.opportunities[id] : opportunityMap.get(id);
  if (!o) return `${heading('02','Opportunity unavailable','This opportunity is not present in the selected dated snapshot.')}<a href="#opportunities">Return to opportunities</a>`;
  return `<a class="back" href="${week?'#weekly/'+week:'#opportunities'}">← ${week?'Back to selected week':'All opportunities'}</a><div class="eyebrow">Opportunity / ${week?'Week ending '+date(week):'Current dated snapshot'}</div><h1>${esc(o.account_label)} ${badge(o.resolution_status,'pending')}</h1><p class="intro">${esc(o.use_case_label || 'Use case unknown')}</p><p><strong>Commercial scope</strong> · ${esc(o.scope_label || 'Unknown')}</p>${week?'<div class="note">Retrospective event reconstruction for this week. This is not proof of what was known then.</div>':''}
  ${week?weeklyBeliefHtml(data.belief_states.weekly.find(w=>w.week_end===week),id):oivSection(data.belief_states.opportunities[id],o)+valuationHtml(data.belief_states.opportunities[id]?.valuation,data.belief_states.opportunities[id]?.context_links||[],data)}
  <section><div class="section-head"><h2>Journey</h2>${evidenceButton(o.supporting_evidence_ids,'Why this state?')}</div><p class="small">Only observed milestones are marked. Blank milestones are unobserved, not completed. Signature reports remain unverified unless explicitly verified.</p><div class="journey">${journeyStates(o).map(s=>`<div class="milestone ${s.observed?'is-observed':''}">${esc(label(s.key))}<small>${s.observed?'Observed':'Unobserved'}${s.furthest?' · furthest':''}</small></div>`).join('')}</div></section>
  <h2>Evidence & operating state</h2><dl class="facts">${['pilot_state','technical_state','commercial_state','lifecycle','momentum','buyer_state','procurement_legal_state','data_access_state','next_step_state','blocker_state','readiness_band','evidence_status'].map(k=>`<div><dt>${esc(label(k))}</dt><dd>${esc(label(o[k]))}</dd></div>`).join('')}</dl>
  <h2>Economics</h2><section class="metrics"><div class="metric"><div class="eyebrow">Verified Actual</div><strong>${money(o.verified_actual_usd)}</strong></div><div class="metric"><div class="eyebrow">Reported signed · pending</div><strong>${money(o.reported_signed_pending_verification_usd)}</strong></div><div class="metric"><div class="eyebrow">Known open commercial value</div><strong>${money(o.known_open_commercial_value_usd)}</strong><p>${esc(label(o.value_status))}</p></div></section>
  ${o.commercial_values.map(v=>`<div class="line-row"><div>${esc(label(v.value_type))} · ${money(v.usd_normalized)}<div class="small">${esc(label(v.status))} · ${v.selected_for_open_value?'Included in D’s open value':'Not included in open commercial value'}${v.value_type==='pilot_fee'?' · Pilot fees do not count as commercial Actual':''}</div></div>${evidenceButton(v.evidence_ids,'Value evidence')}</div>`).join('')}<p class="small">Values are shown individually. Alternatives are not summed. Unknown USD remains unknown.</p>
  <div class="two-col"><section><h2>Observed event timeline</h2>${o.event_timeline.map(e=>`<div class="timeline-row"><span class="small">${date(e.event_date)}</span><div>${esc(label(e.event_type))}<p class="small">${esc(label(e.verification))}</p></div>${evidenceButton(e.evidence_ids,'Evidence')}</div>`).join('')||'<p class="empty">No dated events linked. No earlier milestones have been inferred.</p>'}</section><section><h2>Review & evidence</h2><p>${o.review_ids.length} linked review items. ${o.supporting_evidence_ids.length} supporting evidence references.</p><p>${evidenceButton(o.supporting_evidence_ids,'Inspect supporting excerpts')}</p>${o.conflicting_evidence_ids.length?evidenceButton(o.conflicting_evidence_ids,'Conflicting evidence'):''}<a href="#review/opportunity/${esc(id)}">Open linked reviews →</a></section></div>`;
}
function weekly(selected) {
  const weeks=data.weekly_snapshots;
  const s=weeks.find(w=>w.week_end===selected)||weeks.at(-1);
  const map=new Map(Object.entries(s.retrospective_event_state.opportunities));
  return `${heading('03','Weekly movement','A change log reconstructed from dated evidence. Journey, economic changes and risk remain separate.')}<div class="toolbar"><label>Week ending · ${esc(data.manifest.timezone)}<select id="week-select">${weeks.map(w=>`<option value="${w.week_end}" ${w===s?'selected':''}>${date(w.week_end)} · ${w.movement.count} changes</option>`).join('')}</select></label><span class="result-count">${weeks.length} published weekly snapshots</span></div>
  <div class="weeks" aria-label="Choose a published week">${weeks.map(w=>`<button class="week" data-week="${w.week_end}" aria-label="${date(w.week_end)}: ${w.movement.count} changes" title="${date(w.week_end)} · ${w.movement.count} changes" aria-pressed="${w===s}">${'<span></span>'.repeat(w.movement.count)}</button>`).join('')}</div><div class="week-labels"><span>${date(weeks[0].week_end)}</span><span>Each mark = one published change</span><span>${date(weeks.at(-1).week_end)}</span></div>
  <div class="note"><strong>Retrospective reconstruction.</strong> Historical knowledge quality: ${esc(label(s.historical_knowledge_quality))}. The source timestamps do not establish what was known at the time. Current stage labels are not used to reconstruct history.</div>
  <div class="section-head"><h2>Week ending ${date(s.week_end)}</h2><span class="small">Verified Actual: ${money(s.retrospective_event_state.verified_actual_usd)}</span></div><p class="small">${s.movement_baseline==='first_snapshot_no_prior_comparison'?'First snapshot; no previous-week comparison.':'Compared with the previous published reporting week.'} “First appears” describes inclusion in this reconstruction, not a newly won account.</p><div class="movement-grid four">${movementCards(s.movement,map,s.week_end)}${beliefChangesCard(data.belief_states.weekly.find(w=>w.week_end===s.week_end)?.changes||[],opportunityMap,s.week_end)}</div>`;
}
let reviewPage=0;
function review(group,opportunityId) {
  return `${heading('04','A working queue of open questions.','Preserved uncertainty, ready for a human decision. Signature checks are listed first; the queue does not assign a financial risk score. This snapshot is read-only.')}<div class="toolbar"><label>Search issues, accounts or exact evidence<input id="review-search" type="search" placeholder="Search, e.g. SIGNED or 580"></label><label>Review category<select id="review-group"><option value="">All categories</option>${GROUPS.map(g=>`<option value="${esc(g)}" ${g===group?'selected':''}>${g} (${allReviews(data).filter(r=>reviewGroup(r)===g).length})</option>`).join('')}</select></label><label>Opportunity<select id="review-op"><option value="">All opportunities</option><option value="unlinked">Unlinked / outside dated population</option>${data.opportunities.map(o=>`<option value="${o.opportunity_id}" ${o.opportunity_id===opportunityId?'selected':''}>${esc(o.account_label)} · ${esc(o.scope_label)}</option>`).join('')}</select></label><label class="check"><input id="review-informational" type="checkbox"> Include informational items</label></div><p class="small">By default only items that need a human decision are listed (decision_needed: contract verification, structure-changing identity, material value conflicts, contested inferred states). Informational items stay available for audit. Unlinked claims may lack resolved identity, scope or date. A signature claim here has not entered Verified Actual. Materiality is unknown unless supplied.</p><div id="review-count" class="small" role="status"></div><div id="review-rows"></div><div class="pagination"><button id="previous-page">← Previous</button><span id="page-label" class="small"></span><button id="next-page">Next →</button></div>`;
}
function renderReviewRows() {
  const q=$('#review-search').value.toLowerCase(),g=$('#review-group').value,oid=$('#review-op').value,include=$('#review-informational').checked;
  const all=allReviews(data);
  const matching=all.filter(r=>(!g||reviewGroup(r)===g)&&(!oid||(oid==='unlinked'?!r.opportunity_id:r.opportunity_id===oid))&&[reviewTitle(r),r.required_action,opportunityMap.get(r.opportunity_id)?.account_label,...r.evidence_ids.map(id=>evidenceMap.get(id)?.exact_excerpt)].join(' ').toLowerCase().includes(q)).sort((a,b)=>GROUPS.indexOf(reviewGroup(a))-GROUPS.indexOf(reviewGroup(b)));
  const rows=visibleReviews(matching,data,include), hidden=matching.length-rows.length;
  const pages=Math.max(1,Math.ceil(rows.length/20)); reviewPage=Math.min(reviewPage,pages-1);
  $('#review-count').textContent=`${rows.length} of ${all.length} review items · ${include?'all triage levels':'decision needed only'}${hidden?` · ${hidden} informational hidden`:''}`;
  $('#review-rows').innerHTML=rows.slice(reviewPage*20,(reviewPage+1)*20).map(r=>`<article class="review-item"><div><div class="eyebrow">${esc(reviewGroup(r))}</div><p>${r.opportunity_id?`<a href="${opportunityHref(r.opportunity_id)}">${esc(opportunityMap.get(r.opportunity_id)?.account_label)}</a>`:'Unlinked / outside dated population'}</p>${badge(r.status)}</div><div><h3>${esc(reviewTitle(r))}</h3><p class="action">${esc(r.required_action)}</p><p class="small">Financial materiality: ${money(r.financial_materiality_usd)}</p>${triageHtml(triageFor(r,data))}</div><div>${evidenceButton(r.evidence_ids,'Inspect evidence')}<p class="small">${r.evidence_ids.length} linked references</p></div></article>`).join('')||'<p class="empty">No review items match these filters.</p>';
  $('#page-label').textContent=`Page ${reviewPage+1} of ${pages}`; $('#previous-page').disabled=reviewPage===0; $('#next-page').disabled=reviewPage>=pages-1;
}
function triageHtml(t) {
  if (!t) return '<p class="small triage">Not triaged · treated as needing a decision</p>';
  return `<p class="small triage"><span class="chip ${t.decision_needed?'needed':''}">${t.decision_needed?'Decision needed':'Informational'}</span> ${esc(beliefLabel(t.category))} — ${esc(t.rationale)}</p>`;
}
function showEvidence(ids) {
  $('#evidence-content').innerHTML=ids.map(id=>{
    const e=evidenceMap.get(id); if(!e) return '<p>Evidence reference unavailable.</p>';
    return `<article class="evidence"><div class="eyebrow">${esc(label(e.source_type))} · ${date(e.business_date)}</div><h3>${esc(e.title || 'Source excerpt')}</h3><div>${badge(e.verification_status,'pending')} ${badge(e.claim_status)}</div><blockquote>${esc(e.exact_excerpt)}</blockquote><p class="small">Documented: ${date(e.documented_at)}. First seen: ${date(e.source_first_seen_at)}. Collection time does not establish the business date.</p><details><summary>Source reference</summary><p class="reference">Source: ${esc(e.source_system)}<br>Reference: ${esc(e.reference)}<br>Evidence: ${esc(e.evidence_id)}</p></details></article>`;
  }).join(''); $('#evidence-dialog').showModal();
}
function methodologySnapshot(snapshot) {
  return {
    opportunities:snapshot.opportunities.length,
    provisional:snapshot.opportunity_details.filter(o=>o.resolution_status==='provisional').length,
    events:new Set(snapshot.opportunity_details.flatMap(o=>o.event_ids)).size,
    values:new Set(snapshot.opportunity_details.flatMap(o=>o.commercial_values.map(v=>v.value_id))).size,
    weeks:snapshot.weekly_snapshots.length,
    reviews:snapshot.review_queue.length,
    actual:snapshot.overview.verified_signed_acv_usd
  };
}
function beliefMethod(b) {
  if (!b) return '';
  const p=b.provenance, r=b.review_summary;
  return `<section class="method-section method-belief" aria-label="Inferred commercial state"><div class="eyebrow">06 / Inferred commercial state</div><h2>Observed <span aria-hidden="true">→</span> Inferred <span aria-hidden="true">→</span> Verified.</h2>
  <p>Exact excerpts become <strong>atomic signals</strong>: a meeting held, a pilot scope agreed, data received, a price discussed, a budget frozen. Each signal keeps its date, its modality (completed, planned, conditional, negated…), its extraction method and its evidence. A belief engine combines signals over time into <strong>inferred states</strong> — pilot status, buyer and technical commitment, procurement, commercial status, blockers, momentum and engagement — each with a confidence band and an explanation of the signals for and against.</p>
  <div class="method-pair"><section><h3>Who does what</h3><p>GPT-6 Luna extracts candidate signals with exact quotes. Jev is a narrow sensor: it answers bounded questions about one cited span and can move one signal by at most one band. Deterministic rules are mechanical: dates, cadence, inactivity and modality guards that can only weaken a statement. The engine combines signals; it never verifies.</p></section>
  <section><h3>Confidence bands are not probabilities</h3><p>${esc(b.ontology?.confidence_semantics || 'Bands summarise heuristic support points; they are ordinal labels, not calibrated probabilities.')}</p><p class="small">Planned is not executed; a conditional statement is not a commitment; contradictory or stale evidence lowers the band.</p></section></div>
  <p><strong>Verification stays separate.</strong> Only the documentary contract gate feeds the documentary-verified figure. The recognised figure uses the belief layer’s reasoning under the explicit rule in section 07; inferred state bands and counts are never themselves money. Review asks for a human decision only where the answer changes recognised value, opportunity structure or a contested inferred state: ${esc(r.decision_needed)} of ${esc(r.total)} items in this snapshot; the others are kept as informational audit records.</p>
  ${p?`<div class="note" data-testid="belief-provenance"><strong>About this demo’s inferred states.</strong> ${esc(p.sensor)}. The canonical database behind the frozen snapshot is not shipped, so signals were derived offline by a deterministic language sensor from the published exact excerpts, event timeline and commercial values of each displayed opportunity. Live runs use Luna and Jev as described above.</div>`:''}</section>`;
}
function flowBox(x,y,w,h,cls,title,sub) {
  const lines=[title,sub].filter(Boolean), mid=y+h/2-(lines.length-1)*9;
  return `<g class="fc-${cls}"><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="4"/>${lines.map((t,i)=>`<text x="${x+w/2}" y="${mid+i*19}" class="${i?'fc-sub':'fc-title'}" text-anchor="middle" dominant-baseline="middle">${esc(t)}</text>`).join('')}</g>`;
}
function flowArrow(d,labelText,lx,ly) { return `<path class="fc-arrow" d="${d}" marker-end="url(#fc-head)"/>${labelText?`<text class="fc-label" x="${lx}" y="${ly}">${esc(labelText)}</text>`:''}`; }
// The mechanism as a flow chart; amounts come from the published snapshot.
function flowChart(snapshot) {
  const v=valuationOf(snapshot), steps=[
    ['Sources','Notion meeting notes and Airtable CRM records are read without modification.'],
    ['Evidence','Every statement is kept as an exact excerpt of an immutable, hashed source snapshot.'],
    ['Extraction','Luna proposes atomic signals with modality; Jev answers narrow sensor questions; rules extract dates, amounts and cadence and can only weaken a statement.'],
    ['Observed','Atomic signals: type, date, modality, method and exact evidence.'],
    ['Reconstruction','Unlinked notes are linked into deals by rare shared anchors; names alone never link.'],
    ['Inferred','The belief engine combines signals over time into states with confidence bands and reasons for and against.'],
    ['Decision','Reported signed with a high, uncontested band, one stated annual amount and a date in the target window?'],
    ['Yes','Signed ACV recognised by reasoning (headline).'],['No','Estimate: stated value, else pilot fee × corpus ratio, else corpus median.'],
    ['Separately','The documentary gate gives the stricter verified figure; review asks only decision-relevant questions.']];
  return `<section class="method-section method-flow" aria-label="Mechanism flow chart"><div class="eyebrow">The mechanism at a glance</div><h2>From a sentence in a note to a number on the overview.</h2>
  <div class="flow-wrap"><svg class="flow-chart" viewBox="0 0 1000 724" role="img" aria-labelledby="flow-title"><title id="flow-title">Flow from sources through evidence, extraction, signals, reconstruction and the belief engine to recognised signed ACV or an estimate, with the documentary gate and review shown separately</title>
  <defs><marker id="fc-head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="fc-head"/></marker></defs>
  ${flowBox(200,10,260,50,'source','Notion','meeting notes')}${flowBox(540,10,260,50,'source','Airtable','CRM records')}
  ${flowArrow('M330,60 L420,98')}${flowArrow('M670,60 L580,98')}
  ${flowBox(250,100,500,56,'node','Exact evidence excerpts','immutable snapshots · hashes · exact spans')}
  ${flowArrow('M440,156 L185,198')}${flowArrow('M500,156 L500,198')}${flowArrow('M560,156 L815,198')}
  ${flowBox(40,200,290,70,'model','GPT-6 Luna · medium reasoning','atomic signals + modality, exact quotes')}
  ${flowBox(355,200,290,70,'model','Jev · narrow sensor','plan vs execution · real blocker · commitment')}
  ${flowBox(670,200,290,70,'rule','Deterministic rules','dates · amounts · cadence · modality guards')}
  ${flowArrow('M185,270 L400,308')}${flowArrow('M500,270 L500,308')}${flowArrow('M815,270 L600,308')}
  ${flowBox(250,310,500,56,'observed','OBSERVED · atomic signals','type · date · modality · method · evidence')}
  ${flowArrow('M420,366 L190,408')}${flowArrow('M560,366 L570,408')}
  ${flowBox(40,410,300,70,'node','Deal reconstruction','links unlinked notes by rare shared anchors')}
  ${flowArrow('M340,445 L378,445')}
  ${flowBox(380,410,380,70,'inferred','INFERRED · belief engine','combines signals over time → states + bands')}
  ${flowArrow('M760,445 L788,445')}
  ${flowBox(790,410,180,70,'gate','Review triage','decision-needed only')}
  ${flowArrow('M570,480 L570,493')}
  <g class="fc-decision"><path d="M570,493 L830,550 L570,607 L310,550 Z"/><text x="570" y="541" class="fc-title" text-anchor="middle">Reported signed · high band · uncontested</text><text x="570" y="562" class="fc-sub" text-anchor="middle">one annual amount · date in target window?</text></g>
  ${flowArrow('M310,550 L285,550 L285,626','yes',293,592)}${flowArrow('M830,550 L860,550 L860,626','no',868,592)}
  ${flowBox(140,628,290,72,'out','Signed ACV — recognised',v?money(v.recognized_signed_acv_usd)+' · headline':'headline figure')}
  ${flowBox(640,628,340,72,'estimate','Estimate · not signed',v?money(v.estimated_open_pipeline_usd)+' open · '+money(v.weighted_pipeline_usd)+' weighted':'stated → pilot × ratio → median')}
  ${flowArrow('M750,128 L988,128 L988,712 L535,712 L535,702')}
  ${flowBox(450,628,170,72,'gate','Documentary gate',v?money(v.documentary_verified_usd)+' verified':'stricter, separate')}
  </svg></div>
  <p class="small">${evidenceButton(uniqueIds(recognisedValuations(snapshot).map(d=>d.valuation.evidence_ids||[])),'Why? Inspect the evidence behind the recognised figure')}</p>
  <ol class="flow-steps">${steps.map(([k,t])=>`<li><strong>${esc(k)}.</strong> ${esc(t)}</li>`).join('')}</ol></section>`;
}
function methodology(snapshot=data) {
  const s=methodologySnapshot(snapshot);
  const evidence=new Map(snapshot.evidence_summaries.map(e=>[e.evidence_id,e]));
  const example=snapshot.review_queue.filter(r=>/reported.*signature/.test(r.reason)).flatMap(r=>r.evidence_ids.map(id=>evidence.get(id))).find(e=>e && /^SIGNED\./i.test(e.exact_excerpt) && e.verification_status==='unverified');
  const stages=[['Sources','Notion + Airtable'],['Ingest','Evidence ingestion'],['Extract','Semantic extraction'],['Organize','Canonical business state'],['Infer','Belief layer'],['Value','Recognition & estimates'],['Measure','Quantitative read model'],['Explore','Product']];
  return `<article id="how-it-works" class="methodology">
  ${heading('05','How the GTM tracker works',"A B2B team's GTM evidence is spread across structured CRM records and qualitative meeting notes, most of it soft. The system turns that evidence into observed signals, reasons over them to infer the commercial state, and values deals from context — with every conclusion traceable to exact evidence and the stricter documentary gate kept visible.")}
  <p class="small">A five-minute guide · Evidence, inference and economics</p>
  <ol class="architecture" aria-label="Sources, evidence ingestion, semantic extraction, canonical business state, belief layer, recognition and estimates, quantitative read model, product">${stages.map(([stage,title])=>`<li><span class="eyebrow">${stage}</span><strong>${title}</strong></li>`).join('')}</ol>
  <section class="method-principle" aria-label="Core methodological principle"><h2>Observed <span aria-hidden="true">→</span> Inferred <span aria-hidden="true">→</span> Valued</h2><p>Models extract observations from exact text. A belief engine reasons over combinations of those observations — partial, soft evidence is accepted when the reasons are coherent and reproducible — and deterministic code does the arithmetic. Excess verification is treated as a failure mode; documentary verification is still reported, separately.</p></section>
  ${flowChart(snapshot)}

  <section class="method-section"><div class="eyebrow">01 / The problem</div><h2>Measure progress without manufacturing certainty.</h2>
  <p>The tracker measures weekly go-to-market (GTM) progress against ${money(snapshot.overview.target.amount_usd)} in new signed commercial annual contract value (ACV), by ${date(snapshot.overview.target.deadline)}. Much of the evidence lives in conversations, not neatly filled CRM fields.</p>
  <ol class="sales-context" aria-label="Typical commercial journey">${['Conference encounter','Follow-up','Scoping','Pilot','Commercial deployment'].map(x=>`<li>${x}</li>`).join('')}</ol>
  <p>Airtable supplies useful CRM evidence, but it is a current snapshot. Notion meeting notes contain richer detail; the sources can disagree. Missing historical stage records cannot safely be reconstructed. <strong>CRM stage ≠ historical truth.</strong> The journey above describes a typical path, not an assumed sequence for every opportunity.</p></section>

  <section class="method-section"><div class="eyebrow">02 / From source to product</div><h2>One chain of evidence. Separate responsibilities.</h2>
  <dl class="stage-explanations">
  <div><dt>Evidence ingestion</dt><dd>Notion and Airtable records become immutable, provider-neutral evidence. Original content, IDs, dates and provenance remain auditable; source transport is separated from business meaning.</dd></div>
  <div><dt>Semantic extraction</dt><dd>Deterministic parsing and identity candidates give the extractor context. Claims, events, values and atomic signals (with modality: completed, planned, conditional, negated…) are proposed and checked against the source text.</dd></div>
  <div><dt>Canonical business state</dt><dd>Accepted evidence enters a shared business model with its provenance. Signals that lack typed details are kept as signals instead of being discarded or sent to review.</dd></div>
  <div><dt>Belief layer</dt><dd>Signals are combined over time into inferred states with confidence bands; unlinked notes are reconstructed into deals by shared distinctive anchors; signatures are recognised by reasoning and open deals are estimated from context.</dd></div>
  <div><dt>Quantitative read model</dt><dd>The saved canonical state becomes a dated, reconciled read model and weekly snapshots. Published values and evidence references form the presentation contract.</dd></div>
  <div><dt>This product</dt><dd>These pages display the read model’s frozen snapshot. Search, filters and evidence navigation run locally; opening the product does not rerun extraction, reinterpret evidence or recalculate commercial state.</dd></div>
  </dl>
  <div class="method-pair"><section><h3>GPT-6 Luna · Structured extraction</h3><p>The low-cost semantic extractor identifies source-supported candidates: accounts and contacts; opportunity, use case and scope; events; commercial values; qualitative signals; and relations.</p><p>It returns exact supporting text. Python locates that quote in the submitted chunk, maps it back to the original source string, and validates the coordinates. The model does not calculate character offsets.</p><p class="small">Luna runs with medium reasoning effort. It cannot verify contracts, calculate ACV or currency conversions, invent canonical IDs, or infer missing milestones; inference happens in the belief engine.</p></section>
  <section><h3>Jev · Narrow sensor</h3><p>Jev answers bounded questions about one cited span: is this a plan or execution, conditional or current, a real blocker or only a risk, a commitment or only interest, has procurement started. It is not the main parser and never decides a state on its own.</p><p>A reading can move one signal by at most one confidence band or weaken its modality; repeated calls record agreement. The belief engine needs several independent signals for a high band.</p><p class="small">These readings measure statement stability. They are not commercial forecasts or probabilities of closing a sale.</p></section></div>
  <p>Ordinary Python handles exact-source validation, source mapping, IDs, dates, deduplication, arithmetic, currency conversion under defined rules, gates, referential integrity and persistence. Missing facts remain missing.</p></section>

  <section class="method-section"><div class="eyebrow">03 / The business model</div><h2>One account can contain several opportunities.</h2>
  <p class="method-equation">Opportunity = Account × Use Case × Commercial Scope</p>
  <p>A CRM Deal is a source record, not automatically the canonical business object. Different use cases, pilot scopes and rollout alternatives must remain distinct until the evidence supports linking them.</p>
  <details><summary>The objects behind the tracker</summary><dl class="concepts">${[['Account / Contact','The organization and people involved; uncertain identity links remain unresolved.'],['Opportunity','A specific account, use case and commercial scope.'],['Event / Claim','An observed occurrence or a source assertion, with its supporting evidence and status.'],['Commercial Value','An amount with its type, currency, period, scope and verification state.'],['Evidence','The exact source excerpt and provenance behind a material statement.'],['Conflict / Review Item','Contradictory evidence or a specific question that requires a decision.']].map(([k,v])=>`<div><dt>${k}</dt><dd>${v}</dd></div>`).join('')}</dl></details>
  <p>Events distinguish follow-up and scoping, pilot verbal yes, statement-of-work drafting or sending, pilot signature, technical milestones, procurement/legal work, commercial proposals and commercial signature. Lost, stalled and revived are distinct states.</p>
  <p><strong>A later milestone does not imply that earlier milestones occurred.</strong> Negated, conditional, hypothetical or planned statements are not completed events. Uncertain claims remain labelled; current CRM stage never fills gaps in historical journey evidence.</p></section>

  <section class="method-section"><div class="eyebrow">04 / Reading the commercial numbers</div><h2>Different kinds of value answer different questions.</h2>
  <div class="table-wrap"><table class="method-table"><thead><tr><th>Measure</th><th>Meaning</th></tr></thead><tbody>
  <tr><td>Signed ACV — recognised by reasoning</td><td>Commercial ACV whose signature the belief layer supports with high confidence: reported signature, coherent corroborating chain, stated annual amount and currency, signature date in the target window. This is the headline figure.</td></tr>
  <tr><td>Documentary-verified (Verified Actual)</td><td>Commercial ACV backed by the required documentary or authorized verification evidence. The stricter gate, always shown under the recognised figure and never added to it.</td></tr>
  <tr><td>Estimated and weighted pipeline</td><td>Values estimated from context with a basis and range, and a heuristic stage weighting of them. Not signed, not a forecast, never added to signed ACV.</td></tr>
  <tr><td>Reported signed, pending verification</td><td>A source reports a commercial signature, but the verification gate has not cleared. Kept separate from Actual.</td></tr>
  <tr><td>Open commercial value</td><td>The known eligible commercial value associated with open opportunities. This is a known-value subset, not a complete valuation of all activity.</td></tr>
  <tr><td>Unknown</td><td>The value or its eligibility is unresolved. <strong>Unknown ≠ $0.</strong></td></tr>
  <tr><td>Proxy / sensitivity measure</td><td>Progression-weighted values explore sensitivity. They are not probabilities, expected revenue or forecasts, and are not added to Actual.</td></tr>
  </tbody></table></div>
  <p>Current signed ACV recognised by reasoning is <strong data-testid="method-recognised">${money(valuationOf(snapshot)?.recognized_signed_acv_usd)}</strong>. Current documentary-verified Actual is <strong data-testid="method-actual">${money(s.actual)}</strong>: the stricter gate's contribution published in this snapshot. Neither figure includes estimates. Pilot fees do not become commercial ACV; mutually exclusive alternatives are not summed.</p>
  ${example?`<aside class="method-example"><div class="eyebrow">A real source example · account unnamed</div><h3>A signature report still needs verification.</h3><blockquote>${esc(example.exact_excerpt)}</blockquote><p>A source can report a signature and commercial price while documentary verification is still missing. This excerpt is marked <strong>unverified</strong>. Reporting, review and documentary verification are separate steps; the report does not enter the documentary-verified figure. With a coherent corroborating chain it can still be recognised by reasoning (section 07), with its reasons shown.</p><p>Its business date is ${example.business_date?esc(date(example.business_date)):'unknown'}. An undated report can remain in Review without appearing in the dated opportunity population.</p>${evidenceButton([example.evidence_id],'Inspect the source evidence')}</aside>`:''}</section>

  <section class="method-section"><div class="eyebrow">05 / Review and uncertainty</div><h2>Keep the question visible until it is resolved.</h2>
  <p>Soft evidence alone never creates a review task. Every item is kept for audit, but the queue shows by default only questions whose answer changes recognised value, opportunity structure or a contested inferred state; the rest are informational.</p>
  <p>Each material state can be traced through a claim, event or value to an exact supporting excerpt. Human documentary verification remains necessary where the commercial gate requires it. <a href="#review">Explore the review queue →</a></p></section>

  ${beliefMethod(snapshot.belief_states)}

  ${valuationMethod(snapshot)}

  <section class="method-section method-snapshot"><div class="eyebrow">08 / Current demo snapshot · ${date(snapshot.manifest.business_as_of)}</div><h2>What this product actually contains</h2>
  <dl class="facts"><div><dt>Dated opportunities</dt><dd data-testid="method-opportunities">${s.opportunities}</dd></div><div><dt>Provisional identities</dt><dd>${s.provisional} of ${s.opportunities}</dd></div><div><dt>Weekly snapshots</dt><dd data-testid="method-weeks">${s.weeks}</dd></div><div><dt>Linked events / values</dt><dd>${s.events} / ${s.values}</dd></div><div><dt>Evidence references</dt><dd>${snapshot.evidence_summaries.length}</dd></div><div><dt>Review items</dt><dd>${s.reviews}</dd></div></dl>
  <p class="small">These counts come from the current published snapshot. They describe the dated product population, not full-corpus extraction or all canonical records; those upstream totals are not published in this contract.</p>
  <h3>Limits of this snapshot</h3><p>Provisional identity and scope need review. Some evidence lacks a usable date or resolved link, so source coverage and dated display coverage differ. Weekly movement is a retrospective reconstruction; historical knowledge quality is ${esc(label(snapshot.manifest.historical_knowledge_quality)).toLowerCase()}. Neither later milestones nor collection timestamps prove what was known earlier.</p></section>

  <details class="method-tools"><summary>Tools and responsibilities</summary><div class="table-wrap"><table class="method-table"><thead><tr><th>Tool</th><th>Role</th><th>Not trusted to do</th></tr></thead><tbody>${[['Airtable','CRM source evidence','Define complete historical truth'],['Notion','Qualitative meeting-note evidence','Determine business state directly'],['GPT-6 Luna','Structured semantic extraction','Verify contracts or forecast sales'],['Jev','Narrow sensor questions about one cited span','Decide a state alone or forecast revenue'],['Belief engine','Combine signals into inferred states, reconstruct deals, recognise and estimate value','Hide its reasons or alter source evidence'],['Python','Validation, reconciliation, arithmetic and persistence','Invent qualitative facts'],['SQLite','Canonical and read-model persistence','Interpret evidence']].map(row=>`<tr>${row.map(c=>`<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table></div></details>
  <p class="method-return"><a href="#overview">Return to the operating overview →</a></p>
  </article>`;
}
function render() {
  const [view,arg,arg2]=(location.hash.slice(1)||'overview').split('/').map(decodeURIComponent);
  const active=view==='opportunity'||view==='reconstructed'?'opportunities':view;
  document.querySelectorAll('nav a').forEach(a=>{ if(a.hash==='#'+active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current'); });
  const content=$('#content');
  if(view==='overview') content.innerHTML=overview();
  else if(view==='how-it-works') content.innerHTML=methodology();
  else if(view==='opportunities') {content.innerHTML=opportunities(); renderOpportunityRows(); $('#op-search').oninput=renderOpportunityRows; $('#op-lifecycle').onchange=renderOpportunityRows;}
  else if(view==='opportunity') content.innerHTML=detail(arg,arg2);
  else if(view==='reconstructed') content.innerHTML=reconstructedDetail(arg,data);
  else if(view==='weekly') {content.innerHTML=weekly(arg); $('#week-select').onchange=e=>location.hash='weekly/'+e.target.value;}
  else if(view==='review') {reviewPage=0;content.innerHTML=review(arg,arg==='opportunity'?arg2:null);renderReviewRows();['review-search','review-group','review-op','review-informational'].forEach(id=>$('#'+id).addEventListener(id==='review-search'?'input':'change',()=>{reviewPage=0;renderReviewRows();}));$('#previous-page').onclick=()=>{reviewPage--;renderReviewRows();};$('#next-page').onclick=()=>{reviewPage++;renderReviewRows();};}
  else content.innerHTML=heading('','View not found','Use the navigation to return to the operating notebook.');
  window.scrollTo(0,0);
}
async function init() {
  try {
    async function read(name) {const r=await fetch(RUNTIME+name+'.json',{cache:'no-store'}); if(!r.ok)throw new Error('Snapshot file unavailable');const p=await r.json();if(p.schema_version!=='presentation_v1')throw new Error('Unsupported snapshot version');return p;}
    const manifest=await read('manifest');
    const payloads=await Promise.all(FILES.map(read));
    data={manifest}; FILES.forEach((name,i)=>{if(payloads[i].kind!==name)throw new Error('Snapshot file mismatch');data[name]=payloads[i].data;});
    opportunityMap=new Map(data.opportunity_details.map(o=>[o.opportunity_id,o])); evidenceMap=new Map(data.evidence_summaries.map(e=>[e.evidence_id,e]));
    $('#as-of').textContent='As of '+date(manifest.business_as_of)+' · Retrospective';
    $('#snapshot-label').textContent='Read-only · '+manifest.schema_version+' · '+manifest.revision_id.slice(0,8);
    document.addEventListener('click',e=>{const b=e.target.closest('[data-evidence]');if(b)showEvidence(b.dataset.evidence.split('|'));const w=e.target.closest('[data-week]');if(w)location.hash='weekly/'+w.dataset.week;});
    $('#close-evidence').onclick=()=>$('#evidence-dialog').close(); window.addEventListener('hashchange',render);render();
  } catch(error) { $('#content').innerHTML='<h1>Snapshot unavailable</h1><p>The local presentation snapshot could not be loaded. No substitute business data is shown.</p><p>Run the offline presentation validator and serve this product over localhost.</p>'; console.error(error.message); }
}
if(typeof module!=='undefined')module.exports={money,label,esc,reviewGroup,reviewTitle,journeyStates,movementCards,opportunityHref,methodologySnapshot,methodology,FILES,
  DIMENSIONS,beliefLabel,bandChip,headlineHtml,beliefStateHtml,observedHtml,verifiedHtml,oivSection,weeklyBeliefHtml,beliefChangesCard,
  inferredOverview,questionsPanel,beliefMethod,triageFor,triageHtml,decisionNeeded,allReviews,visibleReviews,
  valuationOf,valuationLabel,isRecognised,valuationKind,recognisedValuations,recognisedHeadline,estimatesHtml,valuationHtml,contextLinksHtml,
  reconstructedTable,reconstructedDetail,reconstructedHref,linkageHtml,valuationMethod,anchorText};
if(typeof document!=='undefined')init();
