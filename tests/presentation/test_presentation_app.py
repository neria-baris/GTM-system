"""Negative/non-inference checks for the D-only presentation consumer."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

ROOT = Path(__file__).resolve().parents[2]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_offline_build():
    result = module("check_presentation_app").check(ROOT / "app", ROOT / "demo")
    assert result["passed"]
    assert result["opportunities"] > 0


@pytest.mark.parametrize("old,new", [
    ("../demo/", "../outputs/C2/"),
    ("observed:detail.observed_milestones.includes(key)", "observed:true"),
    ("Sensitivity proxy — not a forecast", "Expected revenue"),
    ("money(o.verified_signed_acv_usd)", "money(649600)"),
    ("exact_excerpt", "hidden_excerpt"),
    ('data-section="observed-inferred-verified"', 'data-section="combined"'),
    ("'review_queue', 'belief_states'", "'review_queue'"),
    ('id="review-informational"', 'id="review-all"'),
    ("Inferred · not verified", "Likely"),
    # Policy: recognised headline from the belief layer, documentary line kept, reconstructed deals visible.
    ("Documentary-verified: ", "Verified: "),
    ("money(v.recognized_signed_acv_usd)", "money(v.estimated_open_pipeline_usd)"),
    ("Signed ACV — recognised by reasoning", "Signed ACV"),
    ('data-section="reconstructed-deals"', 'data-section="other-deals"'),
    ("Reconstructed deals (inferred from context)", "More deals"),
    ("view==='reconstructed'", "view==='inferred'"),
    ('data-testid="reconstructed-note"', 'data-testid="note"'),
    ("Weighted pipeline · heuristic stage weighting", "Expected pipeline"),
    ('data-section="valuation"', 'data-section="value"'),
])
def test_build_rejects_semantic_regressions(tmp_path, old, new):
    app = tmp_path / "app"
    shutil.copytree(ROOT / "app", app)
    p = app / "app.js"
    p.write_text(p.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    with pytest.raises(ValueError):
        module("check_presentation_app").check(app, ROOT / "demo")


def test_javascript_semantics():
    code = r"""
    const assert=require('node:assert/strict'),fs=require('node:fs');
    const app=require('./app/app.js');
    const read=n=>JSON.parse(fs.readFileSync('demo/'+n+'.json')).data;
    assert.equal(app.money(null),'Unknown'); assert.equal(app.money(undefined),'Unknown');
    assert.notEqual(app.money('0'),'Unknown'); assert.equal(app.money('bogus'),'Unknown');
    const onlyLater={observed_milestones:['pilot_signed'],furthest_evidenced_journey_milestone:'pilot_signed'};
    assert.deepEqual(app.journeyStates(onlyLater).filter(s=>s.observed).map(s=>s.key),['pilot_signed']);
    assert(!app.journeyStates(onlyLater).find(s=>s.key==='encounter').observed);
    assert(app.label('signed_reported').includes('unverified'));
    assert.equal(app.esc('<script>'), '&lt;script&gt;');
    const details=read('opportunity_details');
    for(const o of details){
      assert.deepEqual(app.journeyStates(o).filter(s=>s.observed).map(s=>s.key).sort(),[...o.observed_milestones].sort());
      assert.equal(app.money(o.known_open_commercial_value_usd),'Unknown');
      assert.equal(o.verified_actual_usd,'0');
    }
    const reviews=read('review_queue');
    for(const r of reviews) assert(!/\b(llm|jev|semantic)\b/i.test(app.reviewTitle(r)));
    assert.equal(read('overview').verified_signed_acv_usd,'0');
    // Data-driven formatting: do not freeze the audited zero into the UI.
    assert.equal(app.money('1234.50'),'$1,234.5');
    assert(app.opportunityHref('id','2026-01-04').endsWith('/2026-01-04'));
    """
    result = subprocess.run([shutil.which("node"), "-e", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_server_exposes_only_product_and_contract():
    server_module = __import__("runtime.server", fromlist=["Handler"])
    server_module.verify_release()
    server = ThreadingHTTPServer(("127.0.0.1", 0), server_module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/app/") as r:
            assert r.status == 200
            assert "default-src 'none'" in r.headers["Content-Security-Policy"]
        with urlopen(base + "/") as r:
            assert r.url.endswith("/app/")
        with urlopen(base + "/demo/overview.json") as r:
            assert json.load(r)["kind"] == "overview"
        with urlopen(base + "/demo/belief_states.json") as r:
            assert json.load(r)["kind"] == "belief_states"
        for path in ("/.env", "/state/pipeline.json", "/data/raw/", "/outputs/C/canonical_state.sqlite",
                     "/app/../.env", "/app/%2e%2e/.env", "/app/app.js.bak", "/scripts/serve_product.py"):
            with pytest.raises(HTTPError) as error:
                urlopen(base + path)
            assert error.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_methodology_renders_published_counts_without_mutation():
    code = r"""
    const assert=require('node:assert/strict'),fs=require('node:fs');
    const app=require('./app/app.js');
    const snapshot={manifest:JSON.parse(fs.readFileSync('demo/manifest.json'))};
    for(const name of app.FILES) snapshot[name]=JSON.parse(fs.readFileSync('demo/'+name+'.json')).data;
    const original=JSON.stringify(snapshot), metrics=app.methodologySnapshot(snapshot);
    assert.equal(metrics.opportunities,snapshot.opportunities.length);
    assert.equal(metrics.weeks,snapshot.weekly_snapshots.length);
    assert.equal(metrics.actual,snapshot.overview.verified_signed_acv_usd);
    const html=app.methodology(snapshot);
    assert(html.includes('How the GTM tracker works'));
    assert(html.includes('GPT-6 Luna')); assert(html.includes('Jev'));
    assert(html.includes('class="architecture"')); assert(html.includes('data-evidence='));
    assert(html.includes('Unknown ≠ $0')); assert(html.includes('Tools and responsibilities'));
    assert.equal(JSON.stringify(snapshot),original);
    // Counts and money must follow the supplied presentation fixture, not this demo's totals.
    snapshot.opportunities=snapshot.opportunities.slice(0,2);
    snapshot.weekly_snapshots=snapshot.weekly_snapshots.slice(0,3);
    snapshot.overview.verified_signed_acv_usd='1234';
    const changed=app.methodology(snapshot);
    assert(changed.includes('data-testid="method-opportunities">2<'));
    assert(changed.includes('data-testid="method-weeks">3<'));
    assert(changed.includes('data-testid="method-actual">$1,234<'));
    """
    result = subprocess.run([shutil.which("node"), "-e", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_build_requires_top_level_methodology_navigation(tmp_path):
    app = tmp_path / "app"
    shutil.copytree(ROOT / "app", app)
    index = app / "index.html"
    index.write_text(index.read_text(encoding="utf-8").replace('href="#how-it-works"', 'href="#missing"'), encoding="utf-8")
    with pytest.raises(ValueError, match="Missing navigation: how-it-works"):
        module("check_presentation_app").check(app, ROOT / "demo")


def test_belief_rendering_keeps_observed_inferred_verified_separate():
    code = r"""
    const assert=require('node:assert/strict'),fs=require('node:fs');
    const app=require('./app/app.js');
    const snap={manifest:JSON.parse(fs.readFileSync('demo/manifest.json'))};
    for(const name of app.FILES) snap[name]=JSON.parse(fs.readFileSync('demo/'+name+'.json')).data;
    const b=snap.belief_states, details=new Map(snap.opportunity_details.map(o=>[o.opportunity_id,o]));
    const clean=html=>html.replace(/unverified|not verified|verification|Verified · documentary gate only|Verified Actual/gi,'');
    assert.deepEqual(Object.keys(b.opportunities).sort(),snap.opportunities.map(o=>o.opportunity_id).sort());
    for(const [id,entry] of Object.entries(b.opportunities)){
      const o=details.get(id), html=app.oivSection(entry,o);
      assert(html.includes('data-section="observed-inferred-verified"'));
      assert(html.includes('Observed · atomic signals')&&html.includes('Inferred · not verified')&&html.includes('Verified · documentary gate only'));
      // Verified column renders the published per-opportunity Actual, unchanged.
      assert(html.includes('data-testid="detail-verified-actual">'+app.money(o.verified_actual_usd)+'<'));
      for(const [dim,s] of Object.entries(entry.current.states)){
        assert.equal(s.inferred,true);
        const one=app.beliefStateHtml(dim,s);
        if(!s.verified) assert(!/verified/i.test(clean(one)),dim+': '+one);
        if(s.band) assert(one.includes('Why?'));
      }
      assert(!/verified/i.test(clean(app.headlineHtml(entry))));
      assert(!/[$€£]/.test(app.headlineHtml(entry)));
    }
    // A forged inferred 'verified_signed' state without gate verification is never shown as verified.
    const forged={value:'verified_signed',band:'very_high',verified:false,supporting:[],contradicting:[],missing_expected:[],
      explanation:'forged',support_points:9,opposition_points:0,model_dependence:'high',caps_applied:[]};
    assert(!/verified/i.test(clean(app.beliefStateHtml('commercial_status',forged))));
    assert(!/verified/i.test(clean(app.headlineHtml({headline:{parts:[{dimension:'commercial_status',value:'verified_signed',band:'very_high'}]}}))));
    // Inferred portfolio counts never carry money; Verified Actual stays the published aggregate.
    const row=app.inferredOverview(b);
    assert(row.includes('not verified, not a forecast')); assert(!/[$€£]/.test(row));
    assert.equal(b.overview.value_buckets.verified_actual_usd,snap.overview.verified_signed_acv_usd);
    assert.equal(app.money(snap.overview.verified_signed_acv_usd),'$0');
    // Review: default list is exactly the decision-needed items; informational items stay available.
    const all=app.allReviews(snap);
    assert.equal(app.visibleReviews(all,snap,false).length,b.review_summary.decision_needed);
    assert.equal(app.visibleReviews(all,snap,true).length,b.review_summary.total);
    assert(b.review_summary.decision_needed<all.length);
    const panel=app.questionsPanel(snap);
    assert(panel.includes('data-testid="decision-needed">'+b.review_summary.decision_needed+'<'));
    assert(panel.includes('data-testid="informational">'+b.review_summary.informational+'<'));
    for(const r of all) assert(app.triageHtml(app.triageFor(r,snap)).includes(app.esc(app.triageFor(r,snap).rationale)));
    // Weekly: a fourth card lists inferred changes, labelled as inferred.
    const week=b.weekly.find(w=>w.changes.length), opps=new Map(snap.opportunity_details.map(o=>[o.opportunity_id,o]));
    const card=app.beliefChangesCard(week.changes,opps,week.week_end);
    assert(card.includes('Inferred, not verified')); assert.equal((card.match(/class="change"/g)||[]).length,week.changes.length);
    const id=Object.keys(week.retrospective)[0];
    assert(app.weeklyBeliefHtml(week,id).includes('Inferred · not verified'));
    // Methodology discloses the belief layer and the demo's offline sensor.
    const method=app.methodology(snap);
    assert(method.includes('not probabilities')); assert(method.includes(app.esc(b.provenance.sensor)));
    assert(method.includes('data-testid="belief-provenance"'));
    """
    result = subprocess.run([shutil.which("node"), "-e", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


DEMO = ROOT / "demo"


def test_offline_belief_builder_is_reproducible_and_complete(tmp_path):
    outputs = []
    for run in ("a", "b"):
        out = tmp_path / f"belief_states_{run}.json"
        subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / "build_demo_beliefs.py"), "--runtime", str(DEMO),
                        "--output", str(out)], cwd=ROOT, check=True, capture_output=True)
        outputs.append(out.read_bytes())
    assert outputs[0] == outputs[1]
    manifest = json.loads((DEMO / "manifest.json").read_text(encoding="utf-8"))
    payload = json.loads(outputs[0])
    data = payload["data"]
    assert payload["kind"] == "belief_states" and payload["schema_version"] == "presentation_v1"
    opportunities = json.loads((DEMO / "opportunities.json").read_text(encoding="utf-8"))["data"]
    assert set(data["opportunities"]) == {o["opportunity_id"] for o in opportunities}
    for entry in data["opportunities"].values():
        assert entry["current"]["states"] and entry["headline"]["text"]
    assert data["provenance"]["derived_from_snapshot_id"] == manifest["snapshot_id"]
    assert "Luna and Jev are not re-run" in data["provenance"]["sensor"]
    for name, digest in data["provenance"]["input_file_sha256"].items():
        assert manifest["files"][name] == digest


def test_build_rejects_tampered_belief_file(tmp_path):
    runtime = tmp_path / "demo"
    shutil.copytree(ROOT / "demo", runtime)
    path = runtime / "belief_states.json"
    path.write_bytes(path.read_bytes().replace(b'"inferred": true', b'"inferred": false', 1))
    with pytest.raises(ValueError, match="hash mismatch"):
        module("check_presentation_app").check(ROOT / "app", runtime)


def test_node_optional_switch(monkeypatch):
    mod = module("check_presentation_app")
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    monkeypatch.delenv("GTM_NODE_OPTIONAL", raising=False)
    with pytest.raises(ValueError, match="Node is required"):
        mod.check(ROOT / "app", ROOT / "demo")
    monkeypatch.setenv("GTM_NODE_OPTIONAL", "1")
    assert mod.check(ROOT / "app", ROOT / "demo")["javascript_syntax_check"] == "skipped_node_unavailable"


def _node(code):
    result = subprocess.run([shutil.which("node"), "-e", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


SNAPSHOT_JS = r"""
const assert=require('node:assert/strict'),fs=require('node:fs');
const app=require('./app/app.js');
const load=()=>{const s={manifest:JSON.parse(fs.readFileSync('demo/manifest.json'))};
  for(const n of app.FILES) s[n]=JSON.parse(fs.readFileSync('demo/'+n+'.json')).data; return s;};
