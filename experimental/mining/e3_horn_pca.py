"""
E3 (Day 4, stretch) -- minimal AMIE-style PCA-confidence Horn-rule miner, for the
two rule shapes the fragment can absorb: p(x,y) => C(x) and p(x,y) => C(y).

Incompleteness assumption, stated explicitly (the spec requires this): E0's
miner used the Closed-World Assumption (CWA) -- every x with an outgoing p edge
that ISN'T typed C counts as a negative example of "p(x,y) => C(x)", even if x
has no typing information at all. That conflates "genuinely not C" with "unknown,
just never typed" -- exactly the incompleteness bias E1/E2 kept surfacing.

This miner instead uses AMIE's Partial Completeness Assumption (PCA): an entity
x only counts as a valid negative if x is ALREADY known to have SOME type at all
(x has an outgoing edge on the KG's own typing predicate). An x with zero typing
edges is excluded from both numerator and denominator -- "unknown" is not the
same as "no". Support stays a plain cardinality count (|body & head|), matching
AMIE's own definition, and is tracked separately from confidence so a rule that
is confident but rare is distinguishable from one that is confident and common.

Second deliverable (spec-required): "log rules that exceeded confidence but
failed the fragment filter." E3's own shipped rule shapes are always
expressible (same grammar as E0's), so that inventory would be vacuously empty
if left there. A genuinely richer Horn-rule miner does not stop at single-atom
bodies -- the next natural refinement AMIE-style miners try is a negated
exclusion atom, "p(x,y) AND NOT q(x,_) => C(x)" (x has p, lacks a competing
predicate q, so is even more likely C). This is exactly the shape
`gxpath/parser.py` rejects on sight (needs `!`/negation) -- it is used here
ONLY to populate the inexpressible inventory, never shipped as a candidate,
never fed into repair or the recovery comparison.

Usage: python experimental/mining/e3_horn_pca.py
Writes: experimental/mining/results/e3_horn_pca.json, .md;
        results/cm_sprint_runs.jsonl (tag=E3)
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Set

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from kgrepair import gxpath                        # noqa: E402
from kgrepair.gxpath import ParseError               # noqa: E402
from kgrepair.ntriples import load_ntriples_file      # noqa: E402

from experimental.mining.e1_recovery import (SLICES, THRESHOLDS,          # noqa: E402
                                             _curated_ptime_core, _curated_v2,
                                             _matches, _signature)
from experimental.mining.log import log_run                                # noqa: E402
from experimental.mining.miner import (TYPING_PREDS, Candidate, build_index,  # noqa: E402
                                       mine_prevalence)

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
REAL = os.path.join(ROOT, "fixtures", "real")
MIN_SUPPORT = 20


def _typed_subjects(idx) -> Set[str]:
    type_pred = TYPING_PREDS[idx.kg][0]
    return set(idx.subj_of.get(type_pred, set()))


def mine_pca(idx, typed_subjects: Set[str], *, domain: str, thresholds: List[float],
            min_support: int) -> Dict[float, List[Candidate]]:
    by_threshold: Dict[float, List[Candidate]] = {t: [] for t in thresholds}
    lowest = min(thresholds)

    for p in idx.candidate_preds:
        for role, pop_all, path_fmt in (
            ("existential_domain", idx.subj_of.get(p, set()), f"< down({p}) >"),
            ("existential_range", idx.obj_of.get(p, set()), f"< up({p}) >"),
        ):
            pca_pop = pop_all & typed_subjects           # PCA restriction
            if len(pca_pop) < min_support:
                continue
            for c in idx.class_nodes:
                hits = pca_pop & idx.class_instances[c]
                support = len(hits)
                if support < min_support:
                    continue
                conf = support / len(pca_pop)
                if conf < lowest:
                    continue
                for t in thresholds:
                    if conf >= t:
                        by_threshold[t].append(Candidate(
                            kind=role, domain=domain, kg=idx.kg,
                            antecedent=path_fmt,
                            consequent=_tau(idx.kg, c),
                            support=support, prevalence=conf, threshold=t,
                            note=(f"PCA-confidence: {support}/{len(pca_pop)}={conf:.1%} "
                                  f"among entities that HAVE some type (CWA population "
                                  f"was {len(pop_all)}, {len(pop_all) - len(pca_pop)} "
                                  f"excluded as untyped-unknown)"),
                            cid_hint=f"hornpca.{domain}.{'dom' if role=='existential_domain' else 'rng'}."
                                    f"{_short(p)}.{_short(c)}",
                        ))
    for t in thresholds:
        by_threshold[t].sort(key=lambda cand: (cand.kind, cand.cid_hint))
    return by_threshold


def _tau(kg: str, class_value: str) -> str:
    type_pred, subclass_pred = TYPING_PREDS[kg]
    return f'< down({type_pred}) . down({subclass_pred})* . [val("{class_value}")] >'


def _short(curie: str) -> str:
    return curie.split(":", 1)[-1].replace('"', "").replace(" ", "_")


 
# mineable-but-inexpressible: negated-exclusion refinement (never shipped)
 

def find_inexpressible_refinements(idx, typed_subjects: Set[str], *, min_support: int,
                                   confidence_floor: float, top_k_competitors: int = 5) -> List[Dict]:
    """For every PCA rule that already clears `confidence_floor`, try adding a
    negated-exclusion atom against each of the top-K other frequent predicates
    and check whether confidence improves. Every such refinement is, by
    construction, outside Reg-GXPath_pos (needs `!`) -- confirmed by actually
    calling the real parser, not asserted. Returns only the refinements whose
    (manually computed, since they cannot be parsed/evaluated) confidence
    exceeds the floor, i.e. rules that "exceeded confidence but failed the
    fragment filter." """
    top_preds = sorted(idx.candidate_preds,
                       key=lambda q: len(idx.subj_of.get(q, set())), reverse=True)[:top_k_competitors]
    findings = []
    for p in idx.candidate_preds:
        pop_all = idx.subj_of.get(p, set())
        pca_pop = pop_all & typed_subjects
        if len(pca_pop) < min_support:
            continue
        for c in idx.class_nodes:
            base_hits = pca_pop & idx.class_instances[c]
            if len(base_hits) < min_support:
                continue
            base_conf = len(base_hits) / len(pca_pop)
            if base_conf < confidence_floor:
                continue
            for q in top_preds:
                if q == p:
                    continue
                excl_pop = pca_pop - idx.subj_of.get(q, set())    # NOT q(x, _)
                if len(excl_pop) < min_support:
                    continue
                excl_hits = excl_pop & idx.class_instances[c]
                if not excl_hits:
                    continue
                excl_conf = len(excl_hits) / len(excl_pop)
                if excl_conf <= base_conf:
                    continue        # refinement must actually improve confidence

                antecedent = f"< down({p}) > & ! < down({q}) >"
                consequent = _tau(idx.kg, c)
                try:
                    gxpath.parse_node(antecedent)
                    parse_status = "UNEXPECTEDLY PARSED -- investigate"
                except ParseError as exc:
                    parse_status = f"rejected as expected: {exc}"

                findings.append({
                    "antecedent": antecedent, "consequent": consequent,
                    "base_confidence": base_conf, "base_support": len(base_hits),
                    "refined_confidence": excl_conf, "refined_support": len(excl_hits),
                    "excluded_predicate": q, "fragment_check": parse_status,
                })
    return findings


 
