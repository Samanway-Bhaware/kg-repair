"""
Per-source extractors (Stage-1 fetch into the cache).

SPARQL sources (Wikidata, DBpedia): cache-aware, deterministic-order frontier BFS.
Each round issues one CONSTRUCT over a sorted batch of frontier nodes restricted to
the allow-listed predicates (declared with the source's prefixes). Responses are
defensively re-filtered through the allow-list before `RawCache.store`, so no
person/org triple ever reaches disk (Level-0). Resumable: a query whose text is
already cached is not re-fetched.

YAGO 4.5 (dump): two-pass stream-filter over the downloaded tiny dump -- pass 1
collects the frontier's node ids reachable over allow-listed edges from the seeds up
to a hop cap; pass 2 emits the allow-listed edges among frontier nodes. Chosen over a
single pass because the frontier is seed-anchored and the dump is unordered, so we
must know the frontier before deciding which edges to keep.

The fetch layer only fills the cache; deterministic sizing is Stage-2 (`slicing`).
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, Iterable, List, Set, Tuple

from ..ntriples import iter_triples
from .allowlist import AllowList, load_allowlist
from .cache import RawCache
from .fetch import PoliteFetcher
from .yago_turtle import iter_single_line_facts

WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"
DBPEDIA_ENDPOINT = "https://dbpedia.org/sparql"

# Non-person seeds (geographic features, countries, taxa, biomedical concepts).
# Documented Level-0-safe: cities/countries/taxa/anatomy/disease/medication only.
# More seeds -> larger reachable frontier (DBpedia especially needs breadth, its geo
# predicates branch shallowly). All entries are non-person: settlements, admin areas,
# countries, taxa, anatomical structures, diseases, medications.
_WD_CITIES = ["Q64", "Q84", "Q90", "Q60", "Q1490", "Q65", "Q1492", "Q220", "Q1741",
              "Q1748", "Q1055", "Q1218", "Q1524", "Q2807", "Q1085", "Q1731", "Q1794",
              "Q1726", "Q1780", "Q2044", "Q2079", "Q1899", "Q4093", "Q1963", "Q2634"]
_WD_COUNTRIES = ["Q183", "Q145", "Q142", "Q30", "Q17", "Q29", "Q38", "Q40", "Q31",
                 "Q55", "Q34", "Q35", "Q20", "Q27", "Q45", "Q77", "Q96", "Q155"]
_DB_CITIES = ["Berlin", "London", "Paris", "New_York_City", "Tokyo", "Rome", "Vienna",
              "Madrid", "Amsterdam", "Brussels", "Copenhagen", "Oslo", "Stockholm",
              "Helsinki", "Dublin", "Lisbon", "Warsaw", "Prague", "Budapest", "Athens",
              "Munich", "Hamburg", "Barcelona", "Milan", "Naples", "Lyon", "Marseille",
              "Toronto", "Chicago", "Boston", "Sydney", "Melbourne", "Osaka", "Kyoto",
              "Frankfurt", "Cologne", "Stuttgart", "Zurich", "Geneva", "Venice",
              "Florence", "Turin", "Seville", "Valencia", "Porto", "Rotterdam",
              "Antwerp", "Gothenburg", "Bergen", "Aarhus", "Krakow", "Gdansk",
              "Brno", "Bratislava", "Ljubljana", "Zagreb", "Bucharest", "Sofia",
              "Belgrade", "Thessaloniki", "Manchester", "Birmingham", "Glasgow",
              "Edinburgh", "Liverpool", "Leeds", "Bristol", "Montreal", "Vancouver",
              "Ottawa", "Calgary", "Philadelphia", "Houston", "Phoenix", "Nagoya",
              "Sapporo", "Fukuoka", "Brisbane", "Perth", "Adelaide", "Auckland"]
_DB_COUNTRIES = ["Germany", "France", "Japan", "United_Kingdom", "Italy", "Spain",
                 "Netherlands", "Belgium", "Poland", "Austria", "Canada", "Australia"]

SEEDS: Dict[str, Dict[str, List[str]]] = {
    "wikidata": {
        "geography": [f"wd:{q}" for q in _WD_CITIES + _WD_COUNTRIES],
        "taxa": ["wd:Q140", "wd:Q25265", "wd:Q26214", "wd:Q7377", "wd:Q19939",
                 "wd:Q144", "wd:Q146", "wd:Q83310", "wd:Q42569", "wd:Q158695",
                 "wd:Q127960", "wd:Q25324", "wd:Q10884", "wd:Q10908", "wd:Q184425",
                 "wd:Q7368", "wd:Q9394", "wd:Q3736439", "wd:Q152", "wd:Q159226"],
        "anatomy": ["wd:Q1072", "wd:Q9649", "wd:Q1073", "wd:Q9394", "wd:Q7891",
                    "wd:Q9635", "wd:Q712378", "wd:Q9584", "wd:Q1074", "wd:Q9103",
                    "wd:Q9644", "wd:Q40397", "wd:Q483213", "wd:Q712547"],
        "disease": ["wd:Q2840", "wd:Q12078", "wd:Q12136", "wd:Q18123741", "wd:Q35869",
                    "wd:Q3241045", "wd:Q39833", "wd:Q131742", "wd:Q12252", "wd:Q83267",
                    "wd:Q133823", "wd:Q41112", "wd:Q18965518", "wd:Q188008"],
        "medication": ["wd:Q18216", "wd:Q188724", "wd:Q422985", "wd:Q412415",
                       "wd:Q205204", "wd:Q407431", "wd:Q188451", "wd:Q201928",
                       "wd:Q47521", "wd:Q212405", "wd:Q422", "wd:Q18936"],
    },
    "dbpedia": {
        "geography": [f"dbr:{c}" for c in _DB_CITIES + _DB_COUNTRIES],
        "taxa": ["dbr:Lion", "dbr:Tiger", "dbr:Domestic_dog", "dbr:Cat", "dbr:Oak",
                 "dbr:Rose", "dbr:Honey_bee", "dbr:Brown_bear", "dbr:Wolf", "dbr:Horse",
                 "dbr:Cattle", "dbr:Chicken", "dbr:Apple", "dbr:Maize", "dbr:Rice",
                 "dbr:Salmon", "dbr:Eagle", "dbr:Frog", "dbr:Butterfly", "dbr:Pine"],
    },
    "yago": {
        "geography": ["yago:Berlin", "yago:London", "yago:Paris", "yago:Tokyo",
                      "yago:Germany", "yago:France", "yago:Japan", "yago:Rome",
                      "yago:Madrid", "yago:Vienna", "yago:Amsterdam", "yago:Italy"],
        "taxa": ["yago:Lion", "yago:Tiger", "yago:Dog", "yago:Cat", "yago:Oak",
                 "yago:Wolf", "yago:Horse", "yago:Apple", "yago:Salmon", "yago:Eagle"],
    },
}


def _prefix_header(al: AllowList) -> str:
    return "\n".join(f"PREFIX {p}: <{ns}>" for p, ns in sorted(al.prefixes.items()))


def _construct_query(al: AllowList, batch: List[str]) -> str:
    values_s = " ".join(sorted(batch))
    values_p = " ".join(sorted(al.predicates))
    return (f"{_prefix_header(al)}\n"
            f"CONSTRUCT {{ ?s ?p ?o }} WHERE {{\n"
            f"  VALUES ?s {{ {values_s} }}\n"
            f"  VALUES ?p {{ {values_p} }}\n"
            f"  ?s ?p ?o .\n}}")


# Typing spine per SPARQL source: the predicates tau_C walks (type + subClassOf).
# A typing-closure query fetches ONLY these, so it completes a node's type
# information without pulling in new domain edges that could create fresh
# antecedent matches (see typing_closure_extract).
_TYPING_PREDS = {
    "wikidata": ("wdt:P31", "wdt:P279"),
    "dbpedia": ("rdf:type", "rdfs:subClassOf"),
}


def _typing_query(al: AllowList, batch: List[str], preds: Tuple[str, ...]) -> str:
    values_s = " ".join(sorted(batch))
    values_p = " ".join(sorted(preds))
    return (f"{_prefix_header(al)}\n"
            f"CONSTRUCT {{ ?s ?p ?o }} WHERE {{\n"
            f"  VALUES ?s {{ {values_s} }}\n"
            f"  VALUES ?p {{ {values_p} }}\n"
            f"  ?s ?p ?o .\n}}")


_VALUES_S_RE = re.compile(r"VALUES\s+\?s\s*\{([^}]*)\}")


def _queried_subjects(cache: RawCache, source: str) -> Set[str]:
    """Every node that has appeared as ?s in a cached CONSTRUCT batch -- i.e. a node
    whose neighbourhood (full or typing-only) was actually fetched. Read from the
    cache's own query-text sidecars, so it is exact and generation-agnostic."""
    subs: Set[str] = set()
    d = cache.source_dir(source)
    if not os.path.isdir(d):
        return subs
    for name in sorted(os.listdir(d)):
        if not name.endswith(".meta.json"):
            continue
        with open(os.path.join(d, name), "r", encoding="utf-8") as fh:
            qt = (json.load(fh) or {}).get("query_text", "")
        for m in _VALUES_S_RE.finditer(qt):
            subs.update(tok for tok in m.group(1).split() if tok)
    return subs