const testid=(html,id)=>{const m=html.match(new RegExp('data-testid="'+id+'">([^<]*)<'));assert(m,'missing '+id);return m[1];};
"""


def test_recognised_headline_follows_published_data_and_excludes_estimates():
    _node(SNAPSHOT_JS + r"""
    const snap=load(), v=app.valuationOf(snap);
    assert(v, 'demo publishes valuation totals');
    const html=app.recognisedHeadline(snap);
    assert(html.includes('Signed ACV — recognised by reasoning'));
    assert.equal(testid(html,'recognised'),app.money(v.recognized_signed_acv_usd));
    assert.notEqual(testid(html,'recognised'),'$0');
    // The stricter documentary line stays directly under the headline and still renders the read model's $0.
    assert.equal(testid(html,'actual'),'$0');
    assert(html.includes('Documentary-verified: <strong data-testid="actual">$0<'));
    assert(html.indexOf('data-testid="recognised"')<html.indexOf('Documentary-verified: '));
    // Why? lists exactly the evidence of the recognised valuations (incl. reconstructed deals).
    const deals=app.recognisedValuations(snap);
    assert.equal(deals.length,v.recognized_deal_count);
    assert(deals.some(d=>d.href.startsWith('#reconstructed/')));
    const why=html.match(/data-evidence="([^"]*)">Why\? View evidence/);
    assert(why); assert.deepEqual(why[1].split('|').sort(),[...new Set(deals.flatMap(d=>d.valuation.evidence_ids))].sort());
    const evidence=new Set(snap.evidence_summaries.map(e=>e.evidence_id));
    for(const id of why[1].split('|')) assert(evidence.has(id));
    // Not hardcoded: the headline follows the fixture.
    v.recognized_signed_acv_usd='1234';
    assert.equal(testid(app.recognisedHeadline(snap),'recognised'),'$1,234');
    // Estimates and weighted values never leak into the recognised or documentary figures.
    v.estimated_open_pipeline_usd='987654321'; v.weighted_pipeline_usd='123456789';
    const after=app.recognisedHeadline(snap);
    assert.equal(testid(after,'recognised'),'$1,234'); assert.equal(testid(after,'actual'),'$0');
    assert(!after.includes(app.money('987654321')) && !after.includes(app.money('123456789')));
    const est=app.estimatesHtml(snap);
    assert.equal(testid(est,'estimated-pipeline'),app.money('987654321'));
    assert.equal(testid(est,'weighted-pipeline'),app.money('123456789'));
    assert(est.includes('heuristic stage weighting') && est.includes('Not a forecast and not a probability'));
    // Absent valuation (e.g. an older live read model): Unknown, never a substitute number.
    delete snap.belief_states.overview.valuation;
    assert.equal(testid(app.recognisedHeadline(snap),'recognised'),'Unknown');
    assert.equal(testid(app.recognisedHeadline(snap),'actual'),'$0');
    """)


def test_valuation_block_and_context_links_render_published_valuations():
    _node(SNAPSHOT_JS + r"""
    const snap=load(), b=snap.belief_states;
    for(const e of Object.values(b.opportunities)){
      const html=app.valuationHtml(e.valuation,e.context_links,snap);
      assert(html.includes('data-section="valuation"'));
      assert.equal(testid(html,'valuation-kind'),app.esc(app.valuationLabel(app.valuationKind(e.valuation))));
      assert.equal(testid(html,'valuation-amount'),app.money(e.valuation.amount_usd));
      const n=e.context_links.length;
      assert(html.includes('Linked by context: '+n+' '+(n===1?'note':'notes')));
      if(n) assert(html.includes('share distinctive anchors'));
      if(e.valuation.kind==='estimate'){
        assert(html.includes('Estimate · not a commitment'));
        assert(html.includes(app.money(e.valuation.range_usd[0])+' – '+app.money(e.valuation.range_usd[1])));
        assert(html.includes('not a probability'));
      }
      if((e.valuation.evidence_ids||[]).length) assert(html.includes('Why? Valuation evidence'));
      for(const r of e.valuation.reasons) assert(html.includes(app.esc(r)));
    }
    assert(app.valuationHtml(null,[],snap).includes('No valuation is published'));
    """)


def test_reconstructed_deals_table_and_route_label_themselves_inferred():
    _node(SNAPSHOT_JS + r"""
    const snap=load(), recon=snap.belief_states.reconstructed_opportunities, ids=Object.keys(recon);
    assert(ids.length>0);
    const table=app.reconstructedTable(snap);
    assert(table.includes('Reconstructed deals (inferred from context)'));
    assert.equal((table.match(/href="#reconstructed\//g)||[]).length,ids.length);
    for(const id of ids) assert(table.includes('href="'+app.reconstructedHref(id)+'"'));
    const evidence=new Set(snap.evidence_summaries.map(e=>e.evidence_id));
    for(const id of ids){
      const r=recon[id], html=app.reconstructedDetail(id,snap);
      assert(html.includes('Reconstructed deal · Inferred from context'));
      assert(html.includes('data-testid="reconstructed-note"') && html.includes('Not a canonical opportunity'));
      assert(html.includes('data-section="observed-inferred-verified"') && html.includes('Inferred · not verified'));
      assert(html.includes('Verified · documentary gate only'));
      assert.equal(testid(html,'reconstructed-documentary'),r.valuation?.documentary_verified?'Yes · documentary gate':'No');
      assert(html.includes('data-section="valuation"') && html.includes('data-section="reconstruction-links"'));
      for(const l of r.links) assert(html.includes('>'+app.esc(l.score)+'<'));
      for(const s of Object.values(r.current.states)) if(s.band) assert(html.includes('Why?'));
      for(const m of html.matchAll(/data-evidence="([^"]*)"/g)) for(const e of m[1].split('|')) assert(evidence.has(e),e);
      if(app.isRecognised(r.valuation)){
        assert(html.includes('part of Signed ACV — recognised by reasoning'));
        assert(r.corroboration.every(c=>html.includes(app.esc(c.text))));
      }
    }
    assert(app.reconstructedDetail('missing',snap).includes('Reconstructed deal unavailable'));
    // Methodology explains recognition vs documentary verification, reconstruction rules and heuristic weights.
    const method=app.valuationMethod(snap);
    for(const t of ['Signed ACV — recognised by reasoning','Documentary-verified','Names alone never link','templates','heuristic, not calibrated'])
      assert(method.includes(t),t);
    assert(app.methodology(snap).includes('data-testid="method-recognised">'+app.money(snap.belief_states.overview.valuation.recognized_signed_acv_usd)+'<'));
    """)


def _tampered_runtime(tmp_path, mutate):
    runtime = tmp_path / "demo"
    shutil.copytree(ROOT / "demo", runtime)
    path = runtime / "belief_states.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload["data"])
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    manifest_path = runtime / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["belief_states.json"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return runtime


def _recognised_deal(data):
    return next(r for r in data["reconstructed_opportunities"].values() if r["valuation"].get("recognized"))


@pytest.mark.parametrize("mutate,match", [
    (lambda d: _recognised_deal(d)["valuation"]["evidence_ids"].append("missing-evidence"), "unpublished evidence"),
    (lambda d: _recognised_deal(d)["corroboration"][0].update(evidence_id="missing-evidence"), "unpublished evidence"),
    (lambda d: next(iter(d["opportunities"].values()))["valuation"]["evidence_ids"].append("missing-evidence"),
     "unpublished evidence"),
    (lambda d: d["overview"]["valuation"].update(
        recognized_signed_acv_usd=d["overview"]["valuation"]["estimated_open_pipeline_usd"]), "Recognised signed ACV"),
    (lambda d: d["overview"]["valuation"].update(documentary_verified_usd="1"), "Documentary-verified"),
    (lambda d: _recognised_deal(d).update(status="canonical"), "not labelled inferred"),
])
def test_build_rejects_inconsistent_valuation_data(tmp_path, mutate, match):
    runtime = _tampered_runtime(tmp_path, mutate)
    with pytest.raises(ValueError, match=match):
        module("check_presentation_app").check(ROOT / "app", runtime)


def test_build_rejects_frontend_arithmetic_on_reasoned_figures(tmp_path):
    app = tmp_path / "app"
    shutil.copytree(ROOT / "app", app)
    p = app / "app.js"
    p.write_text(p.read_text(encoding="utf-8")
                 + "\nfunction bogus(v){return v.recognized_signed_acv_usd+v.weighted_pipeline_usd;}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="arithmetic"):
        module("check_presentation_app").check(app, ROOT / "demo")



def test_published_demo_is_the_validated_live_run():
    manifest = json.loads((ROOT / "demo" / "manifest.json").read_text(encoding="utf-8"))
    data = json.loads((ROOT / "demo" / "belief_states.json").read_text(encoding="utf-8"))["data"]
    assert manifest["source_run_ids"]["a2"] and "Luna" in data["provenance"]["sensors"]
    recognised = [o["valuation"] for o in list(data["opportunities"].values()) + list(data["reconstructed_opportunities"].values())
                  if o["valuation"].get("recognized")]
    assert data["overview"]["valuation"]["recognized_signed_acv_usd"] == str(sum(int(v["amount_usd"]) for v in recognised))
    assert int(data["overview"]["valuation"]["recognized_signed_acv_usd"]) > 0
    assert data["overview"]["valuation"]["documentary_verified_usd"] == json.loads(
        (ROOT / "demo" / "overview.json").read_text(encoding="utf-8"))["data"]["verified_signed_acv_usd"]
