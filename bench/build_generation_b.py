"""
P8a/F4: build a cell's size ladder by slicing down from one generation B cache.

One fetch per cell, every rung sliced out of it. That is the whole point: slicing is
a pure function of (cache, params) and its ordering does not read `target_edges`, so
rungs cut from one generation nest (`tests/test_slice_nesting.py`). Fetching per rung
would produce one generation per rung and the ladder would stop being comparable.

Reads `data/raw_genB/<domain>/`, never `data/raw/`. Generation A is not touched:
nothing here fetches, and nothing here writes outside `fixtures/real/generation_b/`.

Usage:
  python bench/build_generation_b.py                     # every cell with a genB cache
  python bench/build_generation_b.py --cells wikidata:disease
  python bench/build_generation_b.py --verify-rebuild     # byte-identical second build

NOTE: the inputs this script needs are NOT shipped with the repository.
`fixtures/real/generation_b/` and the `data/raw_genB/` cache it slices from were
lost and are not recoverable; only the RESULTS computed from them survive, in
`eval/generation_b_ladder.json` and `eval/generation_drift.json`. Re-running this
against a freshly fetched cache produces a different generation and will NOT
reproduce those committed numbers. See DATA.md.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from build_real_slice import pinned_seeds                                # noqa: E402
from kgrepair.ntriples import load_ntriples                             # noqa: E402
from kgrepair.pipeline import (RawCache, SliceParams, deny_check,       # noqa: E402
                               load_allowlist, slice_from_cache)
from kgrepair.pipeline.extract import SEEDS                             # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
CACHE_ROOT_B = os.path.join(ROOT, "data", "raw_genB")
OUT_DIR = os.path.join(ROOT, "fixtures", "real", "generation_b")

#: Every rung the campaign may ask for. A cell's ladder is truncated at its ceiling,
#: which is the largest rung its cache can actually fill.
RUNGS = [100, 1000, 5000, 10000, 20000, 50000, 100000]


def cells_with_a_cache():
    """(source, domain) for every genB cache on disk, derived rather than listed."""
    out = []
    if not os.path.isdir(CACHE_ROOT_B):
        return out
    for domain in sorted(os.listdir(CACHE_ROOT_B)):
        d = os.path.join(CACHE_ROOT_B, domain)
        if not os.path.isdir(d):
            continue
        for source in sorted(os.listdir(d)):
            if os.path.isdir(os.path.join(d, source)):
                out.append((source, domain))
    return out


def seeds_for(source, domain, cache, al):
    """Pinned seeds where the cell has a pin, otherwise the written-down constant.

    YAGO is the only source whose seeds are derived from a cache, and its pin is what
    keeps generation B comparable with generation A (P8a/F1).
    """
    pinned = pinned_seeds(source, domain)
    if pinned is not None:
        return sorted(pinned)
    return list(SEEDS[source][domain])


def build_ladder(source, domain, *, rungs=RUNGS, out_dir=OUT_DIR, write=True):
    cache = RawCache(os.path.join(CACHE_ROOT_B, domain))
    al = load_allowlist(source)
    seeds = seeds_for(source, domain, cache, al)
    generation = cache.generation_hash(source)

    rows = []
    previous_edges = None
    ceiling_reached = False
    for target in rungs:
        params = SliceParams(source=source, domain=domain, seeds=seeds,
                             target_edges=target, allowlist_id=al.allowlist_id)
        sl = slice_from_cache(cache, params,
                              name=f"genB_{source}_{domain}_{target}")
        edges = set(sl.graph.edges())

        # Level-0 belt, same assertion the generation A builder makes.
        denied = deny_check(sl.graph, al)
        assert denied == [], f"LEVEL-0 VIOLATION: {denied}"
        # loader round-trip, so a rung that cannot be reloaded never reaches disk
        reloaded = load_ntriples(sl.to_ntriples().splitlines())
        assert set(reloaded.edges()) == edges, f"{sl.name}: round-trip mismatch"

        nests = previous_edges is None or previous_edges <= edges
        assert nests, f"{sl.name}: does not contain the rung below it"

        short = len(edges) < target          # the cache could not fill this rung
        rows.append({"name": sl.name, "target_edges": target, "V": sl.manifest["V"],
                     "E": sl.manifest["E"], "labels": sl.manifest["labels"],
                     "data_values": sl.manifest["data_values"],
                     "content_hash": sl.manifest["content_hash"],
                     "nests_in_previous": bool(nests),
                     "short_of_target": bool(short)})

        if write:
            os.makedirs(out_dir, exist_ok=True)
            base = os.path.join(out_dir, sl.name)
            with open(base + ".nt", "w", encoding="utf-8") as fh:
                fh.write(sl.to_ntriples())
            manifest = dict(sl.manifest)
            manifest["generation"] = "B"
            manifest["ladder_rungs"] = rungs
            with open(base + ".manifest.json", "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, indent=2, sort_keys=True)
                fh.write("\n")

        previous_edges = edges
        if short:
            # Past the ceiling every larger rung returns the same set, so stop here
            # rather than writing identical files under different names.
            ceiling_reached = True
            break

    return {"source": source, "domain": domain,
            "cache_generation_hash": generation,
            "seeds": len(seeds), "seeds_pinned": pinned_seeds(source, domain) is not None,
            "ceiling_edges": rows[-1]["E"] if rows else 0,
            "ceiling_is_cache_exhaustion": ceiling_reached,
            "rungs": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default="")
    ap.add_argument("--verify-rebuild", action="store_true",
                    help="build twice and assert the manifests match byte for byte")
    ap.add_argument("--out", default=os.path.join(ROOT, "eval", "generation_b_ladder.json"))
    args = ap.parse_args()

    cells = ([tuple(c.split(":", 1)) for c in args.cells.split(",")] if args.cells
             else cells_with_a_cache())
    print(f"cells with a generation B cache: {[':'.join(c) for c in cells]}\n")

    out = []
    for source, domain in cells:
        row = build_ladder(source, domain)
        out.append(row)
        top = row["rungs"][-1]
        print(f"{source}:{domain:12s} gen={row['cache_generation_hash']} "
              f"ceiling={row['ceiling_edges']} rungs="
              f"{[r['target_edges'] for r in row['rungs']]} "
              f"{'(cache exhausted)' if row['ceiling_is_cache_exhaustion'] else ''}")
        for r in row["rungs"]:
            print(f"    {r['target_edges']:>7} -> V={r['V']:<7} E={r['E']:<7} "
                  f"nests={r['nests_in_previous']} hash={r['content_hash']}")

        if args.verify_rebuild:
            again = build_ladder(source, domain, write=False)
            assert [r["content_hash"] for r in again["rungs"]] == \
                   [r["content_hash"] for r in row["rungs"]], "rebuild drifted"
            print(f"    rebuild: byte-identical across {len(row['rungs'])} rung(s)")

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"cache_root": os.path.relpath(CACHE_ROOT_B, ROOT),
                   "rungs_offered": RUNGS, "cells": out}, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
