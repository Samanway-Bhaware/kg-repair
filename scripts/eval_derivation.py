"""
Evaluation harness for the constraint candidate generator (src/kgrepair/derive.py).

Runs derive_candidates on each committed fixture that has authored constraints, then
scores the mined candidates against the authored v1 and v2 sets by shape. A mined
candidate matches an authored one when the kind and the predicate set agree and the
class is equal (exact) or within one subclass hop (relaxed). Precision, recall, and F1
are reported per domain and overall, against v1 and v2 separately.

Output is byte-reproducible (sorted, no wall-clock, thresholds only from DeriveConfig),
matching the D7 table convention: eval/constraint_derivation.md plus a machine-readable
eval/constraint_derivation.json.

Note on fixtures: the task named synthetic_*_wd.nt slices; those are not committed, so
this harness uses the committed real_wikidata_* slices (the same corpus the mining study
used). Wire additional slices into CELLS if they become available.

Usage: python scripts/eval_derivation.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from typing import Dict, FrozenSet, List, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kgrepair import constraints as authored           # noqa: E402
from kgrepair.datagraph import DataGraph                # noqa: E402
from kgrepair.derive import SHAPES, DeriveConfig, derive_candidates  # noqa: E402
from kgrepair.ntriples import load_ntriples_file         # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
REAL = os.path.join(ROOT, "fixtures", "real")
OUT_DIR = os.path.join(ROOT, "eval")
MD_PATH = os.path.join(OUT_DIR, "constraint_derivation.md")
JSON_PATH = os.path.join(OUT_DIR, "constraint_derivation.json")

# (domain, kg, fixture basename)
CELLS = [
    ("geography", "wikidata", "real_wikidata_geography_1000"),
    ("taxa", "wikidata", "real_wikidata_taxa_1000"),
    ("anatomy", "wikidata", "real_wikidata_anatomy_1000_typed"),
    ("disease", "wikidata", "real_wikidata_disease_1000"),
    ("medication", "wikidata", "real_wikidata_medication_1000_typed"),
]

MINEABLE_KINDS = ("existential_domain", "existential_range",
                  "typing_existence", "requires_statement")

_STRUCTURAL = {"wdt:P31", "wdt:P279", "rdf:type", "rdfs:subClassOf", "schema:subClassOf"}
_DOWN = re.compile(r"down\(([^)]+)\)")
_UP = re.compile(r"up\(([^)]+)\)")
_VAL = re.compile(r'val\("([^"]+)"\)')

Signature = Tuple[str, FrozenSet[str], FrozenSet[str]]   # (kind, predicates, classes)


def _predicates(text: str) -> FrozenSet[str]:
    labels = set(_DOWN.findall(text)) | set(_UP.findall(text))
    return frozenset(p for p in labels if p not in _STRUCTURAL)


def _signature(kind: str, antecedent: str, consequent: str) -> Signature:
    """(kind, non-structural predicate set, class-value set). For domain/range/typing
    the predicates and classes come from antecedent and consequent respectively; for
    requires-statement the required predicate is in the consequent and the class is the
    tau_C in the antecedent. Structural type/subclass predicates are filtered so the
    signature is stable across v2's widened class tests."""
    if kind == "requires_statement":
        return (kind, _predicates(consequent), frozenset(_VAL.findall(antecedent)))
    return (kind, _predicates(antecedent), frozenset(_VAL.findall(consequent)))


def _hierarchy(graph: DataGraph) -> Tuple[Dict[str, set], Dict[str, set]]:
    parents: Dict[str, set] = defaultdict(set)
    children: Dict[str, set] = defaultdict(set)
    for label in ("wdt:P279", "rdfs:subClassOf", "schema:subClassOf"):
        for s in sorted(graph.nodes):
            for o in graph.succ(label, s):
                parents[s].add(o)
                children[o].add(s)
    return parents, children


def _class_matches(mined_classes: FrozenSet[str], authored_classes: FrozenSet[str],
                   parents: Dict[str, set], children: Dict[str, set], relaxed: bool) -> bool:
    if mined_classes & authored_classes:
        return True
    if not relaxed:
        return False
    for m in mined_classes:
        near = {m} | parents.get(m, set()) | children.get(m, set())
        if near & authored_classes:
            return True
    return False


def _matches(mined: Signature, auth: Signature, parents, children, relaxed: bool) -> bool:
    if mined[0] != auth[0] or mined[1] != auth[1]:
        return False
    return _class_matches(mined[2], auth[2], parents, children, relaxed)