def typing_closure_extract(source: str, domain: str, cache: RawCache,
                           fetcher: PoliteFetcher, *, batch_size: int = 40,
                           max_rounds: int = 8, max_requests: int = 60) -> Dict:
    """
    Close the typing spine (T0 fix): fetch `type`/`subClassOf` for EVERY node that
    entered the cache but was never queried as ?s -- the frontier-boundary nodes
    whose typing was never fetched by the seed-anchored BFS. Restricting the fetch to
    the typing predicates (not the full allow-list) means no new domain edges are
    added, so no fresh antecedent matches are created: the closure only ever *adds*
    the consequent-satisfying type information a boundary node genuinely has.

    Iterated to a fixpoint (bounded by `max_rounds`): typing a boundary node can
    reveal a new class node whose own subClassOf* chain is still unfetched, so we
    repeat until every referenced node has been queried (spine closed) or the caps
    fire. Resumable: query texts are content-addressed, so an already-cached typing
    query is not re-issued. Returns a small report; writes only NEW cache segments.
    """
    endpoint = WIKIDATA_ENDPOINT if source == "wikidata" else DBPEDIA_ENDPOINT
    al = load_allowlist(source)
    preds = _TYPING_PREDS[source]
    prefix = al.prefixes  # for the expandable-node test
    known_curie_prefixes = tuple(f"{p}:" for p in prefix)

    rounds = 0
    requests = 0
    while rounds < max_rounds and requests < max_requests:
        rounds += 1
        present: Set[str] = set()
        for s, p, o, is_lit in cache.iter_raw_triples(source):
            pc = al.curie_of(p)
            if not al.allows(pc):
                continue
            present.add(al.curie_of(s))
            if not is_lit:
                present.add(al.curie_of(o))
        queried = _queried_subjects(cache, source)
        # Only entity nodes are fetchable subjects; predicates/rdf-schema terms and
        # literal value-nodes are not. Restrict to prefix-expandable entity CURIEs.
        todo = sorted(n for n in present
                      if n not in queried and n.startswith(known_curie_prefixes))
        if not todo:
            break
        for i in range(0, len(todo), batch_size):
            if requests >= max_requests:
                break
            batch = todo[i:i + batch_size]
            query = _typing_query(al, batch, preds)
            body = fetcher.sparql_construct(endpoint, query)
            filtered, _new = _filter_body(body, al)
            cache.store(source, query, filtered, endpoint)
            requests += 1
    return {"source": source, "domain": domain, "closure_rounds": rounds,
            "closure_requests": requests,
            "cached_edges": _cached_edge_count(cache, al),
            "fetcher_requests": fetcher.request_count}


