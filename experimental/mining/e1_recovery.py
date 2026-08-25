"""
E1 (Day 2) -- recovery evaluation: mined vs hand-curated v1 AND v2.

Matching definition (stated explicitly, since it decides every number below):
a hand-curated ptime_core constraint H is "recovered" at threshold t if some
mined candidate M at that threshold shares H's `kind` AND at least one predicate
AND at least one class value with H. Two flavours are tracked separately:

  recovered_base      -- overlaps H's ORIGINAL (v1) class value(s)
  recovered_v2_added   -- overlaps a class value v2 added that v1 did NOT have
                         (only meaningful for the 7 constraints C1 touched)

A curated constraint whose `kind` is not one of the four shapes E0's miner can
even propose (typing_inheritance, functional, symmetric, inverse, safety_edge)
is marked `out_of_search_space` -- a structurally different verdict from
"missed": the miner cannot recover it at ANY threshold, not just this one.

Usage: python experimental/mining/e1_recovery.py
Writes: experimental/mining/results/e1_recovery.json,
        experimental/mining/results/e1_recovery.md
        results/cm_sprint_runs.jsonl (one record per slice)
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Dict, FrozenSet, List, Optional, Tuple

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from kgrepair import constraints as constraints_pkg          # noqa: E402
from kgrepair.constraints.model import Constraint             # noqa: E402
from kgrepair.pipeline.fetch import PoliteFetcher              # noqa: E402

from experimental.mining.labels import resolve_labels          # noqa: E402
from experimental.mining.log import log_run                    # noqa: E402

CANDIDATES_DIR = os.path.join(os.path.dirname(__file__), "candidates")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
THRESHOLDS = [0.99, 0.95, 0.90]

MINEABLE_KINDS = {"existential_domain", "existential_range",
                  "requires_statement", "typing_existence"}

# (slice basename, domain, kg, has_v2)
SLICES = [
    ("real_yago_taxa_1000", "taxa", "yago", False),
    ("real_wikidata_anatomy_1000_typed", "anatomy", "wikidata", True),
    ("real_wikidata_medication_1000_typed", "medication", "wikidata", True),
    ("real_wikidata_geography_10000", "geography", "wikidata", False),
]

_PRED_RE = re.compile(r"(?:down|up)\(([^)]+)\)")
_VAL_RE = re.compile(r'val\("([^"]+)"\)')


def _signature(antecedent: str, consequent: str) -> Tuple[FrozenSet[str], FrozenSet[str]]:
    text = antecedent + " " + consequent
    return frozenset(_PRED_RE.findall(text)), frozenset(_VAL_RE.findall(text))


def _load_candidates(slice_name: str, threshold: float) -> List[Dict]:
    path = os.path.join(CANDIDATES_DIR, f"{slice_name}_{threshold:.2f}.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _matches(cand: Dict, kind: str, preds: FrozenSet[str], vals: FrozenSet[str]) -> bool:
    if cand["kind"] != kind:
        return False
    cpreds, cvals = _signature(cand["containment"]["phi"], cand["containment"]["psi"])
    return bool(cpreds & preds) and bool(cvals & vals)


def _curated_ptime_core(domain: str, kg: str) -> List[Constraint]:
    cs = constraints_pkg.get(domain, kg, version=1)
    return [c for c in cs if c.tier == "ptime_core"]


def _curated_v2(domain: str, kg: str) -> Dict[str, Constraint]:
    """v1_cid -> v2 Constraint, for constraints C1 actually touched (cid suffix
    '.v2' convention from src/kgrepair/constraints/biomedical_v2.py)."""
    cs = constraints_pkg.get(domain, kg, version=2)
    return {c.cid[: -len(".v2")]: c for c in cs if c.cid.endswith(".v2")}


def evaluate_slice(slice_name: str, domain: str, kg: str, has_v2: bool) -> Dict:
    curated = _curated_ptime_core(domain, kg)
    v2_by_v1_cid = _curated_v2(domain, kg) if has_v2 else {}

    by_threshold_cands = {t: _load_candidates(slice_name, t) for t in THRESHOLDS}
    all_curated_preds_vals = [
        _signature(c.antecedent, c.consequent) for c in curated
    ] + [_signature(c.antecedent, c.consequent) for c in v2_by_v1_cid.values()]

    per_constraint = []
    for c in curated:
        row = {"cid": c.cid, "kind": c.kind, "mineable": c.kind in MINEABLE_KINDS,
              "by_threshold": {}}
        preds_v1, vals_v1 = _signature(c.antecedent, c.consequent)
        v2c = v2_by_v1_cid.get(c.cid)
        vals_v2_added = frozenset()
        if v2c is not None:
            _preds_v2, vals_v2 = _signature(v2c.antecedent, v2c.consequent)
            vals_v2_added = vals_v2 - vals_v1

        for t in THRESHOLDS:
            if c.kind not in MINEABLE_KINDS:
                row["by_threshold"][f"{t:.2f}"] = "out_of_search_space"
                continue
            cands = by_threshold_cands[t]
            recovered_base = any(_matches(m, c.kind, preds_v1, vals_v1) for m in cands)
            recovered_v2_added = bool(vals_v2_added) and any(
                _matches(m, c.kind, preds_v1, vals_v2_added) for m in cands)
            if recovered_base and recovered_v2_added:
                verdict = "recovered_base_and_v2_added"
            elif recovered_base:
                verdict = "recovered_base_only"
            elif recovered_v2_added:
                verdict = "recovered_v2_added_only"
            else:
                verdict = "missed"
            row["by_threshold"][f"{t:.2f}"] = verdict
        per_constraint.append(row)

    # novelty: mined candidates matching NO curated signature (v1 or v2) at all
    novelty_by_threshold = {}
    for t in THRESHOLDS:
        novel = []
        for m in by_threshold_cands[t]:
            mpreds, mvals = _signature(m["containment"]["phi"], m["containment"]["psi"])
            matched_any = any(
                bool(mpreds & preds) and bool(mvals & vals)
                for (preds, vals) in all_curated_preds_vals
            )
            if not matched_any:
                novel.append(m)
        novelty_by_threshold[f"{t:.2f}"] = novel

    recovery_counts = {}
    for t in THRESHOLDS:
        key = f"{t:.2f}"
        verdicts = [r["by_threshold"].get(key) for r in per_constraint]
        recovery_counts[key] = {
            "recovered_base": sum(1 for v in verdicts
                                  if v in ("recovered_base_only", "recovered_base_and_v2_added")),
            "recovered_v2_added": sum(1 for v in verdicts
                                      if v in ("recovered_v2_added_only", "recovered_base_and_v2_added")),
            "missed": sum(1 for v in verdicts if v == "missed"),
            "out_of_search_space": sum(1 for v in verdicts if v == "out_of_search_space"),
            "novel_count": len(novelty_by_threshold[key]),
        }

    return {
        "slice": slice_name, "domain": domain, "kg": kg,
        "per_constraint": per_constraint,
        "recovery_counts": recovery_counts,
        "novel_candidates": {t: [m["cid"] for m in cands]
                            for t, cands in novelty_by_threshold.items()},
        "_novel_raw": novelty_by_threshold,
    }


def main() -> None:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    results = []
    for slice_name, domain, kg, has_v2 in SLICES:
        res = evaluate_slice(slice_name, domain, kg, has_v2)
        run_id = log_run("E1", {
            "slice": slice_name, "domain": domain, "kg": kg,
            "recovery_counts": res["recovery_counts"],
        })
        res["run_id"] = run_id
        results.append(res)

    # novelty sampling + label resolution (lowest threshold = richest candidate set)
    fetcher = PoliteFetcher()
    lowest = f"{min(THRESHOLDS):.2f}"
    novelty_labels = {}
    for res in results:
        novel_at_lowest = res["_novel_raw"][lowest]
        distinct_vals = []
        seen = set()
        for m in novel_at_lowest:
            _preds, vals = _signature(m["containment"]["phi"], m["containment"]["psi"])
            for v in vals:
                if v not in seen and v.startswith("wd:"):
                    seen.add(v)
                    distinct_vals.append(v)
        sample_vals = distinct_vals[:5]
        labels = resolve_labels(sample_vals, fetcher=fetcher) if sample_vals else {}
        novelty_labels[res["slice"]] = labels

    out = {
        "results": [{k: v for k, v in r.items() if k != "_novel_raw"} for r in results],
        "novelty_label_sample": novelty_labels,
    }
    out_path = os.path.join(RESULTS_DIR, "e1_recovery.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, sort_keys=True)
    print(f"wrote {out_path}")

    for res in results:
        print(f"\n{res['slice']} ({res['kg']}/{res['domain']}) run_id={res['run_id']}")
        for t, counts in res["recovery_counts"].items():
            print(f"  threshold={t}  {counts}")
        print(f"  novelty label sample: {novelty_labels[res['slice']]}")


if __name__ == "__main__":
    main()
