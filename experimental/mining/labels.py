"""
E1 -- resolve a Wikidata class's English label, for the "classify a sample of
novel mined constraints by hand" step. Goes through the project's OWN
`PoliteFetcher` (rate-limited, retried) via a CONSTRUCT query + the project's own
N-Triples parser -- not a bespoke urllib call -- so this stays inside "the
existing cached, rate-limited fetch layer" the sprint's isolation rule requires.
Cached in its own file under data/raw/mining/ (a new, sprint-scoped cache
generation, deliberately separate from data/raw/plausibility/'s D6/D7 cache).
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from kgrepair.ntriples import iter_triples          # noqa: E402
from kgrepair.pipeline.fetch import PoliteFetcher   # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
CACHE_PATH = os.path.join(ROOT, "data", "raw", "mining", "label_cache.json")
ENDPOINT = "https://query.wikidata.org/sparql"


def _load_cache() -> Dict[str, str]:
    if not os.path.exists(CACHE_PATH):
        return {}
    with open(CACHE_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _save_cache(cache: Dict[str, str]) -> None:
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=2, sort_keys=True)


def resolve_labels(curies: List[str], *, fetcher: PoliteFetcher) -> Dict[str, str]:
    """wd:Qxxx -> English label, cached. Only issues a request for curies not
    already cached; one batched CONSTRUCT covers every uncached curie."""
    cache = _load_cache()
    todo = sorted({c for c in curies if c not in cache})
    if todo:
        values = " ".join(todo)
        query = (
            'PREFIX wd: <http://www.wikidata.org/entity/>\n'
            'PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n'
            'CONSTRUCT { ?class rdfs:label ?label }\n'
            'WHERE {\n'
            f'  VALUES ?class {{ {values} }}\n'
            '  ?class rdfs:label ?label .\n'
            '  FILTER(LANG(?label) = "en")\n'
            '}')
        body = fetcher.sparql_construct(ENDPOINT, query)
        for s, _p, _o_node, o_lit in iter_triples(body.splitlines()):
            if o_lit is not None:
                curie = "wd:" + s.rsplit("/", 1)[-1]
                cache[curie] = o_lit
        for c in todo:
            cache.setdefault(c, "(no English label found)")
        _save_cache(cache)
    return {c: cache.get(c, "(not resolved)") for c in curies}
