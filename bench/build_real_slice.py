"""
Build one real slice end-to-end: fetch (cached) -> slice (deterministic) -> loader
round-trip -> consistency-only run through the T1 harness -> write manifest + .nt.

Reused by P3 corpus production. SPARQL sources fetch live (polite, resumable via
cache); YAGO reads a pre-extracted cache. Level-0 is enforced in the extractor.

Usage:
  python bench/build_real_slice.py --source wikidata --domain geography --target 1000
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kgrepair import constraints
from kgrepair.instrument import RunContext, constraints_meta, slice_meta_from_graph, validate_record
from kgrepair.ntriples import load_ntriples
from kgrepair.pipeline import RawCache, SliceParams, deny_check, load_allowlist, slice_from_cache
from kgrepair.pipeline.extract import SEEDS, sparql_extract
from kgrepair.pipeline.fetch import FetchPolicy, PoliteFetcher
from kgrepair.validator import Validator

ROOT = os.path.join(os.path.dirname(__file__), "..")
CACHE_ROOT = os.path.join(ROOT, "data", "raw")
OUT_DIR = os.path.join(ROOT, "fixtures", "real")
RESULTS = os.path.join(ROOT, "results")


def _domain_cs(domain, source):
    kg = {"wikidata": "wikidata", "dbpedia": "dbpedia", "yago": "yago"}[source]
    return constraints.get(domain, kg)


_YAGO_BACKBONE = {"taxa": "schema:parentTaxon", "geography": "schema:location"}

PINNED_SEEDS_PATH = os.path.join(OUT_DIR, "pinned_seeds.json")


def pinned_seeds(source, domain):
    """Seeds pinned from an earlier cache generation, or None if this cell has none.

    YAGO seeds are derived from the cache backbone rather than written down, so a
    re-extract that moved the backbone would move the seeds and confound a
    generation-against-generation comparison. `fixtures/real/pinned_seeds.json`
    records the values a named generation produced, and they are read back verbatim
    here. This is the YAGO counterpart of `extract.SEEDS`, which is a constant for
    the same reason.

    Only the cells listed in the file are pinned. Anything else falls through to the
    derivation below, so this cannot change what a cell without a pin does.
    """
    if not os.path.exists(PINNED_SEEDS_PATH):
        return None
    with open(PINNED_SEEDS_PATH, encoding="utf-8") as fh:
        return (json.load(fh).get("seeds", {}).get(source, {}) or {}).get(domain)


def _yago_seeds(cache, al, domain):
    """YAGO entity IRIs are opaque -> derive seeds from the cache's domain backbone.

    A pin for this cell wins over the derivation. See `pinned_seeds`.
    """
    pinned = pinned_seeds("yago", domain)
    if pinned is not None:
        return sorted(pinned)
    pred = _YAGO_BACKBONE.get(domain, "rdf:type")
    subs = {al.curie_of(s) for s, p, o, _lit in cache.iter_raw_triples("yago")
            if al.curie_of(p) == pred}
    return sorted(subs)


def build(source, domain, target, *, do_fetch=True, min_interval=1.0, max_requests=60):
    # Cache is scoped per (domain, source): otherwise one domain's edges satisfy the
    # resumability edge-count check and block another domain's fetch on the same source.
    cache = RawCache(os.path.join(CACHE_ROOT, domain))
    al = load_allowlist(source)
    report = {}
    if do_fetch and source in ("wikidata", "dbpedia"):
        fetcher = PoliteFetcher(FetchPolicy(min_interval_s=min_interval))
        report = sparql_extract(source, domain, cache, fetcher, target_edges=target,
                                max_requests=max_requests)

    seeds = _yago_seeds(cache, al, domain) if source == "yago" else SEEDS[source][domain]
    params = SliceParams(source=source, domain=domain, seeds=seeds,
                         target_edges=target, allowlist_id=al.allowlist_id)
    sl = slice_from_cache(cache, params,
                          name=f"real_{source}_{domain}_{target}")

    # loader round-trip (must not raise) + deny-check (Level-0)
    g = load_ntriples(sl.to_ntriples().splitlines())
    assert set(g.edges()) == set(sl.graph.edges()), "round-trip mismatch"
    denied = deny_check(sl.graph, al)
    assert denied == [], f"LEVEL-0 VIOLATION: denied predicates emitted: {denied}"

    # consistency-only run through the T1 harness
    cs = _domain_cs(domain, source)
    with RunContext(RESULTS, slice=slice_meta_from_graph(
            g, source="real", manifest_hash=sl.manifest["content_hash"],
            params={"slice_source": source, "domain": domain, "target_edges": target}),
            constraints=constraints_meta(cs), mode="consistency") as run:
        with run.phase("load"):
            _ = g
        with run.phase("consistency_initial"):
            rep = Validator(g, use_closure=True).validate(cs)
    assert validate_record(run.record) == []

    # persist slice + manifest + ground-truth-free (real has no injected GT)
    os.makedirs(OUT_DIR, exist_ok=True)
    base = os.path.join(OUT_DIR, sl.name)
    with open(base + ".nt", "w", encoding="utf-8") as fh:
        fh.write(sl.to_ntriples())
    manifest = dict(sl.manifest)
    manifest["violations"] = {v.constraint.cid: v.count for v in rep.failing()}
    manifest["fetch_report"] = report
    with open(base + ".manifest.json", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return sl, manifest, rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, choices=["wikidata", "dbpedia", "yago"])
    ap.add_argument("--domain", required=True)
    ap.add_argument("--target", type=int, default=1000)
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--min-interval", type=float, default=1.0)
    ap.add_argument("--max-requests", type=int, default=60)
    args = ap.parse_args()

    sl, manifest, rep = build(args.source, args.domain, args.target,
                              do_fetch=not args.no_fetch, min_interval=args.min_interval,
                              max_requests=args.max_requests)
    print(f"{sl.name}: V={manifest['V']} E={manifest['E']} labels={manifest['labels']} "
          f"values={manifest['data_values']}")
    print(f"  fetch: {manifest.get('fetch_report')}")
    print(f"  violations: {manifest['violations']}")
    print(f"  content_hash={manifest['content_hash']} cache_gen={manifest['cache_generation_hash']}")


if __name__ == "__main__":
    main()