# comparison against E0 on E1's own recovery metric (domain/range kinds only)
 

def compare_recovery(domain: str, kg: str, has_v2: bool,
                     e0_by_threshold: Dict[float, list], pca_by_threshold: Dict[float, list]) -> Dict:
    curated = [c for c in _curated_ptime_core(domain, kg)
              if c.kind in ("existential_domain", "existential_range")]
    v2_by_v1_cid = _curated_v2(domain, kg) if has_v2 else {}

    def _recovered_count(by_threshold, t):
        n = 0
        for c in curated:
            preds_v1, vals_v1 = _signature(c.antecedent, c.consequent)
            cand_dicts = [{"kind": m.kind, "containment": {"phi": m.antecedent, "psi": m.consequent}}
                         for m in by_threshold[t]]
            if any(_matches(m, c.kind, preds_v1, vals_v1) for m in cand_dicts):
                n += 1
                continue
            v2c = v2_by_v1_cid.get(c.cid)
            if v2c is not None:
                _p2, vals_v2 = _signature(v2c.antecedent, v2c.consequent)
                vals_added = vals_v2 - vals_v1
                if vals_added and any(_matches(m, c.kind, preds_v1, vals_added) for m in cand_dicts):
                    n += 1
        return n

    return {
        "domain": domain, "kg": kg, "curated_domrange_count": len(curated),
        "by_threshold": {
            f"{t:.2f}": {
                "e0_recovered": _recovered_count(e0_by_threshold, t),
                "pca_recovered": _recovered_count(pca_by_threshold, t),
                "e0_candidate_count": len(e0_by_threshold[t]),
                "pca_candidate_count": len(pca_by_threshold[t]),
            } for t in THRESHOLDS
        },
    }


