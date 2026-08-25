"""
D7/C1 -- v1 vs v2 evaluation on the affected real cells + geography-10k control.

For anatomy-1k, disease-1k, medication-1k (the RC1/RC2-affected cells) and
geography-10k (a control that should barely move -- untouched by C1): consistency
prevalence v1 vs v2, superset-repair additions v1 vs v2, and plausibility precision
v1 vs v2. Because v2 only changes WHICH nodes are witnesses and widens the class TEST
(not the class VALUE asserted on repair -- a v2 addition for a still-witness entity
targets the identical class as v1: wd:Q4936952/Q12136/Q12140), every (entity, class)
pair that is still added under v2 has an IDENTICAL cached plausibility verdict to its
v1 record; only genuinely new (entity, class) pairs need a fresh live check, and none
are expected here since v2 only ever REMOVES witnesses (antecedent narrowing) or
REMOVES contradictions (consequent widening) relative to v1 -- it never adds a new kind
of edge. This keeps the recheck inside the plausibility cache, no new live fetching.

Usage: python bench/real_v2_eval.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kgrepair import constraints                                     # noqa: E402
from kgrepair.instrument import render_table                         # noqa: E402
from kgrepair.ntriples import load_ntriples_file                     # noqa: E402
from kgrepair.repair import core_constraints, superset_repair        # noqa: E402
from kgrepair.validator import Validator                             # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
REAL = os.path.join(ROOT, "fixtures", "real")
RESULTS = os.path.join(ROOT, "results")
ASK_CACHE_PATH = os.path.join(ROOT, "data", "raw", "plausibility", "wikidata", "ask_cache.json")

# (cellkey, domain, basename) -- the RC1/RC2-affected cells + geography-10k control
CELLS = [
    ("anatomy_1000", "anatomy", "real_wikidata_anatomy_1000_typed"),
    ("disease_1000", "disease", "real_wikidata_disease_1000"),
    ("medication_1000", "medication", "real_wikidata_medication_1000_typed"),
    ("geography_10000", "geography", "real_wikidata_geography_10000"),
]


def prevalence(domain, basename, version):
    g = load_ntriples_file(os.path.join(REAL, basename + ".nt"))
    cs = constraints.get(domain, "wikidata", version=version)
    val = Validator(g, use_closure=True)
    total = 0
    per = {}
    for c in core_constraints(cs):
        n = val.check_one(c).count
        if n:
            per[c.cid] = n
        total += n
    return total, per


def additions(domain, basename, version):
    g = load_ntriples_file(os.path.join(REAL, basename + ".nt"))
    cs = constraints.get(domain, "wikidata", version=version)
    res = superset_repair(g, cs, in_place=True, prune=True)
    named = [(r.src, r.dst, r.constraint) for r in res.changelog
            if r.op == "add_edge" and r.provenance == "named"]
    return named, res


def classify(ask_cache, entity, cls):
    key = f"{entity}||{cls}"
    typed = ask_cache.get(key)
    if typed is True:
        return "corroborated"
    ht = ask_cache.get(f"{entity}||__ANYTYPE__")
    if ht is True:
        return "contradicted"
    if ht is False:
        return "plausible"
    return "unknown"


def precision(ask_cache, named_edges):
    """Precision = corroborated / definitively-classified (corrob+contra+plausible) --
    NOT / all pairs. `total_pairs` may exceed the classified count when a cell's
    additions exceed T5's per-cell live-check cap (e.g. geography-10k, 1586 pairs vs a
    120-cap) or when a pair only has a cached verdict via overlap with another cell's
    additions (geography-1k and geography-10k share many entities, same seed set)."""
    pairs = sorted(set((e, c) for (e, c, _cid) in named_edges))
    counts = {"corroborated": 0, "contradicted": 0, "plausible": 0, "unknown": 0}
    unknown_pairs = []
    for (e, c) in pairs:
        status = classify(ask_cache, e, c)
        counts[status] += 1
        if status == "unknown":
            unknown_pairs.append((e, c))
    classified_n = counts["corroborated"] + counts["contradicted"] + counts["plausible"]
    return counts, len(pairs), classified_n, unknown_pairs


def main():
    ask_cache = json.load(open(ASK_CACHE_PATH)) if os.path.exists(ASK_CACHE_PATH) else {}
    rows = []
    unknown_total = []
    for cellkey, domain, basename in CELLS:
        prev1, per1 = prevalence(domain, basename, 1)
        prev2, per2 = prevalence(domain, basename, 2)
        add1, _res1 = additions(domain, basename, 1)
        add2, _res2 = additions(domain, basename, 2)
        prec1_counts, total1_n, classified1_n, unk1 = precision(ask_cache, add1)
        prec2_counts, total2_n, classified2_n, unk2 = precision(ask_cache, add2)
        unknown_total += unk2
        rows.append({
            "cell": cellkey,
            "prevalence_v1": prev1, "prevalence_v2": prev2,
            "additions_v1": len(add1), "additions_v2": len(add2),
            "corrob_v1": prec1_counts["corroborated"], "checked_v1": classified1_n,
            "prec_v1": f"{prec1_counts['corroborated']/classified1_n:.1%}" if classified1_n else "-",
            "corrob_v2": prec2_counts["corroborated"], "checked_v2": classified2_n,
            "prec_v2": f"{prec2_counts['corroborated']/classified2_n:.1%}" if classified2_n else "-",
            "contra_v2": prec2_counts["contradicted"],
            "unclassified_v1": total1_n - classified1_n, "unclassified_v2": total2_n - classified2_n,
        })
    print(render_table(rows))
    if unknown_total:
        print(f"\nWARNING: {len(unknown_total)} v2 (entity,class) pairs have NO cached "
              f"plausibility verdict (would need a fresh live check): {unknown_total[:10]}")
    else:
        print("\nAll v2 additions have cached plausibility verdicts -- no new live "
              "fetching needed (as predicted: v2 never asserts a new class value).")

    with open(os.path.join(RESULTS, "v1_vs_v2_eval.json"), "w") as fh:
        json.dump({"rows": rows, "unknown_pairs": unknown_total}, fh, indent=2)
    print(f"\nwrote {os.path.join(RESULTS, 'v1_vs_v2_eval.json')}")


if __name__ == "__main__":
    main()
