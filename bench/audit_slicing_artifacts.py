"""
T0 (D6) slicing-artifact audit.

For each cap-abort cell we classify every existential domain/range witness on the
slice into one of three buckets, to decide whether the P4 prevalence numbers are
trustworthy or inflated by extraction artifacts:

  * SLICE_ARTIFACT -- the witness DOES satisfy tau_C in the full raw cache, but the
    typing edge(s) were dropped by the size-capped BFS before entering the slice.
    (Typing was fetched; slicing lost it.)
  * FETCH_ARTIFACT -- the witness still fails tau_C in the full cache AND the
    extractor never issued a query with this node as ?s (its typing was never
    fetched -- a frontier-boundary node). This is the audit's core question:
    "was a typing query issued for that node at all?"
  * GENUINE -- the node was queried (full allow-listed neighbourhood is in cache)
    and still fails tau_C: genuinely untyped in the fetched data.

artifact_fraction = (SLICE_ARTIFACT + FETCH_ARTIFACT) / witnesses.

Read-only: builds an in-memory graph from the existing raw cache; never fetches,
never mutates the cache or slices.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kgrepair.constraints import get as get_cs                       # noqa: E402
from kgrepair.datagraph import DataGraph                            # noqa: E402
from kgrepair.gxpath import Evaluator                               # noqa: E402
from kgrepair.ntriples import load_ntriples_file                    # noqa: E402
from kgrepair.pipeline.allowlist import load_allowlist             # noqa: E402
from kgrepair.pipeline.cache import RawCache                        # noqa: E402
from kgrepair.repair import eligible_constraints                    # noqa: E402
from kgrepair.validator import Validator                            # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
CACHE_ROOT = os.path.join(ROOT, "data", "raw")
REAL = os.path.join(ROOT, "fixtures", "real")

_VALUING = ("wdt:P279", "rdfs:subClassOf", "rdf:type", "wdt:P31", "schema:subClassOf")

# (source, domain, target)
ABORT_CELLS = [
    ("wikidata", "geography", 10000),
    ("wikidata", "anatomy", 1000),
    ("wikidata", "medication", 1000),
]

_VALUES_S = re.compile(r"VALUES\s+\?s\s*\{([^}]*)\}")


def queried_subjects(cache: RawCache, source: str):
    """Set of node CURIEs that appeared as ?s in a cached CONSTRUCT batch -- i.e.
    nodes whose full allow-listed neighbourhood (incl. P31/P279) was fetched."""
    subs = set()
    d = cache.source_dir(source)
    for name in os.listdir(d):
        if not name.endswith(".meta.json"):
            continue
        meta = json.load(open(os.path.join(d, name)))
        for m in _VALUES_S.finditer(meta.get("query_text", "")):
            subs.update(tok for tok in m.group(1).split() if tok)
    return subs


def full_cache_graph(cache: RawCache, al) -> DataGraph:
    """DataGraph over every allow-listed cached triple (CURIE-abbreviated, with the
    loader's class-valuing) -- the whole fetched neighbourhood, not the slice."""
    g = DataGraph()
    for s, p, o, is_lit in cache.iter_raw_triples(al.source):
        pc = al.curie_of(p)
        if not al.allows(pc) or is_lit:
            continue
        sc, oc = al.curie_of(s), al.curie_of(o)
        g.add_edge(sc, pc, oc)
        if pc in _VALUING and g.value(oc) is None:
            g.set_value(oc, oc)
    return g


def audit_cell(source, domain, target):
    al = load_allowlist(source)
    cache = RawCache(os.path.join(CACHE_ROOT, domain))
    qs = queried_subjects(cache, source)
    g_full = full_cache_graph(cache, al)
    ev_full = Evaluator(g_full, use_closure=True)

    slice_path = os.path.join(REAL, f"real_{source}_{domain}_{target}.nt")
    g_slice = load_ntriples_file(slice_path)
    val = Validator(g_slice, use_closure=True)

    cs = get_cs(domain, source)
    dom_rng = [c for c in eligible_constraints(cs)
               if c.kind in ("existential_domain", "existential_range")]

    rows = []
    per_class = {"slice": 0, "fetch": 0, "genuine": 0, "witnesses": 0}
    detail = []
    for c in dom_rng:
        witnesses = val.check_one(c).witnesses
        psi_full = ev_full.eval_node(c.psi)   # nodes satisfying tau_C in full cache
        s_art = f_art = gen = 0
        for w in witnesses:
            if w in psi_full:
                s_art += 1
                bucket = "SLICE_ARTIFACT"
            elif w not in qs:
                f_art += 1
                bucket = "FETCH_ARTIFACT"
            else:
                gen += 1
                bucket = "GENUINE"
            detail.append((c.cid, w, bucket))
        n = len(witnesses)
        per_class["slice"] += s_art
        per_class["fetch"] += f_art
        per_class["genuine"] += gen
        per_class["witnesses"] += n
        rows.append({
            "constraint": c.cid, "kind": c.kind, "witnesses": n,
            "slice_artifact": s_art, "fetch_artifact": f_art, "genuine": gen,
        })
    total = per_class["witnesses"]
    artifacts = per_class["slice"] + per_class["fetch"]
    frac = artifacts / total if total else 0.0
    return {
        "cell": f"{source} {domain} {target}",
        "V_slice": len(g_slice.nodes), "V_cache": len(g_full.nodes),
        "queried_subjects": len(qs),
        "rows": rows, "totals": per_class,
        "artifact_fraction": frac,
        "detail": detail,
    }


def main():
    results = [audit_cell(*cell) for cell in ABORT_CELLS]
    for r in results:
        print(f"\n=== {r['cell']} ===")
        print(f"  slice V={r['V_slice']}  cache V={r['V_cache']}  "
              f"queried_subjects={r['queried_subjects']}")
        for row in r["rows"]:
            print(f"  {row['constraint']:22} {row['kind']:20} "
                  f"witnesses={row['witnesses']:4} "
                  f"slice_art={row['slice_artifact']:4} "
                  f"fetch_art={row['fetch_artifact']:4} "
                  f"genuine={row['genuine']:4}")
        t = r["totals"]
        print(f"  TOTAL witnesses={t['witnesses']} "
              f"slice_art={t['slice']} fetch_art={t['fetch']} genuine={t['genuine']} "
              f"-> artifact_fraction={r['artifact_fraction']:.1%}")
    # machine-readable
    out = os.path.join(ROOT, "results", "t0_artifact_audit.json")
    with open(out, "w") as fh:
        json.dump([{k: v for k, v in r.items() if k != "detail"} for r in results],
                  fh, indent=2)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
