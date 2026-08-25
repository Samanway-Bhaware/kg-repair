"""
E2 (Day 3) -- closed-loop vetting: repair under MINED constraints, plausibility-
check the additions against live Wikidata, and trace contradicted additions back
to entity level -- the full mine -> repair -> vet -> indict loop, no hand-curation.

Threshold choice (justified from E1's sensitivity curve, not asserted): 0.90, the
loosest threshold tested. It is the ONLY threshold at which either cell's mined
set contains anything E1 could match to a hand-curated rule at all (medication's
Q112193867 "type of disease" recovery happens only at 90%; anatomy recovers
nothing at any threshold). Using a tighter threshold here would silently exclude
the one candidate set with any known real signal in it -- 0.90 is the set that
gives the closed loop something real to vet, at the cost of including more of
E1's documented root-class noise. That noise is the point of running the loop:
does live plausibility-checking correctly separate it from the signal?

v1/v2 comparison numbers are NOT re-derived here (a sprint non-goal: "no re-runs
of settled D7 tables") -- they are read directly from the existing
results/v1_vs_v2_eval.json, the same artifact docs/evaluation.md Table 7 cites.

Live queries go through the project's own PoliteFetcher, cached in
data/raw/mining/ (NOT data/raw/plausibility/, D6/D7's cache) -- a new,
sprint-scoped cache generation per the isolation rule.

Usage: python experimental/mining/e2_closed_loop.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from kgrepair.constraints.model import Constraint, ConstraintSet   # noqa: E402
from kgrepair.ntriples import load_ntriples_file                    # noqa: E402
from kgrepair.pipeline.fetch import FetchPolicy, PoliteFetcher       # noqa: E402
from kgrepair.repair import core_constraints, superset_repair        # noqa: E402
from kgrepair.validator import Validator                             # noqa: E402

from experimental.mining.log import log_run    # noqa: E402

CANDIDATES_DIR = os.path.join(os.path.dirname(__file__), "candidates")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
REAL = os.path.join(ROOT, "fixtures", "real")
MINING_CACHE_DIR = os.path.join(ROOT, "data", "raw", "mining")
ASK_CACHE_PATH = os.path.join(MINING_CACHE_DIR, "ask_cache.json")
ENTITY_TYPE_CACHE_PATH = os.path.join(MINING_CACHE_DIR, "entity_type_cache.json")

WD_ENTITY = "http://www.wikidata.org/entity/"
WD_PROP = "http://www.wikidata.org/prop/direct/"
ENDPOINT = "https://query.wikidata.org/sparql"

THRESHOLD = 0.90
ADDITION_CAP = 0.30       # SUPERSET_CAP_DEFAULT convention (app/caps.py, bench/real_superset.py)
PLAUSIBILITY_PER_CELL_CAP = 150
MIN_SAMPLE_CONTRADICTED = 20

# (cellkey matching results/v1_vs_v2_eval.json's "cell", domain, slice basename)
CELLS = [
    ("anatomy_1000", "anatomy", "real_wikidata_anatomy_1000_typed"),
    ("medication_1000", "medication", "real_wikidata_medication_1000_typed"),
]


def _expand(curie: str) -> str:
    if curie.startswith("wd:"):
        return WD_ENTITY + curie[3:]
    if curie.startswith("wdt:"):
        return WD_PROP + curie[4:]
    return curie


def _load_mined_constraint_set(slice_name: str, threshold: float) -> ConstraintSet:
    path = os.path.join(CANDIDATES_DIR, f"{slice_name}_{threshold:.2f}.json")
    with open(path, encoding="utf-8") as fh:
        dicts = json.load(fh)
    cs = ConstraintSet(f"mined@{slice_name}@{threshold:.2f}")
    for d in dicts:
        cs.add(Constraint.from_dict(d))
    return cs


def _core_witness_fraction(g, cs) -> Tuple[int, int, float]:
    val = Validator(g, use_closure=True)
    total = sum(len(val.check_one(c).witnesses) for c in core_constraints(cs))
    e = g.num_edges()
    return total, e, total / max(1, e)


def _type_edges_added(res) -> List[Tuple[str, str, str]]:
    return sorted({(r.src, r.dst, r.constraint) for r in res.changelog
                   if r.op == "add_edge" and r.provenance == "named"})


def _load_cache(path: str) -> Dict:
    return json.load(open(path)) if os.path.exists(path) else {}


def _save_cache(path: str, cache: Dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(cache, open(path, "w"), indent=0, sort_keys=True)


def _cached_ask(cache: Dict, key: str, query: str, fetcher: PoliteFetcher) -> Optional[bool]:
    """Cached ASK, saving after every NEW fetch (not just at the end) -- a
    transient network failure mid-run must not lose already-completed queries.
    Returns None (not a crash) on failure, so the caller can record 'unknown'."""
    if key in cache:
        return cache[key]
    try:
        val = fetcher.sparql_ask(ENDPOINT, query)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"  WARNING: ASK failed for {key!r}: {exc} -- marking unknown, continuing")
        return None
    cache[key] = val
    _save_cache(ASK_CACHE_PATH, cache)
    return val


def plausibility_check(type_edges: List[Tuple[str, str, str]], fetcher: PoliteFetcher,
                       *, per_cell_cap: int) -> Dict:
    cache = _load_cache(ASK_CACHE_PATH)

    def ask_typed(entity: str, cls: str):
        q = f"ASK {{ <{_expand(entity)}> <{WD_PROP}P31>/<{WD_PROP}P279>* <{_expand(cls)}> }}"
        return _cached_ask(cache, f"{entity}||{cls}", q, fetcher)

    def ask_has_type(entity: str):
        q = f"ASK {{ <{_expand(entity)}> <{WD_PROP}P31> ?t }}"
        return _cached_ask(cache, f"{entity}||__ANYTYPE__", q, fetcher)

    checked = sorted(set(type_edges))[:per_cell_cap]
    corroborated = contradicted = plausible = unknown = 0
    contradicted_entities: List[Tuple[str, str, str]] = []   # (entity, mined_class, cid)
    for (entity, cls, cid) in checked:
        typed = ask_typed(entity, cls)
        if typed is None:
            unknown += 1
            continue
        if typed:
            corroborated += 1
            continue
        has_type = ask_has_type(entity)
        if has_type is None:
            unknown += 1
        elif has_type:
            contradicted += 1
            contradicted_entities.append((entity, cls, cid))
        else:
            plausible += 1
    n_classified = corroborated + contradicted + plausible
    return {
        "type_edges_total": len(type_edges), "checked": len(checked),
        "classified": n_classified, "unknown": unknown,
        "corroborated": corroborated, "contradicted": contradicted, "plausible": plausible,
        "precision": corroborated / n_classified if n_classified else None,
        "contradicted_entities": contradicted_entities,
    }


def trace_contradicted(contradicted_entities: List[Tuple[str, str, str]],
                       fetcher: PoliteFetcher, *, sample_size: int) -> Dict:
    """C1-style entity-level trace: for a sample of contradicted (entity, mined_class,
    cid) triples, batch-fetch each entity's REAL wdt:P31 targets + English labels, and
    tally which mined constraint (cid) the contradictions indict."""
    sample = contradicted_entities[:sample_size]
    entities = sorted({e for (e, _c, _cid) in sample})
    cache = _load_cache(ENTITY_TYPE_CACHE_PATH)
    todo = sorted(e for e in entities if e not in cache)
    if todo:
        values = " ".join(f"<{_expand(e)}>" for e in todo)
        query = (f"PREFIX wdt: <{WD_PROP}>\nPREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
                 f"SELECT ?entity ?type ?typeLabel WHERE {{\n  VALUES ?entity {{ {values} }}\n"
                 f"  ?entity wdt:P31 ?type .\n"
                 f"  OPTIONAL {{ ?type rdfs:label ?typeLabel . FILTER(LANG(?typeLabel) = \"en\") }}\n}}")
        data = urllib.parse.urlencode({"query": query, "format": "json"}).encode()
        req = urllib.request.Request(ENDPOINT, data=data, headers={
            "Accept": "application/sparql-results+json", "User-Agent": fetcher.policy.accept})
        try:
            fetcher._throttle()
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode())
            fetcher._last_request = __import__("time").perf_counter()
            fetcher.request_count += 1
            per_entity: Dict[str, List[str]] = {}
            for b in body["results"]["bindings"]:
                ent = "wd:" + b["entity"]["value"].rsplit("/", 1)[-1]
                label = b.get("typeLabel", {}).get("value", "(no label)")
                per_entity.setdefault(ent, []).append(label)
            for e in todo:
                cache[e] = per_entity.get(e, [])
        except (urllib.error.URLError, TimeoutError) as exc:
            for e in todo:
                cache.setdefault(e, [f"FETCH_FAILED: {exc}"])
        _save_cache(ENTITY_TYPE_CACHE_PATH, cache)

    indicted_by_cid: Dict[str, int] = {}
    traced = []
    for (entity, mined_cls, cid) in sample:
        real_types = cache.get(entity, [])
        indicted_by_cid[cid] = indicted_by_cid.get(cid, 0) + 1
        traced.append({"entity": entity, "mined_class": mined_cls, "indicted_constraint": cid,
                       "real_p31_labels": real_types})
    return {"sample_size": len(sample), "indicted_by_constraint": indicted_by_cid,
           "traced": traced}


def run_cell(cellkey: str, domain: str, slice_name: str, fetcher: PoliteFetcher) -> Dict:
    g = load_ntriples_file(os.path.join(REAL, f"{slice_name}.nt"))
    mined_cs = _load_mined_constraint_set(slice_name, THRESHOLD)
    planned, e, frac = _core_witness_fraction(g, mined_cs)

    result = {"cell": cellkey, "domain": domain, "slice": slice_name,
             "mined_constraint_count": len(mined_cs), "planned_additions": planned,
             "E": e, "add_fraction": frac, "cap": ADDITION_CAP}

    if frac > ADDITION_CAP:
        result["status"] = "ABORTED-BY-CAP"
        result["note"] = (f"mined set's {planned} planned additions over {e} edges "
                          f"({frac:.1%}) exceed the {ADDITION_CAP:.0%} cap -- repair NOT run")
        run_id = log_run("E2", {"cell": cellkey, "status": "ABORTED-BY-CAP",
                                "add_fraction": frac, "mined_constraint_count": len(mined_cs)})
        result["run_id"] = run_id
        return result

    res = superset_repair(g, mined_cs, in_place=True, prune=True)
    result["status"] = "repaired"
    result["added_edges"] = len(res.added_edges)
    result["added_nodes"] = len(res.added_nodes)
    result["rounds"] = res.rounds
    result["attestations"] = res.attestations

    type_edges = _type_edges_added(res)
    plaus = plausibility_check(type_edges, fetcher, per_cell_cap=PLAUSIBILITY_PER_CELL_CAP)
    result["plausibility"] = {k: v for k, v in plaus.items() if k != "contradicted_entities"}

    trace = trace_contradicted(plaus["contradicted_entities"], fetcher,
                               sample_size=max(MIN_SAMPLE_CONTRADICTED, 0))
    result["indictment_trace"] = trace

    run_id = log_run("E2", {
        "cell": cellkey, "status": "repaired", "add_fraction": frac,
        "mined_constraint_count": len(mined_cs), "added_edges": result["added_edges"],
        "plausibility": result["plausibility"],
        "indicted_by_constraint": trace["indicted_by_constraint"],
    })
    result["run_id"] = run_id
    return result


def three_way_table() -> Dict[str, Dict]:
    """v1/v2 numbers read from the existing D7 artifact, NOT re-derived here."""
    path = os.path.join(ROOT, "results", "v1_vs_v2_eval.json")
    with open(path, encoding="utf-8") as fh:
        rows = json.load(fh)["rows"]
    return {r["cell"]: r for r in rows}


def main() -> None:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    fetcher = PoliteFetcher(FetchPolicy(min_interval_s=1.0, timeout_s=60))
    v1v2 = three_way_table()

    cell_results = []
    for cellkey, domain, slice_name in CELLS:
        print(f"=== {cellkey} ===")
        res = run_cell(cellkey, domain, slice_name, fetcher)
        res["v1"] = {"additions": v1v2[cellkey]["additions_v1"],
                    "checked": v1v2[cellkey]["checked_v1"],
                    "corroborated": v1v2[cellkey]["corrob_v1"],
                    "precision": v1v2[cellkey]["prec_v1"]}
        res["v2"] = {"additions": v1v2[cellkey]["additions_v2"],
                    "checked": v1v2[cellkey]["checked_v2"],
                    "corroborated": v1v2[cellkey]["corrob_v2"],
                    "precision": v1v2[cellkey]["prec_v2"]}
        cell_results.append(res)
        print(json.dumps({k: v for k, v in res.items() if k != "indictment_trace"}, indent=2))

    out_path = os.path.join(RESULTS_DIR, "e2_closed_loop.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({"threshold": THRESHOLD, "cap": ADDITION_CAP, "cells": cell_results},
                  fh, indent=2, sort_keys=True)
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
