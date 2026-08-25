"""
E4 (Day 5 AM) -- robustness spot-checks. Three short, independent checks; each
ships its own result note "however preliminary," per the spec's own gate --
none of these feed back into the mined constraint sets or repair.

Usage: python experimental/mining/e4_robustness.py
Writes: experimental/mining/results/e4_robustness.json, .md;
        results/cm_sprint_runs.jsonl (tag=E4)
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from kgrepair.constraints.model import Constraint, ConstraintSet  # noqa: E402
from kgrepair.ntriples import load_ntriples_file                   # noqa: E402
from kgrepair.synthetic import synthetic_constraints                # noqa: E402
from kgrepair.validator import Validator                            # noqa: E402

from experimental.mining.e1_recovery import _matches, _signature      # noqa: E402
from experimental.mining.log import log_run                           # noqa: E402
from experimental.mining.miner import build_index, mine_prevalence     # noqa: E402

REAL = os.path.join(ROOT, "fixtures", "real")
SYNTHETIC = os.path.join(ROOT, "fixtures", "synthetic")
CANDIDATES_DIR = os.path.join(os.path.dirname(__file__), "candidates")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
MIN_SUPPORT = 20
THRESHOLDS = [0.99, 0.95, 0.90]


def _load_mined_cs(slice_name: str, threshold: float) -> ConstraintSet:
    path = os.path.join(CANDIDATES_DIR, f"{slice_name}_{threshold:.2f}.json")
    with open(path, encoding="utf-8") as fh:
        dicts = json.load(fh)
    cs = ConstraintSet(f"mined@{slice_name}@{threshold:.2f}")
    for d in dicts:
        cs.add(Constraint.from_dict(d))
    return cs


 
# 4a. cross-source transfer: wikidata-geography mined set -> dbpedia geography
 

def check_cross_source_transfer() -> Dict:
    mined_cs = _load_mined_cs("real_wikidata_geography_10000", 0.90)
    dbpedia_g = load_ntriples_file(os.path.join(REAL, "real_dbpedia_geography_1000.nt"))

    val = Validator(dbpedia_g, use_closure=True)
    total_witnesses = 0
    for c in mined_cs:
        total_witnesses += val.check_one(c).count

    # No trivial predicate/value mapping exists for the general set (Wikidata
    # wdt:/wd: identifiers do not occur in a DBpedia graph at all -- confirmed
    # above by the near-guaranteed zero witness count, not assumed). The ONE
    # exception: E1 found `geo.wd.req.city_country` (City requires P17/country)
    # was mining's cleanest recovery. Its DBpedia analogue is a plausible,
    # genuinely trivial one-rule mapping (dbo:Settlement requires dbo:country),
    # attempted here as the one worthwhile transfer candidate.
    mapped = Constraint(
        cid="mapped.geo.req.settlement_country", domain="geography", kg="dbpedia",
        kind="requires_statement", tier="ptime_core", provenance="mined+mapped",
        direction="superset",
        antecedent='< down(rdf:type) . down(rdfs:subClassOf)* . [val("dbo:Settlement")] >',
        consequent="< down(dbo:country) >",
        note="hand-mapped from the ONE cleanly-recovered wikidata rule "
             "(City requires wdt:P17) -- wd:Q515->dbo:Settlement, wdt:P17->dbo:country")
    mapped_witnesses = val.check_one(mapped).count

    return {
        "raw_transfer": {
            "mined_constraint_count": len(mined_cs),
            "total_witnesses_on_dbpedia": total_witnesses,
            "note": ("every mined constraint uses wdt:/wd: identifiers; a DBpedia "
                    "graph uses dbo:/dbr:/rdf:/rdfs: -- zero syntactic overlap is "
                    "expected and is what near-zero witnesses here confirms, not "
                    "evidence of DBpedia's own consistency"),
        },
        "one_trivial_mapping_attempted": {
            "constraint": mapped.to_dict(), "witnesses_on_dbpedia": mapped_witnesses,
            "verdict": ("holds (0 witnesses) -- the one cleanly-recovered wikidata "
                       "rule's DBpedia analogue is also consistent on this slice"
                       if mapped_witnesses == 0 else
                       f"{mapped_witnesses} witness(es) -- does NOT hold as-is on "
                       "this DBpedia slice"),
        },
    }


 
# 4b. clean-baseline sanity: yago taxa, train-slice + held-out-rung check
 

def check_clean_baseline_sanity() -> Dict:
    mined_cs = _load_mined_cs("real_yago_taxa_1000", 0.90)
    out = {"mined_constraint_count": len(mined_cs), "checks": []}
    for slice_name, role in (("real_yago_taxa_1000", "training slice (in-sample)"),
                             ("real_yago_taxa_10000", "held-out rung (out-of-sample)")):
        path = os.path.join(REAL, f"{slice_name}.nt")
        if not os.path.exists(path):
            out["checks"].append({"slice": slice_name, "role": role, "status": "MISSING"})
            continue
        g = load_ntriples_file(path)
        val = Validator(g, use_closure=True)
        rows = [{"cid": c.cid, "witnesses": val.check_one(c).count} for c in mined_cs]
        total = sum(r["witnesses"] for r in rows)
        out["checks"].append({"slice": slice_name, "role": role, "V": len(g.nodes),
                              "total_witnesses": total, "per_constraint": rows})
    return out


 
# 4c. synthetic control: exact recovery against a KNOWN ground-truth set
 

def check_synthetic_control() -> Dict:
    slice_name = "synthetic_geoLike_1k_s0"
    g = load_ntriples_file(os.path.join(SYNTHETIC, f"{slice_name}.nt"))
    idx = build_index(g, "synthetic", min_support=MIN_SUPPORT)
    by_threshold = mine_prevalence(idx, domain="synthetic_geography",
                                   thresholds=THRESHOLDS, min_support=MIN_SUPPORT)

    truth = synthetic_constraints()
    rows = []
    for t in THRESHOLDS:
        cand_dicts = [{"kind": m.kind, "containment": {"phi": m.antecedent, "psi": m.consequent}}
                     for m in by_threshold[t]]
        for c in truth:
            preds, vals = _signature(c.antecedent, c.consequent)
            recovered = any(_matches(m, c.kind, preds, vals) for m in cand_dicts)
            rows.append({"threshold": f"{t:.2f}", "cid": c.cid, "kind": c.kind,
                        "recovered": recovered})
    by_t_summary = {
        f"{t:.2f}": {
            "recovered": sum(1 for r in rows if r["threshold"] == f"{t:.2f}" and r["recovered"]),
            "total_true_constraints": len(truth),
            "mined_candidate_count": len(by_threshold[t]),
        } for t in THRESHOLDS
    }
    return {"slice": slice_name, "true_constraint_count": len(truth),
           "by_threshold": by_t_summary, "per_constraint": rows}


def main() -> None:
    os.makedirs(RESULTS_DIR, exist_ok=True)

    cross = check_cross_source_transfer()
    run_id_a = log_run("E4", {"check": "cross_source_transfer", "result": cross})
    print("=== 4a. cross-source transfer ===")
    print(json.dumps(cross, indent=2))

    baseline = check_clean_baseline_sanity()
    run_id_b = log_run("E4", {"check": "clean_baseline_sanity", "result": baseline})
    print("\n=== 4b. clean-baseline sanity (yago taxa) ===")
    print(json.dumps(baseline, indent=2))

    synth = check_synthetic_control()
    run_id_c = log_run("E4", {"check": "synthetic_control", "result": synth})
    print("\n=== 4c. synthetic control ===")
    print(json.dumps(synth, indent=2))

    out = {"cross_source_transfer": {**cross, "run_id": run_id_a},
          "clean_baseline_sanity": {**baseline, "run_id": run_id_b},
          "synthetic_control": {**synth, "run_id": run_id_c}}
    out_path = os.path.join(RESULTS_DIR, "e4_robustness.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, sort_keys=True)
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
