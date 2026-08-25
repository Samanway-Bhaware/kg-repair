"""
E0 (Day 1) driver: run the prevalence miner on the four target slices at three
thresholds, fragment-filter + tier-classify every candidate, serialise survivors
in the real constraint schema, and tabulate raw/fragment-passed/per-tier counts.

Usage: python experimental/mining/run_e0.py
Writes:
  experimental/mining/candidates/<slice>_<threshold>.json   (survivor constraints)
  experimental/mining/results/e0_summary.json                (the tabulation)
  results/cm_sprint_runs.jsonl                                (one record per slice)
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from kgrepair.ntriples import load_ntriples_file   # noqa: E402

from experimental.mining.fragment_filter import filter_candidates   # noqa: E402
from experimental.mining.log import log_run                          # noqa: E402
from experimental.mining.miner import build_index, mine_prevalence   # noqa: E402
from experimental.mining.tier_classifier import classify             # noqa: E402

THRESHOLDS = [0.99, 0.95, 0.90]
MIN_SUPPORT = 20

# The four target slices named in the E0 spec: yago taxa (clean baseline),
# wikidata anatomy + medication (the defect domains -- mined on the T0-corrected
# *_typed slices so the typing spine is complete, matching what D6/D7 use as
# ground truth), wikidata geography (the ontology-gap domain -- the 10k rung is
# the one RC3's "canal" genuine-gap evidence lives in, so it's the more
# informative geography cell for this sprint than the 1k rung).
TARGET_SLICES = [
    "real_yago_taxa_1000",
    "real_wikidata_anatomy_1000_typed",
    "real_wikidata_medication_1000_typed",
    "real_wikidata_geography_10000",
]

REAL_DIR = os.path.join(ROOT, "fixtures", "real")
CANDIDATES_DIR = os.path.join(os.path.dirname(__file__), "candidates")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


def _load_manifest(name: str):
    with open(os.path.join(REAL_DIR, f"{name}.manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)


def run_one_slice(name: str) -> dict:
    manifest = _load_manifest(name)
    kg, domain = manifest["slice_source"], manifest["domain"]
    graph = load_ntriples_file(os.path.join(REAL_DIR, f"{name}.nt"))
    source_slice_hash = manifest.get("content_hash", "")

    idx = build_index(graph, kg, min_support=MIN_SUPPORT)
    by_threshold = mine_prevalence(idx, domain=domain, thresholds=THRESHOLDS,
                                   min_support=MIN_SUPPORT)

    per_threshold_report = {}
    for t in THRESHOLDS:
        raw = by_threshold[t]
        survivors, rejected = filter_candidates(raw)
        tier_counts = {"ptime_core": 0, "boundary": 0}
        serialised = []
        for cand in survivors:
            verdict = classify(cand.kind)
            tier_counts[verdict.tier] += 1
            d = cand.as_constraint_dict(source_slice_hash=source_slice_hash,
                                        min_support=MIN_SUPPORT)
            d["tier"] = verdict.tier
            d["direction"] = verdict.direction
            serialised.append(d)

        out_path = os.path.join(CANDIDATES_DIR, f"{name}_{t:.2f}.json")
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(serialised, fh, indent=2, sort_keys=True)

        by_kind = {}
        for cand in survivors:
            by_kind[cand.kind] = by_kind.get(cand.kind, 0) + 1

        per_threshold_report[f"{t:.2f}"] = {
            "raw": len(raw),
            "fragment_passed": len(survivors),
            "fragment_rejected": len(rejected),
            "by_tier": tier_counts,
            "by_kind": by_kind,
            "candidates_file": os.path.relpath(out_path, ROOT),
        }

    run_id = log_run("E0", {
        "slice": name, "kg": kg, "domain": domain,
        "V": manifest.get("V"), "E": manifest.get("E"),
        "min_support": MIN_SUPPORT, "thresholds": THRESHOLDS,
        "per_threshold": per_threshold_report,
    })
    return {"slice": name, "kg": kg, "domain": domain, "run_id": run_id,
            "per_threshold": per_threshold_report}


def main() -> None:
    os.makedirs(CANDIDATES_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    summary = [run_one_slice(name) for name in TARGET_SLICES]
    out_path = os.path.join(RESULTS_DIR, "e0_summary.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, sort_keys=True)
    print(f"wrote {out_path}")
    for row in summary:
        print(f"\n{row['slice']} ({row['kg']}/{row['domain']}) run_id={row['run_id']}")
        for t, rep in row["per_threshold"].items():
            print(f"  threshold={t}  raw={rep['raw']:4d}  "
                 f"fragment_passed={rep['fragment_passed']:4d}  "
                 f"fragment_rejected={rep['fragment_rejected']:3d}  "
                 f"tier={rep['by_tier']}  kind={rep['by_kind']}")


if __name__ == "__main__":
    main()
