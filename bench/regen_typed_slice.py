"""
T0 (D6) corrected-slice regeneration via typing completion.

For each cell whose slicing-artifact fraction was material (>10%), we:
  1. close the typing spine over that domain's cache (`typing_closure_extract`) --
     fetches type/subClassOf for every frontier-boundary node that was never queried;
  2. load the ORIGINAL slice and typing-complete it (`typing_complete`) -- add the
     type/subClassOf edges it was missing, closing the subClassOf* chain, WITHOUT
     re-running the edge-capped BFS (which would re-truncate the very typing we added
     and change the entity population). Same entities, complete typing.
  3. measure corrected prevalence and write a NEW slice/manifest (`_typed`), leaving
     the original untouched (historical record), tagged with the new cache generation.

Because augmentation adds only typing-spine edges (never a domain predicate), the
existential-domain/range witness *population* (antecedent matches) is identical to the
original slice; only how many satisfy tau_C changes. So original-minus-corrected on
those constraints is exactly the resolved slicing/fetch artifacts.

Usage:
  python bench/regen_typed_slice.py                 # anatomy + medication (default)
  python bench/regen_typed_slice.py --max-requests 400 --min-interval 1.0
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kgrepair.constraints import get as get_cs                       # noqa: E402
from kgrepair.instrument import (RunContext, constraints_meta,       # noqa: E402
                                 slice_meta_from_graph, validate_record)
from kgrepair.ntriples import load_ntriples, load_ntriples_file      # noqa: E402
from kgrepair.pipeline import RawCache, deny_check, load_allowlist   # noqa: E402
from kgrepair.pipeline.extract import typing_closure_extract         # noqa: E402
from kgrepair.pipeline.fetch import FetchPolicy, PoliteFetcher       # noqa: E402
from kgrepair.pipeline.slicing import typing_complete                # noqa: E402
from kgrepair.validator import Validator                             # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
CACHE_ROOT = os.path.join(ROOT, "data", "raw")
OUT_DIR = os.path.join(ROOT, "fixtures", "real")
RESULTS = os.path.join(ROOT, "results")

# (source, domain, target) -- the material-artifact cells from the T0 audit
MATERIAL_CELLS = [
    ("wikidata", "anatomy", 1000),
    ("wikidata", "medication", 1000),
]


def _orig_manifest(source, domain, target):
    p = os.path.join(OUT_DIR, f"real_{source}_{domain}_{target}.manifest.json")
    return json.load(open(p))


def _serialize(g, name, gen_hash):
    lines = [f"# real slice {name} (source=real/wikidata; Level-0 filtered; T0 typing-completed)",
             f"# cache_generation={gen_hash}"]
    for s, p, o in sorted(g.edges()):
        lines.append(f"<{s}> <{p}> <{o}> .")
    return "\n".join(lines) + "\n"


def regen(source, domain, target, *, min_interval=1.0, max_requests=400):
    cache = RawCache(os.path.join(CACHE_ROOT, domain))
    al = load_allowlist(source)
    gen_before = cache.generation_hash(source)

    fetcher = PoliteFetcher(FetchPolicy(min_interval_s=min_interval))
    closure = typing_closure_extract(source, domain, cache, fetcher,
                                     max_rounds=12, max_requests=max_requests)
    gen_after = cache.generation_hash(source)

    orig_manifest = _orig_manifest(source, domain, target)
    g = load_ntriples_file(os.path.join(OUT_DIR, f"real_{source}_{domain}_{target}.nt"))
    V0, E0 = len(g.nodes), g.num_edges()
    added = typing_complete(g, cache, al)

    denied = deny_check(g, al)
    assert denied == [], f"LEVEL-0 VIOLATION: {denied}"

    cs = get_cs(domain, source)
    name = f"real_{source}_{domain}_{target}_typed"
    with RunContext(RESULTS, slice=slice_meta_from_graph(
            g, source="real", manifest_hash="",
            params={"slice_source": source, "domain": domain, "target_edges": target,
                    "generation": "typed", "cache_generation_hash": gen_after}),
            constraints=constraints_meta(cs), mode="consistency") as run:
        with run.phase("consistency_initial"):
            rep = Validator(g, use_closure=True).validate(cs)
    assert validate_record(run.record) == []

    # round-trip guard on the serialized augmented slice
    nt = _serialize(g, name, gen_after)
    g2 = load_ntriples(nt.splitlines())
    assert set(g2.edges()) == set(g.edges()), "round-trip mismatch"

    base = os.path.join(OUT_DIR, name)
    with open(base + ".nt", "w", encoding="utf-8") as fh:
        fh.write(nt)
    corrected = {v.constraint.cid: v.count for v in rep.failing()}
    stats = g.stats()
    manifest = {
        "name": name, "namespace": "real", "slice_source": source, "source": "real",
        "domain": domain, "target_edges": target,
        "generation": "typed (T0 typing-completed)",
        "supersedes": f"real_{source}_{domain}_{target}",
        "cache_generation_before": gen_before, "cache_generation_after": gen_after,
        "closure_report": closure,
        "typing_edges_added": added,
        "V_before": V0, "E_before": E0,
        "V": stats["nodes"], "E": stats["edges"],
        "labels": stats["labels"], "data_values": stats["valued_nodes"],
        "violations_original": orig_manifest.get("violations", {}),
        "violations": corrected,
    }
    with open(base + ".manifest.json", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-interval", type=float, default=1.0)
    ap.add_argument("--max-requests", type=int, default=400)
    args = ap.parse_args()
    for cell in MATERIAL_CELLS:
        m = regen(*cell, min_interval=args.min_interval, max_requests=args.max_requests)
        print(f"\n=== {m['name']} ===")
        print(f"  cache generation: {m['cache_generation_before']} -> {m['cache_generation_after']}")
        print(f"  closure: {m['closure_report']}")
        print(f"  typing edges added: {m['typing_edges_added']}  "
              f"(V {m['V_before']}->{m['V']}, E {m['E_before']}->{m['E']})")
        print(f"  violations original : {m['violations_original']}")
        print(f"  violations corrected: {m['violations']}")


if __name__ == "__main__":
    main()
