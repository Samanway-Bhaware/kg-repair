"""
P8a/F2: how far each never-probed cell can actually be fetched.

The size ladder is built by fetching a cell once at its ceiling and slicing every
smaller rung out of that one generation. This measures the ceiling for the cells that
have never been fetched above target 1000, so the fixed-rung quality matrix can be
set at a rung every cell can serve.

Writes into a SEPARATE cache root (`data/raw_genB/<domain>/`). Generation A's cache
lives under `data/raw/` and a fetch into it would add segments and move its
generation hash, which is exactly what happened to anatomy and medication during the
D6/T0 typing closure. Generation B gets its own root so generation A stays readable
and its hash stays meaningful.

Two measurements, and they answer different questions:

  * the fetch ceiling: how many allow-listed edges the seed-anchored frontier walk
    reaches, and what stopped it (an exhausted frontier, the target cap, or the
    request budget);
  * allow-list coverage: for a sample of the nodes actually queried, how much of
    their outgoing structure the allow-list admits. This is what says whether a
    ceiling is a ceiling on allow-listed structure or on the source graph.

On the second measurement and Level 0: the coverage queries are COUNT aggregates, so
the endpoint returns integers and never the triples themselves. No person-pointing or
organisation-pointing triple enters this process, let alone reaches disk. That is
stricter than the fetch path, which relies on the query's predicate restriction.

Usage:
  export SSL_CERT_FILE=$(python3 -c "import certifi;print(certifi.where())")
  python bench/frontier_probe.py --target 50000
  python bench/frontier_probe.py --cells wikidata:disease --target 50000
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from kgrepair.pipeline import RawCache, load_allowlist                    # noqa: E402
from kgrepair.pipeline.extract import (DBPEDIA_ENDPOINT, SEEDS,           # noqa: E402
                                       WIKIDATA_ENDPOINT, _cached_edge_count,
                                       _prefix_header, _queried_subjects,
                                       sparql_extract)
from kgrepair.pipeline.fetch import USER_AGENT, FetchPolicy, PoliteFetcher  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
CACHE_ROOT_B = os.path.join(ROOT, "data", "raw_genB")
OUT_DIR = os.path.join(ROOT, "eval")

#: The predicate universe each cell's coverage is measured against. Wikidata's
#: allow-list is a subset of the direct-property namespace, so comparing against
#: every predicate on an entity (labels, statement nodes, site links) would answer a
#: different question. DBpedia's allow-list spans ontology and schema predicates, so
#: the universe there is everything with an IRI object.
_UNIVERSE_FILTER = {
    "wikidata": 'FILTER(STRSTARTS(STR(?p), "http://www.wikidata.org/prop/direct/"))',
    "dbpedia": "FILTER(isIRI(?o))",
}

STOP_EXHAUSTED = "frontier exhausted"
STOP_TARGET = "target cap"
STOP_REQUESTS = "request budget"


def endpoint_of(source):
    return WIKIDATA_ENDPOINT if source == "wikidata" else DBPEDIA_ENDPOINT


 
# which cells have never been fetched above target 1000
 
def derive_cells():
    """(source, domain) cells whose largest committed rung is 1000 or below.

    Derived from `bench/real_ladder.py` CELLS rather than written down, so a cell
    added to the campaign later is picked up here without editing this file.
    """
    from real_ladder import CELLS
    largest = {}
    for source, domain, target, _live in CELLS:
        key = (source, domain)
        largest[key] = max(largest.get(key, 0), target)
    return sorted(key for key, top in largest.items() if top <= 1000), largest


 
# allow-list coverage, as counts only
 
def _sparql_select(fetcher, endpoint, query):
    """POST a SELECT and return its bindings, retrying like the library fetcher.

    Written here rather than in `kgrepair.pipeline.fetch` because it exists for this
    measurement: the fetch path needs CONSTRUCT and ASK, and neither wants a counting
    helper. The retry and backoff behaviour is copied deliberately. Without it the
    first burst of coverage queries earns a 429 and the measurement dies halfway,
    which is exactly what happened when this was written without one.
    """
    data = urllib.parse.urlencode({"query": query}).encode("utf-8")
    headers = {"User-Agent": USER_AGENT,
               "Accept": "application/sparql-results+json",
               "Content-Type": "application/x-www-form-urlencoded"}
    for attempt in range(fetcher.policy.max_retries + 1):
        fetcher._throttle()                   # same politeness as every other request
        req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=fetcher.policy.timeout_s) as resp:
                body = json.loads(resp.read().decode("utf-8", errors="replace"))
            fetcher._last_request = time.perf_counter()
            fetcher.request_count += 1
            return body.get("results", {}).get("bindings", [])
        except urllib.error.HTTPError as exc:
            fetcher._last_request = time.perf_counter()
            if exc.code in (429, 500, 502, 503, 504) and attempt < fetcher.policy.max_retries:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                wait = (float(retry_after) if retry_after and retry_after.isdigit()
                        else fetcher.policy.backoff_base_s * (2 ** attempt))
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            fetcher._last_request = time.perf_counter()
            if attempt < fetcher.policy.max_retries:
                time.sleep(fetcher.policy.backoff_base_s * (2 ** attempt))
                continue
            raise
    raise RuntimeError("exhausted retries on a coverage query")


def coverage(source, cache, fetcher, *, sample_size, batch=10):
    """How much of the sampled nodes' outgoing structure the allow-list admits.

    One grouped-count query per batch: predicate IRIs with a count each, over the
    predicate universe for this source. The allow-listed and dropped halves are then
    split locally, which also gives the per-predicate breakdown.

    Asking for counts grouped by predicate rather than two totals is not only tidier.
    A `VALUES ?s` and `VALUES ?p` pair in one query returns zero rows on the Wikidata
    endpoint even where the same restriction inside a CONSTRUCT returns triples, so
    the two-total version silently measured nothing. Counting the universe once and
    splitting locally cannot drift from the allow-list, because it reads the same
    `al.allows`.

    Level 0: predicate IRIs and integers come back. Object values never do, so no
    person-pointing or organisation-pointing value enters this process.
    """
    al = load_allowlist(source)
    queried = sorted(_queried_subjects(cache, source))
    if not queried:
        return {"sampled": 0, "note": "no node was queried, so nothing to sample"}
    # evenly spaced through the sorted list, so the sample is not all seeds
    step = max(1, len(queried) // sample_size)
    nodes = queried[::step][:sample_size]
    universe = _UNIVERSE_FILTER[source]
    header = _prefix_header(al)

    per_predicate = {}
    for i in range(0, len(nodes), batch):
        chunk = " ".join(nodes[i:i + batch])
        rows = _sparql_select(fetcher, endpoint_of(source), (
            f"{header}\nSELECT ?p (COUNT(*) AS ?n) WHERE {{\n"
            f"  VALUES ?s {{ {chunk} }}\n  ?s ?p ?o .\n  {universe}\n}} GROUP BY ?p"))
        for row in rows:
            curie = al.curie_of(row["p"]["value"])
            per_predicate[curie] = per_predicate.get(curie, 0) + int(row["n"]["value"])

    allowed = {p: n for p, n in per_predicate.items() if al.allows(p)}
    dropped = {p: n for p, n in per_predicate.items() if not al.allows(p)}
    total_all = sum(per_predicate.values())
    total_allowed = sum(allowed.values())
    total_dropped = sum(dropped.values())
    top_dropped = sorted(dropped.items(), key=lambda kv: (-kv[1], kv[0]))[:15]
    return {"sampled": len(nodes), "universe": universe,
            "triples_in_universe": total_all,
            "triples_allow_listed": total_allowed,
            "triples_dropped": total_dropped,
            "dropped_fraction": round(total_dropped / total_all, 4) if total_all else None,
            "allow_listed_by_predicate": dict(sorted(allowed.items())),
            "top_dropped_by_predicate": dict(top_dropped),
            "distinct_predicates_seen": len(per_predicate),
            "distinct_predicates_allow_listed": len(allowed)}


 
# the probe
 
def probe_cell(source, domain, *, target, max_requests, sample_size, min_interval):
    cache = RawCache(os.path.join(CACHE_ROOT_B, domain))
    al = load_allowlist(source)
    fetcher = PoliteFetcher(FetchPolicy(min_interval_s=min_interval, timeout_s=120))

    before = _cached_edge_count(cache, al)
    t0 = time.perf_counter()
    report = sparql_extract(source, domain, cache, fetcher, target_edges=target,
                            max_requests=max_requests)
    elapsed = time.perf_counter() - t0

    # What stopped it, measured rather than inferred: a node that entered the cache
    # and was never queried is frontier the walk did not get to.
    present = set()
    for s, p, o, is_lit in cache.iter_raw_triples(source):
        pc = al.curie_of(p)
        if not al.allows(pc):
            continue
        present.add(al.curie_of(s))
        if not is_lit:
            present.add(al.curie_of(o))
    queried = _queried_subjects(cache, source)
    expandable = tuple(f"{p}:" for p in al.prefixes)
    remaining = sorted(n for n in present
                       if n not in queried and n.startswith(expandable))

    want = int(target * 1.5)                  # sparql_extract's over_fetch default
    edges = report["cached_edges"]
    if report["requests"] >= max_requests:
        stop = STOP_REQUESTS
    elif edges >= want:
        stop = STOP_TARGET
    elif not remaining:
        stop = STOP_EXHAUSTED
    else:
        stop = STOP_EXHAUSTED                 # frontier list emptied before the caps

    cov = coverage(source, cache, fetcher, sample_size=sample_size) if sample_size else {}

    return {
        "source": source, "domain": domain, "target_edges": target,
        "over_fetch_want": want,
        "cached_edges_before": before, "cached_edges": edges,
        "requests": report["requests"], "max_requests": max_requests,
        "batches": report["requests"],
        "seeds": len(SEEDS[source][domain]),
        "nodes_queried": len(queried), "nodes_present": len(present),
        "frontier_remaining": len(remaining),
        "stop_reason": stop,
        "wall_clock_s": round(elapsed, 1),
        "cache_generation_hash": cache.generation_hash(source),
        "coverage": cov,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=50000)
    ap.add_argument("--max-requests", type=int, default=400)
    ap.add_argument("--sample", type=int, default=40,
                    help="nodes sampled for the allow-list coverage counts (0 to skip)")
    ap.add_argument("--min-interval", type=float, default=1.0)
    ap.add_argument("--cells", default="",
                    help="comma-separated source:domain, default is the derived list")
    ap.add_argument("--out", default=os.path.join(OUT_DIR, "frontier_probe.json"))
    args = ap.parse_args()

    derived, largest = derive_cells()
    if args.cells:
        cells = [tuple(c.split(":", 1)) for c in args.cells.split(",")]
    else:
        cells = derived

    print(f"derived cell list (largest committed rung <= 1000): "
          f"{[':'.join(c) for c in derived]}")
    print(f"probing: {[':'.join(c) for c in cells]}\n")

    rows = []
    for source, domain in cells:
        print(f"-- {source}:{domain} target={args.target} ...", flush=True)
        try:
            row = probe_cell(source, domain, target=args.target,
                             max_requests=args.max_requests, sample_size=args.sample,
                             min_interval=args.min_interval)
        except Exception as exc:                  # a cell that fails is reported, not fatal
            row = {"source": source, "domain": domain, "target_edges": args.target,
                   "status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}
        rows.append(row)
        print(f"   {json.dumps({k: v for k, v in row.items() if k != 'coverage'})}")
        if row.get("coverage"):
            print(f"   coverage: {json.dumps(row['coverage'])}")
        print(flush=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    payload = {"target_edges": args.target, "max_requests": args.max_requests,
               "cache_root": os.path.relpath(CACHE_ROOT_B, ROOT),
               "derived_cells": [":".join(c) for c in derived],
               "largest_committed_rung": {f"{s}:{d}": t for (s, d), t in sorted(largest.items())},
               "cells": rows}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