def _authored_mineable(domain: str, kg: str, version: int) -> List[Signature]:
    try:
        cs = authored.get(domain, kg, version=version)
    except KeyError:
        return []
    sigs = []
    for c in cs:
        if c.tier == "ptime_core" and c.kind in MINEABLE_KINDS:
            sigs.append(_signature(c.kind, c.antecedent, c.consequent))
    return sigs


def _prf(tp: int, predicted: int, actual: int) -> Tuple[float, float, float]:
    precision = tp / predicted if predicted else 0.0
    recall = tp / actual if actual else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return round(precision, 4), round(recall, 4), round(f1, 4)


def _score(mined_sigs: List[Signature], auth_sigs: List[Signature],
           parents, children, relaxed: bool) -> Dict:
    tp_mined = sum(1 for m in mined_sigs
                   if any(_matches(m, a, parents, children, relaxed) for a in auth_sigs))
    matched_auth = sum(1 for a in auth_sigs
                       if any(_matches(m, a, parents, children, relaxed) for m in mined_sigs))
    precision, _r, _f = _prf(tp_mined, len(mined_sigs), len(auth_sigs))
    _p, recall, _f2 = _prf(matched_auth, len(mined_sigs), len(auth_sigs))
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"mined": len(mined_sigs), "authored": len(auth_sigs),
            "tp_mined": tp_mined, "matched_authored": matched_auth,
            "precision": precision, "recall": recall, "f1": round(f1, 4)}


def evaluate() -> Dict:
    # Pinned to the shape-driven generator, explicitly rather than by default.
    # Since P4d the default is the two-axis search, and this harness measures how
    # much of an authored set the SHAPE sweep recovers: its shape labels are what
    # `_signature` matches on. Repointing it at the search would change what every
    # number in the committed table means, so the switch is recorded separately
    # and this measurement stays what it says it is.
    cfg = DeriveConfig(generator=SHAPES)
    per_cell = {}
    for domain, kg, basename in CELLS:
        path = os.path.join(REAL, basename + ".nt")
        if not os.path.exists(path):
            per_cell[domain] = {"status": "MISSING-FIXTURE", "fixture": basename}
            continue
        graph = load_ntriples_file(path)
        result = derive_candidates(graph, domain, kg, cfg)
        parents, children = _hierarchy(graph)
        mined_sigs = [_signature(c.kind, c.antecedent, c.consequent) for c in result.constraints]
        cell = {"status": "ok", "fixture": basename, "vocab": result.vocab,
                "mined_total": result.stats.get("emitted", 0),
                "mined_generated": result.stats.get("total_generated", 0),
                "mined_pruned_redundant": result.stats.get("pruned_redundant", 0),
                "mined_by_shape": {k: result.stats.get(k, 0) for k in MINEABLE_KINDS},
                "versions": {}}
        for version in (1, 2):
            auth_sigs = _authored_mineable(domain, kg, version)
            overall = {mode: _score(mined_sigs, auth_sigs, parents, children, mode == "relaxed")
                       for mode in ("exact", "relaxed")}
            by_shape = {}
            for kind in MINEABLE_KINDS:
                m_k = [s for s in mined_sigs if s[0] == kind]
                a_k = [s for s in auth_sigs if s[0] == kind]
                by_shape[kind] = {
                    mode: _score(m_k, a_k, parents, children, mode == "relaxed")
                    for mode in ("exact", "relaxed")}
            cell["versions"][f"v{version}"] = {"overall": overall, "by_shape": by_shape}
        per_cell[domain] = cell
    return {"config": {"min_support": cfg.min_support,
                       "min_pca_confidence": cfg.min_pca_confidence,
                       "min_typed_fraction": cfg.min_typed_fraction,
                       "contamination_frac": cfg.contamination_frac},
            "cells": per_cell}


 
# markdown rendering (byte-reproducible)
 