def _filter_body(body: str, al: AllowList) -> Tuple[str, Set[str]]:
    """Keep only allow-listed triples (Level-0 belt); return (filtered_ntriples,
    expandable new IRI object CURIEs)."""
    kept: List[str] = []
    new_nodes: Set[str] = set()
    known_ns = tuple(al.prefixes.values())
    for s, p, o_node, o_lit in iter_triples(body.splitlines()):
        pc = al.curie_of(p)
        if not al.allows(pc):
            continue
        kept.append(f"<{s}> <{p}> <{o_node}> ." if o_lit is None
                    else f'<{s}> <{p}> "{o_lit}" .')
        if o_lit is None and o_node.startswith(known_ns):
            new_nodes.add(al.curie_of(o_node))       # only prefix-expandable nodes expand
    return "\n".join(kept) + ("\n" if kept else ""), new_nodes


def _cached_edge_count(cache: RawCache, al: AllowList) -> int:
    n = 0
    for s, p, o, is_lit in cache.iter_raw_triples(al.source):
        if al.allows(al.curie_of(p)):
            n += 1
    return n


def sparql_extract(source: str, domain: str, cache: RawCache, fetcher: PoliteFetcher,
                   *, target_edges: int, batch_size: int = 40, max_requests: int = 60,
                   over_fetch: float = 1.5, extra_seeds: Iterable[str] = ()) -> Dict:
    """Frontier-BFS fetch for a SPARQL source into `cache`. Returns a small report."""
    endpoint = WIKIDATA_ENDPOINT if source == "wikidata" else DBPEDIA_ENDPOINT
    al = load_allowlist(source)
    seeds = list(SEEDS[source][domain]) + list(extra_seeds)

    visited: Set[str] = set()
    frontier: List[str] = sorted(set(seeds))
    requests = 0
    want = int(target_edges * over_fetch)
    while frontier and requests < max_requests and _cached_edge_count(cache, al) < want:
        batch = sorted(n for n in frontier if n not in visited)[:batch_size]
        if not batch:
            break
        query = _construct_query(al, batch)
        body = fetcher.sparql_construct(endpoint, query)
        filtered, new_nodes = _filter_body(body, al)
        cache.store(source, query, filtered, endpoint)
        requests += 1
        visited.update(batch)
        frontier = sorted(new_nodes - visited)
    return {"source": source, "domain": domain, "requests": requests,
            "cached_edges": _cached_edge_count(cache, al),
            "fetcher_requests": fetcher.request_count}


 
