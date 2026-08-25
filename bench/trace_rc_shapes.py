"""
D7/C1 -- derive the exact RC1/RC2 constraint-fix shapes from the D6/T5 plausibility
trace, rather than from memory of Wikidata conventions.

For each affected cell, recompute the superset-repair additions, classify each
(entity, class) pair against the cached plausibility verdicts (same logic as
`bench/real_superset.py`'s `plausibility_check`), and for every CONTRADICTED entity
batch-fetch its real `wdt:P31` targets + labels in one combined SPARQL query. Tallying
those targets across all contradicted entities in a cell gives the empirically observed
meta-class / off-domain-class shape -- the exact evidence C1's constraint fixes must be
grounded in.

Read-only against the plausibility cache (extends it with the new label-lookup queries,
cached the same way). Prints a frequency table per cell; writes the raw tally to
results/rc_shape_trace.json for constraints_v2.py to consume.

Usage: python bench/trace_rc_shapes.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kgrepair import constraints                                     # noqa: E402
from kgrepair.ntriples import load_ntriples_file                     # noqa: E402
from kgrepair.pipeline.fetch import FetchPolicy, PoliteFetcher        # noqa: E402
from kgrepair.repair import superset_repair                          # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
REAL = os.path.join(ROOT, "fixtures", "real")
RESULTS = os.path.join(ROOT, "results")
CACHE_PATH = os.path.join(ROOT, "data", "raw", "plausibility", "wikidata", "ask_cache.json")
LABEL_CACHE_PATH = os.path.join(ROOT, "data", "raw", "plausibility", "wikidata", "label_cache.json")

WD_ENTITY = "http://www.wikidata.org/entity/"
WD_PROP = "http://www.wikidata.org/prop/direct/"
ENDPOINT = "https://query.wikidata.org/sparql"

# (cellkey, domain, slice_basename)
CELLS = [
    ("anatomy_1000", "anatomy", "real_wikidata_anatomy_1000_typed"),
    ("disease_1000", "disease", "real_wikidata_disease_1000"),
    ("medication_1000", "medication", "real_wikidata_medication_1000_typed"),
]


def _expand(curie):
    if curie.startswith("wd:"):
        return WD_ENTITY + curie[3:]
    if curie.startswith("wdt:"):
        return WD_PROP + curie[4:]
    return curie


def _compress(iri):
    if iri.startswith(WD_ENTITY):
        return "wd:" + iri[len(WD_ENTITY):]
    if iri.startswith(WD_PROP):
        return "wdt:" + iri[len(WD_PROP):]
    return iri


def added_type_edges(domain, basename):
    """(entity, class, constraint_id) for every named-provenance added type edge --
    constraint_id is kept throughout so shared class tests (e.g. tau_Disease reused by
    both dis.wd.* and med.wd.rng.treats) are attributed to the RIGHT constraint, not
    conflated by (entity, class) alone."""
    path = os.path.join(REAL, basename + ".nt")
    g = load_ntriples_file(path)
    cs = constraints.get(domain, "wikidata")
    res = superset_repair(g, cs, in_place=True, prune=True)
    out = []
    for r in res.changelog:
        if r.op == "add_edge" and r.provenance == "named":
            out.append((r.src, r.dst, r.constraint))
    return out


def classify(ask_cache, entity, cls):
    key = f"{entity}||{cls}"
    typed = ask_cache.get(key)
    if typed is True:
        return "corroborated"
    has_type_key = f"{entity}||__ANYTYPE__"
    has_type = ask_cache.get(has_type_key)
    if has_type is True:
        return "contradicted"
    if has_type is False:
        return "plausible"
    return "unknown"  # not in cache -- shouldn't happen post-T5, reported not guessed


def batch_fetch_p31(fetcher, entities, label_cache):
    """One SPARQL SELECT for every entity's P31 targets + English labels, via VALUES.
    Skips entities already in label_cache."""
    todo = sorted(e for e in entities if e not in label_cache)
    if not todo:
        return
    values = " ".join(f"<{_expand(e)}>" for e in todo)
    query = f"""PREFIX wdt: <{WD_PROP}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?entity ?type ?typeLabel WHERE {{
  VALUES ?entity {{ {values} }}
  ?entity wdt:P31 ?type .
  OPTIONAL {{ ?type rdfs:label ?typeLabel . FILTER(LANG(?typeLabel) = "en") }}
}}"""
    data = urllib.parse.urlencode({"query": query, "format": "json"}).encode()
    req = urllib.request.Request(ENDPOINT, data=data, headers={
        "Accept": "application/sparql-results+json", "User-Agent": fetcher.policy.accept})
    for attempt in range(3):
        try:
            time.sleep(fetcher.policy.min_interval_s)
            resp = urllib.request.urlopen(req, timeout=60)
            body = json.loads(resp.read().decode())
            break
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"  batch fetch attempt {attempt} failed: {e}")
            time.sleep(3)
    else:
        print(f"  WARNING: batch fetch failed for {len(todo)} entities after 3 attempts")
        return
    per_entity = {}
    for b in body["results"]["bindings"]:
        ent = _compress(b["entity"]["value"])
        typ = _compress(b["type"]["value"])
        lbl = b.get("typeLabel", {}).get("value", "")
        per_entity.setdefault(ent, []).append((typ, lbl))
    for e in todo:
        label_cache[e] = per_entity.get(e, [])


def main():
    ask_cache = json.load(open(CACHE_PATH)) if os.path.exists(CACHE_PATH) else {}
    label_cache = json.load(open(LABEL_CACHE_PATH)) if os.path.exists(LABEL_CACHE_PATH) else {}
    fetcher = PoliteFetcher(FetchPolicy(min_interval_s=1.0, timeout_s=60))

    # bucket by (cellkey, constraint_id) -- NOT just cellkey: a cell can host several
    # constraints (e.g. medication_1000 hosts both med.wd.dom.treats and
    # med.wd.rng.treats, which share no class test and must not be conflated).
    report = {}
    all_contradicted_by_constraint = {}
    for cellkey, domain, basename in CELLS:
        edges = added_type_edges(domain, basename)
        by_constraint = {}
        for (entity, cls, cid) in edges:
            by_constraint.setdefault(cid, set()).add((entity, cls))

        for cid, pairs in sorted(by_constraint.items()):
            contradicted_entities = sorted({e for (e, c) in pairs
                                            if classify(ask_cache, e, c) == "contradicted"})
            all_contradicted_by_constraint.setdefault(cid, set()).update(contradicted_entities)

    fetcher_batch = set()
    for cid, ents in all_contradicted_by_constraint.items():
        fetcher_batch.update(ents)
    print(f"fetching P31 types for {len(fetcher_batch)} unique contradicted entities...")
    batch_fetch_p31(fetcher, fetcher_batch, label_cache)
    json.dump(label_cache, open(LABEL_CACHE_PATH, "w"), indent=0, sort_keys=True)

    for cid in sorted(all_contradicted_by_constraint):
        contradicted_entities = sorted(all_contradicted_by_constraint[cid])
        tally = Counter()
        examples_by_class = {}
        for e in contradicted_entities:
            for (typ, lbl) in label_cache.get(e, []):
                tally[(typ, lbl)] += 1
                examples_by_class.setdefault((typ, lbl), []).append(e)
        ranked = tally.most_common(10)
        print(f"\n=== {cid}: {len(contradicted_entities)} contradicted entities ===")
        for (typ, lbl), n in ranked:
            print(f"  {n:4} x  {typ:16} {lbl!r:30} e.g. {examples_by_class[(typ,lbl)][:2]}")
        report[cid] = {
            "contradicted_count": len(contradicted_entities),
            "class_tally": [{"class": typ, "label": lbl, "count": n,
                            "examples": examples_by_class[(typ, lbl)][:5]}
                           for (typ, lbl), n in ranked],
        }

    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "rc_shape_trace.json"), "w") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nwrote {os.path.join(RESULTS, 'rc_shape_trace.json')}")


if __name__ == "__main__":
    main()
