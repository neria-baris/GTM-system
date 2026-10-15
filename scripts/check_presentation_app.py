"""Offline static build gate; deliberately imports no business pipeline modules."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_FILES = ("overview", "opportunities", "opportunity_details", "weekly_snapshots", "evidence_summaries", "review_queue")
BELIEF_FILE = "belief_states"
EVIDENCE_KEYS = {"evidence_ids", "strongest_evidence_ids", "supporting_evidence_ids", "contradicting_evidence_ids"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def seller_names() -> list[str]:
    """Organisation names from config/tracker.json; the frontend must stay data-driven."""
    config = ROOT / "config/tracker.json"
    seller = json.loads(config.read_text(encoding="utf-8")).get("seller", {}) if config.is_file() else {}
    return [n for n in [seller.get("name"), *seller.get("aliases", [])] if n]


def check(app: Path, runtime: Path, report: Path | None = None) -> dict:
    files = {name: (app / name).read_text(encoding="utf-8")
             for name in ("index.html", "app.js", "styles.css")}
    html, js, css = (files[k] for k in ("index.html", "app.js", "styles.css"))
    for view in ("overview", "opportunities", "weekly", "review", "how-it-works"):
        require(f'href="#{view}"' in html, f"Missing navigation: {view}")
    require("../demo/" in js, "Missing D-only data boundary")
    require(len(re.findall(r"\bfetch\s*\(", js)) == 1, "Unreviewed data loading path")
    require("fetch(RUNTIME+name+'.json'" in js, "Unreviewed fetch destination")
    require(not re.search(r"outputs/(A2|C2|C)/|data/raw|canonical_state|api\.(openai|notion)|api_key|integrate_full_corpus", js, re.I), "Upstream dependency in frontend")
    require(not re.search(r"https?://|@import", html + js + css), "External runtime dependency")
    require(not re.search(r"\b(?:5000000|649600|377|888)\b|\$5M|Coldharbour|Westra", js), "Hardcoded sample business result")
    require(not any(name.casefold() in (html + js).casefold() for name in seller_names()), "Hardcoded organisation name")
    require("observed:detail.observed_milestones.includes(key)" in js, "Journey must use explicit observed membership")
    require(not re.search(r"indexOf\([^\n]+[<>]=?[^\n]+indexOf", js), "Journey backfill logic")
    require("Sensitivity proxy — not a forecast" in js, "Missing proxy distinction")
    require("money(o.verified_signed_acv_usd)" in js, "Actual must render D's aggregate")
    require(not re.search(r"verified\w*\s*\+|\+\s*.*heuristic_proxy", js), "Combined Actual/proxy")
    for key in ("data-evidence", "exact_excerpt", "verification_status", "showModal"):
        require(key in js, f"Missing evidence affordance: {key}")
    for token in ("--paper", "--ink", "--accent", "--serif", "--line"):
        require(token in css, f"Missing brand token {token}")
    # Observed -> Inferred -> Verified must stay visibly separate in the product.
    require(re.search(r"const FILES\s*=\s*\[[^\]]*'belief_states'", js) is not None, "Missing belief_states in FILES")
    require('data-section="observed-inferred-verified"' in js, "Missing Observed/Inferred/Verified section")
    for marker in ("Observed → Inferred → Verified", "Inferred · not verified", "Verified · documentary gate only"):
        require(marker in js, f"Missing belief distinction marker: {marker}")
    require('id="review-informational"' in js and "decision_needed" in js and "visibleReviews(" in js,
            "Missing decision-needed review filter")
    require("Inferred commercial state — not verified, not a forecast" in js, "Missing inferred overview label")
    # Reasoned recognition is the headline; the stricter documentary figure stays directly visible.
    require("Signed ACV — recognised by reasoning" in js, "Missing recognised headline label")
    require("belief_states.overview.valuation" in js and "money(v.recognized_signed_acv_usd)" in js,
            "Recognised headline must render the belief layer's published aggregate")
    require(re.search(r"Documentary-verified: (?:<[^>]*>)?\$\{money\(o\.verified_signed_acv_usd\)\}", js) is not None,
            "Missing documentary-verified line")
    require("Weighted pipeline · heuristic stage weighting" in js and "Not a forecast and not a probability" in js,
            "Weighted pipeline must be labelled as heuristic, not a forecast")
    require(not re.search(r"(?:recognized_signed_acv_usd|estimated_open_pipeline_usd|weighted_pipeline_usd|weighted_usd)\)?\s*[-+*/]\s*[\w(.]"
                          r"|[\w)\]]\s*[-+*/]\s*[\w.?]*\.(?:recognized_signed_acv_usd|estimated_open_pipeline_usd|weighted_pipeline_usd|weighted_usd)\b",
                          js), "Frontend arithmetic on recognised/estimated/weighted figures")
    for marker in ('data-section="valuation"', "Linked by context: ", 'data-section="reconstructed-deals"',
                   "Reconstructed deals (inferred from context)", "reconstructed_opportunities", "'#reconstructed/'",
                   "view==='reconstructed'", 'data-testid="reconstructed-note"', "Inferred from context"):
        require(marker in js, f"Missing valuation/reconstruction affordance: {marker}")
    node = shutil.which("node")
    if node:
        subprocess.run([node, "--check", str(app / "app.js")], check=True, capture_output=True)
        syntax = "passed"
    else:
        require(os.environ.get("GTM_NODE_OPTIONAL") == "1",
                "Node is required for local JavaScript syntax verification")
        syntax = "skipped_node_unavailable"
    manifest = json.loads((runtime / "manifest.json").read_text(encoding="utf-8"))
    require(manifest["schema_version"] == "presentation_v1", "Contract version mismatch")
    data = {}
    require(f"{BELIEF_FILE}.json" in manifest["files"], "Missing belief_states contract file")
    for name, expected in manifest["files"].items():
        require(name in {n + ".json" for n in CONTRACT_FILES + (BELIEF_FILE,)}, "Unexpected contract file")
        raw = (runtime / name).read_bytes()
        require(hashlib.sha256(raw).hexdigest() == expected, "D snapshot hash mismatch")
        data[name[:-5]] = json.loads(raw)["data"]
    ids = {o["opportunity_id"] for o in data["opportunities"]}
    require(bool(ids) and ids == {o["opportunity_id"] for o in data["opportunity_details"]}, "Opportunity reconciliation failed")
    evidence = {e["evidence_id"] for e in data["evidence_summaries"]}
    require(all(e in evidence for r in data["review_queue"] for e in r["evidence_ids"]), "Broken review evidence")
    beliefs = check_beliefs(data, ids, evidence)
    return {"passed": True, "gate": "offline_static_build", "snapshot_id": manifest["snapshot_id"],
            "opportunities": len(ids), "weekly_snapshots": len(data["weekly_snapshots"]),
            "evidence_references": len(evidence), "review_items": len(data["review_queue"]),
            "verified_actual_usd": data["overview"]["verified_signed_acv_usd"],
            "belief_states": beliefs, "javascript_syntax_check": syntax,
            "external_runtime_dependencies": [], "upstream_rerun": False,
            "browser_validation": "See browser_smoke_report.json; this gate is structural only"}


def _evidence_refs(value, found: set[str]) -> set[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in EVIDENCE_KEYS and isinstance(nested, list):
                found.update(nested)
            else:
                _evidence_refs(nested, found)
    elif isinstance(value, list):
        for nested in value:
            _evidence_refs(nested, found)
    return found


def check_beliefs(data: dict, ids: set[str], evidence: set[str]) -> dict:
    belief = data[BELIEF_FILE]
    require(set(belief["opportunities"]) == ids, "Belief opportunities do not reconcile with opportunities")
    refs = _evidence_refs(belief, set())
    require(refs <= evidence, "Belief file references unpublished evidence")
    review_ids = {r["review_id"] for r in data["review_queue"]} | {r["review_id"] for r in belief["belief_review_items"]}
    require(set(belief["review_triage"]) == review_ids, "Review triage does not cover every review item")
    for oid, entry in belief["opportunities"].items():
        for dimension, state in entry["current"]["states"].items():
            require(state.get("inferred") is True, f"Belief state not labelled inferred: {dimension}")
            require(not state.get("verified") or state["value"] == "verified_signed", "Inferred state marked verified")
    buckets = belief["overview"]["value_buckets"]
    require(buckets["verified_actual_usd"] == data["overview"]["verified_signed_acv_usd"], "Belief layer changed Verified Actual")
    needed = sum(1 for t in belief["review_triage"].values() if t["decision_needed"])
    require(needed == belief["review_summary"]["decision_needed"], "Review triage summary mismatch")
    return {"opportunities": len(belief["opportunities"]), "evidence_references": len(refs),
            "decision_needed_reviews": needed, "review_items": len(belief["review_triage"]),
            "valuation": check_valuations(belief, data, ids, evidence)}


VALUATION_KINDS = {"recognized_signed_acv", "estimate", "unknown"}
ESTIMATE_BASES = {"stated_rollout_value", "pilot_fee_times_corpus_ratio", "corpus_median_rollout"}


def _usd(value, message):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(message) from None


def _check_valuation(where: str, v: dict | None, evidence: set[str]) -> None:
    if v is None:
        return
    require(v.get("kind") in VALUATION_KINDS, f"Unknown valuation kind: {where}")
    require(set(v.get("evidence_ids") or []) <= evidence, f"Valuation references unpublished evidence: {where}")
    if v["kind"] == "estimate":
        require(v.get("basis") in ESTIMATE_BASES, f"Estimate without a known basis: {where}")
        amount = _usd(v.get("amount_usd"), f"Estimate without amount: {where}")
        low, high = (_usd(x, f"Estimate without range: {where}") for x in v.get("range_usd") or [None, None])
        require(low <= amount <= high, f"Estimate outside its range: {where}")
        require(v.get("band") and v.get("reasons"), f"Estimate without band or reasons: {where}")
        _usd(v.get("weighted_usd"), f"Estimate without heuristic weighting: {where}")
    elif v["kind"] == "recognized_signed_acv":
        require(bool(v.get("evidence_ids")) and bool(v.get("reasons")), f"Recognition without evidence/reasons: {where}")
        if v.get("recognized"):
            _usd(v.get("amount_usd"), f"Recognised valuation without amount: {where}")
    else:
        require(v.get("amount_usd") is None, f"Unknown valuation carries an amount: {where}")


def check_valuations(belief: dict, data: dict, ids: set[str], evidence: set[str]) -> dict | str:
    """Recognised / documentary / estimate figures and reconstructed deals, when the belief layer publishes them."""
    totals = belief["overview"].get("valuation")
    reconstructed = belief.get("reconstructed_opportunities") or {}
    for oid, entry in belief["opportunities"].items():
        _check_valuation(f"opportunity {oid}", entry.get("valuation"), evidence)
        require(all(isinstance(g, str) for g in entry.get("context_links") or []), f"Malformed context links: {oid}")
    for cid, r in reconstructed.items():
        require(r.get("cluster_id") == cid and cid not in ids, f"Reconstructed deal collides with an opportunity: {cid}")
        require(r.get("status") == "inferred_from_context", f"Reconstructed deal not labelled inferred: {cid}")
        refs = _evidence_refs(r, set()) | {c.get("evidence_id") for c in r.get("corroboration") or []}
        require(refs <= evidence, f"Reconstructed deal references unpublished evidence: {cid}")
        require({l.get("group") for l in r.get("links") or []} <= set(r.get("groups") or []), f"Link outside deal: {cid}")
        for dimension, state in (r.get("current") or {}).get("states", {}).items():
            require(state.get("inferred") is True, f"Reconstructed state not labelled inferred: {cid} {dimension}")
        _check_valuation(f"reconstructed {cid}", r.get("valuation"), evidence)
    if totals is None:
        require(not reconstructed, "Reconstructed deals published without valuation totals")
        return "not_published"
    recognised = [v for v in [e.get("valuation") for e in belief["opportunities"].values()]
                  + [r.get("valuation") for r in reconstructed.values()]
                  if v and v.get("kind") == "recognized_signed_acv" and v.get("recognized")]
    total = sum((_usd(v["amount_usd"], "Recognised amount") for v in recognised), Decimal(0))
    require(_usd(totals["recognized_signed_acv_usd"], "Recognised total") == total
            and totals["recognized_deal_count"] == len(recognised),
            "Recognised signed ACV does not reconcile with recognised valuations (estimates must not be included)")
    require(totals["documentary_verified_usd"] == data["overview"]["verified_signed_acv_usd"],
            "Documentary-verified figure differs from the read model")
    point = _usd(totals["estimated_open_pipeline_usd"], "Estimated pipeline")
    low, high = (_usd(x, "Estimated pipeline range") for x in totals["estimated_open_pipeline_range_usd"])
    require(low <= point <= high, "Estimated pipeline outside its range")
    require(_usd(totals["weighted_pipeline_usd"], "Weighted pipeline") <= point, "Weighted pipeline exceeds estimates")
    require(set(totals.get("estimate_count_by_basis") or {}) <= ESTIMATE_BASES, "Unknown estimate basis")
    return {"recognized_signed_acv_usd": totals["recognized_signed_acv_usd"], "recognized_deals": len(recognised),
            "documentary_verified_usd": totals["documentary_verified_usd"], "reconstructed_deals": len(reconstructed)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = check(args.app, args.runtime)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        shutil.copy2(args.output, args.output.with_name(args.output.name + "." + stamp + ".bak"))
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