def main() -> None:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    all_comparisons = []
    all_inexpressible = []

    for slice_name, domain, kg, has_v2 in SLICES:
        g = load_ntriples_file(os.path.join(REAL, f"{slice_name}.nt"))
        idx = build_index(g, kg, min_support=MIN_SUPPORT)
        typed_subjects = _typed_subjects(idx)

        e0_full = __import__("experimental.mining.miner", fromlist=["mine_prevalence"]) \
            .mine_prevalence(idx, domain=domain, thresholds=THRESHOLDS, min_support=MIN_SUPPORT)
        e0_domrange = {t: [c for c in cands if c.kind in
                          ("existential_domain", "existential_range")] for t, cands in e0_full.items()}

        pca_by_t = mine_pca(idx, typed_subjects, domain=domain, thresholds=THRESHOLDS,
                            min_support=MIN_SUPPORT)

        for t in THRESHOLDS:
            out_path = os.path.join(RESULTS_DIR, "..", "candidates",
                                    f"{slice_name}_hornpca_{t:.2f}.json")
            serial = [{"cid": c.cid_hint, "kind": c.kind, "domain": c.domain, "kg": c.kg,
                      "containment": {"phi": c.antecedent, "psi": c.consequent},
                      "support": c.support, "pca_confidence": c.prevalence, "note": c.note}
                     for c in pca_by_t[t]]
            with open(out_path, "w", encoding="utf-8") as fh:
                json.dump(serial, fh, indent=2, sort_keys=True)

        comparison = compare_recovery(domain, kg, has_v2, e0_domrange, pca_by_t)
        all_comparisons.append(comparison)

        inexpressible = find_inexpressible_refinements(
            idx, typed_subjects, min_support=MIN_SUPPORT, confidence_floor=min(THRESHOLDS))
        for f in inexpressible:
            f["slice"] = slice_name
        all_inexpressible.extend(inexpressible)

        run_id = log_run("E3", {
            "slice": slice_name, "domain": domain, "kg": kg,
            "comparison": comparison["by_threshold"],
            "inexpressible_found": len(inexpressible),
        })
        print(f"{slice_name}: run_id={run_id}")
        print(f"  {json.dumps(comparison['by_threshold'], indent=2)}")
        print(f"  inexpressible refinements found: {len(inexpressible)}")

    out = {"comparisons": all_comparisons, "inexpressible": all_inexpressible}
    out_path = os.path.join(RESULTS_DIR, "e3_horn_pca.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, sort_keys=True)
    print(f"\nwrote {out_path}")
    print(f"total inexpressible refinements across all slices: {len(all_inexpressible)}")


if __name__ == "__main__":
    main()