def _md_table(headers: List[str], rows: List[List[str]]) -> str:
    line = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join(["---"] * len(headers)) + "|"
    body = ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join([line, sep] + body)


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def build(data: Dict) -> str:
    cfg = data["config"]
    parts: List[str] = []
    parts.append("# Constraint derivation evaluation\n")
    parts.append(
        "Mined candidates from `src/kgrepair/derive.py` scored against the authored "
        "constraint sets. A mined candidate matches an authored one when the kind and "
        "predicate set agree and the class is equal (exact) or within one subclass hop "
        "(relaxed). Regenerate with `python scripts/eval_derivation.py`; guarded for "
        "byte-reproducibility by `tests/test_derive_eval.py`.\n")
    parts.append(
        "**Generator: `shapes`.** Every number below is the shape-driven sweep, "
        "pinned explicitly. Since P4d the derivation default is the two-axis search "
        "(`kgrepair.search`), which this table does not measure; the search's own "
        "evaluation is `eval/derivation_search_evaluation.md`.\n")
    parts.append(
        f"Thresholds (DeriveConfig): min_support={cfg['min_support']}, "
        f"min_pca_confidence={cfg['min_pca_confidence']}, "
        f"min_typed_fraction={cfg['min_typed_fraction']}, "
        f"contamination_frac={cfg['contamination_frac']}.\n")

    # Table 1: per-domain overall, v1 and v2, exact and relaxed
    parts.append("## Overall precision / recall / F1 by domain\n")
    headers = ["domain", "fixture", "mined", "authored (v1)",
               "P exact v1", "R exact v1", "F1 exact v1",
               "P relax v1", "R relax v1", "F1 relax v1",
               "P relax v2", "R relax v2", "F1 relax v2"]
    rows = []
    for domain, _kg, _fx in CELLS:
        cell = data["cells"].get(domain, {})
        if cell.get("status") != "ok":
            rows.append([domain, cell.get("fixture", "?"), "MISSING", "-",
                         "-", "-", "-", "-", "-", "-", "-", "-", "-"])
            continue
        v1 = cell["versions"]["v1"]
        v2 = cell["versions"]["v2"]
        e1, r1 = v1["overall"]["exact"], v1["overall"]["relaxed"]
        r2 = v2["overall"]["relaxed"]
        rows.append([
            domain, cell["fixture"], str(cell["mined_total"]), str(e1["authored"]),
            _pct(e1["precision"]), _pct(e1["recall"]), _pct(e1["f1"]),
            _pct(r1["precision"]), _pct(r1["recall"]), _pct(r1["f1"]),
            _pct(r2["precision"]), _pct(r2["recall"]), _pct(r2["f1"]),
        ])
    parts.append(_md_table(headers, rows))

    # Table 2: by-shape, aggregated across domains, relaxed, v1 and v2
    parts.append("\n## By shape, aggregated across domains (relaxed match)\n")
    sh_headers = ["shape", "mined", "authored v1", "P v1", "R v1", "F1 v1",
                  "authored v2", "P v2", "R v2", "F1 v2"]
    sh_rows = []
    for kind in MINEABLE_KINDS:
        agg = {v: {"mined": 0, "authored": 0, "tp": 0, "matched": 0} for v in ("v1", "v2")}
        for domain, _kg, _fx in CELLS:
            cell = data["cells"].get(domain, {})
            if cell.get("status") != "ok":
                continue
            for v in ("v1", "v2"):
                s = cell["versions"][v]["by_shape"][kind]["relaxed"]
                agg[v]["mined"] += s["mined"]
                agg[v]["authored"] += s["authored"]
                agg[v]["tp"] += s["tp_mined"]
                agg[v]["matched"] += s["matched_authored"]
        p1, _r1, _f1 = _prf(agg["v1"]["tp"], agg["v1"]["mined"], agg["v1"]["authored"])
        _pp, rr1, _ff = _prf(agg["v1"]["matched"], agg["v1"]["mined"], agg["v1"]["authored"])
        p2, _r, _f = _prf(agg["v2"]["tp"], agg["v2"]["mined"], agg["v2"]["authored"])
        _pp2, rr2, _ff2 = _prf(agg["v2"]["matched"], agg["v2"]["mined"], agg["v2"]["authored"])
        f1v1 = (2 * p1 * rr1 / (p1 + rr1)) if (p1 + rr1) else 0.0
        f1v2 = (2 * p2 * rr2 / (p2 + rr2)) if (p2 + rr2) else 0.0
        sh_rows.append([kind, str(agg["v1"]["mined"]), str(agg["v1"]["authored"]),
                        _pct(p1), _pct(rr1), _pct(round(f1v1, 4)),
                        str(agg["v2"]["authored"]), _pct(p2), _pct(rr2), _pct(round(f1v2, 4))])
    parts.append(_md_table(sh_headers, sh_rows))

    parts.append(
        "\n## Reading these numbers\n"
        "Recall is which authored constraints the profiler rediscovers; precision is how "
        "many mined candidates correspond to an authored one. Low precision on "
        "requires_statement is expected and is flagged low_trust in the approval report: "
        "a missing edge is the very violation the repair engine exists to fix, so "
        "profiling cannot tell a real requirement from an incidental one. The relaxed "
        "column credits a class chosen one subclass hop away from the authored class, "
        "which is where class-granularity selection lands most of its near-misses.\n")
    return "\n".join(parts) + "\n"


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    data = evaluate()
    with open(JSON_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    with open(MD_PATH, "w", encoding="utf-8") as fh:
        fh.write(build(data))
    print(f"wrote {MD_PATH}")
    print(f"wrote {JSON_PATH}")


if __name__ == "__main__":
    main()