# YAGO 4.5 dump stream-filter (tiny dump)
 

def _yago_zip_lines(zip_path: str, inner_name: str):
    """Stream text lines from a Turtle entry inside a zip without full extraction."""
    import io
    import zipfile
    zf = zipfile.ZipFile(zip_path)
    with zf.open(inner_name) as raw:
        for line in io.TextIOWrapper(raw, encoding="utf-8", errors="replace"):
            yield line


def yago_stream_extract(zip_path: str, inner_name: str, domain: str, cache: RawCache,
                        *, seeds: Iterable[str] = (), type_seeds: Iterable[str] = (),
                        max_frontier: int = 20000, hop_cap: int = 4) -> Dict:
    """
    Single-pass allow-list stream-filter over the YAGO 4.5 Turtle dump (streamed from
    the zip; single-line-fact reader). Pass collects allow-listed edges into memory
    (only a small fraction of the dump) and, when `type_seeds` classes are given,
    records their instances -- YAGO entity IRIs are opaque (e.g. `yago:X_Q123`), so
    type-seeding (all `rdf:type <class>` subjects) is more robust than guessing IRIs.
    A bounded in-memory BFS from seeds ∪ typed instances then emits allow-listed edges
    among the frontier. Person/org predicates are dropped by the whitelist (Level-0).
    """
    al = load_allowlist("yago")
    type_set = set(type_seeds)
    adj: Dict[str, List[Tuple[str, str, bool]]] = {}
    typed: Set[str] = set()
    kept_edges = 0
    for s, p, o, is_lit in iter_single_line_facts(_yago_zip_lines(zip_path, inner_name)):
        pc = al.curie_of(p)
        if not al.allows(pc):
            continue                                   # Level-0 whitelist at read time
        adj.setdefault(s, []).append((p, o, is_lit))
        kept_edges += 1
        if pc == "rdf:type" and o in type_set:
            typed.add(s)

    # bounded BFS from explicit seeds + class instances
    frontier: Set[str] = set(seeds) | set(sorted(typed)[:max_frontier])
    seen: Set[str] = set()
    for _hop in range(hop_cap):
        wave = sorted(n for n in frontier if n not in seen)
        if not wave or len(frontier) >= max_frontier:
            break
        for node in wave:
            seen.add(node)
            for (p, o, is_lit) in adj.get(node, ()):
                if not is_lit and len(frontier) < max_frontier:
                    frontier.add(o)

    kept: List[str] = []
    for node in sorted(frontier):
        for (p, o, is_lit) in adj.get(node, ()):
            kept.append(f"<{node}> <{p}> <{o}> ." if not is_lit
                        else f'<{node}> <{p}> "{o}" .')
    body = "\n".join(kept) + ("\n" if kept else "")
    cache.store("yago", f"dump-stream domain={domain} seeds={sorted(seeds)[:3]}",
                body, url=os.path.basename(zip_path))
    return {"source": "yago", "domain": domain, "allowlisted_edges_in_dump": kept_edges,
            "frontier": len(frontier), "cached_edges": _cached_edge_count(cache, al)}
